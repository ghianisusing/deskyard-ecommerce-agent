// Small motion helpers shared by the store scripts. Purely decorative:
// if this file fails to load, every page still works and nothing stays
// hidden, because the CSS only hides .reveal elements under html.js and
// shows them again as soon as they are marked visible.
(function () {
  const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  // --- Scroll reveal -----------------------------------------------------
  // Elements rise in as they enter the viewport. Each batch is staggered
  // by its position (--i) so a row of cards cascades rather than popping
  // in all at once.
  const observer =
    !reduceMotion && "IntersectionObserver" in window
      ? new IntersectionObserver(
          (entries) => {
            let batch = 0;
            entries.forEach((entry) => {
              if (!entry.isIntersecting) return;
              entry.target.style.setProperty("--i", batch++);
              entry.target.classList.add("is-visible");
              observer.unobserve(entry.target);
            });
          },
          { rootMargin: "0px 0px -40px 0px", threshold: 0.08 }
        )
      : null;

  const REVEAL_SELECTOR = ".product-card, .cart-row, .order-card, .empty-state, .cart-summary, .receipt, .auth-card";

  function reveal(root = document) {
    let onScreen = 0;
    root.querySelectorAll(REVEAL_SELECTOR).forEach((el) => {
      if (el.classList.contains("reveal")) return;
      el.classList.add("reveal");
      // Anything already in view animates in straight away rather than
      // waiting for the observer, so above-the-fold content never depends
      // on it firing.
      const rect = el.getBoundingClientRect();
      if (!observer || (rect.top < window.innerHeight && rect.bottom > 0)) {
        el.style.setProperty("--i", onScreen++);
        requestAnimationFrame(() => el.classList.add("is-visible"));
        // rAF doesn't run in a background tab; make sure it still shows.
        setTimeout(() => el.classList.add("is-visible"), 50);
        return;
      }
      observer.observe(el);
    });

    // Photos fade in once decoded instead of painting in pieces.
    root.querySelectorAll(".product-visual img, .thumb img").forEach((img) => {
      if (img.classList.contains("fade-img")) return;
      const done = () => img.classList.add("is-loaded");
      img.classList.add("fade-img");
      if (img.complete) done();
      else {
        img.addEventListener("load", done, { once: true });
        img.addEventListener("error", done, { once: true });
      }
    });
  }

  // --- Value flash -------------------------------------------------------
  // A number that changed in place (a total, a subtotal, the cart badge)
  // gives a quick flash so the eye catches that it moved.
  function flash(el) {
    if (!el) return;
    el.classList.remove("value-flash");
    void el.offsetWidth; // restart the animation
    el.classList.add("value-flash");
  }

  // --- Collapse and remove an element -----------------------------------
  function collapseAndRemove(el, done) {
    if (!el) return done && done();
    if (reduceMotion) {
      el.remove();
      return done && done();
    }
    el.style.height = `${el.offsetHeight}px`;
    void el.offsetHeight;
    el.classList.add("is-removing");
    el.style.height = "0px";
    setTimeout(() => {
      el.remove();
      if (done) done();
    }, 460);
  }

  window.DeskyardFX = { reveal, flash, collapseAndRemove, reduceMotion };

  reveal();

  // One gentle nudge of the chat button a few seconds in, once per visit.
  const toggle = document.getElementById("chat-toggle");
  if (toggle && !reduceMotion) {
    let nudged = false;
    try { nudged = sessionStorage.getItem("deskie-nudged") === "1"; } catch (e) { /* storage blocked */ }
    if (!nudged) {
      setTimeout(() => {
        if (toggle.getAttribute("aria-expanded") === "true") return;
        toggle.classList.add("nudge");
        toggle.addEventListener("animationend", () => toggle.classList.remove("nudge"), { once: true });
        try { sessionStorage.setItem("deskie-nudged", "1"); } catch (e) { /* storage blocked */ }
      }, 4000);
    }
  }
})();
