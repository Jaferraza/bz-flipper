/**
 * CraftersMC Bazaar Flip Dashboard - Client Application
 * Vanilla JavaScript implementation.
 */

(function () {
  "use strict";

  // Application State
  const state = {
    items: [],
    favorites: new Set(),
    selectedItem: null,
    lookbackWindow: "1h",
    sortBy: "profit",
    sortDir: "desc",
    searchQuery: "",
    minProfit: null,
    minVolume: null,
    budgetCap: null,
    favoritesOnly: false,
    stale: false,
    lastRefreshAt: null,
    nextRefreshAt: null,
    refreshInProgress: false,
    etag: null,
    pollingIntervalId: null,
    countdownIntervalId: null,
    chartInstance: null,
    theme: "dark",
  };

  // DOM Elements
  const el = {
    themeToggleBtn: document.getElementById("themeToggleBtn"),
    themeIcon: document.getElementById("themeIcon"),
    refreshBtn: document.getElementById("refreshBtn"),
    refreshSpinner: document.getElementById("refreshSpinner"),
    staleNoticeBanner: document.getElementById("staleNoticeBanner"),
    staleMessage: document.getElementById("staleMessage"),
    statusDot: document.getElementById("statusDot"),
    statusText: document.getElementById("statusText"),
    lastRefreshTime: document.getElementById("lastRefreshTime"),
    nextRefreshCountdown: document.getElementById("nextRefreshCountdown"),
    itemCountDisplay: document.getElementById("itemCountDisplay"),
    searchInput: document.getElementById("searchInput"),
    clearSearchBtn: document.getElementById("clearSearchBtn"),
    lookbackSelect: document.getElementById("lookbackSelect"),
    sortSelect: document.getElementById("sortSelect"),
    sortDirBtn: document.getElementById("sortDirBtn"),
    sortDirIcon: document.getElementById("sortDirIcon"),
    minProfitInput: document.getElementById("minProfitInput"),
    minVolumeInput: document.getElementById("minVolumeInput"),
    budgetCapInput: document.getElementById("budgetCapInput"),
    favoritesOnlyCheckbox: document.getElementById("favoritesOnlyCheckbox"),
    favCount: document.getElementById("favCount"),
    resetFiltersBtn: document.getElementById("resetFiltersBtn"),
    emptyResetBtn: document.getElementById("emptyResetBtn"),
    loadingIndicator: document.getElementById("loadingIndicator"),
    emptyIndicator: document.getElementById("emptyIndicator"),
    tableContainer: document.getElementById("tableContainer"),
    marketTableBody: document.getElementById("marketTableBody"),
    cardsContainer: document.getElementById("cardsContainer"),
    lookbackLabels: document.querySelectorAll(".lookback-label"),
    // Modal elements
    detailModalBackdrop: document.getElementById("detailModalBackdrop"),
    modalItemTitle: document.getElementById("modalItemTitle"),
    modalItemId: document.getElementById("modalItemId"),
    modalStaleBadge: document.getElementById("modalStaleBadge"),
    closeModalBtn: document.getElementById("closeModalBtn"),
    modalDoneBtn: document.getElementById("modalDoneBtn"),
    modalFavoriteBtn: document.getElementById("modalFavoriteBtn"),
    modalBuyPrice: document.getElementById("modalBuyPrice"),
    modalBuyQty: document.getElementById("modalBuyQty"),
    modalSellPrice: document.getElementById("modalSellPrice"),
    modalSellQty: document.getElementById("modalSellQty"),
    modalSpread: document.getElementById("modalSpread"),
    modalTax: document.getElementById("modalTax"),
    modalNetProfit: document.getElementById("modalNetProfit"),
    modalRoi: document.getElementById("modalRoi"),
    modalBuyVolume: document.getElementById("modalBuyVolume"),
    modalSellVolume: document.getElementById("modalSellVolume"),
    modalBudgetRequired: document.getElementById("modalBudgetRequired"),
    modalCandidateQty: document.getElementById("modalCandidateQty"),
    modalLastFetch: document.getElementById("modalLastFetch"),
    queueProgressDisplay: document.getElementById("queueProgressDisplay"),
    catalogInput: document.getElementById("catalogInput"),
    catalogDatalist: document.getElementById("catalogDatalist"),
    addCatalogFavBtn: document.getElementById("addCatalogFavBtn"),
    itemHistoryChart: document.getElementById("itemHistoryChart"),
  };

  // Catalog cache
  let fullCatalog = [];

  // -------------------------------------------------------------------------
  // Initialization & Storage
  // -------------------------------------------------------------------------

  async function init() {
    loadTheme();
    bindEvents();
    startPolling();
    await syncFavoritesWithBackend();
    loadCatalog();
    fetchMarketData();
  }

  async function loadCatalog() {
    try {
      const res = await fetch("/api/items/catalog");
      if (!res.ok) return;
      const data = await res.json();
      fullCatalog = data.catalog || [];
      if (el.catalogDatalist) {
        el.catalogDatalist.innerHTML = "";
        fullCatalog.forEach((item) => {
          const opt = document.createElement("option");
          opt.value = item.itemId;
          const age = item.lastUpdated ? formatRelativeTime(item.lastUpdated) : "Never fetched";
          opt.textContent = `${item.displayName} (${item.itemId}) — ${age}`;
          el.catalogDatalist.appendChild(opt);
        });
      }
    } catch (e) {
      console.warn("Could not load full catalog:", e);
    }
  }

  async function syncFavoritesWithBackend() {
    try {
      const res = await fetch("/api/favorites");
      if (res.ok) {
        const data = await res.json();
        if (data.favorites && data.favorites.length) {
          state.favorites = new Set(data.favorites);
          localStorage.setItem("craftersmc_favorites", JSON.stringify(data.favorites));
        } else {
          loadFavoritesLocal();
          // Push local favorites to backend
          if (state.favorites.size > 0) {
            await fetch("/api/favorites", {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ favorites: Array.from(state.favorites) }),
            });
          }
        }
      }
    } catch (e) {
      loadFavoritesLocal();
    }
    updateFavoritesCount();
  }

  function loadFavoritesLocal() {
    try {
      const stored = localStorage.getItem("craftersmc_favorites");
      if (stored) {
        state.favorites = new Set(JSON.parse(stored));
      }
    } catch (e) {
      console.warn("Could not parse favorites from localStorage", e);
    }
  }

  function saveFavorites() {
    try {
      localStorage.setItem("craftersmc_favorites", JSON.stringify(Array.from(state.favorites)));
    } catch (e) {
      console.warn("Could not save favorites to localStorage", e);
    }
    updateFavoritesCount();
  }

  function updateFavoritesCount() {
    if (el.favCount) {
      el.favCount.textContent = state.favorites.size;
    }
  }

  async function toggleFavorite(itemId, event) {
    if (event) event.stopPropagation();
    const isNowFav = !state.favorites.has(itemId);
    if (isNowFav) {
      state.favorites.add(itemId);
    } else {
      state.favorites.delete(itemId);
    }
    saveFavorites();
    render();
    if (state.selectedItem && state.selectedItem.itemId === itemId) {
      updateModalFavoriteButton(itemId);
    }

    // Sync to backend & bump queue
    try {
      await fetch("/api/favorites", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ itemId: itemId, isFavorite: isNowFav }),
      });
    } catch (e) {
      console.warn("Could not sync favorite to server", e);
    }
  }

  // -------------------------------------------------------------------------
  // Theme Management
  // -------------------------------------------------------------------------

  function loadTheme() {
    const saved = localStorage.getItem("craftersmc_theme");
    if (saved) {
      state.theme = saved;
    } else if (window.matchMedia && window.matchMedia("(prefers-color-scheme: light)").matches) {
      state.theme = "light";
    } else {
      state.theme = "dark";
    }
    applyTheme();
  }

  function applyTheme() {
    document.documentElement.setAttribute("data-theme", state.theme);
    if (el.themeIcon) {
      el.themeIcon.textContent = state.theme === "dark" ? "🌙" : "☀️";
    }
    if (state.chartInstance) {
      renderChartHistory([]); // Refresh chart colors if modal open
    }
  }

  function toggleTheme() {
    state.theme = state.theme === "dark" ? "light" : "dark";
    localStorage.setItem("craftersmc_theme", state.theme);
    applyTheme();
  }

  // -------------------------------------------------------------------------
  // Polling Lifecycle & Visibility
  // -------------------------------------------------------------------------

  function startPolling() {
    stopPolling();
    // 10-minute cadence (600,000 ms)
    state.pollingIntervalId = setInterval(() => {
      fetchMarketData();
    }, 600000);

    // 1-second countdown timer
    state.countdownIntervalId = setInterval(updateCountdown, 1000);

    // Visibility listener: pause when hidden, resume on active
    document.addEventListener("visibilitychange", handleVisibilityChange);
  }

  function stopPolling() {
    if (state.pollingIntervalId) {
      clearInterval(state.pollingIntervalId);
      state.pollingIntervalId = null;
    }
    if (state.countdownIntervalId) {
      clearInterval(state.countdownIntervalId);
      state.countdownIntervalId = null;
    }
  }

  function handleVisibilityChange() {
    if (document.hidden) {
      // Tab hidden - pause countdown
      if (state.countdownIntervalId) {
        clearInterval(state.countdownIntervalId);
        state.countdownIntervalId = null;
      }
    } else {
      // Tab resumed - fetch latest snapshot immediately & restart timer
      fetchMarketData();
      if (!state.countdownIntervalId) {
        state.countdownIntervalId = setInterval(updateCountdown, 1000);
      }
    }
  }

  function updateCountdown() {
    if (!state.nextRefreshAt) {
      el.nextRefreshCountdown.textContent = "-";
      return;
    }
    const target = new Date(state.nextRefreshAt).getTime();
    const now = Date.now();
    const diff = Math.max(0, Math.floor((target - now) / 1000));

    const mins = Math.floor(diff / 60);
    const secs = diff % 60;
    el.nextRefreshCountdown.textContent = `${mins}m ${secs < 10 ? "0" : ""}${secs}s`;

    if (diff === 0 && !state.refreshInProgress) {
      fetchMarketData();
    }
  }

  // -------------------------------------------------------------------------
  // API Fetching & Caching
  // -------------------------------------------------------------------------

  async function fetchMarketData() {
    try {
      const params = new URLSearchParams();
      if (state.searchQuery) params.set("search", state.searchQuery);
      if (state.sortBy) params.set("sort_by", state.sortBy);
      if (state.sortDir) params.set("sort_dir", state.sortDir);
      if (state.minProfit !== null) params.set("min_profit", state.minProfit);
      if (state.minVolume !== null) params.set("min_volume", state.minVolume);
      if (state.budgetCap !== null) params.set("budget_cap", state.budgetCap);
      if (state.favoritesOnly) {
        params.set("favorites_only", "true");
        params.set("favorites", Array.from(state.favorites).join(","));
      }
      params.set("lookback_window", state.lookbackWindow);

      const headers = { Accept: "application/json" };
      if (state.etag) {
        headers["If-None-Match"] = state.etag;
      }

      const response = await fetch(`/api/market?${params.toString()}`, { headers });

      if (response.status === 304) {
        // Cache not modified
        updateStatusDisplay(false);
        return;
      }

      if (!response.ok) {
        throw new Error(`Server returned HTTP ${response.status}`);
      }

      const etagHeader = response.headers.get("ETag");
      if (etagHeader) state.etag = etagHeader;

      const data = await response.json();
      state.items = data.items || [];
      state.stale = !!data.stale;
      state.lastRefreshAt = data.lastRefreshAt;
      state.nextRefreshAt = data.nextRefreshAt;
      state.refreshInProgress = !!data.refreshInProgress;

      updateStatusDisplay(false);
      render();
    } catch (err) {
      console.error("Error fetching market data:", err);
      updateStatusDisplay(true, err.message);
    }
  }

  async function triggerManualRefresh() {
    try {
      el.refreshBtn.disabled = true;
      el.refreshSpinner.classList.add("spinning");

      const response = await fetch("/api/refresh", { method: "POST" });
      const res = await response.json();

      state.refreshInProgress = true;
      updateStatusDisplay(false);

      // Poll status for up to 30 seconds
      let attempts = 0;
      const pollInterval = setInterval(async () => {
        attempts++;
        try {
          const statusRes = await fetch("/api/status");
          const statusData = await statusRes.json();
          if (!statusData.refreshInProgress || attempts > 20) {
            clearInterval(pollInterval);
            el.refreshSpinner.classList.remove("spinning");
            el.refreshBtn.disabled = false;
            fetchMarketData();
          }
        } catch (e) {
          clearInterval(pollInterval);
          el.refreshSpinner.classList.remove("spinning");
          el.refreshBtn.disabled = false;
        }
      }, 1500);
    } catch (e) {
      console.error("Failed to trigger refresh", e);
      el.refreshSpinner.classList.remove("spinning");
      el.refreshBtn.disabled = false;
    }
  }

  function updateStatusDisplay(isError = false, errorMessage = "") {
    el.loadingIndicator.style.display = "none";

    if (isError) {
      el.statusDot.className = "status-indicator error";
      el.statusText.textContent = `Error: ${errorMessage || "Offline"}`;
      el.staleNoticeBanner.style.display = "flex";
      el.staleMessage.textContent = "Could not contact local backend. Showing cached state.";
      return;
    }

    if (state.stale) {
      el.statusDot.className = "status-indicator stale";
      el.statusText.textContent = state.refreshInProgress ? "Syncing upstream..." : "Stale Cache";
      el.staleNoticeBanner.style.display = "flex";
      el.staleMessage.textContent = "Data is older than 10m or upstream is updating. Displaying preserved good values.";
    } else {
      el.statusDot.className = "status-indicator";
      el.statusText.textContent = state.refreshInProgress ? "Syncing upstream..." : "Live & Synchronized";
      el.staleNoticeBanner.style.display = "none";
    }

    if (state.lastRefreshAt) {
      const d = new Date(state.lastRefreshAt);
      el.lastRefreshTime.textContent = d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
    } else {
      el.lastRefreshTime.textContent = "Pending";
    }

    el.itemCountDisplay.textContent = state.items.length;
    el.lookbackLabels.forEach((label) => {
      label.textContent = state.lookbackWindow;
    });
  }

  // -------------------------------------------------------------------------
  // Rendering
  // -------------------------------------------------------------------------

  function formatCoin(num) {
    if (num === null || num === undefined) return "-";
    return Number(num).toLocaleString(undefined, {
      minimumFractionDigits: 1,
      maximumFractionDigits: 1,
    });
  }

  function formatInt(num) {
    if (num === null || num === undefined) return "-";
    return Number(num).toLocaleString();
  }

  function formatRelativeTime(isoString) {
    if (!isoString) return "Never";
    const diffMs = Date.now() - new Date(isoString).getTime();
    if (isNaN(diffMs) || diffMs < 0) return "Now";
    const diffSec = Math.floor(diffMs / 1000);
    if (diffSec < 60) return `${diffSec}s ago`;
    const diffMin = Math.floor(diffSec / 60);
    if (diffMin < 60) return `${diffMin}m ago`;
    const diffHr = Math.floor(diffMin / 60);
    if (diffHr < 24) return `${diffHr}h ago`;
    return `${Math.floor(diffHr / 24)}d ago`;
  }

  function render() {
    if (state.items.length === 0) {
      el.tableContainer.style.display = "none";
      el.cardsContainer.style.display = "none";
      el.emptyIndicator.style.display = "flex";
      return;
    }

    el.emptyIndicator.style.display = "none";
    el.tableContainer.style.display = "block";
    el.cardsContainer.style.display = "flex";

    renderTable();
    renderCards();
  }

  function renderTable() {
    el.marketTableBody.innerHTML = "";
    const fragment = document.createDocumentFragment();

    state.items.forEach((item) => {
      const tr = document.createElement("tr");
      tr.addEventListener("click", () => openDetailModal(item.itemId));

      const isFav = state.favorites.has(item.itemId);

      // Price change indicator
      let diffHtml = '<span class="diff-neutral">-</span>';
      if (item.priceChange !== null && item.priceChange !== undefined) {
        if (item.priceChange > 0) {
          diffHtml = `<span class="diff-positive">+${formatCoin(item.priceChange)} (+${item.priceChangePercent}%)</span>`;
        } else if (item.priceChange < 0) {
          diffHtml = `<span class="diff-negative">${formatCoin(item.priceChange)} (${item.priceChangePercent}%)</span>`;
        } else {
          diffHtml = '<span class="diff-neutral">0.0 (0%)</span>';
        }
      }

      tr.innerHTML = `
        <td class="col-fav" style="text-align: center;">
          <button class="star-btn ${isFav ? "active" : ""}" aria-label="Toggle favorite" title="${isFav ? "Remove from watchlist" : "Add to watchlist"}">
            ${isFav ? "★" : "☆"}
          </button>
        </td>
        <td class="col-item">
          <div class="item-cell">
            <span class="item-name">${escapeHtml(item.displayName)}</span>
            <span class="item-id-sub">${escapeHtml(item.itemId)}</span>
          </div>
        </td>
        <td class="col-price num-cell">${formatCoin(item.buyOrderPrice)}</td>
        <td class="col-price num-cell">${formatCoin(item.sellOfferPrice)}</td>
        <td class="col-price num-cell">${formatCoin(item.spread)}</td>
        <td class="col-profit">
          <span class="profit-badge">${formatCoin(item.profitPerFlip)}</span>
        </td>
        <td class="col-roi">
          <span class="roi-badge">${item.roiPercent !== null ? item.roiPercent + "%" : "-"}</span>
        </td>
        <td class="col-change num-cell">${diffHtml}</td>
        <td class="col-volume num-cell">${formatInt(item.buyVolume)} / ${formatInt(item.sellVolume)}</td>
        <td class="col-updated num-cell" title="${item.lastUpdated || ""}"
          style="font-size:0.78rem; opacity:0.75;">${formatRelativeTime(item.lastUpdated)}</td>
        <td class="col-action">
          <button class="btn btn-outline btn-sm">Inspect</button>
        </td>
      `;

      // Handle star button click separately
      const starBtn = tr.querySelector(".star-btn");
      starBtn.addEventListener("click", (e) => toggleFavorite(item.itemId, e));

      fragment.appendChild(tr);
    });

    el.marketTableBody.appendChild(fragment);
  }

  function renderCards() {
    el.cardsContainer.innerHTML = "";
    const fragment = document.createDocumentFragment();

    state.items.forEach((item) => {
      const card = document.createElement("div");
      card.className = "market-card";
      card.addEventListener("click", () => openDetailModal(item.itemId));

      const isFav = state.favorites.has(item.itemId);

      let diffHtml = '<span class="diff-neutral">-</span>';
      if (item.priceChange !== null && item.priceChange !== undefined) {
        if (item.priceChange > 0) {
          diffHtml = `<span class="diff-positive">+${formatCoin(item.priceChange)}</span>`;
        } else if (item.priceChange < 0) {
          diffHtml = `<span class="diff-negative">${formatCoin(item.priceChange)}</span>`;
        } else {
          diffHtml = '<span class="diff-neutral">0.0</span>';
        }
      }

      card.innerHTML = `
        <div class="card-top">
          <div class="card-title-group">
            <button class="star-btn ${isFav ? "active" : ""}" aria-label="Toggle favorite">
              ${isFav ? "★" : "☆"}
            </button>
            <div class="item-cell">
              <span class="item-name">${escapeHtml(item.displayName)}</span>
              <span class="item-id-sub">${escapeHtml(item.itemId)}</span>
            </div>
          </div>
          <span class="profit-badge">+${formatCoin(item.profitPerFlip)}</span>
        </div>
        <div class="card-grid">
          <div class="card-metric">
            <span class="card-metric-label">Buy Order (Bid)</span>
            <span class="card-metric-val">${formatCoin(item.buyOrderPrice)}</span>
          </div>
          <div class="card-metric">
            <span class="card-metric-label">Sell Offer (Ask)</span>
            <span class="card-metric-val">${formatCoin(item.sellOfferPrice)}</span>
          </div>
          <div class="card-metric">
            <span class="card-metric-label">Spread</span>
            <span class="card-metric-val">${formatCoin(item.spread)}</span>
          </div>
          <div class="card-metric">
            <span class="card-metric-label">ROI (%)</span>
            <span class="card-metric-val">${item.roiPercent !== null ? item.roiPercent + "%" : "-"}</span>
          </div>
        </div>
        <div class="card-footer">
          <span>Change (${state.lookbackWindow}): ${diffHtml}</span>
          <span>Vol: ${formatInt(item.sellVolume)}</span>
        </div>
      `;

      const starBtn = card.querySelector(".star-btn");
      starBtn.addEventListener("click", (e) => toggleFavorite(item.itemId, e));

      fragment.appendChild(card);
    });

    el.cardsContainer.appendChild(fragment);
  }

  // -------------------------------------------------------------------------
  // Item Detail Modal & History Chart
  // -------------------------------------------------------------------------

  async function openDetailModal(itemId) {
    el.detailModalBackdrop.style.display = "flex";
    try {
      const response = await fetch(`/api/items/${itemId}`);
      if (!response.ok) throw new Error("Item not found");
      const data = await response.json();
      state.selectedItem = data.item;

      el.modalItemTitle.textContent = data.item.displayName || itemId;
      el.modalItemId.textContent = itemId;
      el.modalStaleBadge.style.display = data.item.stale ? "inline-flex" : "none";

      el.modalBuyPrice.textContent = formatCoin(data.item.buyOrderPrice);
      el.modalBuyQty.textContent = data.item.bestBuyQuantity ? `Depth: ${data.item.bestBuyQuantity}` : "Depth: -";

      el.modalSellPrice.textContent = formatCoin(data.item.sellOfferPrice);
      el.modalSellQty.textContent = data.item.bestSellQuantity ? `Depth: ${data.item.bestSellQuantity}` : "Depth: -";

      el.modalSpread.textContent = formatCoin(data.item.spread);
      el.modalTax.textContent = formatCoin(data.item.taxAmount);
      el.modalNetProfit.textContent = formatCoin(data.item.profitPerFlip);
      el.modalRoi.textContent = data.item.roiPercent !== null ? `${data.item.roiPercent}%` : "-";

      el.modalBuyVolume.textContent = formatInt(data.item.buyVolume);
      el.modalSellVolume.textContent = formatInt(data.item.sellVolume);

      el.modalBudgetRequired.textContent = formatCoin(data.item.requiredBudget);
      el.modalCandidateQty.textContent = data.item.candidateQuantity ? `Matched qty: ${data.item.candidateQuantity}` : "Depth: -";

      if (data.item.lastUpdated) {
        el.modalLastFetch.textContent = new Date(data.item.lastUpdated).toLocaleString();
      } else {
        el.modalLastFetch.textContent = "-";
      }

      updateModalFavoriteButton(itemId);
      renderChartHistory(data.history || []);
    } catch (e) {
      console.error("Error opening item details:", e);
    }
  }

  function updateModalFavoriteButton(itemId) {
    const isFav = state.favorites.has(itemId);
    el.modalFavoriteBtn.textContent = isFav ? "★ Remove from Watchlist" : "☆ Add to Watchlist";
  }

  function closeDetailModal() {
    el.detailModalBackdrop.style.display = "none";
    state.selectedItem = null;
  }

  function renderChartHistory(history) {
    if (state.chartInstance) {
      state.chartInstance.destroy();
      state.chartInstance = null;
    }

    if (!el.itemHistoryChart) return;
    const ctx = el.itemHistoryChart.getContext("2d");

    const labels = history.map((pt) => {
      const d = new Date(pt.capturedAt * 1000);
      return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
    });

    const sellPrices = history.map((pt) => pt.sellOfferPrice);
    const buyPrices = history.map((pt) => pt.buyOrderPrice);

    const isDark = state.theme === "dark";
    const gridColor = isDark ? "rgba(255, 255, 255, 0.08)" : "rgba(0, 0, 0, 0.08)";
    const textColor = isDark ? "#8b949e" : "#656d76";

    // Chart.js instance
    state.chartInstance = new Chart(ctx, {
      type: "line",
      data: {
        labels: labels.length ? labels : ["Now"],
        datasets: [
          {
            label: "Sell Offer (Ask)",
            data: sellPrices.length ? sellPrices : [state.selectedItem ? state.selectedItem.sellOfferPrice : 0],
            borderColor: "#f85149",
            backgroundColor: "rgba(248, 81, 73, 0.1)",
            borderWidth: 2,
            tension: 0.2,
            pointRadius: 3,
          },
          {
            label: "Buy Order (Bid)",
            data: buyPrices.length ? buyPrices : [state.selectedItem ? state.selectedItem.buyOrderPrice : 0],
            borderColor: "#58a6ff",
            backgroundColor: "rgba(88, 166, 255, 0.1)",
            borderWidth: 2,
            tension: 0.2,
            pointRadius: 3,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { display: false },
          tooltip: {
            mode: "index",
            intersect: false,
          },
        },
        scales: {
          x: {
            grid: { color: gridColor },
            ticks: { color: textColor, maxTicksLimit: 6 },
          },
          y: {
            grid: { color: gridColor },
            ticks: { color: textColor },
          },
        },
      },
    });
  }

  // -------------------------------------------------------------------------
  // Event Bindings
  // -------------------------------------------------------------------------

  function bindEvents() {
    el.themeToggleBtn.addEventListener("click", toggleTheme);
    el.refreshBtn.addEventListener("click", triggerManualRefresh);

    // Search input
    let searchDebounceTimer = null;
    el.searchInput.addEventListener("input", (e) => {
      state.searchQuery = e.target.value.trim();
      el.clearSearchBtn.style.display = state.searchQuery ? "block" : "none";
      clearTimeout(searchDebounceTimer);
      searchDebounceTimer = setTimeout(fetchMarketData, 250);
    });

    el.clearSearchBtn.addEventListener("click", () => {
      el.searchInput.value = "";
      state.searchQuery = "";
      el.clearSearchBtn.style.display = "none";
      fetchMarketData();
    });

    // Lookback Select
    el.lookbackSelect.addEventListener("change", (e) => {
      state.lookbackWindow = e.target.value;
      fetchMarketData();
    });

    // Sort column & direction
    el.sortSelect.addEventListener("change", (e) => {
      state.sortBy = e.target.value;
      fetchMarketData();
    });

    el.sortDirBtn.addEventListener("click", () => {
      state.sortDir = state.sortDir === "asc" ? "desc" : "asc";
      el.sortDirIcon.textContent = state.sortDir === "asc" ? "↑" : "↓";
      fetchMarketData();
    });

    // Thresholds
    let filterDebounceTimer = null;
    function handleThresholdChange() {
      clearTimeout(filterDebounceTimer);
      filterDebounceTimer = setTimeout(() => {
        state.minProfit = el.minProfitInput.value ? parseFloat(el.minProfitInput.value) : null;
        state.minVolume = el.minVolumeInput.value ? parseInt(el.minVolumeInput.value, 10) : null;
        state.budgetCap = el.budgetCapInput.value ? parseFloat(el.budgetCapInput.value) : null;
        fetchMarketData();
      }, 300);
    }

    el.minProfitInput.addEventListener("input", handleThresholdChange);
    el.minVolumeInput.addEventListener("input", handleThresholdChange);
    el.budgetCapInput.addEventListener("input", handleThresholdChange);

    // Favorites only toggle
    el.favoritesOnlyCheckbox.addEventListener("change", (e) => {
      state.favoritesOnly = e.target.checked;
      fetchMarketData();
    });

    // Reset filters
    function resetFilters() {
      el.searchInput.value = "";
      el.clearSearchBtn.style.display = "none";
      el.minProfitInput.value = "";
      el.minVolumeInput.value = "";
      el.budgetCapInput.value = "";
      el.favoritesOnlyCheckbox.checked = false;
      el.sortSelect.value = "profit";
      state.searchQuery = "";
      state.minProfit = null;
      state.minVolume = null;
      state.budgetCap = null;
      state.favoritesOnly = false;
      state.sortBy = "profit";
      state.sortDir = "desc";
      el.sortDirIcon.textContent = "↓";
      fetchMarketData();
    }

    el.resetFiltersBtn.addEventListener("click", resetFilters);
    el.emptyResetBtn.addEventListener("click", resetFilters);

    // Modal controls
    el.closeModalBtn.addEventListener("click", closeDetailModal);
    el.modalDoneBtn.addEventListener("click", closeDetailModal);
    el.detailModalBackdrop.addEventListener("click", (e) => {
      if (e.target === el.detailModalBackdrop) closeDetailModal();
    });

    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape" && el.detailModalBackdrop.style.display === "flex") {
        closeDetailModal();
      }
    });

    // Catalog quick star handler
    if (el.addCatalogFavBtn && el.catalogInput) {
      el.addCatalogFavBtn.addEventListener("click", async () => {
        const raw = el.catalogInput.value.trim();
        if (!raw) return;
        const match = fullCatalog.find(
          (c) =>
            c.itemId.toLowerCase() === raw.toLowerCase() ||
            c.displayName.toLowerCase() === raw.toLowerCase()
        );
        const targetId = match ? match.itemId : raw;
        await toggleFavorite(targetId);
        el.catalogInput.value = "";
        if (el.queueProgressDisplay) {
          el.queueProgressDisplay.textContent = `★ Bumped ${targetId} to front of queue!`;
        }
        fetchMarketData();
      });

      el.catalogInput.addEventListener("keydown", (e) => {
        if (e.key === "Enter") {
          el.addCatalogFavBtn.click();
        }
      });
    }

    el.modalFavoriteBtn.addEventListener("click", () => {
      if (state.selectedItem) {
        toggleFavorite(state.selectedItem.itemId);
      }
    });

    // 4-second status poller for queue progress and live row streaming
    setInterval(pollStatus, 4000);
  }

  async function pollStatus() {
    try {
      const res = await fetch("/api/status");
      if (!res.ok) return;
      const s = await res.json();
      if (s.queueProgress && el.queueProgressDisplay) {
        const q = s.queueProgress;
        if (q.total > 0 && q.completed < q.total) {
          el.queueProgressDisplay.textContent = `[${q.completed}/${q.total}] ${q.currentItem || "Pacing 7.5s..."}`;
        } else if (q.total > 0 && q.completed >= q.total) {
          el.queueProgressDisplay.textContent = `Done (${q.total} items)`;
        }
      }
      if (s.totalItems !== state.items.length) {
        fetchMarketData();
      }
    } catch (e) {}
  }

  function escapeHtml(str) {
    if (!str) return "";
    return String(str)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#039;");
  }

  // Run on DOM ready
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
