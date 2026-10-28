"""Testes do catálogo de portais e do cliente Conecta (sem rede: requests mockado)."""
from __future__ import annotations

import base64
import json
from datetime import date
from pathlib import Path

import pytest

from certidoes import conecta, portais
from certidoes.models import TipoCertidao

TIPOS_VALIDOS = {t.value for t in TipoCertidao} - {"desconhecida"}
CAMPOS = {"id", "nome", "tipo", "orgao", "url", "url_verificacao", "captcha",
          "validade_tipica_dias", "observacao", "verificado_em", "fonte",
          # esquema v2
          "acesso", "nivel_govbr", "abrange_filiais", "certidao_unica", "prioridade"}
ACESSOS = {"captcha", "govbr", "certificado", "livre", "desconhecido"}
CAPTCHA_DE = {"captcha": True, "govbr": False, "certificado": False, "livre": False, "desconhecido": None}
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
    # Certidão Única (SIDEB) primeiro; modelo antigo (PGE + SEFAZ) só como alternativa
    unica = estaduais[0]
    assert unica["id"] == "sp_certidao_unica"
    assert unica["certidao_unica"] is True and unica["prioridade"] == 1
    assert unica["abrange_filiais"] is True and unica["validade_tipica_dias"] == 90
    assert unica["url"].startswith("https://www4.fazenda.sp.gov.br/SIDEB/")
    assert unica["verificado_em"] and unica["fonte"].startswith("https://legislacao.fazenda.sp.gov.br/")
    antigos = estaduais[1:]
    assert all(i["prioridade"] > 1 and i["certidao_unica"] is False for i in antigos)
    municipais = [i for i in itens if i["tipo"] == "municipal"]
    assert len(municipais) == 1 and municipais[0]["url"]
    for i in itens:
        for campo in ("nome", "tipo", "url", "captcha", "observacao", "verificado_em", "acesso", "prioridade"):
            assert campo in i


def test_municipio_nao_catalogado():
    itens = portais.portais_para("SP", "Campinas")
    mun = [i for i in itens if i["tipo"] == "municipal"]
    assert len(mun) == 1
    assert "não catalogado" in mun[0]["nome"]
    assert mun[0]["url"] is None
    assert "data/portais.json" in mun[0]["observacao"]


def test_url_verificacao():
    assert portais.url_verificacao("federal").startswith("https://servicos.receitafederal.gov.br/")
    assert portais.url_verificacao(TipoCertidao.FGTS).startswith("https://consulta-crf.caixa.gov.br")
    assert portais.url_verificacao("estadual", "SP").endswith("/SIDEB/CertidaoNegativaDebitos/Validacao")
    assert portais.url_verificacao("estadual", "XX") is None


# ---------------- esquema v2 ----------------

def test_esquema_v2_campos_coerentes():
    cat = portais.carregar()
    assert cat.get("esquema") == 2
    for item in _todos(cat):
        ident = item["id"]
        assert item["acesso"] in ACESSOS, ident
        assert item["captcha"] is CAPTCHA_DE[item["acesso"]], ident
        assert item["nivel_govbr"] in (None, "bronze", "prata", "ouro"), ident
        if item["acesso"] != "govbr":
            assert item["nivel_govbr"] is None, ident
        assert item["abrange_filiais"] in (True, False, None), ident
        assert item["certidao_unica"] in (True, False, None), ident
        if item["tipo"] != "estadual":
            assert item["certidao_unica"] is None, ident
        v = item["validade_tipica_dias"]
        assert v is None or (isinstance(v, int) and v > 0), ident
        assert isinstance(item["prioridade"], int) and not isinstance(item["prioridade"], bool), ident
        assert item["prioridade"] >= 1, ident
        if item["verificado_em"] is not None:
            assert item["fonte"], ident
        if item["acesso"] != "desconhecido":
            # modo de acesso afirmado precisa de fonte e data
            assert item["verificado_em"] and item["fonte"], ident
        if item["acesso"] == "desconhecido":
            assert "confirmar" in item["observacao"].lower(), ident


def test_ids_unicos():
    ids = [i["id"] for i in _todos(portais.carregar())]
    assert len(ids) == len(set(ids))


def test_rj_conjunta_ainda_nao_e_item():
    # anunciada para nov/2026 e não confirmada em fonte oficial: só registrada na observação
    rj = portais.carregar()["estaduais"]["RJ"]
    assert {i["id"] for i in rj} == {"rj_sefaz", "rj_pge"}
    assert not any(i["certidao_unica"] for i in rj)
    assert any("conjunta" in i["observacao"].lower() for i in rj)


def test_portais_para_ordenado_por_tipo_e_prioridade():
    itens = portais.portais_para("SP", "São Paulo")
    ordem = list(portais._ORDEM_TIPOS)
    chaves = [(ordem.index(i["tipo"]), i["prioridade"]) for i in itens]
    assert chaves == sorted(chaves)
    assert itens[0]["tipo"] == "federal"


def _catalogo_tmp(tmp_path: Path, dados: dict) -> Path:
    caminho = tmp_path / "portais.json"
    caminho.write_text(json.dumps(dados, ensure_ascii=False), encoding="utf-8")
    portais.limpar_cache()
    return caminho


CATALOGO_FALSO = {
    "versao": "teste", "atualizado_em": "2026-10-27",
    "federais": [
        {"id": "fed_captcha", "nome": "Federal com captcha", "tipo": "federal", "url": "https://a.gov.br/",
         "acesso": "captcha", "captcha": True, "prioridade": 1},
        {"id": "fed_govbr", "nome": "Federal gov.br", "tipo": "federal", "url": "https://b.gov.br/",
         "acesso": "govbr", "captcha": False, "nivel_govbr": "prata", "prioridade": 2},
        {"id": "fed_verificacao", "nome": "Verificação", "tipo": "federal", "url": "https://c.gov.br/",
         "acesso": "livre", "captcha": False, "prioridade": 0, "url_verificacao": "https://c.gov.br/v"},
        {"id": "fgts_v1", "nome": "FGTS item antigo", "tipo": "fgts", "url": "https://d.gov.br/", "captcha": True},
        {"id": "trab_v1", "nome": "Trabalhista antigo", "tipo": "trabalhista", "url": "https://e.jus.br/",
         "captcha": False},
        {"id": "sicaf_sem_url", "nome": "SICAF sem URL", "tipo": "sicaf", "url": None, "acesso": "livre",
         "captcha": False, "prioridade": 1},
    ],
    "estaduais": {"XX": [
        {"id": "xx_b", "nome": "Estadual B", "tipo": "estadual", "url": "https://xx2.gov.br/",
         "acesso": "desconhecido", "captcha": None, "prioridade": 1, "url_verificacao": "https://xx2.gov.br/v"},
        {"id": "xx_a", "nome": "Estadual A", "tipo": "estadual", "url": "https://xx1.gov.br/",
         "acesso": "certificado", "captcha": False, "prioridade": 2, "url_verificacao": "https://xx1.gov.br/v"},
        {"id": "xx_c", "nome": "Estadual C", "tipo": "estadual", "url": "https://xx3.gov.br/",
         "acesso": "captcha", "captcha": True, "prioridade": 0},
    ]},
    "municipais": {"XX/Cidade Ação": [
        {"id": "mun", "nome": "Municipal", "tipo": "municipal", "url": "https://cidade.gov.br/", "captcha": None},
    ]},
}


def test_itens_v1_sao_tolerados(tmp_path):
    caminho = _catalogo_tmp(tmp_path, CATALOGO_FALSO)
    try:
        por_id = {i["id"]: i for i in portais.portais_para("XX", "cidade acao", caminho)}
        assert por_id["fgts_v1"]["acesso"] == "captcha" and por_id["fgts_v1"]["captcha"] is True
        assert por_id["trab_v1"]["acesso"] == "livre"
        assert por_id["mun"]["acesso"] == "desconhecido" and por_id["mun"]["captcha"] is None
        assert por_id["fgts_v1"]["prioridade"] == 99           # prioridade ausente vai para o fim
        for campo in ("nivel_govbr", "abrange_filiais", "certidao_unica", "validade_tipica_dias"):
            assert por_id["fgts_v1"][campo] is None
        assert portais.acesso_de({"acesso": "invalido"}) == "desconhecido"
        assert portais.acesso_de({}) == "desconhecido"
    finally:
        portais.limpar_cache()


def test_melhor_rota_prefere_sem_captcha(tmp_path):
    caminho = _catalogo_tmp(tmp_path, CATALOGO_FALSO)
    try:
        # captcha com prioridade 1 perde para gov.br com prioridade 2; verificação é ignorada
        assert portais.melhor_rota("federal", caminho=caminho)["id"] == "fed_govbr"
        assert portais.melhor_rota(TipoCertidao.FEDERAL, caminho=caminho)["id"] == "fed_govbr"
        # confirmada sem captcha (certificado) vence desconhecida, que vence captcha
        assert portais.melhor_rota("estadual", "xx", caminho=caminho)["id"] == "xx_a"
        # só existe a rota com captcha: ela é devolvida
        assert portais.melhor_rota("fgts", caminho=caminho)["id"] == "fgts_v1"
        assert portais.melhor_rota("municipal", "XX", "Cidade Acao", caminho=caminho)["id"] == "mun"
        assert portais.melhor_rota("municipal", "XX", "Outra", caminho=caminho) is None
        assert portais.melhor_rota("sicaf", caminho=caminho) is None   # item sem URL
        assert portais.melhor_rota("estadual", "YY", caminho=caminho) is None
        # url_verificacao respeita a prioridade
        assert portais.url_verificacao("estadual", "XX", caminho) == "https://xx2.gov.br/v"
    finally:
        portais.limpar_cache()


def test_melhor_rota_catalogo_real():
    unica = portais.melhor_rota("estadual", "SP")
    assert unica["id"] == "sp_certidao_unica"
    fed = portais.melhor_rota("federal")
    assert fed["id"] == "rfb_pgfn_cnd"          # item de verificação não é rota de emissão
    assert portais.melhor_rota("trabalhista")["tipo"] == "trabalhista"
    assert portais.melhor_rota("municipal", "SP", "São Paulo")["id"] == "sao_paulo"


def test_resumo_acesso(tmp_path):
    r = portais.resumo_acesso()
    assert set(r["por_acesso"]) == ACESSOS
    assert r["total"] == sum(1 for _ in _todos(portais.carregar()))
    assert r["total"] == sum(r["por_acesso"].values())
    assert set(r["por_escopo"]) == {"federal", "estadual", "municipal"}
    for escopo, cont in r["por_escopo"].items():
        assert set(cont) == ACESSOS
    assert sum(sum(c.values()) for c in r["por_escopo"].values()) == r["total"]

    caminho = _catalogo_tmp(tmp_path, CATALOGO_FALSO)
    try:
        r = portais.resumo_acesso(caminho)
        assert r["total"] == 10
        assert r["por_acesso"] == {"captcha": 3, "govbr": 1, "certificado": 1, "livre": 3, "desconhecido": 2}
        assert r["por_escopo"]["municipal"]["desconhecido"] == 1
    finally:
        portais.limpar_cache()


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
