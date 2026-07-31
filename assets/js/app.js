(() => {
  'use strict';

  const app = window.APP || {};
  const baseUrl = app.baseUrl || '';
  const csrfToken = app.csrf || '';
  const pendingMoves = new Set();

  const sidebar = document.querySelector('#sidebar');
  const overlay = document.querySelector('.menu-overlay');
  document.querySelectorAll('[data-menu-open]').forEach((button) => button.addEventListener('click', () => {
    sidebar?.classList.add('open');
    overlay?.classList.add('open');
  }));
  document.querySelectorAll('[data-menu-close], .sidebar nav a').forEach((button) => button.addEventListener('click', () => {
    sidebar?.classList.remove('open');
    overlay?.classList.remove('open');
  }));

  document.querySelectorAll('[data-confirm]').forEach((button) => button.addEventListener('click', (event) => {
    if (!window.confirm(button.dataset.confirm || 'Confirma esta ação?')) event.preventDefault();
  }));
  document.querySelectorAll('[data-money]').forEach((input) => input.addEventListener('blur', () => {
    const digits = input.value.replace(/\D/g, '');
    if (digits) input.value = (Number(digits) / 100).toLocaleString('pt-BR', {minimumFractionDigits: 2, maximumFractionDigits: 2});
  }));
  document.querySelectorAll('[data-whatsapp]').forEach((input) => input.addEventListener('input', () => {
    const digits = input.value.replace(/\D/g, '').slice(0, 11);
    input.value = digits.replace(/^(\d{2})(\d)/, '($1) $2').replace(/(\d{5})(\d)/, '$1-$2');
  }));

  function showToast(message, type = 'success') {
    let region = document.querySelector('#toast-region');
    if (!region) {
      region = document.createElement('div');
      region.id = 'toast-region';
      region.className = 'toast-region';
      region.setAttribute('aria-live', 'polite');
      region.setAttribute('aria-atomic', 'true');
      document.body.append(region);
    }
    const toast = document.createElement('div');
    toast.className = `toast toast-${type === 'error' ? 'error' : 'success'} toast-runtime`;
    toast.setAttribute('role', type === 'error' ? 'alert' : 'status');
    toast.textContent = message;
    region.append(toast);
    window.setTimeout(() => toast.remove(), 5200);
  }

  function configureTheme() {
    const key = 'print-fornece-theme';
    const select = document.querySelector('[data-theme-select]');
    const mediaQuery = window.matchMedia?.('(prefers-color-scheme: dark)');
    const getPreference = () => {
      try {
        const saved = window.localStorage.getItem(key);
        return ['light', 'dark', 'system'].includes(saved) ? saved : 'system';
      } catch (_) {
        return 'system';
      }
    };
    const applyTheme = (preference, save = false) => {
      const theme = preference === 'system' ? (mediaQuery?.matches ? 'dark' : 'light') : preference;
      document.documentElement.dataset.theme = theme;
      document.documentElement.dataset.themePreference = preference;
      const themeColor = document.querySelector('meta[name="theme-color"]');
      if (themeColor) themeColor.content = theme === 'dark' ? '#0d1510' : '#f4f7f5';
      if (select) select.value = preference;
      if (save) {
        try { window.localStorage.setItem(key, preference); } catch (_) { /* Preference remains in memory only. */ }
      }
      document.dispatchEvent(new CustomEvent('app:themechange', {detail: {theme, preference}}));
    };

    const preference = getPreference();
    applyTheme(preference);
    select?.addEventListener('change', () => applyTheme(select.value, true));
    mediaQuery?.addEventListener?.('change', () => {
      if (getPreference() === 'system') applyTheme('system');
    });
  }

  async function moveOrder(orderId, stage) {
    let response;
    try {
      response = await fetch(`${baseUrl}/producao/atualizar-status.php`, {
        method: 'POST',
        credentials: 'same-origin',
        headers: {'Content-Type': 'application/json', 'X-Requested-With': 'XMLHttpRequest'},
        body: JSON.stringify({csrf_token: csrfToken, pedido_id: Number(orderId), etapa: stage}),
      });
    } catch (_) {
      throw new Error('Não foi possível conectar ao servidor. O pedido permaneceu na etapa anterior.');
    }

    let data = null;
    try { data = await response.json(); } catch (_) { /* A resposta abaixo será tratada como falha segura. */ }
    if (!response.ok || !data?.success) {
      throw new Error(data?.message || 'O servidor não confirmou a movimentação. O pedido não foi alterado.');
    }
    return data;
  }

  function updateKanbanKpis(kpis) {
    if (!kpis || typeof kpis !== 'object') return;
    document.querySelectorAll('[data-kanban-kpi]').forEach((element) => {
      const value = kpis[element.dataset.kanbanKpi];
      if (Number.isFinite(Number(value))) element.textContent = String(value);
    });
  }

  function updateEmptyState(column) {
    const list = column.querySelector('[data-stage-cards]');
    if (!list) return;
    const cards = list.querySelectorAll('.order-card');
    let empty = list.querySelector('[data-empty-state]');
    if (cards.length === 0 && !empty) {
      empty = document.createElement('div');
      empty.className = 'empty-state';
      empty.dataset.emptyState = '';
      empty.innerHTML = '<i class="fa-regular fa-folder-open" aria-hidden="true"></i>Nenhum pedido';
      list.append(empty);
    } else if (cards.length > 0) {
      empty?.remove();
    }
  }

  function updateColumnCount(column) {
    const count = column.querySelector('[data-stage-count]');
    if (count) count.textContent = String(column.querySelectorAll('.order-card').length);
  }

  function refreshMoveSelect(card, currentStage) {
    const select = card.querySelector('[data-order-move-select]');
    if (!select) return;
    const stages = [...document.querySelectorAll('.kanban-column')].map((column) => ({
      value: column.dataset.stage,
      label: column.querySelector('.kanban-title span')?.textContent?.trim() || column.dataset.stage,
    }));
    select.replaceChildren(new Option('Mover para…', '', true, true));
    stages.filter((stage) => stage.value !== currentStage).forEach((stage) => select.add(new Option(stage.label, stage.value)));
  }

  function setCardBusy(card, isBusy) {
    card?.classList.toggle('is-saving', isBusy);
    if (card) card.setAttribute('aria-busy', isBusy ? 'true' : 'false');
    card?.querySelectorAll('select, button').forEach((control) => { control.disabled = isBusy; });
  }

  function findOrderCard(orderId) {
    return [...document.querySelectorAll('.order-card')].find((card) => card.dataset.orderId === String(orderId)) || null;
  }

  async function persistMove(orderId, destination) {
    const card = findOrderCard(orderId);
    if (pendingMoves.has(String(orderId))) return;
    const sourceStage = card?.dataset.stage;
    if (sourceStage === destination) return;

    pendingMoves.add(String(orderId));
    setCardBusy(card, true);
    try {
      const result = await moveOrder(orderId, destination);
      updateKanbanKpis(result.kpis);

      if (card && sourceStage) {
        const sourceColumn = card.closest('.kanban-column');
        const targetColumn = document.querySelector(`.kanban-column[data-stage="${result.nova_etapa}"]`);
        const activeFilter = document.querySelector('[data-kanban-filter-stage]')?.dataset.kanbanFilterStage || '';
        if (activeFilter && activeFilter !== result.nova_etapa) {
          card.remove();
        } else if (targetColumn) {
          targetColumn.querySelector('[data-stage-cards]')?.append(card);
          card.dataset.stage = result.nova_etapa;
          refreshMoveSelect(card, result.nova_etapa);
        }
        if (sourceColumn) {
          updateEmptyState(sourceColumn);
          updateColumnCount(sourceColumn);
        }
        if (targetColumn && targetColumn !== sourceColumn) {
          updateEmptyState(targetColumn);
          updateColumnCount(targetColumn);
        }
      }
      showToast(result.message);
      return result;
    } catch (error) {
      showToast(error instanceof Error ? error.message : 'Não foi possível movimentar o pedido.', 'error');
      throw error;
    } finally {
      pendingMoves.delete(String(orderId));
      setCardBusy(card, false);
    }
  }

  function configureKanban() {
    const kanban = document.querySelector('.kanban');
    if (!kanban) return;
    let draggedCard = null;

    kanban.addEventListener('dragstart', (event) => {
      const card = event.target.closest('.order-card');
      if (!card || pendingMoves.has(card.dataset.orderId)) return;
      draggedCard = card;
      card.classList.add('dragging');
      event.dataTransfer?.setData('text/plain', card.dataset.orderId || '');
      if (event.dataTransfer) event.dataTransfer.effectAllowed = 'move';
    });
    kanban.addEventListener('dragend', () => {
      draggedCard?.classList.remove('dragging');
      kanban.querySelectorAll('.kanban-column').forEach((column) => column.classList.remove('drag-over'));
      draggedCard = null;
    });
    kanban.addEventListener('dragover', (event) => {
      const column = event.target.closest('.kanban-column');
      if (!column || !draggedCard || column.dataset.stage === draggedCard.dataset.stage) return;
      event.preventDefault();
      kanban.querySelectorAll('.kanban-column').forEach((item) => item.classList.toggle('drag-over', item === column));
      if (event.dataTransfer) event.dataTransfer.dropEffect = 'move';
    });
    kanban.addEventListener('dragleave', (event) => {
      const column = event.target.closest('.kanban-column');
      if (column && !column.contains(event.relatedTarget)) column.classList.remove('drag-over');
    });
    kanban.addEventListener('drop', async (event) => {
      const column = event.target.closest('.kanban-column');
      event.preventDefault();
      kanban.querySelectorAll('.kanban-column').forEach((item) => item.classList.remove('drag-over'));
      if (!column || !draggedCard || column.dataset.stage === draggedCard.dataset.stage) return;
      try { await persistMove(draggedCard.dataset.orderId, column.dataset.stage); } catch (_) { /* Card was intentionally left in its original column. */ }
    });
    kanban.addEventListener('change', async (event) => {
      const select = event.target.closest('[data-order-move-select]');
      if (!select || !select.value) return;
      const stage = select.value;
      select.value = '';
      try { await persistMove(select.dataset.orderId, stage); } catch (_) { /* Error feedback was already displayed. */ }
    });
  }

  document.querySelectorAll('[data-order-move]').forEach((button) => button.addEventListener('click', async () => {
    button.disabled = true;
    try {
      await persistMove(button.dataset.orderMove, button.dataset.stage);
      window.setTimeout(() => window.location.reload(), 450);
    } catch (_) {
      button.disabled = false;
    }
  }));

  async function pollNotifications() {
    const count = document.querySelector('[data-unread-count]');
    if (!count) return;
    try {
      const response = await fetch(`${baseUrl}/notificacoes/poll.php`, {credentials: 'same-origin', headers: {'X-Requested-With': 'XMLHttpRequest'}});
      if (!response.ok) return;
      const data = await response.json();
      count.textContent = data.unread;
      count.classList.toggle('is-empty', !data.unread);
    } catch (_) { /* A notification refresh must never interrupt the current page. */ }
  }

  function configurePwa() {
    const installButton = document.querySelector('[data-install-app]');
    const iosButton = document.querySelector('[data-install-ios]');
    let installPrompt = null;
    const isIos = /iphone|ipad|ipod/i.test(window.navigator.userAgent) && !window.MSStream;
    const isStandalone = window.matchMedia?.('(display-mode: standalone)').matches || window.navigator.standalone === true;

    window.addEventListener('beforeinstallprompt', (event) => {
      event.preventDefault();
      installPrompt = event;
      if (!isIos && !isStandalone && installButton) installButton.hidden = false;
    });
    installButton?.addEventListener('click', async () => {
      if (!installPrompt) return;
      installPrompt.prompt();
      await installPrompt.userChoice;
      installPrompt = null;
      installButton.hidden = true;
    });
    if (isIos && !isStandalone && iosButton) iosButton.hidden = false;
    iosButton?.addEventListener('click', () => showToast('No iPhone ou iPad, abra o menu Compartilhar e escolha “Adicionar à Tela de Início”.'));
    window.addEventListener('appinstalled', () => {
      installButton && (installButton.hidden = true);
      iosButton && (iosButton.hidden = true);
      showToast('Aplicativo instalado com sucesso.');
    });

    if ('serviceWorker' in navigator) {
      const scope = `${baseUrl || ''}/`.replace(/\/\/+/, '/');
      navigator.serviceWorker.register(`${baseUrl}/service-worker.php`, {scope}).catch(() => {
        /* The site remains fully functional when service workers are unavailable. */
      });
    }
  }

  configureTheme();
  configureKanban();
  configurePwa();
  if (document.querySelector('[data-unread-count]')) window.setInterval(pollNotifications, 60000);
})();
