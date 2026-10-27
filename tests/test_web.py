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
    r = cliente.post("/api/conecta", data={"cnpj": CNPJ})
    assert r.status_code == 400
