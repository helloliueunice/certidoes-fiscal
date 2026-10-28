"""Gera PDFs SINTÉTICOS de certidões para testes (tests/amostras/).

Todos os documentos são FICTÍCIOS, marcados "DOCUMENTO DE TESTE - SEM VALIDADE" no cabeçalho e
no rodapé, com empresa e CNPJs inventados. As datas são relativas a date.today() para que os
testes não envelheçam.

Uso:  python tests/gerar_amostras.py [pasta_destino]
Também grava esperado.json (resultado esperado por arquivo) e LEIA-ME.txt.
"""
from __future__ import annotations

import io
import json
import sys
import textwrap
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Optional

from reportlab.lib.pagesizes import A4
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

MARCA = "DOCUMENTO DE TESTE - SEM VALIDADE"
PASTA_PADRAO = Path(__file__).resolve().parent / "amostras"
EMPRESA = "EMPRESA EXEMPLO DE SERVIÇOS LTDA"
OUTRA_EMPRESA = "OUTRA EMPRESA FICTÍCIA COMÉRCIO LTDA"

_MESES = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto",
          "setembro", "outubro", "novembro", "dezembro"]


# --------------------------------------------------------------------------------------
# CNPJs fictícios com DV calculado
# --------------------------------------------------------------------------------------

def _dv(base: str) -> str:
    def um(b: str, pesos: list[int]) -> str:
        r = sum(int(n) * p for n, p in zip(b, pesos)) % 11
        return "0" if r < 2 else str(11 - r)
    p1 = [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
    d1 = um(base, p1)
    return d1 + um(base + d1, [6] + p1)


def gerar_cnpj(raiz8: str, ordem4: str = "0001") -> str:
    base = raiz8 + ordem4
    return base + _dv(base)


def fmt_cnpj(d: str) -> str:
    return f"{d[:2]}.{d[2:5]}.{d[5:8]}/{d[8:12]}-{d[12:]}"


CNPJ_EMPRESA = gerar_cnpj("12345678")      # 12.345.678/0001-95
CNPJ_OUTRA = gerar_cnpj("98765432")


def br(d: date) -> str:
    return d.strftime("%d/%m/%Y")


def extenso(d: date) -> str:
    return f"{d.day} de {_MESES[d.month - 1]} de {d.year}"


# --------------------------------------------------------------------------------------
# Desenho dos PDFs
# --------------------------------------------------------------------------------------

def _cabecalho_rodape(cv: canvas.Canvas) -> None:
    w, h = A4
    cv.setFont("Helvetica-Bold", 11)
    cv.setFillColorRGB(0.8, 0, 0)
    cv.drawCentredString(w / 2, h - 30, MARCA)
    cv.drawCentredString(w / 2, 22, MARCA)
    cv.setFillColorRGB(0, 0, 0)


def _pagina(cv: canvas.Canvas, linhas: list[str]) -> None:
    _cabecalho_rodape(cv)
    w, h = A4
    y = h - 70
    for ln in linhas:
        if ln.startswith("# "):
            cv.setFont("Helvetica-Bold", 11)
            partes = textwrap.wrap(ln[2:], 80) or [""]
        else:
            cv.setFont("Helvetica", 9.5)
            partes = textwrap.wrap(ln, 100) or [""]
        for p in partes:
            cv.drawString(50, y, p)
            y -= 14
        if y < 60:
            cv.showPage()
            _cabecalho_rodape(cv)
            y = h - 70


def _pdf_texto(caminho: Path, paginas: list[list[str]]) -> None:
    cv = canvas.Canvas(str(caminho), pagesize=A4)
    cv.setTitle(MARCA)
    for i, linhas in enumerate(paginas):
        if i:
            cv.showPage()
        _pagina(cv, linhas)
    cv.save()


def _pdf_escaneado(caminho: Path) -> None:
    """PDF só com imagem (sem camada de texto), simulando digitalização."""
    from PIL import Image, ImageDraw

    img = Image.new("RGB", (1240, 1754), "white")
    dr = ImageDraw.Draw(img)
    dr.text((420, 40), MARCA, fill="red")
    dr.text((420, 1700), MARCA, fill="red")
    dr.rectangle((100, 150, 1140, 260), outline="black", width=3)
    dr.text((140, 190), "CERTIDAO NEGATIVA DE DEBITOS (imagem digitalizada)", fill="black")
    for i in range(20):
        dr.line((120, 320 + i * 40, 1100 - (i % 4) * 90, 320 + i * 40), fill=(90, 90, 90), width=6)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    cv = canvas.Canvas(str(caminho), pagesize=A4)
    w, h = A4
    cv.drawImage(ImageReader(buf), 0, 0, width=w, height=h)
    cv.save()


# --------------------------------------------------------------------------------------
# Modelos (redação típica dos emissores, com dados fictícios)
# --------------------------------------------------------------------------------------

def _federal(titulo: str, emissao: date, validade: date, cnpj: str, nome: str, corpo: str,
             codigo: str = "1A2B.3C4D.5E6F.7A8B") -> list[str]:
    return [
        "MINISTÉRIO DA FAZENDA",
        "Secretaria da Receita Federal do Brasil",
        "Procuradoria-Geral da Fazenda Nacional",
        f"# {titulo}",
        f"Nome: {nome}",
        f"CNPJ: {fmt_cnpj(cnpj)}",
        corpo,
        "A aceitação desta certidão está condicionada à verificação de sua autenticidade na "
        "Internet, nos endereços <http://rfb.gov.br> ou <http://www.pgfn.gov.br>.",
        "Certidão emitida gratuitamente com base na Portaria Conjunta RFB/PGFN nº 1.751, de 2/10/2014.",
        f"Emitida às 10:15:30 do dia {br(emissao)} <hora e data de Brasília>.",
        f"Válida até {br(validade)}.",
        f"Código de controle da certidão: {codigo}",
        "Qualquer rasura ou emenda invalidará este documento.",
    ]


_CORPO_FED_NEG = ("Ressalvado o direito de a Fazenda Nacional cobrar e inscrever quaisquer dívidas de "
                  "responsabilidade do sujeito passivo acima identificado que vierem a ser apuradas, é "
                  "certificado que não constam pendências em seu nome, relativas a créditos tributários "
                  "administrados pela Secretaria da Receita Federal do Brasil (RFB) e a inscrições em "
                  "Dívida Ativa da União (DAU) junto à Procuradoria-Geral da Fazenda Nacional (PGFN).")
_CORPO_FED_PEN = ("Ressalvado o direito de a Fazenda Nacional cobrar e inscrever quaisquer dívidas, é "
                  "certificado que constam débitos com exigibilidade suspensa nos termos do art. 151 da "
                  "Lei nº 5.172, de 25 de outubro de 1966 - CTN, ou objeto de decisão judicial que "
                  "determina sua desconsideração para fins de certificação da regularidade fiscal.")


def _cndt(titulo: str, emissao: date, validade: date, cnpj: str, corpo: str,
          numero: str = "12345678/2026") -> list[str]:
    return [
        "PODER JUDICIÁRIO",
        "JUSTIÇA DO TRABALHO",
        f"# {titulo}",
        f"Nome: {EMPRESA}",
        f"CNPJ: {fmt_cnpj(cnpj)}",
        f"Certidão nº: {numero}",
        f"Expedição: {br(emissao)}, às 10:20:30",
        f"Validade: {br(validade)} - 180 (cento e oitenta) dias, contados da data de sua expedição.",
        corpo,
        "Os dados constantes desta Certidão são de responsabilidade dos Tribunais do Trabalho. "
        "Conforme Lei nº 12.440/2011 e Resolução Administrativa nº 1470/2011 do TST.",
        "A autenticidade desta certidão pode ser verificada no portal do Tribunal Superior do Trabalho.",
    ]


@dataclass
class Amostra:
    nome: str
    tipo: str
    situacao: str
    cnpj: Optional[str]
    validade: Optional[date]
    paginas: list[list[str]] = field(default_factory=list)
    escaneado: bool = False
    data_emissao: Optional[date] = None
    uf: Optional[str] = None
    municipio: Optional[str] = None
    codigo_controle: Optional[str] = None
    avisos_contem: list[str] = field(default_factory=list)
    descricao: str = ""
    # Só SICAF: tipo -> (validade, automatica, pendencia)
    cobertura: Optional[dict[str, tuple[Optional[date], bool, bool]]] = None
    # Só SICAF: cobertura_sicaf["_situacao"] esperado
    sicaf_situacao: Optional[dict] = None


def amostras(hoje: Optional[date] = None) -> list[Amostra]:
    h = hoje or date.today()
    em = h - timedelta(days=10)
    val180 = em + timedelta(days=180)  # = hoje + 170
    lista: list[Amostra] = []

    lista.append(Amostra(
        "federal_negativa", "federal", "negativa", CNPJ_EMPRESA, val180, data_emissao=em,
        codigo_controle="1A2B.3C4D.5E6F.7A8B", descricao="CND federal negativa",
        paginas=[_federal("CERTIDÃO NEGATIVA DE DÉBITOS RELATIVOS AOS TRIBUTOS FEDERAIS E À DÍVIDA "
                          "ATIVA DA UNIÃO", em, val180, CNPJ_EMPRESA, EMPRESA, _CORPO_FED_NEG)]))

    lista.append(Amostra(
        "federal_positiva_efeito_negativa", "federal", "positiva_efeito_negativa", CNPJ_EMPRESA,
        val180, data_emissao=em, codigo_controle="9F8E.7D6C.5B4A.3210",
        descricao="CPEN federal",
        paginas=[_federal("CERTIDÃO POSITIVA COM EFEITOS DE NEGATIVA DE DÉBITOS RELATIVOS AOS TRIBUTOS "
                          "FEDERAIS E À DÍVIDA ATIVA DA UNIÃO", em, val180, CNPJ_EMPRESA, EMPRESA,
                          _CORPO_FED_PEN, codigo="9F8E.7D6C.5B4A.3210")]))

    em_v = h - timedelta(days=200)
    val_v = em_v + timedelta(days=180)  # vencida há 20 dias
    lista.append(Amostra(
        "federal_vencida", "federal", "negativa", CNPJ_EMPRESA, val_v, data_emissao=em_v,
        descricao="CND federal vencida",
        paginas=[_federal("CERTIDÃO NEGATIVA DE DÉBITOS RELATIVOS AOS TRIBUTOS FEDERAIS E À DÍVIDA "
                          "ATIVA DA UNIÃO", em_v, val_v, CNPJ_EMPRESA, EMPRESA, _CORPO_FED_NEG,
                          codigo="0A0B.0C0D.0E0F.1111")]))

    ini_f, fim_f = h - timedelta(days=10), h + timedelta(days=20)
    cert_f = ini_f.strftime("%Y%m%d") + "01234567890123"
    lista.append(Amostra(
        "fgts_regular", "fgts", "regular", CNPJ_EMPRESA, fim_f, data_emissao=ini_f,
        codigo_controle=cert_f, descricao="CRF FGTS regular",
        paginas=[[
            "CAIXA ECONÔMICA FEDERAL",
            "# Certificado de Regularidade do FGTS - CRF",
            f"Inscrição: {fmt_cnpj(CNPJ_EMPRESA)}",
            f"Razão Social: {EMPRESA}",
            "Endereço: RUA FICTÍCIA DE TESTE, 100 / CENTRO / SÃO PAULO / SP / 01000-000",
            "A Caixa Econômica Federal, no uso da atribuição que lhe confere o Art. 7, da Lei 8.036, "
            "de 11 de maio de 1990, certifica que, nesta data, a empresa abaixo identificada está "
            "regular perante o Fundo de Garantia do Tempo de Serviço - FGTS.",
            "O presente Certificado não servirá de prova contra cobrança de quaisquer débitos "
            "referentes a contribuições e/ou encargos devidos, decorrentes das obrigações com o FGTS.",
            f"Validade: {br(ini_f)} a {br(fim_f)}",
            f"Certificação Número: {cert_f}",
            f"Informação obtida em {br(ini_f)} 09:12:44",
            "A utilização deste Certificado para os fins previstos em Lei está condicionada à "
            "verificação de autenticidade no site da Caixa: www.caixa.gov.br",
        ]]))

    lista.append(Amostra(
        "cndt_negativa", "trabalhista", "negativa", CNPJ_EMPRESA, val180, data_emissao=em,
        codigo_controle="12345678/2026", descricao="CNDT negativa",
        paginas=[_cndt("CERTIDÃO NEGATIVA DE DÉBITOS TRABALHISTAS", em, val180, CNPJ_EMPRESA,
                       "Certifica-se que " + EMPRESA + ", inscrito(a) no CNPJ sob o nº "
                       + fmt_cnpj(CNPJ_EMPRESA) + ", NÃO CONSTA como inadimplente no Banco Nacional "
                       "de Devedores Trabalhistas.")]))

    lista.append(Amostra(
        "cndt_positiva", "trabalhista", "positiva", CNPJ_EMPRESA, val180, data_emissao=em,
        codigo_controle="87654321/2026", descricao="CNDT positiva (recusada)",
        paginas=[_cndt("CERTIDÃO POSITIVA DE DÉBITOS TRABALHISTAS", em, val180, CNPJ_EMPRESA,
                       "Certifica-se que " + EMPRESA + " CONSTA do Banco Nacional de Devedores "
                       "Trabalhistas em face do inadimplemento de obrigações estabelecidas no(s) "
                       "processo(s) abaixo.", numero="87654321/2026")]))

    em_b = h - timedelta(days=175)
    val_b = em_b + timedelta(days=180)  # vence em 5 dias
    lista.append(Amostra(
        "cndt_vence_em_breve", "trabalhista", "negativa", CNPJ_EMPRESA, val_b, data_emissao=em_b,
        descricao="CNDT negativa vencendo em 5 dias",
        paginas=[_cndt("CERTIDÃO NEGATIVA DE DÉBITOS TRABALHISTAS", em_b, val_b, CNPJ_EMPRESA,
                       "Certifica-se que a empresa NÃO CONSTA como inadimplente no Banco Nacional "
                       "de Devedores Trabalhistas.", numero="11112222/2026")]))

    lista.append(Amostra(
        "estadual_sp_pge", "estadual", "negativa", CNPJ_EMPRESA, val180, data_emissao=em, uf="SP",
        descricao="PGE-SP débitos inscritos em dívida ativa",
        paginas=[[
            "PROCURADORIA GERAL DO ESTADO DE SÃO PAULO",
            "# Certidão Negativa de Débitos Tributários da Dívida Ativa do Estado de São Paulo",
            f"CNPJ: {fmt_cnpj(CNPJ_EMPRESA)}",
            f"Nome: {EMPRESA}",
            "Ressalvado o direito de a Fazenda do Estado de São Paulo cobrar quaisquer débitos que "
            "vierem a ser apurados, certifica-se que não constam débitos inscritos em Dívida Ativa de "
            "responsabilidade do interessado acima identificado.",
            f"Data e hora da emissão: {br(em)} 11:02:13",
            f"Validade: {br(val180)}",
            "Certidão nº 55443322",
            "A autenticidade desta certidão deverá ser confirmada no site www.dividaativa.pge.sp.gov.br",
        ]]))

    val_s = em + timedelta(days=60)
    lista.append(Amostra(
        "estadual_sp_sefaz", "estadual", "negativa", CNPJ_EMPRESA, val_s, data_emissao=em, uf="SP",
        descricao="SEFAZ-SP débitos não inscritos",
        paginas=[[
            "GOVERNO DO ESTADO DE SÃO PAULO",
            "SECRETARIA DA FAZENDA E PLANEJAMENTO",
            "# Certidão de Débitos Tributários Não Inscritos na Dívida Ativa do Estado de São Paulo",
            f"CNPJ: {fmt_cnpj(CNPJ_EMPRESA)}",
            "Inscrição Estadual: 123.456.789.110",
            f"Razão Social: {EMPRESA}",
            "Ressalvado o direito de a Fazenda Pública do Estado de São Paulo apurar débitos de "
            "responsabilidade do contribuinte acima identificado: Não constam débitos declarados ou "
            "apurados pendentes de inscrição na Dívida Ativa.",
            f"Data de emissão: {br(em)}",
            f"Validade da certidão: {br(val_s)}",
            "Código de autenticidade: 2026AB12CD34",
            "Certidão emitida nos termos da Resolução Conjunta SF/PGE.",
        ]]))

    val_rj = em + timedelta(days=90)
    lista.append(Amostra(
        "estadual_rj", "estadual", "negativa", CNPJ_EMPRESA, val_rj, data_emissao=em, uf="RJ",
        descricao="Estadual genérica (RJ), datas por extenso",
        paginas=[[
            "ESTADO DO RIO DE JANEIRO",
            "SECRETARIA DE ESTADO DE FAZENDA",
            "# CERTIDÃO DE REGULARIDADE FISCAL",
            f"Contribuinte: {EMPRESA}",
            f"CNPJ/MF: {fmt_cnpj(CNPJ_EMPRESA)}",
            "Certificamos que, até a presente data, não constam débitos relativos a tributos "
            "estaduais em nome do contribuinte acima identificado.",
            f"Rio de Janeiro, {extenso(em - timedelta(days=3))}.",
            f"Emitida em {extenso(em)}.",
            f"Válida até {extenso(val_rj)}.",
            "Código de autenticidade: RJ-7788-9900",
        ]]))

    # Certidão Única estadual de SP (SIDEB: Sefaz + PGE). Redação SINTÉTICA, montada com as
    # expressões divulgadas (inscritos e não inscritos, raiz do CNPJ, 90/180 dias); o modelo
    # oficial ainda não foi confirmado.
    val_u = em + timedelta(days=90)
    lista.append(Amostra(
        "estadual_sp_unica", "estadual", "negativa", CNPJ_EMPRESA, val_u, data_emissao=em, uf="SP",
        codigo_controle="SIDEB2026A1B2C3",
        descricao="SP Certidão Única (SIDEB, Sefaz + PGE), validade 90 dias da emissão",
        paginas=[[
            "GOVERNO DO ESTADO DE SÃO PAULO",
            "SECRETARIA DA FAZENDA E PLANEJAMENTO - PROCURADORIA GERAL DO ESTADO",
            "SIDEB",
            "# CERTIDÃO NEGATIVA DE DÉBITOS TRIBUTÁRIOS - CERTIDÃO ÚNICA",
            f"CNPJ: {fmt_cnpj(CNPJ_EMPRESA)}",
            f"Nome: {EMPRESA}",
            "Certidão emitida conjuntamente pela Secretaria da Fazenda e Planejamento e pela "
            "Procuradoria Geral do Estado, abrangendo os débitos tributários inscritos e não "
            "inscritos em dívida ativa.",
            "Ressalvado o direito de a Fazenda do Estado de São Paulo cobrar quaisquer débitos que "
            "vierem a ser apurados, certifica-se que não constam débitos de responsabilidade do "
            "interessado acima identificado.",
            "A certidão abrange todos os estabelecimentos da empresa (raiz do CNPJ).",
            f"Data de emissão: {br(em)} 09:30:12",
            "Esta certidão é válida por 90 (noventa) dias, contados da data de sua emissão "
            "(180 dias para contribuintes do Cadastro Fiscal Positivo).",
            "Código de autenticidade: SIDEB2026A1B2C3",
            "A autenticidade desta certidão deverá ser confirmada em "
            "https://www4.fazenda.sp.gov.br/SIDEB/CertidaoNegativaDebitos",
        ]]))

    lista.append(Amostra(
        "municipal_sp", "municipal", "negativa", CNPJ_EMPRESA, val180, data_emissao=em,
        uf="SP", municipio="São Paulo", descricao="Prefeitura de SP, validade por prazo",
        paginas=[[
            "PREFEITURA DO MUNICÍPIO DE SÃO PAULO - CNPJ 46.395.000/0001-39",
            "SECRETARIA MUNICIPAL DA FAZENDA",
            "# Certidão Conjunta de Débitos de Tributos Mobiliários",
            f"Contribuinte: {EMPRESA}",
            f"CNPJ: {fmt_cnpj(CNPJ_EMPRESA)}",
            "CCM: 1.234.567-8",
            "Ressalvado o direito de a Fazenda Municipal cobrar débitos que vierem a ser apurados, "
            "certifica-se que não constam débitos de tributos mobiliários para o contribuinte acima.",
            f"Data de emissão: {br(em)}",
            "Esta certidão é válida por 180 dias a partir da data de emissão.",
            "Código de autenticidade: SP0011223344",
        ]]))

    # Declaração SICAF: nível III (federal, FGTS, trabalhista) e nível IV (estadual, municipal).
    v_fed, v_fgts, v_trab = h + timedelta(days=120), h + timedelta(days=40), h + timedelta(days=150)
    v_est, v_mun = h + timedelta(days=90), h + timedelta(days=60)
    emis_sicaf = h - timedelta(days=1)
    lista.append(Amostra(
        "sicaf", "sicaf", "regular", CNPJ_EMPRESA, v_fgts, data_emissao=emis_sicaf,
        descricao="Declaração SICAF sem pendência (5 itens, estadual inserida manualmente)",
        sicaf_situacao={"credenciado": True, "situacao": "Credenciado", "impedimento": None},
        cobertura={
            "federal": (v_fed, True, False), "fgts": (v_fgts, True, False),
            "trabalhista": (v_trab, True, False), "estadual": (v_est, False, False),
            "municipal": (v_mun, False, False),
        },
        paginas=[[
            "Ministério da Gestão e da Inovação em Serviços Públicos",
            "# Sistema de Cadastramento Unificado de Fornecedores - SICAF",
            "Declaração",
            "Declaramos para os fins previstos na Lei nº 14.133, de 2021, conforme documentação "
            "registrada no SICAF, que a situação do fornecedor no momento é a seguinte:",
            f"CNPJ: {fmt_cnpj(CNPJ_EMPRESA)}",
            f"Razão Social: {EMPRESA}",
            "Situação do Fornecedor: Credenciado",
            "Ocorrências e Impedimentos: Nada consta",
            "I - Credenciamento",
            "II - Habilitação Jurídica",
            "III - Regularidade Fiscal e Trabalhista Federal",
            "Receita Federal e PGFN Validade:",
            f"{br(v_fed)} Automática",
            f"FGTS Validade: {br(v_fgts)} Automática",
            f"Trabalhista Validade: {br(v_trab)} Automática(http://www.tst.jus.br/certidao)",
            "IV - Regularidade Fiscal Estadual/Distrital e Municipal",
            f"Receita Estadual/Distrital Validade: {br(v_est)} Manual",
            f"Receita Municipal Validade: {br(v_mun)} (*)",
            "(*) Certidão inserida pelo fornecedor.",
            f"Emitido em: {br(emis_sicaf)} 10:15",
        ]]))

    vp_fed, vp_fgts, vp_trab = h + timedelta(days=100), h + timedelta(days=25), h + timedelta(days=130)
    vp_est, vp_mun = h + timedelta(days=30), h - timedelta(days=5)
    lista.append(Amostra(
        "sicaf_pendencia", "sicaf", "indeterminada", CNPJ_EMPRESA, vp_mun, data_emissao=emis_sicaf,
        avisos_contem=["pendência"],
        descricao="Declaração SICAF com pendência no nível IV (municipal vencida), datas soltas",
        sicaf_situacao={"credenciado": True, "situacao": "Credenciado", "impedimento": None},
        cobertura={
            "federal": (vp_fed, True, False), "fgts": (vp_fgts, True, False),
            "trabalhista": (vp_trab, True, False), "estadual": (vp_est, True, True),
            "municipal": (vp_mun, True, True),
        },
        paginas=[[
            "Ministério da Gestão e da Inovação em Serviços Públicos",
            "# Sistema de Cadastramento Unificado de Fornecedores - SICAF",
            "Declaração",
            f"CNPJ: {fmt_cnpj(CNPJ_EMPRESA)}",
            f"Razão Social: {EMPRESA}",
            "Situação do Fornecedor: Credenciado",
            "III - Regularidade Fiscal e Trabalhista Federal",
            f"Receita Federal e PGFN {br(vp_fed)} Automática",
            "Validade:",
            f"FGTS {br(vp_fgts)} Automática",
            "Validade:",
            f"Trabalhista {br(vp_trab)} Automática(http://www.tst.jus.br/certidao)",
            "Validade:",
            "IV - Regularidade Fiscal Estadual/Distrital e Municipal: (Possui Pendência)",
            f"Receita Estadual/Distrital {br(vp_est)} Automática",
            "Validade:",
            f"Receita Municipal {br(vp_mun)} Automática",
            "Validade:",
            f"Emitido em: {br(emis_sicaf)} 10:15",
        ]]))

    vd_fed, vd_fgts, vd_trab = h + timedelta(days=90), h + timedelta(days=50), h + timedelta(days=120)
    imped = "Impedimento de Licitar: Consta - Suspensão temporária (art. 156, III, Lei 14.133/2021)"
    lista.append(Amostra(
        "sicaf_descredenciado", "sicaf", "indeterminada", CNPJ_EMPRESA, vd_fgts, data_emissao=h,
        avisos_contem=["Descredenciado", "Impedimento de Licitar", "pendência"],
        descricao="Declaração SICAF: fornecedor descredenciado, com impedimento e pendência no nível III "
                  "informada após os itens",
        cobertura={
            "federal": (vd_fed, True, True), "fgts": (vd_fgts, True, True),
            "trabalhista": (vd_trab, True, True),
        },
        sicaf_situacao={"credenciado": False, "situacao": "Descredenciado", "impedimento": imped},
        paginas=[[
            "Ministério da Gestão e da Inovação em Serviços Públicos",
            "# Sistema de Cadastramento Unificado de Fornecedores - SICAF",
            "Declaração",
            f"CNPJ: {fmt_cnpj(CNPJ_EMPRESA)}",
            f"Razão Social: {EMPRESA}",
            "Situação do Fornecedor: Descredenciado",
            "Ocorrência: Nada Consta",
            imped,
            "Ocorrências Impeditivas indiretas: Nada Consta",
            "III - Regularidade Fiscal e Trabalhista Federal",
            f"Receita Federal e PGFN Validade: {br(vd_fed)} Automática",
            f"FGTS Validade: {br(vd_fgts)} Automática",
            f"Trabalhista Validade: {br(vd_trab)} Automática(http://www.tst.jus.br/certidao)",
            "Situação do nível: Possui Pendência",
            "IV - Regularidade Fiscal Estadual/Distrital e Municipal",
            "Nenhum registro encontrado",
            f"Emitido em: {br(h)} 14:32",
        ]]))

    lista.append(Amostra(
        "cnpj_divergente", "federal", "negativa", CNPJ_OUTRA, val180, data_emissao=em,
        descricao="CND federal de OUTRA empresa",
        paginas=[_federal("CERTIDÃO NEGATIVA DE DÉBITOS RELATIVOS AOS TRIBUTOS FEDERAIS E À DÍVIDA "
                          "ATIVA DA UNIÃO", em, val180, CNPJ_OUTRA, OUTRA_EMPRESA, _CORPO_FED_NEG,
                          codigo="ABCD.EF01.2345.6789")]))

    lista.append(Amostra(
        "escaneado", "desconhecida", "indeterminada", None, None, escaneado=True,
        avisos_contem=["PDF sem texto"], descricao="Somente imagem, sem texto"))

    lista.append(Amostra(
        "duas_certidoes", "trabalhista", "negativa", CNPJ_EMPRESA, val180, data_emissao=em,
        avisos_contem=["mais de uma certidão"], descricao="CNDT + federal no mesmo arquivo",
        paginas=[
            _cndt("CERTIDÃO NEGATIVA DE DÉBITOS TRABALHISTAS", em, val180, CNPJ_EMPRESA,
                  "Certifica-se que a empresa NÃO CONSTA como inadimplente no BNDT.",
                  numero="33334444/2026"),
            _federal("CERTIDÃO NEGATIVA DE DÉBITOS RELATIVOS AOS TRIBUTOS FEDERAIS E À DÍVIDA "
                     "ATIVA DA UNIÃO", em, val180 - timedelta(days=30), CNPJ_EMPRESA, EMPRESA,
                     _CORPO_FED_NEG),
        ]))
    return lista


LEIA_ME = f"""AMOSTRAS SINTÉTICAS - {MARCA}

Os PDFs desta pasta são FICTÍCIOS, gerados por tests/gerar_amostras.py apenas para testes
automatizados do extrator. Não são certidões reais e não têm qualquer validade jurídica.

- Empresa fictícia: {EMPRESA} (CNPJ {fmt_cnpj(CNPJ_EMPRESA)}, DV calculado; dado inventado)
- Outra empresa fictícia: {OUTRA_EMPRESA} (CNPJ {fmt_cnpj(CNPJ_OUTRA)})
- As datas são relativas ao dia da geração (date.today()); regenere para atualizar.
- Os códigos de controle são inventados e NÃO devem ser consultados nos portais.
- esperado.json traz, por arquivo, o resultado que o extrator deve produzir.

Regenerar:  python tests/gerar_amostras.py
"""


def gerar(destino: str | Path | None = None, hoje: Optional[date] = None) -> dict[str, dict]:
    """Gera todos os PDFs, LEIA-ME.txt e esperado.json em ``destino``. Devolve o esperado."""
    pasta = Path(destino) if destino else PASTA_PADRAO
    pasta.mkdir(parents=True, exist_ok=True)
    esperado: dict[str, dict] = {}
    for a in amostras(hoje):
        arq = pasta / f"{a.nome}.pdf"
        if a.escaneado:
            _pdf_escaneado(arq)
        else:
            _pdf_texto(arq, a.paginas)
        esperado[arq.name] = {
            "descricao": a.descricao,
            "tipo": a.tipo,
            "situacao": a.situacao,
            "cnpj": a.cnpj,
            "validade": a.validade.isoformat() if a.validade else None,
            "data_emissao": a.data_emissao.isoformat() if a.data_emissao else None,
            "uf": a.uf,
            "municipio": a.municipio,
            "codigo_controle": a.codigo_controle,
            "avisos_contem": a.avisos_contem,
            "cobertura": None if a.cobertura is None else {
                **{k: {"validade": v.isoformat() if v else None, "automatica": aut, "pendencia": pen}
                   for k, (v, aut, pen) in a.cobertura.items()},
                **({"_situacao": a.sicaf_situacao} if a.sicaf_situacao is not None else {}),
            },
        }
    (pasta / "esperado.json").write_text(
        json.dumps({"gerado_em": (hoje or date.today()).isoformat(), "arquivos": esperado},
                   ensure_ascii=False, indent=2), encoding="utf-8")
    (pasta / "LEIA-ME.txt").write_text(LEIA_ME, encoding="utf-8")
    return esperado


if __name__ == "__main__":
    r = gerar(sys.argv[1] if len(sys.argv) > 1 else None)
    print(f"{len(r)} amostras geradas.")
