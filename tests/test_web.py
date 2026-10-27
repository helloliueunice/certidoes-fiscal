"""Testes da interface web (FastAPI + gov.br DS)."""
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from web.main import app

AMOSTRAS = Path(__file__).parent / "amostras"
CNPJ = "12.345.678/0001-95"


@pytest.fixture(scope="module")
def cliente():
    if not (AMOSTRAS / "federal_negativa.pdf").exists():
        from tests.gerar_amostras import gerar
        gerar(AMOSTRAS)
    return TestClient(app)


def _form(**extra):
    base = {"numero": "001/2026", "cnpj": CNPJ, "razao_social": "EMPRESA EXEMPLO DE SERVIÇOS LTDA",
            "uf": "SP", "municipio": "São Paulo", "fiscal": "Fulano", "competencia": "10/2026",
            "orgao": "Órgão Exemplo", "dias_alerta": "15",
            "exigidas": ["federal", "fgts", "trabalhista", "estadual", "municipal"]}
    base.update(extra)
    return base


def _arquivos(*nomes):
    return [("arquivos", (f"{n}.pdf", (AMOSTRAS / f"{n}.pdf").read_bytes(), "application/pdf")) for n in nomes]


def test_inicio_usa_govbr_ds(cliente):
    r = cliente.get("/")
    assert r.status_code == 200
    assert "/static/govbr-ds/core.min.css" in r.text
    assert "br-header" in r.text and "br-footer" in r.text
    assert cliente.get("/static/govbr-ds/core.min.css").status_code == 200


def test_saude(cliente):
    assert cliente.get("/saude").json() == {"status": "ok"}


def test_portais(cliente):
    r = cliente.get("/api/portais", params={"uf": "SP", "municipio": "São Paulo"}).json()
    tipos = {p["tipo"] for p in r["portais"]}
    assert {"federal", "estadual", "municipal"} <= tipos


def test_conferencia_completa_apto(cliente):
    ok = ["federal_negativa", "fgts_regular", "cndt_negativa", "estadual_sp_pge",
          "estadual_sp_sefaz", "municipal_sp"]
    r = cliente.post("/conferir", data=_form(), files=_arquivos(*ok), follow_redirects=False)
    assert r.status_code == 303
    url = r.headers["location"]
    pagina = cliente.get(url)
    assert "Nenhuma pendência impeditiva" in pagina.text
    pdf = cliente.get(url + "/checklist.pdf")
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")
    csv = cliente.get(url + "/controle.csv")
    assert csv.status_code == 200 and "001/2026" in csv.content.decode("utf-8-sig")


def test_conferencia_com_pendencia(cliente):
    r = cliente.post("/conferir", data=_form(), files=_arquivos("federal_vencida", "cndt_positiva"))
    assert r.status_code == 200
    assert "Há pendências" in r.text and "PENDENTE" in r.text


def test_validacao_cnpj_e_arquivo(cliente):
    r = cliente.post("/conferir", data=_form(cnpj="11.111.111/1111-11"), files=_arquivos("fgts_regular"))
    assert r.status_code == 422 and "CNPJ inválido" in r.text
    falso = [("arquivos", ("x.pdf", b"nao sou pdf", "application/pdf"))]
    r = cliente.post("/conferir", data=_form(), files=falso)
    assert r.status_code == 422 and "não é um PDF" in r.text


def test_resultado_expirado(cliente):
    assert cliente.get("/resultado/inexistente").status_code == 404
    assert cliente.get("/resultado/inexistente/checklist.pdf").status_code == 404


def test_conecta_nao_configurado(cliente):
    r = cliente.post("/api/conecta", data={"cnpj": CNPJ}, headers={"Origin": "http://testserver"})
    assert r.status_code == 400


# ----------------------------------------------------------------- SICAF, solicitação, mutirão, Conecta
import html
import os
import re
from datetime import date, timedelta
from urllib.parse import unquote

import web.main as wm
from certidoes import planejamento


def test_cabecalho_e_checkbox_sicaf(cliente):
    r = cliente.get("/")
    assert 'href="/mutirao"' in r.text and "Planejar emissão do mês" in r.text
    m = re.search(r'<input id="aceitar_sicaf"[^>]*>', r.text)
    assert m and "checked" not in m.group(0)
    ajuda = re.search(r'id="aceitar-sicaf-ajuda">(.*?)</p>', r.text, re.S).group(1)
    assert "por você, fiscal" in ajuda and "na data do atesto" in ajuda
    assert "simples consulta" in ajuda and "Automática" in ajuda and "Manual" in ajuda
    assert "inseridos pelo fornecedor" in ajuda
    assert 'href="https://www.gov.br/compras/' in ajuda


def test_conferir_repassa_aceitar_sicaf(cliente, monkeypatch):
    vistos = []
    original = wm.validar

    def espiao(contrato, certs, **kw):
        vistos.append(contrato.aceitar_sicaf)
        return original(contrato, certs, **kw)

    monkeypatch.setattr(wm, "validar", espiao)
    cliente.post("/conferir", data=_form(aceitar_sicaf="1"), files=_arquivos("sicaf"))
    cliente.post("/conferir", data=_form(), files=_arquivos("sicaf"))
    assert vistos == [True, False]


def test_portais_sicaf_no_topo(cliente):
    tipos = "federal,fgts,trabalhista,estadual,municipal"
    r = cliente.get("/api/portais", params={"uf": "SP", "municipio": "São Paulo", "tipos": tipos,
                                            "sicaf": "1"}).json()["portais"]
    assert r[0]["tipo"] == "sicaf" and r[0]["destaque"] is True
    assert sum(p["destaque"] for p in r) == 1
    r = cliente.get("/api/portais", params={"uf": "SP", "municipio": "São Paulo", "tipos": tipos}).json()["portais"]
    assert all(p["tipo"] != "sicaf" and not p["destaque"] for p in r)


def test_resultado_texto_de_solicitacao(cliente):
    r = cliente.post("/conferir", data=_form(), files=_arquivos("federal_vencida", "cndt_positiva"))
    assert "Texto de solicitação à contratada" in r.text
    assert 'id="texto-solicitacao"' in r.text and "MINUTA" in r.text
    assert "art. 92, XVI" in r.text and "retenção" not in r.text.lower()
    m = re.search(r'href="(mailto:\?subject=[^"]+)"', r.text)
    assert m
    href = m.group(1).replace("&amp;", "&")
    if "&body=" in href:
        corpo = unquote(href.split("&body=")[1])
        assert "Contrato nº 001/2026" in corpo and "Trabalhista (CNDT - TST)" in corpo
    else:   # corpo longo: só assunto + aviso
        assert "cole-o no e-mail" in r.text
    assert '/static/app.js' in r.text


def _csv_de_conferencia(cliente, numero, arquivos, **extra):
    r = cliente.post("/conferir", data=_form(numero=numero, **extra), files=_arquivos(*arquivos),
                     follow_redirects=False)
    return cliente.get(r.headers["location"] + "/controle.csv").content


def test_mutirao_formulario(cliente):
    r = cliente.get("/mutirao")
    assert r.status_code == 200
    assert f'value="{planejamento.data_corte_padrao().isoformat()}"' in r.text
    assert 'name="csvs"' in r.text and "Peça à contratada" in r.text and "Use o SICAF" in r.text
    assert "não contorna captcha" in r.text
    assert "Plano até" not in r.text


def test_mutirao_plano_completo(cliente):
    novo = _csv_de_conferencia(cliente, "001/2026", ["federal_negativa", "fgts_regular", "cndt_negativa"])
    assert b"validade_iso" in novo
    antigo = ("data_referencia;competencia;contrato;cnpj;razao_social;fiscal;item;semaforo;resultado;"
              "situacao;validade;codigo_controle;arquivo;mensagem;apto_atesto\r\n"
              "01/09/2026;08/2026;777/2025;11.222.333/0001-81;ALFA LTDA;Fulano;Fazenda Municipal;"
              "verde;OK;Negativa;05/09/2026;;m.pdf;ok;sim\r\n").encode("utf-8-sig")
    ate = date.today() + timedelta(days=20)
    r = cliente.post("/mutirao", data={"ate": ate.isoformat(), "orgao": "Órgão X", "prazo": "7"},
                     files=[("csvs", ("a.csv", novo, "text/csv")), ("csvs", ("b.csv", antigo, "text/csv"))])
    assert r.status_code == 200
    t = r.text
    assert f"Plano até {ate:%d/%m/%Y}" in t
    for rotulo in ("Contratadas", "Ainda válidas", "A emitir", "Via SICAF", "Captchas evitados"):
        assert rotulo in t
    assert "ALFA LTDA" in t and "EMPRESA EXEMPLO" in t and "11.222.333/0001-81" in t
    assert "Abrir portal" in t and "com captcha" in t and "Portais com captcha são acessados por você" in t
    assert 'data-copiar="g1-cnpj"' in t and "Copiar texto de solicitação à contratada" in t
    assert re.search(r'data-chave="\d{14}\|[^|"]*\|\w+\|' + ate.isoformat() + '"', t)
    assert 'href="mailto:?subject=' in t and "7 dias úteis" in t and "Órgão X" in t
    assert "data:text/csv" not in t
    assert 'action="/mutirao/plano.csv"' in t
    plano_json = html.unescape(re.search(r'name="plano" value="([^"]*)"', t).group(1))
    r2 = cliente.post("/mutirao/plano.csv", data={"plano": plano_json, "ate": ate.isoformat()})
    assert r2.status_code == 200 and r2.headers["content-type"].startswith("text/csv")
    assert f'mutirao_{ate.isoformat()}.csv' in r2.headers["content-disposition"]
    plano = r2.content.decode("utf-8")
    assert plano.startswith("\ufeffcontratada;cnpj;contrato") and "ALFA LTDA" in plano
    assert "<details" in t and "/static/mutirao.js" in t
    assert cliente.get("/static/mutirao.js").status_code == 200


def test_mutirao_sicaf_forcado(cliente):
    novo = _csv_de_conferencia(cliente, "002/2026", ["federal_vencida"])
    r = cliente.post("/mutirao", data={"ate": (date.today() + timedelta(days=10)).isoformat(),
                                       "aceitar_sicaf": "1"},
                     files=[("csvs", ("a.csv", novo, "text/csv"))])
    assert r.status_code == 200 and "consultar SICAF" in r.text and "Abrir SICAF" in r.text


def test_mutirao_erros(cliente):
    r = cliente.post("/mutirao", data={"ate": "2026-11-10"})
    assert r.status_code == 422 and "Envie ao menos uma planilha" in r.text
    r = cliente.post("/mutirao", data={"ate": "2026-11-10"},
                     files=[("csvs", ("x.csv", b"qualquer;coisa\n1;2", "text/csv"))])
    assert r.status_code == 422 and "Nenhuma linha válida" in r.text
    r = cliente.post("/mutirao", data={"ate": "ontem"},
                     files=[("csvs", ("x.csv", b"a;b", "text/csv"))])
    assert r.status_code == 422 and "Data de corte inválida" in r.text


ORIGEM = {"Origin": "http://testserver"}


def test_conecta_pdf_nao_configurado(cliente):
    assert cliente.get("/conecta/cnd.pdf", params={"cnpj": CNPJ}).status_code == 405
    r = cliente.post("/conecta/cnd.pdf", data={"cnpj": CNPJ}, headers=ORIGEM)
    assert r.status_code == 400 and "não configurada" in r.text and "br-message" in r.text


def _conecta_falso(monkeypatch, pastas):
    def falso(cnpj, salvar_pdf_em=None):
        pastas.append(salvar_pdf_em)
        caminho = os.path.join(salvar_pdf_em, "cnd.pdf")
        with open(caminho, "wb") as f:
            f.write(b"%PDF-1.4 teste")
        return {"ok": True, "caminho_pdf": caminho, "mensagem": "Certidão emitida"}

    monkeypatch.setattr(wm, "_conecta_ok", lambda: True)
    monkeypatch.setattr(wm._conecta, "consultar_cnd", falso)
    monkeypatch.setattr(wm, "_consultas_conecta", {})


def test_conecta_pdf_ok_e_erro(cliente, monkeypatch):
    pastas = []
    _conecta_falso(monkeypatch, pastas)
    pagina = cliente.get("/").text
    assert "Baixar CND federal (PDF)" in pagina
    assert re.search(r'<form id="form-cnd" method="post" action="/conecta/cnd.pdf"', pagina)
    assert 'form="form-cnd"' in pagina and 'name="cnpj" id="cnd-cnpj"' in pagina
    r = cliente.post("/conecta/cnd.pdf", data={"cnpj": CNPJ}, headers=ORIGEM)
    assert r.status_code == 200 and r.content.startswith(b"%PDF")
    assert r.headers["content-type"] == "application/pdf"
    assert "cnd_federal_12345678000195" in r.headers["content-disposition"]
    assert not os.path.exists(pastas[0])     # apagado depois do envio
    r = cliente.post("/conecta/cnd.pdf", data={"cnpj": CNPJ}, headers={"Referer": "http://testserver/"})
    assert r.status_code == 200              # Referer do mesmo host também vale

    assert cliente.post("/conecta/cnd.pdf", data={"cnpj": "123"}, headers=ORIGEM).status_code == 400

    monkeypatch.setattr(wm._conecta, "consultar_cnd",
                        lambda cnpj, salvar_pdf_em=None: {"ok": False, "mensagem": "Contribuinte não cadastrado"})
    r = cliente.post("/conecta/cnd.pdf", data={"cnpj": CNPJ}, headers=ORIGEM)
    assert r.status_code == 502 and "Contribuinte não cadastrado" in r.text and "portal da Receita" in r.text


def test_conecta_pdf_origem(cliente, monkeypatch):
    pastas = []
    _conecta_falso(monkeypatch, pastas)
    for cab in ({}, {"Origin": "https://malicioso.example"}, {"Referer": "https://malicioso.example/x"},
                {"Origin": "null"}):
        r = cliente.post("/conecta/cnd.pdf", data={"cnpj": CNPJ}, headers=cab)
        assert r.status_code == 403 and "Pedido recusado" in r.text, cab
    assert pastas == []


def test_conecta_pdf_limite_por_ip(cliente, monkeypatch):
    pastas = []
    _conecta_falso(monkeypatch, pastas)
    monkeypatch.setattr(wm, "CONECTA_LIMITE_HORA", 3)
    codigos = [cliente.post("/conecta/cnd.pdf", data={"cnpj": CNPJ}, headers=ORIGEM).status_code
               for _ in range(4)]
    assert codigos == [200, 200, 200, 429]
    r = cliente.post("/conecta/cnd.pdf", data={"cnpj": CNPJ}, headers=ORIGEM)
    assert r.status_code == 429 and "Limite de consultas" in r.text and "br-message" in r.text
    assert len(pastas) == 3


# ----------------------------------------------------------------- segurança
def test_cabecalhos_de_seguranca(cliente):
    for url in ("/", "/mutirao", "/como-usar", "/saude", "/static/app.js"):
        h = cliente.get(url).headers
        csp = h["content-security-policy"]
        assert "default-src 'self'" in csp and "script-src 'self';" in csp
        assert "frame-ancestors 'none'" in csp and "form-action 'self' mailto:" in csp
        assert "'unsafe-inline'" not in csp
        assert h["x-content-type-options"] == "nosniff"
        assert h["x-frame-options"] == "DENY"
        assert h["referrer-policy"] == "strict-origin-when-cross-origin"
        assert "camera=()" in h["permissions-policy"]


def test_templates_sem_script_estilo_ou_handler_inline():
    pasta = Path(__file__).resolve().parent.parent / "web" / "templates"
    for arq in pasta.glob("*.html"):
        t = arq.read_text(encoding="utf-8")
        assert not re.search(r"<script(?![^>]*\bsrc=)[^>]*>", t), arq.name
        assert "<style" not in t and not re.search(r'\sstyle="', t), arq.name
        assert not re.search(r"\son[a-z]+\s*=", t), arq.name
        assert "javascript:" not in t, arq.name


def test_limite_corpo_content_length(cliente, monkeypatch):
    grande = b"x" * (wm.LIMITE_PADRAO + 10)
    r = cliente.post("/api/conecta", content=grande,
                     headers={"Content-Type": "application/x-www-form-urlencoded"})
    assert r.status_code == 413 and r.json()["ok"] is False
    assert "content-security-policy" in r.headers
    r = cliente.post("/mutirao/plano.csv", content=b"plano=" + b"x" * (wm.LIMITE_PLANO + 70 * 1024),
                     headers={"Content-Type": "application/x-www-form-urlencoded"})
    assert r.status_code == 413 and "Envio grande demais" in r.text and "br-message" in r.text
    monkeypatch.setattr(wm, "MAX_ARQUIVOS", 1)
    monkeypatch.setattr(wm, "MAX_MB", 1)          # limite /conferir = 1*1 + 2 MB
    pdf = b"%PDF-1.4 " + b"0" * (3 * 1024 * 1024 + 10)
    r = cliente.post("/conferir", data=_form(), files=[("arquivos", ("g.pdf", pdf, "application/pdf"))])
    assert r.status_code == 413 and "Envio grande demais" in r.text


def test_limite_corpo_sem_content_length(cliente):
    def pedacos():
        for _ in range(100):
            yield b"a" * 1024          # 100 KB em chunked, sem Content-Length

    r = cliente.post("/api/conecta", content=pedacos(),
                     headers={"Content-Type": "application/x-www-form-urlencoded"})
    assert r.status_code == 413
    corpo = (b"--XYZ\r\nContent-Disposition: form-data; name=\"cnpj\"\r\n\r\n" + b"1" * 100_000 +
             b"\r\n--XYZ--\r\n")

    def multipart():
        for i in range(0, len(corpo), 4096):
            yield corpo[i:i + 4096]

    r = cliente.post("/conecta/cnd.pdf", content=multipart(),
                     headers={"Content-Type": "multipart/form-data; boundary=XYZ", **ORIGEM})
    assert r.status_code == 413 and "Envio grande demais" in r.text


def test_limite_corpo_nao_afeta_envio_normal(cliente):
    r = cliente.post("/conferir", data=_form(), files=_arquivos("federal_negativa", "fgts_regular"),
                     follow_redirects=False)
    assert r.status_code == 303


# ----------------------------------------------------------------- CSV: injeção de fórmula
def test_csv_controle_e_plano_sanitizados(cliente):
    r = cliente.post("/conferir", data=_form(razao_social="=1+1", municipio="-2+3", numero="@9/2026"),
                     files=[("arquivos", ("@x.pdf", (AMOSTRAS / "fgts_regular.pdf").read_bytes(),
                                          "application/pdf"))], follow_redirects=False)
    csv_ = cliente.get(r.headers["location"] + "/controle.csv").content
    texto = csv_.decode("utf-8-sig")
    assert ";'=1+1;" in texto and ";'-2+3;" in texto and ";'@x.pdf;" in texto and ";'@9/2026;" in texto
    assert ";=1+1;" not in texto and ";-2+3;" not in texto

    ate = (date.today() + timedelta(days=20)).isoformat()
    r = cliente.post("/mutirao", data={"ate": ate}, files=[("csvs", ("a.csv", csv_, "text/csv"))])
    assert r.status_code == 200
    assert ">=1+1<" in r.text            # na tela, o nome volta sem o apóstrofo (lido de volta)
    plano_json = html.unescape(re.search(r'name="plano" value="([^"]*)"', r.text).group(1))
    plano = cliente.post("/mutirao/plano.csv", data={"plano": plano_json, "ate": ate}).content.decode("utf-8-sig")
    linhas = plano.splitlines()
    assert all(c[:1] not in "=+-@\t\r" for ln in linhas for c in ln.split(";") if c)
    assert "'=1+1" in plano and "'-2+3" in plano


def test_plano_csv_rejeita_entrada_invalida(cliente):
    for plano in ("", "nao e json", '{"a": 1}', "[1, 2]"):
        r = cliente.post("/mutirao/plano.csv", data={"plano": plano, "ate": "2026-11-10"})
        assert r.status_code == 400 and "Não foi possível gerar" in r.text, plano
    malicioso = '[{"contratada": "=HYPERLINK(\\"http://x\\")", "extra": "ignorar", "cnpj": "+1"}]'
    r = cliente.post("/mutirao/plano.csv", data={"plano": malicioso, "ate": "x"})
    assert r.status_code == 200 and 'filename="mutirao.csv"' in r.headers["content-disposition"]
    t = r.content.decode("utf-8-sig")
    assert "'=HYPERLINK" in t and ";'+1;" in t and "ignorar" not in t


def test_mailto_longo_vira_so_assunto():
    curto = wm.mailto("Assunto", "corpo curto")
    assert curto["curto"] is False and "&body=corpo%20curto" in curto["href"]
    longo = wm.mailto("Assunto", "á" * 2000)
    assert longo["curto"] is True and longo["href"] == "mailto:?subject=Assunto"


def test_mutirao_textos_sicaf_e_contrato(cliente):
    t = cliente.get("/mutirao").text
    assert "quando o contrato prever" in t and "art. 92, XVI" in t
    assert "O contrato obriga" not in t
    assert "simples consulta" in t and "Automática" in t and "Manual" in t
    assert 'href="https://www.gov.br/compras/' in t


def test_api_conecta_origem_e_limite_compartilhado(cliente, monkeypatch):
    pastas = []
    _conecta_falso(monkeypatch, pastas)
    monkeypatch.setattr(wm._conecta, "consultar_cnd",
                        lambda cnpj, salvar_pdf_em=None: {"ok": True, "mensagem": "ok", "bruto": {"x": 1}})
    for cab in ({}, {"Origin": "https://malicioso.example"}, {"Referer": "https://malicioso.example/"}):
        r = cliente.post("/api/conecta", data={"cnpj": CNPJ}, headers=cab)
        assert r.status_code == 403 and r.json()["ok"] is False, cab
    monkeypatch.setattr(wm, "CONECTA_LIMITE_HORA", 3)
    r = cliente.post("/api/conecta", data={"cnpj": CNPJ}, headers=ORIGEM)
    assert r.status_code == 200 and "bruto" not in r.json()
    assert cliente.post("/api/conecta", data={"cnpj": CNPJ}, headers=ORIGEM).status_code == 200
    # a terceira consulta vem pelo PDF: o contador é o mesmo
    assert cliente.post("/conecta/cnd.pdf", data={"cnpj": CNPJ}, headers=ORIGEM).status_code == 502
    r = cliente.post("/api/conecta", data={"cnpj": CNPJ}, headers=ORIGEM)
    assert r.status_code == 429 and "Limite" in r.json()["mensagem"]
    assert cliente.post("/conecta/cnd.pdf", data={"cnpj": CNPJ}, headers=ORIGEM).status_code == 429
