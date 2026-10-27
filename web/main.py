"""Interface web no Padrão Digital de Governo (gov.br DS), para deploy no Railway.

Rodar localmente:  uvicorn web.main:app --reload
Produção:          uvicorn web.main:app --host 0.0.0.0 --port $PORT
"""
from __future__ import annotations

import os
import secrets
import tempfile
import threading
import time
from datetime import date
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.background import BackgroundTask

from certidoes.atesto import gerar_csv, gerar_pdf
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
    ICONE_SEMAFORO=ICONE_SEMAFORO, formatar_data=formatar_data, formatar_cnpj=formatar_cnpj,
    DOC_CONECTA=DOC_CONECTA, AVISO_IA_LGPD=AVISO_IA_LGPD,
)

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
         "observacoes": "", "exigidas": sorted(PADRAO)}
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
def api_portais(uf: str = "", municipio: str = "", tipos: str = ""):
    if _portais is None or not uf:
        return {"portais": []}
    try:
        lista = _portais.portais_para(uf, municipio or "")
    except Exception:
        return JSONResponse({"portais": [], "erro": "catálogo indisponível"}, status_code=500)
    filtro = {t for t in tipos.split(",") if t}
    saida = []
    for p in lista:
        tipo = p.get("tipo", "")
        if filtro and tipo not in filtro and tipo != "outra":
            continue
        try:
            rotulo = TipoCertidao(tipo).rotulo
        except ValueError:
            rotulo = tipo
        saida.append({"nome": p.get("nome"), "tipo": tipo, "rotulo": rotulo,
                      "url": p.get("url"), "captcha": p.get("captcha"),
                      "observacao": p.get("observacao"), "verificado_em": p.get("verificado_em")})
    return {"portais": saida}


@app.post("/api/conecta")
def api_conecta(cnpj: str = Form(...)):
    if not _conecta_ok():
        return JSONResponse({"ok": False, "mensagem": "Integração com o Conecta não configurada."},
                            status_code=400)
    d = so_digitos(cnpj)
    if not cnpj_valido(d):
        return JSONResponse({"ok": False, "mensagem": "CNPJ inválido."}, status_code=400)
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
    exigidas: list[str] = Form(default=[]),
    arquivos: list[UploadFile] = File(default=[]),
):
    valores = {"numero": numero.strip(), "cnpj": cnpj.strip(), "razao_social": razao_social.strip(),
               "uf": uf if uf in UFS else "DF", "municipio": municipio.strip(),
               "fiscal": fiscal.strip(), "competencia": competencia.strip(),
               "orgao": orgao.strip(), "dias_alerta": max(0, min(int(dias_alerta), 90)),
               "observacoes": observacoes.strip()[:2000], "exigidas": exigidas}
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
                        competencia=valores["competencia"], exigidas=tipos)
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
    return templates.TemplateResponse(request, "resultado.html", {
        "request": request, "chave": chave, "r": resultado, "resumo": resumo(resultado),
        "extras": extras, "certs": d["certs"], "orgao": d["orgao"],
        "observacoes": d["observacoes"],
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
