"""Testes do catálogo de portais e do cliente Conecta (sem rede: requests mockado)."""
from __future__ import annotations

import base64
from datetime import date
from pathlib import Path

import pytest

from certidoes import conecta, portais
from certidoes.models import TipoCertidao

TIPOS_VALIDOS = {t.value for t in TipoCertidao} - {"desconhecida"}
CAMPOS = {"id", "nome", "tipo", "orgao", "url", "url_verificacao", "captcha",
          "validade_tipica_dias", "observacao", "verificado_em", "fonte"}
UFS = {"AC", "AL", "AP", "AM", "BA", "CE", "DF", "ES", "GO", "MA", "MT", "MS", "MG", "PA",
       "PB", "PR", "PE", "PI", "RJ", "RN", "RS", "RO", "RR", "SC", "SP", "SE", "TO"}


def _todos(cat):
    yield from cat["federais"]
    for itens in cat["estaduais"].values():
        yield from itens
    for itens in cat["municipais"].values():
        yield from itens


def test_catalogo_carrega():
    cat = portais.carregar()
    assert cat["atualizado_em"] == "2026-10-27"
    assert cat["versao"]
    assert portais.carregar() is cat  # cache


def test_27_ufs_e_capitais():
    cat = portais.carregar()
    assert set(cat["estaduais"]) == UFS
    assert set(portais.ufs()) == UFS
    assert {k.split("/")[0] for k in cat["municipais"]} == UFS
    assert all(cat["estaduais"][uf] for uf in UFS)


def test_campos_obrigatorios_e_tipos():
    for item in _todos(portais.carregar()):
        assert CAMPOS <= set(item), item.get("id")
        assert item["tipo"] in TIPOS_VALIDOS, item["id"]
        assert item["nome"]
        assert item["captcha"] in (True, False, None)
        if item["verificado_em"] is None:
            assert "confirmar" in item["observacao"].lower(), item["id"]
        else:
            assert item["url"], item["id"]
        if item["url"]:
            assert item["url"].startswith(("http://", "https://"))


def test_federais_essenciais():
    tipos = {i["tipo"] for i in portais.carregar()["federais"]}
    assert {"federal", "fgts", "trabalhista", "sicaf", "outra"} <= tipos


def test_portais_para_sao_paulo():
    itens = portais.portais_para("sp", "sao paulo")
    n_fed = len(portais.carregar()["federais"])
    assert len([i for i in itens if i["escopo"] == "federal"]) == n_fed
    estaduais = [i for i in itens if i["tipo"] == "estadual"]
    assert len(estaduais) == 2
    assert any("PGE" in i["nome"] for i in estaduais)
    assert any("SEFAZ" in i["nome"] for i in estaduais)
    municipais = [i for i in itens if i["tipo"] == "municipal"]
    assert len(municipais) == 1 and municipais[0]["url"]
    for i in itens:
        for campo in ("nome", "tipo", "url", "captcha", "observacao", "verificado_em"):
            assert campo in i


def test_municipio_nao_catalogado():
    itens = portais.portais_para("SP", "Campinas")
    mun = [i for i in itens if i["tipo"] == "municipal"]
    assert len(mun) == 1
    assert "não catalogado" in mun[0]["nome"]
    assert mun[0]["url"] is None
    assert "data/portais.json" in mun[0]["observacao"]


def test_url_verificacao():
    assert "receita.fazenda.gov.br" in portais.url_verificacao("federal")
    assert portais.url_verificacao(TipoCertidao.FGTS).startswith("https://consulta-crf.caixa.gov.br")
    assert "fazenda.sp.gov.br" in portais.url_verificacao("estadual", "SP")
    assert portais.url_verificacao("estadual", "XX") is None


# ---------------- Conecta ----------------

@pytest.fixture
def sem_env(monkeypatch):
    for v in ("CONECTA_CLIENT_ID", "CONECTA_CLIENT_SECRET", "CONECTA_AMBIENTE", "CONECTA_CPF_USUARIO"):
        monkeypatch.delenv(v, raising=False)


def test_conecta_nao_configurado(sem_env):
    assert conecta.configurado() is False
    r = conecta.consultar_cnd("11222333000181")
    assert r["ok"] is False and "não configurada" in r["mensagem"]


PDF_FAKE = b"%PDF-1.4\n% DOCUMENTO DE TESTE\n%%EOF\n"
RESPOSTA_EXEMPLO = {  # formato do exemplo do manual Documentacao_API_CND.pdf
    "Status": 1,
    "Mensagem": "Certidão encontrada",
    "Certidao": {
        "TipoContribuinte": 1,
        "ContribuinteCertidao": "11222333000181",
        "TipoCertidao": 2,
        "CodigoControle": "ABCD.1234.EF56.7890",
        "DataEmissao": "2026-10-27T10:56:41",
        "DataValidade": "2027-04-25",
        "DocumentoPdf": base64.b64encode(PDF_FAKE).decode(),
    },
}


class _Resp:
    def __init__(self, status_code, dados):
        self.status_code = status_code
        self._dados = dados

    def json(self):
        return self._dados


class _Sessao:
    def __init__(self, respostas):
        self.respostas = list(respostas)
        self.chamadas = []

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def post(self, url, **kw):
        self.chamadas.append((url, kw))
        return self.respostas.pop(0)


@pytest.fixture
def com_env(monkeypatch):
    monkeypatch.setenv("CONECTA_CLIENT_ID", "id-teste")
    monkeypatch.setenv("CONECTA_CLIENT_SECRET", "segredo-teste")
    monkeypatch.setenv("CONECTA_AMBIENTE", "homologacao")
    monkeypatch.delenv("CONECTA_CPF_USUARIO", raising=False)
    monkeypatch.setattr(conecta.time, "sleep", lambda s: None)


def _mock(monkeypatch, respostas):
    sessao = _Sessao(respostas)
    monkeypatch.setattr(conecta.requests, "Session", lambda: sessao)
    return sessao


def test_consultar_cnd_sucesso_salva_pdf(com_env, monkeypatch, tmp_path: Path):
    sessao = _mock(monkeypatch, [_Resp(200, {"access_token": "tok"}), _Resp(200, RESPOSTA_EXEMPLO)])
    assert conecta.configurado()
    r = conecta.consultar_cnd("11.222.333/0001-81", salvar_pdf_em=str(tmp_path))
    assert r["ok"] is True and r["status"] == 1
    assert r["validade"] == date(2027, 4, 25)
    assert r["emissao"] == date(2026, 10, 27)
    assert r["codigo_controle"] == "ABCD.1234.EF56.7890"
    assert Path(r["caminho_pdf"]).read_bytes() == PDF_FAKE
    assert "omitido" in r["bruto"]["Certidao"]["DocumentoPdf"]
    # token + consulta
    url_tok, kw_tok = sessao.chamadas[0]
    assert url_tok.endswith("/oauth2/jwt-token")
    url, kw = sessao.chamadas[1]
    assert url.endswith("/api-cnd-hom/v1/ConsultaCnd/certidao")
    assert kw["json"] == {"TipoContribuinte": 1, "ContribuinteConsulta": "11222333000181",
                          "CodigoIdentificacao": "9201", "GerarCertidaoPdf": True}
    assert kw["headers"]["Authorization"] == "Bearer tok"
    assert "x-cpf-usuario" not in kw["headers"]
    assert "segredo-teste" not in repr(r)


def test_consultar_cnd_status7_repete_com_chave(com_env, monkeypatch):
    sessao = _mock(monkeypatch, [_Resp(200, {"access_token": "tok"}),
                                 _Resp(201, {"Status": 7, "Mensagem": "Em processamento", "Chave": "K1"}),
                                 _Resp(200, RESPOSTA_EXEMPLO)])
    r = conecta.consultar_cnd("11222333000181")
    assert r["ok"] and r["caminho_pdf"] is None
    assert sessao.chamadas[2][1]["json"]["Chave"] == "K1"


def test_consultar_cnd_nao_emitida(com_env, monkeypatch):
    _mock(monkeypatch, [_Resp(200, {"access_token": "tok"}),
                        _Resp(200, {"Status": 3, "Mensagem": "Certidão não emitida"})])
    r = conecta.consultar_cnd("11222333000181")
    assert r["ok"] is False and r["status"] == 3


def test_consultar_cnd_erros(com_env, monkeypatch):
    _mock(monkeypatch, [_Resp(401, {})])
    assert conecta.consultar_cnd("11222333000181")["ok"] is False
    _mock(monkeypatch, [_Resp(200, {"access_token": "tok"}), _Resp(403, {})])
    r = conecta.consultar_cnd("11222333000181")
    assert r["ok"] is False and "IP" in r["mensagem"]
    assert conecta.consultar_cnd("123")["ok"] is False

    class _Falha(_Sessao):
        def post(self, url, **kw):
            raise conecta.requests.ConnectionError("sem rede")
    monkeypatch.setattr(conecta.requests, "Session", lambda: _Falha([]))
    r = conecta.consultar_cnd("11222333000181")
    assert r["ok"] is False and "ConnectionError" in r["mensagem"]
