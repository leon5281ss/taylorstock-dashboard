const state = {
  data: null,
  stocks: [],
  filter: "全部",
  search: "",
  sortDesc: true,
};

const els = {
  summary: document.querySelector("#summaryCards"),
  tableBody: document.querySelector("#stockTableBody"),
  mobileCards: document.querySelector("#mobileCards"),
  search: document.querySelector("#searchInput"),
  chips: [...document.querySelectorAll(".chip")],
  sortScore: document.querySelector("#sortScoreButton"),
  refresh: document.querySelector("#refreshButton"),
  generatedAt: document.querySelector("#generatedAt"),
  dialog: document.querySelector("#detailDialog"),
  dialogCode: document.querySelector("#dialogCode"),
  dialogTitle: document.querySelector("#dialogTitle"),
  dialogContent: document.querySelector("#dialogContent"),
  closeDialog: document.querySelector("#closeDialog"),
};

function isNumber(value) {
  return typeof value === "number" && Number.isFinite(value);
}

function formatNumber(value, digits = 0) {
  if (!isNumber(value)) return "資料不足";
  return new Intl.NumberFormat("zh-Hant-TW", {
    maximumFractionDigits: digits,
    minimumFractionDigits: digits,
  }).format(value);
}

function formatMoney(value) {
  if (!isNumber(value)) return "資料不足";
  return `$${formatNumber(value, 0)}`;
}

function formatPercent(value) {
  if (!isNumber(value)) return String(value ?? "資料不足");
  return `${(value * 100).toFixed(2)}%`;
}

function formatPnlRate(value) {
  if (!isNumber(value)) return String(value ?? "資料不足");
  const sign = value > 0 ? "+" : "";
  return `${sign}${value.toFixed(2)}%`;
}

function toneClass(value) {
  if (!isNumber(value)) return "neutral";
  if (value > 0) return "positive";
  if (value < 0) return "negative";
  return "neutral";
}

function statusBadge(status) {
  const safe = status || "資料不足";
  return `<span class="badge status-${safe}">${safe}</span>`;
}

function splitReasons(reasons) {
  if (Array.isArray(reasons)) return reasons.filter(Boolean);
  if (!reasons) return [];
  return String(reasons)
    .split(/[；\n]/)
    .map((item) => item.trim())
    .filter(Boolean);
}

function topReasons(stock, count = 3) {
  const reasons = splitReasons(stock.riskReasons);
  return reasons.length ? reasons.slice(0, count) : ["尚無主要警訊"];
}

function reasonList(stock, count) {
  const items = typeof count === "number" ? topReasons(stock, count) : splitReasons(stock.riskReasons);
  return `<ul class="reason-list">${items.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul>`;
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

async function loadData() {
  if (window.STOCK_DASHBOARD_DATA) {
    return window.STOCK_DASHBOARD_DATA;
  }
  const response = await fetch("data/stocks.json", { cache: "no-store" });
  if (!response.ok) throw new Error(`資料讀取失敗：${response.status}`);
  return response.json();
}

function filteredStocks() {
  const keyword = state.search.trim().toLowerCase();
  return state.stocks
    .filter((stock) => {
      if (state.filter === "人工確認") return stock.manualCheck === "是";
      if (state.filter !== "全部") return stock.status === state.filter;
      return true;
    })
    .filter((stock) => {
      if (!keyword) return true;
      return `${stock.code} ${stock.name}`.toLowerCase().includes(keyword);
    })
    .sort((a, b) => {
      const av = isNumber(a.totalScore) ? a.totalScore : -1;
      const bv = isNumber(b.totalScore) ? b.totalScore : -1;
      return state.sortDesc ? bv - av : av - bv;
    });
}

function renderSummary() {
  const s = state.data.summary || {};
  const cards = s.positionAmountsPublished
    ? [
        ["總市值", formatMoney(s.totalMarketValue)],
        ["總未實現損益", formatMoney(s.totalUnrealizedPnl)],
        ["整體報酬率", formatPercent(s.overallReturnRate)],
        ["出場警訊", formatNumber(s.exitCount)],
        ["減碼警訊", formatNumber(s.reduceCount)],
        ["人工確認", formatNumber(s.manualCheckCount)],
      ]
    : [
        ["追蹤股票", formatNumber(s.stockCount)],
        ["平均分數", isNumber(s.averageScore) ? s.averageScore.toFixed(1) : "資料不足"],
        ["資料日期", s.asOf || "資料不足"],
        ["出場警訊", formatNumber(s.exitCount)],
        ["減碼警訊", formatNumber(s.reduceCount)],
        ["人工確認", formatNumber(s.manualCheckCount)],
      ];
  els.summary.innerHTML = cards
    .map(([label, value]) => `<article class="summary-card"><span>${label}</span><strong>${value}</strong></article>`)
    .join("");
}

function renderTable(stocks) {
  els.tableBody.innerHTML = stocks
    .map(
      (stock) => `
        <tr>
          <td class="sticky-col code-col">${escapeHtml(stock.code)}</td>
          <td class="sticky-col name-col">${escapeHtml(stock.name)}</td>
          <td class="category-cell">${escapeHtml(stock.category || "")}</td>
          <td>${formatMoney(stock.price)}</td>
          <td class="${toneClass(stock.unrealizedPnlRate)}">${formatPnlRate(stock.unrealizedPnlRate)}</td>
          <td><strong>${isNumber(stock.totalScore) ? stock.totalScore : "資料不足"}</strong></td>
          <td>${statusBadge(stock.status)}</td>
          <td>${reasonList(stock, 3)}</td>
          <td>${stock.manualCheck === "是" ? "是" : "否"}</td>
          <td>${escapeHtml(stock.updatedAt || "資料不足")}</td>
          <td>${escapeHtml(stock.dataQualityStatus || "資料不足")}</td>
          <td><button class="detail-button" type="button" data-code="${escapeHtml(stock.code)}">展開詳情</button></td>
        </tr>
      `
    )
    .join("");
}

function renderCards(stocks) {
  els.mobileCards.innerHTML = stocks
    .map(
      (stock) => `
        <article class="stock-card">
          <div class="card-top">
            <div class="card-title">
              <strong>${escapeHtml(stock.code)} ${escapeHtml(stock.name)}</strong>
              <span class="muted">${escapeHtml(stock.category || "")}</span>
            </div>
            ${statusBadge(stock.status)}
          </div>
          <div class="card-metrics">
            <div class="metric"><span>總分</span><strong>${isNumber(stock.totalScore) ? stock.totalScore : "資料不足"}</strong></div>
            <div class="metric"><span>最新價格</span><strong>${formatMoney(stock.price)}</strong></div>
            <div class="metric"><span>損益率</span><strong class="${toneClass(stock.unrealizedPnlRate)}">${formatPnlRate(stock.unrealizedPnlRate)}</strong></div>
            <div class="metric"><span>資料品質</span><strong>${escapeHtml(stock.dataQualityStatus || "資料不足")}</strong></div>
          </div>
          <div class="card-row">
            <span class="muted">人工確認</span>
            <strong>${stock.manualCheck === "是" ? "是" : "否"}</strong>
          </div>
          ${reasonList(stock, 3)}
          <button class="detail-button mobile-toggle" type="button" data-code="${escapeHtml(stock.code)}">查看完整資料</button>
          <div class="card-details" id="card-detail-${escapeHtml(stock.code)}" hidden></div>
        </article>
      `
    )
    .join("");
}

function renderDetailHtml(stock) {
  const sections = [
    ["公開摘要", {
      股票代號: stock.code,
      股票名稱: stock.name,
      投資分類: stock.category,
      最新價格: stock.price,
      損益率: stock.unrealizedPnlRate,
      總分: stock.totalScore,
      狀態: stock.status,
      主要警訊摘要: topReasons(stock, 3).join("；"),
      是否需要人工確認: stock.manualCheck,
      更新日期: stock.updatedAt,
      資料品質狀態: stock.dataQualityStatus,
    }],
    ["技術面", {
      MA20: stock.technical?.ma20,
      MA60: stock.technical?.ma60,
      MA120: stock.technical?.ma120,
      K: stock.technical?.k,
      D: stock.technical?.d,
      J: stock.technical?.j,
      MACD: stock.technical?.macd,
      RSI14: stock.technical?.rsi,
    }],
    ["分數", {
      技術面: stock.scores?.technical,
      基本面: stock.scores?.fundamental,
      籌碼面: stock.scores?.chip,
      新聞與產業: stock.scores?.news,
      總分: stock.scores?.total,
    }],
    ["基本面", stock.details?.revenue || {}],
    ["籌碼", stock.details?.chip || {}],
    ["財報估值", stock.details?.financial || {}],
    ["新聞風險", stock.details?.news || {}],
  ];
  const sectionHtml = sections
    .map(([title, data]) => {
      const rows = Object.entries(data || {})
        .slice(0, 12)
        .map(([key, value]) => `<div class="kv"><span>${escapeHtml(key)}</span><strong>${escapeHtml(displayValue(value))}</strong></div>`)
        .join("");
      return `<section class="detail-section"><h3>${title}</h3>${rows || '<p class="muted">API 未取得</p>'}</section>`;
    })
    .join("");
  return `
    <section class="detail-section">
      <h3>完整主要理由</h3>
      ${reasonList(stock)}
      <p class="muted">資料來源與日期：${escapeHtml(stock.details?.score?.資料來源與日期 || stock.updatedAt || "資料不足")}</p>
    </section>
    <div class="detail-grid">${sectionHtml}</div>
  `;
}

function displayValue(value) {
  if (isNumber(value)) {
    if (Math.abs(value) < 1 && value !== 0) return formatPercent(value);
    return formatNumber(value, 2);
  }
  if (value === null || value === undefined || value === "") return "API 未取得";
  if (typeof value === "object") return "API 未取得";
  return value ?? "資料不足";
}

function openDetail(code) {
  const stock = state.stocks.find((item) => item.code === code);
  if (!stock) return;
  els.dialogCode.textContent = `${stock.code} | ${stock.status}`;
  els.dialogTitle.textContent = stock.name;
  els.dialogContent.innerHTML = renderDetailHtml(stock);
  if (typeof els.dialog.showModal === "function") {
    els.dialog.showModal();
  }
}

function toggleMobileDetail(code) {
  const stock = state.stocks.find((item) => item.code === code);
  const target = document.querySelector(`#card-detail-${CSS.escape(code)}`);
  if (!stock || !target) return;
  const willOpen = target.hasAttribute("hidden");
  document.querySelectorAll(".card-details").forEach((item) => item.setAttribute("hidden", ""));
  if (willOpen) {
    target.innerHTML = renderDetailHtml(stock);
    target.removeAttribute("hidden");
  }
}

function render() {
  const stocks = filteredStocks();
  renderSummary();
  renderTable(stocks);
  renderCards(stocks);
}

function bindEvents() {
  els.search.addEventListener("input", (event) => {
    state.search = event.target.value;
    render();
  });

  els.chips.forEach((chip) => {
    chip.addEventListener("click", () => {
      els.chips.forEach((item) => item.classList.remove("active"));
      chip.classList.add("active");
      state.filter = chip.dataset.filter;
      render();
    });
  });

  els.sortScore.addEventListener("click", () => {
    state.sortDesc = !state.sortDesc;
    els.sortScore.textContent = state.sortDesc ? "總分高到低" : "總分低到高";
    render();
  });

  document.body.addEventListener("click", (event) => {
    const detailButton = event.target.closest(".detail-button");
    if (!detailButton) return;
    const code = detailButton.dataset.code;
    if (detailButton.classList.contains("mobile-toggle")) {
      toggleMobileDetail(code);
    } else {
      openDetail(code);
    }
  });

  els.closeDialog.addEventListener("click", () => els.dialog.close());
  els.refresh.addEventListener("click", () => window.location.reload());
}

async function init() {
  try {
    state.data = await loadData();
    state.stocks = state.data.stocks || [];
    els.generatedAt.textContent = `資料日期：${state.data.summary?.asOf || "資料不足"}｜產生時間：${state.data.generatedAt || "資料不足"}`;
    bindEvents();
    render();
  } catch (error) {
    console.error(error);
    els.generatedAt.textContent = "資料讀取失敗，請先執行股票更新腳本。";
    els.mobileCards.innerHTML = `<article class="stock-card"><strong>無法載入資料</strong><p>${escapeHtml(error.message)}</p></article>`;
  }
}

init();
