// Cart interactions without full page reloads.
//
// Every form this touches (#add-to-cart-form, .update-form, .remove-form)
// is a real <form method="post"> pointing at a real Django view. This
// script only intercepts their submit event to swap in a fetch() call
// instead — if JS fails to load or errors out, the forms still work
// exactly as before (full page navigation), so this is progressive
// enhancement, not a hard dependency.

function getCookie(name) {
  const match = document.cookie.match(new RegExp(`(?:^|; )${name}=([^;]*)`));
  return match ? decodeURIComponent(match[1]) : null;
}

const csrftoken = getCookie("csrftoken");
const ajaxHeaders = { "X-Requested-With": "XMLHttpRequest", "X-CSRFToken": csrftoken };

async function postForm(form) {
  const res = await fetch(form.action, { method: "POST", headers: ajaxHeaders, body: new FormData(form) });
  const data = await res.json().catch(() => ({}));
  if (!res.ok || data.ok === false) throw new Error(data.error || `Request failed (${res.status})`);
  return data;
}

function updateCartBadge(count) {
  const badge = document.getElementById("cart-badge");
  if (!badge) return;
  badge.textContent = count;
  badge.setAttribute("aria-label", `${count} items`);
  badge.hidden = !(count > 0);
  badge.classList.remove("bump");
  void badge.offsetWidth; // restart the animation
  badge.classList.add("bump");

  const countLine = document.getElementById("cart-count-line");
  if (countLine) countLine.textContent = `${count} item${count === 1 ? "" : "s"}`;
}

function setCartTotal(total) {
  const totalEl = document.getElementById("cart-total");
  if (totalEl) totalEl.textContent = `$${total}`;
}

let toastTimer = null;
function showToast(message, link) {
  const toast = document.getElementById("toast");
  if (!toast) return;
  toast.textContent = message;
  if (link) {
    const a = document.createElement("a");
    a.href = link.href;
    a.textContent = link.label;
    toast.appendChild(a);
  }
  toast.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { toast.hidden = true; }, 4000);
}

function showCartError(message) {
  const el = document.getElementById("cart-error");
  if (!el) return;
  el.textContent = message;
  el.hidden = !message;
}

function showEmptyCart() {
  const container = document.getElementById("cart-container");
  if (!container) return;
  const shopUrl = container.dataset.shopUrl || "/";
  container.innerHTML = `
    <div class="empty-state" id="cart-empty-state">
      <h2>Your Cart is Empty</h2>
      <p>Add some gear to get started.</p>
      <a href="${shopUrl}" class="btn">Browse the Shop →</a>
    </div>`;
}

// --- Quantity steppers (product page + cart rows) ----------------------
// The -/+ buttons nudge the number input within its min/max. On cart rows
// (data-autosubmit) a change is saved shortly after the last click, so
// tapping + three times sends one request, not three.
function clampQuantity(input, value = parseInt(input.value, 10)) {
  const min = Number(input.min) || 1;
  const max = input.max ? Number(input.max) : Infinity;
  if (Number.isNaN(value)) value = min;
  return Math.min(Math.max(value, min), max);
}

function syncStepperButtons(stepper) {
  const input = stepper.querySelector("input[type=number]");
  const value = clampQuantity(input);
  stepper.querySelector('[data-step="-1"]').disabled = value <= (Number(input.min) || 1);
  stepper.querySelector('[data-step="1"]').disabled = input.max !== "" && value >= Number(input.max);
}

document.querySelectorAll("[data-stepper]").forEach((stepper) => {
  const input = stepper.querySelector("input[type=number]");
  const form = stepper.closest("form");
  let saveTimer = null;

  const scheduleSave = () => {
    if (!stepper.hasAttribute("data-autosubmit")) return;
    clearTimeout(saveTimer);
    saveTimer = setTimeout(() => form.requestSubmit(), 400);
  };

  stepper.querySelectorAll("[data-step]").forEach((btn) => {
    btn.addEventListener("click", () => {
      input.value = clampQuantity(input, clampQuantity(input) + Number(btn.dataset.step));
      syncStepperButtons(stepper);
      scheduleSave();
    });
  });

  // Enter in a cart quantity box should save, not jump to checkout.
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && stepper.hasAttribute("data-autosubmit")) {
      e.preventDefault();
      input.dispatchEvent(new Event("change"));
    }
  });

  input.addEventListener("change", () => {
    input.value = clampQuantity(input);
    syncStepperButtons(stepper);
    scheduleSave();
  });

  syncStepperButtons(stepper);
});

// --- Add to cart (product detail page) --------------------------------
const addForm = document.getElementById("add-to-cart-form");
if (addForm) {
  addForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const btn = document.getElementById("add-to-cart-btn");
    const statusEl = document.getElementById("add-to-cart-status");
    const originalLabel = btn.textContent;
    btn.disabled = true;
    btn.textContent = "Adding…";

    try {
      const data = await postForm(addForm);
      updateCartBadge(data.cart_count);
      btn.textContent = "Added ✓";
      if (statusEl) statusEl.textContent = `${data.line_quantity} in your cart.`;
      showToast(`${data.quantity_added} × ${data.product_name} added`, {
        href: document.getElementById("cart-link")?.href || "/cart/",
        label: "View cart →",
      });
    } catch (err) {
      btn.textContent = "Couldn't add — try again";
      if (statusEl) statusEl.textContent = "";
    } finally {
      setTimeout(() => {
        btn.textContent = originalLabel;
        btn.disabled = false;
      }, 1400);
    }
  });
}

// --- Change quantity (cart page) ---------------------------------------
document.querySelectorAll(".update-form").forEach((form) => {
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const row = document.getElementById(`cart-row-${form.dataset.productId}`);
    const input = form.querySelector("input[name=quantity]");
    row?.classList.add("is-busy");
    showCartError("");

    try {
      const data = await postForm(form);
      input.value = data.line_quantity;
      if (data.max_quantity > 0) input.max = data.max_quantity;
      syncStepperButtons(form.querySelector("[data-stepper]"));
      const subtotalEl = document.getElementById(`cart-subtotal-${form.dataset.productId}`);
      if (subtotalEl) subtotalEl.textContent = `$${data.line_subtotal}`;
      setCartTotal(data.total);
      updateCartBadge(data.cart_count);
    } catch (err) {
      showCartError(err.message.startsWith("Request failed") ? "Couldn't update that quantity — please try again." : err.message);
    } finally {
      row?.classList.remove("is-busy");
    }
  });
});

// --- Remove from cart (cart page) --------------------------------------
document.querySelectorAll(".remove-form").forEach((form) => {
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const btn = form.querySelector("button[type=submit]");
    const row = document.getElementById(`cart-row-${form.dataset.productId}`);
    btn.disabled = true;
    showCartError("");

    try {
      const data = await postForm(form);
      updateCartBadge(data.cart_count);

      if (data.cart_empty) {
        showEmptyCart();
        return;
      }
      setCartTotal(data.total);
      if (row) {
        row.classList.add("is-removing");
        setTimeout(() => row.remove(), 250);
      }
    } catch (err) {
      btn.disabled = false;
      showCartError("Couldn't remove that item — please try again.");
    }
  });
});
