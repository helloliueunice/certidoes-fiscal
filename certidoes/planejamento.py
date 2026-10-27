"""Planejamento do "mutirão" mensal de emissão de certidões.

Lê os CSVs de controle gerados pelo próprio sistema (atesto.gerar_csv), descobre o que ainda
está válido numa data de corte e o que precisa ser emitido, e monta o texto de solicitação à
contratada. Lógica pura, sem acesso a rede nem a portais: o sistema só aponta links oficiais;
portais com captcha continuam sendo acessados pelo próprio fiscal.
"""
from __future__ import annotations

import csv
import io
import unicodedata
from datetime import date, datetime
from typing import Any, Optional

from .atesto import celula_segura, validade_item
from .models import ResultadoValidacao, Semaforo, TipoCertidao, formatar_cnpj, so_digitos

# Certidões que a declaração do SICAF obtém do emissor por integração.
TIPOS_SICAF = {TipoCertidao.FEDERAL.value, TipoCertidao.FGTS.value, TipoCertidao.TRABALHISTA.value}

ORDEM_TIPOS = [t.value for t in (TipoCertidao.SICAF, TipoCertidao.FEDERAL, TipoCertidao.FGTS,
                                 TipoCertidao.TRABALHISTA, TipoCertidao.ESTADUAL,
                                 TipoCertidao.MUNICIPAL, TipoCertidao.OUTRA)]

ACAO_EMITIR = "emitir"
ACAO_SICAF = "consultar SICAF"
ACAO_NENHUMA = "nenhuma"
ACAO_RECONFERIR = "reconferir"

# Trechos (normalizados) que indicam ATENÇÃO por motivo diferente de "vence em breve":
# SICAF "Manual", CNPJ ausente, leitura por IA ou baixa confiança, conflito entre documentos,
# pendência no SICAF etc. As mensagens de "vence em breve"/"vence hoje" não contêm nenhum deles.
_SINAIS_RECONFERIR = ("confer", "confir", "consult", "manual", "por ia", "pendencia",
                      "prevaleceu", "nao utilizada", "fornecedor", "impediment", "nao identificad")

ARTIGO_LEI = "Lei nº 14.133/2021, art. 92, XVI"


# ---------------------------------------------------------------- utilidades

def _norm(texto: Optional[str]) -> str:
    s = unicodedata.normalize("NFKD", texto or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    return " ".join(s.lower().split())


def _data(texto: Optional[str]) -> Optional[date]:
    texto = (texto or "").strip()
    if not texto:
        return None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d/%m/%y"):
        try:
            return datetime.strptime(texto, fmt).date()
        except ValueError:
            continue
    return None


def _fmt(d: Optional[date]) -> str:
    return d.strftime("%d/%m/%Y") if d else ""


_ROTULOS = {_norm(t.rotulo): t.value for t in TipoCertidao}
_PALAVRAS = [  # (trecho normalizado, tipo) — para rótulos antigos ou editados à mão
    ("sicaf", "sicaf"), ("fgts", "fgts"), ("crf", "fgts"), ("trabalhist", "trabalhista"),
    ("cndt", "trabalhista"), ("tst", "trabalhista"), ("receita", "federal"), ("pgfn", "federal"),
    ("federal", "federal"), ("estadual", "estadual"), ("sefaz", "estadual"),
    ("municipal", "municipal"), ("prefeitura", "municipal"),
]


def deduzir_tipo(rotulo: Optional[str]) -> Optional[str]:
    """Rótulo do item (ex.: "Receita Federal / PGFN") -> TipoCertidao.value, ou None."""
    n = _norm(rotulo)
    if not n:
        return None
    if n in _ROTULOS:
        v = _ROTULOS[n]
        return None if v == TipoCertidao.DESCONHECIDA.value else v
    for trecho, tipo in _PALAVRAS:
        if trecho in n:
            return tipo
    return None


def data_corte_padrao(hoje: Optional[date] = None) -> date:
    """Dia 10 do mês seguinte."""
    hoje = hoje or date.today()
    if hoje.month == 12:
        return date(hoje.year + 1, 1, 10)
    return date(hoje.year, hoje.month + 1, 10)


# ---------------------------------------------------------------- leitura dos CSVs

def _decodificar(conteudo: bytes) -> str:
    for enc in ("utf-8-sig", "cp1252"):
        try:
            return conteudo.decode(enc)
        except UnicodeDecodeError:
            continue
    return conteudo.decode("utf-8", errors="replace")


def _sem_protecao(texto: str) -> str:
    """Desfaz o apóstrofo que atesto.celula_segura põe antes de = + - @."""
    if len(texto) > 1 and texto[0] == "'" and texto[1] in "=+-@\t\r":
        return texto[1:]
    return texto


def precisa_reconferir(semaforo: str, mensagem: str) -> bool:
    """ATENÇÃO na última conferência por motivo que não seja só a proximidade do vencimento."""
    if semaforo != Semaforo.AMARELO.value:
        return False
    n = _norm(mensagem)
    if not n:
        return True   # sem mensagem não dá para saber o motivo: pedir reconferência
    return any(sinal in n for sinal in _SINAIS_RECONFERIR)


def _linha(bruta: dict[str, Any]) -> Optional[dict]:
    g = lambda k: _sem_protecao((bruta.get(k) or "").strip())  # noqa: E731
    cnpj = so_digitos(g("cnpj"))
    if len(cnpj) != 14:
        return None
    tipo = g("tipo").lower()
    if tipo not in {t.value for t in TipoCertidao} or tipo == TipoCertidao.DESCONHECIDA.value:
        tipo = deduzir_tipo(g("item")) or ""
    if not tipo:
        return None
    validade = _data(g("validade_iso")) or _data(g("validade"))
    return {
        "data_referencia": _data(g("data_referencia")),
        "competencia": g("competencia"),
        "contrato": g("contrato"),
        "cnpj": cnpj,
        "razao_social": g("razao_social"),
        "fiscal": g("fiscal"),
        "uf_sede": g("uf_sede").upper(),
        "municipio_sede": g("municipio_sede"),
        "tipo": tipo,
        "item": g("item") or TipoCertidao(tipo).rotulo,
        "semaforo": g("semaforo").lower(),
        "situacao": g("situacao"),
        "validade": validade,
        "codigo_controle": g("codigo_controle"),
        "via_sicaf": _norm(g("via_sicaf")) in ("sim", "s", "1", "true"),
        "mensagem": g("mensagem"),
    }


def ler_csvs(conteudos: list[bytes]) -> list[dict]:
    """Lê um ou mais CSVs de controle (utf-8-sig, separador ';').

    Aceita CSVs antigos (sem uf_sede, municipio_sede, tipo, validade_iso, via_sicaf): o tipo é
    deduzido do rótulo do item. Linhas sem CNPJ válido ou sem tipo identificável são ignoradas.
    Se o mesmo contrato + CNPJ + tipo aparecer mais de uma vez, fica a linha com a
    data_referencia mais recente (em empate, a última lida).
    """
    escolhidas: dict[tuple, dict] = {}
    for conteudo in conteudos:
        if not conteudo:
            continue
        texto = _decodificar(conteudo)
        primeira = texto.split("\n", 1)[0]
        sep = ";" if ";" in primeira or "," not in primeira else ","
        try:
            leitor = csv.DictReader(io.StringIO(texto), delimiter=sep)
            if not leitor.fieldnames or "cnpj" not in [(f or "").strip() for f in leitor.fieldnames]:
                continue
            for bruta in leitor:
                bruta = {(k or "").strip(): v for k, v in bruta.items() if isinstance(v, str)}
                linha = _linha(bruta)
                if not linha:
                    continue
                chave = (linha["cnpj"], _norm(linha["contrato"]), linha["tipo"])
                atual = escolhidas.get(chave)
                if atual is None or (linha["data_referencia"] or date.min) >= (atual["data_referencia"] or date.min):
                    escolhidas[chave] = linha
        except csv.Error:
            continue
    return list(escolhidas.values())


# ---------------------------------------------------------------- portais

def _portais_do_tipo(tipo: str, uf: str, municipio: str) -> list[dict]:
    try:
        from . import portais
        lista = portais.portais_para(uf or "", municipio or "")
    except Exception:
        return []
    saida = []
    for p in lista:
        if p.get("tipo") != tipo or "verificacao" in (p.get("id") or ""):
            continue
        saida.append({"nome": p.get("nome") or "", "url": p.get("url"), "captcha": p.get("captcha"),
                      "url_verificacao": p.get("url_verificacao")})
    return saida


# ---------------------------------------------------------------- planejamento

def planejar(linhas: list[dict], ate: date, hoje: Optional[date] = None,
             aceitar_sicaf: bool = False) -> list[dict]:
    """Agrupa as linhas por contratada (CNPJ + contrato) e diz o que emitir até `ate`.

    Para cada item: status "emitir" (validade vazia, vencida, anterior a `ate`, ou item que
    estava PENDENTE na última conferência), "reconferir" (validade >= `ate`, mas em ATENÇÃO
    por motivo que não seja só o vencimento próximo) ou "ok" (validade >= `ate`).
    Quando a contratada é comprovada pelo SICAF (alguma linha via_sicaf ou `aceitar_sicaf`),
    federal/FGTS/trabalhista a emitir viram ação "consultar SICAF".
    """
    hoje = hoje or date.today()
    grupos: dict[tuple, dict] = {}
    for ln in linhas:
        chave = (ln["cnpj"], _norm(ln.get("contrato")))
        g = grupos.setdefault(chave, {
            "cnpj": ln["cnpj"], "cnpj_formatado": formatar_cnpj(ln["cnpj"]),
            "contrato": ln.get("contrato") or "", "razao_social": "", "fiscal": "",
            "uf_sede": "", "municipio_sede": "", "competencia": "", "data_referencia": None,
            "_linhas": [],
        })
        g["_linhas"].append(ln)
        if (ln.get("data_referencia") or date.min) >= (g["data_referencia"] or date.min):
            for campo in ("razao_social", "fiscal", "uf_sede", "municipio_sede", "competencia"):
                if ln.get(campo):
                    g[campo] = ln[campo]
            g["data_referencia"] = ln.get("data_referencia") or g["data_referencia"]

    saida = []
    for g in grupos.values():
        usa_sicaf = aceitar_sicaf or any(ln.get("via_sicaf") for ln in g["_linhas"])
        itens = []
        for ln in g.pop("_linhas"):
            v = ln.get("validade")
            pendente = ln.get("semaforo") == Semaforo.VERMELHO.value
            if v is None:
                status, motivo = "emitir", "sem validade registrada"
                sit = "sem_validade"
            elif v < hoje:
                status, motivo = "emitir", f"vencida em {_fmt(v)}"
                sit = "vencida"
            elif v < ate:
                status, motivo = "emitir", f"vence em {_fmt(v)}, antes da data de corte"
                sit = "vence_antes"
            elif pendente:
                status, motivo = "emitir", "estava PENDENTE na última conferência"
                sit = "pendente"
            elif precisa_reconferir(ln.get("semaforo") or "", ln.get("mensagem") or ""):
                status = "reconferir"
                motivo = ("válida até " + _fmt(v) + ", mas estava em ATENÇÃO na última conferência: "
                          + (ln.get("mensagem") or "conferir o documento"))
                sit = "reconferir"
            else:
                status, motivo = "ok", f"válida até {_fmt(v)}"
                sit = "valida"
            via = bool(ln.get("via_sicaf")) or (usa_sicaf and ln["tipo"] in TIPOS_SICAF)
            if status == "ok":
                acao = ACAO_NENHUMA
            elif status == "reconferir":
                acao = ACAO_RECONFERIR
            elif ln["tipo"] == TipoCertidao.SICAF.value or (usa_sicaf and ln["tipo"] in TIPOS_SICAF):
                acao = ACAO_SICAF
            else:
                acao = ACAO_EMITIR
            portais: list[dict] = []
            if acao == ACAO_RECONFERIR:
                # conferência no site do emissor (inclusive itens "Manual" do SICAF)
                portais = _portais_do_tipo(ln["tipo"], g["uf_sede"], g["municipio_sede"])
            elif acao == ACAO_EMITIR:
                portais = _portais_do_tipo(ln["tipo"], g["uf_sede"], g["municipio_sede"])
            elif acao == ACAO_SICAF:
                portais = _portais_do_tipo(TipoCertidao.SICAF.value, g["uf_sede"], g["municipio_sede"])
            itens.append({
                "tipo": ln["tipo"], "rotulo": TipoCertidao(ln["tipo"]).rotulo,
                "validade": v, "validade_txt": _fmt(v), "status": status, "acao": acao,
                "via_sicaf": via, "motivo": motivo, "situacao_plano": sit, "portais": portais,
                "captcha": any(p.get("captcha") is True for p in portais),
                "semaforo_anterior": ln.get("semaforo") or "",
                "codigo_controle": ln.get("codigo_controle") or "",
            })
        itens.sort(key=lambda i: ORDEM_TIPOS.index(i["tipo"]) if i["tipo"] in ORDEM_TIPOS else 99)
        g["itens"] = itens
        g["a_emitir"] = [i for i in itens if i["acao"] == ACAO_EMITIR]
        g["consultar_sicaf"] = [i for i in itens if i["acao"] == ACAO_SICAF]
        g["reconferir"] = [i for i in itens if i["acao"] == ACAO_RECONFERIR]
        g["ok"] = [i for i in itens if i["status"] == "ok"]
        g["usa_sicaf"] = usa_sicaf
        g["ate"] = ate
        g["totais"] = _totais([g])
        saida.append(g)
    saida.sort(key=lambda g: (_norm(g["razao_social"]), g["contrato"]))
    return saida


def _totais(grupos: list[dict]) -> dict:
    itens = [i for g in grupos for i in g["itens"]]
    ok = sum(1 for i in itens if i["status"] == "ok")
    sicaf = sum(1 for i in itens if i["acao"] == ACAO_SICAF)
    emitir = [i for i in itens if i["acao"] == ACAO_EMITIR]
    reconferir = sum(1 for i in itens if i["acao"] == ACAO_RECONFERIR)
    return {
        "contratadas": len(grupos),
        "itens": len(itens),
        "ok": ok,
        "via_sicaf": sicaf,
        "a_emitir": len(emitir),
        "a_reconferir": reconferir,
        "captchas_evitados": ok + sicaf,
        # estimativa: um captcha por portal com captcha conhecido
        "captchas_a_resolver": sum(sum(1 for p in i["portais"] if p.get("captcha") is True)
                                   for i in emitir),
    }


def totalizar(grupos: list[dict]) -> dict:
    """Totais do mutirão inteiro."""
    return _totais(grupos)


def grupo_de_resultado(resultado: ResultadoValidacao) -> dict:
    """Converte os itens PENDENTE/ATENÇÃO de uma conferência num grupo para texto_solicitacao."""
    c = resultado.contrato
    itens = []
    for i in resultado.itens:
        if i.semaforo == Semaforo.VERDE:
            continue
        v = validade_item(i)
        itens.append({"tipo": i.tipo.value, "rotulo": i.tipo.rotulo, "validade": v,
                      "validade_txt": _fmt(v), "status": "emitir", "acao": ACAO_EMITIR,
                      "via_sicaf": False, "motivo": i.mensagem, "portais": [], "captcha": False,
                      "situacao_plano": "pendente" if i.semaforo == Semaforo.VERMELHO else "vence_antes"})
    return {"cnpj": c.cnpj, "cnpj_formatado": formatar_cnpj(c.cnpj), "contrato": c.numero,
            "razao_social": c.razao_social, "fiscal": c.fiscal, "uf_sede": c.uf_sede,
            "municipio_sede": c.municipio_sede, "competencia": c.competencia,
            "itens": itens, "a_emitir": itens, "consultar_sicaf": [], "reconferir": [], "ok": [],
            "ate": None}


# ---------------------------------------------------------------- textos

def assunto_solicitacao(grupo: dict) -> str:
    return f"Contrato nº {grupo.get('contrato') or '[número]'} — envio de certidões de regularidade atualizadas"


def texto_solicitacao(grupo: dict, prazo_dias: int = 5, orgao: str = "") -> str:
    """Minuta de e-mail/ofício à contratada pedindo as certidões que vencem até a data de corte."""
    itens = grupo.get("a_emitir") or []
    ate = grupo.get("ate")
    contrato = grupo.get("contrato") or "[número]"
    razao = grupo.get("razao_social") or "[razão social]"
    cnpj = grupo.get("cnpj_formatado") or formatar_cnpj(grupo.get("cnpj"))
    prazo = max(1, int(prazo_dias or 5))
    linhas = [
        "MINUTA — revisar antes de enviar",
        "",
        f"Assunto: {assunto_solicitacao(grupo)}",
        "",
        f"À {razao}, CNPJ {cnpj}.",
        "",
        "Prezados(as),",
        "",
        f"No âmbito da fiscalização do Contrato nº {contrato}"
        + (f", firmado com {orgao}" if orgao else "")
        + f", solicitamos o envio, no prazo de {prazo} dias úteis, das certidões de regularidade "
        "relacionadas abaixo, atualizadas"
        + (f" e com validade que alcance, no mínimo, {_fmt(ate)}" if ate else "")
        + ":",
        "",
    ]
    if itens:
        for i in itens:
            det = f"validade registrada: {i['validade_txt']}" if i.get("validade_txt") else "sem certidão válida registrada"
            linhas.append(f"- {i['rotulo']} ({det})")
    else:
        linhas.append("- [nenhuma certidão pendente identificada — revisar]")
    linhas += [
        "",
        "Lembramos que cabe à contratada manter, durante toda a execução do contrato, as "
        "condições de habilitação e qualificação exigidas na licitação "
        f"({ARTIGO_LEI}) e, conforme previsto no contrato, encaminhar as certidões de "
        "regularidade juntamente com a nota fiscal.",
        "",
        "As certidões podem ser enviadas em PDF, em resposta a esta mensagem.",
        "",
        "Atenciosamente,",
        "",
        grupo.get("fiscal") or "[nome do fiscal]",
        "Fiscal do contrato" + (f" — {orgao}" if orgao else ""),
    ]
    return "\n".join(linhas)


CAMPOS_PLANO = ["contratada", "cnpj", "contrato", "uf_sede", "municipio_sede", "item", "tipo",
                "validade", "status", "acao", "via_sicaf", "motivo", "portal", "url_portal",
                "captcha", "feito"]


def linhas_plano(grupos: list[dict]) -> list[dict]:
    """Uma linha (dict de textos) por item e portal, nas colunas de CAMPOS_PLANO."""
    saida: list[dict] = []
    for g in grupos:
        for i in g["itens"]:
            base = {"contratada": g["razao_social"], "cnpj": g["cnpj_formatado"],
                    "contrato": g["contrato"], "uf_sede": g["uf_sede"],
                    "municipio_sede": g["municipio_sede"], "item": i["rotulo"], "tipo": i["tipo"],
                    "validade": i["validade_txt"], "status": i["status"], "acao": i["acao"],
                    "via_sicaf": "sim" if i["via_sicaf"] else "não", "motivo": i["motivo"],
                    "portal": "", "url_portal": "", "captcha": "", "feito": ""}
            for p in i["portais"] or [None]:
                linha = dict(base)
                if p:
                    linha.update(portal=p["nome"], url_portal=p["url"] or "",
                                 captcha={True: "sim", False: "não"}.get(p["captcha"], "não informado"))
                saida.append(linha)
    return saida


MAX_LINHAS_PLANO = 5000
MAX_TEXTO_CELULA = 1000


def csv_de_linhas(linhas: list[dict]) -> str:
    """CSV do plano (';', Excel pt-BR), só com as colunas conhecidas e células sanitizadas
    contra injeção de fórmula. Aceita linhas vindas do navegador (valida tipos e tamanhos)."""
    if not isinstance(linhas, list) or len(linhas) > MAX_LINHAS_PLANO:
        raise ValueError("plano inválido")
    saida = io.StringIO()
    w = csv.DictWriter(saida, fieldnames=CAMPOS_PLANO, delimiter=";", lineterminator="\r\n")
    w.writeheader()
    for ln in linhas:
        if not isinstance(ln, dict):
            raise ValueError("plano inválido")
        w.writerow({k: celula_segura(str(ln.get(k) if ln.get(k) is not None else "")[:MAX_TEXTO_CELULA])
                    for k in CAMPOS_PLANO})
    return saida.getvalue()


def csv_plano(grupos: list[dict]) -> str:
    """Lista do mutirão em CSV (';', para Excel pt-BR). Uma linha por item e portal."""
    return csv_de_linhas(linhas_plano(grupos))
