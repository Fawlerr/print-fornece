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

  // --- Kanban Column & Card Actions Manager ---

  function updateColumnStates() {
    document.querySelectorAll(".kanban-column").forEach((col) => {
      const cardsContainer = col.querySelector(".kanban-cards");
      if (!cardsContainer) return;
      
      const cards = cardsContainer.querySelectorAll(".order-card");
      const countSpan = col.querySelector(".kanban-title span:last-child");
      if (countSpan) {
        countSpan.textContent = String(cards.length);
      }

      const emptyStates = cardsContainer.querySelectorAll(".empty-state");
      if (cards.length > 0) {
        emptyStates.forEach(es => es.remove());
      } else {
        if (emptyStates.length === 0) {
          const colTitle = col.querySelector(".kanban-title span:first-child")?.textContent || "esta etapa";
          const emptyDiv = document.createElement("div");
          emptyDiv.className = "empty-state";
          emptyDiv.textContent = `Nenhum pedido em ${colTitle.toLowerCase()}.`;
          cardsContainer.appendChild(emptyDiv);
        }
      }
    });
  }

  const STAGE_ACTION_CONFIG = {
    novo: { next: "aguardando_pagamento" },
    aguardando_pagamento: { previous: "novo", next: "pagamento_confirmado" },
    pagamento_confirmado: { previous: "aguardando_pagamento", next: "pre_impressao" },
    pre_impressao: { previous: "pagamento_confirmado", next: "em_producao" },
    em_producao: { previous: "pre_impressao", next: "pronto_retirada" },
    pronto_retirada: { previous: "em_producao", finalize: true },
  };

  function stageButton(orderId, stage, direction) {
    const isNext = direction === "next";
    const label = isNext ? "Avançar uma etapa" : "Voltar uma etapa";
    const icon = isNext ? "fa-chevron-right" : "fa-chevron-left";
    const nextClass = isNext ? " kanban-stage-button-next" : "";
    return `<button class="kanban-stage-button${nextClass}" type="button" data-order-move="${orderId}" data-stage="${stage}" aria-label="${label}" title="${label}"><i class="fa-solid ${icon}" aria-hidden="true"></i><span class="sr-only">${label}</span></button>`;
  }

  function updateCardActionButtons(card, newStage) {
    const actionsDiv = card.querySelector(".order-stage-actions");
    if (!actionsDiv) return;
    const orderId = card.dataset.orderId || card.dataset.orderMove;
    const actions = STAGE_ACTION_CONFIG[newStage] || {};
    const previous = actions.previous
      ? stageButton(orderId, actions.previous, "previous")
      : '<span class="kanban-stage-spacer" aria-hidden="true"></span>';
    let next = "";
    if (actions.next) {
      next = stageButton(orderId, actions.next, "next");
    } else if (actions.finalize) {
      next = `<a class="kanban-stage-button kanban-stage-button-next" href="/production/${orderId}/" aria-label="Abrir pedido para finalizar" title="Abrir pedido para finalizar"><i class="fa-solid fa-check" aria-hidden="true"></i><span class="sr-only">Abrir pedido para finalizar</span></a>`;
    }
    // Retain the server-rendered client link as a DOM node.  Client names are
    // user data and must never be interpolated back into HTML strings.
    const heading = actionsDiv.querySelector("h3");
    actionsDiv.innerHTML = previous;
    if (heading) actionsDiv.appendChild(heading);
    actionsDiv.insertAdjacentHTML("beforeend", next);

    bindMoveButtons(actionsDiv);
  }

  async function moveOrder(source, orderId, stage) {
    const endpoint = datasetValue(source, "kanbanEndpoint") || `/production/${orderId}/stage/`;
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

  function bindMoveButtons(container = document) {
    container.querySelectorAll("[data-order-move]").forEach((button) => {
      if (button.dataset.bound) return;
      button.dataset.bound = "true";

      button.addEventListener("click", async (e) => {
        e.stopPropagation();
        const orderId = button.dataset.orderMove || button.dataset.orderId;
        const stage = button.dataset.stage;
        if (!orderId || !stage) return;

        const card = button.closest(".order-card");
        button.disabled = true;

        try {
          const data = await moveOrder(button, orderId, stage);
          showStatus(data.message || "Pedido movido com sucesso.");
          
          if (data.redirect) {
            window.location.assign(data.redirect);
            return;
          }

          if (card) {
            const targetColumn = document.querySelector(`.kanban-column[data-stage="${stage}"]`);
            if (targetColumn) {
              const cardsContainer = targetColumn.querySelector(".kanban-cards");
              if (cardsContainer) {
                cardsContainer.appendChild(card);
                card.dataset.stage = stage;
                updateCardActionButtons(card, stage);
                updateColumnStates();
              }
            } else {
              window.location.reload();
            }
          } else {
            window.location.reload();
          }
        } catch (error) {
          window.alert(error.message || "Não foi possível mover o pedido.");
          button.disabled = false;
        }
      });
    });
  }

  function bindCardClickHandlers() {
    document.querySelectorAll(".order-card").forEach((card) => {
      if (card.dataset.clickBound) return;
      card.dataset.clickBound = "true";
      card.style.cursor = "pointer";

      card.addEventListener("click", (e) => {
        if (e.target.closest("button, a, input, select, form")) return;
        const orderId = card.dataset.orderId;
        if (orderId) {
          window.location.href = `/production/${orderId}/`;
        }
      });
    });
  }

  // Bind initial buttons and card clicks
  bindMoveButtons();
  bindCardClickHandlers();
  updateColumnStates();

  // --- Drag and Drop Setup ---
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
        if (cards) {
          cards.appendChild(card);
          card.dataset.stage = targetStage;
          updateCardActionButtons(card, targetStage);
          updateColumnStates();
        }
        showStatus(data.message || "Pedido movido com sucesso.");
      } catch (error) {
        window.alert(error.message || "Não foi possível mover o pedido.");
      }
    });
  });

  // --- Service Worker & PWA Install Manager ---
  let deferredPrompt = null;
  const isIOS = /iPad|iPhone|iPod/.test(navigator.userAgent) && !window.MSStream;
  const isStandalone = window.matchMedia('(display-mode: standalone)').matches || window.navigator.standalone === true;

  if ('serviceWorker' in navigator) {
    window.addEventListener('load', () => {
      navigator.serviceWorker.register('/static/sw.js')
        .then((reg) => console.log('Service Worker PWA registrado:', reg.scope))
        .catch((err) => console.log('Falha no Service Worker:', err));
    });
  }

  window.addEventListener('beforeinstallprompt', (e) => {
    e.preventDefault();
    deferredPrompt = e;
    const installBtn = document.querySelector('#pwa-install-btn');
    const installBanner = document.querySelector('#pwa-install-banner');
    if (installBtn) installBtn.style.display = 'inline-flex';
    if (installBanner && !localStorage.getItem('pwa_banner_dismissed')) {
      installBanner.style.display = 'block';
    }
  });

  const triggerPwaInstall = () => {
    if (deferredPrompt) {
      deferredPrompt.prompt();
      deferredPrompt.userChoice.then((choiceResult) => {
        if (choiceResult.outcome === 'accepted') {
          console.log('Usuário aceitou a instalação do WebApp');
        }
        deferredPrompt = null;
        const banner = document.querySelector('#pwa-install-banner');
        if (banner) banner.style.display = 'none';
      });
    } else if (isIOS) {
      const iosModal = document.querySelector('#ios-pwa-modal');
      if (iosModal) iosModal.style.display = 'flex';
    } else {
      alert('Para instalar o WebApp, acesse a opção "Adicionar à Tela Inicial" no menu do seu navegador.');
    }
  };

  const topInstallBtn = document.querySelector('#pwa-install-btn');
  if (topInstallBtn) {
    if (isIOS && !isStandalone) topInstallBtn.style.display = 'inline-flex';
    topInstallBtn.addEventListener('click', triggerPwaInstall);
  }

  const bannerInstallBtn = document.querySelector('#pwa-banner-install-btn');
  if (bannerInstallBtn) bannerInstallBtn.addEventListener('click', triggerPwaInstall);

  const bannerCloseBtn = document.querySelector('#pwa-banner-close-btn');
  if (bannerCloseBtn) {
    bannerCloseBtn.addEventListener('click', () => {
      const banner = document.querySelector('#pwa-install-banner');
      if (banner) banner.style.display = 'none';
      localStorage.setItem('pwa_banner_dismissed', '1');
    });
  }

  const iosCloseBtn = document.querySelector('#ios-modal-close-btn');
  const iosConfirmBtn = document.querySelector('#ios-modal-confirm-btn');
  const iosModal = document.querySelector('#ios-pwa-modal');
  const closeIosModal = () => { if (iosModal) iosModal.style.display = 'none'; };
  if (iosCloseBtn) iosCloseBtn.addEventListener('click', closeIosModal);
  if (iosConfirmBtn) iosConfirmBtn.addEventListener('click', closeIosModal);

  // --- Push Notifications & Polling Manager ---
  const pushBtn = document.querySelector('#pwa-push-btn');
  if (pushBtn) {
    if ('Notification' in window && Notification.permission === 'granted') {
      pushBtn.classList.add('active');
      pushBtn.querySelector('span').textContent = 'Push Ativo';
    }

    pushBtn.addEventListener('click', async () => {
      if (!('Notification' in window)) {
        alert('Seu dispositivo/navegador não suporta notificações Push.');
        return;
      }
      try {
        const permission = await Notification.requestPermission();
        if (permission === 'granted') {
          pushBtn.classList.add('active');
          pushBtn.querySelector('span').textContent = 'Push Ativo';
          new Notification('Print Fornece', {
            body: 'Notificações Push ativadas com sucesso neste aparelho!',
            icon: '/static/icons/icon-192.png'
          });
        } else {
          alert('Permissão de notificação recusada.');
        }
      } catch (err) {
        console.error('Erro ao ativar notificações:', err);
      }
    });
  }

  let lastUnreadCount = -1;
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

      if (lastUnreadCount >= 0 && unread > lastUnreadCount) {
        if ('Notification' in window && Notification.permission === 'granted') {
          new Notification('Print Fornece', {
            body: 'Você recebeu um novo alerta ou atualização no sistema!',
            icon: '/static/icons/icon-192.png',
            vibrate: [200, 100, 200]
          });
        }
      }
      lastUnreadCount = unread;
      count.textContent = String(unread);
      count.classList.toggle("is-empty", unread === 0);
    } catch (_) {
    }
  }

  if (body.dataset.notificationsPollEndpoint && document.querySelector("[data-unread-count]")) {
    window.setInterval(pollNotifications, 30000);
  }
})();
