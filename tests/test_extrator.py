"""Testes do extrator de certidões (PDFs sintéticos + trechos de texto)."""
from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gerar_amostras  # noqa: E402

from certidoes import extrator, ia  # noqa: E402
from certidoes.extrator import AVISO_ESCANEADO, AVISO_MULTIPLAS, ler_pdf, ler_texto, ler_varios  # noqa: E402
from certidoes.models import Situacao, TipoCertidao  # noqa: E402

CNPJ = gerar_amostras.CNPJ_EMPRESA
HOJE = date.today()


@pytest.fixture(scope="session")
def amostras(tmp_path_factory):
    pasta = tmp_path_factory.mktemp("amostras")
    esperado = gerar_amostras.gerar(pasta)
    return pasta, esperado


@pytest.fixture(autouse=True)
def _sem_ia(monkeypatch):
    monkeypatch.delenv("CERTIDOES_IA", raising=False)


NOMES = [a.nome + ".pdf" for a in gerar_amostras.amostras()]


@pytest.mark.parametrize("nome", NOMES)
def test_amostra_confere_com_esperado(amostras, nome):
    pasta, esperado = amostras
    e = esperado[nome]
    c = ler_pdf(pasta / nome)
    assert c.arquivo == nome
    assert c.metodo == "regras"
    assert c.tipo.value == e["tipo"]
    assert c.situacao.value == e["situacao"]
    assert c.cnpj == e["cnpj"]
    assert (c.validade.isoformat() if c.validade else None) == e["validade"]
    for campo in ("data_emissao",):
        if e[campo]:
            assert getattr(c, campo).isoformat() == e[campo]
    for campo in ("uf", "municipio", "codigo_controle"):
        if e[campo]:
            assert getattr(c, campo) == e[campo]
    for trecho in e["avisos_contem"]:
        assert any(trecho in a for a in c.avisos), c.avisos
    if e["tipo"] != "desconhecida" and not e["avisos_contem"]:
        assert c.confianca >= 0.9
        assert c.texto
    cob = {k: (v if k.startswith("_") else
               {"validade": v["validade"].isoformat() if v["validade"] else None,
                "automatica": v["automatica"], "pendencia": v["pendencia"]})
           for k, v in c.cobertura_sicaf.items()}
    assert cob == (e["cobertura"] or {})


def test_marca_de_teste_no_texto(amostras):
    pasta, _ = amostras
    assert "DOCUMENTO DE TESTE - SEM VALIDADE" in extrator.extrair_texto(pasta / "cndt_negativa.pdf")


def test_escaneado(amostras):
    pasta, _ = amostras
    assert extrator.extrair_texto(pasta / "escaneado.pdf") == ""
    c = ler_pdf(pasta / "escaneado.pdf")
    assert AVISO_ESCANEADO in c.avisos
    assert c.confianca == 0.0


def test_vencida_e_vence_em_breve(amostras):
    pasta, _ = amostras
    assert ler_pdf(pasta / "federal_vencida.pdf").validade < HOJE
    assert ler_pdf(pasta / "cndt_vence_em_breve.pdf").validade == HOJE + timedelta(days=5)


def test_urls_verificacao(amostras):
    pasta, _ = amostras
    assert ler_pdf(pasta / "federal_negativa.pdf").url_verificacao == extrator.URL_FEDERAL
    assert ler_pdf(pasta / "fgts_regular.pdf").url_verificacao == extrator.URL_FGTS
    assert ler_pdf(pasta / "cndt_negativa.pdf").url_verificacao == extrator.URL_TST


def test_municipal_ignora_cnpj_da_prefeitura(amostras):
    pasta, _ = amostras
    c = ler_pdf(pasta / "municipal_sp.pdf")
    assert c.cnpj == CNPJ
    assert c.orgao_emissor == "Prefeitura de São Paulo"


def test_duas_certidoes(amostras):
    pasta, _ = amostras
    c = ler_pdf(pasta / "duas_certidoes.pdf")
    assert AVISO_MULTIPLAS in c.avisos
    assert c.confianca < 0.9


def test_ler_varios(amostras):
    pasta, _ = amostras
    r = ler_varios([pasta / "federal_negativa.pdf", pasta / "fgts_regular.pdf"])
    assert [c.tipo for c in r] == [TipoCertidao.FEDERAL, TipoCertidao.FGTS]


def test_pdf_inexistente_nao_quebra(tmp_path):
    c = ler_pdf(tmp_path / "nao_existe.pdf")
    assert c.tipo == TipoCertidao.DESCONHECIDA
    assert any("Não foi possível ler" in a for a in c.avisos)


# ---------------------------------------------------------------- unitários de texto

def test_data_por_extenso_e_ancora():
    t = ("SECRETARIA DA FAZENDA DO ESTADO DE MINAS GERAIS\nCERTIDÃO DE DÉBITOS TRIBUTÁRIOS\n"
         "CNPJ: 12.345.678/0001-95\nBelo Horizonte, 1º de março de 2026.\n"
         "Não constam débitos.\nEmitida em 2 de março de 2026.\nVálida até 31 de maio de 2026.")
    c = ler_texto(t, "mg.pdf")
    assert c.tipo == TipoCertidao.ESTADUAL
    assert c.uf == "MG"
    assert c.data_emissao == date(2026, 3, 2)
    assert c.validade == date(2026, 5, 31)
    assert c.situacao == Situacao.NEGATIVA


def test_data_com_pontos():
    c = ler_texto("CERTIDÃO NEGATIVA DE DÉBITOS TRABALHISTAS\nCNPJ: 12.345.678/0001-95\n"
                  "Expedição: 01.02.2026\nValidade: 31.07.2026 - 180 dias")
    assert c.validade == date(2026, 7, 31)
    assert c.data_emissao == date(2026, 2, 1)


@pytest.mark.parametrize("frase,esperada", [
    ("Não constam débitos em nome do contribuinte.", Situacao.NEGATIVA),
    ("Constam débitos em nome do contribuinte.", Situacao.POSITIVA),
    ("Certidão com efeito de negativa: constam débitos com exigibilidade suspensa.",
     Situacao.POSITIVA_EFEITO_NEGATIVA),
    ("Nada consta.", Situacao.NEGATIVA),
])
def test_constam_vs_nao_constam(frase, esperada):
    t = f"GOVERNO DO ESTADO DO PARANÁ\nCertidão de débitos tributários\nCNPJ: {CNPJ}\n{frase}\nVálida até 10/12/2026"
    c = ler_texto(t)
    assert c.tipo == TipoCertidao.ESTADUAL
    assert c.uf == "PR"
    assert c.situacao == esperada


def test_cnpj_sem_mascara():
    c = ler_texto(f"CERTIDÃO NEGATIVA DE DÉBITOS TRABALHISTAS\nCNPJ: {CNPJ}\nValidade: 10/12/2026")
    assert c.cnpj == CNPJ
    assert c.confianca >= 0.9 - 0.05


def test_cnpj_invalido_gera_aviso():
    c = ler_texto("CERTIDÃO NEGATIVA DE DÉBITOS TRABALHISTAS\nCNPJ: 12.345.678/0001-00\nValidade: 10/12/2026")
    assert c.cnpj == "12345678000100"
    assert any("dígito verificador inválido" in a for a in c.avisos)


def test_cnpj_do_contribuinte_e_nao_do_orgao():
    t = ("Secretaria da Fazenda do Estado de Goiás - CNPJ 01.409.655/0001-80\n"
         "Certidão negativa de débitos\nContribuinte: EMPRESA EXEMPLO DE SERVIÇOS LTDA\n"
         f"CNPJ: {gerar_amostras.fmt_cnpj(CNPJ)}\nVálida até 01/01/2027")
    c = ler_texto(t)
    assert c.cnpj == CNPJ
    assert c.uf == "GO"
    assert c.razao_social == "EMPRESA EXEMPLO DE SERVIÇOS LTDA"


def test_campos_faltantes_reduzem_confianca():
    c = ler_texto("CERTIDÃO NEGATIVA DE DÉBITOS TRABALHISTAS")
    assert c.confianca < 0.8
    assert "CNPJ não encontrado no PDF" in c.avisos
    assert "Data de validade não encontrada" in c.avisos


def test_texto_vazio():
    c = ler_texto("   ", "x.pdf")
    assert AVISO_ESCANEADO in c.avisos


def test_validade_relativa_em_dias():
    c = ler_texto("PREFEITURA MUNICIPAL DE CAMPINAS - SP\nCertidão negativa de débitos mobiliários\n"
                  f"CNPJ: {CNPJ}\nData de emissão: 10/01/2026\nVálida por 90 (noventa) dias.")
    assert c.tipo == TipoCertidao.MUNICIPAL
    assert c.municipio == "Campinas"
    assert c.uf == "SP"
    assert c.validade == date(2026, 4, 10)


def test_sicaf_com_pendencia():
    c = ler_texto("Sistema de Cadastramento Unificado de Fornecedores - SICAF\nCNPJ: "
                  f"{CNPJ}\nPossui Pendência: Sim\nFGTS - Validade: 10/12/2026")
    assert c.tipo == TipoCertidao.SICAF
    assert c.situacao == Situacao.INDETERMINADA
    assert any("pendência" in a for a in c.avisos)


def test_outra_ceis():
    c = ler_texto("CONTROLADORIA-GERAL DA UNIÃO\nCadastro Nacional de Empresas Inidôneas e Suspensas (CEIS)\n"
                  f"Certidão\nCNPJ: {CNPJ}\nNada consta.")
    assert c.tipo == TipoCertidao.OUTRA
    assert c.situacao == Situacao.NEGATIVA


def test_texto_original_preservado():
    t = "CERTIDÃO NEGATIVA DE DÉBITOS TRABALHISTAS\nCNPJ: " + CNPJ
    assert ler_texto(t).texto == t


def test_federal_positiva_comum():
    c = ler_texto("CERTIDÃO POSITIVA DE DÉBITOS RELATIVOS AOS TRIBUTOS FEDERAIS E À DÍVIDA ATIVA DA UNIÃO\n"
                  f"CNPJ: {CNPJ}\nVálida até 01/02/2027.")
    assert c.tipo == TipoCertidao.FEDERAL
    assert c.situacao == Situacao.POSITIVA


# ---------------------------------------------------------------- IA (sem rede)

def test_ia_desligada_por_padrao(monkeypatch):
    monkeypatch.delenv("CERTIDOES_IA", raising=False)
    assert ia.habilitada() is False
    assert ia.extrair_com_ia("qualquer texto", "a.pdf") is None


def test_ia_parse_defensivo():
    obj = ia._json_da_resposta('```json\n{"tipo": "fgts", "situacao": "regular", "cnpj": "12.345.678/0001-95",'
                               ' "validade": "2026-12-01", "uf": "xyz"}\n```')
    c = ia._para_certidao(obj, "a.pdf")
    assert c.metodo == "ia"
    assert c.tipo == TipoCertidao.FGTS
    assert c.cnpj == CNPJ
    assert c.uf is None
    assert c.confianca <= 0.7
    assert ia.AVISO_IA in c.avisos
    assert ia._json_da_resposta("não é json") is None


# ---------------------------------------------------------------- revisão: situação

_CAMPINAS_POS = (
    "PREFEITURA MUNICIPAL DE CAMPINAS - SP\nCERTIDÃO POSITIVA DE DÉBITOS TRIBUTÁRIOS\n"
    "Contribuinte: X LTDA CNPJ: 11.222.333/0001-81\nConstam débitos.\n"
    "Nos termos do art. 206 do CTN, somente a certidão que indique débitos suspensos tem os mesmos "
    "efeitos de negativa.\nData de emissão: 01/10/2026 Validade: 30/12/2026"
)


def test_bloqueante_positiva_com_mencao_normativa_a_efeitos_de_negativa():
    c = ler_texto(_CAMPINAS_POS)
    assert c.tipo == TipoCertidao.MUNICIPAL
    assert c.situacao == Situacao.POSITIVA
    assert c.cnpj == "11222333000181"
    assert c.validade == date(2026, 12, 30)


@pytest.mark.parametrize("frase", [
    "Esta certidão NÃO tem efeitos de negativa.",
    "Constam débitos exigíveis (não produz efeito de certidão negativa).",
    "Esta certidão não possui efeito de negativa.",
])
def test_efeito_de_negativa_negado_nao_vira_pen(frase):
    t = f"GOVERNO DO ESTADO DA BAHIA\nCERTIDÃO POSITIVA DE DÉBITOS\nCNPJ: {CNPJ}\n{frase}\nVálida até 10/12/2026"
    assert ler_texto(t).situacao == Situacao.POSITIVA


def test_titulo_pen_reconhecido():
    t = (f"GOVERNO DO ESTADO DA BAHIA\nCERTIDÃO POSITIVA COM EFEITO DE NEGATIVA\nCNPJ: {CNPJ}\n"
         "Constam débitos com exigibilidade suspensa.\nVálida até 10/12/2026")
    c = ler_texto(t)
    assert c.situacao == Situacao.POSITIVA_EFEITO_NEGATIVA
    assert not any("mais restritiva" in a for a in c.avisos)


def test_corpo_com_efeito_de_negativa_sem_titulo():
    t = (f"SECRETARIA DA FAZENDA DO ESTADO DO CEARÁ\nCertidão de regularidade\nCNPJ: {CNPJ}\n"
         "A presente certidão tem os mesmos efeitos da certidão negativa, sendo emitida "
         "com efeitos de negativa.\nVálida até 10/12/2026")
    assert ler_texto(t).situacao == Situacao.POSITIVA_EFEITO_NEGATIVA


def test_conflito_titulo_negativa_corpo_positiva_prevalece_restritiva():
    t = (f"GOVERNO DO ESTADO DE PERNAMBUCO\nCERTIDÃO NEGATIVA DE DÉBITOS\nCNPJ: {CNPJ}\n"
         "Constam débitos em aberto.\nVálida até 10/12/2026")
    c = ler_texto(t)
    assert c.situacao == Situacao.POSITIVA
    assert any("mais restritiva" in a for a in c.avisos)


def test_conflito_titulo_pen_corpo_positiva():
    t = (f"GOVERNO DO ESTADO DE PERNAMBUCO\nCERTIDÃO POSITIVA COM EFEITOS DE NEGATIVA\nCNPJ: {CNPJ}\n"
         "Possui débitos exigíveis.\nVálida até 10/12/2026")
    c = ler_texto(t)
    assert c.situacao == Situacao.POSITIVA
    assert any("mais restritiva" in a for a in c.avisos)


@pytest.mark.parametrize("frase,esperada", [
    ("O contribuinte possui débitos.", Situacao.POSITIVA),
    ("O contribuinte não possui débitos.", Situacao.NEGATIVA),
    ("Existem débitos em aberto.", Situacao.POSITIVA),
    ("Não existem débitos.", Situacao.NEGATIVA),
    ("Situação: POSITIVA", Situacao.POSITIVA),
    ("Situação: NEGATIVA", Situacao.NEGATIVA),
    ("Consta débito.", Situacao.POSITIVA),
    ("Consta débito inscrito em dívida ativa.", Situacao.POSITIVA),
    ("Constam em nome do contribuinte acima débitos.", Situacao.POSITIVA),
    ("Não constam débitos exigíveis. Constam débitos com exigibilidade suspensa.",
     Situacao.POSITIVA_EFEITO_NEGATIVA),
    ("Não constam débitos vencidos; há débitos parcelados em dia.", Situacao.POSITIVA_EFEITO_NEGATIVA),
])
def test_frases_de_debito(frase, esperada):
    t = f"GOVERNO DO ESTADO DE ALAGOAS\nCertidão de débitos tributários\nCNPJ: {CNPJ}\n{frase}\nVálida até 10/12/2026"
    assert ler_texto(t).situacao == esperada


# ---------------------------------------------------------------- revisão: datas

def test_ano_com_dois_digitos():
    c = ler_texto(f"CERTIDÃO NEGATIVA DE DÉBITOS TRABALHISTAS\nCNPJ: {CNPJ}\n"
                  "Expedição: 01/10/26\nValidade: 30/12/26")
    assert c.data_emissao == date(2026, 10, 1)
    assert c.validade == date(2026, 12, 30)


def test_validade_de_n_dias_a_contar_de_data():
    c = ler_texto("PREFEITURA MUNICIPAL DE CAMPINAS - SP\nCertidão negativa de débitos\n"
                  f"CNPJ: {CNPJ}\nCertidão com validade de 180 dias a contar de 01/10/2026.")
    assert c.validade == date(2026, 10, 1) + timedelta(days=180)


# ---------------------------------------------------------------- SICAF: cobertura por nível

_SICAF_CAB = ("Sistema de Cadastramento Unificado de Fornecedores - SICAF\nDeclaração\n"
              f"CNPJ: {gerar_amostras.fmt_cnpj(CNPJ)}\nRazão Social: EMPRESA EXEMPLO\n"
              "Situação do Fornecedor: Credenciado\n")


def _cob(c, tipo):
    return c.cobertura_sicaf[tipo]


def test_sicaf_formato_real_niveis_iii_e_iv():
    t = _SICAF_CAB + (
        "III - Regularidade Fiscal e Trabalhista Federal\n"
        "Receita Federal e PGFN Validade: 02/02/2025 Automática\n"
        "FGTS Validade: 13/11/2024 Automática\n"
        "Trabalhista Validade: 22/04/2025 Automática(http://www.tst.jus.br/certidao)\n"
        "IV - Regularidade Fiscal Estadual/Distrital e Municipal\n"
        "Receita Estadual/Distrital Validade: 13/07/2024\n"
        "Receita Municipal Validade: 15/03/2024 (*)\n"
        "Emitido em: 01/07/2024 09:00")
    c = ler_texto(t, "sicaf.pdf")
    assert c.tipo == TipoCertidao.SICAF
    assert c.situacao == Situacao.REGULAR
    assert _cob(c, "federal") == {"validade": date(2025, 2, 2), "automatica": True, "pendencia": False}
    assert _cob(c, "fgts")["validade"] == date(2024, 11, 13)
    assert _cob(c, "trabalhista") == {"validade": date(2025, 4, 22), "automatica": True, "pendencia": False}
    assert _cob(c, "estadual") == {"validade": date(2024, 7, 13), "automatica": False, "pendencia": False}
    assert _cob(c, "municipal") == {"validade": date(2024, 3, 15), "automatica": False, "pendencia": False}
    assert c.validade == date(2024, 3, 15)          # a mais próxima entre os itens
    assert c.data_emissao == date(2024, 7, 1)


def test_sicaf_datas_soltas_e_validade_deslocada():
    t = _SICAF_CAB + (
        "III - Regularidade Fiscal e Trabalhista Federal\n"
        "Receita Federal e PGFN 26/07/2024 Automática\n"
        "FGTS 13/11/2024 Manual\n"
        "Trabalhista 22/04/2025 Automática\n"
        "Validade:\nValidade:\nValidade:\n"
        "IV - Regularidade Fiscal Estadual/Distrital e Municipal\nNenhum registro encontrado\n")
    c = ler_texto(t)
    assert {k for k in c.cobertura_sicaf if not k.startswith("_")} == {"federal", "fgts", "trabalhista"}
    assert _cob(c, "federal")["validade"] == date(2024, 7, 26)
    assert _cob(c, "fgts") == {"validade": date(2024, 11, 13), "automatica": False, "pendencia": False}
    assert _cob(c, "trabalhista")["validade"] == date(2025, 4, 22)


def test_sicaf_data_na_linha_seguinte():
    t = _SICAF_CAB + (
        "III - Regularidade Fiscal e Trabalhista Federal\n"
        "Receita Federal e PGFN Validade:\n02/02/2025 Automática\n"
        "FGTS\nValidade: 13/11/2024\nAutomática\n"
        "Trabalhista Validade: 22/04/2025 Automática\n")
    c = ler_texto(t)
    assert _cob(c, "federal") == {"validade": date(2025, 2, 2), "automatica": True, "pendencia": False}
    assert _cob(c, "fgts") == {"validade": date(2024, 11, 13), "automatica": True, "pendencia": False}


def test_sicaf_colunas_rotulos_antes_das_datas():
    t = _SICAF_CAB + (
        "III - Regularidade Fiscal e Trabalhista Federal\n"
        "Receita Federal e PGFN\nFGTS\nTrabalhista\n"
        "Validade: 02/02/2025 Automática\nValidade: 13/11/2024 Manual\nValidade: 22/04/2025 Automática\n")
    c = ler_texto(t)
    assert _cob(c, "federal")["validade"] == date(2025, 2, 2)
    assert _cob(c, "fgts") == {"validade": date(2024, 11, 13), "automatica": False, "pendencia": False}
    assert _cob(c, "trabalhista")["validade"] == date(2025, 4, 22)


def test_sicaf_pendencia_marca_so_o_nivel():
    t = _SICAF_CAB + (
        "III - Regularidade Fiscal e Trabalhista Federal (Possui Pendência)\n"
        "Receita Federal e PGFN Validade: 02/02/2025 Automática\n"
        "FGTS Validade: 13/11/2024 Automática\n"
        "Trabalhista Validade: 22/04/2025 Automática\n"
        "IV - Regularidade Fiscal Estadual/Distrital e Municipal\n"
        "Receita Estadual/Distrital Validade: 13/07/2024 Automática\n")
    c = ler_texto(t)
    assert all(_cob(c, k)["pendencia"] for k in ("federal", "fgts", "trabalhista"))
    assert _cob(c, "estadual")["pendencia"] is False
    assert c.situacao == Situacao.INDETERMINADA
    assert any("pendência" in a for a in c.avisos)


def test_sicaf_sem_niveis_formato_antigo():
    t = _SICAF_CAB + ("Receita Federal e PGFN - Validade: 02/02/2027\n"
                      "FGTS - Validade: 13/11/2026\n")
    c = ler_texto(t)
    assert _cob(c, "federal") == {"validade": date(2027, 2, 2), "automatica": False, "pendencia": False}
    assert c.validade == date(2026, 11, 13)


def test_nao_sicaf_sem_cobertura():
    c = ler_texto(f"CERTIDÃO NEGATIVA DE DÉBITOS TRABALHISTAS\nCNPJ: {CNPJ}\nFGTS Validade: 10/12/2026")
    assert c.cobertura_sicaf == {}


def test_sicaf_com_cobertura_nao_chama_ia(amostras, monkeypatch):
    pasta, _ = amostras
    monkeypatch.setattr(ia, "habilitada", lambda: True)
    def _falha(*a, **k):
        raise AssertionError("IA não deveria ser chamada")
    monkeypatch.setattr(ia, "extrair_com_ia", _falha)
    c = ler_pdf(pasta / "sicaf_pendencia.pdf")
    assert c.metodo == "regras" and c.cobertura_sicaf


def test_sicaf_pendencia_nao_derruba_confianca(amostras):
    pasta, _ = amostras
    c = ler_pdf(pasta / "sicaf_pendencia.pdf")
    assert c.confianca >= 0.9
    assert not any("anterior à emissão" in a for a in c.avisos)


# ---------------------------------------------------------------- SICAF: revisão independente

def _tipos(c):
    return {k for k in c.cobertura_sicaf if not k.startswith("_")}


def test_sicaf_pendencia_depois_dos_itens_do_nivel():
    t = _SICAF_CAB + (
        "III - Regularidade Fiscal e Trabalhista Federal\n"
        "Receita Federal e PGFN Validade: 02/02/2027 Automática\n"
        "FGTS Validade: 13/11/2026 Automática\n"
        "Trabalhista Validade: 22/04/2027 Automática\n"
        "Situação do nível: Possui Pendência\n"
        "IV - Regularidade Fiscal Estadual/Distrital e Municipal\n"
        "Receita Estadual/Distrital Validade: 13/07/2027 Automática\n")
    c = ler_texto(t)
    assert all(_cob(c, k)["pendencia"] for k in ("federal", "fgts", "trabalhista"))
    assert _cob(c, "estadual")["pendencia"] is False
    assert any("nível III" in a for a in c.avisos)


def test_sicaf_nao_possui_pendencia_nao_marca():
    t = _SICAF_CAB + ("III - Regularidade Fiscal e Trabalhista Federal\n"
                      "FGTS Validade: 13/11/2026 Automática\nSituação do nível: Não possui pendência\n")
    c = ler_texto(t)
    assert _cob(c, "fgts")["pendencia"] is False
    assert c.situacao == Situacao.REGULAR


def test_sicaf_emitido_em_com_hora():
    c = ler_texto(_SICAF_CAB + "III - Regularidade Fiscal e Trabalhista Federal\n"
                  "FGTS Validade: 13/11/2026 Automática\nEmitido em: 27/10/2026 14:32\n")
    assert c.data_emissao == date(2026, 10, 27)


def test_sicaf_situacao_credenciado_nada_consta():
    t = _SICAF_CAB + ("Ocorrência: Nada Consta\nImpedimento de Licitar: Nada Consta\n"
                      "Ocorrências Impeditivas indiretas: Nada Consta\n"
                      "III - Regularidade Fiscal e Trabalhista Federal\nFGTS Validade: 13/11/2026 Automática\n")
    t = t.replace("Declaração\n", "Declaração\nDeclaramos que a situação do fornecedor no momento é a seguinte:\n")
    c = ler_texto(t)
    assert c.cobertura_sicaf["_situacao"] == {"credenciado": True, "situacao": "Credenciado",
                                              "impedimento": None}
    assert not any("SICAF: fornecedor" in a for a in c.avisos)


def test_sicaf_descredenciado_e_impedimento_geram_aviso():
    t = ("Sistema de Cadastramento Unificado de Fornecedores - SICAF\n"
         f"CNPJ: {CNPJ}\nSituação do Fornecedor: Descredenciado\n"
         "Ocorrências Impeditivas indiretas: Consta (sócio com impedimento)\n"
         "III - Regularidade Fiscal e Trabalhista Federal\nFGTS Validade: 13/11/2026 Automática\n")
    c = ler_texto(t)
    sit = c.cobertura_sicaf["_situacao"]
    assert sit["credenciado"] is False and sit["situacao"] == "Descredenciado"
    assert sit["impedimento"] == "Ocorrências Impeditivas indiretas: Consta (sócio com impedimento)"
    assert "SICAF: fornecedor Descredenciado" in c.avisos
    assert any("Ocorrências Impeditivas indiretas: Consta" in a for a in c.avisos)
    assert _tipos(c) == {"fgts"}


def test_sicaf_situacao_ausente():
    t = ("Sistema de Cadastramento Unificado de Fornecedores - SICAF\n"
         f"CNPJ: {CNPJ}\nIII - Regularidade Fiscal e Trabalhista Federal\nFGTS Validade: 13/11/2026 Automática\n")
    c = ler_texto(t)
    assert c.cobertura_sicaf["_situacao"]["credenciado"] is False
    assert c.cobertura_sicaf["_situacao"]["situacao"] is None
    assert any("situação do fornecedor não identificada" in a for a in c.avisos)


def test_sicaf_sem_itens_so_situacao_ainda_chama_regra_de_ia(monkeypatch):
    # só "_situacao" não conta como cobertura lida: confiança e IA tratam como antes
    t = ("Sistema de Cadastramento Unificado de Fornecedores - SICAF\n"
         f"CNPJ: {CNPJ}\nSituação do Fornecedor: Credenciado\nPossui Pendência\n")
    c = ler_texto(t)
    assert _tipos(c) == set()
    assert extrator._precisa_ia(c) is True
