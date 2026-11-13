/*
 * A6 — Kanban em tempo real (polling curto).
 * A cada 15 s busca os cards alterados e atualiza o card na coluna certa, sem recarregar
 * a página (ex.: selo APROVADO quando o cliente aprova pelo link do WhatsApp).
 */
(() => {
  "use strict";

  const board = document.querySelector("[data-kanban-live]");
  if (!board) return;
  const url = board.dataset.kanbanLive;
  const POLL_MS = 15000;
  let since = board.dataset.kanbanNow || new Date().toISOString();
  let busy = false;

  const columnFor = (stage) => document.querySelector(`.kanban-column[data-stage="${stage}"] .kanban-cards`);

  const apply = (order) => {
    const current = document.querySelector(`.order-card[data-order-id="${order.id}"]`);
    if (current && current.classList.contains("dragging")) return; // não mexe no card que está sendo arrastado
    if (!order.visible || !order.html) {
      if (current) current.remove();
      return;
    }
    const template = document.createElement("template");
    template.innerHTML = order.html.trim();
    const fresh = template.content.firstElementChild;
    if (!fresh) return;
    const target = columnFor(order.stage);
    if (!target) { if (current) current.remove(); return; }
    // Com filtro ativo, só atualiza os cards que já estão na tela (não insere novos).
    if (!current && board.dataset.kanbanFiltered === "true") return;
    if (current && current.parentElement === target) {
      current.replaceWith(fresh);
    } else {
      if (current) current.remove();
      target.prepend(fresh);
    }
    fresh.classList.add("is-live-updated");
    setTimeout(() => fresh.classList.remove("is-live-updated"), 2500);
    document.dispatchEvent(new CustomEvent("pf:kanban-card-updated", { detail: { orderId: order.id, element: fresh } }));
  };

  const poll = async () => {
    if (busy || document.hidden) return;
    busy = true;
    try {
      const response = await fetch(`${url}?since=${encodeURIComponent(since)}`, { credentials: "same-origin", headers: { Accept: "application/json" } });
      if (!response.ok) return;
      const data = await response.json();
      (data.orders || []).forEach(apply);
      if (data.orders && data.orders.length) document.dispatchEvent(new CustomEvent("pf:kanban-refreshed"));
      if (data.now) since = data.now;
    } catch (_e) {
      /* sem conexão: tenta de novo no próximo ciclo */
    } finally {
      busy = false;
    }
  };

  setInterval(poll, POLL_MS);
  document.addEventListener("visibilitychange", () => { if (!document.hidden) poll(); });
})();
