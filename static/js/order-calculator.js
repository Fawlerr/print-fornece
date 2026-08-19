(() => {
  "use strict";

  const calculator = document.querySelector("[data-order-calculator]");
  if (!calculator) return;

  const endpoint = calculator.dataset.endpoint;
  const status = calculator.querySelector("[data-calculator-status]");
  const cartTbody = calculator.querySelector("[data-cart-tbody]");
  const cartCount = calculator.querySelector("[data-cart-count]");
  const cartTotalBadge = calculator.querySelector("[data-cart-total-badge]");
  const calculationPayload = document.querySelector("#id_calculation_payload");
  const totalAmountInput = document.querySelector("#id_total_amount");
  const descriptionInput = document.querySelector("#id_description");

  // Tab buttons and containers
  const tabBtns = calculator.querySelectorAll(".catalog-tab-btn");
  const tabContents = {
    dtf: calculator.querySelector("#tab-dtf"),
    shirts: calculator.querySelector("#tab-shirts"),
    services: calculator.querySelector("#tab-services"),
  };

  // DTF inputs & add button
  const dtfWidthInput = calculator.querySelector("[data-calculator-width]");
  const dtfHeightInput = calculator.querySelector("[data-calculator-height]");
  const dtfQuantityInput = calculator.querySelector("[data-calculator-quantity]");
  const addDtfBtn = calculator.querySelector("[data-add-dtf-btn]");

  // Shirt inputs & add button
  const shirtColorSelect = calculator.querySelector("[data-shirt-color]");
  const shirtSizeSelect = calculator.querySelector("[data-shirt-size]");
  const shirtQuantityInput = calculator.querySelector("[data-shirt-quantity]");
  const addShirtBtn = calculator.querySelector("[data-add-shirt-btn]");

  // Extra service inputs & add button
  const serviceQuantityInput = calculator.querySelector("[data-service-quantity]");
  const addServiceBtn = calculator.querySelector("[data-add-service-btn]");

  let cartItems = [];

  const money = (value) => Number(value || 0).toLocaleString("pt-BR", {
    style: "currency",
    currency: "BRL",
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });

  const number = (value, minDec = 0, maxDec = 2) => Number(value || 0).toLocaleString("pt-BR", {
    minimumFractionDigits: minDec,
    maximumFractionDigits: maxDec,
  });

  const csrfToken = () => document.querySelector("input[name='csrfmiddlewaretoken']")?.value || "";

  const setStatus = (message, isError = false) => {
    if (!status) return;
    status.textContent = message;
    status.classList.toggle("is-error", isError);
  };

  // Tab switching
  tabBtns.forEach((btn) => {
    btn.addEventListener("click", () => {
      tabBtns.forEach((b) => {
        b.classList.remove("active", "btn-primary");
        b.classList.add("btn-secondary");
      });
      btn.classList.add("active", "btn-primary");
      btn.classList.remove("btn-secondary");

      const tabKey = btn.dataset.tab;
      Object.entries(tabContents).forEach(([key, contentEl]) => {
        if (contentEl) {
          contentEl.style.display = key === tabKey ? "block" : "none";
        }
      });
    });
  });

  // Calculate and add item helper
  const calculateItem = async (payload) => {
    setStatus("Calculando item…");
    try {
      const response = await fetch(endpoint, {
        method: "POST",
        credentials: "same-origin",
        headers: {
          Accept: "application/json",
          "Content-Type": "application/json",
          "X-CSRFToken": csrfToken(),
        },
        body: JSON.stringify(payload),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok || !data.quote) {
        setStatus(data.message || "Erro ao calcular item.", true);
        return null;
      }
      return data.quote;
    } catch (_err) {
      setStatus("Falha de conexão com a calculadora.", true);
      return null;
    }
  };

  const renderCart = () => {
    if (!cartTbody) return;
    cartTbody.innerHTML = "";

    if (cartItems.length === 0) {
      cartTbody.innerHTML = `
        <tr class="empty-cart-row">
          <td colspan="5" style="text-align: center; color: var(--muted, #9ca3af); padding: 16px;">
            Nenhum item adicionado ainda. Escolha no catálogo acima e clique para inserir.
          </td>
        </tr>
      `;
      if (cartCount) cartCount.textContent = "0";
      if (cartTotalBadge) cartTotalBadge.textContent = "R$ 0,00";
      if (calculationPayload) calculationPayload.value = "";
      return;
    }

    let totalSum = 0;
    cartItems.forEach((item, index) => {
      const itemTotal = parseFloat(item.total || 0);
      totalSum += itemTotal;

      let specText = item.material_name;
      let measureText = `${item.quantity || 1} un`;

      if (item.kind === "material") {
        measureText = `${item.art_width_cm}x${item.art_height_cm} cm (${item.quantity} un · ${number(item.film_used_m, 2, 2)}m)`;
      } else if (item.kind === "produto") {
        specText = `${item.material_name} (${item.product_color || ""}, Tam: ${item.product_size || ""})`;
        measureText = `${item.quantity} un`;
      } else if (item.kind === "servico") {
        measureText = `${item.quantity} un`;
      }

      const tr = document.createElement("tr");
      tr.innerHTML = `
        <td>
          <strong>${specText}</strong>
          ${item.pricing_rule ? `<br><small class="text-muted" style="font-size: 0.78rem;">${item.pricing_rule}</small>` : ""}
        </td>
        <td>${measureText}</td>
        <td>${money(item.unit_price)}</td>
        <td><strong style="color: #10b981;">${money(item.total)}</strong></td>
        <td style="text-align: center;">
          <button type="button" class="btn btn-danger btn-small" data-remove-item="${index}" title="Remover item" style="padding: 4px 8px; font-size: 0.8rem;">
            <i class="fa-solid fa-trash"></i>
          </button>
        </td>
      `;
      cartTbody.appendChild(tr);
    });

    if (cartCount) cartCount.textContent = String(cartItems.length);
    if (cartTotalBadge) cartTotalBadge.textContent = money(totalSum);

    // Sync hidden payload
    if (calculationPayload) {
      calculationPayload.value = JSON.stringify({ items: cartItems });
    }

    // Sync total amount field (com dedução de abatimento e correção por defeito)
    if (totalAmountInput) {
      const discountInput = document.querySelector("#id_discount_advance");
      let discountVal = 0;
      if (discountInput && discountInput.value) {
        const parsed = parseFloat(discountInput.value.replace(/\./g, "").replace(",", "."));
        if (!isNaN(parsed) && parsed > 0) discountVal = parsed;
      }
      const isCorrectionEl = document.querySelector("#id_is_correction");
      const isCorrection = isCorrectionEl && isCorrectionEl.checked;

      const finalSum = isCorrection ? 0 : Math.max(0, totalSum - discountVal);

      totalAmountInput.value = number(finalSum, 2, 2);
      totalAmountInput.dispatchEvent(new Event("input", { bubbles: true }));
      totalAmountInput.dispatchEvent(new Event("change", { bubbles: true }));
    }

    // Auto-generate / update description with item list if empty or user wants
    if (descriptionInput && (!descriptionInput.value.trim() || descriptionInput.dataset.autoGenerated === "true")) {
      const lines = cartItems.map((it) => {
        if (it.kind === "material") {
          return `${it.material_name}: ${it.art_width_cm}x${it.art_height_cm} cm - ${it.quantity} un (${it.film_used_m}m)`;
        }
        if (it.kind === "produto") {
          return `${it.material_name} (${it.product_color}, Tam: ${it.product_size}) - ${it.quantity} un`;
        }
        return `${it.material_name} - ${it.quantity} un`;
      });
      descriptionInput.value = lines.join("\n");
      descriptionInput.dataset.autoGenerated = "true";
    }

    // Attach remove handlers
    cartTbody.querySelectorAll("[data-remove-item]").forEach((btn) => {
      btn.addEventListener("click", () => {
        const idx = parseInt(btn.dataset.removeItem, 10);
        cartItems.splice(idx, 1);
        renderCart();
        setStatus("Item removido do pedido.");
      });
    });
  };

  // 1. Add DTF
  if (addDtfBtn) {
    addDtfBtn.addEventListener("click", async () => {
      const selectedMat = calculator.querySelector("input[name='calculator_material']:checked")?.value || "dtf_textil";
      const width = dtfWidthInput.value.trim();
      const height = dtfHeightInput.value.trim();
      const qty = dtfQuantityInput.value.trim() || "1";

      if (!width || !height || !qty) {
        setStatus("Preencha largura, altura e quantidade da arte DTF.", true);
        return;
      }

      addDtfBtn.disabled = true;
      const quote = await calculateItem({
        kind: "material",
        material_code: selectedMat,
        width_cm: width,
        height_cm: height,
        quantity: qty,
      });
      addDtfBtn.disabled = false;

      if (quote) {
        cartItems.push(quote);
        renderCart();
        setStatus(`Item ${quote.material_name} adicionado ao pedido!`);
      }
    });
  }

  // 2. Add Shirt
  if (addShirtBtn) {
    addShirtBtn.addEventListener("click", async () => {
      const shirtModel = calculator.querySelector("input[name='shirt_model']:checked")?.value || "camisa_algodao_menegotti";
      const color = shirtColorSelect?.value || "Preta";
      const size = shirtSizeSelect?.value || "M";
      const qty = shirtQuantityInput?.value.trim() || "1";

      if (!qty || parseInt(qty, 10) < 1) {
        setStatus("Informe uma quantidade válida de camisas.", true);
        return;
      }

      addShirtBtn.disabled = true;
      const quote = await calculateItem({
        kind: "produto",
        shirt_code: shirtModel,
        color,
        size,
        quantity: qty,
      });
      addShirtBtn.disabled = false;

      if (quote) {
        cartItems.push(quote);
        renderCart();
        setStatus(`Camisa ${quote.material_name} (${color}, ${size}) adicionada!`);
      }
    });
  }

  // 3. Add Service
  if (addServiceBtn) {
    addServiceBtn.addEventListener("click", async () => {
      const serviceModel = calculator.querySelector("input[name='extra_service_model']:checked")?.value || "ajuste_preparacao_arquivo";
      const qty = serviceQuantityInput?.value.trim() || "1";

      if (!qty || parseInt(qty, 10) < 1) {
        setStatus("Informe uma quantidade válida para o serviço.", true);
        return;
      }

      addServiceBtn.disabled = true;
      const quote = await calculateItem({
        kind: "servico",
        service_code: serviceModel,
        quantity: qty,
      });
      addServiceBtn.disabled = false;

      if (quote) {
        cartItems.push(quote);
        renderCart();
        setStatus(`${quote.material_name} adicionado!`);
      }
    });
  }

  // Initialize existing items from JSON script or hidden payload
  let loadedItems = [];
  const existingEl = document.getElementById("existing-order-items");
  if (existingEl) {
    try {
      const parsed = JSON.parse(existingEl.textContent || "[]");
      if (Array.isArray(parsed) && parsed.length > 0) {
        loadedItems = parsed;
      }
    } catch (_e) {}
  }
  if (loadedItems.length === 0 && calculationPayload && calculationPayload.value) {
    try {
      const parsedPayload = JSON.parse(calculationPayload.value);
      if (Array.isArray(parsedPayload)) {
        loadedItems = parsedPayload;
      } else if (parsedPayload && Array.isArray(parsedPayload.items)) {
        loadedItems = parsedPayload.items;
      }
    } catch (_e) {}
  }
  if (loadedItems.length > 0) {
    cartItems = loadedItems;
    renderCart();
  }

  // Intercept form submit to auto-add filled DTF inputs if cart was empty
  const orderForm = calculator.closest("form");
  if (orderForm) {
    orderForm.addEventListener("submit", async (e) => {
      if (cartItems.length === 0 && dtfWidthInput && dtfHeightInput) {
        const width = dtfWidthInput.value.trim();
        const height = dtfHeightInput.value.trim();
        const qty = (dtfQuantityInput && dtfQuantityInput.value.trim()) || "1";
        if (width && height && parseFloat(width) > 0 && parseFloat(height) > 0) {
          e.preventDefault();
          const selectedMat = calculator.querySelector("input[name='calculator_material']:checked")?.value || "dtf_textil";
          setStatus("Calculando item DTF antes de salvar…");
          const quote = await calculateItem({
            kind: "material",
            material_code: selectedMat,
            width_cm: width,
            height_cm: height,
            quantity: qty,
          });
          if (quote) {
            cartItems.push(quote);
            renderCart();
          }
          orderForm.submit();
          return;
        }
      }
      if (calculationPayload && cartItems.length > 0) {
        calculationPayload.value = JSON.stringify({ items: cartItems });
      }
    });
  }
})();

