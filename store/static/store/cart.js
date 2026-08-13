// Cart interactions without full page reloads.
//
// Both forms this touches (#add-to-cart-form, .remove-form) are real
// <form method="post"> elements pointing at real Django views. This script
// only intercepts their submit event to swap in a fetch() call instead —
// if JS fails to load or errors out, the forms still work exactly as
// before (full page navigation), so this is progressive enhancement, not
// a hard dependency.

function getCookie(name) {
  const match = document.cookie.match(new RegExp(`(?:^|; )${name}=([^;]*)`));
  return match ? decodeURIComponent(match[1]) : null;
}

const csrftoken = getCookie("csrftoken");

function updateCartBadge(count) {
  const badge = document.getElementById("cart-badge");
  if (!badge) return;
  if (count > 0) {
    badge.textContent = count;
    badge.style.display = "";
  } else {
    badge.style.display = "none";
  }
}

function showEmptyCart() {
  const container = document.getElementById("cart-container");
  if (!container) return;
  const shopUrl = container.dataset.shopUrl || "/";
  container.innerHTML = `
    <div class="empty-state" id="cart-empty-state">
      <h2>Your Cart is Empty</h2>
      <p style="margin-bottom:24px;">Add some gear to get started.</p>
      <a href="${shopUrl}" style="padding:12px 28px; background:var(--blueprint); color:#fff; border-radius:var(--radius); font-weight:600;">Browse the Shop →</a>
    </div>`;
}

// --- Add to cart (product detail page) --------------------------------
const addForm = document.getElementById("add-to-cart-form");
if (addForm) {
  addForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const btn = document.getElementById("add-to-cart-btn");
    const statusEl = document.getElementById("add-to-cart-status");
    const originalLabel = btn.textContent;
    btn.disabled = true;

    try {
      const res = await fetch(addForm.action, {
        method: "POST",
        headers: { "X-Requested-With": "XMLHttpRequest", "X-CSRFToken": csrftoken },
        body: new FormData(addForm),
      });
      if (!res.ok) throw new Error(`Request failed (${res.status})`);
      const data = await res.json();

      updateCartBadge(data.cart_count);
      btn.textContent = "Added ✓";
      if (statusEl) {
        statusEl.textContent = `${data.quantity_added} added to cart — ${data.line_quantity} total in cart.`;
      }
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

// --- Remove from cart (cart page) --------------------------------------
document.querySelectorAll(".remove-form").forEach((form) => {
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const btn = form.querySelector("button[type=submit]");
    const productId = form.dataset.productId;
    btn.disabled = true;

    try {
      const res = await fetch(form.action, {
        method: "POST",
        headers: { "X-Requested-With": "XMLHttpRequest", "X-CSRFToken": csrftoken },
      });
      if (!res.ok) throw new Error(`Request failed (${res.status})`);
      const data = await res.json();

      updateCartBadge(data.cart_count);

      const row = document.getElementById(`cart-row-${productId}`);
      if (row) row.remove();

      if (data.cart_empty) {
        showEmptyCart();
      } else {
        const totalEl = document.getElementById("cart-total");
        if (totalEl) totalEl.textContent = `$${data.total}`;
      }
    } catch (err) {
      btn.disabled = false;
      alert("Couldn't remove that item — please try again.");
    }
  });
});
