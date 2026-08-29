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
    pronto_retirada: { previous: "em_producao", next: "entregue", finalize: true },
    entregue: { previous: "pronto_retirada" },
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

    // Atualiza badge de pagamento se estava como Não Pago
    const badge = card.querySelector(".badge-nao_pago");
    if (badge && (newStage === "pagamento_confirmado" || newStage === "pre_impressao" || newStage === "em_producao" || newStage === "pronto_retirada" || newStage === "entregue")) {
      badge.className = "badge badge-pago";
      badge.textContent = "Pago";
    }

    const orderId = card.dataset.orderId;
    const config = STAGE_ACTION_CONFIG[newStage];
    if (!config) {
      actionsDiv.innerHTML = "";
      return;
    }

    let html = "";
    if (config.previous) {
      html += stageButton(orderId, config.previous, "prev");
    } else {
      html += '<span class="kanban-stage-spacer" aria-hidden="true"></span>';
    }

    if (config.next) {
      html += stageButton(orderId, config.next, "next");
    } else if (config.finalize) {
      html += `<a class="kanban-stage-button kanban-stage-button-next" href="/production/${orderId}/" aria-label="Abrir pedido para finalizar" title="Abrir pedido para finalizar"><span class="desktop-only">Finalizar </span><i class="fa-solid fa-check" aria-hidden="true"></i></a>`;
    }

    actionsDiv.innerHTML = html;
    bindMoveButtons();
    bindCardClickHandlers();
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

  // --- Real-time Online Users & Live Stopwatch Manager ---
  (() => {
    const onlineEndpoint = body.dataset.onlineUsersEndpoint;
    const modal = document.querySelector("#onlineUsersModal");
    const openBtns = document.querySelectorAll("[data-open-online-users]");
    const closeBtns = [
      document.querySelector("#closeOnlineUsersModalBtn"),
      document.querySelector("#closeOnlineUsersFooterBtn"),
    ];
    const refreshBtn = document.querySelector("#refreshOnlineUsersBtn");
    const refreshIcon = document.querySelector("#refreshOnlineUsersIcon");
    const listEl = document.querySelector("#onlineUsersList");
    const emptyEl = document.querySelector("#onlineUsersEmpty");
    const loadingEl = document.querySelector("#onlineUsersLoading");
    const searchInput = document.querySelector("#searchOnlineUsersInput");
    const filterTabs = document.querySelectorAll(".online-filter-tab");
    const sidebarCountEl = document.querySelector("#sidebarOnlineCount");
    const modalPillText = document.querySelector("#modalOnlinePillText");
    const selfTimerEl = document.querySelector("#selfLiveTimer");

    let cachedUsers = [];
    const userTimers = new Map();
    let activeFilter = "all";
    let activeSearch = "";
    let isFetching = false;

    function formatTime(totalSec) {
      const s = Math.max(0, Math.floor(Number(totalSec) || 0));
      const hours = String(Math.floor(s / 3600)).padStart(2, "0");
      const minutes = String(Math.floor((s % 3600) / 60)).padStart(2, "0");
      const seconds = String(s % 60).padStart(2, "0");
      return `${hours}:${minutes}:${seconds}`;
    }

    function updateSelfSessionTimer() {
      if (!selfTimerEl) return;
      const startIso = selfTimerEl.dataset.selfStart;
      if (!startIso) return;
      const startTime = new Date(startIso).getTime();
      if (isNaN(startTime)) return;
      const now = Date.now();
      const elapsedSec = Math.max(0, Math.floor((now - startTime) / 1000));
      selfTimerEl.textContent = formatTime(elapsedSec);
    }

    function tickAllLiveTimers() {
      updateSelfSessionTimer();
      userTimers.forEach((sec, userId) => {
        const nextSec = sec + 1;
        userTimers.set(userId, nextSec);
        const timerDoms = document.querySelectorAll(`[data-user-timer-id="${userId}"]`);
        timerDoms.forEach((el) => {
          el.textContent = formatTime(nextSec);
        });
      });
    }

    // 1-second live clock ticker
    window.setInterval(tickAllLiveTimers, 1000);
    updateSelfSessionTimer();

    function renderUsers() {
      if (!listEl) return;

      const filtered = cachedUsers.filter((u) => {
        const matchesFilter =
          activeFilter === "all" ||
          (activeFilter === "online" && u.status === "online") ||
          (activeFilter === "idle" && u.status === "idle") ||
          (activeFilter === "offline" && u.status === "offline");

        const q = activeSearch.toLowerCase().trim();
        const matchesSearch =
          !q ||
          (u.name && u.name.toLowerCase().includes(q)) ||
          (u.email && u.email.toLowerCase().includes(q)) ||
          (u.role_label && u.role_label.toLowerCase().includes(q)) ||
          (u.sector_label && u.sector_label.toLowerCase().includes(q));

        return matchesFilter && matchesSearch;
      });

      if (loadingEl) loadingEl.style.display = "none";

      if (filtered.length === 0) {
        listEl.innerHTML = "";
        if (emptyEl) emptyEl.style.display = "block";
        return;
      }

      if (emptyEl) emptyEl.style.display = "none";

      const html = filtered
        .map((u) => {
          const initial = (u.name || u.email || "?").charAt(0).toUpperCase();
          const selfBadge = u.is_self
            ? `<span class="badge" style="background: rgba(59, 130, 246, 0.2); color: #93c5fd; border: 1px solid rgba(59, 130, 246, 0.4); padding: 2px 7px; font-size: 0.72rem;">Você</span>`
            : "";
          const roleBadge = `<span class="badge" style="background: #202823; color: #a9b7ad; font-size: 0.74rem;">${u.role_label}</span>`;
          const sectorBadge = `<span class="badge" style="background: #19221d; color: #7f8e82; font-size: 0.72rem;">${u.sector_label}</span>`;

          const timerBox =
            u.status === "online" || u.status === "idle"
              ? `
            <div class="stopwatch-digital-clock ${u.status}" title="Tempo ativo na sessão atual">
              <i class="fa-solid fa-stopwatch" aria-hidden="true"></i>
              <span data-user-timer-id="${u.id}">${formatTime(userTimers.get(u.id) || u.online_seconds)}</span>
            </div>
            <span class="stopwatch-label">Online desde ${u.last_login_formatted || "—"}</span>
          `
              : `
            <div class="stopwatch-digital-clock offline" title="Usuário desconectado">
              <i class="fa-regular fa-circle-stop" aria-hidden="true"></i>
              <span>Desconectado</span>
            </div>
            <span class="stopwatch-label">Último acesso: ${u.last_login_formatted || "—"}</span>
          `;

          return `
          <div class="online-user-card ${u.is_self ? "is-self" : ""}">
            <div class="online-avatar-wrap">
              <span>${initial}</span>
              <span class="online-avatar-status ${u.status}" title="${u.status_label}"></span>
            </div>

            <div class="online-user-main">
              <div class="online-user-name-row">
                <strong class="online-user-name">${u.name}</strong>
                ${selfBadge}
                <div class="online-user-badges">
                  ${roleBadge}
                  ${sectorBadge}
                </div>
              </div>

              <div class="online-user-details-row">
                <span title="Última atividade registrada: ${u.last_activity_formatted || ""}">
                  <i class="fa-regular fa-clock" style="color: #24d366;"></i>
                  Última ação: <strong style="color: #f5f7f5;">${u.last_activity_relative}</strong>
                </span>
                <span title="Tela que o colaborador está visualizando">
                  <i class="fa-regular fa-compass" style="color: #60a5fa;"></i>
                  ${u.last_seen_page}
                </span>
                <span title="Dispositivo de acesso">
                  <i class="fa-solid fa-laptop" style="color: #9da69f;"></i>
                  ${u.last_seen_device}
                </span>
              </div>
            </div>

            <div class="online-user-timer-box">
              ${timerBox}
            </div>
          </div>
        `;
        })
        .join("");

      listEl.innerHTML = html;
    }

    function updateCounts(data) {
      if (!data) return;
      const onlineCount = data.online_count || 0;
      const idleCount = data.idle_count || 0;
      const totalUsers = data.total_users || (data.users ? data.users.length : 0);
      const offlineCount = Math.max(0, totalUsers - onlineCount - idleCount);

      if (sidebarCountEl) sidebarCountEl.textContent = String(onlineCount);
      if (modalPillText) modalPillText.textContent = `${onlineCount} online agora`;

      const bAll = document.querySelector("#tabBadgeAll");
      const bOnline = document.querySelector("#tabBadgeOnline");
      const bIdle = document.querySelector("#tabBadgeIdle");
      const bOffline = document.querySelector("#tabBadgeOffline");

      if (bAll) bAll.textContent = String(totalUsers);
      if (bOnline) bOnline.textContent = String(onlineCount);
      if (bIdle) bIdle.textContent = String(idleCount);
      if (bOffline) bOffline.textContent = String(offlineCount);
    }

    async function fetchOnlineUsers(isManual = false) {
      if (!onlineEndpoint || isFetching) return;
      isFetching = true;

      if (isManual && refreshIcon) {
        refreshIcon.classList.add("fa-spin");
      }

      try {
        const url = `${onlineEndpoint}${isManual ? "?heartbeat=1" : ""}`;
        const response = await fetch(url, {
          credentials: "same-origin",
          headers: { Accept: "application/json", "X-Requested-With": "XMLHttpRequest" },
        });

        if (!response.ok) return;
        const data = await response.json();

        cachedUsers = data.users || [];
        cachedUsers.forEach((u) => {
          userTimers.set(u.id, u.online_seconds || 0);
        });

        updateCounts(data);
        renderUsers();
      } catch (err) {
        console.warn("Erro ao sincronizar usuários online:", err);
      } finally {
        isFetching = false;
        if (refreshIcon) {
          setTimeout(() => refreshIcon.classList.remove("fa-spin"), 400);
        }
      }
    }

    function openModal() {
      if (modal) {
        modal.style.display = "flex";
        if (loadingEl && cachedUsers.length === 0) loadingEl.style.display = "block";
        fetchOnlineUsers(true);
      }
    }

    function closeModal() {
      if (modal) modal.style.display = "none";
    }

    openBtns.forEach((btn) => btn.addEventListener("click", openModal));
    closeBtns.forEach((btn) => {
      if (btn) btn.addEventListener("click", closeModal);
    });

    if (modal) {
      modal.addEventListener("click", (e) => {
        if (e.target === modal) closeModal();
      });
    }

    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape" && modal && modal.style.display === "flex") {
        closeModal();
      }
    });

    if (refreshBtn) {
      refreshBtn.addEventListener("click", () => fetchOnlineUsers(true));
    }

    if (searchInput) {
      searchInput.addEventListener("input", (e) => {
        activeSearch = e.target.value;
        renderUsers();
      });
    }

    filterTabs.forEach((tab) => {
      tab.addEventListener("click", () => {
        filterTabs.forEach((t) => t.classList.remove("active"));
        tab.classList.add("active");
        activeFilter = tab.dataset.filter || "all";
        renderUsers();
      });
    });

    // Polling contínuo de usuários online
    if (onlineEndpoint) {
      fetchOnlineUsers(false);
      window.setInterval(() => fetchOnlineUsers(false), 20000);
    }
  })();
})();

