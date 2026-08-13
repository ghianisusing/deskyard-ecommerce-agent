// Category chips, pagination, and search on the shop page update in place
// instead of doing a full page navigation. The real reason this matters:
// a normal <a href> or form submit triggers the browser's default
// scroll-to-top behavior on navigation. Since this only ever swaps DOM
// content (no navigation actually happens), scroll position is
// untouched — which is the whole point.
//
// No backend changes needed: this fetches the same URLs the plain links
// already pointed to, gets back the full server-rendered page (same as a
// normal click would receive), and just pulls out the #product-results
// fragment instead of using the whole document. If anything goes wrong,
// it falls back to a real navigation, so this can never leave a click
// looking like it did nothing.
(function () {
  const resultsEl = document.getElementById("product-results");
  if (!resultsEl) return;

  function bindResultLinks() {
    resultsEl
      .querySelectorAll(".category-chips a, .pagination a, .clear-filters")
      .forEach((link) => {
        link.addEventListener("click", (e) => {
          e.preventDefault();
          loadResults(link.href);
        });
      });

    const form = resultsEl.querySelector(".filter-bar");
    if (form) {
      form.addEventListener("submit", (e) => {
        e.preventDefault();
        const params = new URLSearchParams(new FormData(form));
        const query = params.toString();
        loadResults(query ? `${window.location.pathname}?${query}` : window.location.pathname);
      });
    }
  }

  async function loadResults(url, { pushHistory = true, scrollY = window.scrollY } = {}) {
    try {
      const res = await fetch(url, { headers: { "X-Requested-With": "XMLHttpRequest" } });
      if (!res.ok) throw new Error(`Request failed (${res.status})`);
      const html = await res.text();
      const freshResults = new DOMParser().parseFromString(html, "text/html").getElementById(
        "product-results"
      );
      if (!freshResults) {
        window.location.href = url;
        return;
      }

      resultsEl.innerHTML = freshResults.innerHTML;
      bindResultLinks(); // old listeners went away with the old DOM nodes
      if (pushHistory) history.pushState({ shopFilters: true, scrollY }, "", url);

      // preventDefault() stops the browser from navigating, but it does
      // NOT stop the browser from re-clamping scroll position when
      // swapping in shorter content leaves the page shorter than the
      // current scroll offset — that's a separate, automatic reflow
      // behavior. Restore the position explicitly, after layout has had
      // a chance to settle from the innerHTML swap.
      requestAnimationFrame(() => window.scrollTo(0, scrollY));
    } catch (err) {
      // Never leave a click silently doing nothing — fall back to a real
      // navigation, which is exactly what would've happened without this
      // script running at all.
      window.location.href = url;
    }
  }

  bindResultLinks();

  // Support the browser back/forward buttons after filtering around,
  // restoring whatever scroll position was saved when that history entry
  // was created.
  window.addEventListener("popstate", (e) => {
    const savedScrollY = e.state && typeof e.state.scrollY === "number" ? e.state.scrollY : 0;
    loadResults(window.location.href, { pushHistory: false, scrollY: savedScrollY });
  });
})();
