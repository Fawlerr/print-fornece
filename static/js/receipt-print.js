/*
 * A4 — Impressão da nota.
 *
 * - "Estação de impressão": opção salva NESTE navegador (localStorage). Desligada por
 *   padrão em todos os dispositivos (inclusive celular).
 * - A estação consulta a fila a cada 15 s e imprime as notas de pedidos que entraram em
 *   "Pagamento confirmado". O servidor "reserva" cada nota (claim) de forma atômica, então
 *   a mesma nota nunca é impressa duas vezes, nem por duas estações.
 * - Se o card sair e voltar para "Pagamento confirmado", pergunta antes de imprimir de novo.
 * - Botões [data-reprint-order] reimprimem a nota em qualquer dispositivo (fica no histórico).
 */
(() => {
  "use strict";

  const STATION_KEY = "pf.printStation";
  const DEVICE_KEY = "pf.printDeviceName";
  const POLL_MS = 15000;
  const config = document.querySelector("[data-receipt-print-config]");
  if (!config) return;

  const queueUrl = config.dataset.queueUrl;
  const enabled = config.dataset.enabled === "true";
  const urlFor = (template, id) => template.replace("/0/", `/${id}/`);
  const claimUrl = (id) => urlFor(config.dataset.claimUrl, id);
  const logUrl = (id) => urlFor(config.dataset.logUrl, id);
  const notaUrl = (id) => `${urlFor(config.dataset.notaUrl, id)}?autoprint=1`;

  const storage = {
    get(key) { try { return window.localStorage.getItem(key); } catch (_e) { return null; } },
    set(key, value) { try { window.localStorage.setItem(key, value); } catch (_e) { /* modo privado */ } },
    remove(key) { try { window.localStorage.removeItem(key); } catch (_e) { /* modo privado */ } },
  };

  const isStation = () => enabled && storage.get(STATION_KEY) === "1";
  const deviceName = () => storage.get(DEVICE_KEY) || "Estação de impressão";
  const csrfToken = () => {
    const match = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
    return match ? decodeURIComponent(match[1]) : (document.querySelector("input[name='csrfmiddlewaretoken']")?.value || "");
  };

  const post = async (url, body) => {
    const response = await fetch(url, {
      method: "POST",
      credentials: "same-origin",
      headers: { Accept: "application/json", "Content-Type": "application/json", "X-CSRFToken": csrfToken() },
      body: JSON.stringify(body || {}),
    });
    const data = await response.json().catch(() => ({}));
    return { ok: response.ok, status: response.status, data };
  };

  const toast = (message, isError = false) => {
    if (typeof window.showToast === "function") { window.showToast(message, isError ? "error" : "success"); return; }
    let box = document.querySelector("[data-print-toast]");
    if (!box) {
      box = document.createElement("div");
      box.setAttribute("data-print-toast", "");
      box.setAttribute("role", "status");
      box.className = "print-toast";
      document.body.appendChild(box);
    }
    box.textContent = message;
    box.classList.toggle("is-error", isError);
    box.hidden = false;
    clearTimeout(box._timer);
    box._timer = setTimeout(() => { box.hidden = true; }, 4000);
  };

  // Abre a nota num iframe oculto e chama a janela de impressão (sem pop-up bloqueado).
  const printNota = (orderId) => {
    const frame = document.createElement("iframe");
    frame.className = "receipt-print-frame";
    frame.setAttribute("aria-hidden", "true");
    frame.tabIndex = -1;
    frame.src = notaUrl(orderId);
    document.body.appendChild(frame);
    setTimeout(() => frame.remove(), 60000);
  };

  const reprint = async (orderId, reason = "reimpressao") => {
    const result = await post(logUrl(orderId), { source: reason, device: deviceName() });
    if (!result.ok) { toast(result.data.message || "Não foi possível registrar a impressão.", true); return; }
    printNota(orderId);
    toast("Enviando a nota para a impressora…");
  };

  // Tenta reservar a impressão automática. Se a nota já saiu, pergunta antes de repetir.
  const autoPrint = async (orderId, { askIfPrinted = false } = {}) => {
    if (!isStation()) return;
    const result = await post(claimUrl(orderId), { device: deviceName() });
    if (result.ok && result.data.claimed) {
      printNota(orderId);
      toast(`Imprimindo a nota do pedido ${result.data.number || ""}…`);
      return;
    }
    if (askIfPrinted && result.data && result.data.already_printed) {
      const when = result.data.printed_at_display ? ` em ${result.data.printed_at_display}` : "";
      const who = result.data.printed_by ? ` por ${result.data.printed_by}` : "";
      if (window.confirm(`A nota do pedido ${result.data.number || ""} já foi impressa${when}${who}. Imprimir de novo?`)) {
        await reprint(orderId, "reimpressao");
      }
    }
  };

  let polling = false;
  const pollQueue = async () => {
    if (!isStation() || polling) return;
    polling = true;
    try {
      const response = await fetch(queueUrl, { credentials: "same-origin", headers: { Accept: "application/json" } });
      if (!response.ok) return;
      const data = await response.json();
      for (const order of data.orders || []) {
        // eslint-disable-next-line no-await-in-loop
        await autoPrint(order.id);
      }
    } catch (_e) {
      /* rede instável: tenta de novo no próximo ciclo */
    } finally {
      polling = false;
    }
  };

  // API pública usada pelo Kanban e pela tela de configurações.
  window.PFReceiptPrint = {
    isStation,
    deviceName,
    setStation(on, name) {
      if (on) storage.set(STATION_KEY, "1"); else storage.remove(STATION_KEY);
      if (name !== undefined) { if (name) storage.set(DEVICE_KEY, name); else storage.remove(DEVICE_KEY); }
      if (on) pollQueue();
    },
    onStageChanged(orderId, newStage) {
      if (newStage === "pagamento_confirmado") autoPrint(orderId, { askIfPrinted: true });
    },
    printNota,
    reprint,
  };

  document.addEventListener("click", (event) => {
    const button = event.target.closest("[data-reprint-order]");
    if (!button) return;
    event.preventDefault();
    event.stopPropagation();
    reprint(button.dataset.reprintOrder, "reimpressao");
  });

  document.addEventListener("pf:stage-changed", (event) => {
    const { orderId, stage } = event.detail || {};
    if (orderId) window.PFReceiptPrint.onStageChanged(orderId, stage);
  });

  if (isStation()) {
    pollQueue();
    setInterval(pollQueue, POLL_MS);
    document.addEventListener("visibilitychange", () => { if (!document.hidden) pollQueue(); });
  }
})();
