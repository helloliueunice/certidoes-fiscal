import csv
from datetime import date, timedelta

import pdfplumber
import pytest

from certidoes.atesto import AVISO_RODAPE, CAMPOS_CSV, gerar_csv, gerar_pdf
from certidoes.models import (Certidao, Contrato, ItemChecklist, ResultadoValidacao, Semaforo,
                              Situacao, TipoCertidao as T)
from certidoes.validador import validar

HOJE = date(2026, 10, 27)
ANTIGAS = ["data_referencia", "competencia", "contrato", "cnpj", "razao_social", "fiscal",
           "item", "semaforo", "resultado", "situacao", "validade", "codigo_controle",
           "arquivo", "mensagem", "apto_atesto"]
CNPJ = "11222333000181"


def _contrato():
    return Contrato(numero="12/2026", cnpj=CNPJ, razao_social="Empresa Teste Ltda",
                    uf_sede="MG", municipio_sede="Belo Horizonte", fiscal="Maria Fiscal",
                    competencia="10/2026")


def _certs(positiva=False):
    def c(tipo, **kw):
        base = dict(arquivo=f"/tmp/x/{tipo.value}.pdf", tipo=tipo, situacao=Situacao.NEGATIVA,
                    cnpj=CNPJ, validade=HOJE + timedelta(days=90), confianca=0.95,
                    codigo_controle=f"COD-{tipo.value.upper()}",
                    url_verificacao=f"https://{tipo.value}.gov.br/verificar")
        base.update(kw)
        return Certidao(**base)
    return [
        c(T.FEDERAL, situacao=Situacao.POSITIVA if positiva else Situacao.NEGATIVA),
        c(T.FGTS, situacao=Situacao.REGULAR),
        c(T.TRABALHISTA),
        c(T.ESTADUAL, uf="MG"),
        c(T.MUNICIPAL, uf="MG", municipio="Belo Horizonte"),
        c(T.SICAF, situacao=Situacao.REGULAR),
    ]


def _texto(caminho):
    with pdfplumber.open(caminho) as pdf:
        return [p.extract_text() or "" for p in pdf.pages]


@pytest.mark.parametrize("positiva", [False, True])
def test_gerar_pdf(tmp_path, positiva):
    res = validar(_contrato(), _certs(positiva), hoje=HOJE)
    assert res.apto_atesto is (not positiva)
    saida = gerar_pdf(res, str(tmp_path / "sub" / "check.pdf"), orgao="Órgão de Teste",
                      observacoes="Linha 1\nLinha 2")
    assert (tmp_path / "sub" / "check.pdf").stat().st_size > 1000
    paginas = _texto(saida)
    tudo = "\n".join(paginas)
    flat = " ".join(tudo.split())
    assert "Checklist de Regularidade para Atesto" in tudo
    assert "11.222.333/0001-81" in tudo
    assert "Minuta" in tudo
    assert "autenticidade conferida" in tudo
    assert "COD-FEDERAL" in tudo and "https://federal.gov.br/verificar" in tudo
    assert "Órgão de Teste" in tudo and "Linha 2" in tudo
    for p in paginas:   # rodapé em todas as páginas
        assert " ".join(AVISO_RODAPE.split()) in " ".join(p.split())
        assert "Página" in p
    if positiva:
        assert "notificação" in flat.lower()
        assert "PENDENTE" in tudo
        assert "[prazo]" in tudo
        assert "retenção" not in flat.lower()
    else:
        assert "Minuta de atesto" in tudo
        assert "competência 10/2026" in flat
        assert "Há pendências" not in tudo and "OK" in tudo


def test_gerar_csv(tmp_path):
    r1 = validar(_contrato(), _certs(), hoje=HOJE)
    r2 = validar(_contrato(), _certs(True), hoje=HOJE)
    saida = gerar_csv([r1, r2], str(tmp_path / "controle.csv"))
    with open(saida, encoding="utf-8-sig") as f:
        linhas = list(csv.DictReader(f, delimiter=";"))
    assert len(linhas) == 10
    assert linhas[0]["cnpj"] == "11.222.333/0001-81"
    assert linhas[5]["resultado"] == "PENDENTE" and linhas[5]["apto_atesto"] == "não"
    assert linhas[0]["apto_atesto"] == "sim"
    # colunas novas ao final, antigas na mesma ordem
    assert CAMPOS_CSV[:15] == ANTIGAS
    assert CAMPOS_CSV[15:] == ["uf_sede", "municipio_sede", "tipo", "validade_iso", "via_sicaf"]
    with open(saida, encoding="utf-8-sig") as f:
        assert f.readline().strip().split(";") == CAMPOS_CSV
    assert linhas[0]["tipo"] == "federal" and linhas[1]["tipo"] == "fgts"
    assert linhas[0]["uf_sede"] == "MG" and linhas[0]["municipio_sede"] == "Belo Horizonte"
    assert linhas[0]["validade_iso"] == (HOJE + timedelta(days=90)).isoformat()
    assert linhas[0]["validade"] == (HOJE + timedelta(days=90)).strftime("%d/%m/%Y")
    assert all(l["via_sicaf"] == "não" for l in linhas)


def test_csv_via_sicaf_e_item_sem_certidao(tmp_path):
    sicaf = Certidao(arquivo="/x/sicaf.pdf", tipo=T.SICAF, situacao=Situacao.REGULAR, cnpj=CNPJ,
                     validade=HOJE + timedelta(days=20))
    res = ResultadoValidacao(contrato=_contrato(), data_referencia=HOJE, itens=[
        ItemChecklist(T.FEDERAL, Semaforo.VERDE, "Comprovada pela declaração do SICAF.", sicaf),
        ItemChecklist(T.MUNICIPAL, Semaforo.VERMELHO, "Certidão não enviada."),
    ])
    saida = gerar_csv([res], str(tmp_path / "c.csv"))
    with open(saida, encoding="utf-8-sig") as f:
        linhas = list(csv.DictReader(f, delimiter=";"))
    assert linhas[0]["via_sicaf"] == "sim" and linhas[0]["tipo"] == "federal"
    assert linhas[1]["via_sicaf"] == "não" and linhas[1]["validade_iso"] == ""
    assert linhas[1]["tipo"] == "municipal"


def test_minuta_texto_revisado_e_caixa_atencao(tmp_path):
    certs = _certs()
    certs[1].validade = HOJE + timedelta(days=5)   # FGTS em ATENÇÃO
    res = validar(_contrato(), certs, hoje=HOJE)
    assert res.apto_atesto
    flat = " ".join("\n".join(_texto(gerar_pdf(res, str(tmp_path / "a.pdf")))).split())
    assert ("não foram identificadas pendências de regularidade fiscal, social e trabalhista "
            "nas certidões apresentadas e conferidas") in flat
    assert "mantém as condições de habilitação" not in flat
    assert "[ ] Conferi manualmente os itens em ATENÇÃO" in flat
    assert "foram conferidos manualmente" not in flat


def test_pdf_destaca_extra_positiva(tmp_path):
    certs = _certs() + [Certidao(arquivo="ceis.pdf", tipo=T.OUTRA, situacao=Situacao.POSITIVA,
                                 cnpj=CNPJ, validade=HOJE + timedelta(days=30), confianca=0.9)]
    res = validar(_contrato(), certs, hoje=HOJE)
    flat = " ".join("\n".join(_texto(gerar_pdf(res, str(tmp_path / "b.pdf")))).split())
    assert "Atenção: certidão POSITIVA enviada, embora não exigida — avaliar" in flat


def test_csv_sem_injecao_de_formula(tmp_path):
    from certidoes.atesto import celula_segura
    contrato = _contrato()
    contrato.razao_social = "=1+1"
    contrato.municipio_sede = "-2+3"
    certs = _certs()
    certs[1].arquivo = "/tmp/x/@x.pdf"
    certs[2].codigo_controle = "+SOMA(A1)"
    saida = gerar_csv([validar(contrato, certs, hoje=HOJE)], str(tmp_path / "f.csv"))
    with open(saida, encoding="utf-8-sig") as f:
        linhas = list(csv.DictReader(f, delimiter=";"))
    assert linhas[0]["razao_social"] == "'=1+1" and linhas[0]["municipio_sede"] == "'-2+3"
    assert linhas[1]["arquivo"] == "'@x.pdf" and linhas[2]["codigo_controle"] == "'+SOMA(A1)"
    for ln in linhas:
        assert not any(v[:1] in ("=", "+", "-", "@", "\t", "\r") for v in ln.values() if v)
    assert celula_segura("\tx") == "'\tx" and celula_segura("\rx") == "'\rx"
    assert celula_segura("12.345") == "12.345" and celula_segura(None) == ""


def test_csv_validade_do_item_via_sicaf(tmp_path):
    from certidoes.atesto import validade_item
    sicaf = Certidao(arquivo="/x/sicaf.pdf", tipo=T.SICAF, situacao=Situacao.REGULAR, cnpj=CNPJ,
                     validade=HOJE + timedelta(days=5),          # validade da declaração
                     cobertura_sicaf={
                         "_situacao": {"situacao": "Credenciado", "credenciado": True},
                         "federal": {"validade": date(2027, 2, 24), "automatica": True, "pendencia": False},
                         "fgts": {"validade": None, "automatica": True, "pendencia": False},
                     })
    itens = [ItemChecklist(T.FEDERAL, Semaforo.VERDE, "via SICAF", sicaf),
             ItemChecklist(T.FGTS, Semaforo.AMARELO, "via SICAF", sicaf),
             ItemChecklist(T.TRABALHISTA, Semaforo.AMARELO, "via SICAF", sicaf),   # sem cobertura
             ItemChecklist(T.SICAF, Semaforo.VERDE, "declaração", sicaf)]
    res = ResultadoValidacao(contrato=_contrato(), data_referencia=HOJE, itens=itens)
    saida = gerar_csv([res], str(tmp_path / "s.csv"))
    with open(saida, encoding="utf-8-sig") as f:
        linhas = list(csv.DictReader(f, delimiter=";"))
    assert linhas[0]["validade"] == "24/02/2027" and linhas[0]["validade_iso"] == "2027-02-24"
    assert linhas[1]["validade"] == "" and linhas[1]["validade_iso"] == ""
    assert linhas[2]["validade_iso"] == ""
    assert linhas[3]["validade_iso"] == (HOJE + timedelta(days=5)).isoformat()
    assert all(l["via_sicaf"] == "sim" for l in linhas)
    assert validade_item(ItemChecklist(T.FGTS, Semaforo.VERMELHO, "não enviada")) is None
    texto = " ".join("\n".join(_texto(gerar_pdf(res, str(tmp_path / "s.pdf")))).split())
    assert "24/02/2027" in texto
