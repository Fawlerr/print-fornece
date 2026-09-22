(function () {
  'use strict';

  var form = document.getElementById('charge-form');
  if (!form) {
    return;
  }

  var cardPanel = document.querySelector('[data-card-payment-panel]');
  var methodInputs = document.querySelectorAll('[data-payment-method]');
  var savedMethod = document.querySelector('[data-saved-method]');
  var tokenInput = document.getElementById('card_token');
  var submitButton = document.querySelector('[data-charge-submit]');
  var errorBox = document.getElementById('card-tokenization-error');
  var sensitiveInputs = cardPanel ? cardPanel.querySelectorAll('[data-card-sensitive]') : [];
  var installmentInput = cardPanel ? cardPanel.querySelector('[name="parcelas"]') : null;

  var TOKENIZATION_ENDPOINT = 'https://api.pagar.me/core/v5/tokens';

  function selectedMethod() {
    var selected = document.querySelector('[data-payment-method]:checked');
    return selected ? selected.value : '';
  }

  function usesSavedMethod() {
    return Boolean(savedMethod && savedMethod.value);
  }

  function displayError(message) {
    if (!errorBox) {
      return;
    }
    errorBox.textContent = message;
    errorBox.hidden = false;
  }

  function clearError() {
    if (!errorBox) {
      return;
    }
    errorBox.textContent = '';
    errorBox.hidden = true;
  }

  function setCardFieldsEnabled(enabled) {
    sensitiveInputs.forEach(function (input) {
      input.disabled = !enabled;
      input.required = enabled;
    });
  }

  function syncCardPanel() {
    var shouldShowCard = selectedMethod() === 'cartao';
    var shouldCaptureNewCard = shouldShowCard && !usesSavedMethod();

    if (cardPanel) {
      cardPanel.hidden = !shouldShowCard || !shouldCaptureNewCard;
    }
    setCardFieldsEnabled(shouldCaptureNewCard);
    if (installmentInput) {
      installmentInput.disabled = !shouldShowCard;
    }
    clearError();
  }

  function normalizeDigits(value) {
    return (value || '').replace(/\D/g, '');
  }

  function parseExpiry(value) {
    var digits = normalizeDigits(value);
    if (digits.length !== 4) {
      return null;
    }

    var month = Number(digits.slice(0, 2));
    var year = Number(digits.slice(2, 4));
    if (month < 1 || month > 12) {
      return null;
    }

    return { month: month, year: 2000 + year };
  }

  function cardValue(selector) {
    var input = document.querySelector(selector);
    return input ? input.value.trim() : '';
  }

  function buildTokenPayload() {
    var expiry = parseExpiry(cardValue('[data-card-expiry]'));
    var number = normalizeDigits(cardValue('[data-card-number]'));
    var cvv = normalizeDigits(cardValue('[data-card-cvv]'));
    var holderName = cardValue('[data-card-holder-name]');

    if (!number || !holderName || !expiry || !cvv) {
      return null;
    }

    var card = {
      number: number,
      holder_name: holderName,
      exp_month: expiry.month,
      exp_year: expiry.year,
      cvv: cvv
    };

    return {
      type: 'card',
      card: card
    };
  }

  function clearAndDisableSensitiveFields() {
    sensitiveInputs.forEach(function (input) {
      input.value = '';
      input.disabled = true;
      input.required = false;
    });
    if (installmentInput) {
      installmentInput.disabled = false;
    }
  }

  function setSubmitting(isSubmitting) {
    if (submitButton) {
      submitButton.disabled = isSubmitting;
      submitButton.textContent = isSubmitting ? 'Tokenizando cartão…' : 'Gerar cobrança';
    }
  }

  methodInputs.forEach(function (input) {
    input.addEventListener('change', syncCardPanel);
  });

  if (savedMethod) {
    savedMethod.addEventListener('change', syncCardPanel);
  }

  document.querySelectorAll('[data-card-number]').forEach(function (input) {
    input.addEventListener('input', function () {
      input.value = normalizeDigits(input.value).replace(/(.{4})/g, '$1 ').trim().slice(0, 23);
    });
  });

  document.querySelectorAll('[data-card-expiry]').forEach(function (input) {
    input.addEventListener('input', function () {
      var digits = normalizeDigits(input.value).slice(0, 4);
      input.value = digits.length > 2 ? digits.slice(0, 2) + '/' + digits.slice(2) : digits;
    });
  });

  syncCardPanel();

  form.addEventListener('submit', function (event) {
    if (selectedMethod() !== 'cartao' || usesSavedMethod() || (tokenInput && tokenInput.value)) {
      return;
    }

    event.preventDefault();
    clearError();

    if (!form.reportValidity()) {
      return;
    }

    var publicKey = form.getAttribute('data-stone-public-key');
    if (!publicKey) {
      displayError('A chave pública de testes não está configurada. Não foi possível tokenizar o cartão.');
      return;
    }

    var payload = buildTokenPayload();
    if (!payload) {
      displayError('Confira número, nome, validade e CVV do cartão antes de continuar.');
      return;
    }

    setSubmitting(true);

    fetch(TOKENIZATION_ENDPOINT + '?appId=' + encodeURIComponent(publicKey), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    })
      .then(function (response) {
        if (!response.ok) {
          throw new Error('TOKENIZATION_REQUEST_FAILED');
        }
        return response.json();
      })
      .then(function (tokenResponse) {
        if (!tokenResponse || !tokenResponse.id) {
          throw new Error('TOKENIZATION_RESPONSE_INVALID');
        }

        tokenInput.value = tokenResponse.id;
        clearAndDisableSensitiveFields();

        // Native submit sends card_token only; raw card fields are cleared and disabled first.
        HTMLFormElement.prototype.submit.call(form);
      })
      .catch(function () {
        // Do not expose provider response details or log any card information.
        displayError('Não foi possível tokenizar o cartão agora. Revise os dados e tente novamente.');
        setSubmitting(false);
      });
  });
}());
