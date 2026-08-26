/**
 * Meme 工坊 · Dashboard 前端
 *
 * 结构：bridge 封装 -> 状态仓库 -> 渲染器 -> 事件绑定。
 * 所有 DOM 均通过 createElement 构建，避免把后端字符串当作 HTML 解析。
 */

const bridge = window.AstrBotPluginPage;

const PAGE_SIZE = 48;
const HISTORY_LIMIT = 60;
const BULK_LIMIT = 200;
const THEME_STORAGE_KEY = "meme-forge-theme";
const LAYOUT_STORAGE_KEY = "meme-forge-layout";

const VIEWS = ["overview", "library", "records"];

const VIEW_INFO = {
  overview: { kicker: "CONTROL / OVERVIEW", title: "概览" },
  library: { kicker: "LIBRARY / MANAGE", title: "表情库" },
  records: { kicker: "ACTIVITY / RECORDS", title: "使用记录" },
};

const SOURCE_INFO = {
  meme_generator: { label: "内置", note: "meme-generator 自带" },
  external: { label: "meme_emoji", note: "扩展表情库" },
  gouqi: { label: "枸杞", note: "枸杞扩展表情库" },
};

const state = {
  view: "overview",
  overview: null,
  catalog: { items: [], total: 0, tags: [], sources: [], offset: 0, limit: PAGE_SIZE },
  filters: { q: "", tag: "", status: "all", source: "", sort: "key" },
  layout: "grid",
  selectMode: false,
  selection: new Set(),
  bulkBusy: false,
  detail: null,
  detailKey: "",
  history: { items: [], conversations: [] },
  session: "",
  recordsMode: "timeline",
  themeMode: "system",
  requests: { catalog: 0, detail: 0, history: 0, overview: 0 },
  previewCache: new Map(),
  materialCache: new Map(),
};

const el = (id) => document.getElementById(id);

const dom = {
  navItems: [...document.querySelectorAll("[data-view-target]")],
  panels: [...document.querySelectorAll("[data-view-panel]")],
  viewKicker: el("view-kicker"),
  viewTitle: el("view-title"),
  statusPill: el("status-pill"),
  statusText: el("status-text"),
  refresh: el("refresh-button"),
  engineVersion: el("engine-version"),
  navLibraryCount: el("nav-library-count"),
  navRecordsCount: el("nav-records-count"),
  themeButtons: [...document.querySelectorAll("[data-theme-mode]")],
  heroTotal: el("hero-total"),
  heroMeta: el("hero-meta"),
  sourceBar: el("source-bar"),
  sourceLegend: el("source-legend"),
  extensionList: el("extension-list"),
  metricTiles: el("metric-tiles"),
  topMemes: el("top-memes"),
  activeSessions: el("active-sessions"),
  recentActivity: el("recent-activity"),
  search: el("search-input"),
  sourceChips: el("source-chips"),
  tagFilter: el("tag-filter"),
  statusFilter: el("status-filter"),
  sortFilter: el("sort-filter"),
  catalogCount: el("catalog-count"),
  catalogMessage: el("catalog-message"),
  memeGrid: el("meme-grid"),
  layoutButtons: [...document.querySelectorAll("[data-layout]")],
  selectModeButton: el("select-mode-button"),
  previousPage: el("previous-page"),
  nextPage: el("next-page"),
  pageStatus: el("page-status"),
  bulkBar: el("bulk-bar"),
  bulkCount: el("bulk-count"),
  bulkSelectPage: el("bulk-select-page"),
  bulkEnable: el("bulk-enable"),
  bulkDisable: el("bulk-disable"),
  bulkClear: el("bulk-clear"),
  sessionFilter: el("history-session-filter"),
  clearSessionFilter: el("clear-session-filter"),
  recordsModeButtons: [...document.querySelectorAll("[data-records-mode]")],
  sessionList: el("session-list"),
  recordsCount: el("records-count"),
  historyMessage: el("history-message"),
  historyBody: el("history-body"),
  drawer: el("drawer"),
  drawerPanel: el("drawer-panel"),
  drawerBackdrop: el("drawer-backdrop"),
  drawerClose: el("drawer-close"),
  drawerTitle: el("drawer-title"),
  drawerEyebrow: el("drawer-eyebrow"),
  drawerBody: el("drawer-body"),
  lightbox: el("lightbox"),
  lightboxImage: el("lightbox-image"),
  lightboxCaption: el("lightbox-caption"),
  lightboxClose: el("lightbox-close"),
  toastStack: el("toast-stack"),
};

/* --- 通用小工具 ---------------------------------------------------------- */

function make(tag, className = "", text) {
  const node = document.createElement(tag);
  if (className) {
    node.className = className;
  }
  if (text !== undefined) {
    node.textContent = String(text);
  }
  return node;
}

function icon(symbolId, size) {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("aria-hidden", "true");
  if (size) {
    svg.setAttribute("width", String(size));
    svg.setAttribute("height", String(size));
  }
  const use = document.createElementNS("http://www.w3.org/2000/svg", "use");
  use.setAttribute("href", "#" + symbolId);
  svg.append(use);
  return svg;
}

function clear(node) {
  while (node.firstChild) {
    node.removeChild(node.firstChild);
  }
}

function setMessage(node, text = "", isError = false) {
  node.textContent = text;
  node.classList.toggle("is-error", Boolean(text) && isError);
  node.hidden = !text;
}

function emptyState(title, description, symbolId = "i-inbox") {
  const box = make("div", "empty-state");
  box.append(icon(symbolId, 30), make("strong", "", title));
  if (description) {
    box.append(make("p", "", description));
  }
  return box;
}

function skeleton(count, isRow = false) {
  const wrap = make("div", isRow ? "" : "skeleton-grid");
  if (isRow) {
    wrap.style.display = "grid";
    wrap.style.gap = "8px";
  }
  for (let index = 0; index < count; index += 1) {
    wrap.append(make("div", isRow ? "skeleton is-row" : "skeleton"));
  }
  return wrap;
}

function hueOf(value) {
  const text = String(value || "");
  let hash = 0;
  for (let index = 0; index < text.length; index += 1) {
    hash = (hash * 31 + text.charCodeAt(index)) % 360;
  }
  return hash;
}

function glyphOf(value) {
  const normalized = String(value || "MF").replace(/[^\p{L}\p{N}]/gu, "");
  return (normalized.slice(0, 2) || "MF").toUpperCase();
}

function sourceLabel(source) {
  return SOURCE_INFO[source]?.label || source || "未知";
}

function formatNumber(value) {
  return new Intl.NumberFormat("zh-CN").format(Number(value) || 0);
}

/** 侧边栏徽标空间很窄，四位以上直接压缩成 1.3k / 2.4M。 */
function formatCompact(value) {
  const amount = Number(value) || 0;
  if (amount < 1000) {
    return String(amount);
  }
  if (amount < 1000000) {
    const scaled = amount / 1000;
    return (scaled < 10 ? scaled.toFixed(1) : Math.round(scaled)) + "k";
  }
  const scaled = amount / 1000000;
  return (scaled < 10 ? scaled.toFixed(1) : Math.round(scaled)) + "M";
}

function formatBytes(bytes) {
  const amount = Number(bytes) || 0;
  if (amount < 1024) {
    return amount + " B";
  }
  if (amount < 1024 * 1024) {
    return (amount / 1024).toFixed(1) + " KB";
  }
  return (amount / 1024 / 1024).toFixed(1) + " MB";
}

function parseDate(value) {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? null : date;
}

function formatDateTime(value) {
  const date = parseDate(value);
  if (!date) {
    return String(value || "--");
  }
  return new Intl.DateTimeFormat("zh-CN", { dateStyle: "short", timeStyle: "short" }).format(date);
}

function formatTime(value) {
  const date = parseDate(value);
  if (!date) {
    return "--:--";
  }
  return new Intl.DateTimeFormat("zh-CN", { hour: "2-digit", minute: "2-digit" }).format(date);
}

function formatDayLabel(value) {
  const date = parseDate(value);
  if (!date) {
    return "未知日期";
  }
  const today = new Date();
  const sameDay = (left, right) =>
    left.getFullYear() === right.getFullYear() &&
    left.getMonth() === right.getMonth() &&
    left.getDate() === right.getDate();
  if (sameDay(date, today)) {
    return "今天";
  }
  const yesterday = new Date(today.getTime() - 86_400_000);
  if (sameDay(date, yesterday)) {
    return "昨天";
  }
  return new Intl.DateTimeFormat("zh-CN", { month: "long", day: "numeric" }).format(date);
}

function relativeTime(value) {
  const date = parseDate(value);
  if (!date) {
    return "--";
  }
  const seconds = Math.round((Date.now() - date.getTime()) / 1000);
  if (seconds < 60) {
    return "刚刚";
  }
  const units = [
    [60, "分钟"],
    [24, "小时"],
    [7, "天"],
  ];
  let amount = seconds / 60;
  let label = "分钟";
  for (const [step, name] of units) {
    if (amount < step) {
      label = name;
      break;
    }
    amount /= step;
    label = name;
  }
  return Math.max(1, Math.round(amount)) + label + "前";
}

function shortSession(session) {
  const text = String(session || "");
  const parts = text.split(":");
  return parts.length > 1 ? parts.slice(1).join(":") : text;
}

/* --- 接口封装 ------------------------------------------------------------ */

function unwrap(payload) {
  if (!payload || payload.ok !== true) {
    throw new Error(payload?.error || "请求未返回可用数据。");
  }
  return payload;
}

async function apiGet(endpoint, params = {}) {
  if (!bridge) {
    throw new Error("AstrBot 页面桥接未加载。");
  }
  return unwrap(await bridge.apiGet(endpoint, params));
}

async function apiPost(endpoint, body) {
  if (!bridge) {
    throw new Error("AstrBot 页面桥接未加载。");
  }
  return unwrap(await bridge.apiPost(endpoint, body));
}

/* --- 提示条 -------------------------------------------------------------- */

function toast(text, kind = "ok") {
  const node = make("div", "toast");
  node.dataset.kind = kind;
  node.append(icon(kind === "error" ? "i-alert" : "i-check", 15), make("span", "", text));
  dom.toastStack.append(node);
  window.setTimeout(() => {
    node.classList.add("is-out");
    window.setTimeout(() => node.remove(), 260);
  }, 3200);
  while (dom.toastStack.children.length > 4) {
    dom.toastStack.firstElementChild?.remove();
  }
}

function setStatus(text, kind = "ok") {
  dom.statusText.textContent = text;
  dom.statusPill.classList.remove("is-ok", "is-warn", "is-error");
  dom.statusPill.classList.add("is-" + kind);
}

/* --- 主题 ---------------------------------------------------------------- */

const systemDark = window.matchMedia?.("(prefers-color-scheme: dark)");

function resolveTheme(mode) {
  if (mode === "light" || mode === "dark") {
    return mode;
  }
  return systemDark && !systemDark.matches ? "light" : "dark";
}

function applyThemeMode(mode, persist = true) {
  state.themeMode = ["system", "light", "dark"].includes(mode) ? mode : "system";
  document.documentElement.dataset.theme = resolveTheme(state.themeMode);
  for (const button of dom.themeButtons) {
    button.setAttribute("aria-selected", String(button.dataset.themeMode === state.themeMode));
  }
  if (!persist) {
    return;
  }
  try {
    window.localStorage.setItem(THEME_STORAGE_KEY, state.themeMode);
  } catch {
    // 隐私模式或嵌入式 Dashboard 可能禁用 localStorage。
  }
}

/* --- 视图切换 ------------------------------------------------------------ */

function viewFromHash() {
  const hash = String(window.location.hash || "").replace(/^#\/?/, "");
  return VIEWS.includes(hash) ? hash : "overview";
}

function setView(view, { syncHash = true } = {}) {
  const target = VIEWS.includes(view) ? view : "overview";
  state.view = target;
  for (const panel of dom.panels) {
    panel.hidden = panel.dataset.viewPanel !== target;
  }
  for (const item of dom.navItems) {
    const isActive = item.dataset.viewTarget === target;
    if (item.classList.contains("nav-item")) {
      item.classList.toggle("is-active", isActive);
      if (isActive) {
        item.setAttribute("aria-current", "page");
      } else {
        item.removeAttribute("aria-current");
      }
    }
  }
  dom.viewKicker.textContent = VIEW_INFO[target].kicker;
  dom.viewTitle.textContent = VIEW_INFO[target].title;
  if (syncHash && viewFromHash() !== target) {
    window.location.hash = "#" + target;
  }
}

/* --- 概览渲染 ------------------------------------------------------------ */

function renderOverview() {
  const data = state.overview;
  dom.engineVersion.textContent = data?.engine_version || "--";
  dom.heroTotal.textContent = data ? formatNumber(data.total_memes) : "--";
  dom.navLibraryCount.textContent = data ? formatCompact(data.total_memes) : "--";
  dom.navRecordsCount.textContent = data ? formatCompact(data.usage_records) : "--";
  dom.navLibraryCount.title = data ? formatNumber(data.total_memes) + " 个表情" : "";
  dom.navRecordsCount.title = data ? formatNumber(data.usage_records) + " 条记录" : "";

  clear(dom.heroMeta);
  if (data) {
    const prefix = String(data.trigger_prefix || "meme");
    dom.heroMeta.append(
      chip("引擎 " + (data.engine_version || "--"), "is-mono"),
      chip("前缀 /" + prefix, "is-mono is-primary"),
      chip(formatNumber(data.enabled_memes) + " 个可用", "is-secondary"),
    );
  }

  renderSourceBar(data?.sources || [], data?.total_memes || 0);
  renderMetricTiles(data);
  renderExtensions(data);
  renderTopMemes(data?.top_memes || []);
  renderActiveSessions(data?.active_conversations || []);
  renderRecentActivity(data?.recent_records || []);
}

function chip(text, extra = "") {
  return make("span", ("chip " + extra).trim(), text);
}

function renderSourceBar(sources, total) {
  clear(dom.sourceBar);
  clear(dom.sourceLegend);
  if (!sources.length) {
    dom.sourceLegend.append(make("span", "region-message", "暂无来源数据。"));
    return;
  }
  const sum = sources.reduce((carry, item) => carry + (Number(item.count) || 0), 0) || total || 1;
  for (const entry of sources) {
    const bar = make("span");
    bar.dataset.source = entry.source;
    bar.style.flexBasis = ((Number(entry.count) || 0) / sum) * 100 + "%";
    bar.style.flexGrow = "0";
    dom.sourceBar.append(bar);

    const button = make("button");
    button.type = "button";
    const swatch = make("span", "legend-swatch");
    swatch.dataset.source = entry.source;
    button.append(
      swatch,
      make("span", "", sourceLabel(entry.source)),
      make("span", "legend-value", formatNumber(entry.count)),
    );
    button.title = "在表情库中只看" + sourceLabel(entry.source);
    button.addEventListener("click", () => {
      state.filters.source = entry.source;
      setView("library");
      void loadCatalog({ resetOffset: true });
    });
    dom.sourceLegend.append(button);
  }
}

function tile(label, value, note, accent, ratio) {
  const node = make("div", "tile");
  if (accent) {
    node.dataset.accent = accent;
  }
  node.append(make("span", "tile-label", label), make("strong", "tile-value", value));
  // ratio 为数字时画占比条；为 null 时画一条统一的装饰条，让四块指标视觉对齐。
  if (ratio !== undefined) {
    const flat = ratio === null;
    const meter = make("div", flat ? "meter is-flat" : "meter");
    const fill = make("i");
    fill.style.width = flat ? "100%" : Math.max(0, Math.min(100, Number(ratio) * 100)).toFixed(1) + "%";
    meter.append(fill);
    node.append(meter);
  }
  if (note) {
    node.append(make("span", "tile-note", note));
  }
  return node;
}

function renderMetricTiles(data) {
  clear(dom.metricTiles);
  if (!data) {
    dom.metricTiles.append(skeleton(4));
    return;
  }
  const total = Number(data.total_memes) || 0;
  const enabled = Number(data.enabled_memes) || 0;
  const disabled = Number(data.disabled_memes) || 0;
  dom.metricTiles.append(
    tile("已启用", formatNumber(enabled), "可被指令触发", "", total ? enabled / total : 0),
    tile("已禁用", formatNumber(disabled), "可随时单独恢复", "danger", total ? disabled / total : 0),
    tile("生成记录", formatNumber(data.usage_records), "仅统计文本信息，不含图片", "secondary", null),
    tile("标签数量", formatNumber(data.tag_count), "用于筛选表情主题", "accent", null),
  );
}

function extensionRow(title, ready, warn, description) {
  const row = make("div", "ext-row");
  if (ready) {
    row.classList.add("is-ready");
  } else if (warn) {
    row.classList.add("is-warn");
  }
  const iconBox = make("span", "ext-icon");
  iconBox.append(icon(ready ? "i-check" : warn ? "i-alert" : "i-puzzle", 16));
  const copy = make("div", "ext-copy");
  copy.append(make("strong", "", title), make("small", "", description));
  row.append(iconBox, copy, chip(ready ? "就绪" : warn ? "待修复" : "未安装", ready ? "is-primary" : warn ? "is-accent" : ""));
  return row;
}

function renderExtensions(data) {
  clear(dom.extensionList);
  if (!data) {
    dom.extensionList.append(skeleton(2, true));
    return;
  }
  const ext = data.extension || {};
  const gouqi = data.gouqi_extension || {};

  const extReady = Boolean(ext.installed && ext.library_valid && ext.resources_present);
  const extWarn = Boolean(ext.installed && !extReady);
  const extNote = ext.installed
    ? [ext.tag ? "版本 " + ext.tag : "版本未知", ext.library_valid ? "清单正常" : "清单异常", ext.resources_present ? "素材完整" : "素材缺失"].join(" · ")
    : "未安装，可在插件配置中启用后自动下载";
  dom.extensionList.append(extensionRow("meme_emoji 扩展", extReady, extWarn, extNote));

  const gouqiReady = Boolean(gouqi.installed && gouqi.assets_valid);
  const gouqiWarn = Boolean(gouqi.installed && !gouqiReady);
  const gouqiNote = gouqi.installed
    ? [gouqi.commit ? "commit " + String(gouqi.commit).slice(0, 7) : "commit 未知", formatNumber(gouqi.templates) + " 个模板", gouqi.assets_valid ? "素材完整" : "素材缺失"].join(" · ")
    : "未安装，可在插件配置中启用后自动下载";
  dom.extensionList.append(extensionRow("枸杞扩展", gouqiReady, gouqiWarn, gouqiNote));
}

function rankRow(index, title, subtitle, value, ratio, onOpen) {
  const row = make(onOpen ? "button" : "div", "rank-row");
  if (onOpen) {
    row.type = "button";
    row.addEventListener("click", onOpen);
  }
  row.style.setProperty("--fill", Math.max(0, Math.min(100, ratio * 100)).toFixed(1) + "%");
  const copy = make("div", "rank-copy");
  copy.append(make("strong", "", title), make("small", "", subtitle));
  row.append(make("span", "rank-index", String(index).padStart(2, "0")), copy, make("span", "rank-value", value));
  return row;
}

function renderTopMemes(items) {
  clear(dom.topMemes);
  if (!items.length) {
    dom.topMemes.append(emptyState("还没有生成记录", "触发一次表情后，这里会显示最常用的模板。"));
    return;
  }
  const max = Math.max(...items.map((item) => Number(item.count) || 0), 1);
  items.forEach((item, index) => {
    dom.topMemes.append(
      rankRow(
        index + 1,
        item.key,
        "最近触发词 " + (item.last_trigger || item.key) + " · " + relativeTime(item.last_used_at),
        formatNumber(item.count) + " 次",
        (Number(item.count) || 0) / max,
        () => void openDetail(item.key),
      ),
    );
  });
}

function renderActiveSessions(items) {
  clear(dom.activeSessions);
  if (!items.length) {
    dom.activeSessions.append(emptyState("暂无活跃会话", "有人使用表情后，这里会显示所在会话。"));
    return;
  }
  const max = Math.max(...items.map((item) => Number(item.count) || 0), 1);
  items.forEach((item, index) => {
    dom.activeSessions.append(
      rankRow(
        index + 1,
        shortSession(item.session),
        (item.platform || "未知平台") + " · 最近 " + (item.last_key || "--") + " · " + relativeTime(item.last_used_at),
        formatNumber(item.count) + " 次",
        (Number(item.count) || 0) / max,
        () => {
          state.session = item.session;
          setView("records");
          void loadHistory();
        },
      ),
    );
  });
}

function groupByDay(items) {
  const groups = [];
  let current = null;
  for (const item of items) {
    const label = formatDayLabel(item.created_at);
    if (!current || current.label !== label) {
      current = { label, items: [] };
      groups.push(current);
    }
    current.items.push(item);
  }
  return groups;
}

function renderRecentActivity(items) {
  clear(dom.recentActivity);
  if (!items.length) {
    dom.recentActivity.append(emptyState("暂无活动", "最近成功生成的表情会出现在这里。"));
    return;
  }
  for (const group of groupByDay(items)) {
    dom.recentActivity.append(make("p", "timeline-day", group.label));
    for (const record of group.items) {
      dom.recentActivity.append(timelineRow(record));
    }
  }
}

function timelineRow(record) {
  const row = make("button", "timeline-row");
  row.type = "button";
  const copy = make("div", "timeline-copy");
  copy.append(
    make("strong", "", record.key + "  ·  " + (record.trigger || record.key)),
    make("small", "", (record.sender_name || record.sender_id || "未知用户") + " @ " + shortSession(record.session)),
  );
  row.append(make("span", "timeline-time", formatTime(record.created_at)), copy, chip(record.platform || "--", "is-mono"));
  row.title = "查看 " + record.key + " 详情";
  row.addEventListener("click", () => void openDetail(record.key));
  return row;
}

/* --- 表情库 -------------------------------------------------------------- */

function renderSourceChips() {
  clear(dom.sourceChips);
  const sources = state.catalog.sources || [];
  const total = sources.reduce((carry, item) => carry + (Number(item.count) || 0), 0);
  if (sources.length < 2) {
    dom.sourceChips.hidden = true;
    return;
  }
  dom.sourceChips.hidden = false;
  const entries = [
    { source: "", label: "全部", count: total },
    ...sources.map((item) => ({ source: item.source, label: sourceLabel(item.source), count: item.count })),
  ];
  for (const entry of entries) {
    const button = make("button");
    button.type = "button";
    button.append(document.createTextNode(entry.label), make("b", "", formatNumber(entry.count)));
    button.setAttribute("aria-pressed", String(state.filters.source === entry.source));
    button.addEventListener("click", () => {
      state.filters.source = entry.source;
      void loadCatalog({ resetOffset: true });
    });
    dom.sourceChips.append(button);
  }
}

function renderTagOptions() {
  const current = state.filters.tag;
  clear(dom.tagFilter);
  const all = make("option", "", "全部标签");
  all.value = "";
  dom.tagFilter.append(all);
  for (const tag of state.catalog.tags || []) {
    const option = make("option", "", tag);
    option.value = tag;
    dom.tagFilter.append(option);
  }
  dom.tagFilter.value = (state.catalog.tags || []).includes(current) ? current : "";
  state.filters.tag = dom.tagFilter.value;
}

function memeCard(item) {
  const card = make("article", "meme-card");
  card.style.setProperty("--hue", String(hueOf(item.key)));
  card.dataset.key = item.key;
  card.classList.toggle("is-off", !item.enabled);
  card.classList.toggle("is-selected", state.selection.has(item.key));

  const open = make("button", "meme-open");
  open.type = "button";
  open.setAttribute("aria-label", "查看 " + item.key + " 的详情");
  open.addEventListener("click", () => {
    if (state.selectMode) {
      toggleSelection(item.key);
      return;
    }
    void openDetail(item.key);
  });

  const glyph = make("span", "meme-glyph", glyphOf(item.key));
  glyph.setAttribute("aria-hidden", "true");

  const body = make("div", "meme-body");
  body.append(make("span", "meme-key", item.key));
  const keywords = (item.keywords || []).filter(Boolean);
  body.append(make("span", "meme-keywords", keywords.length ? keywords.join(" · ") : "无触发关键词"));

  const foot = make("div", "meme-foot");
  const sourceBadge = make("span", "meme-badge");
  sourceBadge.dataset.source = item.source;
  sourceBadge.append(icon("i-puzzle", 11), make("span", "", sourceLabel(item.source)));
  const needBadge = make("span", "meme-need");
  needBadge.append(
    icon("i-image", 11),
    make("span", "", item.images?.label ?? "0"),
    make("i"),
    icon("i-text", 11),
    make("span", "", item.texts?.label ?? "0"),
  );
  needBadge.title = "需要图片 " + (item.images?.label ?? "0") + " 张，文本 " + (item.texts?.label ?? "0") + " 段";
  foot.append(sourceBadge, needBadge, make("span", "spacer"));

  if (state.selectMode) {
    const pick = make("button", "pick");
    pick.type = "button";
    pick.setAttribute("role", "checkbox");
    pick.setAttribute("aria-checked", String(state.selection.has(item.key)));
    pick.setAttribute("aria-label", "选择 " + item.key);
    pick.append(icon("i-check", 12));
    pick.addEventListener("click", () => toggleSelection(item.key));
    foot.append(pick);
  } else {
    const toggle = make("button", "switch");
    toggle.type = "button";
    toggle.setAttribute("role", "switch");
    toggle.setAttribute("aria-checked", String(item.enabled));
    toggle.setAttribute("aria-label", (item.enabled ? "禁用 " : "启用 ") + item.key);
    toggle.title = item.enabled ? "点击禁用" : "点击启用";
    toggle.addEventListener("click", () => void setEnabled(item.key, !item.enabled, toggle));
    foot.append(toggle);
  }

  card.append(open, glyph, body, foot);
  return card;
}

function renderCatalog() {
  const { items, total, offset, limit } = state.catalog;
  dom.memeGrid.classList.toggle("is-list", state.layout === "list");
  clear(dom.memeGrid);
  if (!items.length) {
    dom.memeGrid.append(emptyState("没有匹配的表情", "换个关键词，或把筛选条件放宽一些。", "i-search"));
  } else {
    for (const item of items) {
      dom.memeGrid.append(memeCard(item));
    }
  }
  dom.catalogCount.textContent = formatNumber(total) + " 个结果";
  const from = total ? offset + 1 : 0;
  const to = Math.min(offset + limit, total);
  dom.pageStatus.textContent = total ? from + " - " + to + " / " + formatNumber(total) : "0 / 0";
  dom.previousPage.disabled = offset <= 0;
  dom.nextPage.disabled = offset + limit >= total;
  renderBulkBar();
}

function renderBulkBar() {
  const count = state.selection.size;
  dom.bulkBar.classList.toggle("is-open", state.selectMode);
  dom.bulkCount.textContent = String(count);
  const busy = Boolean(state.bulkBusy);
  dom.bulkEnable.disabled = busy || count === 0;
  dom.bulkDisable.disabled = busy || count === 0;
  dom.bulkClear.disabled = busy || count === 0;
  const pageKeys = state.catalog.items.map((item) => item.key);
  const allPicked = pageKeys.length > 0 && pageKeys.every((key) => state.selection.has(key));
  dom.bulkSelectPage.disabled = busy || pageKeys.length === 0;
  dom.bulkSelectPage.textContent = allPicked ? "取消本页" : "本页全选";
}

function togglePageSelection() {
  const pageKeys = state.catalog.items.map((item) => item.key);
  if (!pageKeys.length) {
    return;
  }
  if (pageKeys.every((key) => state.selection.has(key))) {
    for (const key of pageKeys) {
      state.selection.delete(key);
    }
  } else {
    let truncated = false;
    for (const key of pageKeys) {
      if (state.selection.size >= BULK_LIMIT && !state.selection.has(key)) {
        truncated = true;
        continue;
      }
      state.selection.add(key);
    }
    if (truncated) {
      toast("单次最多选择 " + BULK_LIMIT + " 个表情，已选到上限。", "error");
    }
  }
  renderCatalog();
}

function toggleSelection(key) {
  if (state.selection.has(key)) {
    state.selection.delete(key);
  } else {
    if (state.selection.size >= BULK_LIMIT) {
      toast("单次最多选择 " + BULK_LIMIT + " 个表情。", "error");
      return;
    }
    state.selection.add(key);
  }
  renderCatalog();
}

function setSelectMode(enabled) {
  state.selectMode = enabled;
  dom.selectModeButton.setAttribute("aria-pressed", String(enabled));
  dom.selectModeButton.classList.toggle("is-primary", enabled);
  if (!enabled) {
    state.selection.clear();
  }
  renderCatalog();
}

/* --- 详情抽屉 ------------------------------------------------------------ */

let lastFocused = null;

function openDrawer(key) {
  lastFocused = document.activeElement;
  dom.drawerTitle.textContent = key;
  dom.drawerEyebrow.textContent = "MEME DETAIL";
  dom.drawer.hidden = false;
  dom.drawerPanel.focus({ preventScroll: true });
}

function closeDrawer() {
  dom.drawer.hidden = true;
  state.detailKey = "";
  state.detail = null;
  clear(dom.drawerBody);
  if (lastFocused instanceof HTMLElement) {
    lastFocused.focus({ preventScroll: true });
  }
}

async function openDetail(key) {
  const target = String(key || "").trim();
  if (!target) {
    return;
  }
  state.detailKey = target;
  openDrawer(target);
  clear(dom.drawerBody);
  dom.drawerBody.append(skeleton(3, true));
  const requestId = ++state.requests.detail;
  try {
    const data = await apiGet("dashboard/meme", { key: target });
    if (requestId !== state.requests.detail) {
      return;
    }
    state.detail = data.item;
    renderDetail(data.item);
  } catch (error) {
    if (requestId !== state.requests.detail) {
      return;
    }
    clear(dom.drawerBody);
    const message = make("p", "region-message is-error", error.message || "读取详情失败。");
    dom.drawerBody.append(message);
  }
}

function commandPrefix() {
  const prefix = String(state.overview?.trigger_prefix ?? "meme").trim();
  if (!prefix) {
    return "/";
  }
  return "/" + prefix + (/[A-Za-z0-9]$/.test(prefix) ? " " : "");
}

function commandExamples(detail) {
  const trigger = (detail.keywords || []).find(Boolean) || detail.key;
  const needImages = Number(detail.images?.min) || 0;
  const needTexts = Number(detail.texts?.min) || 0;
  const hints = [];
  if (needImages) {
    hints.push("需要 " + (detail.images?.label ?? needImages) + " 张图片（可 @ 某人、引用消息或直接发图）");
  }
  if (needTexts) {
    hints.push("需要 " + (detail.texts?.label ?? needTexts) + " 段文本");
  }
  const examples = [];
  const base = trigger + (needTexts ? " " + (detail.default_texts || []).slice(0, needTexts).map((text) => text || "文本").join(" ") : "");
  examples.push({ command: base, hint: hints.join("，") || "直接发送即可生成" });
  examples.push({ command: commandPrefix() + base, hint: "带插件前缀的等价写法，适合关键词冲突时使用" });

  const options = detail.options || [];
  const bareOption = options.find((option) => (option.aliases || []).length);
  if (bareOption) {
    examples.push({
      command: trigger + " " + bareOption.aliases[0],
      hint: "直接跟上选项名即可，例如「" + bareOption.name + "」的可选值：" + (bareOption.choices || []).join("、"),
    });
  }
  const flagOption = options.find((option) => (option.flags || []).length);
  if (flagOption) {
    const flag = flagOption.flags[0];
    examples.push({
      command: trigger + " " + (flagOption.type === "bool" ? flag : flag + " " + (formatOptionDefault(flagOption.default) === "未设置" ? "值" : formatOptionDefault(flagOption.default))),
      hint: "使用参数开关：" + (flagOption.description || flagOption.name),
    });
  }
  return examples;
}

function formatOptionDefault(value) {
  if (value === undefined || value === null || value === "") {
    return "未设置";
  }
  if (typeof value === "boolean") {
    return value ? "true" : "false";
  }
  if (Array.isArray(value)) {
    return value.join(", ");
  }
  return String(value);
}

function section(title) {
  const node = make("section", "detail-section");
  node.append(make("h3", "", title));
  return node;
}

function commandLine(example) {
  const line = make("div", "command-line");
  const code = make("code");
  code.append(document.createTextNode(example.command));
  if (example.hint) {
    code.append(make("span", "command-hint", example.hint));
  }
  const copy = make("button", "btn is-icon is-quiet");
  copy.type = "button";
  copy.title = "复制命令";
  copy.setAttribute("aria-label", "复制命令 " + example.command);
  copy.append(icon("i-copy", 15));
  copy.addEventListener("click", () => void copyText(example.command));
  line.append(code, copy);
  return line;
}

async function copyText(text) {
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(text);
    } else {
      const area = make("textarea");
      area.value = text;
      area.setAttribute("readonly", "readonly");
      area.style.position = "fixed";
      area.style.opacity = "0";
      document.body.append(area);
      area.select();
      document.execCommand("copy");
      area.remove();
    }
    toast("已复制：" + text);
  } catch {
    toast("复制失败，请手动选择文本。", "error");
  }
}

function specCell(label, value) {
  const cell = make("div", "spec-cell");
  cell.append(make("dt", "", label), make("dd", "", value));
  return cell;
}

function renderDetail(detail) {
  clear(dom.drawerBody);
  dom.drawerTitle.textContent = detail.key;
  dom.drawerEyebrow.textContent = sourceLabel(detail.source).toUpperCase() + " · MEME DETAIL";

  // 状态与开关
  const statusSection = section("状态");
  const statusRow = make("div", "detail-row");
  const toggle = make("button", "switch");
  toggle.type = "button";
  toggle.setAttribute("role", "switch");
  toggle.setAttribute("aria-checked", String(detail.enabled));
  toggle.setAttribute("aria-label", (detail.enabled ? "禁用 " : "启用 ") + detail.key);
  toggle.addEventListener("click", () => void setEnabled(detail.key, !detail.enabled, toggle));
  statusRow.append(
    chip(detail.enabled ? "已启用" : "已禁用", detail.enabled ? "is-primary" : "is-danger"),
    chip(sourceLabel(detail.source), "is-secondary"),
    make("span", "", detail.enabled ? "当前可被触发" : "当前不响应任何触发词"),
    toggle,
  );
  statusSection.append(statusRow);

  const specs = make("dl", "spec-grid");
  specs.append(
    specCell("图片需求", detail.images?.label ?? "0"),
    specCell("文本需求", detail.texts?.label ?? "0"),
    specCell("可选参数", formatNumber((detail.options || []).length)),
    specCell("内置素材", detail.has_materials ? formatNumber(detail.materials?.total || 0) : "无"),
  );
  statusSection.append(specs);
  dom.drawerBody.append(statusSection);

  // 触发词
  const triggerSection = section("触发词");
  const triggers = make("div", "tag-list");
  const keywords = (detail.keywords || []).filter(Boolean);
  if (keywords.length) {
    for (const keyword of keywords) {
      const item = make("button", "chip is-mono");
      item.type = "button";
      item.textContent = keyword;
      item.title = "复制触发词";
      item.addEventListener("click", () => void copyText(keyword));
      triggers.append(item);
    }
  } else {
    triggers.append(make("span", "region-message", "该表情没有关键词，只能用 " + commandPrefix() + detail.key + " 触发。"));
  }
  triggerSection.append(triggers);
  if ((detail.tags || []).length) {
    const tags = make("div", "tag-list");
    for (const tag of detail.tags) {
      const item = make("button", "chip");
      item.type = "button";
      item.append(icon("i-tag", 12), make("span", "", tag));
      item.title = "在表情库中按此标签筛选";
      item.addEventListener("click", () => {
        state.filters.tag = tag;
        state.filters.q = "";
        dom.search.value = "";
        closeDrawer();
        setView("library");
        void loadCatalog({ resetOffset: true });
      });
      tags.append(item);
    }
    triggerSection.append(tags);
  }
  dom.drawerBody.append(triggerSection);

  // 命令示例
  const commandSection = section("命令示例");
  const block = make("div", "command-block");
  for (const example of commandExamples(detail)) {
    block.append(commandLine(example));
  }
  commandSection.append(block);
  dom.drawerBody.append(commandSection);

  // 预览
  const previewSection = section("效果预览");
  const frame = make("div", "preview-frame");
  frame.append(make("p", "region-message", "正在生成预览..."));
  previewSection.append(frame);
  dom.drawerBody.append(previewSection);
  void loadPreview(detail.key, frame);

  // 参数
  const options = detail.options || [];
  if (options.length) {
    const optionSection = section("可选参数 " + options.length);
    const list = make("div", "option-list");
    for (const option of options) {
      list.append(optionRow(option));
    }
    optionSection.append(list);
    dom.drawerBody.append(optionSection);
  }

  // 默认文本
  if ((detail.default_texts || []).length) {
    const textSection = section("默认文本");
    const list = make("div", "tag-list");
    for (const text of detail.default_texts) {
      list.append(chip(text, "is-mono"));
    }
    textSection.append(list);
    dom.drawerBody.append(textSection);
  }

  // 素材
  if (detail.has_materials && (detail.materials?.items || []).length) {
    const materialSection = section("内置素材 " + formatNumber(detail.materials.total));
    const grid = make("div", "material-grid");
    for (const material of detail.materials.items) {
      grid.append(materialThumb(detail.key, material));
    }
    materialSection.append(grid);
    if (detail.materials.truncated) {
      materialSection.append(make("p", "region-message", "素材较多，仅展示前 " + detail.materials.items.length + " 个。"));
    }
    dom.drawerBody.append(materialSection);
    observeMaterials(grid);
  }
}

function optionRow(option) {
  const row = make("div", "option-row");
  const head = make("div", "option-head");
  head.append(make("strong", "", option.name), make("span", "option-type", option.type || "text"));
  const flags = [...(option.flags || []), ...(option.aliases || [])].filter(Boolean);
  if (flags.length) {
    head.append(chip(flags.join(" / "), "is-mono"));
  }
  row.append(head);
  if (option.description) {
    row.append(make("p", "option-desc", option.description));
  }
  const meta = make("div", "option-meta");
  meta.append(make("span", "", "默认 " + formatOptionDefault(option.default)));
  if ((option.choices || []).length) {
    meta.append(make("span", "", "可选 " + option.choices.join(" | ")));
  }
  if (option.minimum !== null && option.minimum !== undefined) {
    meta.append(make("span", "", "最小 " + option.minimum));
  }
  if (option.maximum !== null && option.maximum !== undefined) {
    meta.append(make("span", "", "最大 " + option.maximum));
  }
  row.append(meta);
  return row;
}

async function loadPreview(key, frame) {
  const cached = state.previewCache.get(key);
  if (cached) {
    fillPreview(frame, key, cached);
    return;
  }
  try {
    const data = await apiGet("dashboard/preview", { key });
    if (state.detailKey !== key) {
      return;
    }
    state.previewCache.set(key, data.data_url);
    if (state.previewCache.size > 40) {
      state.previewCache.delete(state.previewCache.keys().next().value);
    }
    fillPreview(frame, key, data.data_url);
  } catch (error) {
    if (state.detailKey !== key) {
      return;
    }
    clear(frame);
    frame.append(make("p", "region-message is-error", error.message || "预览生成失败。"));
  }
}

function fillPreview(frame, key, dataUrl) {
  clear(frame);
  const image = make("img");
  image.src = dataUrl;
  image.alt = key + " 的效果预览";
  image.loading = "lazy";
  image.addEventListener("click", () => openLightbox(dataUrl, key + " · 效果预览"));
  frame.append(image);
}

function materialThumb(key, material) {
  const button = make("button", "material-thumb is-loading");
  button.type = "button";
  button.dataset.key = key;
  button.dataset.name = material.name;
  button.title = material.name + " · " + formatBytes(material.size);
  button.setAttribute("aria-label", "查看素材 " + material.name);
  button.append(make("span", "material-name", material.name));
  return button;
}

let materialObserver = null;
const materialQueue = [];
let materialActive = 0;

function observeMaterials(grid) {
  materialObserver?.disconnect();
  materialObserver = new IntersectionObserver(
    (entries) => {
      for (const entry of entries) {
        if (!entry.isIntersecting) {
          continue;
        }
        materialObserver?.unobserve(entry.target);
        materialQueue.push(entry.target);
        pumpMaterialQueue();
      }
    },
    { root: dom.drawerBody, rootMargin: "160px" },
  );
  for (const thumb of grid.querySelectorAll(".material-thumb")) {
    materialObserver.observe(thumb);
  }
}

function pumpMaterialQueue() {
  while (materialActive < 3 && materialQueue.length) {
    const target = materialQueue.shift();
    materialActive += 1;
    void loadMaterial(target).finally(() => {
      materialActive -= 1;
      pumpMaterialQueue();
    });
  }
}

async function loadMaterial(button) {
  const key = button.dataset.key || "";
  const name = button.dataset.name || "";
  const cacheKey = key + "::" + name;
  try {
    let dataUrl = state.materialCache.get(cacheKey);
    if (!dataUrl) {
      const data = await apiGet("dashboard/material", { key, name });
      dataUrl = data.data_url;
      state.materialCache.set(cacheKey, dataUrl);
      if (state.materialCache.size > 200) {
        state.materialCache.delete(state.materialCache.keys().next().value);
      }
    }
    if (!button.isConnected) {
      return;
    }
    const image = make("img");
    image.src = dataUrl;
    image.alt = name;
    button.classList.remove("is-loading");
    button.prepend(image);
    button.addEventListener("click", () => openLightbox(dataUrl, key + " · " + name));
  } catch {
    if (button.isConnected) {
      button.classList.remove("is-loading");
      button.classList.add("is-error");
      button.title = name + " 读取失败";
    }
  }
}

/* --- 灯箱 ---------------------------------------------------------------- */

function openLightbox(dataUrl, caption) {
  dom.lightboxImage.src = dataUrl;
  dom.lightboxImage.alt = caption;
  dom.lightboxCaption.textContent = caption;
  dom.lightbox.hidden = false;
  dom.lightboxClose.focus({ preventScroll: true });
}

function closeLightbox() {
  dom.lightbox.hidden = true;
  dom.lightboxImage.removeAttribute("src");
}

/* --- 使用记录 ------------------------------------------------------------ */

function renderSessions() {
  clear(dom.sessionList);
  const items = state.history.conversations || [];
  if (!items.length) {
    dom.sessionList.append(emptyState("暂无会话记录", "有人成功生成表情后，这里会出现所在会话。"));
    return;
  }
  const sorted = [...items].sort((left, right) => (Number(right.count) || 0) - (Number(left.count) || 0));
  for (const item of sorted) {
    const row = make("button", "session-row");
    row.type = "button";
    row.style.setProperty("--hue", String(hueOf(item.session)));
    row.setAttribute("aria-pressed", String(state.session === item.session));
    const avatar = make("span", "session-avatar", glyphOf(shortSession(item.session)));
    avatar.setAttribute("aria-hidden", "true");
    const copy = make("div", "session-copy");
    copy.append(
      make("strong", "", shortSession(item.session)),
      make("small", "", (item.platform || "--") + " · 最近 " + (item.last_key || "--") + " · " + relativeTime(item.last_used_at)),
    );
    row.append(avatar, copy, chip(formatNumber(item.count) + " 次", "is-mono"));
    row.addEventListener("click", () => {
      state.session = state.session === item.session ? "" : item.session;
      void loadHistory();
    });
    dom.sessionList.append(row);
  }
}

function renderHistory() {
  const items = state.history.items || [];
  dom.recordsCount.textContent = formatNumber(items.length) + " 条";
  clear(dom.historyBody);
  if (!items.length) {
    dom.historyBody.append(emptyState("暂无记录", "被选中的会话还没有生成过表情。"));
    return;
  }
  if (state.recordsMode === "table") {
    dom.historyBody.append(historyTable(items));
    return;
  }
  const timeline = make("div", "timeline");
  for (const group of groupByDay(items)) {
    timeline.append(make("p", "timeline-day", group.label));
    for (const record of group.items) {
      timeline.append(timelineRow(record));
    }
  }
  dom.historyBody.append(timeline);
}

function historyTable(items) {
  const wrap = make("div", "table-wrap");
  const table = make("table", "history-table");
  const head = make("thead");
  const headRow = make("tr");
  for (const [label, className] of [["时间", "col-time"], ["用户", "col-who"], ["触发词", "col-key"], ["Meme", "col-key"], ["会话", "col-who"]]) {
    const cell = make("th", className, label);
    cell.scope = "col";
    headRow.append(cell);
  }
  head.append(headRow);
  const body = make("tbody");
  for (const record of items) {
    const row = make("tr");
    row.append(make("td", "col-time", formatDateTime(record.created_at)));
    row.append(make("td", "col-who", record.sender_name || record.sender_id || "--"));
    row.append(make("td", "col-key", record.trigger || "--"));
    const keyCell = make("td", "col-key");
    const link = make("button", "", record.key);
    link.type = "button";
    link.addEventListener("click", () => void openDetail(record.key));
    keyCell.append(link);
    row.append(keyCell);
    row.append(make("td", "col-who", (record.platform || "--") + " / " + shortSession(record.session)));
    body.append(row);
  }
  table.append(head, body);
  wrap.append(table);
  return wrap;
}

function renderSessionOptions() {
  const items = state.history.conversations || [];
  clear(dom.sessionFilter);
  const all = make("option", "", "全部会话");
  all.value = "";
  dom.sessionFilter.append(all);
  for (const item of items) {
    const option = make("option", "", shortSession(item.session) + "（" + (item.platform || "--") + "）");
    option.value = item.session;
    dom.sessionFilter.append(option);
  }
  const known = items.some((item) => item.session === state.session);
  dom.sessionFilter.value = known ? state.session : "";
  if (!known) {
    state.session = "";
  }
}

/* --- 数据加载 ------------------------------------------------------------ */

async function loadOverview() {
  const requestId = ++state.requests.overview;
  try {
    const data = await apiGet("dashboard/overview");
    if (requestId !== state.requests.overview) {
      return;
    }
    state.overview = data;
    renderOverview();
    setStatus("运行中 · " + formatNumber(data.enabled_memes) + " 个可用", "ok");
  } catch (error) {
    if (requestId !== state.requests.overview) {
      return;
    }
    setStatus(error.message || "读取概览失败", "error");
    renderOverview();
    throw error;
  }
}

async function loadCatalog({ resetOffset = false } = {}) {
  if (resetOffset) {
    state.catalog.offset = 0;
  }
  const requestId = ++state.requests.catalog;
  setMessage(dom.catalogMessage, "正在读取表情库...");
  if (!state.catalog.items.length) {
    clear(dom.memeGrid);
    dom.memeGrid.append(skeleton(8));
  }
  try {
    const data = await apiGet("dashboard/memes", {
      q: state.filters.q,
      tag: state.filters.tag,
      status: state.filters.status,
      source: state.filters.source,
      sort: state.filters.sort,
      offset: state.catalog.offset,
      limit: PAGE_SIZE,
    });
    if (requestId !== state.requests.catalog) {
      return;
    }
    state.catalog = {
      items: data.items || [],
      total: Number(data.total) || 0,
      tags: data.tags || [],
      sources: data.sources || [],
      offset: Number(data.offset) || 0,
      limit: Number(data.limit) || PAGE_SIZE,
    };
    if (!state.catalog.items.length && state.catalog.offset > 0 && state.catalog.total > 0) {
      state.catalog.offset = 0;
      await loadCatalog();
      return;
    }
    state.filters.sort = data.sort || state.filters.sort;
    dom.sortFilter.value = state.filters.sort;
    renderTagOptions();
    renderSourceChips();
    setMessage(dom.catalogMessage);
    renderCatalog();
  } catch (error) {
    if (requestId !== state.requests.catalog) {
      return;
    }
    state.catalog.items = [];
    renderCatalog();
    setMessage(dom.catalogMessage, error.message || "读取表情库失败。", true);
  }
}

async function loadHistory() {
  const requestId = ++state.requests.history;
  setMessage(dom.historyMessage, "正在读取使用记录...");
  try {
    const data = await apiGet("dashboard/history", { session: state.session, limit: HISTORY_LIMIT });
    if (requestId !== state.requests.history) {
      return;
    }
    state.history = { items: data.items || [], conversations: data.conversations || [] };
    renderSessionOptions();
    renderSessions();
    renderHistory();
    setMessage(dom.historyMessage);
  } catch (error) {
    if (requestId !== state.requests.history) {
      return;
    }
    state.history = { items: [], conversations: [] };
    renderSessions();
    renderHistory();
    setMessage(dom.historyMessage, error.message || "读取使用记录失败。", true);
  }
}

async function setEnabled(key, enabled, control) {
  if (control) {
    control.disabled = true;
  }
  try {
    const data = await apiPost("dashboard/meme-enabled", { key, enabled });
    applyItemUpdate(data.item);
    toast(data.item.key + " 已" + (enabled ? "启用" : "禁用") + "。");
    void loadOverview().catch(() => {});
  } catch (error) {
    toast(error.message || "保存状态失败。", "error");
  } finally {
    if (control) {
      control.disabled = false;
    }
  }
}

function applyItemUpdate(item) {
  for (const existing of state.catalog.items) {
    if (existing.key === item.key) {
      Object.assign(existing, item);
    }
  }
  if (state.detail?.key === item.key) {
    Object.assign(state.detail, item);
    renderDetail(state.detail);
  }
  renderCatalog();
}

async function bulkSetEnabled(enabled) {
  const keys = [...state.selection];
  if (!keys.length) {
    return;
  }
  state.bulkBusy = true;
  renderBulkBar();
  try {
    const data = await apiPost("dashboard/memes-enabled", { keys, enabled });
    for (const item of data.items || []) {
      for (const existing of state.catalog.items) {
        if (existing.key === item.key) {
          Object.assign(existing, item);
        }
      }
    }
    const missing = (data.missing || []).length;
    toast(
      formatNumber((data.items || []).length) + " 个表情已" + (enabled ? "启用" : "禁用") + (missing ? "，" + missing + " 个未找到" : "") + "。",
      missing ? "error" : "ok",
    );
    state.selection.clear();
    renderCatalog();
    if (state.filters.status !== "all") {
      await loadCatalog();
    }
    void loadOverview().catch(() => {});
  } catch (error) {
    toast(error.message || "批量保存失败。", "error");
  } finally {
    state.bulkBusy = false;
    renderBulkBar();
  }
}

async function refreshAll() {
  dom.refresh.disabled = true;
  dom.refresh.classList.add("is-spinning");
  try {
    const results = await Promise.allSettled([loadOverview(), loadCatalog(), loadHistory()]);
    const failed = results.find((result) => result.status === "rejected");
    if (failed) {
      throw failed.reason;
    }
    if (state.detailKey) {
      await openDetail(state.detailKey);
    }
  } catch (error) {
    setStatus(error?.message || "刷新失败", "error");
  } finally {
    dom.refresh.disabled = false;
    dom.refresh.classList.remove("is-spinning");
  }
}

/* --- 事件绑定 ------------------------------------------------------------ */

function bindEvents() {
  for (const item of dom.navItems) {
    item.addEventListener("click", () => {
      setView(item.dataset.viewTarget);
      if (item.dataset.viewTarget === "records" && !state.history.items.length) {
        void loadHistory();
      }
    });
  }
  window.addEventListener("hashchange", () => setView(viewFromHash(), { syncHash: false }));

  for (const button of dom.themeButtons) {
    button.addEventListener("click", () => applyThemeMode(button.dataset.themeMode));
  }
  systemDark?.addEventListener?.("change", () => {
    if (state.themeMode === "system") {
      applyThemeMode("system", false);
    }
  });

  dom.refresh.addEventListener("click", () => void refreshAll());

  let searchTimer = 0;
  dom.search.addEventListener("input", () => {
    window.clearTimeout(searchTimer);
    searchTimer = window.setTimeout(() => {
      state.filters.q = dom.search.value.trim();
      void loadCatalog({ resetOffset: true });
    }, 220);
  });
  dom.tagFilter.addEventListener("change", () => {
    state.filters.tag = dom.tagFilter.value;
    void loadCatalog({ resetOffset: true });
  });
  dom.statusFilter.addEventListener("change", () => {
    state.filters.status = dom.statusFilter.value;
    void loadCatalog({ resetOffset: true });
  });
  dom.sortFilter.addEventListener("change", () => {
    state.filters.sort = dom.sortFilter.value;
    void loadCatalog({ resetOffset: true });
  });
  for (const button of dom.layoutButtons) {
    button.addEventListener("click", () => setLayout(button.dataset.layout));
  }
  dom.selectModeButton.addEventListener("click", () => setSelectMode(!state.selectMode));
  dom.bulkSelectPage.addEventListener("click", togglePageSelection);
  dom.bulkEnable.addEventListener("click", () => void bulkSetEnabled(true));
  dom.bulkDisable.addEventListener("click", () => void bulkSetEnabled(false));
  dom.bulkClear.addEventListener("click", () => {
    state.selection.clear();
    renderCatalog();
  });
  dom.previousPage.addEventListener("click", () => {
    state.catalog.offset = Math.max(0, state.catalog.offset - PAGE_SIZE);
    void loadCatalog();
  });
  dom.nextPage.addEventListener("click", () => {
    state.catalog.offset += PAGE_SIZE;
    void loadCatalog();
  });

  dom.sessionFilter.addEventListener("change", () => {
    state.session = dom.sessionFilter.value;
    void loadHistory();
  });
  dom.clearSessionFilter.addEventListener("click", () => {
    state.session = "";
    void loadHistory();
  });
  for (const button of dom.recordsModeButtons) {
    button.addEventListener("click", () => {
      state.recordsMode = button.dataset.recordsMode;
      for (const other of dom.recordsModeButtons) {
        other.setAttribute("aria-selected", String(other === button));
      }
      renderHistory();
    });
  }

  dom.drawerClose.addEventListener("click", closeDrawer);
  dom.drawerBackdrop.addEventListener("click", closeDrawer);
  dom.lightboxClose.addEventListener("click", closeLightbox);
  dom.lightbox.addEventListener("click", (event) => {
    if (event.target === dom.lightbox || event.target === dom.lightboxImage.parentElement) {
      closeLightbox();
    }
  });

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      if (!dom.lightbox.hidden) {
        closeLightbox();
        return;
      }
      if (!dom.drawer.hidden) {
        closeDrawer();
      }
      return;
    }
    if (event.key === "/" && !event.ctrlKey && !event.metaKey && !event.altKey) {
      if (!dom.drawer.hidden || !dom.lightbox.hidden) {
        return;
      }
      const tag = document.activeElement?.tagName;
      if (tag === "INPUT" || tag === "SELECT" || tag === "TEXTAREA") {
        return;
      }
      event.preventDefault();
      setView("library");
      dom.search.focus();
    }
  });
}

function setLayout(layout) {
  state.layout = layout === "list" ? "list" : "grid";
  for (const button of dom.layoutButtons) {
    button.setAttribute("aria-selected", String(button.dataset.layout === state.layout));
  }
  try {
    window.localStorage.setItem(LAYOUT_STORAGE_KEY, state.layout);
  } catch {
    // 忽略存储不可用。
  }
  renderCatalog();
}

/* --- 启动 ---------------------------------------------------------------- */

function restorePreferences() {
  let theme = "system";
  let layout = "grid";
  try {
    theme = window.localStorage.getItem(THEME_STORAGE_KEY) || "system";
    layout = window.localStorage.getItem(LAYOUT_STORAGE_KEY) || "grid";
  } catch {
    // 忽略存储不可用。
  }
  applyThemeMode(theme, false);
  setLayout(layout);
}

async function boot() {
  restorePreferences();
  bindEvents();
  setView(viewFromHash(), { syncHash: false });
  setStatus("正在连接...", "warn");
  renderOverview();

  if (!bridge) {
    const message = "AstrBot 页面桥接未加载，请在 AstrBot Dashboard 内打开本页面。";
    setStatus("桥接未加载", "error");
    setMessage(dom.catalogMessage, message, true);
    setMessage(dom.historyMessage, message, true);
    return;
  }
  try {
    await bridge.ready();
  } catch (error) {
    const message = error?.message || "页面初始化失败。";
    setStatus("初始化失败", "error");
    setMessage(dom.catalogMessage, message, true);
    setMessage(dom.historyMessage, message, true);
    return;
  }
  await refreshAll();
}

void boot();
