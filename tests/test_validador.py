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


# ---------------------------------------------------------------- SICAF como comprovação

def cob(dias=100, automatica=True, pendencia=False):
    return {"validade": HOJE + timedelta(days=dias) if dias is not None else None,
            "automatica": automatica, "pendencia": pendencia}


CREDENCIADO = {"credenciado": True, "situacao": "Credenciado", "impedimento": None}


def sicaf_cert(cobertura=None, cnpj=CNPJ, arquivo="sicaf.pdf", situacao_forn=CREDENCIADO, **kw):
    if cobertura is None:
        cobertura = {t.value: cob() for t in (T.FEDERAL, T.FGTS, T.TRABALHISTA, T.ESTADUAL, T.MUNICIPAL)}
    cobertura = dict(cobertura)
    if situacao_forn is not None:
        cobertura["_situacao"] = situacao_forn
    kw.setdefault("situacao", Situacao.REGULAR)
    kw.setdefault("data_emissao", HOJE)
    return cert(T.SICAF, cnpj=cnpj, arquivo=arquivo, cobertura_sicaf=cobertura, **kw)


def contrato_sicaf(**kw):
    c = contrato(**kw)
    c.aceitar_sicaf = True
    return c


def test_sicaf_sozinho_comprova_tudo_verde():
    s = sicaf_cert()
    res = validar(contrato_sicaf(), [s], hoje=HOJE)
    assert all(i.semaforo == Semaforo.VERDE for i in res.itens)
    assert all(i.certidao is s for i in res.itens)
    assert item(res, T.FGTS).mensagem == (
        "Comprovada pelo SICAF (obtida automaticamente do emissor). Válida até 04/02/2027 (100 dias).")
    assert s not in res.extras
    assert res.apto_atesto


@pytest.mark.parametrize("dias,esperado", [(16, Semaforo.VERDE), (15, Semaforo.AMARELO),
                                           (0, Semaforo.AMARELO), (-1, Semaforo.VERMELHO)])
def test_sicaf_limites_de_validade(dias, esperado):
    s = sicaf_cert({"fgts": cob(dias)})
    res = validar(contrato_sicaf(exigidas=[T.FGTS]), [s], hoje=HOJE)
    assert res.itens[0].semaforo == esperado
    assert res.itens[0].certidao is s
    if esperado == Semaforo.VERMELHO:
        assert res.itens[0].mensagem.startswith("SICAF: certidão vencida em 26/10/2026.")
        assert "Não comprovada" not in res.itens[0].mensagem


def test_sicaf_manual_amarelo():
    res = validar(contrato_sicaf(exigidas=[T.MUNICIPAL]),
                  [sicaf_cert({"municipal": cob(automatica=False)})], hoje=HOJE)
    i = res.itens[0]
    assert i.semaforo == Semaforo.AMARELO
    assert "inserida manualmente pelo fornecedor no SICAF: conferir a certidão no site do emissor" in i.mensagem
    assert "automaticamente" not in i.mensagem


def test_sicaf_pendencia_no_nivel_amarelo():
    res = validar(contrato_sicaf(exigidas=[T.ESTADUAL]),
                  [sicaf_cert({"estadual": cob(pendencia=True)})], hoje=HOJE)
    assert res.itens[0].semaforo == Semaforo.AMARELO
    assert "pendência" in res.itens[0].mensagem


def test_sicaf_validade_ausente_amarelo():
    res = validar(contrato_sicaf(exigidas=[T.FGTS]), [sicaf_cert({"fgts": cob(None)})], hoje=HOJE)
    assert res.itens[0].semaforo == Semaforo.AMARELO


def test_sicaf_sem_o_item_continua_nao_enviada():
    s = sicaf_cert({"federal": cob()})
    res = validar(contrato_sicaf(exigidas=[T.FEDERAL, T.MUNICIPAL]), [s], hoje=HOJE)
    m = item(res, T.MUNICIPAL)
    assert m.semaforo == Semaforo.VERMELHO and m.certidao is None
    assert m.mensagem.startswith("Não enviada.") and "não traz esta certidão" in m.mensagem
    assert s not in res.extras   # usado no federal


def test_sicaf_propria_verde_tem_prioridade():
    s = sicaf_cert()
    res = validar(contrato_sicaf(), kit() + [s], hoje=HOJE)
    assert all(i.certidao.tipo != T.SICAF for i in res.itens)
    assert all("SICAF" not in i.mensagem for i in res.itens)
    assert s in res.extras
    assert "não utilizado" in nota_extra(s, res)


def test_sicaf_propria_vermelha_e_sicaf_verde_usa_melhor_e_cita_as_duas():
    propria = cert(T.FEDERAL, dias=-2, arquivo="cnd_vencida.pdf")
    s = sicaf_cert({"federal": cob()})
    res = validar(contrato_sicaf(exigidas=[T.FEDERAL]), [propria, s], hoje=HOJE)
    i = res.itens[0]
    assert i.semaforo == Semaforo.VERDE and i.certidao is s
    assert "Comprovada pelo SICAF" in i.mensagem
    assert "cnd_vencida.pdf" in i.mensagem and "Vencida em 25/10/2026" in i.mensagem
    assert propria in res.extras and s not in res.extras
    assert "comprovado pela declaração do SICAF" in nota_extra(propria, res)


def test_sicaf_propria_vermelha_e_sicaf_vermelho_mantem_propria():
    propria = cert(T.FEDERAL, situacao=Situacao.POSITIVA)
    s = sicaf_cert({"federal": cob(-1)})
    res = validar(contrato_sicaf(exigidas=[T.FEDERAL]), [propria, s], hoje=HOJE)
    i = res.itens[0]
    assert i.semaforo == Semaforo.VERMELHO and i.certidao is propria
    assert "POSITIVA" in i.mensagem and "SICAF" in i.mensagem
    assert s in res.extras


def test_sicaf_propria_amarela_tem_prioridade_mas_cita_sicaf():
    propria = cert(T.TRABALHISTA, dias=5)
    s = sicaf_cert({"trabalhista": cob(150)})
    res = validar(contrato_sicaf(exigidas=[T.TRABALHISTA]), [propria, s], hoje=HOJE)
    i = res.itens[0]
    assert i.semaforo == Semaforo.AMARELO and i.certidao is propria
    assert "SICAF: Comprovada pelo SICAF" in i.mensagem


def test_sicaf_sp_estadual_amarelo_com_nota():
    c = contrato_sicaf(uf="SP", mun="São Paulo", exigidas=[T.ESTADUAL])
    s = sicaf_cert({"estadual": cob()})
    res = validar(c, [s], hoje=HOJE)
    assert res.itens[0].semaforo == Semaforo.AMARELO and res.itens[0].certidao is s
    assert "SICAF traz uma única certidão estadual; em SP confira PGE e SEFAZ" in res.itens[0].mensagem


def test_sicaf_sp_so_pge_propria_vermelha_sicaf_supre_com_amarelo():
    c = contrato_sicaf(uf="SP", mun="São Paulo", exigidas=[T.ESTADUAL])
    pge = cert(T.ESTADUAL, uf="SP", orgao_emissor="PGE-SP", arquivo="pge.pdf",
               texto="divida ativa")
    s = sicaf_cert({"estadual": cob()})
    res = validar(c, [pge, s], hoje=HOJE)
    i = res.itens[0]
    assert i.semaforo == Semaforo.AMARELO and i.certidao is s
    assert "pge.pdf" in i.mensagem
    assert pge in res.extras
    assert "Complementa" not in nota_extra(pge, res)


def test_sicaf_cnpj_diferente_nao_comprova():
    s = sicaf_cert(cnpj=OUTRA)
    res = validar(contrato_sicaf(exigidas=[T.FGTS]), [s], hoje=HOJE)
    i = res.itens[0]
    assert i.semaforo == Semaforo.VERMELHO and i.certidao is None
    assert i.mensagem.startswith("Não enviada.") and "outro CNPJ" in i.mensagem
    assert s in res.extras and "outro CNPJ" in nota_extra(s, res)


def test_sicaf_de_filial():
    s = sicaf_cert(cnpj=FILIAL)
    res = validar(contrato_sicaf(exigidas=[T.FEDERAL, T.FGTS]), [s], hoje=HOJE)
    assert item(res, T.FEDERAL).semaforo == Semaforo.VERDE
    assert "abrange matriz e filiais" in item(res, T.FEDERAL).mensagem
    assert item(res, T.FGTS).semaforo == Semaforo.AMARELO
    assert "outro estabelecimento" in item(res, T.FGTS).mensagem


def test_sicaf_cnpj_ausente_amarelo():
    res = validar(contrato_sicaf(exigidas=[T.FGTS]), [sicaf_cert(cnpj=None)], hoje=HOJE)
    assert res.itens[0].semaforo == Semaforo.AMARELO


def test_sicaf_mais_recente_prevalece():
    antigo = sicaf_cert({"fgts": cob(-3)}, arquivo="antigo.pdf", data_emissao=HOJE - timedelta(days=60))
    novo = sicaf_cert({"fgts": cob(40)}, arquivo="novo.pdf", data_emissao=HOJE - timedelta(days=1))
    res = validar(contrato_sicaf(exigidas=[T.FGTS]), [antigo, novo], hoje=HOJE)
    assert res.itens[0].certidao is novo and res.itens[0].semaforo == Semaforo.VERDE
    assert antigo in res.extras and novo not in res.extras


def test_sicaf_extraido_por_ia_amarelo():
    s = sicaf_cert({"fgts": cob()}, metodo="ia")
    res = validar(contrato_sicaf(exigidas=[T.FGTS]), [s], hoje=HOJE)
    assert res.itens[0].semaforo == Semaforo.AMARELO


def test_sicaf_nao_aceito_mantem_comportamento_e_sugere_marcar():
    s = sicaf_cert()
    res = validar(contrato(exigidas=[T.FGTS]), [s], hoje=HOJE)
    assert res.itens[0].semaforo == Semaforo.VERMELHO and res.itens[0].mensagem == "Não enviada."
    assert s in res.extras
    assert "marque 'Aceitar SICAF'" in nota_extra(s, res)


def test_sicaf_aceito_sem_cobertura_lida():
    s = cert(T.SICAF, situacao=Situacao.REGULAR, arquivo="sicaf.pdf")
    res = validar(contrato_sicaf(exigidas=[T.FGTS]), [s], hoje=HOJE)
    assert res.itens[0].semaforo == Semaforo.VERMELHO
    assert s in res.extras and "conferir manualmente" in nota_extra(s, res)


def test_sicaf_amostras_pdf(tmp_path):
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import gerar_amostras
    from certidoes.extrator import ler_pdf

    gerar_amostras.gerar(tmp_path)
    hoje = date.today()
    c = Contrato(numero="1/2026", cnpj=gerar_amostras.CNPJ_EMPRESA, razao_social="X",
                 uf_sede="MG", municipio_sede="Belo Horizonte", aceitar_sicaf=True)
    res = validar(c, [ler_pdf(tmp_path / "sicaf.pdf")], hoje=hoje)
    cores = {i.tipo: i.semaforo for i in res.itens}
    assert cores == {T.FEDERAL: Semaforo.VERDE, T.FGTS: Semaforo.VERDE, T.TRABALHISTA: Semaforo.VERDE,
                     T.ESTADUAL: Semaforo.AMARELO, T.MUNICIPAL: Semaforo.AMARELO}
    assert res.apto_atesto and not res.extras

    res = validar(c, [ler_pdf(tmp_path / "sicaf_pendencia.pdf")], hoje=hoje)
    cores = {i.tipo: i.semaforo for i in res.itens}
    # pendência na declaração (situação indeterminada) deixa todos os itens no mínimo amarelos
    assert cores == {T.FEDERAL: Semaforo.AMARELO, T.FGTS: Semaforo.AMARELO, T.TRABALHISTA: Semaforo.AMARELO,
                     T.ESTADUAL: Semaforo.AMARELO, T.MUNICIPAL: Semaforo.VERMELHO}
    assert not res.apto_atesto

    res = validar(c, [ler_pdf(tmp_path / "sicaf_descredenciado.pdf")], hoje=hoje)
    cores = {i.tipo: i.semaforo for i in res.itens}
    assert cores == {T.FEDERAL: Semaforo.AMARELO, T.FGTS: Semaforo.AMARELO, T.TRABALHISTA: Semaforo.AMARELO,
                     T.ESTADUAL: Semaforo.VERMELHO, T.MUNICIPAL: Semaforo.VERMELHO}
    fed = item(res, T.FEDERAL).mensagem
    assert "SICAF: fornecedor Descredenciado" in fed and "Impedimento de Licitar: Consta" in fed



# ---------------------------------------------------------------- SICAF: revisão independente

def _amostras_tmp(tmp_path):
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import gerar_amostras
    gerar_amostras.gerar(tmp_path)
    return gerar_amostras


def test_cndt_positiva_recente_nao_e_substituida_por_sicaf_antigo(tmp_path):
    """Reprodução da revisão: cndt_positiva.pdf (há 10 dias) + SICAF de 60 dias atrás."""
    from certidoes.extrator import ler_pdf
    ga = _amostras_tmp(tmp_path)
    hoje = date.today()
    pos = ler_pdf(tmp_path / "cndt_positiva.pdf")
    s = sicaf_cert({"trabalhista": cob()}, cnpj=ga.CNPJ_EMPRESA, data_emissao=hoje - timedelta(days=60))
    c = Contrato(numero="1", cnpj=ga.CNPJ_EMPRESA, razao_social="X", uf_sede="MG",
                 municipio_sede="BH", aceitar_sicaf=True, exigidas=[T.TRABALHISTA])
    i = validar(c, [pos, s], hoje=hoje).itens[0]
    assert i.semaforo == Semaforo.VERMELHO and i.certidao is pos
    assert (f"Certidão própria POSITIVA emitida em {(hoje - timedelta(days=10)).strftime('%d/%m/%Y')} é mais "
            f"recente que a declaração do SICAF de {(hoje - timedelta(days=60)).strftime('%d/%m/%Y')} "
            "— prevalece a mais recente") in i.mensagem


@pytest.mark.parametrize("dias_pos,dias_sicaf", [(10, 60), (0, 0), (None, 0), (5, None)])
def test_positiva_propria_mais_recente_ou_mesma_data_vermelho(dias_pos, dias_sicaf):
    pos = cert(T.TRABALHISTA, situacao=Situacao.POSITIVA,
               data_emissao=HOJE - timedelta(days=dias_pos) if dias_pos is not None else None)
    s = sicaf_cert({"trabalhista": cob()},
                   data_emissao=HOJE - timedelta(days=dias_sicaf) if dias_sicaf is not None else None)
    res = validar(contrato_sicaf(exigidas=[T.TRABALHISTA]), [pos, s], hoje=HOJE)
    i = res.itens[0]
    assert i.semaforo == Semaforo.VERMELHO and i.certidao is pos
    assert "prevalece a mais recente" in i.mensagem
    assert "Declaração do SICAF (não prevaleceu)" in i.mensagem
    assert s in res.extras and "não prevaleceu" in nota_extra(s, res)


def test_sicaf_mais_recente_que_positiva_amarelo_conflito():
    pos = cert(T.TRABALHISTA, situacao=Situacao.POSITIVA, data_emissao=HOJE - timedelta(days=30))
    s = sicaf_cert({"trabalhista": cob()}, data_emissao=HOJE)
    i = validar(contrato_sicaf(exigidas=[T.TRABALHISTA]), [pos, s], hoje=HOJE).itens[0]
    assert i.semaforo == Semaforo.AMARELO and i.certidao is s
    assert ("conflito: certidão própria POSITIVA de 27/09/2026; SICAF de 27/10/2026 indica regular "
            "— confira no site do emissor") in i.mensagem


def test_positiva_mais_recente_que_negativa_propria_tambem_conta():
    neg = cert(T.FEDERAL, data_emissao=HOJE - timedelta(days=20), arquivo="neg.pdf")
    pos = cert(T.FEDERAL, situacao=Situacao.POSITIVA, data_emissao=HOJE - timedelta(days=5), arquivo="pos.pdf")
    s = sicaf_cert({"federal": cob()}, data_emissao=HOJE - timedelta(days=30))
    i = validar(contrato_sicaf(exigidas=[T.FEDERAL]), [neg, pos, s], hoje=HOJE).itens[0]
    assert i.semaforo == Semaforo.VERMELHO and "POSITIVA" in i.mensagem


def test_sicaf_com_situacao_indeterminada_minimo_amarelo():
    s = sicaf_cert({"federal": cob()}, situacao=Situacao.INDETERMINADA)
    i = validar(contrato_sicaf(exigidas=[T.FEDERAL]), [s], hoje=HOJE).itens[0]
    assert i.semaforo == Semaforo.AMARELO and "pendência" in i.mensagem


@pytest.mark.parametrize("dias,esperado", [(0, Semaforo.VERDE), (3, Semaforo.VERDE), (4, Semaforo.AMARELO)])
def test_sicaf_data_emissao_antiga(dias, esperado):
    s = sicaf_cert({"fgts": cob()}, data_emissao=HOJE - timedelta(days=dias))
    i = validar(contrato_sicaf(exigidas=[T.FGTS]), [s], hoje=HOJE).itens[0]
    assert i.semaforo == esperado
    if esperado == Semaforo.AMARELO:
        assert ("Declaração do SICAF emitida em 23/10/2026 (há 4 dias): consulte o SICAF novamente "
                "na data do atesto") in i.mensagem


def test_sicaf_data_emissao_ausente():
    s = sicaf_cert({"fgts": cob()}, data_emissao=None)
    i = validar(contrato_sicaf(exigidas=[T.FGTS]), [s], hoje=HOJE).itens[0]
    assert i.semaforo == Semaforo.AMARELO
    assert "consulte o SICAF novamente na data do atesto" in i.mensagem


@pytest.mark.parametrize("valor,esperado", [("10", Semaforo.VERDE), ("1", Semaforo.AMARELO),
                                            ("abc", Semaforo.AMARELO)])
def test_sicaf_max_dias_configuravel(monkeypatch, valor, esperado):
    monkeypatch.setenv("CERTIDOES_SICAF_MAX_DIAS", valor)
    s = sicaf_cert({"fgts": cob()}, data_emissao=HOJE - timedelta(days=4 if valor == "10" else 2 if valor == "1" else 4))
    assert validar(contrato_sicaf(exigidas=[T.FGTS]), [s], hoje=HOJE).itens[0].semaforo == esperado


def test_sicaf_descredenciado_amarelo():
    s = sicaf_cert({"fgts": cob()},
                   situacao_forn={"credenciado": False, "situacao": "Descredenciado", "impedimento": None})
    i = validar(contrato_sicaf(exigidas=[T.FGTS]), [s], hoje=HOJE).itens[0]
    assert i.semaforo == Semaforo.AMARELO and "SICAF: fornecedor Descredenciado" in i.mensagem


def test_sicaf_impedimento_amarelo():
    imp = "Impedimento de Licitar: Consta - suspensão"
    s = sicaf_cert({"fgts": cob()}, situacao_forn={**CREDENCIADO, "impedimento": imp})
    i = validar(contrato_sicaf(exigidas=[T.FGTS]), [s], hoje=HOJE).itens[0]
    assert i.semaforo == Semaforo.AMARELO and f"SICAF: {imp}" in i.mensagem


def test_sicaf_situacao_fornecedor_nao_lida_amarelo():
    s = sicaf_cert({"fgts": cob()}, situacao_forn=None)
    i = validar(contrato_sicaf(exigidas=[T.FGTS]), [s], hoje=HOJE).itens[0]
    assert i.semaforo == Semaforo.AMARELO and "situação do fornecedor não identificada" in i.mensagem


def test_sicaf_so_com_chave_reservada_nao_comprova():
    s = sicaf_cert({})
    res = validar(contrato_sicaf(exigidas=[T.FGTS]), [s], hoje=HOJE)
    assert res.itens[0].semaforo == Semaforo.VERMELHO
    assert "sem itens de regularidade" in nota_extra(s, res)
