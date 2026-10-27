"""Ponte da versão no navegador: mesmas regras, entrada e saída em JSON."""
import json
from pathlib import Path

import pytest

from certidoes import navegador
from certidoes.extrator import extrair_texto

AMOSTRAS = Path(__file__).parent / "amostras"
CONTRATO = {"numero": "001/2026", "cnpj": "12.345.678/0001-95",
            "razao_social": "EMPRESA EXEMPLO DE SERVIÇOS LTDA", "uf": "SP",
            "municipio": "São Paulo", "fiscal": "Fulano", "competencia": "10/2026",
            "orgao": "Órgão Exemplo", "dias_alerta": 15,
            "exigidas": ["federal", "fgts", "trabalhista", "estadual", "municipal"]}


@pytest.fixture(scope="module", autouse=True)
def amostras():
    if not (AMOSTRAS / "federal_negativa.pdf").exists():
        from tests.gerar_amostras import gerar
        gerar(AMOSTRAS)


def _arq(*nomes):
    return [{"nome": f"{n}.pdf", "texto": extrair_texto(AMOSTRAS / f"{n}.pdf")} for n in nomes]


def _conferir(contrato=None, arquivos=None):
    return json.loads(navegador.conferir(json.dumps({"contrato": contrato or CONTRATO,
                                                     "arquivos": arquivos or []})))


def test_conferencia_apta():
    r = _conferir(arquivos=_arq("federal_negativa", "fgts_regular", "cndt_negativa",
                                "estadual_sp_pge", "estadual_sp_sefaz", "municipal_sp"))
    assert r["ok"] and r["apto"]
    assert [i["semaforo"] for i in r["itens"]].count("vermelho") == 0
    assert r["minuta"]["titulo"].startswith("Minuta de atesto")
    assert "&amp;" not in " ".join(r["minuta"]["paragrafos"])
    assert r["csv"].startswith("data_referencia;")
    assert r["contrato"]["cnpj"] == "12.345.678/0001-95"


def test_conferencia_com_pendencia_e_solicitacao():
    r = _conferir(arquivos=_arq("federal_vencida", "cndt_positiva"))
    assert r["ok"] and not r["apto"]
    assert r["minuta"]["titulo"].startswith("Minuta de notificação")
    assert r["solicitacao"] and "MINUTA" in r["solicitacao"]["texto"].upper()


def test_erros_de_preenchimento():
    r = _conferir(contrato={**CONTRATO, "cnpj": "11.111.111/1111-11", "exigidas": []})
    assert not r["ok"]
    assert any("CNPJ" in e for e in r["erros"]) and any("PDF" in e for e in r["erros"])


def test_pdf_ilegivel_e_texto_vazio():
    r = _conferir(arquivos=[{"nome": "x.pdf", "erro": "PDF protegido"},
                            {"nome": "y.pdf", "texto": ""}])
    avisos = " ".join(a for c in r["certidoes"] for a in c["avisos"])
    assert "PDF protegido" in avisos and "escaneado" in avisos.lower()


def test_nome_de_arquivo_sem_caminho():
    r = _conferir(arquivos=[{"nome": "../../etc/x.pdf", "texto": ""}])
    assert r["certidoes"][0]["arquivo"] == "x.pdf"


def test_planejar_mes_a_partir_do_csv():
    r = _conferir(arquivos=_arq("federal_negativa", "fgts_regular"))
    p = json.loads(navegador.planejar_mes(json.dumps(
        {"csvs": [r["csv"]], "ate": "2027-06-01", "orgao": "X", "prazo": 5})))
    assert p["ok"] and p["totais"]["contratadas"] == 1
    assert p["grupos"][0]["solicitacao"] and p["csv"]


def test_planejar_mes_erros():
    p = json.loads(navegador.planejar_mes(json.dumps({"csvs": [], "ate": "x"})))
    assert not p["ok"] and len(p["erros"]) == 2


def test_portais_com_sicaf_em_destaque():
    lista = json.loads(navegador.portais("SP", "São Paulo", json.dumps(["federal", "sicaf"]), True))
    assert lista and lista[0]["tipo"] == "sicaf" and lista[0]["destaque"]
