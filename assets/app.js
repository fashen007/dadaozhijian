const categoryNames = {
  investment: "投资动态",
  statement: "本人发言",
  interview: "采访 / 观点",
  personal: "其他动态",
};

const state = { items: [], category: "all", search: "" };

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
  host.replaceChildren();
  if (!items.length) {
    host.append(node("p", "empty", "暂无匹配的公开动态。"));
    return;
  }
  items.forEach((item) => {
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
    article.append(meta, title, node("p", "summary", item.summary), node("p", "origin", item.source_type + " · " + item.source));
    host.append(article);
  });
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
    document.querySelector("#source-total").textContent = feed.sources.filter((source) => source.status === "ok").length;
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
  renderTimeline();
});

document.querySelector("#search").addEventListener("input", (event) => {
  state.search = event.target.value.trim();
  renderTimeline();
});

start();
