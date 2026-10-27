"""Ponte para a versão que roda no navegador (Pyodide).

A página extrai o texto dos PDFs no próprio navegador (pdf.js) e chama estas funções com JSON.
Nada sai do computador de quem usa: não há servidor. As regras são as mesmas de extrator.py e
validador.py (fonte única da verdade, coberta pelos testes).
"""
from __future__ import annotations

import html
import json
import os
import tempfile
from datetime import date
from typing import Any, Optional

from . import planejamento
from .atesto import CHECKLIST_MANUAL, AVISO_RODAPE, _minuta, gerar_csv, validade_item
from .extrator import ler_texto
from .models import (
    Certidao,
    Contrato,
    TipoCertidao,
    cnpj_valido,
    formatar_cnpj,
    so_digitos,
)
from .validador import (
    ROTULO_SEMAFORO,
    ROTULO_SITUACAO,
    alerta_extra,
    formatar_data,
    nota_extra,
    resumo,
    validar,
)

TIPOS_EXIGIVEIS = [TipoCertidao.FEDERAL, TipoCertidao.FGTS, TipoCertidao.TRABALHISTA,
                   TipoCertidao.ESTADUAL, TipoCertidao.MUNICIPAL, TipoCertidao.SICAF]
MAX_ARQUIVOS = 20
MAX_CARACTERES = 400_000   # texto extraído por arquivo


def _json(obj: Any) -> str:
    def padrao(o):
        if isinstance(o, date):
            return o.isoformat()
        if hasattr(o, "value"):
            return o.value
        return str(o)
    return json.dumps(obj, default=padrao, ensure_ascii=False)


def _hoje(dados: dict) -> date:
    try:
        return date.fromisoformat(str(dados.get("hoje") or ""))
    except ValueError:
        return date.today()


def _cert_dict(c: Certidao) -> dict:
    return {
        "arquivo": c.arquivo,
        "tipo": c.tipo.value,
        "rotulo": c.tipo.rotulo,
        "situacao": ROTULO_SITUACAO[c.situacao],
        "cnpj": formatar_cnpj(c.cnpj) if c.cnpj else "",
        "razao_social": c.razao_social or "",
        "orgao_emissor": c.orgao_emissor or "",
        "uf_municipio": " / ".join(x for x in (c.uf, c.municipio) if x),
        "emissao": formatar_data(c.data_emissao),
        "validade": formatar_data(c.validade),
        "codigo_controle": c.codigo_controle or "",
        "url_verificacao": c.url_verificacao or "",
        "metodo": "IA" if c.metodo == "ia" else "Regras",
        "confianca": round(c.confianca * 100),
        "avisos": list(c.avisos),
    }


def validar_contrato(dados: dict) -> list[str]:
    """Erros de preenchimento, em português (lista vazia = ok)."""
    erros = []
    if not str(dados.get("numero", "")).strip():
        erros.append("Informe o número do contrato.")
    if not cnpj_valido(so_digitos(dados.get("cnpj"))):
        erros.append("CNPJ inválido: confira os dígitos.")
    if not str(dados.get("razao_social", "")).strip():
        erros.append("Informe a razão social da contratada.")
    if not str(dados.get("municipio", "")).strip():
        erros.append("Informe o município da sede.")
    if not [t for t in TIPOS_EXIGIVEIS if t.value in (dados.get("exigidas") or [])]:
        erros.append("Marque ao menos uma certidão exigida.")
    return erros


def conferir(entrada_json: str) -> str:
    """Entrada: {"contrato": {...}, "arquivos": [{"nome", "texto"}], "hoje"?: "aaaa-mm-dd"}."""
    dados = json.loads(entrada_json)
    ct = dados.get("contrato") or {}
    arquivos = dados.get("arquivos") or []
    erros = validar_contrato(ct)
    if not arquivos:
        erros.append("Envie ao menos um PDF de certidão.")
    if len(arquivos) > MAX_ARQUIVOS:
        erros.append(f"Envie no máximo {MAX_ARQUIVOS} arquivos por vez.")
    if erros:
        return _json({"ok": False, "erros": erros})

    hoje = _hoje(dados)
    try:
        dias_alerta = max(0, min(int(ct.get("dias_alerta", 15)), 90))
    except (TypeError, ValueError):
        dias_alerta = 15
    certs = []
    for a in arquivos:
        nome = os.path.basename(str(a.get("nome") or "arquivo.pdf"))[:200]
        if a.get("erro"):
            c = Certidao(arquivo=nome)
            c.avisos.append(f"Não foi possível ler o PDF ({a['erro']}): conferir manualmente")
        else:
            c = ler_texto(str(a.get("texto") or "")[:MAX_CARACTERES], nome)
        c.texto = ""
        certs.append(c)

    contrato = Contrato(
        numero=str(ct["numero"]).strip()[:60], cnpj=so_digitos(ct["cnpj"]),
        razao_social=str(ct["razao_social"]).strip()[:200],
        uf_sede=str(ct.get("uf") or "DF")[:2], municipio_sede=str(ct["municipio"]).strip()[:120],
        fiscal=str(ct.get("fiscal") or "").strip()[:120],
        competencia=str(ct.get("competencia") or "").strip()[:20],
        exigidas=[t for t in TIPOS_EXIGIVEIS if t.value in ct.get("exigidas", [])],
        aceitar_sicaf=bool(ct.get("aceitar_sicaf")),
    )
    r = validar(contrato, certs, hoje=hoje, dias_alerta=dias_alerta)
    orgao = str(ct.get("orgao") or "").strip()[:200]

    itens = []
    for i in r.itens:
        c = i.certidao
        v = validade_item(i)
        itens.append({
            "tipo": i.tipo.value, "rotulo": i.tipo.rotulo, "semaforo": i.semaforo.value,
            "resultado": ROTULO_SEMAFORO[i.semaforo],
            "situacao": ROTULO_SITUACAO[c.situacao] if c else "—",
            "validade": formatar_data(v) if v else "—",
            "mensagem": i.mensagem,
            "codigo_controle": (c.codigo_controle or "—") if c else "—",
            "arquivo": c.arquivo if c else "—",
            "url_verificacao": (c.url_verificacao or "") if c else "",
        })
    extras = [{"arquivo": x.arquivo, "rotulo": x.tipo.rotulo, "nota": nota_extra(x, r),
               "alerta": bool(alerta_extra(x, r))} for x in r.extras]

    titulo, pars = _minuta(r, orgao)
    pasta = tempfile.mkdtemp(prefix="controle_")
    caminho = gerar_csv([r], os.path.join(pasta, "controle.csv"))
    with open(caminho, encoding="utf-8-sig") as f:
        csv_texto = f.read()
    try:
        os.remove(caminho)
        os.rmdir(pasta)
    except OSError:
        pass

    grupo = planejamento.grupo_de_resultado(r)
    solicitacao = None
    if grupo["a_emitir"]:
        solicitacao = {"assunto": planejamento.assunto_solicitacao(grupo),
                       "texto": planejamento.texto_solicitacao(grupo, orgao=orgao)}

    num = so_digitos(contrato.numero) or "contrato"
    comp = (contrato.competencia or "").replace("/", "-") or hoje.isoformat()
    return _json({
        "ok": True,
        "contrato": {"numero": contrato.numero, "cnpj": formatar_cnpj(contrato.cnpj),
                     "razao_social": contrato.razao_social, "uf": contrato.uf_sede,
                     "municipio": contrato.municipio_sede, "fiscal": contrato.fiscal,
                     "competencia": contrato.competencia, "orgao": orgao,
                     "observacoes": str(ct.get("observacoes") or "").strip()[:2000]},
        "data_referencia": formatar_data(r.data_referencia),
        "apto": r.apto_atesto, "resumo": resumo(r), "itens": itens, "extras": extras,
        "certidoes": [_cert_dict(c) for c in certs],
        "minuta": {"titulo": titulo, "paragrafos": [html.unescape(p) for p in pars]},
        "checklist_manual": CHECKLIST_MANUAL, "aviso_rodape": AVISO_RODAPE,
        "csv": csv_texto, "solicitacao": solicitacao,
        "nome_base": f"checklist_{num}_{comp}",
    })


def planejar_mes(entrada_json: str) -> str:
    """Entrada: {"csvs": [texto], "ate": "aaaa-mm-dd", "orgao", "prazo", "aceitar_sicaf"}."""
    dados = json.loads(entrada_json)
    erros = []
    hoje = _hoje(dados)
    try:
        ate = date.fromisoformat(str(dados.get("ate") or ""))
    except ValueError:
        ate = planejamento.data_corte_padrao(hoje)
        erros.append("Data de corte inválida.")
    try:
        prazo = max(1, min(int(dados.get("prazo") or 5), 60))
    except (TypeError, ValueError):
        prazo = 5
    csvs = [str(t) for t in (dados.get("csvs") or [])][:50]
    if not csvs:
        erros.append("Envie ao menos uma planilha de controle (CSV) gerada pelo sistema.")
    linhas = planejamento.ler_csvs([t.encode("utf-8") for t in csvs]) if not erros else []
    if not erros and not linhas:
        erros.append("Nenhuma linha válida encontrada. Use a planilha de controle (CSV) baixada "
                     "na página de resultado da conferência.")
    if erros:
        return _json({"ok": False, "erros": erros})
    orgao = str(dados.get("orgao") or "").strip()[:200]
    grupos = planejamento.planejar(linhas, ate=ate, hoje=hoje,
                                   aceitar_sicaf=bool(dados.get("aceitar_sicaf")))
    for g in grupos:
        g["solicitacao"] = planejamento.texto_solicitacao(g, prazo_dias=prazo, orgao=orgao)
        g["assunto"] = planejamento.assunto_solicitacao(g)
    return _json({"ok": True, "ate": formatar_data(ate), "ate_iso": ate.isoformat(),
                  "grupos": grupos, "totais": planejamento.totalizar(grupos),
                  "csv": planejamento.csv_plano(grupos)})


def portais(uf: str, municipio: str, tipos_json: str = "[]", sicaf: bool = False) -> str:
    from . import portais as _p
    try:
        lista = _p.portais_para(uf, municipio or "")
    except Exception:
        return _json([])
    filtro = set(json.loads(tipos_json or "[]"))
    saida = []
    for p in lista:
        tipo = p.get("tipo", "")
        if filtro and tipo not in filtro and tipo != "outra":
            continue
        try:
            rotulo = TipoCertidao(tipo).rotulo
        except ValueError:
            rotulo = tipo
        saida.append({"nome": p.get("nome"), "tipo": tipo, "rotulo": rotulo, "url": p.get("url"),
                      "captcha": p.get("captcha"), "observacao": p.get("observacao"),
                      "verificado_em": p.get("verificado_em"),
                      "destaque": bool(sicaf and tipo == "sicaf")})
    if sicaf:
        saida.sort(key=lambda x: not x["destaque"])
    return _json(saida)


def data_corte_padrao(hoje_iso: Optional[str] = None) -> str:
    try:
        hoje = date.fromisoformat(hoje_iso) if hoje_iso else date.today()
    except ValueError:
        hoje = date.today()
    return planejamento.data_corte_padrao(hoje).isoformat()
