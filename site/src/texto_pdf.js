// Extrai o texto de um PDF com pdf.js, reconstruindo as linhas como o pdfplumber.
// Usado no navegador (pdfjsLib global) e nos testes em Node (pdfjs-dist).
(function (raiz) {
  "use strict";
  function linhasDaPagina(itens) {
    const pecas = itens
      .filter((i) => typeof i.str === "string" && i.str.length)
      .map((i) => ({ s: i.str, x: i.transform[4], y: i.transform[5], w: i.width || 0,
                     h: Math.abs(i.transform[3]) || Math.abs(i.height) || 10 }));
    pecas.sort((a, b) => b.y - a.y || a.x - b.x);
    const linhas = [];
    for (const p of pecas) {
      const tol = Math.max(2, p.h * 0.4);
      let l = linhas.find((q) => Math.abs(q.y - p.y) <= tol);
      if (!l) { l = { y: p.y, pecas: [] }; linhas.push(l); }
      l.pecas.push(p);
    }
    linhas.sort((a, b) => b.y - a.y);
    return linhas.map((l) => {
      l.pecas.sort((a, b) => a.x - b.x);
      let txt = "", fim = null;
      for (const p of l.pecas) {
        if (fim !== null && p.x - fim > Math.max(1, p.h * 0.15) && !/\s$/.test(txt) && !/^\s/.test(p.s)) txt += " ";
        txt += p.s;
        fim = p.x + p.w;
      }
      return txt.replace(/[ \t]+/g, " ").trim();
    }).filter((t) => t.length);
  }
  async function extrairTexto(pdfjs, dados) {
    const doc = await pdfjs.getDocument({ data: dados, isEvalSupported: false, disableFontFace: true }).promise;
    const partes = [];
    try {
      for (let n = 1; n <= doc.numPages; n++) {
        const pg = await doc.getPage(n);
        const tc = await pg.getTextContent();
        partes.push(linhasDaPagina(tc.items).join("\n"));
      }
    } finally { doc.destroy(); }
    const t = partes.join("\n");
    return t.trim() ? t : "";
  }
  const api = { extrairTexto, linhasDaPagina };
  if (typeof module !== "undefined" && module.exports) module.exports = api; else raiz.TextoPDF = api;
})(typeof window !== "undefined" ? window : globalThis);
