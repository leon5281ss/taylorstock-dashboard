const state = { data: null, stocks: [], search: "", filter: "全部", sortDesc: true };
const element = (id) => document.getElementById(id);
const escapeHtml = (value) => String(value ?? "").replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;").replaceAll('"', "&quot;").replaceAll("'", "&#039;");
const numeric = (value) => typeof value === "number" && Number.isFinite(value);
const format = (value, digits = 2) => numeric(value) ? value.toLocaleString("zh-TW", { maximumFractionDigits: digits }) : "缺資料";
const paragraph = (text) => "<p>" + escapeHtml(text) + "</p>";
const button = (code) => '<button class="detail-button" data-code="' + escapeHtml(code) + '">資料與警報</button>';

function render() {
  const summary = state.data.summary;
  element("generatedAt").textContent = "目標交易日：" + (summary.asOf || "尚未收集") + "｜產生：" + (state.data.generatedAt || "尚未執行") + "｜" + state.data.reportStatus;
  element("summaryCards").innerHTML = [
    ["監控檔數", summary.stockCount], ["當日完整檔數", summary.completeCount ?? 0],
    ["需人工確認", summary.manualCheckCount], ["八大官股", "無權限"],
  ].map(([label, value]) => '<article class="summary-card"><span>' + escapeHtml(label) + "</span><strong>" + escapeHtml(value) + "</strong></article>").join("");
  const rows = state.stocks.filter(stock => (stock.code + " " + stock.name).includes(state.search))
    .filter(stock => state.filter === "全部" || (state.filter === "人工確認" ? stock.manualCheck === "是" : stock.status === state.filter))
    .sort((first, second) => state.sortDesc ? second.alerts.length - first.alerts.length : first.alerts.length - second.alerts.length);
  element("stockTableBody").innerHTML = rows.map(stock => {
    const price = stock.latest.price;
    const institutional = stock.latest.institutional;
    return "<tr>" + [stock.code, stock.name, stock.category, format(price?.close), format(price?.volume, 0),
      format(institutional?.foreign, 0), format(institutional?.trust, 0), format(institutional?.dealer, 0),
      stock.alerts.length, price?.date || "缺資料", stock.dataQualityStatus]
      .map(value => "<td>" + escapeHtml(value) + "</td>").join("") + "<td>" + button(stock.code) + "</td></tr>";
  }).join("");
  element("mobileCards").innerHTML = rows.map(stock => '<article class="stock-card"><h3>' + escapeHtml(stock.code + " " + stock.name) + "</h3>" +
    paragraph("收盤：" + format(stock.latest.price?.close) + " 元｜" + (stock.latest.price?.date || "缺資料")) +
    paragraph("成交量：" + format(stock.latest.price?.volume, 0) + " 股") +
    paragraph(stock.dataQualityStatus + "｜警報 " + stock.alerts.length + " 則") + button(stock.code) + "</article>").join("");
}

function detail(code) {
  const stock = state.stocks.find(row => row.code === code);
  if (!stock) return;
  const sections = [];
  for (const [kind, title, fields] of [
    ["price", "價量（元／股）", [["close", "收盤"], ["volume", "成交量"]]],
    ["institutional", "法人買賣超（股）", [["foreign", "外資"], ["trust", "投信"], ["dealer", "自營商"]]],
    ["margin", "融資融券（張）", [["margin", "融資餘額"], ["marginChange", "融資日變化"], ["short", "融券餘額"], ["shortChange", "融券日變化"]]],
  ]) {
    const row = stock.latest[kind];
    const quality = stock.quality[kind];
    const check = quality.officialCheck;
    sections.push('<section class="detail-section"><h3>' + title + "</h3>" +
      paragraph("交易日期：" + (row?.date || "缺資料") + "｜狀態：" + quality.status) +
      fields.map(([field, label]) => paragraph(label + "：" + format(row?.[field]))).join("") +
      paragraph("來源：" + quality.source) +
      paragraph("官方核對：" + check.status + "；官方日期：" + (check.officialDate || "缺資料") + "；" + (check.reason || "")) +
      paragraph(check.source) +
      (check.differences && Object.keys(check.differences).length ? "<pre>" + escapeHtml(JSON.stringify(check.differences, null, 2)) + "</pre>" : "") +
      paragraph("缺漏日期：" + (quality.missingDates.join("、") || "無已識別缺漏")) + "</section>");
  }
  sections.push('<section class="detail-section"><h3>警報</h3>' +
    (stock.alerts.length ? stock.alerts.map(alert => paragraph(alert.date + "｜" + alert.message + "｜" + alert.source)).join("") : paragraph("未產生警報；請同時檢查未能計算的規則。")) +
    paragraph("未能計算：" + (stock.unavailableRules.join("、") || "無")) +
    paragraph("MA20：" + format(stock.technical.ma20) + "｜MA60：" + format(stock.technical.ma60)) +
    paragraph("八大官股：" + stock.governmentBank.label) +
    paragraph(stock.fundamentals.reason + "；不提供綜合分數。") + "</section>");
  element("dialogCode").textContent = stock.code;
  element("dialogTitle").textContent = stock.name;
  element("dialogContent").innerHTML = sections.join("");
  element("detailDialog").showModal();
}

async function init() {
  try {
    const response = await fetch("data/stocks.json", { cache: "no-store" });
    if (!response.ok) throw new Error("資料讀取失敗");
    state.data = await response.json();
    if (state.data.schemaVersion !== 3 || state.data.stocks.length !== 22) throw new Error("請更新至 22 檔新版資料");
    state.stocks = state.data.stocks;
    element("searchInput").addEventListener("input", event => { state.search = event.target.value.trim(); render(); });
    document.querySelectorAll(".chip").forEach(chip => chip.addEventListener("click", () => {
      document.querySelectorAll(".chip").forEach(button => button.classList.remove("active"));
      chip.classList.add("active");
      state.filter = chip.dataset.filter;
      render();
    }));
    element("sortScoreButton").addEventListener("click", () => {
      state.sortDesc = !state.sortDesc;
      element("sortScoreButton").textContent = state.sortDesc ? "警報多到少" : "警報少到多";
      render();
    });
    document.body.addEventListener("click", event => {
      const target = event.target.closest(".detail-button");
      if (target) detail(target.dataset.code);
    });
    element("closeDialog").addEventListener("click", () => element("detailDialog").close());
    element("refreshButton").addEventListener("click", () => location.reload());
    render();
  } catch (error) {
    element("generatedAt").textContent = error.message;
  }
}
init();

