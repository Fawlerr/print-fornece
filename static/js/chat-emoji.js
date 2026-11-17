/*
 * Seletor de emojis do chat (emoji-picker-element, vendorizado em static/vendor).
 * - Carrega o componente só no primeiro clique (não pesa na abertura da página).
 * - Insere o emoji na posição do cursor do textarea, não só no final.
 * - Fecha ao clicar fora ou com Esc. No celular abre como painel inferior (via CSS).
 */
(function () {
  'use strict';

  const toggle = document.querySelector('[data-emoji-toggle]');
  if (!toggle) return;

  const panel = document.getElementById(toggle.getAttribute('aria-controls'));
  const input = document.getElementById(toggle.dataset.emojiTarget);
  if (!panel || !input) return;

  const { pickerSrc, i18nSrc, dataSrc } = toggle.dataset;
  let pickerPromise = null;
  let selection = { start: input.value.length, end: input.value.length };

  function rememberSelection() {
    if (typeof input.selectionStart === 'number') {
      selection = { start: input.selectionStart, end: input.selectionEnd };
    }
  }
  ['keyup', 'click', 'input', 'select', 'blur'].forEach((evt) => input.addEventListener(evt, rememberSelection));

  function loadPicker() {
    if (!pickerPromise) {
      pickerPromise = Promise.all([import(pickerSrc), import(i18nSrc)]).then(([pickerModule, i18nModule]) => {
        const Picker = pickerModule.default;
        const picker = new Picker({ locale: 'pt', dataSource: dataSrc, i18n: i18nModule.default });
        picker.classList.add('emoji-picker');
        picker.addEventListener('emoji-click', (event) => insertEmoji(event.detail.unicode));
        panel.appendChild(picker);
        return picker;
      }).catch((err) => {
        pickerPromise = null;
        console.error('Falha ao carregar o seletor de emojis', err);
        panel.innerHTML = '<p class="emoji-panel-error">Não foi possível carregar os emojis. Tente de novo.</p>';
        throw err;
      });
    }
    return pickerPromise;
  }

  function insertEmoji(emoji) {
    if (!emoji) return;
    const value = input.value;
    const start = Math.min(selection.start, value.length);
    const end = Math.min(selection.end, value.length);
    input.value = value.slice(0, start) + emoji + value.slice(end);
    const caret = start + emoji.length;
    selection = { start: caret, end: caret };
    input.dispatchEvent(new Event('input', { bubbles: true }));
    // No celular, focar o textarea abriria o teclado por cima do painel; só reposiciona o cursor no desktop.
    if (!isSheetMode()) {
      input.focus();
      input.setSelectionRange(caret, caret);
    }
  }

  function isSheetMode() {
    return window.matchMedia('(max-width: 767px)').matches;
  }

  function isOpen() {
    return !panel.hidden;
  }

  function placePanel() {
    if (isSheetMode()) return;
    const rect = toggle.getBoundingClientRect();
    const width = panel.offsetWidth || 360;
    const left = Math.max(8, Math.min(rect.left, window.innerWidth - width - 8));
    panel.style.left = `${left}px`;
    const height = panel.offsetHeight || 380;
    if (rect.top - height - 8 >= 8) {
      panel.style.top = '';
      panel.style.bottom = `${window.innerHeight - rect.top + 8}px`;
    } else {
      // Sem espaço acima do botão: abre abaixo, dentro da tela.
      panel.style.bottom = '';
      panel.style.top = `${Math.max(8, Math.min(rect.bottom + 8, window.innerHeight - height - 8))}px`;
    }
  }

  function open() {
    rememberSelection();
    panel.hidden = false;
    placePanel();
    toggle.setAttribute('aria-expanded', 'true');
    document.body.classList.toggle('emoji-sheet-open', isSheetMode());
    if (isSheetMode()) input.blur();
    loadPicker().then((picker) => {
      const search = picker.shadowRoot && picker.shadowRoot.querySelector('input.search');
      if (search && !isSheetMode()) search.focus();
    }).catch(() => {});
  }

  function close() {
    if (!isOpen()) return;
    panel.hidden = true;
    toggle.setAttribute('aria-expanded', 'false');
    document.body.classList.remove('emoji-sheet-open');
  }

  toggle.addEventListener('pointerdown', rememberSelection);
  toggle.addEventListener('click', (event) => {
    event.preventDefault();
    if (isOpen()) close();
    else open();
  });

  panel.querySelectorAll('[data-emoji-close]').forEach((btn) => btn.addEventListener('click', close));

  document.addEventListener('pointerdown', (event) => {
    if (!isOpen()) return;
    if (panel.contains(event.target) || toggle.contains(event.target)) return;
    close();
  });

  window.addEventListener('resize', () => { if (isOpen()) placePanel(); });

  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && isOpen()) {
      close();
      toggle.focus();
    }
  });

  window.ChatEmojiPicker = { open, close };
})();
