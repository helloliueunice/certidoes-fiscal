"""Cliente da API Consulta CND (Conecta gov.br / Receita Federal).

Fontes: catálogo https://www.gov.br/conecta/catalogo/apis/consultar-certidao-negativa-de-debito
e o manual Documentacao_API_CND.pdf (consultados em 27/10/2026).

O uso exige adesão formal do órgão ao Conecta gov.br (ver docs/adesao_conecta.md) e liberação
do IP de saída do servidor. Sem configuração, `configurado()` retorna False e o app segue
funcionando no modo manual.

Configuração só por variáveis de ambiente:
  CONECTA_CLIENT_ID, CONECTA_CLIENT_SECRET   credencial gerada na Plataforma Conecta
  CONECTA_AMBIENTE                           "homologacao" ou "producao" (padrão: producao)
  CONECTA_CPF_USUARIO                        opcional; enviado no header x-cpf-usuario se definido

Segredos nunca são registrados em log nem devolvidos no resultado.
"""
from __future__ import annotations

import base64
import binascii
import logging
import os
import time
from datetime import date, datetime
from pathlib import Path
from typing import Any, Optional

import requests

from .models import so_digitos

log = logging.getLogger(__name__)

TIMEOUT = (10, 30)  # (conexão, leitura) em segundos

AMBIENTES: dict[str, dict[str, str]] = {
    "producao": {
        "token": "https://apigateway.conectagov.estaleiro.serpro.gov.br/oauth2/jwt-token",
        "base": "https://apigateway.conectagov.estaleiro.serpro.gov.br/api-cnd",
    },
    "homologacao": {
        # CONFIRMAR NA DOCUMENTAÇÃO: o catálogo traz duas URLs de token de homologação
        # (esta e https://apigateway.conectagov.estaleiro.serpro.gov.br/oauth2/jwt-token).
        "token": "https://h-apigateway.conectagov.np.estaleiro.serpro.gov.br/oauth2/jwt-token",
        "base": "https://apigateway.conectagov.estaleiro.serpro.gov.br/api-cnd-hom",
    },
}
CAMINHO_CONSULTA = "/v1/ConsultaCnd/certidao"  # confirmado no catálogo (POST)

# Corpo da requisição (confirmado no manual):
TIPO_CONTRIBUINTE_PJ = 1          # 1=PJ, 2=PF, 3=Imóvel rural
CODIGO_IDENTIFICACAO_PJ = "9201"  # 9201=PJ, 9202=PF, 9203=Imóvel rural

# Códigos de Status da resposta (confirmados no manual).
STATUS: dict[int, str] = {
    1: "Certidão encontrada",
    2: "Certidão emitida",
    3: "Certidão não emitida",
    4: "Certidão não emitida — situação cadastral impeditiva",
    5: "Análise inconsistente; tente novamente",
    6: "Base de apoio indisponível; tente novamente",
    7: "Em processamento; repetir com a Chave",
    8: "Contribuinte não cadastrado",
    9: "Parâmetros inválidos ou ausentes",
    10: "Tipo de contribuinte inválido",
    11: "Número do contribuinte inválido",
    12: "Código de identificação inválido",
    13: "Chave inválida ou expirada",
    14: "Chave não encontrada; repetir sem a Chave",
    15: "Chave informada para Imóvel Rural",
    99: "Erro no servidor",
}
STATUS_COM_CERTIDAO = {1, 2}
STATUS_REPETIR = {5, 6, 7}

MAX_TENTATIVAS_STATUS7 = 5
ESPERA_STATUS7_S = 1.0  # o manual pede no mínimo 500 ms entre repetições


def _ambiente() -> str:
    amb = (os.environ.get("CONECTA_AMBIENTE") or "producao").strip().lower()
    return amb if amb in AMBIENTES else "producao"


def configurado() -> bool:
    """True quando há credencial Conecta nas variáveis de ambiente."""
    return bool(os.environ.get("CONECTA_CLIENT_ID") and os.environ.get("CONECTA_CLIENT_SECRET"))


def _erro(mensagem: str, status: Optional[int] = None, bruto: Any = None) -> dict:
    return {"ok": False, "status": status, "mensagem": mensagem, "validade": None, "emissao": None,
            "codigo_controle": None, "caminho_pdf": None, "bruto": bruto}


def _obter_token(sessao: requests.Session) -> str:
    """Obtém o token JWT do gateway.

    CONFIRMAR NA DOCUMENTAÇÃO: o manual confirma apenas o Content-Type
    application/x-www-form-urlencoded na requisição do token. O uso de HTTP Basic
    (client_id:client_secret) com grant_type=client_credentials segue o padrão OAuth2
    do gateway e deve ser conferido no Swagger/roteiro de credenciais.
    """
    cid = os.environ["CONECTA_CLIENT_ID"]
    segredo = os.environ["CONECTA_CLIENT_SECRET"]
    resp = sessao.post(
        AMBIENTES[_ambiente()]["token"],
        data={"grant_type": "client_credentials"},  # CONFIRMAR NA DOCUMENTAÇÃO
        auth=(cid, segredo),                         # CONFIRMAR NA DOCUMENTAÇÃO
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=TIMEOUT,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"Falha ao obter token do Conecta (HTTP {resp.status_code}).")
    token = (resp.json() or {}).get("access_token")  # CONFIRMAR NA DOCUMENTAÇÃO (nome do campo)
    if not token:
        raise RuntimeError("Resposta do token sem access_token.")
    return token


def _data(valor: Any) -> Optional[date]:
    if not valor:
        return None
    texto = str(valor).strip()
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d", "%Y-%m-%dT%H:%M:%S.%f"):
        try:
            return datetime.strptime(texto[:26], fmt).date()
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(texto).date()
    except ValueError:
        return None


def _salvar_pdf(b64: str, destino: str, cnpj: str) -> str:
    caminho = Path(destino)
    if caminho.suffix.lower() != ".pdf":
        caminho.mkdir(parents=True, exist_ok=True)
        caminho = caminho / f"cnd_federal_{cnpj}_{date.today():%Y%m%d}.pdf"
    else:
        caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_bytes(base64.b64decode(b64, validate=False))
    return str(caminho)


def _sem_pdf(dados: dict) -> dict:
    """Cópia da resposta sem o base64 do PDF (para guardar em 'bruto')."""
    copia = dict(dados)
    if isinstance(copia.get("Certidao"), dict) and copia["Certidao"].get("DocumentoPdf"):
        cert = dict(copia["Certidao"])
        cert["DocumentoPdf"] = f"<base64 omitido: {len(cert['DocumentoPdf'])} caracteres>"
        copia["Certidao"] = cert
    return copia


def consultar_cnd(cnpj: str, salvar_pdf_em: str | None = None) -> dict:
    """Consulta a CND federal (RFB/PGFN) de um CNPJ pela API Consulta CND.

    Retorna {ok, status, mensagem, validade, emissao, codigo_controle, caminho_pdf, bruto}.
    `salvar_pdf_em` pode ser uma pasta ou um caminho terminado em .pdf.
    Erros nunca levantam exceção: viram {ok: False, mensagem}.
    """
    if not configurado():
        return _erro("API Conecta não configurada (defina CONECTA_CLIENT_ID e CONECTA_CLIENT_SECRET).")
    digitos = so_digitos(cnpj)
    if len(digitos) != 14:
        return _erro("CNPJ inválido: informe 14 dígitos.")

    url = AMBIENTES[_ambiente()]["base"] + CAMINHO_CONSULTA
    corpo: dict[str, Any] = {
        "TipoContribuinte": TIPO_CONTRIBUINTE_PJ,
        "ContribuinteConsulta": digitos,
        "CodigoIdentificacao": CODIGO_IDENTIFICACAO_PJ,
        "GerarCertidaoPdf": bool(salvar_pdf_em),
    }
    try:
        with requests.Session() as sessao:
            token = _obter_token(sessao)
            headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json",
                       "Accept": "application/json"}
            cpf = so_digitos(os.environ.get("CONECTA_CPF_USUARIO"))
            if cpf:
                # CONFIRMAR NA DOCUMENTAÇÃO: o header x-cpf-usuario não aparece na
                # documentação da API CND consultada; só é enviado se configurado.
                headers["x-cpf-usuario"] = cpf

            dados: dict = {}
            for tentativa in range(MAX_TENTATIVAS_STATUS7):
                resp = sessao.post(url, json=corpo, headers=headers, timeout=TIMEOUT)
                if resp.status_code in (401, 403, 415, 504):
                    motivo = {401: "token inválido/expirado ou limite do plano",
                              403: "IP do servidor não liberado no Conecta",
                              415: "tipo de mídia não suportado",
                              504: "tempo esgotado no gateway"}[resp.status_code]
                    return _erro(f"Conecta recusou a consulta (HTTP {resp.status_code}: {motivo}).")
                try:
                    dados = resp.json() or {}
                except ValueError:
                    return _erro(f"Resposta não JSON do Conecta (HTTP {resp.status_code}).")
                status = dados.get("Status")
                if status == 7 and dados.get("Chave"):
                    corpo["Chave"] = dados["Chave"]  # sempre a chave mais recente
                    time.sleep(ESPERA_STATUS7_S)
                    continue
                break
    except requests.RequestException as exc:
        log.warning("Falha de rede na consulta ao Conecta: %s", type(exc).__name__)
        return _erro(f"Falha de comunicação com o Conecta ({type(exc).__name__}).")
    except (RuntimeError, KeyError) as exc:
        return _erro(str(exc))

    status = dados.get("Status")
    mensagem = dados.get("Mensagem") or STATUS.get(status, "Status desconhecido")
    bruto = _sem_pdf(dados)
    cert = dados.get("Certidao") or {}
    if status not in STATUS_COM_CERTIDAO or not cert:
        return _erro(f"{STATUS.get(status, 'Sem certidão')}: {mensagem}", status, bruto)

    caminho_pdf = None
    if salvar_pdf_em and cert.get("DocumentoPdf"):
        try:
            caminho_pdf = _salvar_pdf(cert["DocumentoPdf"], salvar_pdf_em, digitos)
        except (binascii.Error, OSError, ValueError) as exc:
            mensagem = f"{mensagem} (PDF não salvo: {type(exc).__name__})"

    return {
        "ok": True,
        "status": status,
        "mensagem": mensagem,
        "validade": _data(cert.get("DataValidade")),
        "emissao": _data(cert.get("DataEmissao")),
        "codigo_controle": cert.get("CodigoControle"),
        "caminho_pdf": caminho_pdf,
        "bruto": bruto,
    }
