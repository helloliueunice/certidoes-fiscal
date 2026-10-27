// Interações da página de conferência (sem dependências).
(function () {
  "use strict";
  const $ = (s) => document.querySelector(s);
  const digitos = (v) => (v || "").replace(/\D/g, "");

  // ---------- CNPJ: máscara e dígito verificador
  function cnpjValido(c) {
    c = digitos(c);
    if (c.length !== 14 || /^(\d)\1+$/.test(c)) return false;
    const dv = (base, pesos) => {
      const s = base.split("").reduce((t, n, i) => t + Number(n) * pesos[i], 0);
      const r = s % 11;
      return r < 2 ? 0 : 11 - r;
    };
    const p1 = [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2];
    const p2 = [6].concat(p1);
    return dv(c.slice(0, 12), p1) === Number(c[12]) && dv(c.slice(0, 13), p2) === Number(c[13]);
  }
  function mascara(c) {
    c = digitos(c).slice(0, 14);
    return c.replace(/^(\d{2})(\d)/, "$1.$2").replace(/^(\d{2})\.(\d{3})(\d)/, "$1.$2.$3")
      .replace(/\.(\d{3})(\d)/, ".$1/$2").replace(/(\d{4})(\d)/, "$1-$2");
  }
  const cnpj = $("#cnpj");
  const campo = $("#campo-cnpj");
  const ajuda = $("#cnpj-ajuda");
  function atualizarCnpj() {
    if (!cnpj) return;
    cnpj.value = mascara(cnpj.value);
    const d = digitos(cnpj.value);
    campo.classList.remove("success", "danger");
    ajuda.hidden = true;
    $("#cnpj-copiar").hidden = true;
    if (d.length === 14) {
      const ok = cnpjValido(d);
      campo.classList.add(ok ? "success" : "danger");
      ajuda.className = "feedback " + (ok ? "success" : "danger");
      ajuda.innerHTML = ok
        ? '<i class="fas fa-check-circle" aria-hidden="true"></i>CNPJ válido'
        : '<i class="fas fa-times-circle" aria-hidden="true"></i>CNPJ inválido: confira os dígitos';
      ajuda.hidden = false;
      if (ok) {
        $("#cnpj-mascara").textContent = mascara(d);
        $("#cnpj-numeros").textContent = d;
        $("#cnpj-copiar").hidden = false;
      }
    }
  }
  if (cnpj) { cnpj.addEventListener("input", atualizarCnpj); atualizarCnpj(); }

  document.addEventListener("click", (e) => {
    const b = e.target.closest("[data-copiar]");
    if (!b) return;
    const texto = document.getElementById(b.dataset.copiar).textContent;
    const fim = () => { const o = b.innerHTML; b.innerHTML = '<i class="fas fa-check" aria-hidden="true"></i>Copiado'; setTimeout(() => (b.innerHTML = o), 1500); };
    if (navigator.clipboard) navigator.clipboard.writeText(texto).then(fim, fim); else fim();
  });

  // ---------- Portais
  const lista = $("#lista-portais");
  let timer;
  function esc(s) { const d = document.createElement("div"); d.textContent = s == null ? "" : String(s); return d.innerHTML; }
  function tiposMarcados() {
    return Array.from(document.querySelectorAll('input[name="exigidas"]:checked')).map((i) => i.value).join(",");
  }
  async function carregarPortais() {
    if (!lista) return;
    const uf = $("#uf").value, mun = $("#municipio").value.trim();
    if (!uf || !mun) {
      lista.innerHTML = '<p class="text-down-01 m-0 p-2">Informe a UF e o município da sede para ver os portais.</p>';
      return;
    }
    lista.innerHTML = '<p class="text-down-01 m-0 p-2">Carregando portais…</p>';
    try {
      const q = new URLSearchParams({ uf, municipio: mun, tipos: tiposMarcados() });
      const r = await fetch("/api/portais?" + q);
      const { portais } = await r.json();
      if (!portais.length) { lista.innerHTML = '<p class="text-down-01 m-0 p-2">Nenhum portal cadastrado.</p>'; return; }
      lista.innerHTML = portais.map((p) => {
        const captcha = p.captcha === true
          ? '<span class="br-tag warning small"><i class="fas fa-lock" aria-hidden="true"></i> com captcha</span>'
          : p.captcha === false ? '<span class="br-tag small">sem captcha</span>' : "";
        const conferir = p.verificado_em ? "" : '<span class="br-tag small">link a confirmar</span>';
        const botao = p.url
          ? `<a class="br-button secondary small" href="${esc(p.url)}" target="_blank" rel="noopener"><i class="fas fa-external-link-alt" aria-hidden="true"></i>Abrir portal</a>`
          : "";
        return `<div class="br-item" role="listitem">
          <div class="portal-info"><div class="portal-nome">${esc(p.nome)}</div>
          <div class="mt-half"><span class="br-tag small">${esc(p.rotulo)}</span>${captcha}${conferir}</div>
          ${p.observacao ? `<div class="portal-obs mt-half">${esc(p.observacao)}</div>` : ""}</div>${botao}</div>
          <span class="br-divider"></span>`;
      }).join("");
    } catch (e) {
      lista.innerHTML = '<p class="text-down-01 m-0 p-2">Não foi possível carregar o catálogo de portais.</p>';
    }
  }
  const agendar = () => { clearTimeout(timer); timer = setTimeout(carregarPortais, 400); };
  ["#uf", "#municipio"].forEach((s) => { const el = $(s); if (el) el.addEventListener(s === "#uf" ? "change" : "input", agendar); });
  document.querySelectorAll('input[name="exigidas"]').forEach((i) => i.addEventListener("change", agendar));
  carregarPortais();

  // ---------- Conecta
  const btnConecta = $("#btn-conecta");
  if (btnConecta) btnConecta.addEventListener("click", async () => {
    const out = $("#resp-conecta");
    out.hidden = false; out.textContent = "Consultando…";
    const fd = new FormData(); fd.append("cnpj", cnpj.value);
    try { const r = await fetch("/api/conecta", { method: "POST", body: fd }); out.textContent = JSON.stringify(await r.json(), null, 2); }
    catch (e) { out.textContent = "Falha na consulta."; }
  });

  // ---------- Upload (componente br-upload do gov.br DS, sem o JS do DS)
  const area = $("#upload"), input = $("#arquivos"), listaArq = $("#upload-lista"), form = $("#form-conferir");
  if (!area) return;
  let arquivos = [];
  const tamanho = (b) => (b > 1048576 ? (b / 1048576).toFixed(1) + " MB" : Math.max(1, Math.round(b / 1024)) + " KB");
  function desenhar() {
    listaArq.innerHTML = "";
    arquivos.forEach((f, i) => {
      const item = document.createElement("div");
      item.className = "br-item d-flex";
      item.innerHTML = `<div class="content text-primary-default mr-auto">${esc(f.name)}</div>
        <div class="support mr-n2"><span class="mr-1">${tamanho(f.size)}</span>
        <button class="br-button circle small" type="button" aria-label="Remover ${esc(f.name)}"><i class="fas fa-trash" aria-hidden="true"></i></button></div>`;
      item.querySelector("button").addEventListener("click", () => { arquivos.splice(i, 1); desenhar(); });
      listaArq.appendChild(item);
    });
  }
  function adicionar(novos) {
    Array.from(novos).forEach((f) => {
      if (!/\.pdf$/i.test(f.name) && f.type !== "application/pdf") return;
      if (!arquivos.some((a) => a.name === f.name && a.size === f.size)) arquivos.push(f);
    });
    desenhar();
  }
  input.addEventListener("change", () => { adicionar(input.files); input.value = ""; });
  ["dragenter", "dragover"].forEach((ev) => area.addEventListener(ev, (e) => { e.preventDefault(); area.classList.add("dragging"); }));
  ["dragleave", "drop"].forEach((ev) => area.addEventListener(ev, (e) => { e.preventDefault(); area.classList.remove("dragging"); }));
  area.addEventListener("drop", (e) => adicionar(e.dataTransfer.files));

  form.addEventListener("submit", () => {
    try {
      const dt = new DataTransfer();
      arquivos.forEach((f) => dt.items.add(f));
      input.files = dt.files;
    } catch (e) { /* navegador antigo: envia o que estiver no campo */ }
    const b = $("#btn-conferir");
    b.disabled = true;
    b.innerHTML = '<i class="fas fa-spinner fa-spin" aria-hidden="true"></i>Conferindo…';
  });
})();
