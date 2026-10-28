"""Leitura de PDFs de certidões: PDF -> texto -> Certidao.

Regras determinísticas e auditáveis, um bloco por emissor. A IA (``ia.py``) só é
chamada como fallback opcional quando as regras não identificam o tipo ou a situação.

Fluxo:
    extrair_texto(pdf) -> texto bruto
    ler_texto(texto)   -> normaliza (sem acento, maiúsculas, espaços colapsados),
                          identifica o emissor, aplica as regras e calcula confiança.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Callable, Iterable, Optional

from .models import Certidao, Situacao, TipoCertidao, cnpj_valido, formatar_cnpj, so_digitos

__all__ = [
    "extrair_texto",
    "ler_texto",
    "ler_pdf",
    "ler_varios",
    "abrange_raiz",
    "e_estadual_unica",
    "ORGAO_UNICA",
    "URL_SIDEB",
    "AVISO_ESCANEADO",
    "AVISO_MULTIPLAS",
]

AVISO_ESCANEADO = "PDF sem texto (provavelmente escaneado): conferir manualmente"
AVISO_MULTIPLAS = "arquivo contém mais de uma certidão; separe os arquivos"

URL_FEDERAL = "https://servicos.receitafederal.gov.br/servico/certidoes/"
URL_FGTS = "https://consulta-crf.caixa.gov.br/"
URL_TST = "https://www.tst.jus.br/certidao1"
# SP: Certidão Única (Sefaz + PGE) pelo SIDEB. Endereço informado ao projeto; a confirmar.
URL_SIDEB = "https://www4.fazenda.sp.gov.br/SIDEB/CertidaoNegativaDebitos"

# Convenção para certidão estadual ÚNICA (abrange débitos inscritos E não inscritos em dívida
# ativa, emitida em conjunto pela Fazenda e pela Procuradoria do Estado): orgao_emissor começa com
# "SEFAZ+PGE" seguido da UF ("SEFAZ+PGE-SP", "SEFAZ+PGE-RJ"; "SEFAZ+PGE" sem UF identificada).
# O validador usa esta marca (``e_estadual_unica``) para que ela satisfaça sozinha o item estadual.
ORGAO_UNICA = "SEFAZ+PGE"

# --------------------------------------------------------------------------------------
# Normalização
# --------------------------------------------------------------------------------------

_TROCAS = {"°": "O", "–": "-", "—": "-", "‐": "-", "‑": "-", "“": '"', "”": '"', "’": "'"}


@dataclass
class _Texto:
    """Texto normalizado com mapa de posições para o texto original.

    ``linhas`` preserva quebras de linha (colapsadas); ``plano`` é igual, mas com
    quebras trocadas por espaço — mesmo comprimento, mesmo mapa.
    """

    original: str
    linhas: str
    plano: str
    mapa: list[int]

    def original_de(self, ini: int, fim: int) -> str:
        if fim <= ini or ini >= len(self.mapa):
            return ""
        fim = min(fim, len(self.mapa))
        return self.original[self.mapa[ini]: self.mapa[fim - 1] + 1]

    def fatia(self, fim: int) -> "_Texto":
        return _Texto(self.original, self.linhas[:fim], self.plano[:fim], self.mapa[:fim])


def _normalizar(texto: str) -> _Texto:
    out: list[str] = []
    mapa: list[int] = []
    for i, c in enumerate(texto):
        if c in "\n\r\f\v\u2028\u2029":
            if not out:
                continue
            if out[-1] == "\n":
                continue
            if out[-1] == " ":
                out[-1] = "\n"
                mapa[-1] = i
            else:
                out.append("\n")
                mapa.append(i)
            continue
        if c.isspace():
            if out and out[-1] not in (" ", "\n"):
                out.append(" ")
                mapa.append(i)
            continue
        c = _TROCAS.get(c, c)
        d = "".join(x for x in unicodedata.normalize("NFKD", c) if not unicodedata.combining(x))
        for ch in d.upper():
            out.append(ch)
            mapa.append(i)
    while out and out[-1] in (" ", "\n"):
        out.pop()
        mapa.pop()
    linhas = "".join(out)
    return _Texto(texto, linhas, linhas.replace("\n", " "), mapa)


def _norm(s: str) -> str:
    return _normalizar(s).plano


# --------------------------------------------------------------------------------------
# Datas
# --------------------------------------------------------------------------------------

_MESES = {
    "JANEIRO": 1, "FEVEREIRO": 2, "MARCO": 3, "ABRIL": 4, "MAIO": 5, "JUNHO": 6,
    "JULHO": 7, "AGOSTO": 8, "SETEMBRO": 9, "OUTUBRO": 10, "NOVEMBRO": 11, "DEZEMBRO": 12,
}
_RE_DATA = re.compile(
    r"(?<![\d.])(?:(\d{1,2})\s?([/.\-])\s?(\d{1,2})\s?\2\s?(\d{4}|\d{2})"
    r"|(\d{1,2})\s?O?\s+DE\s+(" + "|".join(_MESES) + r")\s+DE\s+(\d{4}))(?![\d])"
)
_FILLER = re.compile(r"[\s:\-]*(?:(?:ATE|EM|DIA|NO DIA|O DIA|DE)\b\s*:?\s*){0,2}")


def _ano(s: str) -> int:
    a = int(s)
    return 2000 + a if len(s) == 2 else a


def _data_de(m: re.Match) -> Optional[date]:
    try:
        if m.group(1):
            d = date(_ano(m.group(4)), int(m.group(3)), int(m.group(1)))
        else:
            d = date(int(m.group(7)), _MESES[m.group(6)], int(m.group(5)))
    except (ValueError, KeyError):
        return None
    return d if 1990 <= d.year <= 2100 else None


def _data_em(texto: str, pos: int) -> tuple[Optional[date], int]:
    """Data que começa em ``pos`` (após pular preenchimento curto como ': ', 'em', 'até')."""
    f = _FILLER.match(texto, pos)
    p = f.end() if f else pos
    m = _RE_DATA.match(texto, p)
    if not m:
        return None, pos
    return _data_de(m), m.end()


def _data_ancora(texto: str, ancoras: Iterable[str]) -> Optional[date]:
    """Primeira data que segue imediatamente uma âncora (na ordem de prioridade das âncoras)."""
    for anc in ancoras:
        for m in re.finditer(anc, texto):
            d, _ = _data_em(texto, m.end())
            if d:
                return d
    return None


def _somar_meses(d: date, meses: int) -> date:
    m = d.month - 1 + meses
    ano, mes = d.year + m // 12, m % 12 + 1
    for dia in (d.day, 30, 29, 28):
        try:
            return date(ano, mes, dia)
        except ValueError:
            continue
    return d


_ANC_EMISSAO = [
    r"EMITIDA AS \d{1,2}:\d{2}(?::\d{2})?(?: HORAS)? DO DIA",
    r"INFORMACAO OBTIDA EM",
    r"DATA E HORA DA EMISSAO",
    r"DATA (?:DE |DA )?EMISSAO",
    r"\bEXPEDICAO",
    r"\bEMITID[AO] EM",
    r"\bEXPEDID[AO] EM",
    r"\bEMISSAO",
]
_ANC_VALIDADE = [
    r"\bVALID[AO] ATE",
    r"\bVALIDADE ATE",
    r"DATA DE VALIDADE",
    r"\bVALIDA(?: SOMENTE)? ATE",
    r"\bVALIDADE(?: DA CERTIDAO)?",
]
_NUM_EXTENSO = {
    "TRINTA": 30, "SESSENTA": 60, "NOVENTA": 90, "CENTO E VINTE": 120, "CENTO E OITENTA": 180,
    "DUZENTOS E SETENTA": 270, "TRES": 3, "SEIS": 6, "DOZE": 12,
}
_N_PRAZO = r"(\d{1,3}|" + "|".join(sorted(_NUM_EXTENSO, key=len, reverse=True)) + r")"
_RE_VALIDADE_REL = [
    re.compile(r"\bVALID[AO] (?:PELO PRAZO DE |POR )" + _N_PRAZO + r"\s*(?:\([^)]*\)\s*)?(DIAS|MESES)\b"),
    re.compile(r"\bVALIDADE\s*(?:DE|:|E DE)?\s*" + _N_PRAZO + r"\s*(?:\([^)]*\)\s*)?(DIAS|MESES)\b"),
]


def _validade_intervalo(texto: str) -> tuple[Optional[date], Optional[date]]:
    """'Validade: 06/10/2026 a 04/11/2026' -> (inicio, fim)."""
    for m in re.finditer(r"\bVALIDADE\s*:?\s*(?:DE\s*)?", texto):
        m1 = _RE_DATA.match(texto, m.end())
        if not m1:
            continue
        sep = re.compile(r"\s*(?:A|ATE|-)\s*").match(texto, m1.end())
        if not sep:
            continue
        m2 = _RE_DATA.match(texto, sep.end())
        if m2:
            return _data_de(m1), _data_de(m2)
    return None, None


_RE_BASE_PRAZO = re.compile(r"\s*,?\s*(?:A CONTAR|A PARTIR|CONTADOS?)\s+D[AEO]S?\b(?:\s+DATA)?")


def _validade_relativa(texto: str, emissao: Optional[date]) -> Optional[date]:
    """'válida por 180 dias' (a partir da emissão) ou '... 180 dias a contar de 01/10/2026'."""
    for rx in _RE_VALIDADE_REL:
        m = rx.search(texto)
        if not m:
            continue
        base = emissao
        b = _RE_BASE_PRAZO.match(texto, m.end())
        if b:
            d, _ = _data_em(texto, b.end())
            base = d or base
        if not base:
            return None
        n = int(m.group(1)) if m.group(1).isdigit() else _NUM_EXTENSO[m.group(1)]
        return base + timedelta(days=n) if m.group(2) == "DIAS" else _somar_meses(base, n)
    return None


# --------------------------------------------------------------------------------------
# CNPJ, razão social, código, URL
# --------------------------------------------------------------------------------------

_RE_CNPJ = re.compile(r"(?<![\d./])(\d{2}\.?\d{3}\.?\d{3}\s?/?\s?\d{4}\s?-?\s?\d{2})(?![\d])")
_RE_RAIZ = re.compile(r"\bCNPJ(?: BASE)?\s*(?:N[O.]+)?\s*:?\s*(\d{2}\.\d{3}\.\d{3})(?![\d./])")
_RE_ANCORA_CNPJ = re.compile(r"(CNPJ|INSCRICAO|INSCRIT[OA])[^\d\n]{0,30}$")
_RE_CONTRIB = re.compile(
    r"\b(NOME|RAZAO SOCIAL|CONTRIBUINTE|INTERESSAD[OA]|REQUERENTE|EMPREGADOR|FORNECEDOR|INSCRIT[OA]|EMPRESA)\b"
)
_RE_ORGAO = re.compile(
    r"\b(PREFEITURA|SECRETARIA|MINISTERIO|PROCURADORIA|TRIBUNAL|CAIXA ECONOMICA|RECEITA FEDERAL|"
    r"GOVERNO DO ESTADO|ORGAO EMISSOR)\b"
)
# CNPJs de órgãos emissores que podem aparecer no rodapé/cabeçalho
_CNPJ_ORGAOS = {"00360305000104", "00394460000141", "00509968000148", "46395000000139"}


def _cnpj(t: _Texto, c: Certidao) -> None:
    f = t.linhas  # mesmo comprimento de t.plano, mas preserva quebras de linha
    cands: list[tuple[float, int, str]] = []
    for m in _RE_CNPJ.finditer(f):
        dig = so_digitos(m.group(1))
        if len(dig) != 14:
            continue
        ini = m.start()
        antes = f[max(0, ini - 200): ini].replace("\n", " ")
        depois = f[m.end(): m.end() + 60].split("\n", 1)[0]  # só o resto da mesma linha
        score = 0.0
        if _RE_ANCORA_CNPJ.search(f[max(0, ini - 40): ini]):
            score += 2
        d_contrib = None
        ms = list(_RE_CONTRIB.finditer(antes))
        if ms:
            d_contrib = len(antes) - ms[-1].end()
        md = _RE_CONTRIB.search(depois)
        if md and (d_contrib is None or md.start() < d_contrib):
            d_contrib = md.start()
        d_orgao = None
        mo = list(_RE_ORGAO.finditer(antes[-150:]))
        if mo:
            d_orgao = len(antes[-150:]) - mo[-1].end()
            if "\n" not in f[max(0, ini - 150) + mo[-1].end(): ini]:
                score -= 2  # órgão citado na mesma linha do CNPJ
        if d_contrib is not None and (d_orgao is None or d_contrib < d_orgao):
            score += 3
        if d_orgao is not None and (d_contrib is None or d_orgao < d_contrib):
            score -= 3
        if dig in _CNPJ_ORGAOS:
            score -= 5
        if cnpj_valido(dig):
            score += 1
        cands.append((score, ini, dig))
    if cands:
        cands.sort(key=lambda x: (-x[0], x[1]))
        escolhido = cands[0][2]
        c.cnpj = escolhido
        outros = {d for s, _, d in cands if d != escolhido and s >= 2 and d not in _CNPJ_ORGAOS}
        if outros:
            c.avisos.append(
                "PDF cita mais de um CNPJ ("
                + ", ".join(formatar_cnpj(o) for o in sorted(outros))
                + f"); usado {formatar_cnpj(escolhido)}: conferir"
            )
        if not cnpj_valido(escolhido):
            c.avisos.append(f"CNPJ com dígito verificador inválido: {formatar_cnpj(escolhido)}")
        return
    m = _RE_RAIZ.search(t.plano)
    if m:
        c.avisos.append(
            f"PDF traz apenas a raiz do CNPJ ({m.group(1)}): conferir com o CNPJ do contrato"
        )


_RE_RAZAO = re.compile(
    r"\b(?:NOME/RAZAO SOCIAL|RAZAO SOCIAL|NOME EMPRESARIAL|NOME(?: DO CONTRIBUINTE| DA EMPRESA)?|"
    r"CONTRIBUINTE|INTERESSAD[OA]|EMPREGADOR)\s*:\s*([^\n]+)"
)
_RE_CORTE_RAZAO = re.compile(r"\s+(?:CNPJ|INSCRICAO|CPF|ENDERECO|CEP)\b.*$")


def _razao_social(t: _Texto, c: Certidao) -> None:
    for m in _RE_RAZAO.finditer(t.linhas):
        ini, fim = m.span(1)
        corte = _RE_CORTE_RAZAO.search(t.linhas, ini, fim)
        if corte:
            fim = corte.start()
        bruto = t.original_de(ini, fim).strip(" .,;:-\t")
        if sum(ch.isalpha() for ch in bruto) >= 3 and not re.fullmatch(r"[\d./\- ]+", bruto):
            c.razao_social = re.sub(r"\s+", " ", bruto)
            return


_RE_CODIGO = re.compile(
    r"(?:CODIGO DE (?:CONTROLE|AUTENTICIDADE|VERIFICACAO|AUTENTICACAO)(?: DA CERTIDAO)?|"
    r"CHAVE DE (?:AUTENTICIDADE|VALIDACAO|AUTENTICACAO)|CERTIFICACAO NUMERO|"
    r"NUMERO DA CERTIDAO|N[O.]+ DA CERTIDAO|CERTIDAO N[O.]+)\s*:?\s*([A-Z0-9][A-Z0-9.\-/]{2,}[A-Z0-9])"
)


def _codigo_generico(f: str) -> Optional[str]:
    for m in _RE_CODIGO.finditer(f):
        v = m.group(1)
        if any(ch.isdigit() for ch in v):
            return v
    return None


_RE_URL = re.compile(r"(HTTPS?://[^\s]+|WWW\.[^\s]+)")


def _url_texto(t: _Texto) -> Optional[str]:
    m = _RE_URL.search(t.plano)
    if not m:
        return None
    u = t.original_de(*m.span(1)).rstrip(".,;)")
    return u if u.lower().startswith("http") else "https://" + u


# --------------------------------------------------------------------------------------
# Situação (genérica)
# --------------------------------------------------------------------------------------

# Ordem de restrição: em conflito prevalece o mais restritivo.
_RESTRICAO = {
    Situacao.POSITIVA: 3,
    Situacao.POSITIVA_EFEITO_NEGATIVA: 2,
    Situacao.NEGATIVA: 1,
    Situacao.REGULAR: 1,
    Situacao.INDETERMINADA: 0,
}

# Título: "CERTIDAO [até 3 palavras] POSITIVA|NEGATIVA", desde que não seja parte de
# "efeito(s) de certidão negativa" (frase de corpo).
_RE_TITULO_SIT = re.compile(
    r"(?<!EFEITO DE )(?<!EFEITOS DE )\bCERTIDAO (?:(?!COM\b)[A-Z]+ ){0,3}(POSITIVA|NEGATIVA)\b"
)
# Complemento do título (pode vir após "DE DEBITOS TRABALHISTAS" ou quebrar de linha):
# só palavras, sem pontuação, até "COM EFEITO(S) DE (CERTIDAO) NEGATIVA".
_RE_TITULO_PEN = re.compile(r"(?:\s+[A-Z]+){0,8}?\s+COM EFEITOS? DE (?:CERTIDAO )?NEGATIVA\b")

_NEGACAO = r"\b(?:NAO|SEM|NEM|NUNCA|SOMENTE|APENAS|JAMAIS)\b"
_RE_CORPO_PEN = re.compile(r"\bCOM (?:OS MESMOS )?EFEITOS? DE (?:CERTIDAO )?NEGATIVA\b")
_RE_SITUACAO_CAMPO = re.compile(
    r"\bSITUACAO\s*:?\s*(POSITIVA(?: COM EFEITOS? DE (?:CERTIDAO )?NEGATIVA)?|NEGATIVA|REGULAR|IRREGULAR)\b"
)
_ALVO_DEB = r"(?:DEBITOS?|PENDENCIAS?(?: FINANCEIRAS| FISCAIS| TRIBUTARIAS)?)"
_RE_CORPO_POS = re.compile(
    r"(?<!NAO )(?<!NADA )(?<!INEXISTEM )\b(?:CONSTAM?|POSSUI|EXISTEM|HA)\b(?: [A-Z]+){0,6} " + _ALVO_DEB + r"\b"
)
_RE_CORPO_NEG = re.compile(
    r"\bNAO CONSTAM?\b|\bNADA CONSTA\b|\bINEXISTEM\b(?: [A-Z]+){0,2} " + _ALVO_DEB
    + r"|\bNAO (?:HA|EXISTEM|POSSUI)\b(?: [A-Z]+){0,2} " + _ALVO_DEB + r"|\bNAO FORAM ENCONTRAD"
)
_RE_SUSPENSO = re.compile(r"SUSPENS|PARCELAD|GARANTID")
_RE_MENCAO_SUSPENSO = re.compile(
    r"EXIGIBILIDADE SUSPENSA|\bDEBITOS?\b(?: [A-Z]+){0,4} (?:SUSPENSOS?|PARCELADOS?)\b|\bPARCELAMENTO\b"
)


def _situacao_titulo(t: _Texto) -> Situacao:
    """Situação declarada no título (primeira ocorrência)."""
    m = _RE_TITULO_SIT.search(t.linhas)
    if not m:
        return Situacao.INDETERMINADA
    if m.group(1) == "NEGATIVA":
        return Situacao.NEGATIVA
    if _RE_TITULO_PEN.match(t.linhas, m.end()):
        return Situacao.POSITIVA_EFEITO_NEGATIVA
    return Situacao.POSITIVA


def _negado(f: str, ini: int, janela: int = 40) -> bool:
    return re.search(_NEGACAO, f[max(0, ini - janela): ini]) is not None


def _sinais_corpo(f: str) -> dict[str, bool]:
    """Sinais do corpo: débito exigível, débito suspenso, sem débito, 'com efeito de negativa'."""
    s = {"positiva": False, "suspensa": False, "negativa": False, "pen": False}
    for m in _RE_CORPO_POS.finditer(f):
        # o que segue a frase (até o fim da frase) diz se o débito está suspenso/parcelado
        resto = re.split(r"\.(?!\d)", f[m.end(): m.end() + 120], maxsplit=1)[0]
        if _RE_SUSPENSO.search(resto):
            s["suspensa"] = True
        else:
            s["positiva"] = True
    for m in _RE_CORPO_PEN.finditer(f):
        if not _negado(f, m.start()):
            s["pen"] = True
    if _RE_CORPO_NEG.search(f):
        s["negativa"] = True
    if s["negativa"]:
        for m in _RE_MENCAO_SUSPENSO.finditer(f):
            # ignora menções hipotéticas/normativas ("somente a certidão que indique débitos suspensos...")
            ini = max(f.rfind(". ", 0, m.start()), f.rfind("\n", 0, m.start())) + 1
            frase = f[ini: m.start()]
            if not re.search(_NEGACAO + r"|\bQUE INDIQU|\bCASO\b|\bSE HOUVER\b|\bART\b", frase):
                s["suspensa"] = True
                break
    m = _RE_SITUACAO_CAMPO.search(f)
    if m:
        v = m.group(1)
        if v.startswith("POSITIVA COM"):
            s["pen"] = True
        elif v in ("POSITIVA", "IRREGULAR"):
            s["positiva"] = True
        else:
            s["negativa"] = True
    return s


def _situacao_corpo(s: dict[str, bool]) -> Situacao:
    if s["positiva"]:
        return Situacao.POSITIVA
    if s["pen"] or s["suspensa"]:
        return Situacao.POSITIVA_EFEITO_NEGATIVA
    if s["negativa"]:
        return Situacao.NEGATIVA
    return Situacao.INDETERMINADA


def _resolver_situacao(t: _Texto, c: Certidao) -> None:
    """O título manda; o corpo só preenche a lacuna ou, em conflito, impõe o mais restritivo."""
    f = t.plano
    sinais = _sinais_corpo(f)
    corpo = _situacao_corpo(sinais)
    atual = c.situacao
    if atual == Situacao.INDETERMINADA:
        atual = _situacao_titulo(t)
    if atual == Situacao.INDETERMINADA:
        c.situacao = corpo
        if sinais["positiva"] and sinais["negativa"]:
            c.avisos.append("Texto traz frases de débito e de ausência de débito: "
                            "considerada POSITIVA (mais restritiva); conferir")
        return
    if corpo != Situacao.INDETERMINADA and _RESTRICAO[corpo] > _RESTRICAO[atual]:
        c.avisos.append(
            f"Título indica {atual.value}, mas o corpo indica {corpo.value}: "
            f"considerada {corpo.value} (mais restritiva); conferir"
        )
        atual = corpo
    c.situacao = atual


# --------------------------------------------------------------------------------------
# UF / município
# --------------------------------------------------------------------------------------

_UFS = {
    "ACRE": "AC", "ALAGOAS": "AL", "AMAPA": "AP", "AMAZONAS": "AM", "BAHIA": "BA", "CEARA": "CE",
    "DISTRITO FEDERAL": "DF", "ESPIRITO SANTO": "ES", "GOIAS": "GO", "MARANHAO": "MA",
    "MATO GROSSO DO SUL": "MS", "MATO GROSSO": "MT", "MINAS GERAIS": "MG", "PARAIBA": "PB",
    "PARANA": "PR", "PARA": "PA", "PERNAMBUCO": "PE", "PIAUI": "PI", "RIO DE JANEIRO": "RJ",
    "RIO GRANDE DO NORTE": "RN", "RIO GRANDE DO SUL": "RS", "RONDONIA": "RO", "RORAIMA": "RR",
    "SANTA CATARINA": "SC", "SAO PAULO": "SP", "SERGIPE": "SE", "TOCANTINS": "TO",
}
_NOMES_UF = "|".join(sorted(_UFS, key=len, reverse=True))
_RE_ESTADO = re.compile(r"\b(?:ESTADO|GOVERNO) D[OEA] (" + _NOMES_UF + r")\b")
_RE_DF = re.compile(r"\bDISTRITO FEDERAL\b")
_CAPITAIS = {
    "RIO BRANCO": "AC", "MACEIO": "AL", "MACAPA": "AP", "MANAUS": "AM", "SALVADOR": "BA",
    "FORTALEZA": "CE", "BRASILIA": "DF", "VITORIA": "ES", "GOIANIA": "GO", "SAO LUIS": "MA",
    "CUIABA": "MT", "CAMPO GRANDE": "MS", "BELO HORIZONTE": "MG", "BELEM": "PA",
    "JOAO PESSOA": "PB", "CURITIBA": "PR", "RECIFE": "PE", "TERESINA": "PI",
    "RIO DE JANEIRO": "RJ", "NATAL": "RN", "PORTO ALEGRE": "RS", "PORTO VELHO": "RO",
    "BOA VISTA": "RR", "FLORIANOPOLIS": "SC", "SAO PAULO": "SP", "ARACAJU": "SE", "PALMAS": "TO",
}
_SIGLAS = set(_UFS.values())


def _uf(f: str) -> Optional[str]:
    m = _RE_ESTADO.search(f)
    if m:
        return _UFS[m.group(1)]
    if _RE_DF.search(f):
        return "DF"
    return None


_MINUSC = {"de", "da", "do", "das", "dos", "e", "d'"}


def _titulo(s: str) -> str:
    s = re.sub(r"\s+", " ", s.strip())
    if s.isupper() or s.islower():
        palavras = s.lower().split(" ")
        s = " ".join(p if (i and p in _MINUSC) else p[:1].upper() + p[1:] for i, p in enumerate(palavras))
    return s


_RE_MUNICIPIO = re.compile(
    r"(?:PREFEITURA(?: MUNICIPAL)?(?: D[OEA])?(?: MUNICIPIO D[OEA])?|\bMUNICIPIO D[OEA])"
    r" ([A-Z][A-Z' ]{1,60}?)(?=\s*(?:[\n\-/,(]|\Z| ESTADO\b| CNPJ\b| SECRETARIA\b))"
)


def _municipio(t: _Texto) -> tuple[Optional[str], Optional[str]]:
    m = _RE_MUNICIPIO.search(t.linhas)
    if not m:
        return None, None
    nome_norm = m.group(1).strip()
    nome = _titulo(t.original_de(*m.span(1)))
    uf = None
    ms = re.compile(r"\s*[-/]\s*([A-Z]{2})\b").match(t.linhas, m.end())
    if ms and ms.group(1) in _SIGLAS:
        uf = ms.group(1)
    return nome, uf or _CAPITAIS.get(nome_norm)


# --------------------------------------------------------------------------------------
# Identificação
# --------------------------------------------------------------------------------------

_TITULOS_FORTES: list[tuple[TipoCertidao, re.Pattern]] = [
    (TipoCertidao.SICAF, re.compile(r"SISTEMA DE CADASTRAMENTO UNIFICADO DE FORNECEDORES")),
    (TipoCertidao.FEDERAL, re.compile(
        r"CERTIDAO (?:NEGATIVA|POSITIVA)(?: COM EFEITOS? DE NEGATIVA)? DE DEBITOS RELATIVOS AOS TRIBUTOS FEDERAIS")),
    (TipoCertidao.TRABALHISTA, re.compile(r"CERTIDAO (?:NEGATIVA|POSITIVA) DE DEBITOS TRABALHISTAS")),
    (TipoCertidao.FGTS, re.compile(r"CERTIFICADO DE REGULARIDADE DO FGTS")),
    (TipoCertidao.ESTADUAL, re.compile(r"(?:NAO INSCRITOS NA )?DIVIDA ATIVA DO ESTADO D[OEA] ")),
    (TipoCertidao.MUNICIPAL, re.compile(r"TRIBUTOS MOBILIARIOS")),
]


def _titulos(f: str) -> list[tuple[int, TipoCertidao]]:
    achados = []
    for tipo, rx in _TITULOS_FORTES:
        m = rx.search(f)
        if m:
            achados.append((m.start(), tipo))
    achados.sort(key=lambda x: x[0])
    return achados


_RE_OUTRA = re.compile(
    r"CADASTRO NACIONAL DE EMPRESAS (?:INIDONEAS|PUNIDAS)|\bCEIS\b|\bCNEP\b|CONTROLADORIA-? ?GERAL DA UNIAO|"
    r"LICITANTES INIDONEOS|TRIBUNAL DE CONTAS DA UNIAO|IMPROBIDADE ADMINISTRATIVA|"
    r"CONSELHO NACIONAL DE JUSTICA|CERTIDAO NEGATIVA CORRECIONAL"
)
_RE_ESTADUAL = re.compile(
    r"SECRETARIA (?:DE ESTADO )?(?:DA |DE )?(?:FAZENDA|ECONOMIA|RECEITA|TRIBUTACAO|FINANCAS)|RECEITA ESTADUAL|"
    r"\bSEFAZ\b|PROCURADORIA[- ]GERAL DO ESTADO|DIVIDA ATIVA DO ESTADO|GOVERNO DO ESTADO|FAZENDA ESTADUAL|"
    r"\bSIDEB\b|"
    r"\bESTADO D[OEA] (?:" + _NOMES_UF + r")\b|\bDISTRITO FEDERAL\b"
)
_RE_MUNICIPAL = re.compile(r"PREFEITURA|SECRETARIA MUNICIPAL|TRIBUTOS MOBILIARIOS|FAZENDA MUNICIPAL")


def _identificar(f: str, titulos: list[tuple[int, TipoCertidao]]) -> TipoCertidao:
    tipos = [tp for _, tp in titulos]
    if TipoCertidao.SICAF in tipos:
        return TipoCertidao.SICAF
    if titulos:
        return titulos[0][1]
    if "TRIBUTOS FEDERAIS" in f and re.search(r"DIVIDA ATIVA DA UNIAO|RECEITA FEDERAL|PGFN", f):
        return TipoCertidao.FEDERAL
    if "FGTS" in f and re.search(r"\bCRF\b|FUNDO DE GARANTIA", f):
        return TipoCertidao.FGTS
    if re.search(r"(?:DEBITOS|DEVEDORES) TRABALHISTAS", f):
        return TipoCertidao.TRABALHISTA
    if _RE_OUTRA.search(f):
        return TipoCertidao.OUTRA
    if "CERTID" not in f:
        return TipoCertidao.DESCONHECIDA
    if _RE_MUNICIPAL.search(f) or re.search(r"\bMUNICIPIO D[OEA] ", f[:600]):
        return TipoCertidao.MUNICIPAL
    if _RE_ESTADUAL.search(f):
        return TipoCertidao.ESTADUAL
    return TipoCertidao.DESCONHECIDA


# --------------------------------------------------------------------------------------
# Regras por emissor
# --------------------------------------------------------------------------------------

def _regra_federal(t: _Texto, c: Certidao) -> None:
    f = t.plano
    c.orgao_emissor = "Receita Federal / PGFN"
    c.url_verificacao = URL_FEDERAL
    m = re.search(
        r"CERTIDAO (NEGATIVA|POSITIVA)( COM EFEITOS? DE NEGATIVA)? DE DEBITOS RELATIVOS AOS TRIBUTOS FEDERAIS", f
    )
    if m:
        if m.group(2):
            c.situacao = Situacao.POSITIVA_EFEITO_NEGATIVA
        elif m.group(1) == "NEGATIVA":
            c.situacao = Situacao.NEGATIVA
        else:
            c.situacao = Situacao.POSITIVA
    m = re.search(r"CODIGO DE CONTROLE DA CERTIDAO\s*:?\s*([0-9A-Z]{4}(?:\.[0-9A-Z]{4}){3})", f)
    if m:
        c.codigo_controle = m.group(1)


def _regra_fgts(t: _Texto, c: Certidao) -> None:
    f = t.plano
    c.orgao_emissor = "Caixa Econômica Federal (CRF)"
    c.url_verificacao = URL_FGTS
    if re.search(r"(?<!NAO )ESTA REGULAR PERANTE O FUNDO DE GARANTIA", f):
        c.situacao = Situacao.REGULAR
    elif re.search(r"NAO ESTA REGULAR|\bIRREGULAR\b", f):
        c.situacao = Situacao.POSITIVA
        c.avisos.append("CRF indica irregularidade perante o FGTS")
    ini, fim = _validade_intervalo(f)
    if fim:
        c.validade = fim
    c.data_emissao = _data_ancora(f, [r"INFORMACAO OBTIDA EM"]) or ini
    m = re.search(r"CERTIFICACAO NUMERO\s*:?\s*(\d{8,})", f)
    if m:
        c.codigo_controle = m.group(1)


def _regra_trabalhista(t: _Texto, c: Certidao) -> None:
    f = t.plano
    c.orgao_emissor = "Tribunal Superior do Trabalho (CNDT)"
    c.url_verificacao = URL_TST
    m = re.search(r"CERTIDAO (NEGATIVA|POSITIVA) DE DEBITOS TRABALHISTAS( COM EFEITOS? DE NEGATIVA)?", f)
    if m:
        if m.group(2):
            c.situacao = Situacao.POSITIVA_EFEITO_NEGATIVA
        elif m.group(1) == "NEGATIVA":
            c.situacao = Situacao.NEGATIVA
        else:
            c.situacao = Situacao.POSITIVA
    m = re.search(r"CERTIDAO N[O.]+\s*:?\s*(\d+/\d{4})", f)
    if m:
        c.codigo_controle = m.group(1)


# Certidão estadual ÚNICA. Regra genérica (o modelo oficial do SIDEB/SP e da conjunta do RJ
# não foi confirmado): basta um dos sinais abaixo.
_RE_UNICA = re.compile(
    r"\bINSCRITOS (?:E|OU) NAO INSCRITOS\b"          # "débitos inscritos e não inscritos em dívida ativa"
    r"|\bCERTIDAO UNICA\b"
    r"|\bSIDEB\b"
)
# Conjunta Fazenda + Procuradoria: exige "certidão conjunta"/"emitida conjuntamente" E menção aos
# dois órgãos ("Resolução Conjunta SF/PGE", rodapé da certidão antiga da SEFAZ-SP, não basta).
_RE_CONJUNTA = re.compile(r"\bCERTIDAO (?:[A-Z]+ ){0,4}CONJUNTA\b|\bEMITIDA CONJUNTAMENTE\b")
_RE_FAZENDA = re.compile(r"\bSEFAZ\b|SECRETARIA (?:DE ESTADO )?(?:DA |DE )?(?:FAZENDA|ECONOMIA|RECEITA)")
_RE_PROCURADORIA = re.compile(r"\bPGE\b|PROCURADORIA[- ]GERAL DO ESTADO")


def _estadual_unica(f: str) -> bool:
    if _RE_UNICA.search(f):
        return True
    return bool(_RE_CONJUNTA.search(f) and _RE_FAZENDA.search(f) and _RE_PROCURADORIA.search(f))


_RE_ABRANGE_RAIZ = re.compile(
    r"\bABRANGE(?:NDO)?\b(?: [A-Z]+){0,3} (?:OS |SEUS |AS )?(?:ESTABELECIMENTOS|FILIAIS)\b"
    r"|\bMATRIZ E (?:SUAS |AS )?FILIAIS\b"
    r"|\bRAIZ DO CNPJ\b|\bCNPJ (?:BASE|RAIZ)\b"
)


def abrange_raiz(texto: str) -> bool:
    """True se o texto declara que a certidão vale para todos os estabelecimentos (raiz do CNPJ)."""
    f = _norm(texto or "")
    for m in _RE_ABRANGE_RAIZ.finditer(f):
        if not _negado(f, m.start(), 20):
            return True
    return False


def e_estadual_unica(c: Certidao) -> bool:
    """Certidão estadual única (Sefaz + PGE), pela convenção de ``orgao_emissor`` (ORGAO_UNICA)."""
    return c.tipo == TipoCertidao.ESTADUAL and (c.orgao_emissor or "").upper().startswith(ORGAO_UNICA)


def _regra_estadual(t: _Texto, c: Certidao) -> None:
    f = t.plano
    c.uf = _uf(f)
    if not c.uf and re.search(r"\bSIDEB\b", f):
        c.uf = "SP"  # SIDEB é o sistema da Sefaz-SP
    sigla = c.uf or "UF?"
    if _estadual_unica(f):
        c.orgao_emissor = f"{ORGAO_UNICA}-{c.uf}" if c.uf else ORGAO_UNICA
        if c.uf == "SP" and not _RE_URL.search(f):
            c.url_verificacao = URL_SIDEB
    elif re.search(r"NAO INSCRITOS NA DIVIDA ATIVA", f):
        c.orgao_emissor = f"SEFAZ-{sigla}"
    elif re.search(r"PROCURADORIA[- ]GERAL DO ESTADO|DIVIDA ATIVA DO ESTADO", f):
        c.orgao_emissor = f"PGE-{sigla}"
    else:
        c.orgao_emissor = f"SEFAZ-{sigla}" if c.uf else "Fazenda Estadual"
    if not c.uf:
        c.avisos.append("UF da certidão estadual não identificada")


def _regra_municipal(t: _Texto, c: Certidao) -> None:
    c.municipio, uf = _municipio(t)
    c.uf = uf or _uf(t.plano)
    c.orgao_emissor = f"Prefeitura de {c.municipio}" if c.municipio else "Fazenda Municipal"
    if not c.municipio:
        c.avisos.append("Município da certidão não identificado")


# Declaração SICAF: nível III = Regularidade Fiscal e Trabalhista Federal;
# nível IV = Regularidade Fiscal Estadual/Distrital e Municipal.
_RE_NIVEL_SICAF = re.compile(r"(?m)^(?:NIVEL\s+)?(VI|V|IV|III|II|I)\s*-\s*(?=[A-Z])")
_ITENS_SICAF: dict[str, tuple[str, re.Pattern]] = {
    "federal": ("III", re.compile(r"(?m)^RECEITA FEDERAL(?: E PGFN)?\b")),
    "fgts": ("III", re.compile(r"(?m)^FGTS\b")),
    "trabalhista": ("III", re.compile(r"(?m)^TRABALHISTA\b")),
    "estadual": ("IV", re.compile(r"(?m)^RECEITA ESTADUAL(?:/DISTRITAL)?\b")),
    "municipal": ("IV", re.compile(r"(?m)^RECEITA MUNICIPAL\b")),
}
_RE_PENDENCIA_NIVEL = re.compile(r"(?<!NAO )POSSUI PENDENCIA|\bCOM PENDENCIA")
_RE_NEG_PENDENCIA = re.compile(r"(?:NAO POSSUI|SEM|NENHUMA|INEXISTENCIA DE|NAO HA) PENDENCIAS?")


def _fim_linha(f: str, pos: int, extra: int = 0) -> int:
    """Fim da linha que contém ``pos`` (mais ``extra`` linhas seguintes)."""
    for _ in range(extra + 1):
        q = f.find("\n", pos)
        if q < 0:
            return len(f)
        pos = q + 1
    return pos - 1


def _automatica(trecho: str) -> bool:
    """'Automática' = obtida pelo SICAF junto ao emissor; 'Manual' ou nada = inserida pelo fornecedor."""
    return "AUTOMATICA" in trecho and "MANUAL" not in trecho


def _cobertura_sicaf(t: _Texto, pendencia_global: bool) -> tuple[dict[str, dict], list[str]]:
    """Lê os itens dos níveis III e IV. Devolve (cobertura, níveis com pendência)."""
    f = t.linhas
    niveis = list(_RE_NIVEL_SICAF.finditer(f))
    vaos: dict[str, tuple[int, int]] = {}
    for i, m in enumerate(niveis):
        nome = m.group(1)
        if nome in vaos:
            continue
        vaos[nome] = (m.start(), niveis[i + 1].start() if i + 1 < len(niveis) else len(f))
    sem_niveis = "III" not in vaos and "IV" not in vaos

    cobertura: dict[str, dict] = {}
    com_pendencia: list[str] = []
    grupos = ("III", "IV") if not sem_niveis else ("*",)
    for grupo in grupos:
        a, b = (0, len(f)) if grupo == "*" else vaos.get(grupo, (0, 0))
        if b <= a:
            continue
        rotulos: list[tuple[int, int, str]] = []  # (início, fim do rótulo, tipo)
        for tipo, (nivel, rx) in _ITENS_SICAF.items():
            if grupo != "*" and nivel != grupo:
                continue
            m = rx.search(f, a, b)
            if m:
                rotulos.append((m.start(), m.end(), tipo))
        rotulos.sort()
        # pendência: em qualquer ponto do bloco do nível (título, itens ou "Situação do nível",
        # até o próximo título de nível) ou, sem níveis, no texto todo
        if grupo == "*":
            pend = pendencia_global
        else:
            pend = bool(_RE_PENDENCIA_NIVEL.search(f, a, b))
            if pend:
                com_pendencia.append(grupo)
        if not rotulos:
            continue  # ex.: "Nenhum registro encontrado"
        achados: dict[str, tuple[Optional[date], bool]] = {}
        faltou = False
        for k, (ri, rf, tipo) in enumerate(rotulos):
            jf = rotulos[k + 1][0] if k + 1 < len(rotulos) else b
            md = _RE_DATA.search(f, rf, jf)
            if not md:
                faltou = True
                continue
            # modo (Automática/Manual): da linha do rótulo até a linha seguinte à da data
            trecho = f[ri: min(jf, _fim_linha(f, md.end(), 1))]
            achados[tipo] = (_data_de(md), _automatica(trecho))
        if faltou:
            # layout em colunas: rótulos de um lado, datas do outro -> pareia na ordem
            datas = list(_RE_DATA.finditer(f, rotulos[0][1], b))
            if len(datas) == len(rotulos):
                achados = {
                    tipo: (_data_de(md), _automatica(f[md.start(): _fim_linha(f, md.end())]))
                    for (_, _, tipo), md in zip(rotulos, datas)
                }
        for _, _, tipo in rotulos:
            if tipo in achados:
                v, aut = achados[tipo]
                cobertura[tipo] = {"validade": v, "automatica": aut, "pendencia": pend}
    return cobertura, com_pendencia


def itens_cobertura(c: Certidao) -> dict[str, dict]:
    """Itens de ``cobertura_sicaf`` por tipo, sem as chaves reservadas ("_situacao" etc.)."""
    return {k: v for k, v in c.cobertura_sicaf.items() if not k.startswith("_")}


_RE_SITUACAO_FORNECEDOR = re.compile(r"SITUACAO DO FORNECEDOR\s*:[ \t]*([^\n]*)")
_RE_OCORRENCIA_SICAF = re.compile(
    r"(?m)^(OCORRENCIAS? IMPEDITIVAS INDIRETAS|IMPEDIMENTOS? DE LICITAR|OCORRENCIAS?(?: E IMPEDIMENTOS)?)"
    r"\s*:[ \t]*([^\n]*)"
)


def _situacao_fornecedor_sicaf(t: _Texto) -> dict:
    """{"credenciado": bool, "situacao": str|None, "impedimento": str|None} da declaração."""
    f = t.linhas
    situacao = None
    m = _RE_SITUACAO_FORNECEDOR.search(f)
    if m and m.group(1).strip():
        situacao = re.sub(r"\s+", " ", t.original_de(*m.span(1))).strip(" .;:-")
    credenciado = bool(m) and bool(re.match(r"CREDENCIADO\b", m.group(1).strip()))
    impedimentos: list[str] = []
    for mo in _RE_OCORRENCIA_SICAF.finditer(f):
        ini, fim = mo.span(2)
        if not mo.group(2).strip():  # valor na linha seguinte
            ini = fim + 1
            fim = _fim_linha(f, ini) if ini < len(f) else ini
        valor = f[ini:fim].strip()
        if not valor or valor.startswith("NADA CONSTA"):
            continue
        rotulo = t.original_de(*mo.span(1)).strip()
        impedimentos.append(f"{rotulo}: " + re.sub(r"\s+", " ", t.original_de(ini, fim)).strip())
    return {"credenciado": credenciado, "situacao": situacao,
            "impedimento": "; ".join(impedimentos) or None}


_NOME_NIVEL = {
    "III": "nível III (Regularidade Fiscal e Trabalhista Federal)",
    "IV": "nível IV (Regularidade Fiscal Estadual/Distrital e Municipal)",
}


def _regra_sicaf(t: _Texto, c: Certidao) -> None:
    f = t.plano
    c.orgao_emissor = "SICAF (Compras.gov.br)"
    pendencia = bool(re.search(r"PENDENCIA", _RE_NEG_PENDENCIA.sub("", f)))
    c.cobertura_sicaf, niveis_pend = _cobertura_sicaf(t, pendencia)
    if pendencia:
        c.situacao = Situacao.INDETERMINADA
        if niveis_pend:
            c.avisos.append("SICAF indica pendência no " + " e no ".join(_NOME_NIVEL[n] for n in niveis_pend)
                            + ": conferir a declaração")
        else:
            c.avisos.append("SICAF indica pendência: conferir a declaração")
    else:
        c.situacao = Situacao.REGULAR
    sit = _situacao_fornecedor_sicaf(t)
    c.cobertura_sicaf["_situacao"] = sit
    if sit["situacao"] is None:
        c.avisos.append("SICAF: situação do fornecedor não identificada na declaração: conferir")
    elif not sit["credenciado"]:
        c.avisos.append(f"SICAF: fornecedor {sit['situacao']}")
    if sit["impedimento"]:
        c.avisos.append(f"SICAF: {sit['impedimento']}")
    datas = [v["validade"] for v in itens_cobertura(c).values() if v["validade"]]
    if not datas:
        for m in re.finditer(r"\bVALIDADE\b", f):
            d, _ = _data_em(f, m.end())
            if d:
                datas.append(d)
    if datas:
        c.validade = min(datas)
        if len(datas) > 1:
            c.avisos.append("SICAF: validade considerada é a mais próxima entre as listadas")
    c.data_emissao = _data_ancora(f, [r"DATA DE EMISSAO", r"EMITIDO EM", r"EMITIDA EM", r"DATA DA CONSULTA"])


def _regra_outra(t: _Texto, c: Certidao) -> None:
    f = t.plano
    if re.search(r"LICITANTES INIDONEOS|TRIBUNAL DE CONTAS DA UNIAO", f):
        c.orgao_emissor = "TCU"
    elif re.search(r"IMPROBIDADE|CONSELHO NACIONAL DE JUSTICA", f):
        c.orgao_emissor = "CNJ"
    else:
        c.orgao_emissor = "CGU"
    if re.search(r"\bNADA CONSTA\b|\bNAO CONSTA", f):
        c.situacao = Situacao.NEGATIVA


_REGRAS: dict[TipoCertidao, Callable[[_Texto, Certidao], None]] = {
    TipoCertidao.FEDERAL: _regra_federal,
    TipoCertidao.FGTS: _regra_fgts,
    TipoCertidao.TRABALHISTA: _regra_trabalhista,
    TipoCertidao.ESTADUAL: _regra_estadual,
    TipoCertidao.MUNICIPAL: _regra_municipal,
    TipoCertidao.SICAF: _regra_sicaf,
    TipoCertidao.OUTRA: _regra_outra,
}

# Tipos para os quais a ausência de validade não reduz a confiança tanto (raramente trazem)
_SEM_VALIDADE_OK = {TipoCertidao.OUTRA}


def _comuns(t: _Texto, c: Certidao) -> None:
    f = t.plano
    if c.tipo not in (TipoCertidao.SICAF, TipoCertidao.FGTS):
        _resolver_situacao(t, c)
    if not c.data_emissao:
        c.data_emissao = _data_ancora(f, _ANC_EMISSAO)
    if not c.validade:
        _, fim = _validade_intervalo(f)
        c.validade = fim or _data_ancora(f, _ANC_VALIDADE) or _validade_relativa(f, c.data_emissao)
    if not c.codigo_controle:
        c.codigo_controle = _codigo_generico(f)
    if not c.url_verificacao:
        c.url_verificacao = _url_texto(t)
    _cnpj(t, c)
    _razao_social(t, c)


def _avaliar(c: Certidao, multiplas: bool) -> None:
    conf = 0.95
    # SICAF lido por nível: a "situação indeterminada" vem de pendência identificada (não é falha
    # de leitura) e um item vencido listado na declaração pode ser anterior à emissão.
    sicaf_lido = c.tipo == TipoCertidao.SICAF and bool(itens_cobertura(c))
    pend_sicaf = sicaf_lido and any("SICAF indica pendência" in a for a in c.avisos)
    if c.tipo == TipoCertidao.DESCONHECIDA:
        conf -= 0.4
        c.avisos.append("Tipo de certidão não identificado")
    if c.situacao == Situacao.INDETERMINADA and not pend_sicaf:
        conf -= 0.25
        c.avisos.append("Situação (negativa/positiva/regular) não identificada")
    if not c.validade:
        conf -= 0.05 if c.tipo in _SEM_VALIDADE_OK else 0.15
        c.avisos.append("Data de validade não encontrada")
    if not c.cnpj:
        conf -= 0.15
        c.avisos.append("CNPJ não encontrado no PDF")
    elif not cnpj_valido(c.cnpj):
        conf -= 0.1
    if not c.data_emissao:
        conf -= 0.02
        c.avisos.append("Data de emissão não encontrada")
    if not c.codigo_controle:
        conf -= 0.02
        c.avisos.append("Código de controle/autenticidade não encontrado")
    if multiplas:
        conf -= 0.1
    if c.validade and c.data_emissao and c.validade < c.data_emissao and not sicaf_lido:
        conf -= 0.1
        c.avisos.append("Validade anterior à emissão: conferir datas")
    c.confianca = round(max(0.0, min(1.0, conf)), 2)


# --------------------------------------------------------------------------------------
# API pública
# --------------------------------------------------------------------------------------

def extrair_texto(caminho: str | Path) -> str:
    """Texto de todas as páginas do PDF (pdfplumber). PDF só com imagem -> ""."""
    import pdfplumber

    partes: list[str] = []
    with pdfplumber.open(str(caminho)) as pdf:
        for pagina in pdf.pages:
            partes.append(pagina.extract_text() or "")
    texto = "\n".join(partes)
    return texto if texto.strip() else ""


def ler_texto(texto: str, arquivo: str = "") -> Certidao:
    """Aplica as regras ao texto já extraído e devolve uma Certidao (nunca levanta exceção)."""
    c = Certidao(arquivo=arquivo, texto=texto or "")
    if not (texto or "").strip():
        c.avisos.append(AVISO_ESCANEADO)
        return c
    t = _normalizar(texto)
    titulos = _titulos(t.plano)
    multiplas = False
    tipos_tit = []
    for pos, tp in titulos:
        if tp not in [x for _, x in tipos_tit]:
            tipos_tit.append((pos, tp))
    if len(tipos_tit) >= 2 and TipoCertidao.SICAF not in [tp for _, tp in tipos_tit]:
        multiplas = True
        c.avisos.append(AVISO_MULTIPLAS)
        t = t.fatia(tipos_tit[1][0])
        titulos = tipos_tit[:1]
    c.tipo = _identificar(t.plano, titulos)
    regra = _REGRAS.get(c.tipo)
    if regra:
        regra(t, c)
    _comuns(t, c)
    _avaliar(c, multiplas)
    return c


def _precisa_ia(c: Certidao) -> bool:
    if c.tipo == TipoCertidao.SICAF and itens_cobertura(c):
        return False  # declaração lida pelas regras; a pendência é tratada no validador
    return c.tipo == TipoCertidao.DESCONHECIDA or c.situacao == Situacao.INDETERMINADA


def ler_pdf(caminho: str | Path) -> Certidao:
    """Lê um PDF. Usa a IA (se habilitada) apenas quando as regras não identificam tipo/situação."""
    nome = Path(caminho).name
    try:
        texto = extrair_texto(caminho)
    except Exception as e:  # PDF corrompido, protegido etc.
        c = Certidao(arquivo=nome)
        c.avisos.append(f"Não foi possível ler o PDF ({type(e).__name__}): conferir manualmente")
        return c
    c = ler_texto(texto, nome)
    if texto and _precisa_ia(c):
        from . import ia

        if ia.habilitada():
            r = ia.extrair_com_ia(texto, nome)
            if r is not None:
                # completa o que a IA não trouxe com o que as regras acharam
                for campo in ("cnpj", "razao_social", "orgao_emissor", "uf", "municipio",
                              "data_emissao", "validade", "codigo_controle", "url_verificacao"):
                    if getattr(r, campo) is None and getattr(c, campo) is not None:
                        setattr(r, campo, getattr(c, campo))
                r.texto = texto
                r.avisos.extend(a for a in c.avisos if a not in r.avisos)
                return r
    return c


def ler_varios(caminhos: Iterable[str | Path]) -> list[Certidao]:
    return [ler_pdf(p) for p in caminhos]
