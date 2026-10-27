"""Interface web no Padrão Digital de Governo (gov.br DS), para deploy no Railway.

Rodar localmente:  uvicorn web.main:app --reload
Produção:          uvicorn web.main:app --host 0.0.0.0 --port $PORT
"""
from __future__ import annotations

import collections
import json
import os
import secrets
import shutil
import tempfile
import threading
import time
from datetime import date
from pathlib import Path
from typing import Optional
from urllib.parse import quote, urlsplit

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.background import BackgroundTask

from certidoes import planejamento
from web.seguranca import CabecalhosSeguranca, LimiteCorpo
from certidoes.atesto import gerar_csv, gerar_pdf, validade_item
from certidoes.extrator import ler_varios
from certidoes.models import (
    Contrato,
    Semaforo,
    TipoCertidao,
    cnpj_valido,
    formatar_cnpj,
    so_digitos,
)
from certidoes.validador import (
    ROTULO_SEMAFORO,
    ROTULO_SITUACAO,
    alerta_extra,
    formatar_data,
    nota_extra,
    resumo,
    validar,
)

try:
    from certidoes import portais as _portais
except Exception:  # pragma: no cover
    _portais = None
try:
    from certidoes import conecta as _conecta
except Exception:  # pragma: no cover
    _conecta = None
try:
    from certidoes import ia as _ia
except Exception:  # pragma: no cover
    _ia = None

BASE = Path(__file__).resolve().parent

NOME_SISTEMA = os.environ.get("SISTEMA_NOME", "Conferência de Certidões")
SUBTITULO = os.environ.get("SISTEMA_SUBTITULO", "Apoio à fiscalização de contratos")
MAX_ARQUIVOS = int(os.environ.get("MAX_ARQUIVOS", "20"))
MAX_MB = int(os.environ.get("MAX_MB_POR_ARQUIVO", "10"))
TTL_RESULTADO = 2 * 60 * 60   # resultados ficam em memória por 2 horas
MAX_RESULTADOS = 200

UFS = ["AC", "AL", "AP", "AM", "BA", "CE", "DF", "ES", "GO", "MA", "MT", "MS", "MG", "PA",
       "PB", "PR", "PE", "PI", "RJ", "RN", "RS", "RO", "RR", "SC", "SP", "SE", "TO"]
TIPOS_EXIGIVEIS = [TipoCertidao.FEDERAL, TipoCertidao.FGTS, TipoCertidao.TRABALHISTA,
                   TipoCertidao.ESTADUAL, TipoCertidao.MUNICIPAL, TipoCertidao.SICAF]
PADRAO = {t.value for t in TIPOS_EXIGIVEIS if t != TipoCertidao.SICAF}

AVISO_IA_LGPD = (
    "Com a IA ligada, o texto dos PDFs não identificados (inclui CNPJ e razão social) é "
    "enviado ao serviço da Anthropic. Use apenas se autorizado pelo órgão (LGPD)."
)
DOC_CONECTA = "https://www.gov.br/conecta/catalogo/apis/consultar-certidao-negativa-de-debito"
MAX_CSVS = 20
MAX_KB_CSV = 2048
MB = 1024 * 1024
LIMITE_PADRAO = 64 * 1024                       # corpo máximo das demais rotas
LIMITE_PLANO = 2 * MB                           # campo oculto com o plano do mutirão
LIMITE_MAILTO = 1800                            # tamanho máximo do corpo codificado no mailto:
CONECTA_LIMITE_HORA = int(os.environ.get("CONECTA_LIMITE_HORA", "10"))

CLASSE_SEMAFORO = {Semaforo.VERDE: "success", Semaforo.AMARELO: "warning",
                   Semaforo.VERMELHO: "danger"}
ICONE_SEMAFORO = {Semaforo.VERDE: "fa-check-circle", Semaforo.AMARELO: "fa-exclamation-triangle",
                  Semaforo.VERMELHO: "fa-times-circle"}

app = FastAPI(title=NOME_SISTEMA, docs_url=None, redoc_url=None, openapi_url=None)
app.mount("/static", StaticFiles(directory=BASE / "static"), name="static")
templates = Jinja2Templates(directory=BASE / "templates")
templates.env.globals.update(
    NOME_SISTEMA=NOME_SISTEMA, SUBTITULO=SUBTITULO, ROTULO_SEMAFORO=ROTULO_SEMAFORO,
    ROTULO_SITUACAO=ROTULO_SITUACAO, CLASSE_SEMAFORO=CLASSE_SEMAFORO,
    ICONE_SEMAFORO=ICONE_SEMAFORO, formatar_data=formatar_data, validade_item=validade_item, formatar_cnpj=formatar_cnpj,
    DOC_CONECTA=DOC_CONECTA, AVISO_IA_LGPD=AVISO_IA_LGPD,
)


def _uri(texto: str) -> str:
    """Equivalente ao encodeURIComponent do JavaScript."""
    return quote(texto or "", safe="-_.!~*'()")


def mailto(assunto: str, corpo: str) -> dict:
    """Link mailto:. Se o corpo codificado passar de LIMITE_MAILTO, vai só o assunto
    (alguns programas de e-mail cortam links longos) e `curto` = True avisa a página."""
    corpo_cod = _uri(corpo)
    if len(corpo_cod) > LIMITE_MAILTO:
        return {"href": f"mailto:?subject={_uri(assunto)}", "curto": True}
    return {"href": f"mailto:?subject={_uri(assunto)}&body={corpo_cod}", "curto": False}


def _url_sicaf() -> Optional[str]:
    try:
        for p in _portais.carregar().get("federais", []):
            if p.get("tipo") == "sicaf" and p.get("url"):
                return p["url"]
    except Exception:
        pass
    return None


templates.env.globals.update(URL_SICAF=_url_sicaf())


# ----------------------------------------------------------------- limites e cabeçalhos
def _limite_corpo(caminho: str) -> int:
    if caminho == "/conferir":
        return MAX_ARQUIVOS * MAX_MB * MB + 2 * MB
    if caminho == "/mutirao":
        return MAX_CSVS * MAX_KB_CSV * 1024 + MB
    if caminho == "/mutirao/plano.csv":
        return LIMITE_PLANO + 64 * 1024
    return LIMITE_PADRAO


def _pagina_413(limite: int) -> str:
    tam = f"{limite / MB:.0f} MB" if limite >= MB else f"{limite // 1024} KB"
    return templates.env.get_template("erro.html").render(
        titulo="Envio grande demais.",
        mensagem=f"O limite desta página é de {tam} por envio. Envie menos arquivos de cada vez "
                 f"(até {MAX_ARQUIVOS} PDFs de {MAX_MB} MB) ou arquivos menores.",
        voltar="/", rotulo_voltar="Voltar")


app.add_middleware(LimiteCorpo, limite_para=_limite_corpo, pagina_html=_pagina_413)
app.add_middleware(CabecalhosSeguranca)   # adicionado por último = mais externo (vale também p/ 413)

# ----------------------------------------------------------------- armazenamento temporário
_resultados: dict[str, dict] = {}
_trava = threading.Lock()


def _guardar(dados: dict) -> str:
    chave = secrets.token_urlsafe(16)
    agora = time.time()
    with _trava:
        for k in [k for k, v in _resultados.items() if agora - v["criado"] > TTL_RESULTADO]:
            del _resultados[k]
        while len(_resultados) >= MAX_RESULTADOS:
            del _resultados[min(_resultados, key=lambda k: _resultados[k]["criado"])]
        _resultados[chave] = {**dados, "criado": agora}
    return chave


def _obter(chave: str) -> Optional[dict]:
    with _trava:
        d = _resultados.get(chave)
    if d and time.time() - d["criado"] <= TTL_RESULTADO:
        return d
    return None


# ----------------------------------------------------------------- utilidades
def _ia_ligada() -> bool:
    try:
        return bool(_ia and _ia.habilitada())
    except Exception:
        return False


def _conecta_ok() -> bool:
    try:
        return bool(_conecta and _conecta.configurado())
    except Exception:
        return False


def _competencia_padrao() -> str:
    hoje = date.today()
    mes = (hoje.month - 2) % 12 + 1
    ano = hoje.year if hoje.month > 1 else hoje.year - 1
    return f"{mes:02d}/{ano}"


def _contexto_form(request: Request, valores: dict | None = None, erros: list[str] | None = None):
    v = {"numero": "", "cnpj": "", "razao_social": "", "uf": "DF", "municipio": "",
         "fiscal": "", "competencia": _competencia_padrao(), "orgao": "", "dias_alerta": 15,
         "observacoes": "", "exigidas": sorted(PADRAO), "aceitar_sicaf": False}
    v.update(valores or {})
    return {"request": request, "v": v, "erros": erros or [], "ufs": UFS,
            "tipos": TIPOS_EXIGIVEIS, "ia_ligada": _ia_ligada(), "conecta_ok": _conecta_ok(),
            "max_arquivos": MAX_ARQUIVOS, "max_mb": MAX_MB}


def _nome_base(contrato: Contrato) -> str:
    num = so_digitos(contrato.numero) or "contrato"
    comp = (contrato.competencia or "").replace("/", "-") or date.today().isoformat()
    return f"checklist_{num}_{comp}"


def _apagar(caminho: str) -> None:
    try:
        os.remove(caminho)
        os.rmdir(os.path.dirname(caminho))
    except OSError:
        pass


# ----------------------------------------------------------------- rotas
@app.get("/", response_class=HTMLResponse)
def inicio(request: Request):
    return templates.TemplateResponse(request, "index.html", _contexto_form(request))


@app.get("/como-usar", response_class=HTMLResponse)
def como_usar(request: Request):
    return templates.TemplateResponse(request, "como_usar.html", {"request": request})


@app.get("/saude")
def saude():
    return {"status": "ok"}


@app.get("/api/portais")
def api_portais(uf: str = "", municipio: str = "", tipos: str = "", sicaf: str = ""):
    if _portais is None or not uf:
        return {"portais": []}
    try:
        lista = _portais.portais_para(uf, municipio or "")
    except Exception:
        return JSONResponse({"portais": [], "erro": "catálogo indisponível"}, status_code=500)
    filtro = {t for t in tipos.split(",") if t}
    destacar_sicaf = sicaf in ("1", "true", "sim")
    saida = []
    for p in lista:
        tipo = p.get("tipo", "")
        if filtro and tipo not in filtro and tipo != "outra" and not (destacar_sicaf and tipo == "sicaf"):
            continue
        try:
            rotulo = TipoCertidao(tipo).rotulo
        except ValueError:
            rotulo = tipo
        saida.append({"nome": p.get("nome"), "tipo": tipo, "rotulo": rotulo,
                      "url": p.get("url"), "captcha": p.get("captcha"),
                      "observacao": p.get("observacao"), "verificado_em": p.get("verificado_em"),
                      "url_verificacao": p.get("url_verificacao"),
                      "destaque": destacar_sicaf and tipo == "sicaf"})
    saida.sort(key=lambda p: not p["destaque"])   # SICAF no topo quando aceito
    return {"portais": saida}


@app.post("/api/conecta")
def api_conecta(request: Request, cnpj: str = Form(...)):
    if not _mesma_origem(request):
        return JSONResponse({"ok": False, "mensagem": "Pedido recusado: origem não permitida."},
                            status_code=403)
    if not _conecta_ok():
        return JSONResponse({"ok": False, "mensagem": "Integração com o Conecta não configurada."},
                            status_code=400)
    d = so_digitos(cnpj)
    if not cnpj_valido(d):
        return JSONResponse({"ok": False, "mensagem": "CNPJ inválido."}, status_code=400)
    ip = request.client.host if request.client else "desconhecido"
    if not _dentro_do_limite(ip):   # mesmo contador de /conecta/cnd.pdf
        return JSONResponse({"ok": False, "mensagem": f"Limite de {CONECTA_LIMITE_HORA} consultas por "
                             "hora atingido. Tente mais tarde ou use o portal da Receita Federal."},
                            status_code=429)
    try:
        r = _conecta.consultar_cnd(d)
    except Exception:
        r = {"ok": False, "mensagem": "Falha na consulta ao Conecta."}
    r.pop("bruto", None)
    return {k: (str(v) if isinstance(v, date) else v) for k, v in r.items()}


@app.post("/conferir", response_class=HTMLResponse)
async def conferir(
    request: Request,
    numero: str = Form(""),
    cnpj: str = Form(""),
    razao_social: str = Form(""),
    uf: str = Form("DF"),
    municipio: str = Form(""),
    fiscal: str = Form(""),
    competencia: str = Form(""),
    orgao: str = Form(""),
    dias_alerta: int = Form(15),
    observacoes: str = Form(""),
    aceitar_sicaf: str = Form(""),
    exigidas: list[str] = Form(default=[]),
    arquivos: list[UploadFile] = File(default=[]),
):
    valores = {"numero": numero.strip(), "cnpj": cnpj.strip(), "razao_social": razao_social.strip(),
               "uf": uf if uf in UFS else "DF", "municipio": municipio.strip(),
               "fiscal": fiscal.strip(), "competencia": competencia.strip(),
               "orgao": orgao.strip(), "dias_alerta": max(0, min(int(dias_alerta), 90)),
               "observacoes": observacoes.strip()[:2000], "exigidas": exigidas,
               "aceitar_sicaf": bool(aceitar_sicaf)}
    arquivos = [a for a in arquivos if a and a.filename]

    erros = []
    if not valores["numero"]:
        erros.append("Informe o número do contrato.")
    if not cnpj_valido(so_digitos(cnpj)):
        erros.append("CNPJ inválido: confira os dígitos.")
    if not valores["razao_social"]:
        erros.append("Informe a razão social da contratada.")
    if not valores["municipio"]:
        erros.append("Informe o município da sede.")
    tipos = [t for t in TIPOS_EXIGIVEIS if t.value in exigidas]
    if not tipos:
        erros.append("Marque ao menos uma certidão exigida.")
    if not arquivos:
        erros.append("Envie ao menos um PDF de certidão.")
    if len(arquivos) > MAX_ARQUIVOS:
        erros.append(f"Envie no máximo {MAX_ARQUIVOS} arquivos por vez.")

    certs = []
    if not erros:
        with tempfile.TemporaryDirectory(prefix="certidoes_") as tmp:
            caminhos, nomes = [], []
            for i, a in enumerate(arquivos):
                conteudo = await a.read(MAX_MB * 1024 * 1024 + 1)
                nome = os.path.basename(a.filename) or f"arquivo_{i}.pdf"
                if len(conteudo) > MAX_MB * 1024 * 1024:
                    erros.append(f"{nome}: maior que {MAX_MB} MB.")
                    continue
                if not conteudo.startswith(b"%PDF"):
                    erros.append(f"{nome}: não é um PDF.")
                    continue
                destino = os.path.join(tmp, f"{i:02d}.pdf")
                with open(destino, "wb") as f:
                    f.write(conteudo)
                caminhos.append(destino)
                nomes.append(nome)
            if not erros:
                certs = ler_varios(caminhos)
                for c, nome in zip(certs, nomes):
                    c.arquivo = nome
                    c.texto = ""   # não guarda o texto do PDF em memória

    if erros:
        return templates.TemplateResponse(
            request, "index.html", _contexto_form(request, valores, erros), status_code=422)

    contrato = Contrato(numero=valores["numero"], cnpj=so_digitos(cnpj),
                        razao_social=valores["razao_social"], uf_sede=valores["uf"],
                        municipio_sede=valores["municipio"], fiscal=valores["fiscal"],
                        competencia=valores["competencia"], exigidas=tipos,
                        aceitar_sicaf=valores["aceitar_sicaf"])
    resultado = validar(contrato, certs, dias_alerta=valores["dias_alerta"])
    chave = _guardar({"resultado": resultado, "certs": certs, "orgao": valores["orgao"],
                      "observacoes": valores["observacoes"]})
    return RedirectResponse(f"/resultado/{chave}", status_code=303)


@app.get("/resultado/{chave}", response_class=HTMLResponse)
def ver_resultado(request: Request, chave: str):
    d = _obter(chave)
    if not d:
        return templates.TemplateResponse(request, "expirado.html", {"request": request},
                                          status_code=404)
    resultado = d["resultado"]
    extras = [{"cert": x, "nota": nota_extra(x, resultado), "alerta": bool(alerta_extra(x, resultado))}
              for x in resultado.extras]
    grupo = planejamento.grupo_de_resultado(resultado)
    solicitacao = None
    if grupo["a_emitir"]:
        texto = planejamento.texto_solicitacao(grupo, orgao=d["orgao"])
        solicitacao = {"texto": texto,
                       "mailto": mailto(planejamento.assunto_solicitacao(grupo), texto)}
    return templates.TemplateResponse(request, "resultado.html", {
        "request": request, "chave": chave, "r": resultado, "resumo": resumo(resultado),
        "extras": extras, "certs": d["certs"], "orgao": d["orgao"],
        "observacoes": d["observacoes"], "solicitacao": solicitacao,
    })


@app.get("/resultado/{chave}/checklist.pdf")
def baixar_pdf(chave: str):
    d = _obter(chave)
    if not d:
        return JSONResponse({"erro": "Resultado expirado. Refaça a conferência."}, status_code=404)
    nome = _nome_base(d["resultado"].contrato) + ".pdf"
    caminho = os.path.join(tempfile.mkdtemp(prefix="atesto_"), nome)
    gerar_pdf(d["resultado"], caminho, orgao=d["orgao"], observacoes=d["observacoes"])
    return FileResponse(caminho, media_type="application/pdf", filename=nome,
                        background=BackgroundTask(_apagar, caminho))


@app.get("/resultado/{chave}/controle.csv")
def baixar_csv(chave: str):
    d = _obter(chave)
    if not d:
        return JSONResponse({"erro": "Resultado expirado. Refaça a conferência."}, status_code=404)
    nome = _nome_base(d["resultado"].contrato) + ".csv"
    caminho = os.path.join(tempfile.mkdtemp(prefix="atesto_"), nome)
    gerar_csv([d["resultado"]], caminho)
    return FileResponse(caminho, media_type="text/csv", filename=nome,
                        background=BackgroundTask(_apagar, caminho))


# ----------------------------------------------------------------- Conecta: PDF da CND federal
def _erro_html(request: Request, titulo: str, mensagem: str, status: int = 400,
               voltar: str = "/", rotulo_voltar: str = "Voltar"):
    return templates.TemplateResponse(request, "erro.html", {
        "request": request, "titulo": titulo, "mensagem": mensagem, "voltar": voltar,
        "rotulo_voltar": rotulo_voltar}, status_code=status)


def _mesma_origem(request: Request) -> bool:
    """Origin (ou, na falta, Referer) precisa ser do mesmo host da requisição."""
    hosts = {request.headers.get("host", "").lower(), request.headers.get("x-forwarded-host", "").lower()}
    hosts.discard("")
    origem = request.headers.get("origin")
    if origem and origem != "null":
        return urlsplit(origem).netloc.lower() in hosts
    ref = request.headers.get("referer")
    if ref:
        return urlsplit(ref).netloc.lower() in hosts
    return False


_consultas_conecta: dict[str, collections.deque] = {}
_trava_conecta = threading.Lock()


def _dentro_do_limite(ip: str) -> bool:
    """No máximo CONECTA_LIMITE_HORA consultas por IP na última hora (memória do processo)."""
    agora = time.time()
    with _trava_conecta:
        for k in [k for k, v in _consultas_conecta.items() if not v or agora - v[-1] > 3600]:
            del _consultas_conecta[k]
        fila = _consultas_conecta.setdefault(ip, collections.deque())
        while fila and agora - fila[0] > 3600:
            fila.popleft()
        if len(fila) >= CONECTA_LIMITE_HORA:
            return False
        fila.append(agora)
        return True


@app.post("/conecta/cnd.pdf")
def conecta_cnd_pdf(request: Request, cnpj: str = Form("")):
    if not _mesma_origem(request):
        return _erro_html(request, "Pedido recusado.",
                          "Use o botão \"Baixar CND federal (PDF)\" na página de conferência.", status=403)
    if not _conecta_ok():
        return _erro_html(request, "Integração com o Conecta não configurada.",
                          "Use o portal da Receita Federal (com captcha) ou peça a adesão do órgão "
                          "à API Consulta CND.")
    d = so_digitos(cnpj)
    if not cnpj_valido(d):
        return _erro_html(request, "CNPJ inválido.",
                          "Preencha o CNPJ da contratada na seção 1 e tente de novo.")
    ip = request.client.host if request.client else "desconhecido"
    if not _dentro_do_limite(ip):
        return _erro_html(request, "Limite de consultas atingido.",
                          f"Por segurança, são permitidas até {CONECTA_LIMITE_HORA} consultas ao Conecta "
                          "por hora a partir deste computador. Tente mais tarde ou use o portal da Receita "
                          "Federal.", status=429)
    pasta = tempfile.mkdtemp(prefix="conecta_")
    try:
        r = _conecta.consultar_cnd(d, salvar_pdf_em=pasta)
    except Exception:
        r = {"ok": False, "mensagem": "Falha na consulta ao Conecta."}
    caminho = r.get("caminho_pdf") if r.get("ok") else None
    if not caminho or not os.path.isfile(caminho):
        shutil.rmtree(pasta, ignore_errors=True)
        msg = r.get("mensagem") or "A consulta não devolveu o PDF da certidão."
        return _erro_html(request, "Não foi possível obter a CND federal pelo Conecta.",
                          f"{msg} Emita a certidão pelo portal da Receita Federal.", status=502)
    nome = f"cnd_federal_{d}_{date.today():%Y%m%d}.pdf"
    return FileResponse(caminho, media_type="application/pdf", filename=nome,
                        background=BackgroundTask(shutil.rmtree, pasta, ignore_errors=True))


# ----------------------------------------------------------------- mutirão mensal
def _contexto_mutirao(request: Request, v: dict | None = None, erros: list[str] | None = None,
                      **extra) -> dict:
    hoje = date.today()
    base = {"ate": planejamento.data_corte_padrao(hoje).isoformat(), "orgao": "", "prazo": 5,
            "aceitar_sicaf": False}
    base.update(v or {})
    return {"request": request, "v": base, "erros": erros or [], "grupos": None, **extra}


@app.get("/mutirao", response_class=HTMLResponse)
def mutirao(request: Request):
    return templates.TemplateResponse(request, "mutirao.html", _contexto_mutirao(request))


@app.post("/mutirao", response_class=HTMLResponse)
async def mutirao_planejar(
    request: Request,
    ate: str = Form(""),
    orgao: str = Form(""),
    prazo: str = Form("5"),
    aceitar_sicaf: str = Form(""),
    csvs: list[UploadFile] = File(default=[]),
):
    erros: list[str] = []
    try:
        data_corte = date.fromisoformat(ate.strip())
    except ValueError:
        data_corte = planejamento.data_corte_padrao()
        erros.append("Data de corte inválida.")
    try:
        prazo_dias = max(1, min(int(prazo), 60))
    except ValueError:
        prazo_dias = 5
    v = {"ate": data_corte.isoformat(), "orgao": orgao.strip()[:200], "prazo": prazo_dias,
         "aceitar_sicaf": bool(aceitar_sicaf)}
    arquivos = [a for a in csvs if a and a.filename]
    if not arquivos:
        erros.append("Envie ao menos uma planilha de controle (CSV) gerada pelo sistema.")
    if len(arquivos) > MAX_CSVS:
        erros.append(f"Envie no máximo {MAX_CSVS} planilhas por vez.")
    conteudos: list[bytes] = []
    if not erros:
        for a in arquivos:
            dados = await a.read(MAX_KB_CSV * 1024 + 1)
            if len(dados) > MAX_KB_CSV * 1024:
                erros.append(f"{os.path.basename(a.filename)}: maior que {MAX_KB_CSV // 1024} MB.")
            else:
                conteudos.append(dados)
    linhas = planejamento.ler_csvs(conteudos) if not erros else []
    if not erros and not linhas:
        erros.append("Nenhuma linha válida encontrada. Use a planilha de controle (CSV) baixada "
                     "na página de resultado da conferência.")
    if erros:
        return templates.TemplateResponse(request, "mutirao.html",
                                          _contexto_mutirao(request, v, erros), status_code=422)

    grupos = planejamento.planejar(linhas, ate=data_corte, hoje=date.today(),
                                   aceitar_sicaf=v["aceitar_sicaf"])
    for n, g in enumerate(grupos, start=1):
        texto = planejamento.texto_solicitacao(g, prazo_dias=prazo_dias, orgao=v["orgao"])
        g["solicitacao"] = texto
        g["mailto"] = mailto(planejamento.assunto_solicitacao(g), texto)
        g["dom_id"] = f"g{n}"
    plano_json = json.dumps(planejamento.linhas_plano(grupos), ensure_ascii=False,
                            separators=(",", ":"))
    return templates.TemplateResponse(request, "mutirao.html", _contexto_mutirao(
        request, v, grupos=grupos, totais=planejamento.totalizar(grupos), data_corte=data_corte,
        plano_json=plano_json if len(plano_json.encode()) <= LIMITE_PLANO else None))


@app.post("/mutirao/plano.csv")
def mutirao_plano_csv(request: Request, plano: str = Form(""), ate: str = Form("")):
    erro = None
    if not plano or len(plano.encode()) > LIMITE_PLANO:
        erro = "Plano vazio ou grande demais."
    else:
        try:
            conteudo = planejamento.csv_de_linhas(json.loads(plano))
        except (ValueError, TypeError):
            erro = "Plano em formato inválido."
    if erro:
        return _erro_html(request, "Não foi possível gerar a lista do mutirão.",
                          f"{erro} Planeje o mutirão de novo.", voltar="/mutirao",
                          rotulo_voltar="Planejar de novo")
    try:
        nome = f"mutirao_{date.fromisoformat(ate):%Y-%m-%d}.csv"
    except ValueError:
        nome = "mutirao.csv"
    return Response(("\ufeff" + conteudo).encode("utf-8"), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{nome}"'})
