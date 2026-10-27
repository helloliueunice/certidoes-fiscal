// Página "Planejar emissão do mês": lista de arquivos, marcação de "feito" e progresso.
// O estado fica só no navegador (memória + localStorage, quando disponível).
(function () {
  "use strict";
  const $ = (s) => document.querySelector(s);
  const esc = (s) => { const d = document.createElement("div"); d.textContent = s == null ? "" : String(s); return d.innerHTML; };

  // ---------- lista dos CSVs escolhidos
  const input = $("#csvs"), lista = $("#csvs-lista"), area = $("#upload-csv");
  function desenhar() {
    if (!input || !lista) return;
    lista.innerHTML = Array.from(input.files || []).map((f) =>
      `<div class="br-item d-flex"><div class="content text-primary-default mr-auto">${esc(f.name)}</div>
       <div class="support"><span>${Math.max(1, Math.round(f.size / 1024))} KB</span></div></div>`).join("");
  }
  if (input) input.addEventListener("change", desenhar);
  if (area && input) {
    ["dragenter", "dragover"].forEach((ev) => area.addEventListener(ev, (e) => { e.preventDefault(); area.classList.add("dragging"); }));
    ["dragleave", "drop"].forEach((ev) => area.addEventListener(ev, (e) => { e.preventDefault(); area.classList.remove("dragging"); }));
    area.addEventListener("drop", (e) => {
      try { input.files = e.dataTransfer.files; } catch (err) { /* navegador antigo */ }
      desenhar();
    });
  }
  const form = $("#form-mutirao");
  if (form) form.addEventListener("submit", () => {
    const b = $("#btn-planejar");
    b.disabled = true;
    b.innerHTML = '<i class="fas fa-spinner fa-spin" aria-hidden="true"></i>Planejando…';
  });

  // ---------- "feito" por item
  const PREFIXO = "mutirao:";
  const memoria = {};
  function ler(chave) {
    if (chave in memoria) return memoria[chave];
    try { return window.localStorage.getItem(PREFIXO + chave) === "1"; } catch (e) { return false; }
  }
  function gravar(chave, valor) {
    memoria[chave] = valor;
    try {
      if (valor) window.localStorage.setItem(PREFIXO + chave, "1");
      else window.localStorage.removeItem(PREFIXO + chave);
    } catch (e) { /* modo privado ou armazenamento bloqueado: fica só em memória */ }
  }
  const caixas = Array.from(document.querySelectorAll("input.feito"));
  const texto = $("#progresso-texto"), barra = $("#progresso-barra");
  function progresso() {
    const feitos = caixas.filter((c) => c.checked).length;
    const total = caixas.length;
    if (texto) texto.textContent = total ? `${feitos} de ${total} feitos` : "Nada a fazer";
    if (barra) {
      barra.setAttribute("aria-valuenow", String(feitos));
      barra.firstElementChild.style.width = (total ? Math.round((feitos / total) * 100) : 100) + "%";
      barra.classList.toggle("completo", total > 0 && feitos === total);
    }
  }
  function marcar(c) {
    const item = c.closest(".item-plano");
    if (item) item.classList.toggle("feito", c.checked);
  }
  caixas.forEach((c) => {
    c.checked = ler(c.dataset.chave);
    marcar(c);
    c.addEventListener("change", () => { gravar(c.dataset.chave, c.checked); marcar(c); progresso(); });
  });
  const limpar = $("#limpar-feitos");
  if (limpar) limpar.addEventListener("click", () => {
    caixas.forEach((c) => { c.checked = false; gravar(c.dataset.chave, false); marcar(c); });
    progresso();
  });
  progresso();
})();
