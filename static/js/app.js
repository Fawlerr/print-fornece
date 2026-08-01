(() => {
  "use strict";

  const body = document.body;

  const closeMenu = () => {
    const sidebar = document.querySelector("#sidebar");
    const overlay = document.querySelector(".menu-overlay");
    if (sidebar) sidebar.classList.remove("open");
    if (overlay) overlay.classList.remove("open");
  };

  document.querySelectorAll("[data-menu-open]").forEach((button) => {
    button.addEventListener("click", () => {
      const sidebar = document.querySelector("#sidebar");
      const overlay = document.querySelector(".menu-overlay");
      if (sidebar) sidebar.classList.add("open");
      if (overlay) overlay.classList.add("open");
    });
  });

  document.querySelectorAll("[data-menu-close], .sidebar nav a").forEach((element) => {
    element.addEventListener("click", closeMenu);
  });

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") closeMenu();
  });

  document.addEventListener("click", (event) => {
    const trigger = event.target.closest("[data-confirm]");
    if (!trigger) return;
    const message = trigger.dataset.confirm || "Confirma esta ação?";
    if (!window.confirm(message)) event.preventDefault();
  });

  document.querySelectorAll("[data-money]").forEach((input) => {
    input.addEventListener("blur", () => {
      const digits = input.value.replace(/\D/g, "");
      if (!digits) return;
      input.value = (Number(digits) / 100).toLocaleString("pt-BR", {
        minimumFractionDigits: 2,
        maximumFractionDigits: 2,
      });
    });
  });

  document.querySelectorAll("[data-whatsapp]").forEach((input) => {
    input.addEventListener("input", () => {
      const digits = input.value.replace(/\D/g, "").slice(0, 11);
      input.value = digits
        .replace(/^(\d{2})(\d)/, "($1) $2")
        .replace(/(\d{5})(\d)/, "$1-$2");
    });
  });

  function getCookie(name) {
    const prefix = name + "=";
    for (const part of document.cookie.split(";")) {
      const value = part.trim();
      if (value.startsWith(prefix)) return decodeURIComponent(value.slice(prefix.length));
    }
    return "";
  }

  function csrfToken() {
    const input = document.querySelector("input[name='csrfmiddlewaretoken']");
    return getCookie("csrftoken") || (input ? input.value : "") || body.dataset.csrfToken || "";
  }

  function dataAttributeName(key) {
    return "data-" + key.replace(/[A-Z]/g, (letter) => "-" + letter.toLowerCase());
  }

  function datasetValue(source, key) {
    const owner = source && source.closest ? source.closest("[" + dataAttributeName(key) + "]") : null;
    if (owner && owner.dataset[key]) return owner.dataset[key];
    return body.dataset[key] || "";
  }

  function showStatus(message) {
    let status = document.querySelector("[data-app-status]");
    if (!status) {
      status = document.createElement("div");
      status.className = "sr-only";
      status.dataset.appStatus = "";
      status.setAttribute("aria-live", "polite");
      body.append(status);
    }
    status.textContent = message;
  }

  async function moveOrder(source, orderId, stage) {
    const endpoint = datasetValue(source, "kanbanEndpoint");
    if (!endpoint) throw new Error("A atualização da produção não está disponível.");

    const orderField = datasetValue(source, "kanbanOrderField") || "order_id";
    const stageField = datasetValue(source, "kanbanStageField") || "stage";
    const payload = {};
    payload[orderField] = orderId;
    payload[stageField] = stage;

    const headers = {
      Accept: "application/json",
      "Content-Type": "application/json",
      "X-Requested-With": "XMLHttpRequest",
    };
    const token = csrfToken();
    if (token) headers["X-CSRFToken"] = token;

    const response = await fetch(endpoint, {
      method: "POST",
      credentials: "same-origin",
      headers,
      body: JSON.stringify(payload),
    });

    let data = {};
    const contentType = response.headers.get("content-type") || "";
    if (contentType.includes("application/json")) data = await response.json();
    if (!response.ok) {
      throw new Error(data.message || data.detail || "Não foi possível mover o pedido.");
    }
    return data;
  }

  document.querySelectorAll("[data-order-move]").forEach((button) => {
    button.addEventListener("click", async () => {
      const orderId = button.dataset.orderMove || button.dataset.orderId;
      const stage = button.dataset.stage;
      if (!orderId || !stage) return;

      button.disabled = true;
      try {
        const data = await moveOrder(button, orderId, stage);
        showStatus(data.message || "Pedido movido com sucesso.");
        if (data.redirect) {
          window.location.assign(data.redirect);
          return;
        }
        window.location.reload();
      } catch (error) {
        window.alert(error.message || "Não foi possível mover o pedido.");
        button.disabled = false;
      }
    });
  });

  let draggedCard = null;
  document.querySelectorAll(".order-card[draggable]").forEach((card) => {
    card.addEventListener("dragstart", () => {
      draggedCard = card;
      card.classList.add("dragging");
    });
    card.addEventListener("dragend", () => {
      draggedCard = null;
      card.classList.remove("dragging");
    });
  });

  document.querySelectorAll(".kanban-column[data-stage]").forEach((column) => {
    column.addEventListener("dragover", (event) => {
      event.preventDefault();
      column.classList.add("drag-over");
    });
    column.addEventListener("dragleave", () => column.classList.remove("drag-over"));
    column.addEventListener("drop", async (event) => {
      event.preventDefault();
      column.classList.remove("drag-over");
      if (!draggedCard) return;

      const card = draggedCard;
      const orderId = card.dataset.orderId || card.dataset.orderMove;
      const currentStage = card.dataset.stage;
      const targetStage = column.dataset.stage;
      if (!orderId || !targetStage || currentStage === targetStage) return;

      try {
        const data = await moveOrder(card, orderId, targetStage);
        const cards = column.querySelector(".kanban-cards");
        if (cards) cards.append(card);
        card.dataset.stage = targetStage;
        showStatus(data.message || "Pedido movido com sucesso.");
      } catch (error) {
        window.alert(error.message || "Não foi possível mover o pedido.");
      }
    });
  });

  async function pollNotifications() {
    const count = document.querySelector("[data-unread-count]");
    const endpoint = body.dataset.notificationsPollEndpoint;
    if (!count || !endpoint) return;

    try {
      const response = await fetch(endpoint, {
        credentials: "same-origin",
        headers: { Accept: "application/json", "X-Requested-With": "XMLHttpRequest" },
      });
      if (!response.ok) return;
      const data = await response.json();
      const unread = Number(data.unread !== undefined ? data.unread : (data.count || 0));
      count.textContent = String(unread);
      count.classList.toggle("is-empty", unread === 0);
    } catch (_) {
      // Uma falha de rede não deve interromper a navegação.
    }
  }

  if (body.dataset.notificationsPollEndpoint && document.querySelector("[data-unread-count]")) {
    window.setInterval(pollNotifications, 60000);
  }
})();
