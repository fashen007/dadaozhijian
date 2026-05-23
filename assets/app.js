const categoryNames = {
  investment: "投资动态",
  statement: "本人发言",
  interview: "采访 / 观点",
  personal: "其他动态",
};

const pageSize = 10;
const state = { items: [], category: "all", search: "", page: 1 };

function formatDate(value, withTime = false) {
  const date = new Date(value);
  return new Intl.DateTimeFormat("zh-CN", {
    dateStyle: "medium",
    ...(withTime ? { timeStyle: "short" } : {}),
    timeZone: "Asia/Shanghai",
  }).format(date);
}

function node(tag, className, text) {
  const element = document.createElement(tag);
  if (className) element.className = className;
  if (text) element.textContent = text;
  return element;
}

function renderSources(sources) {
  const host = document.querySelector("#source-cards");
  host.replaceChildren();
  sources.forEach((source) => {
    const card = node("article", `source-card ${source.status}`);
    const header = node("div", "source-header");
    header.append(node("h3", "", source.name), node("span", "status", source.status === "ok" ? "已更新" : source.status === "setup" ? "待配置" : "读取异常"));
    card.append(header, node("p", "", source.detail), node("small", "", `检查于 ${formatDate(source.checked_at, true)}`));
    host.append(card);
  });
}

function itemMatches(item) {
  const matchCategory = state.category === "all" || item.category === state.category;
  const keyword = state.search.toLowerCase();
  const matchText = !keyword || `${item.title} ${item.summary} ${item.source}`.toLowerCase().includes(keyword);
  return matchCategory && matchText;
}

function renderTimeline() {
  const host = document.querySelector("#timeline-list");
  const items = state.items.filter(itemMatches);
  const totalPages = Math.max(1, Math.ceil(items.length / pageSize));
  state.page = Math.min(state.page, totalPages);
  const start = (state.page - 1) * pageSize;
  const visibleItems = items.slice(start, start + pageSize);
  host.replaceChildren();
  if (!items.length) {
    host.append(node("p", "empty", "暂无匹配的公开动态。"));
    renderPagination(0, 1);
    return;
  }
  visibleItems.forEach((item) => {
    const article = node("article", "timeline-card");
    const meta = node("div", "meta");
    meta.append(node("span", `pill ${item.category}`, categoryNames[item.category] || "动态"));
    meta.append(node("time", "", formatDate(item.published_at)));
    meta.append(node("span", "verification", item.verification));
    const title = node("h3");
    const link = node("a", "", item.title);
    link.href = item.url;
    link.target = "_blank";
    link.rel = "noopener";
    title.append(link);
    const summaryLabel = node("span", `summary-label ${item.summary_status || "source"}`, item.summary_basis || "来源摘要");
    const summary = node("p", "summary", item.summary);
    summary.prepend(summaryLabel);
    article.append(meta, title, summary);
    if (item.summary_citations && item.summary_citations.length) {
      const citations = node("p", "citations", "摘要依据：");
      item.summary_citations.forEach((citation, index) => {
        if (index) citations.append(document.createTextNode(" · "));
        const citationLink = node("a", "", citation.title || "来源");
        citationLink.href = citation.url;
        citationLink.target = "_blank";
        citationLink.rel = "noopener";
        citations.append(citationLink);
      });
      article.append(citations);
    }
    article.append(node("p", "origin", item.source_type + " · " + item.source));
    host.append(article);
  });
  renderPagination(items.length, totalPages);
}

function renderPagination(totalItems, totalPages) {
  const host = document.querySelector("#pagination");
  host.replaceChildren();
  if (!totalItems) return;
  host.append(node("p", "page-count", `共 ${totalItems} 条 · 第 ${state.page} / ${totalPages} 页`));
  if (totalPages === 1) return;
  const controls = node("div", "page-buttons");
  controls.append(pageButton("上一页", state.page - 1, state.page === 1, "previous"));
  const first = Math.max(1, Math.min(state.page - 2, totalPages - 4));
  const last = Math.min(totalPages, first + 4);
  for (let page = first; page <= last; page += 1) {
    const button = pageButton(String(page), page, false, "");
    if (page === state.page) {
      button.classList.add("active");
      button.setAttribute("aria-current", "page");
    }
    controls.append(button);
  }
  controls.append(pageButton("下一页", state.page + 1, state.page === totalPages, "next"));
  host.append(controls);
}

function pageButton(text, page, disabled, className) {
  const button = node("button", className, text);
  button.dataset.page = String(page);
  button.disabled = disabled;
  return button;
}

async function start() {
  try {
    const response = await fetch("./data/feed.json", { cache: "no-store" });
    if (!response.ok) throw new Error("feed unavailable");
    const feed = await response.json();
    state.items = feed.items || [];
    document.querySelector("#updated-at").textContent = formatDate(feed.updated_at, true);
    document.querySelector("#item-total").textContent = state.items.length;
    document.querySelector("#investment-total").textContent = state.items.filter((item) => item.category === "investment").length;
    document.querySelector("#source-total").textContent = feed.sources.filter((source) => source.key !== "summary" && source.status === "ok").length;
    document.querySelectorAll("[data-profile-link]").forEach((link) => { link.href = feed.profile.xueqiu_url; });
    renderSources(feed.sources);
    renderTimeline();
  } catch (error) {
    document.querySelector("#updated-at").textContent = "数据读取失败";
    document.querySelector("#timeline-list").append(node("p", "empty", "请先运行采集脚本生成数据。"));
  }
}

document.querySelector("#filters").addEventListener("click", (event) => {
  const button = event.target.closest("button[data-category]");
  if (!button) return;
  document.querySelectorAll("#filters button").forEach((entry) => entry.classList.remove("active"));
  button.classList.add("active");
  state.category = button.dataset.category;
  state.page = 1;
  renderTimeline();
});

document.querySelector("#search").addEventListener("input", (event) => {
  state.search = event.target.value.trim();
  state.page = 1;
  renderTimeline();
});

document.querySelector("#pagination").addEventListener("click", (event) => {
  const button = event.target.closest("button[data-page]");
  if (!button || button.disabled) return;
  state.page = Number(button.dataset.page);
  renderTimeline();
  document.querySelector(".timeline").scrollIntoView({ behavior: "smooth", block: "start" });
});

start();
