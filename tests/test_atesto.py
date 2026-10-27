import csv
from datetime import date, timedelta

import pdfplumber
import pytest

from certidoes.atesto import AVISO_RODAPE, gerar_csv, gerar_pdf
from certidoes.models import Certidao, Contrato, Situacao, TipoCertidao as T
from certidoes.validador import validar

HOJE = date(2026, 10, 27)
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
