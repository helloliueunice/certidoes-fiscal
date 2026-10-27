"""Fallback OPCIONAL de extração por LLM (Claude, via SDK Python da Anthropic).

Desligado por padrão. Só é usado quando:
  * CERTIDOES_IA=1,
  * ANTHROPIC_API_KEY definida, e
  * o pacote ``anthropic`` está instalado.

Somente o TEXTO extraído (truncado) é enviado, nunca o PDF. O resultado sempre sai com
``metodo="ia"``, confiança <= 0.7 e aviso de conferência manual. Qualquer erro -> None.
"""
from __future__ import annotations

import importlib.util
import json
import os
import re
from datetime import date
from typing import Any, Optional

from .models import Certidao, Situacao, TipoCertidao, cnpj_valido, so_digitos

MODELO_PADRAO = "claude-sonnet-5-5"
LIMITE_CARACTERES = 12_000
CONFIANCA_MAXIMA = 0.7
AVISO_IA = "Extraído por IA: conferir manualmente"
_UFS_VALIDAS = {
    "AC", "AL", "AP", "AM", "BA", "CE", "DF", "ES", "GO", "MA", "MT", "MS", "MG", "PA",
    "PB", "PR", "PE", "PI", "RJ", "RN", "RS", "RO", "RR", "SC", "SP", "SE", "TO",
}

_SISTEMA = (
    "Você extrai dados de certidões de regularidade fiscal/trabalhista brasileiras a partir do "
    "texto de um PDF. Responda APENAS com um objeto JSON, sem comentários nem markdown. "
    "Não invente: use null quando o dado não estiver no texto."
)

_INSTRUCAO = """Campos do JSON (exatamente estas chaves):
- "tipo": um de {tipos}
- "situacao": um de {situacoes}
  (negativa = sem débitos; positiva_efeito_negativa = débitos suspensos/parcelados;
   positiva = débitos exigíveis; regular = CRF do FGTS ou SICAF regular)
- "cnpj": CNPJ do contribuinte/empresa (não do órgão emissor), só dígitos, ou null
- "razao_social": string ou null
- "orgao_emissor": string ou null
- "uf": sigla da UF (2 letras) ou null
- "municipio": string ou null
- "data_emissao": "AAAA-MM-DD" ou null
- "validade": "AAAA-MM-DD" (data final de validade) ou null
- "codigo_controle": código de controle/autenticidade ou número da certidão, ou null
- "url_verificacao": URL para conferir autenticidade, ou null

Texto da certidão (arquivo "{arquivo}"):
<<<
{texto}
>>>"""


def habilitada() -> bool:
    if os.environ.get("CERTIDOES_IA") != "1":
        return False
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return False
    try:
        return importlib.util.find_spec("anthropic") is not None
    except (ImportError, ValueError):
        return False


def _json_da_resposta(texto: str) -> Optional[dict[str, Any]]:
    texto = texto.strip()
    texto = re.sub(r"^```(?:json)?\s*|\s*```$", "", texto)
    try:
        obj = json.loads(texto)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", texto, re.S)
        if not m:
            return None
        try:
            obj = json.loads(m.group(0))
        except json.JSONDecodeError:
            return None
    return obj if isinstance(obj, dict) else None


def _str(v: Any, maximo: int = 300) -> Optional[str]:
    if v is None or isinstance(v, (dict, list)):
        return None
    s = str(v).strip()
    return s[:maximo] if s and s.lower() not in ("null", "none") else None


def _data(v: Any) -> Optional[date]:
    s = _str(v, 20)
    if not s:
        return None
    try:
        return date.fromisoformat(s[:10])
    except ValueError:
        m = re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{4})", s)
        if m:
            try:
                return date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
            except ValueError:
                return None
    return None


def _para_certidao(obj: dict[str, Any], arquivo: str) -> Certidao:
    c = Certidao(arquivo=arquivo, metodo="ia")
    try:
        c.tipo = TipoCertidao(str(obj.get("tipo", "")).strip().lower())
    except ValueError:
        c.tipo = TipoCertidao.DESCONHECIDA
    try:
        c.situacao = Situacao(str(obj.get("situacao", "")).strip().lower())
    except ValueError:
        c.situacao = Situacao.INDETERMINADA
    cnpj = so_digitos(_str(obj.get("cnpj"), 30))
    c.cnpj = cnpj if len(cnpj) == 14 else None
    c.razao_social = _str(obj.get("razao_social"))
    c.orgao_emissor = _str(obj.get("orgao_emissor"))
    uf = (_str(obj.get("uf"), 2) or "").upper()
    c.uf = uf if uf in _UFS_VALIDAS and len(_str(obj.get("uf"), 10) or "") == 2 else None
    c.municipio = _str(obj.get("municipio"), 100)
    c.data_emissao = _data(obj.get("data_emissao"))
    c.validade = _data(obj.get("validade"))
    c.codigo_controle = _str(obj.get("codigo_controle"), 100)
    url = _str(obj.get("url_verificacao"), 300)
    c.url_verificacao = url if url and url.lower().startswith(("http://", "https://")) else None

    c.avisos.append(AVISO_IA)
    conf = CONFIANCA_MAXIMA
    if c.tipo == TipoCertidao.DESCONHECIDA:
        conf -= 0.3
    if c.situacao == Situacao.INDETERMINADA:
        conf -= 0.2
    if not c.validade:
        conf -= 0.1
        c.avisos.append("Data de validade não encontrada")
    if not c.cnpj:
        conf -= 0.1
        c.avisos.append("CNPJ não encontrado no PDF")
    elif not cnpj_valido(c.cnpj):
        conf -= 0.1
        c.avisos.append("CNPJ com dígito verificador inválido")
    c.confianca = round(max(0.0, min(CONFIANCA_MAXIMA, conf)), 2)
    return c


def extrair_com_ia(texto: str, arquivo: str = "") -> Optional[Certidao]:
    """Extrai a certidão via LLM. Nunca levanta exceção: em qualquer falha devolve None."""
    if not habilitada() or not (texto or "").strip():
        return None
    try:
        import anthropic  # import tardio: pacote opcional

        modelo = os.environ.get("CERTIDOES_IA_MODELO") or MODELO_PADRAO
        prompt = _INSTRUCAO.format(
            tipos=", ".join(t.value for t in TipoCertidao),
            situacoes=", ".join(s.value for s in Situacao),
            arquivo=arquivo,
            texto=texto[:LIMITE_CARACTERES],
        )
        cliente = anthropic.Anthropic(timeout=60.0, max_retries=1)
        resposta = cliente.messages.create(
            model=modelo,
            max_tokens=1024,
            system=_SISTEMA,
            messages=[{"role": "user", "content": prompt}],
        )
        conteudo = "".join(
            getattr(b, "text", "") for b in (resposta.content or []) if getattr(b, "type", "") == "text"
        )
        obj = _json_da_resposta(conteudo)
        if obj is None:
            return None
        c = _para_certidao(obj, arquivo)
        c.texto = texto
        return c
    except Exception:
        return None
