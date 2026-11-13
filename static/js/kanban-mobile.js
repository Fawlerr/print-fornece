/*
 * Kanban no celular (rebranding):
 * - abas no topo para ver uma etapa por vez (até 767 px);
 * - seletor "Mover para…" em cada card, além de arrastar e das setas;
 * - botão "Filtros" que mostra/oculta o formulário de filtros.
 */
(() => {
  "use strict";

  const board = document.querySelector(".kanban");
  if (!board) return;
  const MOBILE = window.matchMedia("(max-width: 767px)");
  const TAB_KEY = "pf.kanbanTab";
  const columns = () => Array.from(board.querySelectorAll(".kanban-column[data-stage]"));
  const labelOf = (col) => col.querySelector(".kanban-title span:first-child")?.textContent.trim() || col.dataset.stage;
  const countOf = (col) => col.querySelectorAll(".order-card").length;

  const storage = {
    get: (k) => { try { return sessionStorage.getItem(k); } catch (_e) { return null; } },
    set: (k, v) => { try { sessionStorage.setItem(k, v); } catch (_e) { /* modo privado */ } },
  };
  const csrfToken = () => {
    const match = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
    return match ? decodeURIComponent(match[1]) : (document.querySelector("input[name='csrfmiddlewaretoken']")?.value || "");
  };

  // ---------- Abas ----------
  let tabs = null;
  const select = (stage) => {
    columns().forEach((col) => col.classList.toggle("is-current", col.dataset.stage === stage));
    board.classList.add("has-current");
    if (tabs) {
      tabs.querySelectorAll("button").forEach((b) => {
        const on = b.dataset.stage === stage;
        b.setAttribute("aria-selected", String(on));
        b.tabIndex = on ? 0 : -1;
      });
    }
    storage.set(TAB_KEY, stage);
  };

  const renderTabs = () => {
    if (!tabs) return;
    const current = storage.get(TAB_KEY);
    tabs.innerHTML = "";
    columns().forEach((col) => {
      const b = document.createElement("button");
      b.type = "button";
      b.setAttribute("role", "tab");
      b.dataset.stage = col.dataset.stage;
      b.className = `stage-${col.dataset.stage}`;
      b.style.setProperty("--stage-fg", getComputedStyle(col).getPropertyValue("--stage-fg"));
      b.textContent = `${labelOf(col)} · ${countOf(col)}`;
      b.addEventListener("click", () => select(col.dataset.stage));
      tabs.appendChild(b);
    });
    // Sem escolha salva, fica na primeira etapa (a mesma que o CSS já mostra), sem "pulo" de layout.
    const first = columns().find((c) => c.dataset.stage === current) || columns()[0];
    if (first) select(first.dataset.stage);
  };

  const applyMode = () => {
    if (MOBILE.matches) {
      if (!tabs) {
        tabs = document.querySelector("[data-kanban-tabs]");
        if (!tabs) {
          tabs = document.createElement("div");
          tabs.className = "kanban-mobile-tabs";
          tabs.setAttribute("role", "tablist");
          tabs.setAttribute("aria-label", "Etapas do quadro");
          board.parentElement.insertBefore(tabs, board);
        }
        tabs.addEventListener("keydown", (e) => {
          if (e.key !== "ArrowRight" && e.key !== "ArrowLeft") return;
          const buttons = Array.from(tabs.querySelectorAll("button"));
          const i = buttons.findIndex((b) => b.getAttribute("aria-selected") === "true");
          const next = buttons[(i + (e.key === "ArrowRight" ? 1 : -1) + buttons.length) % buttons.length];
          next.focus(); next.click();
        });
      }
      board.classList.add("is-tabbed");
      renderTabs();
    } else {
      board.classList.remove("has-current");
      columns().forEach((col) => col.classList.remove("is-current"));
      if (tabs) { tabs.innerHTML = ""; }
    }
  };

  // ---------- "Mover para…" ----------
  const addMoveSelect = (card) => {
    if (!card || card.querySelector(".kanban-move-select")) return;
    const controls = card.querySelector(".order-card-controls");
    if (!controls || !card.dataset.kanbanEndpoint) return;
    const sel = document.createElement("select");
    sel.className = "kanban-move-select";
    sel.setAttribute("aria-label", `Mover pedido para outra etapa`);
    sel.innerHTML = `<option value="">Mover para…</option>` + columns()
      .filter((col) => col.dataset.stage !== card.dataset.stage && col.dataset.stage !== "entregue")
      .map((col) => `<option value="${col.dataset.stage}">${labelOf(col)}</option>`).join("");
    sel.addEventListener("click", (e) => e.stopPropagation());
    sel.addEventListener("change", async () => {
      const stage = sel.value;
      if (!stage) return;
      sel.disabled = true;
      try {
        const response = await fetch(card.dataset.kanbanEndpoint, {
          method: "POST",
          credentials: "same-origin",
          headers: { Accept: "application/json", "Content-Type": "application/json", "X-Requested-With": "XMLHttpRequest", "X-CSRFToken": csrfToken() },
          body: JSON.stringify({ stage }),
        });
        const data = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(data.message || "Não foi possível mover o pedido.");
        document.dispatchEvent(new CustomEvent("pf:stage-changed", { detail: { orderId: card.dataset.orderId, stage: data.stage || stage } }));
        if (window.PFKanbanLive) window.PFKanbanLive.poll(); else window.location.reload();
      } catch (error) {
        window.alert(error.message);
        sel.value = "";
      } finally {
        sel.disabled = false;
      }
    });
    controls.appendChild(sel);
  };

  // ---------- Filtros ----------
  const toggle = document.querySelector("[data-toggle-filters]");
  const filters = document.getElementById("kanban-filters");
  if (toggle && filters) {
    toggle.addEventListener("click", () => {
      const open = filters.classList.toggle("is-collapsed") === false;
      toggle.setAttribute("aria-expanded", String(open));
    });
  }

  board.querySelectorAll(".order-card").forEach(addMoveSelect);
  document.addEventListener("pf:kanban-card-updated", (e) => addMoveSelect(e.detail && e.detail.element));
  document.addEventListener("pf:kanban-refreshed", () => { if (tabs) { const cur = storage.get(TAB_KEY); renderTabs(); if (cur) select(cur); } });
  MOBILE.addEventListener("change", applyMode);
  applyMode();
})();
