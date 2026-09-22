(function () {
  'use strict';

  var copyButton = document.querySelector('[data-copy-pix]');
  var code = document.querySelector('[data-pix-copy-code]');
  var feedback = document.querySelector('[data-copy-feedback]');

  if (!copyButton || !code) {
    return;
  }

  function setFeedback(message) {
    if (feedback) {
      feedback.textContent = message;
    }
  }

  function fallbackCopy() {
    code.focus();
    code.select();
    return document.execCommand('copy');
  }

  copyButton.addEventListener('click', function () {
    var value = code.value;
    if (!value) {
      setFeedback('Não há código PIX disponível para copiar.');
      return;
    }

    var copy = navigator.clipboard && window.isSecureContext
      ? navigator.clipboard.writeText(value)
      : Promise.resolve(fallbackCopy());

    Promise.resolve(copy)
      .then(function () {
        setFeedback('Código PIX copiado.');
      })
      .catch(function () {
        setFeedback('Não foi possível copiar automaticamente. Selecione o código e copie manualmente.');
        code.focus();
        code.select();
      });
  });
}());
