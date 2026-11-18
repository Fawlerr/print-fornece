/*
 * Chat de WhatsApp do Print Fornece.
 * - Tempo real por polling leve: mensagens novas a cada 3 s (só com a aba visível) e lista a cada 10 s.
 * - Todo texto vindo do cliente entra no DOM por textContent (nunca innerHTML).
 * - Celular: lista e conversa em telas separadas, botão voltar integrado ao histórico do navegador.
 */
(function () {
  "use strict";

  const raiz = document.getElementById("wa");
  if (!raiz) return;

  const dadosIniciais = JSON.parse(document.getElementById("chat-dados").textContent);
  const API = raiz.dataset.urlBase;
  const POLL_MSG = 3000;
  const POLL_LISTA = 10000;
  const TITULO = document.title;

  const estado = {
    perfis: dadosIniciais.perfis || [],
    conversas: dadosIniciais.conversas || [],
    contadores: dadosIniciais.contadores || {},
    etiquetas: dadosIniciais.etiquetas || [],
    filtro: "",
    busca: "",
    etiqueta: "",
    perfil: null,
    aberta: null,
    conversa: null,
    ultimoId: 0,
    primeiroId: 0,
    mensagens: new Map(),
    anexo: null,
    pollMsg: null,
    pollLista: null,
    carregando: false,
    mensagemApagar: null,
  };

  const $ = (sel) => document.querySelector(sel);
  const el = {
    perfis: $("#wa-perfis"),
    lista: $("#wa-conversas"),
    busca: $("#wa-busca-input"),
    filtros: $("#wa-filtros"),
    filtrosToggle: $("#wa-filtros-toggle"),
    etiquetaFiltro: $("#wa-etiqueta-filtro"),
    vazio: $("#wa-vazio"),
    topo: $("#wa-topo"),
    topoNome: $("#wa-topo-nome"),
    topoTel: $("#wa-topo-telefone"),
    topoAvatar: $("#wa-topo-avatar"),
    caixa: $("#wa-mensagens"),
    listaMsg: $("#wa-lista-mensagens"),
    anteriores: $("#wa-anteriores"),
    composer: $("#wa-composer"),
    texto: $("#wa-texto"),
    enviar: $("#wa-enviar"),
    arquivo: $("#wa-arquivo"),
    anexoPrevia: $("#wa-anexo-previa"),
    anexoNome: $("#wa-anexo-nome"),
    anexoImg: $("#wa-anexo-img"),
    comoDocumento: $("#wa-como-documento"),
    painel: $("#wa-painel"),
    painelCorpo: $("#wa-painel-corpo"),
    arquivar: $("#wa-arquivar"),
    dlgApagar: $("#wa-dialogo-apagar"),
    dlgNova: $("#wa-dialogo-nova"),
  };

  // ------------------------------------------------------------------ util
  function cookie(nome) {
    const m = document.cookie.match(new RegExp("(?:^|; )" + nome + "=([^;]*)"));
    return m ? decodeURIComponent(m[1]) : "";
  }

  async function api(caminho, opcoes = {}) {
    const init = { credentials: "same-origin", headers: { "X-Requested-With": "fetch" }, ...opcoes };
    if (init.method && init.method !== "GET") {
      init.headers["X-CSRFToken"] = cookie("csrftoken") || (document.querySelector("input[name=csrfmiddlewaretoken]") || {}).value || "";
      if (init.json !== undefined) {
        init.headers["Content-Type"] = "application/json";
        init.body = JSON.stringify(init.json);
        delete init.json;
      }
    }
    const resp = await fetch(caminho.startsWith("/") ? caminho : API + caminho, init);
    let dados = {};
    try { dados = await resp.json(); } catch (e) { dados = {}; }
    if (!resp.ok || dados.ok === false) {
      const erro = new Error(dados.erro || (resp.status === 403 ? "Sem permissão." : "Falha de comunicação. Tente de novo."));
      erro.status = resp.status;
      throw erro;
    }
    return dados;
  }

  function criar(tag, attrs = {}, filhos = []) {
    const n = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs)) {
      if (v === null || v === undefined || v === false) continue;
      if (k === "class") n.className = v;
      else if (k === "text") n.textContent = v;
      else if (k === "dataset") Object.assign(n.dataset, v);
      else if (k.startsWith("on")) n.addEventListener(k.slice(2), v);
      else n.setAttribute(k, v === true ? "" : v);
    }
    for (const f of [].concat(filhos)) if (f) n.append(f);
    return n;
  }

  function icone(classes) {
    return criar("i", { class: classes, "aria-hidden": "true" });
  }

  function aviso(texto, tipo = "error") {
    const cont = document.querySelector(".flash-messages") || (() => {
      const c = criar("div", { class: "flash-messages", "aria-live": "polite" });
      document.querySelector("#page-content").prepend(c);
      return c;
    })();
    const t = criar("div", { class: `toast toast-${tipo}`, role: tipo === "error" ? "alert" : "status", text: texto });
    cont.append(t);
    setTimeout(() => t.remove(), 6000);
  }

  const URL_RE = /(https?:\/\/[^\s<>"']+)/g;
  function textoComLinks(texto) {
    const frag = document.createDocumentFragment();
    let ultimo = 0;
    for (const m of texto.matchAll(URL_RE)) {
      if (m.index > ultimo) frag.append(document.createTextNode(texto.slice(ultimo, m.index)));
      frag.append(criar("a", { href: m[0], target: "_blank", rel: "noopener noreferrer", text: m[0] }));
      ultimo = m.index + m[0].length;
    }
    if (ultimo < texto.length) frag.append(document.createTextNode(texto.slice(ultimo)));
    return frag;
  }

  function ehCelular() {
    return window.matchMedia("(max-width: 767px)").matches;
  }

  // ---------------------------------------------------------------- telas
  function mostrarTela(tela) {
    raiz.dataset.tela = tela;
    document.body.classList.toggle("chat-conversa-aberta", tela !== "lista");
  }

  function ajustarViewport() {
    const vv = window.visualViewport;
    const altura = vv ? vv.height : window.innerHeight;
    document.documentElement.style.setProperty("--wa-vh", `${altura}px`);
    document.documentElement.style.setProperty("--wa-vv-top", `${vv ? vv.offsetTop : 0}px`);
  }
  ajustarViewport();
  if (window.visualViewport) {
    window.visualViewport.addEventListener("resize", ajustarViewport);
    window.visualViewport.addEventListener("scroll", ajustarViewport);
  }
  window.addEventListener("resize", ajustarViewport);

  // --------------------------------------------------------------- perfis
  function renderPerfis() {
    el.perfis.replaceChildren();
    el.perfis.hidden = estado.perfis.length <= 1;
    for (const p of estado.perfis) {
      const botao = criar("button", {
        type: "button", role: "tab", class: "wa-perfil" + (p.ativo ? " is-ativo" : ""),
        "aria-selected": p.ativo ? "true" : "false", title: p.nome,
        onclick: () => { estado.perfil = String(p.id); carregarLista(); },
      }, [
        criar("span", { class: "wa-perfil-avatar", style: p.cor ? `--perfil-cor:${p.cor}` : null },
          p.id === "todas" ? [icone("fa-solid fa-layer-group")] : [document.createTextNode(p.iniciais)]),
        criar("span", { class: "wa-perfil-nome", text: p.nome }),
        p.nao_lidas ? criar("span", { class: "wa-badge", text: String(p.nao_lidas), "aria-label": `${p.nao_lidas} não lidas` }) : null,
        p.estado && p.estado !== "open" ? criar("span", { class: "wa-perfil-off", title: "Desconectado", "aria-label": "desconectado" }) : null,
      ]);
      el.perfis.append(botao);
    }
  }

  // ---------------------------------------------------------------- lista
  function renderLista() {
    el.lista.replaceChildren();
    for (const [chave, valor] of Object.entries(estado.contadores)) {
      const alvo = document.querySelector(`[data-contador="${chave}"]`);
      if (alvo) alvo.textContent = valor ? `(${valor})` : "";
    }
    if (!estado.conversas.length) {
      el.lista.append(criar("li", { class: "wa-lista-vazia", text: dadosIniciais.tem_instancia ? "Nenhuma conversa encontrada." : "Nenhum número de WhatsApp disponível para você. Fale com o administrador." }));
      return;
    }
    let totalNaoLidas = 0;
    for (const c of estado.conversas) {
      totalNaoLidas += c.nao_lidas;
      const item = criar("li", {}, [
        criar("button", {
          type: "button", class: "wa-item" + (c.id === estado.aberta ? " is-aberta" : "") + (c.nao_lidas ? " is-nao-lida" : ""),
          "aria-current": c.id === estado.aberta ? "true" : null,
          onclick: () => abrirConversa(c.id, true),
        }, [
          criar("span", { class: "wa-avatar", style: `--avatar-cor:${c.instancia.cor}`, text: c.iniciais, "aria-hidden": "true" }),
          criar("span", { class: "wa-item-corpo" }, [
            criar("span", { class: "wa-item-linha" }, [
              criar("strong", { class: "wa-item-nome", text: c.nome }),
              criar("span", { class: "wa-item-hora", text: c.hora }),
            ]),
            criar("span", { class: "wa-item-linha" }, [
              criar("span", { class: "wa-item-previa" }, [
                c.direcao === "out" ? icone("fa-solid fa-reply wa-item-dir") : null,
                document.createTextNode(c.previa || "Sem mensagens"),
              ]),
              c.nao_lidas ? criar("span", { class: "wa-badge", text: String(c.nao_lidas), "aria-label": `${c.nao_lidas} não lidas` }) : null,
            ]),
            (c.etiquetas.length || estado.perfis.length > 1) ? criar("span", { class: "wa-item-tags" }, [
              estado.perfis.length > 1 ? criar("span", { class: "wa-tag wa-tag--instancia", style: `--tag-cor:${c.instancia.cor}`, text: c.instancia.nome }) : null,
              ...c.etiquetas.map((e) => criar("span", { class: "wa-tag", style: `--tag-cor:${e.cor}`, text: e.nome })),
            ]) : null,
          ]),
        ]),
      ]);
      el.lista.append(item);
    }
    document.title = totalNaoLidas ? `(${totalNaoLidas}) ${TITULO}` : TITULO;
  }

  async function carregarLista() {
    const params = new URLSearchParams();
    if (estado.perfil) params.set("perfil", estado.perfil);
    if (estado.filtro) params.set("filtro", estado.filtro);
    if (estado.busca) params.set("q", estado.busca);
    if (estado.etiqueta) params.set("etiqueta", estado.etiqueta);
    try {
      const dados = await api("conversas/?" + params.toString());
      estado.perfis = dados.perfis;
      estado.conversas = dados.conversas;
      estado.contadores = dados.contadores;
      estado.perfil = null;
      renderPerfis();
      renderLista();
    } catch (e) {
      /* silencioso no polling */
    }
  }

  // ------------------------------------------------------------ mensagens
  const ROTULO_STATUS = { pendente: "Enviando", enviada: "Enviada", entregue: "Entregue", lida: "Lida", falhou: "Falhou" };

  function iconeStatus(status) {
    const mapa = {
      pendente: "fa-regular fa-clock",
      enviada: "fa-solid fa-check",
      entregue: "fa-solid fa-check-double",
      lida: "fa-solid fa-check-double wa-lida",
      falhou: "fa-solid fa-circle-exclamation wa-falhou",
    };
    return criar("span", { class: "wa-status", title: ROTULO_STATUS[status] || status }, [
      icone(mapa[status] || "fa-solid fa-check"),
      criar("span", { class: "visually-hidden", text: ROTULO_STATUS[status] || status }),
    ]);
  }

  function conteudoMidia(m) {
    if (!m.midia) return null;
    if (m.tipo === "imagem" || m.tipo === "figurinha") {
      return criar("a", { href: m.midia, target: "_blank", rel: "noopener", class: "wa-midia-link" }, [
        criar("img", { src: m.midia, alt: m.texto || (m.tipo === "figurinha" ? "Figurinha" : "Imagem"), loading: "lazy", class: m.tipo === "figurinha" ? "wa-figurinha" : "wa-imagem" }),
      ]);
    }
    if (m.tipo === "audio") return criar("audio", { controls: true, preload: "none", src: m.midia, class: "wa-audio" });
    if (m.tipo === "video") return criar("video", { controls: true, preload: "none", src: m.midia, class: "wa-video", playsinline: true });
    return criar("a", { href: m.midia, class: "wa-documento", target: "_blank", rel: "noopener" }, [
      icone("fa-solid fa-file-lines"),
      criar("span", { text: m.arquivo_nome || "Documento" }),
      icone("fa-solid fa-download"),
    ]);
  }

  function balao(m) {
    const enviada = m.direcao === "out";
    const partes = [];
    if (m.revogada) {
      partes.push(criar("p", { class: "wa-apagada" }, [icone("fa-solid fa-ban"), document.createTextNode(" Mensagem apagada")]));
    } else {
      if (enviada && (m.origem !== "chat" || m.remetente)) {
        const rotulo = m.origem === "automatica" ? `Automática${m.pedido ? " · pedido #" + m.pedido : ""}` : m.origem === "celular" ? "Fora do sistema (celular ou Umbler)" : m.remetente;
        partes.push(criar("span", { class: "wa-autor", text: rotulo + (m.origem === "automatica" && m.remetente ? ` · ${m.remetente}` : "") }));
      }
      const midia = conteudoMidia(m);
      if (midia) partes.push(midia);
      if (m.texto) partes.push(criar("p", { class: "wa-texto" }, [textoComLinks(m.texto)]));
    }
    const rodape = criar("span", { class: "wa-rodape" }, [criar("time", { text: m.hora }), enviada ? iconeStatus(m.status) : null]);
    partes.push(rodape);
    if (m.status === "falhou" && !m.revogada) {
      partes.push(criar("p", { class: "wa-erro" }, [
        document.createTextNode(m.erro || "Não enviada."),
        criar("button", { type: "button", class: "wa-link-btn", text: "Reenviar", onclick: () => reenviar(m.id) }),
      ]));
    }
    const podeApagar = m.opcoes && (m.opcoes.para_mim || m.opcoes.para_todos === "sim");
    const acoes = podeApagar ? criar("button", {
      type: "button", class: "wa-menu-btn", "aria-label": "Apagar mensagem", title: "Apagar",
      onclick: () => perguntarApagar(m),
    }, [icone("fa-solid fa-chevron-down")]) : null;
    return criar("li", { class: `wa-msg ${enviada ? "wa-msg--out" : "wa-msg--in"}${m.revogada ? " is-revogada" : ""}`, dataset: { id: String(m.id), dia: m.dia } }, [
      criar("div", { class: "wa-balao" }, [acoes, ...partes]),
    ]);
  }

  function separadorDia(dia) {
    const hoje = new Date();
    const fmt = (d) => `${String(d.getDate()).padStart(2, "0")}/${String(d.getMonth() + 1).padStart(2, "0")}/${d.getFullYear()}`;
    const ontem = new Date(hoje.getTime() - 86400000);
    const rotulo = dia === fmt(hoje) ? "Hoje" : dia === fmt(ontem) ? "Ontem" : dia;
    return criar("li", { class: "wa-dia", dataset: { dia }, "aria-hidden": "false" }, [criar("span", { text: rotulo })]);
  }

  function renderMensagens(lista, { prefixar = false } = {}) {
    const frag = document.createDocumentFragment();
    let diaAnterior = prefixar ? null : (el.listaMsg.lastElementChild ? el.listaMsg.lastElementChild.dataset.dia : null);
    for (const m of lista) {
      if (estado.mensagens.has(m.id)) {
        const antigo = el.listaMsg.querySelector(`[data-id="${m.id}"]`);
        if (antigo) antigo.replaceWith(balao(m));
        estado.mensagens.set(m.id, m);
        continue;
      }
      if (m.dia !== diaAnterior) {
        frag.append(separadorDia(m.dia));
        diaAnterior = m.dia;
      }
      frag.append(balao(m));
      estado.mensagens.set(m.id, m);
      estado.ultimoId = Math.max(estado.ultimoId, m.id);
      estado.primeiroId = estado.primeiroId ? Math.min(estado.primeiroId, m.id) : m.id;
    }
    if (prefixar) {
      const primeiroSep = el.listaMsg.querySelector(".wa-dia");
      el.listaMsg.prepend(frag);
      if (primeiroSep && primeiroSep.previousElementSibling && primeiroSep.previousElementSibling.dataset.dia === primeiroSep.dataset.dia) primeiroSep.remove();
    } else {
      el.listaMsg.append(frag);
    }
  }

  function aplicarEstados(estados) {
    for (const s of estados) {
      const m = estado.mensagens.get(s.id);
      if (!m) continue;
      if (s.ocultada) {
        const no = el.listaMsg.querySelector(`[data-id="${s.id}"]`);
        if (no) no.remove();
        estado.mensagens.delete(s.id);
        continue;
      }
      if (m.status !== s.status || m.revogada !== s.revogada) {
        m.status = s.status;
        if (s.revogada) { m.revogada = true; m.texto = ""; m.midia = ""; m.opcoes = { para_mim: false, para_todos: "nao" }; }
        const no = el.listaMsg.querySelector(`[data-id="${s.id}"]`);
        if (no) no.replaceWith(balao(m));
      }
    }
  }

  function noFinal() {
    return el.caixa.scrollHeight - el.caixa.scrollTop - el.caixa.clientHeight < 120;
  }

  function rolarFinal() {
    el.caixa.scrollTop = el.caixa.scrollHeight;
  }

  function renderTopo(c) {
    el.topoNome.textContent = c.nome;
    el.topoTel.textContent = c.telefone + (estado.perfis.length > 1 ? ` · ${c.instancia.nome}` : "");
    el.topoAvatar.textContent = c.iniciais;
    el.topoAvatar.style.setProperty("--avatar-cor", c.instancia.cor);
    el.arquivar.title = c.arquivada ? "Desarquivar conversa" : "Arquivar conversa";
    el.arquivar.querySelector(".visually-hidden").textContent = el.arquivar.title;
  }

  async function abrirConversa(id, empilhar) {
    if (estado.carregando) return;
    estado.carregando = true;
    pararPollMsg();
    estado.aberta = id;
    estado.mensagens.clear();
    estado.ultimoId = 0;
    estado.primeiroId = 0;
    el.listaMsg.replaceChildren();
    el.vazio.hidden = true;
    el.topo.hidden = false;
    el.caixa.hidden = false;
    el.composer.hidden = false;
    if (window.matchMedia("(min-width: 1280px)").matches) el.painel.hidden = false;
    limparAnexo();
    mostrarTela("conversa");
    if (empilhar) history.pushState({ c: id }, "", `?c=${id}`);
    try {
      const dados = await api(`conversas/${id}/mensagens/`);
      estado.conversa = dados.conversa;
      renderTopo(dados.conversa);
      renderMensagens(dados.mensagens);
      el.anteriores.hidden = !dados.tem_anteriores;
      rolarFinal();
      const item = estado.conversas.find((c) => c.id === id);
      if (item) item.nao_lidas = 0;
      renderLista();
      if (!el.painel.hidden || window.matchMedia("(min-width: 1280px)").matches) carregarPainel();
      if (!ehCelular()) el.texto.focus();
    } catch (e) {
      aviso(e.message);
      if (e.status === 404 || e.status === 403) fecharConversa();
    } finally {
      estado.carregando = false;
      iniciarPollMsg();
    }
  }

  function fecharConversa() {
    pararPollMsg();
    estado.aberta = null;
    estado.conversa = null;
    el.vazio.hidden = false;
    el.topo.hidden = true;
    el.caixa.hidden = true;
    el.composer.hidden = true;
    el.painel.hidden = true;
    mostrarTela("lista");
    renderLista();
  }

  async function buscarNovas() {
    if (!estado.aberta || document.hidden) return;
    const id = estado.aberta;
    try {
      const dados = await api(`conversas/${id}/mensagens/?depois=${estado.ultimoId}`);
      if (estado.aberta !== id) return;
      const estavaNoFinal = noFinal();
      renderMensagens(dados.mensagens);
      aplicarEstados(dados.estados);
      if (dados.mensagens.length && estavaNoFinal) rolarFinal();
    } catch (e) { /* tenta de novo no próximo ciclo */ }
  }

  function iniciarPollMsg() {
    pararPollMsg();
    if (estado.aberta) estado.pollMsg = setInterval(buscarNovas, POLL_MSG);
  }

  function pararPollMsg() {
    if (estado.pollMsg) clearInterval(estado.pollMsg);
    estado.pollMsg = null;
  }

  el.anteriores.addEventListener("click", async () => {
    if (!estado.aberta || !estado.primeiroId) return;
    const alturaAntes = el.caixa.scrollHeight;
    try {
      const dados = await api(`conversas/${estado.aberta}/mensagens/?antes=${estado.primeiroId}&ler=0`);
      renderMensagens(dados.mensagens, { prefixar: true });
      el.anteriores.hidden = dados.mensagens.length < 60;
      el.caixa.scrollTop = el.caixa.scrollHeight - alturaAntes;
    } catch (e) { aviso(e.message); }
  });

  // ----------------------------------------------------------------- envio
  function autoAltura() {
    el.texto.style.height = "auto";
    el.texto.style.height = Math.min(el.texto.scrollHeight, 140) + "px";
  }
  el.texto.addEventListener("input", autoAltura);
  el.texto.addEventListener("keydown", (ev) => {
    const toque = window.matchMedia("(pointer: coarse)").matches;
    if (ev.key === "Enter" && !ev.shiftKey && !toque) {
      ev.preventDefault();
      el.composer.requestSubmit();
    }
  });

  function limparAnexo() {
    estado.anexo = null;
    el.arquivo.value = "";
    el.anexoPrevia.hidden = true;
    el.anexoImg.hidden = true;
    if (el.anexoImg.src) URL.revokeObjectURL(el.anexoImg.src);
    el.anexoImg.removeAttribute("src");
    el.comoDocumento.checked = false;
  }

  el.arquivo.addEventListener("change", () => {
    const f = el.arquivo.files[0];
    if (!f) return;
    if (f.size > dadosIniciais.limite_mb * 1024 * 1024) {
      aviso(`Arquivo maior que ${dadosIniciais.limite_mb} MB.`);
      limparAnexo();
      return;
    }
    estado.anexo = f;
    el.anexoNome.textContent = `${f.name} (${Math.ceil(f.size / 1024)} KB)`;
    el.anexoPrevia.hidden = false;
    if (f.type.startsWith("image/")) {
      el.anexoImg.src = URL.createObjectURL(f);
      el.anexoImg.hidden = false;
    }
    el.texto.placeholder = "Legenda (opcional)";
    el.texto.focus();
  });
  $("#wa-anexo-remover").addEventListener("click", () => { limparAnexo(); el.texto.placeholder = "Mensagem"; });

  el.composer.addEventListener("submit", async (ev) => {
    ev.preventDefault();
    if (!estado.aberta || el.enviar.disabled) return;
    const texto = el.texto.value.trim();
    if (!texto && !estado.anexo) return;
    el.enviar.disabled = true;
    try {
      let dados;
      if (estado.anexo) {
        const fd = new FormData();
        fd.append("arquivo", estado.anexo);
        fd.append("legenda", texto);
        if (el.comoDocumento.checked) fd.append("como_documento", "1");
        dados = await api(`conversas/${estado.aberta}/midia/`, { method: "POST", body: fd });
        limparAnexo();
        el.texto.placeholder = "Mensagem";
      } else {
        dados = await api(`conversas/${estado.aberta}/enviar/`, { method: "POST", json: { texto } });
      }
      el.texto.value = "";
      autoAltura();
      renderMensagens([dados.mensagem]);
      rolarFinal();
      if (dados.mensagem.status === "falhou") aviso(dados.mensagem.erro || "O WhatsApp não aceitou a mensagem.");
      carregarLista();
    } catch (e) {
      aviso(e.message);
    } finally {
      el.enviar.disabled = false;
      if (!ehCelular()) el.texto.focus();
    }
  });

  async function reenviar(id) {
    try {
      const dados = await api(`mensagens/${id}/reenviar/`, { method: "POST" });
      const antigo = el.listaMsg.querySelector(`[data-id="${dados.removida}"]`);
      if (antigo) antigo.remove();
      estado.mensagens.delete(dados.removida);
      renderMensagens([dados.mensagem]);
      rolarFinal();
    } catch (e) { aviso(e.message); }
  }

  // ---------------------------------------------------------------- apagar
  function perguntarApagar(m) {
    estado.mensagemApagar = m;
    const todos = $("#wa-apagar-todos");
    todos.hidden = m.opcoes.para_todos !== "sim";
    $("#wa-apagar-mim").hidden = !m.opcoes.para_mim;
    $("#wa-apagar-motivo").textContent = m.opcoes.para_todos === "sim"
      ? "Apagar para todos remove a mensagem do WhatsApp do cliente. Apagar para mim esconde só no sistema (para toda a equipe)."
      : (m.opcoes.motivo || "A mensagem será escondida no sistema para toda a equipe.");
    el.dlgApagar.showModal();
  }

  el.dlgApagar.addEventListener("close", async () => {
    const escopo = el.dlgApagar.returnValue;
    const m = estado.mensagemApagar;
    estado.mensagemApagar = null;
    if (!escopo || !m) return;
    try {
      const dados = await api(`mensagens/${m.id}/apagar/`, { method: "POST", json: { escopo } });
      if (escopo === "mim") {
        const no = el.listaMsg.querySelector(`[data-id="${m.id}"]`);
        if (no) no.remove();
        estado.mensagens.delete(m.id);
      } else {
        renderMensagens([dados.mensagem]);
      }
      carregarLista();
    } catch (e) { aviso(e.message); }
  });

  // --------------------------------------------------------------- painel
  function dinheiro(v) {
    return "R$ " + Number(v).toLocaleString("pt-BR", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  }

  async function copiar(texto, botao) {
    try { await navigator.clipboard.writeText(texto); } catch (e) { return aviso("Não foi possível copiar."); }
    const original = botao.textContent;
    botao.textContent = "Copiado";
    setTimeout(() => { botao.textContent = original; }, 1500);
  }

  async function carregarPainel() {
    if (!estado.aberta) return;
    const id = estado.aberta;
    el.painelCorpo.replaceChildren(criar("p", { class: "help", text: "Carregando..." }));
    try {
      const d = await api(`conversas/${id}/painel/`);
      if (estado.aberta !== id) return;
      renderPainel(d);
    } catch (e) {
      el.painelCorpo.replaceChildren(criar("p", { class: "form-error", text: e.message }));
    }
  }

  function renderPainel(d) {
    const corpo = [];
    // Cliente
    if (d.cliente) {
      corpo.push(criar("section", { class: "wa-bloco" }, [
        criar("h3", { text: "Cliente" }),
        criar("a", { href: d.cliente.url, class: "wa-cliente-link" }, [icone("fa-solid fa-address-card"), document.createTextNode(" " + d.cliente.nome)]),
        criar("p", { class: "help", text: `${d.telefone} · ${d.instancia}` }),
      ]));
    } else {
      const input = criar("input", { type: "text", maxlength: "200", value: estado.conversa ? estado.conversa.nome : "", "aria-label": "Nome do cliente" });
      corpo.push(criar("section", { class: "wa-bloco" }, [
        criar("h3", { text: "Cliente" }),
        criar("p", { class: "help", text: "Este número não está no cadastro de clientes." }),
        criar("form", {
          class: "wa-form-linha",
          onsubmit: async (ev) => {
            ev.preventDefault();
            try {
              await api(`conversas/${estado.aberta}/cliente/`, { method: "POST", json: { nome: input.value } });
              aviso("Cliente cadastrado.", "success");
              carregarPainel();
              carregarLista();
            } catch (e) { aviso(e.message); }
          },
        }, [input, criar("button", { type: "submit", class: "btn btn-primary btn-small", text: "Cadastrar" })]),
      ]));
    }
    // Etiquetas
    if (estado.etiquetas.length) {
      const selecionadas = new Set(d.etiquetas);
      corpo.push(criar("section", { class: "wa-bloco" }, [
        criar("h3", { text: "Etiquetas" }),
        criar("div", { class: "wa-etiquetas" }, estado.etiquetas.map((e) => criar("label", { class: "wa-etiqueta-opcao", style: `--tag-cor:${e.cor}` }, [
          criar("input", {
            type: "checkbox", value: String(e.id), checked: selecionadas.has(e.id),
            onchange: async () => {
              const ids = [...el.painelCorpo.querySelectorAll(".wa-etiquetas input:checked")].map((i) => i.value);
              try { await api(`conversas/${estado.aberta}/etiquetas/`, { method: "POST", json: { etiquetas: ids } }); carregarLista(); } catch (err) { aviso(err.message); }
            },
          }),
          criar("span", { text: e.nome }),
        ]))),
      ]));
    }
    // Pedidos
    const pedidos = criar("section", { class: "wa-bloco" }, [criar("h3", { text: `Pedidos (${d.pedidos.length})` })]);
    if (!d.pedidos.length) pedidos.append(criar("p", { class: "help", text: "Nenhum pedido deste cliente." }));
    for (const p of d.pedidos) {
      const acoes = criar("div", { class: "wa-pedido-acoes" }, [
        criar("a", { class: "btn btn-secondary btn-small", href: p.url, text: "Abrir pedido" }),
        !p.quitado && Number(p.saldo) > 0 ? criar("a", { class: "btn btn-primary btn-small", href: p.url_link }, [icone("fa-solid fa-credit-card"), document.createTextNode(" Link cartão")]) : null,
      ]);
      const link = p.link_ativo ? criar("div", { class: "wa-link-ativo" }, [
        criar("span", { text: `Link ativo: ${dinheiro(p.link_ativo.valor)}` }),
        criar("button", { type: "button", class: "wa-link-btn", text: "Copiar", onclick: (ev) => copiar(p.link_ativo.url, ev.currentTarget) }),
      ]) : null;
      const anexos = p.anexos.length ? criar("details", { class: "wa-anexos" }, [
        criar("summary", { text: `Arquivos do pedido (${p.anexos.length})` }),
        criar("ul", {}, p.anexos.map((a) => criar("li", {}, [
          criar("span", { text: a.nome }),
          criar("button", {
            type: "button", class: "wa-link-btn", text: "Enviar",
            onclick: async (ev) => {
              const b = ev.currentTarget;
              b.disabled = true;
              try {
                const r = await api(`conversas/${estado.aberta}/anexo-pedido/`, { method: "POST", json: { anexo: a.id } });
                renderMensagens([r.mensagem]);
                rolarFinal();
                if (ehCelular()) fecharPainel();
              } catch (err) { aviso(err.message); } finally { b.disabled = false; }
            },
          }),
        ]))),
      ]) : null;
      pedidos.append(criar("article", { class: "wa-pedido" }, [
        criar("div", { class: "wa-pedido-linha" }, [
          criar("strong", { text: `#${p.numero}` }),
          criar("span", { class: `badge badge-${p.etapa_codigo}`, text: p.etapa }),
        ]),
        criar("dl", { class: "wa-pedido-valores" }, [
          criar("div", {}, [criar("dt", { text: "Total" }), criar("dd", { text: dinheiro(p.total) })]),
          criar("div", {}, [criar("dt", { text: "Pago" }), criar("dd", { text: dinheiro(p.pago) })]),
          criar("div", {}, [criar("dt", { text: "Saldo" }), criar("dd", { class: Number(p.saldo) > 0 ? "wa-saldo" : "", text: dinheiro(p.saldo) })]),
        ]),
        link, acoes, anexos,
      ]));
    }
    corpo.push(pedidos);
    el.painelCorpo.replaceChildren(...corpo);
  }

  function abrirPainel() {
    if (!estado.aberta) return;
    el.painel.hidden = false;
    if (ehCelular()) {
      mostrarTela("painel");
      history.pushState({ c: estado.aberta, painel: true }, "", `?c=${estado.aberta}`);
    }
    carregarPainel();
  }

  function fecharPainel() {
    if (window.matchMedia("(min-width: 1280px)").matches) return;
    el.painel.hidden = true;
    if (ehCelular()) mostrarTela("conversa");
  }

  document.querySelectorAll("[data-abrir-painel]").forEach((b) => b.addEventListener("click", () => {
    if (!el.painel.hidden && !ehCelular() && !window.matchMedia("(min-width: 1280px)").matches) fecharPainel();
    else abrirPainel();
  }));
  document.querySelector("[data-fechar-painel]").addEventListener("click", () => {
    if (ehCelular() && history.state && history.state.painel) history.back();
    else fecharPainel();
  });

  el.arquivar.addEventListener("click", async () => {
    if (!estado.aberta) return;
    try {
      const d = await api(`conversas/${estado.aberta}/arquivar/`, { method: "POST" });
      aviso(d.arquivada ? "Conversa arquivada." : "Conversa desarquivada.", "success");
      if (estado.conversa) estado.conversa.arquivada = d.arquivada;
      carregarLista();
      if (d.arquivada) {
        if (ehCelular()) history.back();
        else fecharConversa();
      }
    } catch (e) { aviso(e.message); }
  });

  // ------------------------------------------------------------- navegação
  document.querySelector("[data-voltar]").addEventListener("click", () => {
    if (history.state && history.state.c) history.back();
    else fecharConversa();
  });

  window.addEventListener("popstate", (ev) => {
    const st = ev.state || {};
    if (st.painel) { abrirPainel(); return; }
    if (st.c) {
      el.painel.hidden = !window.matchMedia("(min-width: 1280px)").matches;
      if (st.c !== estado.aberta) abrirConversa(st.c, false);
      else mostrarTela("conversa");
      return;
    }
    fecharConversa();
  });

  // ---------------------------------------------------------------- filtros
  let buscaTimer = null;
  el.busca.addEventListener("input", () => {
    clearTimeout(buscaTimer);
    buscaTimer = setTimeout(() => { estado.busca = el.busca.value.trim(); carregarLista(); }, 300);
  });
  el.filtrosToggle.addEventListener("click", () => {
    const aberto = el.filtros.hidden;
    el.filtros.hidden = !aberto;
    el.filtrosToggle.setAttribute("aria-expanded", String(aberto));
  });
  document.querySelectorAll("[data-filtro]").forEach((b) => b.addEventListener("click", () => {
    document.querySelectorAll("[data-filtro]").forEach((x) => x.classList.toggle("is-ativo", x === b));
    estado.filtro = b.dataset.filtro;
    carregarLista();
  }));
  for (const e of estado.etiquetas) el.etiquetaFiltro.append(criar("option", { value: String(e.id), text: e.nome }));
  el.etiquetaFiltro.addEventListener("change", () => { estado.etiqueta = el.etiquetaFiltro.value; carregarLista(); });

  // ---------------------------------------------------------- nova conversa
  $("#wa-nova-btn").addEventListener("click", () => {
    const sel = $("#wa-nova-instancia");
    sel.replaceChildren(...estado.perfis.filter((p) => p.id !== "todas").map((p) => criar("option", { value: String(p.id), text: p.nome, selected: p.ativo })));
    $("#wa-nova-instancia-label").hidden = sel.options.length <= 1;
    $("#wa-nova-erro").hidden = true;
    el.dlgNova.showModal();
  });
  $("#wa-nova-form").addEventListener("submit", async (ev) => {
    if (ev.submitter && ev.submitter.value !== "ok") return;
    ev.preventDefault();
    const erro = $("#wa-nova-erro");
    try {
      const d = await api("conversas/nova/", {
        method: "POST",
        json: { telefone: $("#wa-nova-telefone").value, nome: $("#wa-nova-nome").value, instancia: $("#wa-nova-instancia").value },
      });
      el.dlgNova.close();
      await carregarLista();
      abrirConversa(d.conversa.id, true);
    } catch (e) {
      erro.textContent = e.message;
      erro.hidden = false;
    }
  });

  // ------------------------------------------------------------------ início
  renderPerfis();
  renderLista();
  estado.pollLista = setInterval(() => { if (!document.hidden) carregarLista(); }, POLL_LISTA);
  document.addEventListener("visibilitychange", () => { if (!document.hidden) { carregarLista(); buscarNovas(); } });
  if (dadosIniciais.aberta) {
    history.replaceState({ c: dadosIniciais.aberta }, "", `?c=${dadosIniciais.aberta}`);
    if (ehCelular()) {
      // No celular, a lista fica "atrás" da conversa para o botão voltar do Android funcionar.
      history.replaceState({}, "", window.location.pathname);
      abrirConversa(dadosIniciais.aberta, true);
    } else {
      abrirConversa(dadosIniciais.aberta, false);
    }
  }
})();
