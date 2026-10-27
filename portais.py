"""Catálogo de portais oficiais de emissão e verificação de certidões (data/portais.json).

Somente registra links. Portais com captcha são acessados manualmente pelo fiscal:
este módulo nunca automatiza acesso a esses sítios.
"""
from __future__ import annotations

import json
import unicodedata
from pathlib import Path
from typing import Any, Optional

CAMINHO_PADRAO = Path(__file__).resolve().parent.parent / "data" / "portais.json"

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


def _item(d: dict[str, Any], escopo: str) -> dict[str, Any]:
    item = dict(d)
    for campo in ("nome", "tipo", "url", "captcha", "observacao", "verificado_em", "url_verificacao"):
        item.setdefault(campo, None)
    item["escopo"] = escopo
    return item


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
    return resultado


def url_verificacao(tipo: str, uf: str | None = None, caminho: str | Path | None = None) -> str | None:
    """URL de conferência de autenticidade para o tipo de certidão (valor de TipoCertidao).

    Para "estadual" usa a UF; para os demais tipos procura entre os federais.
    Retorna a primeira `url_verificacao` preenchida, ou None.
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
    for d in candidatos:
        if d.get("tipo") == tipo and d.get("url_verificacao"):
            return d["url_verificacao"]
    return None
