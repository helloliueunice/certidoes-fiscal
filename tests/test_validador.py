from datetime import date, timedelta

import pytest

from certidoes.models import (
    Certidao, Contrato, Semaforo, Situacao, TipoCertidao as T,
)
from certidoes.validador import alerta_extra, nota_extra, resumo, validar

HOJE = date(2026, 10, 27)
CNPJ = "11222333000181"          # matriz (DV válido)
FILIAL = "11222333000262"        # mesma raiz
OUTRA = "99888777000166"


def contrato(uf="MG", mun="Belo Horizonte", exigidas=None):
    c = Contrato(numero="12/2026", cnpj=CNPJ, razao_social="Empresa Teste Ltda",
                 uf_sede=uf, municipio_sede=mun, fiscal="Maria", competencia="10/2026")
    if exigidas is not None:
        c.exigidas = exigidas
    return c


def cert(tipo, dias=100, situacao=Situacao.NEGATIVA, cnpj=CNPJ, **kw):
    base = dict(arquivo=f"{tipo.value}.pdf", tipo=tipo, situacao=situacao, cnpj=cnpj,
                validade=(HOJE + timedelta(days=dias)) if dias is not None else None,
                confianca=0.95, codigo_controle="ABC123", url_verificacao="https://exemplo.gov.br")
    base.update(kw)
    return Certidao(**base)


def item(res, tipo):
    return next(i for i in res.itens if i.tipo == tipo)


def kit(uf="MG", mun="Belo Horizonte"):
    return [cert(T.FEDERAL), cert(T.FGTS, situacao=Situacao.REGULAR), cert(T.TRABALHISTA),
            cert(T.ESTADUAL, uf=uf), cert(T.MUNICIPAL, uf=uf, municipio=mun)]


def test_tudo_verde_ordem_e_resumo():
    res = validar(contrato(), kit(), hoje=HOJE)
    assert [i.tipo for i in res.itens] == contrato().exigidas
    assert all(i.semaforo == Semaforo.VERDE for i in res.itens)
    assert "Válida até 04/02/2027 (100 dias)." in res.itens[0].mensagem
    assert res.apto_atesto
    r = resumo(res)
    assert r["verde"] == 5 and r["vermelho"] == 0 and r["apto_atesto"] is True


def test_faltante_vermelho():
    certs = [c for c in kit() if c.tipo != T.FGTS]
    res = validar(contrato(), certs, hoje=HOJE)
    i = item(res, T.FGTS)
    assert i.semaforo == Semaforo.VERMELHO and i.mensagem == "Não enviada." and i.certidao is None
    assert not res.apto_atesto


def test_positiva_vermelho():
    res = validar(contrato(exigidas=[T.FEDERAL]),
                  [cert(T.FEDERAL, situacao=Situacao.POSITIVA)], hoje=HOJE)
    assert res.itens[0].semaforo == Semaforo.VERMELHO
    assert "Certidão POSITIVA: débitos exigíveis. Não atestar sem regularização." in res.itens[0].mensagem


def test_positiva_efeito_negativa_verde():
    res = validar(contrato(exigidas=[T.FEDERAL]),
                  [cert(T.FEDERAL, situacao=Situacao.POSITIVA_EFEITO_NEGATIVA)], hoje=HOJE)
    assert res.itens[0].semaforo == Semaforo.VERDE


def test_vencida_ontem_vermelho():
    res = validar(contrato(exigidas=[T.TRABALHISTA]), [cert(T.TRABALHISTA, dias=-1)], hoje=HOJE)
    assert res.itens[0].semaforo == Semaforo.VERMELHO
    assert "Vencida em 26/10/2026." in res.itens[0].mensagem


def test_vence_hoje_amarelo():
    res = validar(contrato(exigidas=[T.TRABALHISTA]), [cert(T.TRABALHISTA, dias=0)], hoje=HOJE)
    assert res.itens[0].semaforo == Semaforo.AMARELO
    assert "hoje" in res.itens[0].mensagem


@pytest.mark.parametrize("dias,esperado", [(15, Semaforo.AMARELO), (16, Semaforo.VERDE), (1, Semaforo.AMARELO)])
def test_dias_alerta(dias, esperado):
    res = validar(contrato(exigidas=[T.FGTS]),
                  [cert(T.FGTS, dias=dias, situacao=Situacao.REGULAR)], hoje=HOJE)
    assert res.itens[0].semaforo == esperado


def test_dias_alerta_configuravel():
    res = validar(contrato(exigidas=[T.FGTS]), [cert(T.FGTS, dias=20, situacao=Situacao.REGULAR)],
                  hoje=HOJE, dias_alerta=30)
    assert res.itens[0].semaforo == Semaforo.AMARELO


def test_cnpj_outra_empresa_vermelho():
    res = validar(contrato(exigidas=[T.FEDERAL]), [cert(T.FEDERAL, cnpj=OUTRA)], hoje=HOJE)
    assert res.itens[0].semaforo == Semaforo.VERMELHO
    assert "outra empresa" in res.itens[0].mensagem


def test_cnpj_ausente_amarelo():
    res = validar(contrato(exigidas=[T.FGTS]),
                  [cert(T.FGTS, cnpj=None, situacao=Situacao.REGULAR)], hoje=HOJE)
    assert res.itens[0].semaforo == Semaforo.AMARELO
    assert "CNPJ não encontrado" in res.itens[0].mensagem


def test_filial_amarelo():
    res = validar(contrato(exigidas=[T.FGTS]),
                  [cert(T.FGTS, cnpj=FILIAL, situacao=Situacao.REGULAR)], hoje=HOJE)
    assert res.itens[0].semaforo == Semaforo.AMARELO
    assert "outro estabelecimento" in res.itens[0].mensagem


def test_federal_de_filial_verde_com_nota():
    res = validar(contrato(exigidas=[T.FEDERAL]), [cert(T.FEDERAL, cnpj=FILIAL)], hoje=HOJE)
    assert res.itens[0].semaforo == Semaforo.VERDE
    assert "matriz e filiais" in res.itens[0].mensagem


def test_prefere_cnpj_exato_e_maior_validade():
    a = cert(T.FGTS, dias=30, situacao=Situacao.REGULAR, arquivo="a.pdf")
    b = cert(T.FGTS, dias=60, situacao=Situacao.REGULAR, arquivo="b.pdf")
    c = cert(T.FGTS, dias=90, cnpj=OUTRA, situacao=Situacao.REGULAR, arquivo="c.pdf")
    res = validar(contrato(exigidas=[T.FGTS]), [a, b, c], hoje=HOJE)
    assert res.itens[0].certidao is b
    assert {x.arquivo for x in res.extras} == {"a.pdf", "c.pdf"}


def test_prefere_valida_a_vencida():
    v = cert(T.TRABALHISTA, dias=-5, arquivo="v.pdf")
    ok = cert(T.TRABALHISTA, dias=40, arquivo="ok.pdf")
    res = validar(contrato(exigidas=[T.TRABALHISTA]), [v, ok], hoje=HOJE)
    assert res.itens[0].certidao is ok and res.itens[0].semaforo == Semaforo.VERDE


def test_ia_amarelo():
    res = validar(contrato(exigidas=[T.TRABALHISTA]), [cert(T.TRABALHISTA, metodo="ia")], hoje=HOJE)
    assert res.itens[0].semaforo == Semaforo.AMARELO
    assert "IA" in res.itens[0].mensagem


def test_baixa_confianca_amarelo():
    res = validar(contrato(exigidas=[T.TRABALHISTA]), [cert(T.TRABALHISTA, confianca=0.5)], hoje=HOJE)
    assert res.itens[0].semaforo == Semaforo.AMARELO


def test_avisos_extrator_amarelo():
    res = validar(contrato(exigidas=[T.TRABALHISTA]),
                  [cert(T.TRABALHISTA, avisos=["Data de emissão não encontrada"])], hoje=HOJE)
    assert res.itens[0].semaforo == Semaforo.AMARELO
    assert "Data de emissão não encontrada" in res.itens[0].mensagem


def test_validade_ausente_amarelo():
    res = validar(contrato(exigidas=[T.TRABALHISTA]), [cert(T.TRABALHISTA, dias=None)], hoje=HOJE)
    assert res.itens[0].semaforo == Semaforo.AMARELO
    assert "Validade não identificada" in res.itens[0].mensagem


def test_indeterminada_sem_validade_vermelho():
    res = validar(contrato(exigidas=[T.TRABALHISTA]),
                  [cert(T.TRABALHISTA, dias=None, situacao=Situacao.INDETERMINADA)], hoje=HOJE)
    assert res.itens[0].semaforo == Semaforo.VERMELHO


def test_indeterminada_com_validade_amarelo():
    res = validar(contrato(exigidas=[T.TRABALHISTA]),
                  [cert(T.TRABALHISTA, situacao=Situacao.INDETERMINADA)], hoje=HOJE)
    assert res.itens[0].semaforo == Semaforo.AMARELO


def test_estadual_outra_uf_amarelo_e_prefere_sede():
    rj = cert(T.ESTADUAL, uf="RJ", dias=200, arquivo="rj.pdf")
    res = validar(contrato(exigidas=[T.ESTADUAL]), [rj], hoje=HOJE)
    assert res.itens[0].semaforo == Semaforo.AMARELO
    assert "RJ" in res.itens[0].mensagem and "MG" in res.itens[0].mensagem
    mg = cert(T.ESTADUAL, uf="MG", dias=50, arquivo="mg.pdf")
    res = validar(contrato(exigidas=[T.ESTADUAL]), [rj, mg], hoje=HOJE)
    assert res.itens[0].certidao is mg and res.itens[0].semaforo == Semaforo.VERDE
    assert res.extras == [rj]


def test_municipal_prefere_sede():
    outro = cert(T.MUNICIPAL, uf="MG", municipio="Contagem", dias=300, arquivo="cont.pdf")
    sede = cert(T.MUNICIPAL, uf="MG", municipio="Belo Horizonte", dias=30, arquivo="bh.pdf")
    res = validar(contrato(exigidas=[T.MUNICIPAL]), [outro, sede], hoje=HOJE)
    assert res.itens[0].certidao is sede and res.itens[0].semaforo == Semaforo.VERDE


def test_sp_com_uma_so_estadual_vermelho():
    c = contrato(uf="SP", mun="São Paulo", exigidas=[T.ESTADUAL])
    pge = cert(T.ESTADUAL, uf="SP", orgao_emissor="PGE-SP Procuradoria Geral do Estado",
               arquivo="pge.pdf")
    res = validar(c, [pge], hoje=HOJE)
    i = res.itens[0]
    assert i.semaforo == Semaforo.VERMELHO
    assert not res.apto_atesto
    assert "Em SP são exigidas a certidão da PGE (dívida ativa) e a da SEFAZ (débitos não inscritos); falta uma" in i.mensagem
    assert "SEFAZ" in i.mensagem


def test_sp_com_as_duas_verde():
    c = contrato(uf="SP", mun="São Paulo", exigidas=[T.ESTADUAL])
    pge = cert(T.ESTADUAL, uf="SP", orgao_emissor="PGE-SP", arquivo="pge.pdf")
    sefaz = cert(T.ESTADUAL, uf="SP", orgao_emissor="SEFAZ-SP",
                 texto="Débitos tributários não inscritos na dívida ativa", arquivo="sefaz.pdf")
    res = validar(c, [pge, sefaz], hoje=HOJE)
    assert res.itens[0].semaforo == Semaforo.VERDE
    assert "PGE" in res.itens[0].mensagem and "SEFAZ" in res.itens[0].mensagem
    # a complementar aparece nos extras com nota explicativa
    assert len(res.extras) == 1
    assert "Complementa" in nota_extra(res.extras[0], res)


def test_sp_duas_uma_positiva_vermelho():
    c = contrato(uf="SP", mun="São Paulo", exigidas=[T.ESTADUAL])
    pge = cert(T.ESTADUAL, uf="SP", orgao_emissor="PGE-SP", situacao=Situacao.POSITIVA, arquivo="pge.pdf")
    sefaz = cert(T.ESTADUAL, uf="SP", orgao_emissor="SEFAZ-SP", arquivo="sefaz.pdf")
    res = validar(c, [pge, sefaz], hoje=HOJE)
    assert res.itens[0].semaforo == Semaforo.VERMELHO
    assert res.itens[0].certidao is pge


def test_sicaf_nao_exigido_vai_para_extras():
    sicaf = cert(T.SICAF, situacao=Situacao.REGULAR, arquivo="sicaf.pdf")
    certs = [c for c in kit() if c.tipo != T.FGTS] + [sicaf]
    res = validar(contrato(), certs, hoje=HOJE)
    assert item(res, T.FGTS).semaforo == Semaforo.VERMELHO   # não supre automaticamente
    assert sicaf in res.extras
    assert "fiscal decide" in nota_extra(sicaf, res)


def test_extras_desconhecida_e_outra():
    d = cert(T.DESCONHECIDA, situacao=Situacao.INDETERMINADA, arquivo="x.pdf")
    o = cert(T.OUTRA, arquivo="ceis.pdf")
    res = validar(contrato(), kit() + [d, o], hoje=HOJE)
    assert d in res.extras and o in res.extras
    assert res.apto_atesto
    assert resumo(res)["extras"] == 2


def test_hoje_padrao():
    res = validar(contrato(exigidas=[T.FEDERAL]), [])
    assert res.data_referencia == date.today()


# ---------------------------------------------------- correções da revisão

def test_positiva_mais_recente_prevalece():
    antiga = cert(T.TRABALHISTA, dias=150, arquivo="neg.pdf", data_emissao=date(2026, 9, 1))
    nova = cert(T.TRABALHISTA, dias=100, situacao=Situacao.POSITIVA, arquivo="pos.pdf",
                data_emissao=date(2026, 10, 20))
    res = validar(contrato(exigidas=[T.TRABALHISTA]), [antiga, nova], hoje=HOJE)
    i = res.itens[0]
    assert i.semaforo == Semaforo.VERMELHO
    assert i.certidao is nova   # a mais recente é a escolhida


def test_mensagem_positiva_mais_recente():
    from certidoes.validador import _avaliar_no_grupo
    neg = cert(T.FGTS, situacao=Situacao.REGULAR, data_emissao=date(2026, 9, 1))
    pos = cert(T.FGTS, situacao=Situacao.POSITIVA, arquivo="pos.pdf",
               data_emissao=date(2026, 10, 2))
    sem, msg = _avaliar_no_grupo(neg, [neg, pos], contrato(), HOJE, 15)
    assert sem == Semaforo.VERMELHO
    assert ("Há certidão POSITIVA mais recente (emitida em 02/10/2026) — "
            "prevalece a mais recente") in msg


def test_positiva_mais_antiga_nao_afeta():
    nova = cert(T.TRABALHISTA, dias=150, arquivo="neg.pdf", data_emissao=date(2026, 10, 20))
    antiga = cert(T.TRABALHISTA, dias=100, situacao=Situacao.POSITIVA, arquivo="pos.pdf",
                  data_emissao=date(2026, 9, 1))
    res = validar(contrato(exigidas=[T.TRABALHISTA]), [antiga, nova], hoje=HOJE)
    assert res.itens[0].certidao is nova
    assert res.itens[0].semaforo == Semaforo.VERDE


def test_prefere_mais_recente_por_emissao():
    a = cert(T.FGTS, dias=60, situacao=Situacao.REGULAR, arquivo="a.pdf",
             data_emissao=date(2026, 9, 1))
    b = cert(T.FGTS, dias=30, situacao=Situacao.REGULAR, arquivo="b.pdf",
             data_emissao=date(2026, 10, 10))
    res = validar(contrato(exigidas=[T.FGTS]), [a, b], hoje=HOJE)
    assert res.itens[0].certidao is b


def test_sp_sem_subtipo_nao_rotula_pge():
    c = contrato(uf="SP", mun="São Paulo", exigidas=[T.ESTADUAL])
    pge = cert(T.ESTADUAL, uf="SP", orgao_emissor="PGE-SP", arquivo="pge.pdf")
    x = cert(T.ESTADUAL, uf="SP", orgao_emissor="Governo do Estado", arquivo="x.pdf")
    res = validar(c, [pge, x], hoje=HOJE)
    i = res.itens[0]
    assert i.semaforo == Semaforo.AMARELO
    assert "Estadual (órgão não identificado: conferir se é PGE ou SEFAZ)" in i.mensagem
    assert i.mensagem.count("PGE (dívida ativa):") == 1


def test_sp_so_uma_sem_subtipo():
    c = contrato(uf="SP", mun="São Paulo", exigidas=[T.ESTADUAL])
    x = cert(T.ESTADUAL, uf="SP", orgao_emissor="Governo do Estado", arquivo="x.pdf")
    i = validar(c, [x], hoje=HOJE).itens[0]
    assert i.semaforo == Semaforo.VERMELHO
    assert "PGE (dívida ativa):" not in i.mensagem
    assert "órgão não identificado" in i.mensagem


def test_extra_positiva_nao_exigida_alerta():
    ceis = cert(T.OUTRA, situacao=Situacao.POSITIVA, arquivo="ceis.pdf")
    res = validar(contrato(), kit() + [ceis], hoje=HOJE)
    assert ceis in res.extras
    msg = nota_extra(ceis, res)
    assert "Atenção: certidão POSITIVA enviada, embora não exigida — avaliar" in msg
    assert alerta_extra(ceis, res)


def test_extra_vencida_alerta():
    sicaf = cert(T.SICAF, situacao=Situacao.REGULAR, dias=-3, arquivo="sicaf.pdf")
    res = validar(contrato(), kit() + [sicaf], hoje=HOJE)
    assert "vencida em 24/10/2026" in nota_extra(sicaf, res)


def test_extra_ok_sem_alerta():
    ceis = cert(T.OUTRA, arquivo="ceis.pdf")
    res = validar(contrato(), kit() + [ceis], hoje=HOJE)
    assert alerta_extra(ceis, res) == ""


def test_sp_estadual_de_outra_uf_nao_complementa():
    c = contrato(uf="SP", mun="São Paulo", exigidas=[T.ESTADUAL])
    pge = cert(T.ESTADUAL, uf="SP", orgao_emissor="PGE-SP", arquivo="pge.pdf")
    sefaz = cert(T.ESTADUAL, uf="SP", orgao_emissor="SEFAZ-SP", arquivo="sefaz.pdf")
    rj = cert(T.ESTADUAL, uf="RJ", orgao_emissor="SEFAZ-RJ", arquivo="rj.pdf")
    res = validar(c, [pge, sefaz, rj], hoje=HOJE)
    assert rj in res.extras
    assert "Complementa" not in nota_extra(rj, res)
