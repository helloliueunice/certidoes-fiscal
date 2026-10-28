"""Catálogo de portais oficiais de emissão e verificação de certidões (data/portais.json).

Somente registra links. Portais com captcha são acessados manualmente pelo fiscal:
este módulo nunca automatiza acesso a esses sítios.

Esquema v2 (docs/esquema_portais.md): cada item diz como o fiscal obtém a certidão de um
terceiro (`acesso`: captcha, govbr, certificado, livre ou desconhecido) e a `prioridade`
dentro do mesmo tipo. Itens antigos (v1) são tolerados: `acesso` é deduzido de `captcha`.
"""
from __future__ import annotations

import json
import unicodedata
from pathlib import Path
from typing import Any, Optional

CAMINHO_PADRAO = Path(__file__).resolve().parent.parent / "data" / "portais.json"

ACESSOS = ("captcha", "govbr", "certificado", "livre", "desconhecido")
_PRIORIDADE_PADRAO = 99
_ORDEM_TIPOS = ("federal", "fgts", "trabalhista", "sicaf", "estadual", "municipal", "outra")

_cache: dict[str, dict] = {}


def _normalizar(texto: str | None) -> str:
    """Minúsculas, sem acento e sem espaços extras (para comparar nomes de município/UF)."""
    sem_acento = unicodedata.normalize("NFKD", texto or "")
    sem_acento = "".join(c for c in sem_acento if not unicodedata.combining(c))
    return " ".join(sem_acento.lower().split())


def carregar(caminho: str | Path | None = None) -> dict:
    """Carrega o catálogo JSON (com cache por caminho)."""
    chave = str(Path(caminho) if caminho else CAMINHO_PADRAO)
    if chave not in _cache:
        with open(chave, encoding="utf-8") as f:
            _cache[chave] = json.load(f)
    return _cache[chave]


def limpar_cache() -> None:
    _cache.clear()


def ufs(caminho: str | Path | None = None) -> list[str]:
    """Siglas das UFs presentes no catálogo, em ordem alfabética."""
    return sorted(carregar(caminho).get("estaduais", {}).keys())


def acesso_de(d: dict[str, Any]) -> str:
    """Modo de acesso do item; para itens v1 (sem `acesso`) deduz de `captcha`.

    captcha True -> "captcha"; False -> "livre"; None/ausente -> "desconhecido".
    Valor inválido em `acesso` também vira "desconhecido".
    """
    acesso = d.get("acesso")
    if acesso in ACESSOS:
        return acesso
    if acesso is None:
        captcha = d.get("captcha")
        if captcha is True:
            return "captcha"
        if captcha is False:
            return "livre"
    return "desconhecido"


def _prioridade(d: dict[str, Any]) -> int:
    p = d.get("prioridade")
    return p if isinstance(p, int) and not isinstance(p, bool) else _PRIORIDADE_PADRAO


def _item(d: dict[str, Any], escopo: str) -> dict[str, Any]:
    item = dict(d)
    for campo in ("nome", "tipo", "url", "captcha", "observacao", "verificado_em", "url_verificacao",
                  "nivel_govbr", "abrange_filiais", "certidao_unica", "validade_tipica_dias", "fonte"):
        item.setdefault(campo, None)
    item["acesso"] = acesso_de(d)
    if "captcha" not in d or d.get("captcha") is None:
        # mantém `captcha` coerente com `acesso` (compatibilidade com quem só lê `captcha`)
        item["captcha"] = {"captcha": True, "desconhecido": None}.get(item["acesso"], False)
    item["prioridade"] = _prioridade(d)
    item["escopo"] = escopo
    return item


def _chave_ordem(item: dict[str, Any]) -> tuple:
    tipo = item.get("tipo") or ""
    pos = _ORDEM_TIPOS.index(tipo) if tipo in _ORDEM_TIPOS else len(_ORDEM_TIPOS)
    return (pos, item["prioridade"])


def _municipais(catalogo: dict, uf: str, municipio: str) -> Optional[list[dict]]:
    alvo_uf = _normalizar(uf)
    alvo_mun = _normalizar(municipio)
    for chave, itens in catalogo.get("municipais", {}).items():
        uf_cat, _, mun_cat = chave.partition("/")
        if _normalizar(uf_cat) == alvo_uf and _normalizar(mun_cat) == alvo_mun:
            return itens
    return None


def portais_para(uf: str, municipio: str, caminho: str | Path | None = None) -> list[dict]:
    """Federais + estaduais da UF + municipais do município ("UF/Município").

    A comparação ignora acentos e maiúsculas. Se o município não estiver catalogado,
    devolve um item indicando que o portal precisa ser cadastrado.
    A lista vem ordenada por tipo (federal, fgts, trabalhista, sicaf, estadual, municipal,
    outra) e, dentro do tipo, por `prioridade` (ordenação estável: empate mantém a ordem
    do catálogo). Cada item traz `acesso` e `prioridade` mesmo se o JSON for v1.
    """
    catalogo = carregar(caminho)
    resultado = [_item(d, "federal") for d in catalogo.get("federais", [])]

    sigla = (uf or "").strip().upper()
    for d in catalogo.get("estaduais", {}).get(sigla, []):
        resultado.append(_item(d, "estadual"))

    municipais = _municipais(catalogo, sigla, municipio)
    if municipais:
        resultado.extend(_item(d, "municipal") for d in municipais)
    else:
        nome_mun = (municipio or "").strip() or "(município não informado)"
        resultado.append(_item({
            "id": None,
            "nome": f"Prefeitura de {nome_mun} — portal não catalogado",
            "tipo": "municipal",
            "orgao": f"Prefeitura de {nome_mun}",
            "url": None,
            "captcha": None,
            "observacao": "Cadastre o portal desta prefeitura em data/portais.json",
            "verificado_em": None,
        }, "municipal"))
    resultado.sort(key=_chave_ordem)
    return resultado


def _e_verificacao(d: dict[str, Any]) -> bool:
    return "verificacao" in (d.get("id") or "")


def melhor_rota(tipo: Any, uf: str | None = None, municipio: str | None = None,
                caminho: str | Path | None = None) -> dict | None:
    """Melhor portal para emitir/consultar a certidão do `tipo` (valor de TipoCertidao).

    Entre os itens do tipo (federais; estaduais da UF; municipais do município), ignora os
    de verificação de autenticidade e os sem URL, prefere `acesso != "captcha"` e, depois,
    a menor `prioridade`. "desconhecido" não é tratado como captcha, mas perde para rotas
    confirmadas sem captcha (govbr, certificado, livre). Retorna None se não houver item.
    """
    tipo = getattr(tipo, "value", tipo)
    catalogo = carregar(caminho)
    if tipo == "estadual":
        brutos = catalogo.get("estaduais", {}).get((uf or "").strip().upper(), [])
        escopo = "estadual"
    elif tipo == "municipal":
        brutos = _municipais(catalogo, (uf or "").strip().upper(), municipio or "") or []
        escopo = "municipal"
    else:
        brutos = catalogo.get("federais", [])
        escopo = "federal"
    candidatos = [_item(d, escopo) for d in brutos
                  if d.get("tipo") == tipo and d.get("url") and not _e_verificacao(d)]
    if not candidatos:
        return None

    def chave(item: dict) -> tuple:
        acesso = item["acesso"]
        grupo = 2 if acesso == "captcha" else (1 if acesso == "desconhecido" else 0)
        return (grupo, item["prioridade"])

    return min(candidatos, key=chave)


def resumo_acesso(caminho: str | Path | None = None) -> dict:
    """Contagem de itens por modo de acesso, para documentação.

    Retorna {"total": n, "por_acesso": {acesso: n, ...}, "por_escopo": {escopo: {acesso: n}}}
    com todas as chaves de ACESSOS presentes (zero quando não houver itens).
    """
    catalogo = carregar(caminho)
    grupos = {
        "federal": list(catalogo.get("federais", [])),
        "estadual": [d for itens in catalogo.get("estaduais", {}).values() for d in itens],
        "municipal": [d for itens in catalogo.get("municipais", {}).values() for d in itens],
    }
    por_escopo = {}
    total = {a: 0 for a in ACESSOS}
    for escopo, itens in grupos.items():
        cont = {a: 0 for a in ACESSOS}
        for d in itens:
            cont[acesso_de(d)] += 1
        por_escopo[escopo] = cont
        for a, n in cont.items():
            total[a] += n
    return {"total": sum(total.values()), "por_acesso": total, "por_escopo": por_escopo}


def url_verificacao(tipo: str, uf: str | None = None, caminho: str | Path | None = None) -> str | None:
    """URL de conferência de autenticidade para o tipo de certidão (valor de TipoCertidao).

    Para "estadual" usa a UF; para os demais tipos procura entre os federais.
    Retorna a `url_verificacao` preenchida do item de menor `prioridade` (empate: ordem do
    catálogo), ou None.
    """
    tipo = getattr(tipo, "value", tipo)
    catalogo = carregar(caminho)
    if tipo == "estadual":
        candidatos = catalogo.get("estaduais", {}).get((uf or "").strip().upper(), [])
    elif tipo == "municipal":
        candidatos = []
        alvo = _normalizar(uf)
        for chave, itens in catalogo.get("municipais", {}).items():
            if _normalizar(chave.partition("/")[0]) == alvo:
                candidatos.extend(itens)
    else:
        candidatos = catalogo.get("federais", [])
    for d in sorted(candidatos, key=_prioridade):
        if d.get("tipo") == tipo and d.get("url_verificacao"):
            return d["url_verificacao"]
    return None
