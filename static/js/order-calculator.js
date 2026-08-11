(() => {
  "use strict";

  const calculator = document.querySelector("[data-order-calculator]");
  if (!calculator) return;

  const endpoint = calculator.dataset.endpoint;
  const widthInput = calculator.querySelector("[data-calculator-width]");
  const heightInput = calculator.querySelector("[data-calculator-height]");
  const quantityInput = calculator.querySelector("[data-calculator-quantity]");
  const calculateButton = calculator.querySelector("[data-calculator-calculate]");
  const useValueButton = calculator.querySelector("[data-use-calculated]");
  const status = calculator.querySelector("[data-calculator-status]");
  const result = calculator.querySelector("[data-calculator-result]");
  const total = calculator.querySelector("[data-calculator-total]");
  const film = calculator.querySelector("[data-calculator-film]");
  const rule = calculator.querySelector("[data-calculator-rule]");
  const layout = calculator.querySelector("[data-calculator-layout]");
  const calculationPayload = document.querySelector("#id_calculation_payload");
  const totalAmount = document.querySelector("#id_total_amount");
  let requestNumber = 0;
  let debounceTimer = null;
  let quote = null;

  const money = (value) => Number(value || 0).toLocaleString("pt-BR", {
    style: "currency",
    currency: "BRL",
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });

  const number = (value, minimumFractionDigits = 0, maximumFractionDigits = 2) => Number(value || 0).toLocaleString("pt-BR", {
    minimumFractionDigits,
    maximumFractionDigits,
  });

  const csrfToken = () => document.querySelector("input[name='csrfmiddlewaretoken']")?.value || "";

  const selectedMaterial = () => calculator.querySelector("input[name='calculator_material']:checked")?.value || "";

  const hasValues = () => Boolean(selectedMaterial() && widthInput.value.trim() && heightInput.value.trim() && quantityInput.value.trim());

  const setStatus = (message, error = false) => {
    status.textContent = message;
    status.classList.toggle("is-error", error);
  };

  const invalidateQuote = () => {
    quote = null;
    if (calculationPayload) calculationPayload.value = "";
    if (useValueButton) useValueButton.disabled = true;
  };

  const renderQuote = (nextQuote) => {
    quote = nextQuote;
    const payload = {
      material_code: quote.material_code,
      width_cm: widthInput.value,
      height_cm: heightInput.value,
      quantity: quantityInput.value,
    };
    if (calculationPayload) calculationPayload.value = JSON.stringify(payload);

    total.textContent = money(quote.total);
    film.textContent = `${number(quote.film_used_cm)} cm (${number(quote.film_used_m, 2, 2)} m)`;
    rule.textContent = quote.pricing_type === "per_meter"
      ? `${quote.pricing_rule} · ${money(quote.unit_price)}/m`
      : `${quote.pricing_rule} · valor fixo ${money(quote.unit_price)}`;
    layout.textContent = `${quote.pieces_per_row} por fileira · ${quote.rows} fileira${quote.rows === 1 ? "" : "s"}${quote.used_orientation === "rotacionada" ? " · arte girada" : ""}`;
    result.hidden = false;
    useValueButton.disabled = false;
    setStatus("Orçamento atualizado.");
  };

  const requestCalculation = async () => {
    if (!hasValues()) {
      invalidateQuote();
      result.hidden = true;
      setStatus("Preencha as medidas para calcular.");
      return;
    }
    if (!endpoint) {
      setStatus("Não foi possível iniciar o orçamento.", true);
      return;
    }

    const currentRequest = ++requestNumber;
    invalidateQuote();
    setStatus("Calculando…");
    try {
      const response = await fetch(endpoint, {
        method: "POST",
        credentials: "same-origin",
        headers: {
          Accept: "application/json",
          "Content-Type": "application/json",
          "X-CSRFToken": csrfToken(),
        },
        body: JSON.stringify({
          material_code: selectedMaterial(),
          width_cm: widthInput.value,
          height_cm: heightInput.value,
          quantity: quantityInput.value,
        }),
      });
      const data = await response.json().catch(() => ({}));
      if (currentRequest !== requestNumber) return;
      if (!response.ok || !data.quote) {
        invalidateQuote();
        result.hidden = true;
        setStatus(data.message || "Não foi possível calcular o orçamento.", true);
        return;
      }
      renderQuote(data.quote);
    } catch (_error) {
      if (currentRequest !== requestNumber) return;
      invalidateQuote();
      result.hidden = true;
      setStatus("Não foi possível calcular agora. Tente novamente.", true);
    }
  };

  const scheduleCalculation = () => {
    window.clearTimeout(debounceTimer);
    debounceTimer = window.setTimeout(requestCalculation, 260);
  };

  [widthInput, heightInput, quantityInput].forEach((input) => {
    input.addEventListener("input", scheduleCalculation);
    input.addEventListener("change", scheduleCalculation);
  });
  calculator.querySelectorAll("input[name='calculator_material']").forEach((input) => input.addEventListener("change", scheduleCalculation));
  calculateButton.addEventListener("click", requestCalculation);

  useValueButton.addEventListener("click", () => {
    if (!quote || !totalAmount) return;
    totalAmount.value = number(quote.total, 2, 2);
    totalAmount.dispatchEvent(new Event("input", { bubbles: true }));
    totalAmount.dispatchEvent(new Event("change", { bubbles: true }));
    setStatus("Valor calculado aplicado. Você ainda pode ajustá-lo antes de salvar.");
    totalAmount.focus();
  });
})();
