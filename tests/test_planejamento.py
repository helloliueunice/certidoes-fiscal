"""Testes do planejamento do mutirão mensal (certidoes/planejamento.py)."""
import csv
import io
from datetime import date, timedelta

from certidoes import planejamento as pl
from certidoes.atesto import gerar_csv
from certidoes.models import (Certidao, Contrato, ItemChecklist, ResultadoValidacao, Semaforo,
                              Situacao, TipoCertidao as T)

HOJE = date(2026, 10, 27)
ATE = date(2026, 11, 10)
CNPJ = "11222333000181"
CNPJ2 = "12345678000195"

ANTIGAS = ["data_referencia", "competencia", "contrato", "cnpj", "razao_social", "fiscal",
           "item", "semaforo", "resultado", "situacao", "validade", "codigo_controle",
           "arquivo", "mensagem", "apto_atesto"]


def _csv_antigo(linhas):
    f = io.StringIO()
    w = csv.DictWriter(f, fieldnames=ANTIGAS, delimiter=";")
    w.writeheader()
    for ln in linhas:
        w.writerow({k: ln.get(k, "") for k in ANTIGAS})
    return f.getvalue().encode("utf-8-sig")


def _cert(tipo, validade, situacao=Situacao.NEGATIVA):
    return Certidao(arquivo=f"{tipo.value}.pdf", tipo=tipo, situacao=situacao, cnpj=CNPJ,
                    validade=validade)


def _resultado(itens, ref=HOJE, uf="SP", mun="São Paulo", numero="12/2026", cnpj=CNPJ):
    c = Contrato(numero=numero, cnpj=cnpj, razao_social="Empresa Teste Ltda", uf_sede=uf,
                 municipio_sede=mun, fiscal="Maria Fiscal", competencia="10/2026")
    return ResultadoValidacao(contrato=c, data_referencia=ref, itens=itens)


def _csv_novo(tmp_path, resultados, nome="c.csv"):
    caminho = gerar_csv(resultados, str(tmp_path / nome))
    with open(caminho, "rb") as f:
        return f.read()


def test_deduzir_tipo():
    assert pl.deduzir_tipo("Receita Federal / PGFN") == "federal"
    assert pl.deduzir_tipo("FGTS (CRF - Caixa)") == "fgts"
    assert pl.deduzir_tipo("Trabalhista (CNDT - TST)") == "trabalhista"
    assert pl.deduzir_tipo("Fazenda Estadual") == "estadual"
    assert pl.deduzir_tipo("fazenda municipal") == "municipal"
    assert pl.deduzir_tipo("SICAF") == "sicaf"
    assert pl.deduzir_tipo("Não identificada") is None
    assert pl.deduzir_tipo("") is None


def test_data_corte_padrao():
    assert pl.data_corte_padrao(HOJE) == date(2026, 11, 10)
    assert pl.data_corte_padrao(date(2026, 12, 3)) == date(2027, 1, 10)


def test_ler_csv_antigo_sem_colunas_novas():
    dados = _csv_antigo([
        {"data_referencia": "27/10/2026", "contrato": "1/2026", "cnpj": "11.222.333/0001-81",
         "razao_social": "Empresa", "item": "Receita Federal / PGFN", "semaforo": "verde",
         "validade": "20/12/2026"},
        {"data_referencia": "27/10/2026", "contrato": "1/2026", "cnpj": "11.222.333/0001-81",
         "item": "FGTS (CRF - Caixa)", "semaforo": "vermelho", "validade": ""},
        {"data_referencia": "27/10/2026", "contrato": "1/2026", "cnpj": "invalido",
         "item": "FGTS (CRF - Caixa)"},                      # CNPJ inválido: ignorada
        {"data_referencia": "27/10/2026", "contrato": "1/2026", "cnpj": CNPJ,
         "item": "Item estranho"},                           # tipo não identificável: ignorada
    ])
    linhas = pl.ler_csvs([dados])
    assert len(linhas) == 2
    fed = next(l for l in linhas if l["tipo"] == "federal")
    assert fed["cnpj"] == CNPJ and fed["validade"] == date(2026, 12, 20)
    assert fed["uf_sede"] == "" and fed["via_sicaf"] is False
    assert fed["data_referencia"] == HOJE


def test_ler_csv_novo_e_ignora_lixo(tmp_path):
    r = _resultado([ItemChecklist(T.FEDERAL, Semaforo.VERDE, "ok", _cert(T.FEDERAL, HOJE + timedelta(days=60)))])
    linhas = pl.ler_csvs([_csv_novo(tmp_path, [r]), b"", b"isto nao e csv\n1;2;3", b"\xff\xfe\x00lixo"])
    assert len(linhas) == 1
    ln = linhas[0]
    assert ln["tipo"] == "federal" and ln["uf_sede"] == "SP" and ln["municipio_sede"] == "São Paulo"
    assert ln["validade"] == HOJE + timedelta(days=60)


def test_deduplicacao_fica_a_mais_recente(tmp_path):
    antigo = _resultado([ItemChecklist(T.FGTS, Semaforo.VERDE, "ok", _cert(T.FGTS, date(2026, 10, 30)))],
                        ref=date(2026, 9, 27))
    novo = _resultado([ItemChecklist(T.FGTS, Semaforo.VERDE, "ok", _cert(T.FGTS, date(2026, 11, 25)))],
                      ref=date(2026, 10, 27))
    # ordem de envio invertida: o mais recente vem primeiro
    linhas = pl.ler_csvs([_csv_novo(tmp_path, [novo], "n.csv"), _csv_novo(tmp_path, [antigo], "a.csv")])
    assert len(linhas) == 1 and linhas[0]["validade"] == date(2026, 11, 25)
    # outro contrato da mesma empresa não é deduplicado
    outro = _resultado([ItemChecklist(T.FGTS, Semaforo.VERDE, "ok", _cert(T.FGTS, date(2026, 11, 25)))],
                       numero="99/2026")
    linhas = pl.ler_csvs([_csv_novo(tmp_path, [novo, outro], "o.csv")])
    assert len(linhas) == 2


def test_planejar_datas_de_corte(tmp_path):
    itens = [
        ItemChecklist(T.FEDERAL, Semaforo.VERDE, "ok", _cert(T.FEDERAL, ATE)),                    # = corte: ok
        ItemChecklist(T.FGTS, Semaforo.AMARELO, "vence", _cert(T.FGTS, ATE - timedelta(days=1))),  # < corte
        ItemChecklist(T.TRABALHISTA, Semaforo.VERMELHO, "vencida", _cert(T.TRABALHISTA, HOJE - timedelta(days=2))),
        ItemChecklist(T.ESTADUAL, Semaforo.VERMELHO, "não enviada"),                                # sem validade
        ItemChecklist(T.MUNICIPAL, Semaforo.VERMELHO, "positiva",
                      _cert(T.MUNICIPAL, ATE + timedelta(days=60), Situacao.POSITIVA)),
    ]
    grupos = pl.planejar(pl.ler_csvs([_csv_novo(tmp_path, [_resultado(itens)])]), ate=ATE, hoje=HOJE)
    assert len(grupos) == 1
    g = grupos[0]
    st = {i["tipo"]: i for i in g["itens"]}
    assert st["federal"]["status"] == "ok" and st["federal"]["acao"] == pl.ACAO_NENHUMA
    assert st["fgts"]["status"] == "emitir" and "antes da data de corte" in st["fgts"]["motivo"]
    assert st["trabalhista"]["status"] == "emitir" and "vencida" in st["trabalhista"]["motivo"]
    assert st["estadual"]["status"] == "emitir" and "sem validade" in st["estadual"]["motivo"]
    assert st["municipal"]["status"] == "emitir" and "PENDENTE" in st["municipal"]["motivo"]
    # portais anexados aos itens a emitir; SP tem dois portais estaduais
    assert st["federal"]["portais"] == []
    assert len(st["estadual"]["portais"]) >= 2
    # "captcha" do item acompanha a melhor rota (o catálogo real pode mudar de acesso)
    assert st["fgts"]["captcha"] is (st["fgts"]["acesso_rota"] == "captcha")
    assert st["fgts"]["portais"][0]["url"].startswith("https://")
    federais = pl._portais_do_tipo("federal", "SP", "São Paulo")   # só emissão, sem a de verificação
    assert len(federais) == 1 and not federais[0]["nome"].startswith("Confirmação")
    t = g["totais"]
    assert t == pl.totalizar(grupos)
    assert t["ok"] == 1 and t["a_emitir"] == 4 and t["via_sicaf"] == 0 and t["captchas_evitados"] == 1


def test_planejar_sicaf(tmp_path):
    sicaf = Certidao(arquivo="sicaf.pdf", tipo=T.SICAF, situacao=Situacao.REGULAR, cnpj=CNPJ,
                     validade=HOJE + timedelta(days=3))
    itens = [
        ItemChecklist(T.FEDERAL, Semaforo.VERDE, "via SICAF", sicaf),
        ItemChecklist(T.FGTS, Semaforo.VERDE, "via SICAF", sicaf),
        ItemChecklist(T.TRABALHISTA, Semaforo.VERDE, "ok", _cert(T.TRABALHISTA, ATE + timedelta(days=90))),
        ItemChecklist(T.MUNICIPAL, Semaforo.VERDE, "ok", _cert(T.MUNICIPAL, HOJE + timedelta(days=1))),
    ]
    linhas = pl.ler_csvs([_csv_novo(tmp_path, [_resultado(itens)])])
    assert sum(1 for l in linhas if l["via_sicaf"]) == 2
    g = pl.planejar(linhas, ate=ATE, hoje=HOJE)[0]
    st = {i["tipo"]: i for i in g["itens"]}
    assert g["usa_sicaf"] is True
    assert st["federal"]["acao"] == pl.ACAO_SICAF and st["federal"]["via_sicaf"]
    assert st["fgts"]["acao"] == pl.ACAO_SICAF
    assert "SICAF" in st["federal"]["portais"][0]["nome"]
    assert st["trabalhista"]["status"] == "ok" and st["trabalhista"]["via_sicaf"]
    assert st["municipal"]["acao"] == pl.ACAO_EMITIR and not st["municipal"]["via_sicaf"]
    t = g["totais"]
    assert t["via_sicaf"] == 2 and t["ok"] == 1 and t["a_emitir"] == 1 and t["captchas_evitados"] == 3
    assert [i["tipo"] for i in g["a_emitir"]] == ["municipal"]


def test_planejar_aceitar_sicaf_forcado_em_csv_antigo():
    dados = _csv_antigo([{"data_referencia": "27/10/2026", "contrato": "1", "cnpj": CNPJ,
                          "item": "Receita Federal / PGFN", "validade": "01/11/2026"}])
    g = pl.planejar(pl.ler_csvs([dados]), ate=ATE, hoje=HOJE, aceitar_sicaf=True)[0]
    assert g["itens"][0]["acao"] == pl.ACAO_SICAF


def test_agrupa_por_contratada_e_ordena(tmp_path):
    a = _resultado([ItemChecklist(T.FGTS, Semaforo.VERDE, "ok", _cert(T.FGTS, ATE))])
    b = _resultado([ItemChecklist(T.FGTS, Semaforo.VERDE, "ok", _cert(T.FGTS, HOJE))],
                   cnpj=CNPJ2, numero="2/2026", uf="RJ", mun="Rio de Janeiro")
    b.contrato.razao_social = "Alfa Serviços"
    grupos = pl.planejar(pl.ler_csvs([_csv_novo(tmp_path, [a, b])]), ate=ATE, hoje=HOJE)
    assert [g["razao_social"] for g in grupos] == ["Alfa Serviços", "Empresa Teste Ltda"]
    assert grupos[0]["cnpj_formatado"] == "12.345.678/0001-95"
    assert pl.totalizar(grupos)["contratadas"] == 2


def test_texto_solicitacao(tmp_path):
    itens = [ItemChecklist(T.FGTS, Semaforo.AMARELO, "vence", _cert(T.FGTS, ATE - timedelta(days=1))),
             ItemChecklist(T.FEDERAL, Semaforo.VERDE, "ok", _cert(T.FEDERAL, ATE + timedelta(days=30)))]
    g = pl.planejar(pl.ler_csvs([_csv_novo(tmp_path, [_resultado(itens)])]), ate=ATE, hoje=HOJE)[0]
    texto = pl.texto_solicitacao(g, prazo_dias=7, orgao="Órgão Exemplo")
    assert texto.startswith("MINUTA")
    assert "Contrato nº 12/2026" in texto and "11.222.333/0001-81" in texto
    assert "7 dias úteis" in texto and "10/11/2026" in texto
    assert "FGTS (CRF - Caixa)" in texto and "Receita Federal / PGFN" not in texto
    assert "art. 92, XVI" in texto and "14.133/2021" in texto
    assert "nota fiscal" in texto and "Órgão Exemplo" in texto and "Maria Fiscal" in texto
    baixo = texto.lower()
    assert "retenção" not in baixo and "reter" not in baixo and "pagamento" not in baixo
    assert "Contrato nº 12/2026" in pl.assunto_solicitacao(g)


def test_grupo_de_resultado_e_csv_plano(tmp_path):
    itens = [ItemChecklist(T.FGTS, Semaforo.AMARELO, "vence", _cert(T.FGTS, HOJE + timedelta(days=3))),
             ItemChecklist(T.TRABALHISTA, Semaforo.VERMELHO, "não enviada"),
             ItemChecklist(T.FEDERAL, Semaforo.VERDE, "ok", _cert(T.FEDERAL, ATE))]
    g = pl.grupo_de_resultado(_resultado(itens))
    assert [i["tipo"] for i in g["a_emitir"]] == ["fgts", "trabalhista"]
    texto = pl.texto_solicitacao(g)
    assert "5 dias úteis" in texto and "sem certidão válida registrada" in texto

    grupos = pl.planejar(pl.ler_csvs([_csv_novo(tmp_path, [_resultado(itens)])]), ate=ATE, hoje=HOJE)
    plano = list(csv.DictReader(io.StringIO(pl.csv_plano(grupos)), delimiter=";"))
    assert list(plano[0].keys()) == pl.CAMPOS_PLANO
    assert {l["tipo"] for l in plano} == {"federal", "fgts", "trabalhista"}
    fgts = next(l for l in plano if l["tipo"] == "fgts")
    assert fgts["status"] == "emitir" and fgts["url_portal"].startswith("https://")
    assert fgts["captcha"] == {"com captcha": "sim", "acesso a confirmar": "não informado"}.get(fgts["acesso"], "não")


def test_reconferir_amarelo_por_outro_motivo(tmp_path):
    v = ATE + timedelta(days=60)
    itens = [
        ItemChecklist(T.FEDERAL, Semaforo.AMARELO,
                      "Comprovada pelo SICAF, com ressalvas. Válida até 01/02/2027 (97 dias). "
                      "Certidão inserida manualmente pelo fornecedor no SICAF: conferir a certidão no site do emissor.",
                      _cert(T.FEDERAL, v)),
        ItemChecklist(T.FGTS, Semaforo.AMARELO, "Válida até ... CNPJ não encontrado no PDF: conferir.",
                      _cert(T.FGTS, v)),
        ItemChecklist(T.TRABALHISTA, Semaforo.AMARELO, "Dados extraídos por IA: conferir manualmente.",
                      _cert(T.TRABALHISTA, v)),
        ItemChecklist(T.ESTADUAL, Semaforo.AMARELO,
                      f"Válida até {v:%d/%m/%Y} (10 dias): vence em breve.", _cert(T.ESTADUAL, v)),
        ItemChecklist(T.MUNICIPAL, Semaforo.AMARELO, "Vence hoje (27/10/2026). Pedir certidão atualizada.",
                      _cert(T.MUNICIPAL, v)),
    ]
    g = pl.planejar(pl.ler_csvs([_csv_novo(tmp_path, [_resultado(itens)])]), ate=ATE, hoje=HOJE)[0]
    st = {i["tipo"]: i for i in g["itens"]}
    for tipo in ("federal", "fgts", "trabalhista"):
        assert st[tipo]["status"] == "reconferir" and st[tipo]["acao"] == pl.ACAO_RECONFERIR, tipo
        assert st[tipo]["situacao_plano"] == "reconferir" and "ATENÇÃO" in st[tipo]["motivo"]
        assert st[tipo]["portais"], tipo            # link do emissor para conferir
    assert st["estadual"]["status"] == "ok" and st["municipal"]["status"] == "ok"
    assert [i["tipo"] for i in g["reconferir"]] == ["federal", "fgts", "trabalhista"]
    t = g["totais"]
    assert t["a_reconferir"] == 3 and t["ok"] == 2 and t["a_emitir"] == 0 and t["captchas_evitados"] == 2
    # amarelo com validade antes do corte continua "emitir"
    assert pl.precisa_reconferir("amarelo", "") is True
    assert pl.precisa_reconferir("verde", "conferir") is False


def test_sanitizacao_formula_e_leitura_de_volta(tmp_path):
    r = _resultado([ItemChecklist(T.FGTS, Semaforo.VERDE, "ok",
                                  Certidao(arquivo="@x.pdf", tipo=T.FGTS, situacao=Situacao.REGULAR,
                                           cnpj=CNPJ, validade=ATE))], mun="-2+3")
    r.contrato.razao_social = "=1+1"
    bruto = _csv_novo(tmp_path, [r])
    txt = bruto.decode("utf-8-sig")
    assert "'=1+1" in txt and "'-2+3" in txt and "'@x.pdf" in txt
    ln = pl.ler_csvs([bruto])[0]
    assert ln["razao_social"] == "=1+1" and ln["municipio_sede"] == "-2+3"
    plano = pl.csv_plano(pl.planejar([ln], ate=ATE, hoje=HOJE))
    assert "'=1+1" in plano and "'-2+3" in plano
    celulas = [c for linha in plano.splitlines() for c in linha.split(";")]
    assert not any(c[:1] in ("=", "+", "-", "@", "\t", "\r") for c in celulas if c)


def test_texto_solicitacao_conforme_contrato(tmp_path):
    g = pl.grupo_de_resultado(_resultado([ItemChecklist(T.FGTS, Semaforo.VERMELHO, "não enviada")]))
    t = " ".join(pl.texto_solicitacao(g).split())
    assert "conforme previsto no contrato" in t and "art. 92, XVI" in t
    assert "nota fiscal apresentada" not in t


# ---------------------------------------------------------------- rotas sem captcha (esquema v2)

CATALOGO_V2 = [
    # catálogo em ordem "ruim": a rota com captcha vem antes da rota gov.br
    {"id": "rfb", "nome": "Receita (portal)", "tipo": "federal", "url": "https://rfb.exemplo.gov.br",
     "acesso": "captcha", "captcha": True, "prioridade": 2, "validade_tipica_dias": 180},
    {"id": "rfb_govbr", "nome": "Receita (e-CAC gov.br)", "tipo": "federal", "url": "https://gov.exemplo.gov.br",
     "acesso": "govbr", "captcha": False, "nivel_govbr": "prata", "prioridade": 1, "validade_tipica_dias": 180},
    {"id": "rfb_verificacao", "nome": "Verificação", "tipo": "federal", "url": "https://v.exemplo.gov.br",
     "acesso": "livre", "captcha": False},
    # item antigo, sem os campos novos
    {"id": "caixa", "nome": "Caixa CRF", "tipo": "fgts", "url": "https://caixa.exemplo.gov.br", "captcha": True,
     "validade_tipica_dias": 30},
    {"id": "tst", "nome": "TST CNDT", "tipo": "trabalhista", "url": "https://tst.exemplo.jus.br",
     "acesso": "captcha", "captcha": True, "prioridade": 1},
    # estadual com duas certidões complementares (sem certidão única)
    {"id": "sefaz", "nome": "SEFAZ", "tipo": "estadual", "url": "https://sefaz.exemplo.gov.br",
     "acesso": "govbr", "captcha": False, "certidao_unica": False, "prioridade": 1},
    {"id": "pge", "nome": "PGE", "tipo": "estadual", "url": "https://pge.exemplo.gov.br",
     "acesso": "captcha", "captcha": True, "certidao_unica": False, "prioridade": 2},
    {"id": "pref", "nome": "Prefeitura", "tipo": "municipal", "url": "https://pref.exemplo.gov.br",
     "acesso": "livre", "captcha": False},
    {"id": "sicaf", "nome": "SICAF", "tipo": "sicaf", "url": "https://sicaf.exemplo.gov.br",
     "acesso": "govbr", "captcha": False},
]
CATALOGO_V1 = [{k: v for k, v in p.items() if k in ("id", "nome", "tipo", "url", "captcha")}
               for p in CATALOGO_V2]
for _p in CATALOGO_V1:
    if _p["id"] in ("pref", "sefaz"):
        _p["captcha"] = None          # antigo, não confirmado


def _catalogo(monkeypatch, itens):
    from certidoes import portais
    monkeypatch.setattr(portais, "portais_para", lambda uf, mun, caminho=None: [dict(p) for p in itens])


def _linhas_vencidas(tipos=("federal", "fgts", "trabalhista", "estadual", "municipal")):
    return [{"cnpj": CNPJ, "contrato": "12/2026", "razao_social": "Empresa", "uf_sede": "SP",
             "municipio_sede": "São Paulo", "tipo": t, "validade": HOJE - timedelta(days=3),
             "semaforo": "vermelho", "data_referencia": HOJE} for t in tipos]


def test_acesso_do_portal_antigo_e_novo():
    assert pl.acesso_do_portal({"captcha": True}) == "captcha"
    assert pl.acesso_do_portal({"captcha": False}) == "livre"
    assert pl.acesso_do_portal({"captcha": None}) == "desconhecido"
    assert pl.acesso_do_portal({}) == "desconhecido"
    assert pl.acesso_do_portal({"acesso": "govbr", "captcha": False}) == "govbr"
    assert pl.acesso_do_portal({"acesso": "certificado"}) == "certificado"
    assert pl.acesso_do_portal({"acesso": "invalido", "captcha": True}) == "captcha"
    assert pl.rotulo_acesso({"captcha": True}) == "com captcha"
    assert pl.rotulo_acesso({"acesso": "govbr"}) == "login gov.br (sem captcha)"
    assert pl.rotulo_acesso({"acesso": "govbr", "nivel_govbr": "prata"}) == "login gov.br (sem captcha), nível prata"
    assert pl.rotulo_acesso({"acesso": "certificado"}) == "certificado digital"
    assert pl.rotulo_acesso({"acesso": "livre"}) == "sem captcha"
    assert pl.rotulo_acesso({}) == "acesso a confirmar"
    assert pl.CLASSE_ACESSO["captcha"] == "warning" and pl.CLASSE_ACESSO["govbr"] == "success"
    assert pl.CLASSE_ACESSO["certificado"] == "info" and pl.CLASSE_ACESSO["desconhecido"] == ""


def test_ordenacao_melhor_rota(monkeypatch):
    _catalogo(monkeypatch, CATALOGO_V2)
    fed = pl._portais_do_tipo("federal", "SP", "São Paulo")
    assert [p["nome"] for p in fed] == ["Receita (e-CAC gov.br)", "Receita (portal)"]   # sem a verificação
    assert fed[0]["acesso"] == "govbr" and fed[0]["nivel_govbr"] == "prata" and fed[0]["sem_captcha"]
    lista = pl.ordenar_portais([{"acesso": "captcha", "prioridade": 1}, {"captcha": None},
                                {"acesso": "certificado", "prioridade": 3}, {"acesso": "livre", "prioridade": 2}])
    assert [pl.acesso_do_portal(p) for p in lista] == ["livre", "certificado", "desconhecido", "captcha"]


def test_planejar_rotas_e_contagem_de_captchas(monkeypatch):
    _catalogo(monkeypatch, CATALOGO_V2)
    g = pl.planejar(_linhas_vencidas(), ate=ATE, hoje=HOJE)[0]
    it = {i["tipo"]: i for i in g["itens"]}
    assert it["federal"]["rota_sem_captcha"] is True and it["federal"]["portais"][0]["acesso"] == "govbr"
    assert it["federal"]["melhor_rota_txt"] == "Melhor rota: Receita (e-CAC gov.br) — login gov.br nível prata, sem captcha"
    assert it["federal"]["nota_validade"] == "nova certidão costuma valer 180 dias"
    assert it["fgts"]["rota_sem_captcha"] is False and it["fgts"]["captcha"] is True     # item antigo
    assert it["fgts"]["nota_validade"] == "nova certidão costuma valer 30 dias"
    assert it["trabalhista"]["nota_validade"] == ""
    # SEFAZ (gov.br) + PGE (captcha): as duas certidões são necessárias
    assert it["estadual"]["rota_sem_captcha"] is False and it["estadual"]["captchas_rota"] == 1
    assert it["municipal"]["rota_sem_captcha"] is True
    t = pl.totalizar([g])
    assert t["a_emitir"] == 5
    assert t["captchas_a_resolver"] == 3            # FGTS, TST, PGE
    assert t["sem_captcha_govbr"] == 2              # federal (gov.br) e municipal (livre)
    assert t["acesso_a_confirmar"] == 0
    assert t["captchas_evitados"] == 2              # 0 válidas + 0 SICAF + 2 sem captcha


def test_planejar_certidao_unica_e_alternativas(monkeypatch):
    cat = [dict(p, certidao_unica=True) if p["tipo"] == "estadual" else p for p in CATALOGO_V2]
    _catalogo(monkeypatch, cat)
    g = pl.planejar(_linhas_vencidas(("estadual",)), ate=ATE, hoje=HOJE)[0]
    assert g["itens"][0]["rota_sem_captcha"] is True and pl.totalizar([g])["captchas_a_resolver"] == 0


def test_planejar_catalogo_antigo(monkeypatch):
    _catalogo(monkeypatch, CATALOGO_V1)
    g = pl.planejar(_linhas_vencidas(), ate=ATE, hoje=HOJE)[0]
    t = pl.totalizar([g])
    # federal: captcha + "livre" (captcha False) -> rota sem captcha; municipal: desconhecido
    assert t["sem_captcha_govbr"] == 1 and t["acesso_a_confirmar"] == 1
    assert t["captchas_a_resolver"] == 3          # fgts, tst, pge (sefaz desconhecido não conta)
    for i in g["itens"]:
        for p in i["portais"]:
            assert p["acesso"] in pl.ACESSOS and p["rotulo_acesso"]


def test_planejar_sicaf_nao_conta_captcha(monkeypatch):
    _catalogo(monkeypatch, CATALOGO_V2)
    g = pl.planejar(_linhas_vencidas(("federal", "fgts")), ate=ATE, hoje=HOJE, aceitar_sicaf=True)[0]
    t = pl.totalizar([g])
    assert t["via_sicaf"] == 2 and t["captchas_a_resolver"] == 0 and t["captchas_evitados"] == 2


def test_csv_plano_tem_acesso(monkeypatch):
    _catalogo(monkeypatch, CATALOGO_V2)
    g = pl.planejar(_linhas_vencidas(("federal",)), ate=ATE, hoje=HOJE)
    linhas = pl.linhas_plano(g)
    assert "acesso" in pl.CAMPOS_PLANO
    assert linhas[0]["acesso"].startswith("login gov.br") and linhas[0]["captcha"] == "não"
    assert linhas[1]["acesso"] == "com captcha" and linhas[1]["captcha"] == "sim"


def test_sugestoes_de_rota_na_conferencia(monkeypatch):
    _catalogo(monkeypatch, CATALOGO_V2)
    itens = [ItemChecklist(tipo=T.FEDERAL, semaforo=Semaforo.VERMELHO, mensagem="não enviada"),
             ItemChecklist(tipo=T.FGTS, semaforo=Semaforo.VERDE, mensagem="ok",
                           certidao=_cert(T.FGTS, HOJE + timedelta(days=20)))]
    rotas = pl.sugestoes_de_rota(_resultado(itens))
    assert len(rotas) == 1 and rotas[0]["tipo"] == "federal"
    assert rotas[0]["texto"] == "Melhor rota: Receita (e-CAC gov.br) — login gov.br nível prata, sem captcha"
    assert rotas[0]["rota_sem_captcha"] and rotas[0]["url"] == "https://gov.exemplo.gov.br"
