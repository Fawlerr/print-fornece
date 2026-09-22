(function () {
  'use strict';

  var toggle = document.querySelector('[data-nav-toggle]');
  var navigation = document.getElementById('main-navigation');

  if (toggle && navigation) {
    toggle.addEventListener('click', function () {
      var isOpen = navigation.classList.toggle('is-open');
      toggle.setAttribute('aria-expanded', String(isOpen));
    });
  }

  document.addEventListener('click', function (event) {
    var dismiss = event.target.closest('[data-dismiss-message]');
    if (!dismiss) {
      return;
    }

    var message = dismiss.closest('.message');
    if (message) {
      message.remove();
    }
  });

  document.querySelectorAll('[data-mask-document], input[name="cpf_cnpj"]').forEach(function (input) {
    input.addEventListener('input', function () {
      var digits = input.value.replace(/\D/g, '').slice(0, 14);
      if (digits.length <= 11) {
        input.value = digits
          .replace(/(\d{3})(\d)/, '$1.$2')
          .replace(/(\d{3})(\d)/, '$1.$2')
          .replace(/(\d{3})(\d{1,2})$/, '$1-$2');
      } else {
        input.value = digits
          .replace(/^(\d{2})(\d)/, '$1.$2')
          .replace(/^(\d{3})(\d)/, '$1.$2')
          .replace(/\.(\d{3})(\d)/, '.$1/$2')
          .replace(/(\d{4})(\d)/, '$1-$2');
      }
    });
  });

  document.querySelectorAll('[data-mask-phone], input[name="telefone"]').forEach(function (input) {
    input.addEventListener('input', function () {
      var digits = input.value.replace(/\D/g, '').slice(0, 11);
      if (digits.length <= 10) {
        input.value = digits
          .replace(/^(\d{2})(\d)/, '($1) $2')
          .replace(/(\d{4})(\d)/, '$1-$2');
      } else {
        input.value = digits
          .replace(/^(\d{2})(\d)/, '($1) $2')
          .replace(/(\d{5})(\d)/, '$1-$2');
      }
    });
  });

  /* ========================================================================
     PAINEL LATERAL DE LOGS & TELEMETRIA
     ======================================================================== */
  var drawer = document.getElementById('logs-drawer');
  var overlay = document.getElementById('logs-drawer-overlay');
  var openButtons = document.querySelectorAll('[data-open-logs]');
  var closeButton = document.querySelector('[data-close-logs]');
  var logsList = document.getElementById('logs-list');
  var logsFilterTabs = document.querySelectorAll('[data-log-filter]');
  var logsSearchInput = document.getElementById('logs-search');
  var clearLogsBtn = document.getElementById('btn-clear-logs');
  var activeFilter = '';
  var searchQuery = '';

  function openDrawer() {
    if (drawer && overlay) {
      drawer.classList.add('is-open');
      overlay.classList.add('is-open');
      document.body.style.overflow = 'hidden';
      loadLogs();
    }
  }

  function closeDrawer() {
    if (drawer && overlay) {
      drawer.classList.remove('is-open');
      overlay.classList.remove('is-open');
      document.body.style.overflow = '';
    }
  }

  openButtons.forEach(function (btn) {
    btn.addEventListener('click', openDrawer);
  });

  if (closeButton) {
    closeButton.addEventListener('click', closeDrawer);
  }
  if (overlay) {
    overlay.addEventListener('click', closeDrawer);
  }

  window.openLogsDrawer = openDrawer;
  window.closeLogsDrawer = closeDrawer;

  window.loadLogs = function () {
    if (!logsList) return;
    var apiBase = window.STONE_API_BASE || '/payments/stone/api';
    var url = apiBase + '/logs/?limit=80';
    if (activeFilter) url += '&nivel=' + encodeURIComponent(activeFilter);
    if (searchQuery) url += '&q=' + encodeURIComponent(searchQuery);

    fetch(url)

      .then(function (res) { return res.json(); })
      .then(function (data) {
        renderLogs(data.logs || []);
        var countBadge = document.getElementById('logs-counter-badge');
        if (countBadge) countBadge.textContent = data.total || 0;
      })
      .catch(function (err) {
        logsList.innerHTML = '<div style="color: var(--danger); padding: 1rem;">Erro ao carregar logs.</div>';
      });
  };

  function renderLogs(logs) {
    if (!logsList) return;
    if (!logs.length) {
      logsList.innerHTML = '<div style="padding: 2rem 1rem; text-align: center; color: var(--text-muted); font-family: sans-serif;">Nenhum log encontrado para os critérios selecionados.</div>';
      return;
    }

    var html = '';
    logs.forEach(function (log) {
      var levelClass = 'log-level--' + (log.nivel || 'INFO');
      var statusTag = log.http_status ? ('<span style="color: ' + (log.http_status < 400 ? '#4ade80' : '#f87171') + '; font-weight: bold;">HTTP ' + log.http_status + '</span>') : '';
      var durationTag = log.duracao_ms !== null ? ('<span style="color: var(--text-muted);">' + log.duracao_ms + 'ms</span>') : '';

      html += '<article class="log-entry" id="log-' + log.id + '">';
      html += '  <div class="log-entry__meta">';
      html += '    <div style="display: flex; align-items: center; gap: 0.45rem;">';
      html += '      <span class="log-entry__level ' + levelClass + '">' + log.nivel + '</span>';
      html += '      <span style="color: var(--text-muted); font-size: 0.72rem;">' + log.timestamp + '</span>';
      html += '    </div>';
      html += '    <div style="display: flex; align-items: center; gap: 0.45rem; font-size: 0.72rem;">';
      html += '      ' + statusTag;
      html += '      ' + durationTag;
      html += '    </div>';
      html += '  </div>';

      html += '  <div class="log-entry__body"><strong>' + escapeHtml(log.tipo_evento) + '</strong>: ' + escapeHtml(log.mensagem) + '</div>';

      if (log.order_id || log.charge_id || log.trace_id) {
        html += '<div style="margin-top: 0.35rem; font-size: 0.72rem; color: var(--text-muted); display: flex; flex-wrap: wrap; gap: 0.5rem;">';
        if (log.trace_id) html += '<span>Trace: <code style="color: #93c5fd;">' + escapeHtml(log.trace_id) + '</code></span>';
        if (log.order_id) html += '<span>Order: <code style="color: #6ee7b7;">' + escapeHtml(log.order_id) + '</code></span>';
        if (log.charge_id) html += '<span>Charge: <code style="color: #fbcfe8;">' + escapeHtml(log.charge_id) + '</code></span>';
        html += '</div>';
      }

      var hasReq = log.request_body && Object.keys(log.request_body).length > 0;
      var hasRes = log.response_body && Object.keys(log.response_body).length > 0;

      if (hasReq || hasRes) {
        html += '<div class="log-entry__details">';
        if (hasReq) {
          html += '<details style="margin-bottom: 0.35rem;">';
          html += '  <summary style="cursor: pointer; color: #a78bfa; font-size: 0.72rem;">▶ REQUEST (' + (log.metodo_http || 'POST') + ')</summary>';
          html += '  <pre class="log-entry__codeblock">' + escapeHtml(JSON.stringify(log.request_body, null, 2)) + '</pre>';
          html += '</details>';
        }
        if (hasRes) {
          html += '<details>';
          html += '  <summary style="cursor: pointer; color: #38bdf8; font-size: 0.72rem;">▶ RESPONSE' + (log.http_status ? ' (' + log.http_status + ')' : '') + '</summary>';
          html += '  <pre class="log-entry__codeblock">' + escapeHtml(JSON.stringify(log.response_body, null, 2)) + '</pre>';
          html += '</details>';
        }
        html += '</div>';
      }

      html += '</article>';
    });

    logsList.innerHTML = html;
  }

  function escapeHtml(text) {
    if (!text) return '';
    return String(text)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#039;');
  }

  logsFilterTabs.forEach(function (tab) {
    tab.addEventListener('click', function () {
      logsFilterTabs.forEach(function (t) { t.classList.remove('is-active'); });
      tab.classList.add('is-active');
      activeFilter = tab.getAttribute('data-log-filter') || '';
      loadLogs();
    });
  });

  if (logsSearchInput) {
    var searchTimer;
    logsSearchInput.addEventListener('input', function () {
      clearTimeout(searchTimer);
      searchTimer = setTimeout(function () {
        searchQuery = logsSearchInput.value.trim();
        loadLogs();
      }, 250);
    });
  }

  if (clearLogsBtn) {
    clearLogsBtn.addEventListener('click', function () {
      if (confirm('Tem certeza de que deseja limpar todos os registros de logs de integração?')) {
        var apiBase = window.STONE_API_BASE || '/payments/stone/api';
        fetch(apiBase + '/logs/limpar/', { method: 'POST' })
          .then(function () {
            loadLogs();
          });
      }
    });
  }


  // Atalho de teclado para abrir logs: Ctrl+L ou Shift+L
  document.addEventListener('keydown', function (e) {
    if ((e.ctrlKey && e.key === 'l') || (e.key === 'Escape' && drawer && drawer.classList.contains('is-open'))) {
      if (drawer.classList.contains('is-open')) {
        closeDrawer();
      } else if (e.ctrlKey) {
        e.preventDefault();
        openDrawer();
      }
    }
  });
}());

