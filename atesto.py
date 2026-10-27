"""Geração do PDF de checklist + minuta (atesto ou notificação) e do CSV de controle mensal.

Toda saída é MINUTA: a conferência e a decisão são do fiscal do contrato.
"""
from __future__ import annotations

import csv
import os
from datetime import datetime
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import (
    KeepTogether,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from .models import Certidao, ResultadoValidacao, Semaforo, formatar_cnpj
from .validador import (
    ROTULO_SEMAFORO,
    ROTULO_SITUACAO,
    alerta_extra,
    formatar_data,
    nota_extra,
)

AVISO_RODAPE = (
    "Documento gerado automaticamente como apoio. "
    "A conferência e a decisão são do fiscal do contrato."
)

COR_SEMAFORO = {
    Semaforo.VERDE: colors.HexColor("#C8E6C9"),
    Semaforo.AMARELO: colors.HexColor("#FFF59D"),
    Semaforo.VERMELHO: colors.HexColor("#FFCDD2"),
}

CHECKLIST_MANUAL = [
    "Certidões conferidas no site do emissor (código de controle).",
    "CNPJ das certidões igual ao do contrato.",
    "Sanções consultadas (CEIS/CNEP), se exigido no contrato.",
    "Documentos juntados ao processo.",
    "Nota fiscal compatível com a competência.",
]


def _e(s) -> str:
    return escape(str(s or ""))


def _estilos():
    base = getSampleStyleSheet()
    return {
        "titulo": ParagraphStyle("titulo", parent=base["Title"], fontSize=15, spaceAfter=6),
        "h2": ParagraphStyle("h2", parent=base["Heading2"], fontSize=12, spaceBefore=10, spaceAfter=4),
        "normal": ParagraphStyle("normal", parent=base["Normal"], fontSize=9.5, leading=12.5),
        "cel": ParagraphStyle("cel", parent=base["Normal"], fontSize=8, leading=10),
        "celc": ParagraphStyle("celc", parent=base["Normal"], fontSize=8, leading=10,
                               alignment=TA_CENTER, fontName="Helvetica-Bold"),
        "minuta": ParagraphStyle("minuta", parent=base["Normal"], fontSize=10, leading=14,
                                 spaceAfter=6, firstLineIndent=0),
    }


def _rodape(canvas, doc):
    canvas.saveState()
    canvas.setFont("Helvetica", 7.5)
    canvas.setFillColor(colors.HexColor("#444444"))
    canvas.drawString(2 * cm, 1.2 * cm, AVISO_RODAPE)
    canvas.drawRightString(A4[0] - 2 * cm, 1.2 * cm, f"Página {doc.page}")
    canvas.restoreState()


def _todas_certidoes(resultado: ResultadoValidacao) -> list[Certidao]:
    vistas: list[Certidao] = []
    ids: set[int] = set()
    for c in [i.certidao for i in resultado.itens if i.certidao] + list(resultado.extras):
        if id(c) not in ids:
            ids.add(id(c))
            vistas.append(c)
    return vistas


def _minuta(resultado: ResultadoValidacao, orgao: str) -> tuple[str, list[str]]:
    c = resultado.contrato
    comp = c.competencia or "[competência]"
    empresa = f"{_e(c.razao_social)}, CNPJ {formatar_cnpj(c.cnpj)}"
    if resultado.apto_atesto:
        lista = "; ".join(
            f"{i.tipo.rotulo}"
            + (f" (validade {formatar_data(i.certidao.validade)})"
               if i.certidao and i.certidao.validade else "")
            for i in resultado.itens
        )
        pars = [
            f"Contrato nº {_e(c.numero)} — {empresa}.",
            "À vista das certidões relacionadas neste checklist "
            f"({_e(lista)}), não foram identificadas pendências de regularidade fiscal, social e "
            "trabalhista nas certidões apresentadas e conferidas, "
            f"para fins de atesto da competência {_e(comp)}.",
        ]
        if any(i.semaforo == Semaforo.AMARELO for i in resultado.itens):
            pars.append("[ ] Conferi manualmente os itens em ATENÇÃO.")
        return "Minuta de atesto de regularidade", pars

    pend = [i for i in resultado.itens if i.semaforo == Semaforo.VERMELHO]
    pars = [
        f"À {empresa}.",
        f"Referência: Contrato nº {_e(c.numero)}"
        + (f" — {_e(orgao)}" if orgao else "") + f" — competência {_e(comp)}.",
        "Na conferência da regularidade fiscal, social e trabalhista exigida no contrato, "
        "foram identificadas as seguintes pendências:",
    ]
    for i in pend:
        pars.append(f"- {_e(i.tipo.rotulo)}: {_e(i.mensagem)}")
    pars.append(
        "Solicitamos a regularização e o envio das certidões atualizadas no prazo de "
        "[prazo], contado do recebimento desta notificação, para prosseguimento da "
        "fiscalização do contrato, nos termos contratuais."
    )
    return "Minuta de notificação à contratada", pars


def gerar_pdf(
    resultado: ResultadoValidacao,
    caminho_saida: str,
    orgao: str = "",
    observacoes: str = "",
) -> str:
    """Gera o PDF do checklist com a minuta. Retorna o caminho gerado."""
    pasta = os.path.dirname(os.path.abspath(caminho_saida))
    os.makedirs(pasta, exist_ok=True)
    st = _estilos()
    c = resultado.contrato
    doc = SimpleDocTemplate(
        caminho_saida, pagesize=A4,
        leftMargin=2 * cm, rightMargin=2 * cm, topMargin=1.8 * cm, bottomMargin=2 * cm,
        title="Checklist de Regularidade para Atesto", author=c.fiscal or "",
    )
    larg = A4[0] - 4 * cm
    el = []

    # cabeçalho
    el.append(Paragraph("Checklist de Regularidade para Atesto", st["titulo"]))
    cab = [
        ("Órgão", orgao or "—"),
        ("Contrato nº", c.numero or "—"),
        ("Contratada", f"{c.razao_social} — CNPJ {formatar_cnpj(c.cnpj)}"),
        ("Sede", f"{c.municipio_sede}/{c.uf_sede}"),
        ("Competência", c.competencia or "—"),
        ("Fiscal", c.fiscal or "—"),
        ("Data de referência", formatar_data(resultado.data_referencia)),
        ("Gerado em", datetime.now().strftime("%d/%m/%Y %H:%M")),
    ]
    t = Table(
        [[Paragraph(f"<b>{_e(k)}</b>", st["cel"]), Paragraph(_e(v), st["cel"])] for k, v in cab],
        colWidths=[3.6 * cm, larg - 3.6 * cm],
    )
    t.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.3, colors.grey),
        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#EEF2F7")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    el.append(t)

    situacao_geral = (
        "Sem pendências impeditivas (verificar itens em ATENÇÃO)."
        if resultado.apto_atesto else "Há pendências (itens PENDENTE)."
    )
    el.append(Spacer(1, 6))
    el.append(Paragraph(f"<b>Situação geral:</b> {_e(situacao_geral)}", st["normal"]))

    # checklist
    el.append(Paragraph("Checklist", st["h2"]))
    dados = [[Paragraph(f"<b>{h}</b>", st["cel"]) for h in
              ("Item", "Situação", "Resultado", "Validade", "Código de controle", "Arquivo")]]
    estilo = [
        ("GRID", (0, 0), (-1, -1), 0.3, colors.grey),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1F4E79")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]
    for n, item in enumerate(resultado.itens, start=1):
        cert = item.certidao
        situ = ROTULO_SITUACAO[cert.situacao] if cert else "—"
        dados.append([
            Paragraph(_e(item.tipo.rotulo), st["cel"]),
            Paragraph(f"{_e(situ)}<br/>{_e(item.mensagem)}", st["cel"]),
            Paragraph(ROTULO_SEMAFORO[item.semaforo], st["celc"]),
            Paragraph(formatar_data(cert.validade) if cert else "—", st["cel"]),
            Paragraph(_e(cert.codigo_controle) if cert and cert.codigo_controle else "—", st["cel"]),
            Paragraph(_e(os.path.basename(cert.arquivo)) if cert else "—", st["cel"]),
        ])
        estilo.append(("BACKGROUND", (2, n), (2, n), COR_SEMAFORO[item.semaforo]))
    ws = [2.9, 5.6, 2.3, 1.9, 2.4]
    ws = [w * cm for w in ws]
    ws.append(larg - sum(ws))
    t = Table(dados, colWidths=ws, repeatRows=1)
    t.setStyle(TableStyle(estilo))
    el.append(t)
    el.append(Paragraph(
        "Legenda: OK = sem apontamentos; ATENÇÃO = aceita, mas exige conferência ou vence em breve; "
        "PENDENTE = impede o atesto até regularização.", st["cel"]))

    if resultado.extras:
        el.append(Paragraph("Outros documentos enviados", st["h2"]))
        for x in resultado.extras:
            p = Paragraph(
                f"- <b>{_e(os.path.basename(x.arquivo))}</b> ({_e(x.tipo.rotulo)}): "
                f"{_e(nota_extra(x, resultado))}", st["normal"])
            if alerta_extra(x, resultado):
                caixa = Table([[p]], colWidths=[larg])
                caixa.setStyle(TableStyle([
                    ("BACKGROUND", (0, 0), (-1, -1), COR_SEMAFORO[Semaforo.VERMELHO]),
                    ("BOX", (0, 0), (-1, -1), 0.8, colors.HexColor("#B71C1C")),
                ]))
                el.append(caixa)
            else:
                el.append(p)

    # autenticidade
    el.append(Paragraph("Conferência de autenticidade", st["h2"]))
    certs = _todas_certidoes(resultado)
    if not certs:
        el.append(Paragraph("Nenhuma certidão enviada.", st["normal"]))
    for x in certs:
        el.append(Paragraph(
            f"[ ] autenticidade conferida — <b>{_e(x.tipo.rotulo)}</b> "
            f"({_e(os.path.basename(x.arquivo))})<br/>"
            f"&nbsp;&nbsp;&nbsp;&nbsp;Site: {_e(x.url_verificacao or 'não identificado — usar o portal do emissor')}"
            f" — Código: {_e(x.codigo_controle or 'não identificado')}",
            st["normal"]))

    # checklist manual
    el.append(Paragraph("Checklist do fiscal", st["h2"]))
    for linha in CHECKLIST_MANUAL:
        el.append(Paragraph(f"[ ] {_e(linha)}", st["normal"]))

    if observacoes.strip():
        el.append(Paragraph("Observações", st["h2"]))
        for p in observacoes.strip().splitlines():
            el.append(Paragraph(_e(p) or "&nbsp;", st["normal"]))

    # minuta
    titulo, pars = _minuta(resultado, orgao)
    bloco = [Paragraph(_e(titulo), st["h2"]),
             Paragraph("<i>Texto sugerido; revisar antes de usar.</i>", st["cel"])]
    bloco += [Paragraph(p, st["minuta"]) for p in pars]
    el.append(KeepTogether(bloco[:3]))
    el.extend(bloco[3:])

    # assinatura
    el.append(Spacer(1, 28))
    assin = Table([
        ["______________________________________", "Data: ____/____/________"],
        [Paragraph(f"{_e(c.fiscal) or 'Fiscal do contrato'}<br/>Fiscal do contrato", st["cel"]),
         Paragraph("Matrícula/SIAPE: ______________", st["cel"])],
    ], colWidths=[larg * 0.6, larg * 0.4])
    assin.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]))
    el.append(KeepTogether([assin]))

    doc.build(el, onFirstPage=_rodape, onLaterPages=_rodape)
    return caminho_saida


CAMPOS_CSV = [
    "data_referencia", "competencia", "contrato", "cnpj", "razao_social", "fiscal",
    "item", "semaforo", "resultado", "situacao", "validade", "codigo_controle",
    "arquivo", "mensagem", "apto_atesto",
]


def gerar_csv(resultados: list[ResultadoValidacao], caminho: str) -> str:
    """Uma linha por item do checklist (controle mensal). Separador ';' (Excel pt-BR)."""
    pasta = os.path.dirname(os.path.abspath(caminho))
    os.makedirs(pasta, exist_ok=True)
    with open(caminho, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=CAMPOS_CSV, delimiter=";")
        w.writeheader()
        for r in resultados:
            c = r.contrato
            for i in r.itens:
                cert = i.certidao
                w.writerow({
                    "data_referencia": formatar_data(r.data_referencia),
                    "competencia": c.competencia,
                    "contrato": c.numero,
                    "cnpj": formatar_cnpj(c.cnpj),
                    "razao_social": c.razao_social,
                    "fiscal": c.fiscal,
                    "item": i.tipo.rotulo,
                    "semaforo": i.semaforo.value,
                    "resultado": ROTULO_SEMAFORO[i.semaforo],
                    "situacao": ROTULO_SITUACAO[cert.situacao] if cert else "",
                    "validade": formatar_data(cert.validade) if cert else "",
                    "codigo_controle": (cert.codigo_controle or "") if cert else "",
                    "arquivo": os.path.basename(cert.arquivo) if cert else "",
                    "mensagem": i.mensagem,
                    "apto_atesto": "sim" if r.apto_atesto else "não",
                })
    return caminho
