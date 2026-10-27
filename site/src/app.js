// Conferência de Certidões — versão que roda inteira no navegador.
// As regras (leitura, semáforo, minutas, planejamento) são o pacote Python `certidoes`, executado com Pyodide.
(function () {
  "use strict";
  const $ = (s, r) => (r || document).querySelector(s);
  const $$ = (s, r) => Array.from((r || document).querySelectorAll(s));
  const esc = (s) => { const d = document.createElement("div"); d.textContent = s == null ? "" : String(s); return d.innerHTML; };
  const digitos = (v) => String(v || "").replace(/\D/g, "");

  const UFS = ["AC","AL","AP","AM","BA","CE","DF","ES","GO","MA","MT","MS","MG","PA","PB","PR","PE","PI","RJ","RN","RS","RO","RR","SC","SP","SE","TO"];
  const TIPOS = [["federal","Receita Federal / PGFN"],["fgts","FGTS (CRF - Caixa)"],["trabalhista","Trabalhista (CNDT - TST)"],
                 ["estadual","Fazenda Estadual"],["municipal","Fazenda Municipal"],["sicaf","SICAF"]];
  const PADRAO = new Set(["federal","fgts","trabalhista","estadual","municipal"]);
  const CLASSE = { verde: "success", amarelo: "warning", vermelho: "danger" };
  const ICONE = { verde: "fa-check-circle", amarelo: "fa-exclamation-triangle", vermelho: "fa-times-circle" };
  const MAX_ARQ = 20, MAX_MB = 10;
  const ARQUIVOS_PY = ["certidoes/__init__.py","certidoes/models.py","certidoes/extrator.py","certidoes/validador.py",
                       "certidoes/planejamento.py","certidoes/portais.py","certidoes/atesto.py","certidoes/navegador.py","data/portais.json"];
  const EXEMPLOS = ["federal_negativa","fgts_regular","cndt_positiva","estadual_sp_pge","estadual_sp_sefaz","municipal_sp","cnpj_divergente"];

  let nav = null;            // módulo Python certidoes.navegador
  let ultimo = null;         // último resultado
  let downloads = null;      // capacidade de download do visualizador
  const hojeISO = () => { const d = new Date(); return new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 10); };

  // ------------------------------------------------------------------ navegação por seções
  const VISTAS = ["conferir", "resultado", "planejar", "como-usar"];
  function mostrar() {
    let v = (location.hash || "#conferir").slice(1);
    if (!VISTAS.includes(v) || (v === "resultado" && !ultimo)) v = "conferir";
    for (const n of VISTAS) $("#vista-" + n).hidden = n !== v;
    $$(".header-links [data-vista]").forEach((a) => {
      const atual = a.dataset.vista === v || (v === "resultado" && a.dataset.vista === "conferir");
      if (atual) a.setAttribute("aria-current", "page"); else a.removeAttribute("aria-current");
    });
  }
  window.addEventListener("hashchange", () => { mostrar(); window.scrollTo(0, 0); });

  // ------------------------------------------------------------------ copiar
  document.addEventListener("click", (e) => {
    const b = e.target.closest("[data-copiar]");
    if (!b) return;
    const el = document.getElementById(b.dataset.copiar);
    const texto = el ? el.textContent : "";
    const original = b.innerHTML;
    const ok = () => { b.innerHTML = '<i class="fas fa-check" aria-hidden="true"></i>Copiado'; setTimeout(() => (b.innerHTML = original), 1600); };
    const manual = () => {
      try { const s = window.getSelection(), rg = document.createRange(); rg.selectNodeContents(el); s.removeAllRanges(); s.addRange(rg); } catch (x) { /* nada */ }
      b.innerHTML = '<i class="fas fa-i-cursor" aria-hidden="true"></i>Texto selecionado: use Ctrl+C'; setTimeout(() => (b.innerHTML = original), 2500);
    };
    try { navigator.clipboard.writeText(texto).then(ok, manual); } catch (x) { manual(); }
  });

  // ------------------------------------------------------------------ CNPJ
  function cnpjValido(c) {
    c = digitos(c);
    if (c.length !== 14 || /^(\d)\1+$/.test(c)) return false;
    const dv = (base, pesos) => { const s = base.split("").reduce((t, n, i) => t + Number(n) * pesos[i], 0); const r = s % 11; return r < 2 ? 0 : 11 - r; };
    const p1 = [5,4,3,2,9,8,7,6,5,4,3,2], p2 = [6].concat(p1);
    return dv(c.slice(0, 12), p1) === Number(c[12]) && dv(c.slice(0, 13), p2) === Number(c[13]);
  }
  function mascara(c) {
    c = digitos(c).slice(0, 14);
    return c.replace(/^(\d{2})(\d)/, "$1.$2").replace(/^(\d{2})\.(\d{3})(\d)/, "$1.$2.$3").replace(/\.(\d{3})(\d)/, ".$1/$2").replace(/(\d{4})(\d)/, "$1-$2");
  }
  function atualizarCnpj() {
    const cnpj = $("#cnpj"), campo = $("#campo-cnpj"), ajuda = $("#cnpj-ajuda");
    cnpj.value = mascara(cnpj.value);
    const d = digitos(cnpj.value);
    campo.classList.remove("success", "danger"); ajuda.hidden = true; $("#cnpj-copiar").hidden = true;
    if (d.length === 14) {
      const ok = cnpjValido(d);
      campo.classList.add(ok ? "success" : "danger");
      ajuda.className = "feedback " + (ok ? "success" : "danger");
      ajuda.innerHTML = ok ? '<i class="fas fa-check-circle" aria-hidden="true"></i>CNPJ válido' : '<i class="fas fa-times-circle" aria-hidden="true"></i>CNPJ inválido: confira os dígitos';
      ajuda.hidden = false;
      if (ok) { $("#cnpj-mascara").textContent = mascara(d); $("#cnpj-numeros").textContent = d; $("#cnpj-copiar").hidden = false; }
    }
  }

  // ------------------------------------------------------------------ envio de arquivos (componente br-upload, sem o JS do DS)
  function montarUpload(area, input, lista, filtro) {
    const arquivos = [];
    const tamanho = (b) => (b > 1048576 ? (b / 1048576).toFixed(1) + " MB" : Math.max(1, Math.round(b / 1024)) + " KB");
    function desenhar() {
      lista.innerHTML = "";
      arquivos.forEach((f, i) => {
        const item = document.createElement("div");
        item.className = "br-item d-flex";
        item.innerHTML = '<div class="content text-primary-default mr-auto">' + esc(f.name) + '</div><div class="support mr-n2"><span class="mr-1">' + tamanho(f.size) +
          '</span><button class="br-button circle small" type="button" aria-label="Remover ' + esc(f.name) + '"><i class="fas fa-trash" aria-hidden="true"></i></button></div>';
        item.querySelector("button").addEventListener("click", () => { arquivos.splice(i, 1); desenhar(); });
        lista.appendChild(item);
      });
    }
    function adicionar(novos) {
      Array.from(novos).forEach((f) => { if (filtro(f) && !arquivos.some((a) => a.name === f.name && a.size === f.size)) arquivos.push(f); });
      desenhar();
    }
    input.addEventListener("change", () => { adicionar(input.files); input.value = ""; });
    ["dragenter", "dragover"].forEach((ev) => area.addEventListener(ev, (e) => { e.preventDefault(); area.classList.add("dragging"); }));
    ["dragleave", "drop"].forEach((ev) => area.addEventListener(ev, (e) => { e.preventDefault(); area.classList.remove("dragging"); }));
    area.addEventListener("drop", (e) => adicionar(e.dataTransfer.files));
    return { arquivos, adicionar, limpar: () => { arquivos.length = 0; desenhar(); } };
  }
  document.addEventListener("click", (e) => { const b = e.target.closest("[data-abrir]"); if (b) document.getElementById(b.dataset.abrir).click(); });

  // ------------------------------------------------------------------ Python (Pyodide)
  async function prepararPython() {
    const base = new URL("./", location.href).href;
    const py = await loadPyodide({ indexURL: base + "py/", stdLibURL: base + "py/python_stdlib.zip.wasm" });
    $("#preparo-texto").textContent = " Carregando as regras de leitura das certidões…";
    py.FS.mkdirTree("/home/pyodide/certidoes"); py.FS.mkdirTree("/home/pyodide/data");
    await Promise.all(ARQUIVOS_PY.map(async (p) => {
      const r = await fetch("py/" + p);
      if (!r.ok) throw new Error("arquivo " + p + " indisponível (" + r.status + ")");
      py.FS.writeFile("/home/pyodide/" + p, await r.text());
    }));
    py.runPython("import sys\nif '/home/pyodide' not in sys.path: sys.path.insert(0, '/home/pyodide')");
    return py.pyimport("certidoes.navegador");
  }
  function chamar(fn, ...args) { return JSON.parse(nav[fn](...args)); }

  function mostrarErros(alvo, lista, erros) {
    $(lista).innerHTML = erros.map((e) => "<li>" + esc(e) + "</li>").join("");
    $(alvo).hidden = !erros.length;
    if (erros.length) $(alvo).scrollIntoView({ behavior: "smooth", block: "center" });
  }

  // ------------------------------------------------------------------ portais
  let timerPortais;
  function marcados() { return $$('#exigidas input:checked').map((i) => i.value); }
  function desenharPortais() {
    const lista = $("#lista-portais");
    const uf = $("#uf").value, mun = $("#municipio").value.trim();
    if (!nav) return;
    if (!uf || !mun) { lista.innerHTML = '<p class="text-down-01 m-0 p-2">Informe a UF e o município da sede para ver os portais.</p>'; return; }
    const sicaf = $("#aceitar_sicaf").checked;
    const tipos = marcados(); if (sicaf && !tipos.includes("sicaf")) tipos.push("sicaf");
    const portais = chamar("portais", uf, mun, JSON.stringify(tipos), sicaf);
    if (!portais.length) { lista.innerHTML = '<p class="text-down-01 m-0 p-2">Nenhum portal cadastrado.</p>'; return; }
    lista.innerHTML = portais.map((p) => {
      const captcha = p.captcha === true ? '<span class="br-tag warning small"><i class="fas fa-lock" aria-hidden="true"></i> com captcha</span>'
        : p.captcha === false ? '<span class="br-tag small">sem captcha</span>' : "";
      const destaque = p.destaque ? '<span class="br-tag success small"><i class="fas fa-star" aria-hidden="true"></i> comece por aqui</span>' : "";
      const conferir = p.verificado_em ? "" : '<span class="br-tag small">link a confirmar</span>';
      const botao = p.url ? '<a class="br-button secondary small" href="' + esc(p.url) + '" target="_blank" rel="noopener"><i class="fas fa-external-link-alt" aria-hidden="true"></i>Abrir portal<span class="sr-only"> (abre em nova aba)</span></a>' : "";
      return '<div class="br-item' + (p.destaque ? " portal-destaque" : "") + '" role="listitem"><div class="portal-info"><div class="portal-nome">' + esc(p.nome) +
        '</div><div class="mt-half"><span class="br-tag small">' + esc(p.rotulo) + "</span>" + destaque + captcha + conferir + "</div>" +
        (p.observacao ? '<div class="portal-obs mt-half">' + esc(p.observacao) + "</div>" : "") + "</div>" + botao + '</div><span class="br-divider"></span>';
    }).join("");
  }
  const agendarPortais = () => { clearTimeout(timerPortais); timerPortais = setTimeout(desenharPortais, 300); };

  // ------------------------------------------------------------------ leitura dos PDFs
  async function lerPdfs(arquivos, aoAvancar) {
    const saida = [];
    let n = 0;
    for (const f of arquivos) {
      aoAvancar(++n, arquivos.length, f.name);
      if (f.size > MAX_MB * 1048576) { saida.push({ nome: f.name, erro: "arquivo maior que " + MAX_MB + " MB" }); continue; }
      const dados = new Uint8Array(await f.arrayBuffer());
      if (String.fromCharCode(...dados.slice(0, 4)) !== "%PDF") { saida.push({ nome: f.name, erro: "o arquivo não é um PDF" }); continue; }
      try { saida.push({ nome: f.name, texto: await TextoPDF.extrairTexto(pdfjsLib, dados) }); }
      catch (e) { saida.push({ nome: f.name, erro: e && e.name === "PasswordException" ? "PDF protegido por senha" : "PDF corrompido ou ilegível" }); }
    }
    return saida;
  }

  function contrato() {
    return {
      numero: $("#numero").value, cnpj: $("#cnpj").value, razao_social: $("#razao_social").value, uf: $("#uf").value,
      municipio: $("#municipio").value, fiscal: $("#fiscal").value, competencia: $("#competencia").value, orgao: $("#orgao").value,
      dias_alerta: Number($("#dias_alerta").value || 15), observacoes: $("#observacoes").value, exigidas: marcados(),
      aceitar_sicaf: $("#aceitar_sicaf").checked,
    };
  }

  async function conferir(uploadPdf) {
    const btn = $("#btn-conferir"), original = btn.innerHTML;
    const arquivos = uploadPdf.arquivos.slice();
    if (arquivos.length > MAX_ARQ) { mostrarErros("#erros-conferir", "#erros-lista", ["Envie no máximo " + MAX_ARQ + " arquivos por vez."]); return; }
    btn.disabled = true;
    try {
      const textos = await lerPdfs(arquivos, (i, t) => { btn.innerHTML = '<span class="giro" aria-hidden="true"></span>Lendo ' + i + " de " + t + "…"; });
      const r = chamar("conferir", JSON.stringify({ contrato: contrato(), arquivos: textos, hoje: hojeISO() }));
      if (!r.ok) { mostrarErros("#erros-conferir", "#erros-lista", r.erros); return; }
      mostrarErros("#erros-conferir", "#erros-lista", []);
      ultimo = r; desenharResultado(r); location.hash = "#resultado"; mostrar(); window.scrollTo(0, 0);
    } catch (e) {
      mostrarErros("#erros-conferir", "#erros-lista", ["Não foi possível concluir a conferência. Recarregue a página e tente de novo."]);
      console.error(e);
    } finally { btn.disabled = false; btn.innerHTML = original; }
  }

  // ------------------------------------------------------------------ resultado
  function tag(sem, rot) { return '<span class="br-tag ' + CLASSE[sem] + ' status-tag"><i class="fas ' + ICONE[sem] + '" aria-hidden="true"></i><span>' + esc(rot) + "</span></span>"; }
  function mensagem(tipo, titulo, corpo, icone) {
    return '<div class="br-message ' + tipo + '" role="' + (tipo === "danger" ? "alert" : "status") + '"><div class="icon"><i class="fas ' + icone +
      ' fa-lg" aria-hidden="true"></i></div><div class="content"><span class="message-title">' + esc(titulo) + '</span><span class="message-body"> ' + esc(corpo) + "</span></div></div>";
  }
  function desenharResultado(r) {
    const c = r.contrato;
    $("#res-contrato").innerHTML = "Contrato <strong>" + esc(c.numero) + "</strong> · " + esc(c.razao_social) + " · CNPJ " + esc(c.cnpj);
    $("#res-sede").textContent = "Sede: " + c.municipio + "/" + c.uf + (c.competencia ? " · Competência " + c.competencia : "") + " · Referência " + r.data_referencia;
    $("#res-situacao").innerHTML = r.apto
      ? mensagem("success", "Nenhuma pendência impeditiva.", "Confira os itens em atenção e a autenticidade de cada certidão antes de atestar. O PDF traz a minuta de atesto.", "fa-check-circle")
      : mensagem("danger", "Há pendências.", "O PDF traz a minuta de notificação à contratada, com as pendências listadas.", "fa-times-circle");
    const s = r.resumo;
    const cartao = (cls, n, ic, rot) => '<div class="col-6 col-md-3 mb-2"><div class="br-card cartao ' + cls + '"><div class="card-content"><span class="num">' + n +
      '</span><span class="rot"><i class="fas ' + ic + '" aria-hidden="true"></i> ' + rot + "</span></div></div></div>";
    $("#res-resumo").innerHTML = cartao("success", s.verde, "fa-check-circle", "OK") + cartao("warning", s.amarelo, "fa-exclamation-triangle", "Atenção") +
      cartao("danger", s.vermelho, "fa-times-circle", "Pendente") + cartao("", s.extras, "fa-folder-open", "Outros documentos");
    $("#res-itens").innerHTML = r.itens.map((i) => "<tr><td data-th=\"Resultado\">" + tag(i.semaforo, i.resultado) + '</td><td data-th="Certidão" class="text-medium">' + esc(i.rotulo) +
      '</td><td data-th="Situação">' + esc(i.situacao) + '</td><td data-th="Validade" class="text-nowrap">' + esc(i.validade) + '</td><td data-th="Observação">' + esc(i.mensagem) +
      '</td><td data-th="Arquivo" class="arquivo">' + esc(i.arquivo) + "</td></tr>").join("");
    $("#res-extras").innerHTML = r.extras.length ? '<h2 class="h4 mt-5">Outros documentos enviados</h2>' + r.extras.map((x) =>
      mensagem(x.alerta ? "danger" : "info", x.arquivo + " (" + x.rotulo + ").", x.nota, x.alerta ? "fa-exclamation-triangle" : "fa-file-alt")).join("") : "";
    $("#res-solicitacao").innerHTML = r.solicitacao ? '<h2 class="h4 mt-5">Pedir as certidões à contratada</h2><div class="solicitacao">' +
      '<p class="text-down-01 mb-1">Assunto: <span class="copiavel" id="sol-assunto">' + esc(r.solicitacao.assunto) + "</span></p>" +
      '<pre class="texto-minuta" id="sol-texto">' + esc(r.solicitacao.texto) + "</pre>" +
      '<div class="d-flex flex-wrap mt-2"><button class="br-button primary small mr-2 mb-2" type="button" data-copiar="sol-texto"><i class="fas fa-copy" aria-hidden="true"></i>Copiar texto</button>' +
      '<button class="br-button secondary small mb-2" type="button" data-copiar="sol-assunto"><i class="fas fa-copy" aria-hidden="true"></i>Copiar assunto</button></div></div>' : "";
    $("#res-minuta-titulo").textContent = r.minuta.titulo;
    $("#res-minuta").textContent = r.minuta.titulo + "\n\n" + r.minuta.paragrafos.join("\n\n");
    $("#res-detalhes").innerHTML = r.certidoes.map((ct) => '<details class="detalhe"><summary><span class="title">' + esc(ct.arquivo) + " — " + esc(ct.rotulo) +
      '</span><span class="ml-auto text-down-01">' + esc(ct.metodo) + " · confiança " + ct.confianca + '%</span></summary><div class="content"><dl class="campos">' +
      [["Situação", ct.situacao], ["CNPJ", ct.cnpj || "não encontrado"], ["Razão social", ct.razao_social], ["Órgão emissor", ct.orgao_emissor], ["UF / município", ct.uf_municipio],
       ["Emissão", ct.emissao || "—"], ["Validade", ct.validade || "—"], ["Código de controle", ct.codigo_controle || "—"]]
        .filter((p) => p[1]).map((p) => "<dt>" + esc(p[0]) + "</dt><dd>" + esc(p[1]) + "</dd>").join("") + "</dl>" +
      (ct.url_verificacao ? '<a class="br-button secondary small" href="' + esc(ct.url_verificacao) + '" target="_blank" rel="noopener"><i class="fas fa-external-link-alt" aria-hidden="true"></i>Conferir autenticidade no site do emissor</a>' : "") +
      ct.avisos.map((a) => '<span class="feedback warning d-flex mt-2" role="status"><i class="fas fa-exclamation-triangle" aria-hidden="true"></i>' + esc(a) + "</span>").join("") +
      "</div></details>").join("");
    $("#res-csv").textContent = r.csv;
    atualizarDownloads();
  }

  // ------------------------------------------------------------------ downloads (capacidade do visualizador)
  function atualizarDownloads() {
    const tem = !!downloads;
    $("#btn-pdf").hidden = !tem; $("#btn-csv").hidden = !tem; $("#csv-manual").hidden = tem;
    const aviso = $("#aviso-download");
    aviso.hidden = tem;
    if (!tem) aviso.innerHTML = '<i class="fas fa-info-circle mr-1" aria-hidden="true"></i>Para baixar o PDF e a planilha, abra esta página no claude.ai. Aqui você pode copiar a minuta e a planilha.';
  }
  async function salvar(nome, dados, botao) {
    const aviso = $("#aviso-download");
    try {
      await downloads.save({ filename: nome, data: dados });
      aviso.hidden = true;
    } catch (e) {
      const cod = e && e.code;
      if (cod === "declined") return;
      aviso.hidden = false; aviso.className = "feedback warning d-flex text-down-01";
      aviso.innerHTML = '<i class="fas fa-exclamation-triangle mr-1" aria-hidden="true"></i>' +
        (cod === "rate_limited" ? "Já há um download aguardando confirmação. Conclua-o e tente de novo." : "Não foi possível baixar aqui. Copie a minuta e a planilha nesta página.");
      if (cod !== "rate_limited") { downloads = null; atualizarDownloads(); }
    }
  }

  // ------------------------------------------------------------------ planejamento do mês
  function chaveFeito(g, i, ate) { return "certidoes-feito|" + g.cnpj + "|" + g.contrato + "|" + i.tipo + "|" + ate; }
  function lerFeito(k) { try { return localStorage.getItem(k) === "1"; } catch (e) { return false; } }
  function gravarFeito(k, v) { try { if (v) localStorage.setItem(k, "1"); else localStorage.removeItem(k); } catch (e) { /* só nesta sessão */ } }
  const TAG_PLANO = { sem_validade: ["danger", "fa-times-circle", "sem certidão"], vencida: ["danger", "fa-times-circle", "vencida"],
    pendente: ["danger", "fa-times-circle", "pendente"], vence_antes: ["warning", "fa-exclamation-triangle", "vence antes do corte"],
    valida: ["success", "fa-check-circle", "válida"], reconferir: ["warning", "fa-search", "reconferir"] };

  function desenharPlano(p) {
    const t = p.totais, alvo = $("#plano");
    const cart = (cls, n, ic, rot) => '<div class="br-card cartao ' + cls + '"><div class="card-content"><span class="num">' + n + '</span><span class="rot"><i class="fas ' + ic + '" aria-hidden="true"></i> ' + rot + "</span></div></div>";
    const total = t.a_emitir + t.via_sicaf + t.a_reconferir;
    let h = '<div class="d-flex flex-wrap align-items-start justify-content-between"><h2 class="h3 mt-0 mb-2" id="t-plano">Plano até ' + esc(p.ate) + '</h2><div class="d-flex flex-wrap acoes">' +
      (downloads ? '<button class="br-button primary mr-2 mb-2" type="button" id="btn-plano-csv"><i class="fas fa-file-csv" aria-hidden="true"></i>Baixar lista do mutirão (CSV)</button>' : "") +
      '<button class="br-button tertiary mb-2" type="button" id="limpar-feitos"><i class="fas fa-eraser" aria-hidden="true"></i>Limpar marcações</button></div></div>' +
      '<div class="resumo resumo-mutirao mb-3">' + cart("", t.contratadas, "fa-building", "Contratadas") + cart("success", t.ok, "fa-check-circle", "Ainda válidas") +
      cart("danger", t.a_emitir, "fa-file-signature", "A emitir") + cart("warning", t.a_reconferir, "fa-search", "A reconferir") + cart("info", t.via_sicaf, "fa-id-card", "Via SICAF") +
      cart("success destaque", t.captchas_evitados, "fa-unlock", "Captchas evitados") + "</div>" +
      '<p class="text-down-01 mb-3">Captchas evitados = certidões ainda válidas + itens comprovados pelo SICAF. Estimativa de captchas a resolver hoje: <strong>' + t.captchas_a_resolver + "</strong>.</p>" +
      '<div class="progresso mb-4" aria-live="polite"><div class="d-flex justify-content-between text-down-01 mb-half"><span class="text-medium">Progresso do mutirão</span><span id="progresso-texto">0 de ' + total +
      ' feitos</span></div><div class="barra" role="progressbar" aria-label="Progresso do mutirão" aria-valuemin="0" aria-valuemax="' + total + '" aria-valuenow="0" id="progresso-barra"><span></span></div></div>';
    if (total) h += mensagem("warning", "Portais com captcha são acessados por você.", 'O botão "Abrir portal" só abre o site oficial em outra aba. Depois de emitir, confira a autenticidade e envie os PDFs na conferência.', "fa-lock");
    p.grupos.forEach((g, n) => {
      const id = "g" + (n + 1), acoes = g.a_emitir.concat(g.consultar_sicaf, g.reconferir);
      h += '<article class="br-card grupo-mutirao" aria-labelledby="' + id + '-t"><div class="card-header"><div class="d-flex flex-wrap align-items-start justify-content-between"><div class="grupo-id">' +
        '<h3 class="h5 mt-0 mb-1" id="' + id + '-t">' + esc(g.razao_social || "Contratada sem razão social") + '</h3><p class="text-down-01 mb-1">Contrato <strong>' + esc(g.contrato || "—") + "</strong>" +
        (g.municipio_sede ? " · Sede " + esc(g.municipio_sede) + "/" + esc(g.uf_sede) : "") + '</p><div class="d-flex flex-wrap align-items-center"><span class="text-down-01 text-medium mr-1">CNPJ</span><span class="br-tag mr-1 copiavel" id="' + id +
        '-cnpj">' + esc(g.cnpj_formatado) + '</span><button class="br-button small secondary" type="button" data-copiar="' + id + '-cnpj"><i class="fas fa-copy" aria-hidden="true"></i>Copiar</button></div></div><div class="grupo-contagem text-down-01">' +
        (g.a_emitir.length ? '<span class="br-tag danger status-tag mb-1">' + g.a_emitir.length + " a emitir</span>" : "") +
        (g.consultar_sicaf.length ? '<span class="br-tag info status-tag mb-1">' + g.consultar_sicaf.length + " via SICAF</span>" : "") +
        (g.reconferir.length ? '<span class="br-tag warning status-tag mb-1">' + g.reconferir.length + " a reconferir</span>" : "") +
        (!acoes.length ? '<span class="br-tag success status-tag mb-1"><i class="fas fa-check-circle" aria-hidden="true"></i>em dia</span>' : "") + '</div></div></div><div class="card-content">';
      if (acoes.length) {
        h += '<div class="br-list lista-plano" role="list">' + acoes.map((i) => {
          const tg = TAG_PLANO[i.situacao_plano] || TAG_PLANO.pendente, cid = id + "-" + i.tipo, k = chaveFeito(g, i, p.ate_iso);
          const sicaf = i.acao === "consultar SICAF";
          return '<div class="br-item item-plano' + (lerFeito(k) ? " feito" : "") + '" role="listitem"><div class="br-checkbox item-feito"><input id="' + cid + '" type="checkbox" class="feito" data-chave="' + esc(k) + '"' +
            (lerFeito(k) ? " checked" : "") + '><label for="' + cid + '">Feito<span class="sr-only"> — ' + esc(i.rotulo) + '</span></label></div><div class="item-info"><div class="item-nome">' + esc(i.rotulo) +
            '</div><div class="mt-half"><span class="br-tag ' + tg[0] + ' small status-tag"><i class="fas ' + tg[1] + '" aria-hidden="true"></i><span>' + tg[2] + "</span></span>" +
            (sicaf ? '<span class="br-tag info small status-tag"><i class="fas fa-id-card" aria-hidden="true"></i><span>consultar SICAF</span></span>' : "") +
            '</div><div class="text-down-01 mt-half">Validade registrada: <strong>' + esc(i.validade_txt || "—") + "</strong> · " + esc(i.motivo) + '</div></div><div class="item-portais">' +
            (i.portais.length ? i.portais.map((pt, j) => '<div class="portal-linha">' + (i.portais.length > 1 ? '<div class="portal-obs">' + esc(pt.nome) + "</div>" : "") +
              (pt.url ? '<a class="br-button secondary small" href="' + esc(pt.url) + '" target="_blank" rel="noopener"><i class="fas fa-external-link-alt" aria-hidden="true"></i>' + (sicaf ? "Abrir SICAF" : "Abrir portal") +
                (i.portais.length > 1 ? " " + (j + 1) : "") + '<span class="sr-only"> — ' + esc(pt.nome) + " (abre em nova aba)</span></a>" : '<span class="text-down-01">' + esc(pt.nome) + "</span>") +
              (pt.captcha === true ? '<span class="br-tag warning small"><i class="fas fa-lock" aria-hidden="true"></i> com captcha</span>' : pt.captcha === false ? '<span class="br-tag small">sem captcha</span>' : "") +
              (pt.url_verificacao ? '<a class="br-button tertiary small" href="' + esc(pt.url_verificacao) + '" target="_blank" rel="noopener"><i class="fas fa-shield-alt" aria-hidden="true"></i>Verificar autenticidade</a>' : "") + "</div>").join("")
              : '<span class="text-down-01">Portal não catalogado: use o site do emissor.</span>') + "</div></div>";
        }).join("") + "</div>";
      } else h += '<p class="mb-0"><i class="fas fa-check-circle text-success mr-1" aria-hidden="true"></i>Nada a emitir até ' + esc(p.ate) + ".</p>";
      if (g.ok.length) h += '<details class="detalhe validas mt-2"><summary><span class="title">' + g.ok.length + (g.ok.length === 1 ? " certidão ainda válida" : " certidões ainda válidas") +
        ' na data de corte</span></summary><div class="content"><ul class="lista-validas">' + g.ok.map((i) => '<li><span class="br-tag success small status-tag"><i class="fas fa-check-circle" aria-hidden="true"></i><span>válida</span></span> ' +
        esc(i.rotulo) + " — até " + esc(i.validade_txt) + (i.via_sicaf ? " (SICAF)" : "") + "</li>").join("") + "</ul></div></details>";
      h += "</div>";
      if (g.a_emitir.length) h += '<div class="card-footer"><p class="text-down-01 mb-1">Assunto: <span class="copiavel" id="' + id + '-assunto">' + esc(g.assunto) + '</span></p><div class="d-flex flex-wrap">' +
        '<button class="br-button primary small mr-2 mb-2" type="button" data-copiar="' + id + '-texto"><i class="fas fa-copy" aria-hidden="true"></i>Copiar texto de solicitação à contratada</button>' +
        '<button class="br-button secondary small mb-2" type="button" data-copiar="' + id + '-assunto"><i class="fas fa-copy" aria-hidden="true"></i>Copiar assunto</button></div>' +
        '<details class="detalhe texto-solicitacao"><summary><span class="title">Ver o texto (minuta)</span></summary><div class="content"><pre class="texto-minuta" id="' + id + '-texto">' + esc(g.solicitacao) + "</pre></div></details></div>";
      h += "</article>";
    });
    h += '<p class="text-down-01 mt-4">As marcações de "feito" ficam só neste navegador. O plano é um apoio: a conferência das certidões e o atesto continuam sendo feitos pelo fiscal.</p>';
    alvo.innerHTML = h; alvo.hidden = false;
    const progresso = () => {
      const caixas = $$("input.feito", alvo), feitos = caixas.filter((c) => c.checked).length;
      $("#progresso-texto").textContent = feitos + " de " + caixas.length + " feitos";
      const barra = $("#progresso-barra"); barra.setAttribute("aria-valuenow", feitos);
      barra.firstElementChild.style.width = caixas.length ? (100 * feitos / caixas.length) + "%" : "0";
      barra.classList.toggle("completo", caixas.length > 0 && feitos === caixas.length);
    };
    $$("input.feito", alvo).forEach((c) => c.addEventListener("change", () => { gravarFeito(c.dataset.chave, c.checked); c.closest(".item-plano").classList.toggle("feito", c.checked); progresso(); }));
    $("#limpar-feitos").addEventListener("click", () => { $$("input.feito", alvo).forEach((c) => { c.checked = false; gravarFeito(c.dataset.chave, false); c.closest(".item-plano").classList.remove("feito"); }); progresso(); });
    const b = $("#btn-plano-csv");
    if (b) b.addEventListener("click", () => salvar("mutirao_" + p.ate_iso + ".csv", "﻿" + p.csv));
    progresso();
    alvo.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  async function planejar(uploadCsv, extras) {
    const textos = await Promise.all(uploadCsv.arquivos.map((f) => f.text()));
    const p = chamar("planejar_mes", JSON.stringify({ csvs: textos.concat(extras || []), ate: $("#ate").value, orgao: $("#orgao_plano").value,
      prazo: Number($("#prazo").value || 5), aceitar_sicaf: $("#aceitar_sicaf_plano").checked, hoje: hojeISO() }));
    if (!p.ok) { mostrarErros("#erros-planejar", "#erros-planejar-lista", p.erros); $("#plano").hidden = true; return; }
    mostrarErros("#erros-planejar", "#erros-planejar-lista", []);
    desenharPlano(p);
  }

  // ------------------------------------------------------------------ exemplo
  async function exemplo(uploadPdf) {
    const pares = { numero: "045/2026", cnpj: "12345678000195", razao_social: "EMPRESA EXEMPLO DE SERVIÇOS LTDA", municipio: "São Paulo",
      fiscal: "Fiscal de Exemplo", competencia: "", orgao: "Órgão de Exemplo" };
    for (const [k, v] of Object.entries(pares)) if (!$("#" + k).value || k === "cnpj" || k === "razao_social") $("#" + k).value = v;
    $("#uf").value = "SP"; atualizarCnpj(); desenharPortais();
    uploadPdf.limpar();
    const arquivos = await Promise.all(EXEMPLOS.map(async (n) => new File([await (await fetch("exemplos/" + n + ".pdf")).blob()], n + ".pdf", { type: "application/pdf" })));
    uploadPdf.adicionar(arquivos);
    await conferir(uploadPdf);
  }

  // ------------------------------------------------------------------ início
  function iniciar() {
    $("#uf").innerHTML = UFS.map((u) => '<option value="' + u + '"' + (u === "DF" ? " selected" : "") + ">" + u + "</option>").join("");
    $("#exigidas").innerHTML = TIPOS.map(([v, r]) => '<div class="br-checkbox mr-4 mb-2"><input id="exig-' + v + '" type="checkbox" value="' + v + '"' +
      (PADRAO.has(v) ? " checked" : "") + '><label for="exig-' + v + '">' + esc(r) + "</label></div>").join("");
    const d = new Date(); d.setDate(1); d.setMonth(d.getMonth() - 1);
    $("#competencia").value = String(d.getMonth() + 1).padStart(2, "0") + "/" + d.getFullYear();
    $("#cnpj").addEventListener("input", atualizarCnpj);
    ["#uf", "#aceitar_sicaf"].forEach((s) => $(s).addEventListener("change", agendarPortais));
    $("#municipio").addEventListener("input", agendarPortais);
    $("#exigidas").addEventListener("change", agendarPortais);
    pdfjsLib.GlobalWorkerOptions.workerSrc = "vendor/pdf.worker.min.js";

    const uploadPdf = montarUpload($("#upload"), $("#arquivos"), $("#upload-lista"), (f) => /\.pdf$/i.test(f.name) || f.type === "application/pdf");
    const uploadCsv = montarUpload($("#upload-csv"), $("#csvs"), $("#csvs-lista"), (f) => /\.csv$/i.test(f.name) || f.type === "text/csv");
    $("#form-conferir").addEventListener("submit", (e) => { e.preventDefault(); if (nav) conferir(uploadPdf); });
    $("#form-planejar").addEventListener("submit", (e) => { e.preventDefault(); if (nav) planejar(uploadCsv); });
    $("#btn-exemplo").addEventListener("click", () => exemplo(uploadPdf));
    $("#btn-exemplo-csv").addEventListener("click", async () => {
      const t = await (await fetch("exemplos/controle_exemplo.csv")).text(); planejar(uploadCsv, [t]);
    });
    $("#btn-pdf").addEventListener("click", () => { if (ultimo) salvar(ultimo.nome_base + ".pdf", PdfAtesto.gerar(ultimo)); });
    $("#btn-csv").addEventListener("click", () => { if (ultimo) salvar(ultimo.nome_base + ".csv", "﻿" + ultimo.csv); });
    mostrar();

    if (window.claude && typeof window.claude.use === "function") {
      window.claude.use("downloads").then((dl) => { downloads = dl; if (ultimo) atualizarDownloads(); }).catch(() => { downloads = null; });
    }

    const t0 = performance.now();
    prepararPython().then((m) => {
      nav = m;
      $("#ate").value = String(nav.data_corte_padrao(hojeISO()) || "");
      ["#btn-conferir", "#btn-exemplo", "#btn-planejar", "#btn-exemplo-csv"].forEach((s) => ($(s).disabled = false));
      $("#preparo").hidden = true;
      desenharPortais();
      console.info("Verificador pronto em " + Math.round(performance.now() - t0) + " ms");
    }).catch((e) => {
      console.error(e);
      $("#preparo").className = "br-message danger";
      $("#preparo").innerHTML = '<div class="icon"><i class="fas fa-times-circle fa-lg" aria-hidden="true"></i></div><div class="content"><span class="message-title">Não foi possível preparar o verificador.</span>' +
        '<span class="message-body"> Recarregue a página. Se continuar, use um navegador atualizado (Chrome, Edge ou Firefox).</span></div>';
    });
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", iniciar); else iniciar();
})();
