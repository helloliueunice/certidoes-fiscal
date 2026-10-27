// PDF do checklist + minuta (mesmo conteúdo de certidoes/atesto.py), gerado no navegador com jsPDF.
(function (raiz) {
  "use strict";
  const COR = { verde: [200, 230, 201], amarelo: [255, 245, 157], vermelho: [255, 205, 210] };
  const AZUL = [19, 81, 180];

  function gerar(r) {
    const { jsPDF } = raiz.jspdf;
    const doc = new jsPDF({ unit: "pt", format: "a4" });
    const M = 56, L = doc.internal.pageSize.getWidth() - 2 * M;
    let y = 60;
    const c = r.contrato;

    function precisa(h) { if (y + h > doc.internal.pageSize.getHeight() - 60) { doc.addPage(); y = 60; } }
    function titulo(t, tam) {
      precisa(30); doc.setFont("helvetica", "bold"); doc.setFontSize(tam || 12); doc.setTextColor(0);
      doc.text(t, M, y); y += (tam || 12) + 8;
    }
    function par(t, opts) {
      opts = opts || {};
      doc.setFont("helvetica", opts.estilo || "normal"); doc.setFontSize(opts.tam || 9.5); doc.setTextColor(opts.cor || 40);
      const linhas = doc.splitTextToSize(String(t), L - (opts.recuo || 0));
      for (const l of linhas) { precisa(14); doc.text(l, M + (opts.recuo || 0), y); y += (opts.tam || 9.5) * 1.35; }
      y += opts.depois == null ? 4 : opts.depois;
    }
    function tabela(cfg) {
      doc.autoTable(Object.assign({
        startY: y, margin: { left: M, right: M, bottom: 60 }, theme: "grid",
        styles: { font: "helvetica", fontSize: 8, cellPadding: 4, textColor: 40, lineColor: [200, 200, 200], lineWidth: 0.5 },
        headStyles: { fillColor: AZUL, textColor: 255, fontStyle: "bold" },
      }, cfg));
      y = doc.lastAutoTable.finalY + 14;
    }

    doc.setFont("helvetica", "bold"); doc.setFontSize(16); doc.setTextColor(0);
    doc.text("Checklist de Regularidade para Atesto", doc.internal.pageSize.getWidth() / 2, y, { align: "center" });
    y += 22;
    const agora = new Date();
    const gerado = agora.toLocaleDateString("pt-BR") + " " + agora.toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" });
    tabela({
      body: [["Órgão", c.orgao || "—"], ["Contrato nº", c.numero], ["Contratada", c.razao_social + " — CNPJ " + c.cnpj],
             ["Sede", c.municipio + "/" + c.uf], ["Competência", c.competencia || "—"], ["Fiscal", c.fiscal || "—"],
             ["Data de referência", r.data_referencia], ["Gerado em", gerado]],
      columnStyles: { 0: { fontStyle: "bold", cellWidth: 110, fillColor: [242, 242, 242] } }, styles: { fontSize: 9 },
    });
    par("Situação geral: " + (r.apto ? "sem pendências impeditivas (confira os itens em ATENÇÃO)." : "há pendências (itens PENDENTE)."),
        { estilo: "bold", tam: 10 });

    titulo("Checklist");
    tabela({
      head: [["Item", "Situação", "Resultado", "Validade", "Código de controle", "Arquivo"]],
      body: r.itens.map((i) => [i.rotulo, i.situacao + "\n" + i.mensagem, i.resultado, i.validade, i.codigo_controle, i.arquivo]),
      columnStyles: { 0: { cellWidth: 78 }, 1: { cellWidth: 170 }, 2: { cellWidth: 58, halign: "center", fontStyle: "bold" },
                      3: { cellWidth: 52 }, 4: { cellWidth: 70 } },
      didParseCell: (d) => { if (d.section === "body" && d.column.index === 2) d.cell.styles.fillColor = COR[r.itens[d.row.index].semaforo]; },
    });
    par("Legenda: OK = sem apontamentos; ATENÇÃO = aceita, mas exige conferência ou vence em breve; PENDENTE = impede o atesto até regularização.",
        { tam: 8, cor: 90 });

    if (r.extras.length) {
      titulo("Outros documentos enviados");
      for (const x of r.extras) par((x.alerta ? "ATENÇÃO: " : "") + x.arquivo + " (" + x.rotulo + "): " + x.nota, { tam: 9 });
    }

    titulo("Conferência de autenticidade");
    for (const ct of r.certidoes) {
      par("[ ] autenticidade conferida — " + ct.rotulo + " (" + ct.arquivo + ")", { estilo: "bold", tam: 9, depois: 0 });
      par("Site: " + (ct.url_verificacao || "não identificado — usar o portal do emissor") + " — Código: " + (ct.codigo_controle || "não identificado"),
          { tam: 8.5, recuo: 14, cor: 70 });
    }

    titulo("Checklist do fiscal");
    for (const t of r.checklist_manual) par("[ ] " + t, { tam: 9.5, depois: 1 });
    y += 6;

    if (r.contrato.observacoes) { titulo("Observações do fiscal"); par(r.contrato.observacoes); }

    titulo(r.minuta.titulo);
    par("Texto sugerido; revisar antes de usar.", { estilo: "italic", tam: 8.5, cor: 90 });
    for (const p of r.minuta.paragrafos) par(p, { tam: 10, depois: 6 });

    precisa(80); y += 30;
    doc.setDrawColor(80); doc.line(M, y, M + 230, y);
    doc.setFont("helvetica", "normal"); doc.setFontSize(9); doc.setTextColor(40);
    doc.text("Data: ____/____/________", M + L - 150, y);
    doc.text(c.fiscal || "Fiscal do contrato", M, y + 12); doc.text("Fiscal do contrato", M, y + 24);
    doc.text("Matrícula/SIAPE: ____________", M + L - 150, y + 14);

    const n = doc.internal.getNumberOfPages();
    for (let p = 1; p <= n; p++) {
      doc.setPage(p); doc.setFont("helvetica", "normal"); doc.setFontSize(7.5); doc.setTextColor(70);
      const yb = doc.internal.pageSize.getHeight() - 34;
      doc.text(r.aviso_rodape, M, yb);
      doc.text("Página " + p + " de " + n, M + L, yb, { align: "right" });
    }
    return doc.output("arraybuffer");
  }
  raiz.PdfAtesto = { gerar };
})(window);
