/* Meme 工坊 · Dashboard 前端
   总览 / 表情库 / 工作台 / 记录 四个标签页，全部数据来自插件注册的 dashboard/* 接口。 */

const PAGE_SIZE = 48;
const HISTORY_LIMIT = 60;
const BULK_LIMIT = 200;
const THEME_KEY = "meme-forge-theme";
const DENSITY_KEY = "meme-forge-density";
const VIEW_KEY = "meme-forge-view";
const THUMB_KEY = "meme-forge-thumbs";
const THEMES = ["aurora", "midnight", "carbon", "plum", "daylight", "paper"];
const TABS = ["overview", "library", "maker", "records"];

const SOURCE_INFO = {
  meme_generator: { label: "内置", color: "#38bdf8" },
  external: { label: "meme_emoji", color: "#a78bfa" },
  gouqi: { label: "枸杞", color: "#f97316" },
  maker: { label: "自制", color: "#34d399" },
};

const SLOT_COLOR = { image: "#38bdf8", text: "#f472b6" };

const MAKER_DEFAULTS = {
  key: "",
  title: "",
  keywords: [],
  width: 640,
  height: 640,
  background: "#101418",
  slots: [],
};

/* ---------- 桥接与工具 ---------- */

const bridge = window.AstrBotPluginPage;

function unwrap(payload) {
  if (!payload || payload.ok !== true) {
    throw new Error((payload && (payload.error || payload.message)) || "接口返回异常");
  }
  return payload;
}

async function apiGet(endpoint, params) {
  return unwrap(await bridge.apiGet(endpoint, params));
}

async function apiPost(endpoint, body) {
  return unwrap(await bridge.apiPost(endpoint, body));
}

const $ = (id) => document.getElementById(id);

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined && text !== null) node.textContent = String(text);
  return node;
}

function icon(name, className) {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  if (className) svg.setAttribute("class", className);
  svg.setAttribute("aria-hidden", "true");
  const use = document.createElementNS("http://www.w3.org/2000/svg", "use");
  use.setAttribute("href", "#" + name);
  svg.appendChild(use);
  return svg;
}

function clear(node) {
  while (node.firstChild) node.removeChild(node.firstChild);
  return node;
}

function row(label, value, valueClass) {
  const wrap = el("div");
  wrap.appendChild(el("dt", null, label));
  wrap.appendChild(el("dd", valueClass || null, value));
  return wrap;
}

function clamp(value, min, max, fallback) {
  const number = Number(value);
  if (!Number.isFinite(number)) return fallback;
  return Math.min(max, Math.max(min, number));
}

function formatTime(seconds) {
  if (!seconds) return "--";
  const date = new Date(Number(seconds) * 1000);
  if (Number.isNaN(date.getTime())) return "--";
  const pad = (n) => String(n).padStart(2, "0");
  return pad(date.getMonth() + 1) + "-" + pad(date.getDate()) + " " + pad(date.getHours()) + ":" + pad(date.getMinutes());
}

function shortSession(text) {
  const value = String(text || "");
  if (value.length <= 22) return value;
  return value.slice(0, 10) + "…" + value.slice(-10);
}

function hueOf(text) {
  let hash = 0;
  for (let index = 0; index < text.length; index += 1) {
    hash = (hash * 31 + text.charCodeAt(index)) % 360;
  }
  return hash;
}

function sourceOf(key) {
  return SOURCE_INFO[key] || { label: key || "未知", color: "#94a3b8" };
}

function debounce(fn, wait) {
  let timer = 0;
  return (...args) => {
    window.clearTimeout(timer);
    timer = window.setTimeout(() => fn(...args), wait);
  };
}

async function readFileAsDataUrl(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result || ""));
    reader.onerror = () => reject(new Error("读取文件失败"));
    reader.readAsDataURL(file);
  });
}

/* ---------- 轻量缓存 ---------- */

class LruCache {
  constructor(limit) {
    this.limit = limit;
    this.map = new Map();
  }

  get(key) {
    if (!this.map.has(key)) return undefined;
    const value = this.map.get(key);
    this.map.delete(key);
    this.map.set(key, value);
    return value;
  }

  set(key, value) {
    if (this.map.has(key)) this.map.delete(key);
    this.map.set(key, value);
    while (this.map.size > this.limit) {
      this.map.delete(this.map.keys().next().value);
    }
  }

  clear() {
    this.map.clear();
  }
}

const previewCache = new LruCache(60);
const materialCache = new LruCache(200);

/* ---------- 提示 ---------- */

function toast(message, kind) {
  const stack = $("toast-stack");
  const node = el("div", "toast" + (kind ? " is-" + kind : ""));
  node.appendChild(icon(kind === "error" ? "i-alert" : kind === "ok" ? "i-check" : "i-info"));
  node.appendChild(el("span", null, message));
  stack.appendChild(node);
  window.setTimeout(() => {
    node.classList.add("is-out");
    window.setTimeout(() => node.remove(), 260);
  }, kind === "error" ? 5200 : 3000);
}

function reportError(error, prefix) {
  const message = (error && error.message) || String(error);
  toast((prefix ? prefix + "：" : "") + message, "error");
}

/* ---------- 全局状态 ---------- */

const state = {
  overview: null,
  tab: "overview",
  library: {
    items: [],
    total: 0,
    offset: 0,
    query: "",
    tag: "",
    status: "",
    source: "",
    sort: "key",
    view: "grid",
    thumbs: false,
    selecting: false,
    picked: new Set(),
    loading: false,
    token: 0,
  },
  maker: {
    limits: null,
    templates: [],
    draft: null,
    savedKey: null,
    activeSlot: -1,
    baseUpload: null,
    overlayUpload: null,
    baseUrl: null,
    overlayUrl: null,
    removeBase: false,
    removeOverlay: false,
    dirty: false,
    grid: true,
    scale: 1,
    enabled: true,
    busy: false,
  },
  records: { items: [], conversations: [], session: "", limit: HISTORY_LIMIT },
};


/* ---------- 总览 ---------- */

function statCard(value, label, flavour) {
  const node = el("div", "stat" + (flavour ? " is-" + flavour : ""));
  node.appendChild(el("b", null, value));
  node.appendChild(el("span", null, label));
  return node;
}

function noteInto(node, text, flavour, iconName) {
  clear(node);
  node.className = "note" + (flavour ? " is-" + flavour : "");
  node.appendChild(icon(iconName || (flavour === "warn" ? "i-alert" : flavour === "danger" ? "i-alert" : "i-info")));
  node.appendChild(el("span", null, text));
}

function sourceChip(name, count) {
  const info = sourceOf(name);
  const chip = el("span", "chip");
  const dot = el("i", "dot-source");
  dot.style.setProperty("--src-color", info.color);
  chip.appendChild(dot);
  chip.appendChild(el("span", null, info.label));
  chip.appendChild(el("b", "mono", String(count)));
  return chip;
}

function renderBars(node, items, emptyText) {
  clear(node);
  if (!items || !items.length) {
    node.appendChild(el("li", "empty is-inline", emptyText || "暂无数据"));
    return;
  }
  const top = Math.max(...items.map((item) => Number(item.count) || 0), 1);
  for (const item of items) {
    const count = Number(item.count) || 0;
    const li = el("li");
    const head = el("div", "bar-top");
    head.appendChild(el("b", null, item.key));
    head.appendChild(el("span", "mono", count + " 次"));
    const track = el("div", "bar-track");
    const fill = el("div", "bar-fill");
    fill.style.width = Math.max(4, Math.round((count / top) * 100)) + "%";
    track.appendChild(fill);
    li.appendChild(head);
    li.appendChild(track);
    node.appendChild(li);
  }
}

function renderSessionList(node, items, onPick) {
  clear(node);
  if (!items || !items.length) {
    node.appendChild(el("li", "empty is-inline", "还没有会话记录"));
    return;
  }
  for (const item of items) {
    const li = el("li");
    const copy = el("div", "mini-copy");
    copy.appendChild(el("b", null, item.platform ? item.platform + " · " + shortSession(item.session) : shortSession(item.session)));
    copy.appendChild(el("small", null, "最近 " + (item.last_key || "--") + " · " + formatTime(item.last_used_at)));
    li.appendChild(copy);
    li.appendChild(el("span", "mini-val", (Number(item.count) || 0) + " 次"));
    if (onPick) {
      li.style.cursor = "pointer";
      li.addEventListener("click", () => onPick(item.session));
    }
    node.appendChild(li);
  }
}

function renderFeed(node, items) {
  clear(node);
  if (!items || !items.length) {
    node.appendChild(el("li", "empty is-inline", "还没有生成记录，去群里发一条试试"));
    return;
  }
  for (const item of items) {
    const li = el("li");
    li.appendChild(el("time", null, formatTime(item.created_at)));
    const dot = el("i", "dot-source");
    dot.style.setProperty("--src-color", "var(--accent)");
    li.appendChild(dot);
    li.appendChild(el("span", "feed-key", item.key));
    const who = item.sender_name || item.sender_id || "匿名";
    li.appendChild(el("span", "feed-meta", who + " · " + shortSession(item.session)));
    node.appendChild(li);
  }
}

function renderOverview() {
  const data = state.overview;
  if (!data) return;
  const total = Number(data.total_memes) || 0;
  const enabled = Number(data.enabled_memes) || 0;
  const disabled = Number(data.disabled_memes) || 0;

  $("hero-version").textContent = data.engine_version || "unknown";
  $("hero-count").textContent = total + " 个表情";
  $("chip-prefix").textContent = data.trigger_prefix ? data.trigger_prefix : "（未设置）";
  $("brand-sub").textContent = "本地表情包工厂 · " + total + " 个表情 · " + (data.tag_count || 0) + " 个标签";

  const stats = clear($("hero-stats"));
  stats.appendChild(statCard(String(enabled), "可用表情", "accent"));
  stats.appendChild(statCard(String(disabled), "已禁用", disabled ? "warn" : null));
  stats.appendChild(statCard(String(data.tag_count || 0), "标签种类"));
  stats.appendChild(statCard(String(data.usage_records || 0), "累计生成"));

  const engine = clear($("engine-rows"));
  engine.appendChild(row("表情总数", String(total), "mono"));
  engine.appendChild(row("可用", String(enabled), "mono is-ok"));
  engine.appendChild(row("已禁用", String(disabled), disabled ? "mono is-warn" : "mono"));
  engine.appendChild(row("引擎版本", data.engine_version || "--", "mono"));
  const sources = clear($("engine-sources"));
  sources.className = "chip-row is-tight";
  for (const item of data.sources || []) sources.appendChild(sourceChip(item.source, item.count));

  const ext = data.extension || {};
  const extRows = clear($("extension-rows"));
  extRows.appendChild(row("安装状态", ext.installed ? "已安装" : "未安装", ext.installed ? "is-ok" : "is-off"));
  extRows.appendChild(row("版本标签", ext.tag || "--", "mono"));
  extRows.appendChild(row("表情库", ext.library_valid ? "可用" : "缺失", ext.library_valid ? "is-ok" : "is-warn"));
  extRows.appendChild(row("素材资源", ext.resources_present ? "完整" : "缺失", ext.resources_present ? "is-ok" : "is-warn"));
  if (!ext.installed) {
    noteInto($("extension-note"), "尚未安装扩展表情库。在聊天里发送「meme扩展安装」即可拉取 meme_emoji 的表情。", "warn");
  } else if (!ext.library_valid || !ext.resources_present) {
    noteInto($("extension-note"), "扩展已下载但资源不完整，发送「meme扩展更新」重新同步。", "danger");
  } else {
    noteInto($("extension-note"), "扩展表情已并入统一表情库，可与内置表情一起搜索和禁用。", null, "i-check");
  }

  const gouqi = data.gouqi_extension || {};
  const gouqiRows = clear($("gouqi-rows"));
  gouqiRows.appendChild(row("安装状态", gouqi.installed ? "已安装" : "未安装", gouqi.installed ? "is-ok" : "is-off"));
  gouqiRows.appendChild(row("模板数量", String(gouqi.templates || 0), "mono"));
  gouqiRows.appendChild(row("素材校验", gouqi.assets_valid ? "通过" : "缺失", gouqi.assets_valid ? "is-ok" : "is-warn"));
  gouqiRows.appendChild(row("提交版本", gouqi.commit ? String(gouqi.commit).slice(0, 10) : "--", "mono"));
  if (!gouqi.installed) {
    noteInto($("gouqi-note"), "Gouqi 扩展提供一批本地绘制的整图模板，发送「meme枸杞安装」即可启用。", "warn");
  } else {
    noteInto($("gouqi-note"), "模板由插件内的 Pillow 渲染，不依赖任何外部接口。", null, "i-shield");
  }

  const maker = data.maker || {};
  const makerRows = clear($("maker-rows"));
  makerRows.appendChild(row("功能状态", maker.enabled ? "已开启" : "已关闭", maker.enabled ? "is-ok" : "is-off"));
  makerRows.appendChild(row("自制模板", String(maker.total || 0), "mono"));
  const limits = maker.limits || {};
  const canvas = limits.canvas || {};
  const limitBox = clear($("maker-limits"));
  limitBox.className = "subcard";
  if (maker.enabled) {
    limitBox.appendChild(el("p", null,
      "上限：" + (limits.templates || 0) + " 个模板 · " + (limits.slots || 0) + " 个图层（图片 " +
      (limits.image_slots || 0) + " / 文字 " + (limits.text_slots || 0) + "） · 画布 " +
      (canvas.min || 0) + "~" + (canvas.max || 0) + "px · 单张素材 " + (limits.asset_mb || 0) + "MB"));
  } else {
    limitBox.appendChild(el("p", null, "在插件配置中开启 maker_enabled 后即可使用工作台。"));
  }

  renderBars($("top-memes"), data.top_memes, "还没有人用过表情");
  renderSessionList($("active-sessions"), data.active_conversations, (session) => {
    state.records.session = session;
    switchTab("records");
    $("rec-session").value = session;
    loadRecords().catch((error) => reportError(error, "记录"));
  });
  renderFeed($("recent-feed"), data.recent_records);

  $("tab-badge-library").textContent = String(total);
  const makerOn = maker.enabled !== false;
  const makerBadge = $("tab-badge-maker");
  makerBadge.textContent = makerOn ? String(maker.total || 0) : "关";
  makerBadge.classList.toggle("is-off", !makerOn);
  state.maker.enabled = makerOn;
  if (maker.limits) state.maker.limits = maker.limits;
  updateStatusLine();
}

function updateStatusLine() {
  const data = state.overview;
  const parts = [];
  if (data) {
    parts.push("v" + (data.engine_version || "?"));
    parts.push(data.total_memes + " 表情");
    parts.push((data.enabled_memes || 0) + " 可用");
    if (data.disabled_memes) parts.push(data.disabled_memes + " 已禁用");
  }
  if (state.tab === "library" && state.library.total) {
    parts.push("筛选 " + state.library.total + " 项");
  }
  if (state.tab === "maker") {
    parts.push((state.maker.templates.length || 0) + " 个自制模板");
    if (state.maker.dirty) parts.push("未保存");
  }
  $("status-left").textContent = parts.length ? parts.join(" · ") : "--";
}

async function loadOverview() {
  try {
    const payload = await apiGet("dashboard/overview");
    state.overview = payload;
    renderOverview();
  } catch (error) {
    reportError(error, "总览加载失败");
  }
}


/* ---------- 表情库 ---------- */

const thumbQueue = { running: 0, waiting: [] };

function queueThumb(job) {
  thumbQueue.waiting.push(job);
  pumpThumbs();
}

function pumpThumbs() {
  while (thumbQueue.running < 3 && thumbQueue.waiting.length) {
    const job = thumbQueue.waiting.shift();
    thumbQueue.running += 1;
    job().catch(() => {}).finally(() => {
      thumbQueue.running -= 1;
      pumpThumbs();
    });
  }
}

let thumbObserver = null;

function ensureThumbObserver() {
  if (thumbObserver) return thumbObserver;
  thumbObserver = new IntersectionObserver((entries) => {
    for (const entry of entries) {
      if (!entry.isIntersecting) continue;
      const node = entry.target;
      thumbObserver.unobserve(node);
      queueThumb(() => fillThumb(node));
    }
  }, { rootMargin: "240px 0px" });
  return thumbObserver;
}

async function fillThumb(node) {
  const key = node.dataset.key;
  if (!key || node.dataset.filled === "1") return;
  node.dataset.filled = "1";
  const cached = previewCache.get(key);
  if (cached) {
    paintThumb(node, cached);
    return;
  }
  try {
    const payload = await apiGet("dashboard/preview", { key });
    previewCache.set(key, payload.data_url);
    paintThumb(node, payload.data_url);
  } catch {
    node.dataset.filled = "";
  }
}

function paintThumb(node, dataUrl) {
  const image = el("img");
  image.src = dataUrl;
  image.alt = node.dataset.key || "";
  image.loading = "lazy";
  clear(node).appendChild(image);
  node.classList.add("checker");
}

function memeCard(item) {
  const card = el("article", "meme");
  card.dataset.key = item.key;
  card.tabIndex = 0;
  card.setAttribute("role", "button");
  if (!item.enabled) card.classList.add("is-disabled");
  if (state.library.picked.has(item.key)) card.classList.add("is-picked");

  const info = sourceOf(item.source);
  const glyphText = String((item.keywords && item.keywords[0]) || item.key || "?").slice(0, 1);
  const thumb = el("div", "meme-thumb");
  thumb.dataset.key = item.key;
  thumb.style.setProperty("--glyph", "hsl(" + hueOf(item.key) + " 72% 62%)");
  if (state.library.thumbs) {
    ensureThumbObserver().observe(thumb);
    thumb.appendChild(el("div", "skeleton"));
    thumb.firstChild.style.cssText = "position:absolute;inset:0";
  } else {
    thumb.appendChild(el("span", "meme-glyph", glyphText));
  }
  card.appendChild(thumb);

  const body = el("div", "meme-body");
  const keyLine = el("div", "meme-key");
  const dot = el("i", "dot-source");
  dot.style.setProperty("--src-color", info.color);
  dot.title = info.label;
  keyLine.appendChild(dot);
  keyLine.appendChild(el("b", "mono", item.key));
  if (!item.enabled) keyLine.appendChild(el("span", "chip is-off", "已禁用"));
  body.appendChild(keyLine);
  body.appendChild(el("div", "meme-kw", (item.keywords || []).join(" · ") || "无触发词"));
  card.appendChild(body);

  const foot = el("div", "meme-foot");
  const imageIo = el("span", "io");
  imageIo.appendChild(icon("i-image"));
  imageIo.appendChild(el("span", null, item.images ? item.images.label : "0"));
  const textIo = el("span", "io");
  textIo.appendChild(icon("i-text"));
  textIo.appendChild(el("span", null, item.texts ? item.texts.label : "0"));
  foot.appendChild(imageIo);
  foot.appendChild(textIo);
  if (item.has_materials) {
    const mat = el("span", "io");
    mat.appendChild(icon("i-puzzle"));
    mat.appendChild(el("span", null, "素材"));
    foot.appendChild(mat);
  }
  foot.appendChild(el("span", "io", info.label));
  card.appendChild(foot);

  if (state.library.selecting) {
    const pick = el("button", "btn is-icon is-tiny meme-pick");
    pick.type = "button";
    pick.title = "选择";
    if (state.library.picked.has(item.key)) pick.classList.add("is-on");
    pick.appendChild(icon(state.library.picked.has(item.key) ? "i-check" : "i-select"));
    pick.addEventListener("click", (event) => {
      event.stopPropagation();
      togglePick(item.key);
    });
    card.appendChild(pick);
  }

  card.addEventListener("click", () => {
    if (state.library.selecting) togglePick(item.key);
    else openMeme(item.key);
  });
  card.addEventListener("keydown", (event) => {
    if (event.key !== "Enter" && event.key !== " ") return;
    event.preventDefault();
    card.click();
  });
  return card;
}

function togglePick(key) {
  const picked = state.library.picked;
  if (picked.has(key)) picked.delete(key);
  else if (picked.size >= BULK_LIMIT) {
    toast("一次最多选择 " + BULK_LIMIT + " 个表情", "error");
    return;
  } else picked.add(key);
  renderLibraryGrid();
  renderBulkbar();
}

function renderBulkbar() {
  const bar = $("bulkbar");
  const picked = state.library.picked;
  bar.hidden = !state.library.selecting;
  $("bulk-count").textContent = "已选 " + picked.size + " 项";
  $("bulk-enable").disabled = !picked.size;
  $("bulk-disable").disabled = !picked.size;
}

function fillSelect(node, values, allLabel, labeller) {
  const current = node.value;
  clear(node);
  const first = el("option", null, allLabel);
  first.value = "";
  node.appendChild(first);
  for (const value of values) {
    const option = el("option", null, labeller ? labeller(value) : value);
    option.value = value;
    node.appendChild(option);
  }
  node.value = values.includes(current) ? current : "";
}

function renderLibraryGrid() {
  const grid = clear($("lib-grid"));
  grid.dataset.view = state.library.view;
  for (const item of state.library.items) grid.appendChild(memeCard(item));
  $("lib-empty").hidden = state.library.items.length > 0;
}

function renderLibraryMeta() {
  const lib = state.library;
  const from = lib.total ? lib.offset + 1 : 0;
  const to = Math.min(lib.offset + PAGE_SIZE, lib.total);
  $("lib-meta").textContent = lib.loading ? "载入中…" : lib.total ? from + "-" + to + " / 共 " + lib.total + " 项" : "没有匹配的表情";
  const page = Math.floor(lib.offset / PAGE_SIZE) + 1;
  const pages = Math.max(1, Math.ceil(lib.total / PAGE_SIZE));
  $("lib-page").textContent = page + " / " + pages;
  $("lib-prev").disabled = lib.offset <= 0;
  $("lib-next").disabled = lib.offset + PAGE_SIZE >= lib.total;
  $("lib-search-clear").hidden = !lib.query;
}

async function loadLibrary(resetOffset) {
  const lib = state.library;
  if (resetOffset) {
    lib.offset = 0;
  }
  lib.loading = true;
  const token = (lib.token += 1);
  renderLibraryMeta();
  try {
    const payload = await apiGet("dashboard/memes", {
      q: lib.query,
      tag: lib.tag,
      status: lib.status,
      source: lib.source,
      sort: lib.sort,
      offset: lib.offset,
      limit: PAGE_SIZE,
    });
    if (token !== lib.token) return;
    lib.items = payload.items || [];
    lib.total = Number(payload.total) || 0;
    if (Array.isArray(payload.tags)) fillSelect($("lib-tag"), payload.tags, "全部标签");
    if (Array.isArray(payload.sources)) fillSelect($("lib-source"), payload.sources, "全部来源", (value) => sourceOf(value).label);
    renderLibraryGrid();
  } catch (error) {
    reportError(error, "表情列表");
  } finally {
    if (token === lib.token) {
      lib.loading = false;
      renderLibraryMeta();
      updateStatusLine();
    }
  }
}

/* ---------- 详情抽屉 ---------- */

let drawerReturn = null;

function openDrawer(title, eyebrow) {
  drawerReturn = document.activeElement;
  $("drawer-eyebrow").textContent = eyebrow || "MEME DETAIL";
  $("drawer-title").textContent = title;
  $("drawer").hidden = false;
  $("drawer-panel").focus();
}

function closeDrawer() {
  $("drawer").hidden = true;
  clear($("drawer-body"));
  if (drawerReturn && drawerReturn.focus) drawerReturn.focus();
  drawerReturn = null;
}

function openLightbox(src, caption) {
  $("lightbox-image").src = src;
  $("lightbox-caption").textContent = caption || "";
  $("lightbox").hidden = false;
  $("lightbox-close").focus();
}

function closeLightbox() {
  $("lightbox").hidden = true;
  $("lightbox-image").src = "";
}

function commandLine(text) {
  const node = el("div", "cmd");
  node.appendChild(icon("i-cursor"));
  node.appendChild(el("span", null, text));
  const copy = el("button", "btn is-icon is-tiny is-quiet");
  copy.type = "button";
  copy.title = "复制";
  copy.appendChild(icon("i-copy"));
  copy.addEventListener("click", async () => {
    try {
      await navigator.clipboard.writeText(text);
      toast("已复制指令", "ok");
    } catch {
      toast("浏览器拒绝了复制请求", "error");
    }
  });
  node.appendChild(copy);
  return node;
}

function optionItem(spec) {
  const item = el("div", "opt-item");
  const head = el("div", "opt-head");
  head.appendChild(el("code", null, spec.name));
  head.appendChild(el("span", "mono", spec.type || "text"));
  if (spec.default !== null && spec.default !== undefined && spec.default !== "") {
    head.appendChild(el("span", "mono", "默认 " + spec.default));
  }
  item.appendChild(head);
  if (spec.description) item.appendChild(el("div", "opt-desc", spec.description));
  const hints = [];
  if (spec.choices && spec.choices.length) hints.push("取值：" + spec.choices.join(" / "));
  if (spec.minimum !== null && spec.minimum !== undefined) hints.push("最小 " + spec.minimum);
  if (spec.maximum !== null && spec.maximum !== undefined) hints.push("最大 " + spec.maximum);
  if (spec.aliases && spec.aliases.length) hints.push("直接写：" + spec.aliases.join(" / "));
  if (spec.flags && spec.flags.length) hints.push("开关：" + spec.flags.join(" / "));
  if (hints.length) item.appendChild(el("div", "opt-desc mono", hints.join("　")));
  return item;
}

function detailSection(title, eyebrow) {
  const card = el("section", "card");
  if (eyebrow) card.appendChild(el("p", "eyebrow mono", eyebrow));
  if (title) card.appendChild(el("h3", null, title));
  return card;
}

async function openMeme(key) {
  openDrawer(key, "MEME DETAIL");
  const body = clear($("drawer-body"));
  const loading = el("div", "skeleton");
  loading.style.height = "220px";
  body.appendChild(loading);
  try {
    const payload = await apiGet("dashboard/meme", { key });
    renderMemeDetail(payload.item);
  } catch (error) {
    clear(body).appendChild(el("div", "note is-danger", (error && error.message) || "加载失败"));
  }
}

function renderMemeDetail(item) {
  const body = clear($("drawer-body"));
  const info = sourceOf(item.source);
  const prefix = (state.overview && state.overview.trigger_prefix) || "meme";

  const preview = el("div", "drawer-preview checker");
  const cached = previewCache.get(item.key);
  if (cached) {
    const image = el("img");
    image.src = cached;
    image.alt = item.key;
    image.addEventListener("click", () => openLightbox(cached, item.key));
    preview.appendChild(image);
  } else {
    const button = el("button", "btn is-accent");
    button.type = "button";
    button.appendChild(icon("i-play"));
    button.appendChild(el("span", null, "渲染预览"));
    button.addEventListener("click", async () => {
      button.disabled = true;
      clear(button).appendChild(el("span", null, "渲染中…"));
      try {
        const payload = await apiGet("dashboard/preview", { key: item.key });
        previewCache.set(item.key, payload.data_url);
        renderMemeDetail(item);
      } catch (error) {
        reportError(error, "预览");
        renderMemeDetail(item);
      }
    });
    preview.appendChild(button);
  }
  body.appendChild(preview);

  const chips = el("div", "chip-row");
  const sourceTag = el("span", "chip");
  const dot = el("i", "dot-source");
  dot.style.setProperty("--src-color", info.color);
  sourceTag.appendChild(dot);
  sourceTag.appendChild(el("span", null, info.label));
  chips.appendChild(sourceTag);
  chips.appendChild(el("span", "chip " + (item.enabled ? "is-on" : "is-off"), item.enabled ? "已启用" : "已禁用"));
  const toggle = el("button", "btn is-tiny " + (item.enabled ? "is-danger" : "is-accent"));
  toggle.type = "button";
  toggle.appendChild(icon(item.enabled ? "i-close" : "i-check"));
  toggle.appendChild(el("span", null, item.enabled ? "禁用此表情" : "启用此表情"));
  toggle.addEventListener("click", async () => {
    toggle.disabled = true;
    try {
      const payload = await apiPost("dashboard/meme-enabled", { key: item.key, enabled: !item.enabled });
      toast(payload.item.enabled ? "已启用 " + item.key : "已禁用 " + item.key, "ok");
      renderMemeDetail(payload.item);
      await loadLibrary(false);
      await loadOverview();
    } catch (error) {
      reportError(error, "启停失败");
      toggle.disabled = false;
    }
  });
  chips.appendChild(toggle);
  body.appendChild(chips);

  const basics = detailSection("基础信息", "SPEC");
  const rows = el("dl", "rows");
  rows.appendChild(row("Key", item.key, "mono"));
  rows.appendChild(row("来源", info.label));
  rows.appendChild(row("需要图片", item.images ? item.images.label + " 张" : "--", "mono"));
  rows.appendChild(row("需要文字", item.texts ? item.texts.label + " 段" : "--", "mono"));
  rows.appendChild(row("标签", (item.tags || []).join("、") || "无"));
  basics.appendChild(rows);
  body.appendChild(basics);

  const usage = detailSection("怎么触发", "USAGE");
  const keyword = (item.keywords && item.keywords[0]) || item.key;
  const cmds = el("div", "form-grid");
  cmds.appendChild(commandLine(prefix + " " + keyword));
  cmds.appendChild(commandLine(keyword));
  if (item.texts && item.texts.max > 0) {
    cmds.appendChild(commandLine(keyword + " 你想写的文字"));
  }
  const bare = (item.options || []).find((spec) => spec.aliases && spec.aliases.length);
  if (bare) cmds.appendChild(commandLine(keyword + " " + bare.aliases[0]));
  const flag = (item.options || []).find((spec) => spec.flags && spec.flags.length);
  if (flag) cmds.appendChild(commandLine(keyword + " " + flag.flags[0]));
  usage.appendChild(cmds);
  if (item.keywords && item.keywords.length > 1) {
    const kwRow = el("div", "chip-row is-tight");
    for (const word of item.keywords) kwRow.appendChild(el("span", "chip", word));
    usage.appendChild(kwRow);
  }
  body.appendChild(usage);

  if (item.default_texts && item.default_texts.length) {
    const section = detailSection("默认文字", "DEFAULT TEXT");
    const list = el("div", "chip-row is-tight");
    for (const text of item.default_texts) list.appendChild(el("span", "chip", text));
    section.appendChild(list);
    body.appendChild(section);
  }

  if (item.options && item.options.length) {
    const section = detailSection("可用参数", "OPTIONS");
    const list = el("div", "opt-list");
    for (const spec of item.options) list.appendChild(optionItem(spec));
    section.appendChild(list);
    section.appendChild(el("p", "opt-desc", "参数直接跟在触发词后面，例如「" + keyword + " " + ((item.options[0].aliases && item.options[0].aliases[0]) || item.options[0].name) + "」。"));
    body.appendChild(section);
  }

  const materials = item.materials || {};
  if (materials.total) {
    const section = detailSection("素材图片", "MATERIALS");
    section.appendChild(el("p", "opt-desc", "共 " + materials.total + " 张" + (materials.truncated ? "（仅列出前 " + (materials.items || []).length + " 张）" : "")));
    const grid = el("div", "mat-grid");
    for (const material of materials.items || []) {
      const cell = el("button", "mat-cell checker");
      cell.type = "button";
      cell.title = material.name;
      const cacheKey = item.key + "/" + material.name;
      const known = materialCache.get(cacheKey);
      const paint = (dataUrl) => {
        const image = el("img");
        image.src = dataUrl;
        image.alt = material.name;
        image.loading = "lazy";
        clear(cell).appendChild(image);
        cell.onclick = () => openLightbox(dataUrl, material.name);
      };
      if (known) paint(known);
      else {
        cell.appendChild(el("span", "mono", material.name.slice(0, 6)));
        cell.addEventListener("click", async () => {
          try {
            const payload = await apiGet("dashboard/material", { key: item.key, name: material.name });
            materialCache.set(cacheKey, payload.data_url);
            paint(payload.data_url);
            openLightbox(payload.data_url, material.name);
          } catch (error) {
            reportError(error, "素材");
          }
        }, { once: true });
      }
      grid.appendChild(cell);
    }
    section.appendChild(grid);
    body.appendChild(section);
  }
}


/* ---------- 工作台 ---------- */

const FIT_LABEL = { cover: "裁切填满", contain: "完整放入", stretch: "拉伸变形" };
const ALIGN_LABEL = { left: "左对齐", center: "居中", right: "右对齐" };
const VALIGN_LABEL = { top: "顶部", middle: "居中", bottom: "底部" };

function uniqueKey(base) {
  const taken = new Set(state.maker.templates.map((item) => item.key));
  if (!taken.has(base)) return base;
  for (let index = 2; index < 999; index += 1) {
    const candidate = base + "_" + index;
    if (!taken.has(candidate)) return candidate;
  }
  return base + "_" + Date.now();
}

function blankDraft() {
  const key = uniqueKey("my_meme");
  return {
    key,
    title: "我的表情",
    keywords: [key],
    width: 640,
    height: 640,
    background: "#101418",
    base: null,
    overlay: null,
    tags: [],
    author: "",
    slots: [
      { type: "image", x: 0, y: 0, width: 640, height: 640, fit: "cover" },
    ],
  };
}

function resetMakerAssets() {
  const maker = state.maker;
  maker.baseUpload = null;
  maker.overlayUpload = null;
  maker.baseUrl = null;
  maker.overlayUrl = null;
  maker.removeBase = false;
  maker.removeOverlay = false;
}

function setDraft(draft, savedKey) {
  state.maker.draft = draft;
  state.maker.savedKey = savedKey || null;
  state.maker.activeSlot = draft && draft.slots && draft.slots.length ? 0 : -1;
  state.maker.dirty = !savedKey;
  renderMaker();
}

function markDirty() {
  state.maker.dirty = true;
  updateStatusLine();
}

function renderMakerList() {
  const list = clear($("maker-list"));
  $("maker-count").textContent = String(state.maker.templates.length);
  $("tab-badge-maker").textContent = String(state.maker.templates.length);
  if (!state.maker.templates.length) {
    list.appendChild(el("li", "empty is-inline", "还没有自制模板"));
    return;
  }
  for (const item of state.maker.templates) {
    const li = el("li");
    const button = el("button", "side-item");
    button.type = "button";
    if (state.maker.savedKey === item.key) button.classList.add("is-active");
    const copy = el("span");
    copy.appendChild(el("b", null, item.title || item.key));
    copy.appendChild(el("small", "mono", item.key + " · 图 " + item.image_slots + " / 字 " + item.text_slots));
    button.appendChild(copy);
    button.appendChild(el("span", "side-flag", item.loaded ? "已加载" : "未加载"));
    button.addEventListener("click", async () => {
      if (state.maker.dirty && !(await askConfirm("当前草稿尚未保存，确定切换模板？", { confirmText: "切换" }))) return;
      openTemplate(item.key).catch((error) => reportError(error, "读取模板"));
    });
    li.appendChild(button);
    list.appendChild(li);
  }
}

function canvasScale(draft) {
  const wrap = $("canvas-wrap");
  const available = Math.max(200, wrap.clientWidth - 40);
  return Math.min(1, available / draft.width);
}

function slotLabel(draft, index) {
  const slot = draft.slots[index];
  let counter = 0;
  for (let cursor = 0; cursor <= index; cursor += 1) {
    if (draft.slots[cursor].type === slot.type) counter += 1;
  }
  return (slot.type === "image" ? "图片 " : "文字 ") + counter;
}

let stageBaseNode = null;
let stageOverlayNode = null;

/* The stage is rebuilt with clear(), which detaches the two <img> layers.
   Detached nodes are invisible to getElementById, so keep live references. */
function stageLayers() {
  if (!stageBaseNode) stageBaseNode = $("canvas-base");
  if (!stageOverlayNode) stageOverlayNode = $("canvas-overlay");
  return [stageBaseNode, stageOverlayNode];
}

function renderStage() {
  const draft = state.maker.draft;
  const canvas = $("maker-canvas");
  const title = $("stage-title");
  if (!draft) {
    title.textContent = "未选择模板";
    canvas.style.width = "320px";
    canvas.style.height = "200px";
    canvas.style.background = "var(--surface-3)";
    const [emptyBase, emptyOverlay] = stageLayers();
    clear(canvas);
    canvas.appendChild(emptyBase);
    canvas.appendChild(emptyOverlay);
    emptyBase.hidden = true;
    emptyOverlay.hidden = true;
    $("stage-zoom").textContent = "--";
    return;
  }

  title.textContent = (draft.title || draft.key) + " · " + draft.width + "×" + draft.height;
  const scale = canvasScale(draft);
  state.maker.scale = scale;
  $("stage-zoom").textContent = Math.round(scale * 100) + "%";
  canvas.style.width = Math.round(draft.width * scale) + "px";
  canvas.style.height = Math.round(draft.height * scale) + "px";
  canvas.style.background = draft.background || "#000";
  canvas.classList.toggle("is-grid", state.maker.grid);

  const [baseImage, overlayImage] = stageLayers();
  clear(canvas);
  canvas.appendChild(baseImage);
  canvas.appendChild(overlayImage);
  const baseSrc = state.maker.baseUpload || (state.maker.removeBase ? null : state.maker.baseUrl);
  const overlaySrc = state.maker.overlayUpload || (state.maker.removeOverlay ? null : state.maker.overlayUrl);
  baseImage.hidden = !baseSrc;
  if (baseSrc) baseImage.src = baseSrc;
  overlayImage.hidden = !overlaySrc;
  if (overlaySrc) overlayImage.src = overlaySrc;

  draft.slots.forEach((slot, index) => {
    const node = el("div", "slot");
    node.style.setProperty("--slot-color", SLOT_COLOR[slot.type] || "#38bdf8");
    node.style.left = (slot.x / draft.width) * 100 + "%";
    node.style.top = (slot.y / draft.height) * 100 + "%";
    node.style.width = (slot.width / draft.width) * 100 + "%";
    node.style.height = (slot.height / draft.height) * 100 + "%";
    if (index === state.maker.activeSlot) node.classList.add("is-active");
    node.appendChild(el("span", "slot-tag", slotLabel(draft, index)));
    const face = el("div", "slot-face", slot.type === "text" ? (slot.default || "文字") : FIT_LABEL[slot.fit] || slot.fit);
    node.appendChild(face);
    const handle = el("span", "slot-handle");
    handle.addEventListener("pointerdown", (event) => beginDrag(event, index, "resize"));
    node.appendChild(handle);
    node.addEventListener("pointerdown", (event) => beginDrag(event, index, "move"));
    canvas.appendChild(node);
  });
}

function beginDrag(event, index, mode) {
  if (event.button !== 0) return;
  event.preventDefault();
  event.stopPropagation();
  const draft = state.maker.draft;
  if (!draft) return;
  setActiveSlot(index);
  const slot = draft.slots[index];
  const scale = state.maker.scale || 1;
  const origin = { x: event.clientX, y: event.clientY, sx: slot.x, sy: slot.y, sw: slot.width, sh: slot.height };
  const stepX = Math.max(1, Math.round(draft.width * 0.08));
  const stepY = Math.max(1, Math.round(draft.height * 0.08));
  const node = event.currentTarget.closest(".slot") || event.currentTarget;
  node.classList.add("is-drag");

  const move = (moveEvent) => {
    const dx = (moveEvent.clientX - origin.x) / scale;
    const dy = (moveEvent.clientY - origin.y) / scale;
    if (mode === "move") {
      let nx = Math.round(origin.sx + dx);
      let ny = Math.round(origin.sy + dy);
      if (state.maker.grid && !moveEvent.altKey) {
        nx = Math.round(nx / stepX) * stepX;
        ny = Math.round(ny / stepY) * stepY;
      }
      slot.x = clamp(nx, -draft.width, draft.width, 0);
      slot.y = clamp(ny, -draft.height, draft.height, 0);
    } else {
      let nw = Math.round(origin.sw + dx);
      let nh = Math.round(origin.sh + dy);
      if (state.maker.grid && !moveEvent.altKey) {
        nw = Math.round(nw / stepX) * stepX;
        nh = Math.round(nh / stepY) * stepY;
      }
      slot.width = clamp(nw, 16, 2048, 16);
      slot.height = clamp(nh, 16, 2048, 16);
    }
    renderStage();
    renderSlotForm();
  };
  const finish = () => {
    window.removeEventListener("pointermove", move);
    markDirty();
    renderStage();
  };
  window.addEventListener("pointermove", move);
  window.addEventListener("pointerup", finish, { once: true });
  window.addEventListener("pointercancel", finish, { once: true });
}

function setActiveSlot(index) {
  state.maker.activeSlot = index;
  renderStage();
  renderLayers();
  renderSlotForm();
}

function renderLayers() {
  const list = clear($("mk-layers"));
  const draft = state.maker.draft;
  if (!draft || !draft.slots.length) {
    list.appendChild(el("li", "empty is-inline", "还没有图层"));
    return;
  }
  draft.slots.forEach((slot, index) => {
    const li = el("li");
    const item = el("button", "layer-item");
    item.type = "button";
    item.style.setProperty("--slot-color", SLOT_COLOR[slot.type] || "#38bdf8");
    if (index === state.maker.activeSlot) item.classList.add("is-active");
    item.appendChild(el("i", "layer-dot"));
    item.appendChild(el("span", "layer-name", slotLabel(draft, index) + (slot.type === "text" && slot.default ? "：" + slot.default : "")));
    const kill = el("span", "layer-kill");
    kill.appendChild(icon("i-trash"));
    kill.addEventListener("click", (event) => {
      event.stopPropagation();
      removeSlot(index);
    });
    item.appendChild(kill);
    item.addEventListener("click", () => setActiveSlot(index));
    li.appendChild(item);
    list.appendChild(li);
  });
}

function removeSlot(index) {
  const draft = state.maker.draft;
  if (!draft) return;
  draft.slots.splice(index, 1);
  state.maker.activeSlot = Math.min(index, draft.slots.length - 1);
  markDirty();
  renderStage();
  renderLayers();
  renderSlotForm();
}

function addSlot(type) {
  const draft = state.maker.draft;
  if (!draft) {
    toast("先新建或选择一个模板", "error");
    return;
  }
  const limits = state.maker.limits || {};
  const counted = draft.slots.filter((slot) => slot.type === type).length;
  const cap = type === "image" ? limits.image_slots || 4 : limits.text_slots || 8;
  if (counted >= cap) {
    toast((type === "image" ? "图片" : "文字") + "图层最多 " + cap + " 个", "error");
    return;
  }
  if (draft.slots.length >= (limits.slots || 16)) {
    toast("图层总数已达上限", "error");
    return;
  }
  if (type === "image") {
    draft.slots.push({
      type: "image",
      x: Math.round(draft.width * 0.12),
      y: Math.round(draft.height * 0.12),
      width: Math.round(draft.width * 0.5),
      height: Math.round(draft.height * 0.5),
      fit: "cover",
      radius: 0,
      circle: false,
      rotate: 0,
      opacity: 1,
      flip: false,
      grayscale: false,
      behind_base: false,
    });
  } else {
    draft.slots.push({
      type: "text",
      x: Math.round(draft.width * 0.06),
      y: Math.round(draft.height * 0.72),
      width: Math.round(draft.width * 0.88),
      height: Math.round(draft.height * 0.2),
      default: "",
      color: "#ffffff",
      stroke_color: "#000000",
      stroke_width: Math.max(2, Math.round(draft.width / 220)),
      font_size: 0,
      min_font_size: 14,
      bold: true,
      align: "center",
      valign: "middle",
      rotate: 0,
      line_spacing: 1.18,
      max_lines: 3,
      uppercase: false,
    });
  }
  state.maker.activeSlot = draft.slots.length - 1;
  markDirty();
  renderStage();
  renderLayers();
  renderSlotForm();
}


function ctlNumber(value, min, max, step, onInput) {
  const input = el("input", "mono");
  input.type = "number";
  input.min = String(min);
  input.max = String(max);
  input.step = String(step || 1);
  input.value = String(value);
  input.addEventListener("input", () => onInput(clamp(input.value, min, max, min)));
  return input;
}

function ctlText(value, placeholder, onInput) {
  const input = el("input");
  input.type = "text";
  if (placeholder) input.placeholder = placeholder;
  input.value = value || "";
  input.addEventListener("input", () => onInput(input.value));
  return input;
}

function ctlSelect(options, value, onInput, labels) {
  const select = el("select");
  for (const option of options) {
    const node = el("option", null, (labels && labels[option]) || option);
    node.value = option;
    select.appendChild(node);
  }
  select.value = value;
  select.addEventListener("change", () => onInput(select.value));
  return select;
}

function ctlColor(value, onInput) {
  const wrap = el("span", "color-input");
  const picker = el("input");
  picker.type = "color";
  picker.value = /^#[0-9a-fA-F]{6}$/.test(value || "") ? value : "#000000";
  const text = el("input", "mono");
  text.type = "text";
  text.spellcheck = false;
  text.value = value || "";
  picker.addEventListener("input", () => {
    text.value = picker.value;
    onInput(picker.value);
  });
  text.addEventListener("input", () => {
    if (/^#[0-9a-fA-F]{6}$/.test(text.value)) picker.value = text.value;
    onInput(text.value);
  });
  wrap.appendChild(picker);
  wrap.appendChild(text);
  return wrap;
}

function makerRow(label, control, wide) {
  const wrap = el("label", "form-row" + (wide ? " is-wide" : ""));
  wrap.appendChild(el("span", null, label));
  wrap.appendChild(control);
  return wrap;
}

function makerPair(label, first, second, separator) {
  const wrap = el("div", "form-row");
  wrap.appendChild(el("span", null, label));
  const split = el("div", "split");
  split.appendChild(first);
  split.appendChild(el("em", null, separator || "×"));
  split.appendChild(second);
  wrap.appendChild(split);
  return wrap;
}

function makerCheck(label, value, onInput) {
  const wrap = el("label", "check-row");
  const box = el("input");
  box.type = "checkbox";
  box.checked = Boolean(value);
  box.addEventListener("change", () => onInput(box.checked));
  wrap.appendChild(box);
  wrap.appendChild(el("span", null, label));
  return wrap;
}

function renderSlotForm() {
  const form = clear($("mk-slot-form"));
  const draft = state.maker.draft;
  const index = state.maker.activeSlot;
  if (!draft || index < 0 || !draft.slots[index]) return;
  const slot = draft.slots[index];
  const limits = state.maker.limits || {};
  const touch = () => {
    markDirty();
    renderStage();
  };
  const set = (prop) => (value) => {
    slot[prop] = value;
    touch();
  };

  form.appendChild(el("p", "eyebrow mono", (slot.type === "image" ? "IMAGE LAYER · " : "TEXT LAYER · ") + slotLabel(draft, index)));
  form.appendChild(makerPair("位置",
    ctlNumber(slot.x, -draft.width, draft.width, 1, set("x")),
    ctlNumber(slot.y, -draft.height, draft.height, 1, set("y")), ","));
  form.appendChild(makerPair("尺寸",
    ctlNumber(slot.width, 16, 2048, 1, set("width")),
    ctlNumber(slot.height, 16, 2048, 1, set("height"))));

  if (slot.type === "image") {
    form.appendChild(makerRow("填充", ctlSelect(limits.fit_modes || ["cover", "contain", "stretch"], slot.fit || "cover", set("fit"), FIT_LABEL)));
    form.appendChild(makerPair("圆角/旋转",
      ctlNumber(slot.radius || 0, 0, 512, 1, set("radius")),
      ctlNumber(slot.rotate || 0, -180, 180, 1, set("rotate")), "/"));
    form.appendChild(makerRow("透明度", ctlNumber(slot.opacity === undefined ? 1 : slot.opacity, 0.05, 1, 0.05, set("opacity"))));
    const flags = el("div", "form-row is-wide");
    flags.appendChild(makerCheck("圆形裁切", slot.circle, set("circle")));
    flags.appendChild(makerCheck("左右镜像", slot.flip, set("flip")));
    flags.appendChild(makerCheck("黑白", slot.grayscale, set("grayscale")));
    flags.appendChild(makerCheck("垫在底图下", slot.behind_base, set("behind_base")));
    form.appendChild(flags);
  } else {
    form.appendChild(makerRow("默认文字", ctlText(slot.default, "留空则必须由用户输入", set("default"))));
    form.appendChild(makerRow("文字色", ctlColor(slot.color || "#ffffff", set("color"))));
    form.appendChild(makerRow("描边色", ctlColor(slot.stroke_color || "#000000", set("stroke_color"))));
    form.appendChild(makerPair("描边/旋转",
      ctlNumber(slot.stroke_width || 0, 0, 16, 1, set("stroke_width")),
      ctlNumber(slot.rotate || 0, -180, 180, 1, set("rotate")), "/"));
    form.appendChild(makerPair("字号/最小",
      ctlNumber(slot.font_size || 0, 0, 400, 1, set("font_size")),
      ctlNumber(slot.min_font_size || 12, 8, 200, 1, set("min_font_size")), "/"));
    form.appendChild(makerRow("水平", ctlSelect(limits.alignments || ["left", "center", "right"], slot.align || "center", set("align"), ALIGN_LABEL)));
    form.appendChild(makerRow("垂直", ctlSelect(limits.vertical_alignments || ["top", "middle", "bottom"], slot.valign || "middle", set("valign"), VALIGN_LABEL)));
    form.appendChild(makerPair("行距/行数",
      ctlNumber(slot.line_spacing || 1.18, 0.8, 2.5, 0.02, set("line_spacing")),
      ctlNumber(slot.max_lines || 4, 1, 12, 1, set("max_lines")), "/"));
    const flags = el("div", "form-row is-wide");
    flags.appendChild(makerCheck("加粗", slot.bold, set("bold")));
    flags.appendChild(makerCheck("全部大写", slot.uppercase, set("uppercase")));
    form.appendChild(flags);
    form.appendChild(el("p", "opt-desc", "字号填 0 表示自动缩放到刚好放进框内。"));
  }
}

function paintAssetThumb(node, src, fallbackIcon) {
  clear(node);
  if (src) {
    const image = el("img");
    image.src = src;
    image.alt = "";
    node.appendChild(image);
    node.style.cursor = "zoom-in";
    node.onclick = () => openLightbox(src, "素材预览");
  } else {
    node.appendChild(icon(fallbackIcon));
    node.style.cursor = "default";
    node.onclick = null;
  }
}

function renderInspector() {
  const draft = state.maker.draft;
  const disabled = !draft;
  for (const id of ["mk-key", "mk-keywords", "mk-title", "mk-width", "mk-height", "mk-bg", "mk-bg-text"]) {
    $(id).disabled = disabled;
  }
  $("mk-save").disabled = disabled || state.maker.busy;
  $("mk-delete").disabled = !state.maker.savedKey || state.maker.busy;
  $("maker-preview").disabled = disabled || state.maker.busy;
  if (!draft) {
    $("mk-key").value = "";
    $("mk-keywords").value = "";
    $("mk-title").value = "";
    $("mk-width").value = "";
    $("mk-height").value = "";
    $("mk-bg-text").value = "";
    paintAssetThumb($("mk-base-thumb"), null, "i-image");
    paintAssetThumb($("mk-overlay-thumb"), null, "i-layers");
    return;
  }
  $("mk-key").value = draft.key || "";
  $("mk-keywords").value = (draft.keywords || []).join(" ");
  $("mk-title").value = draft.title || "";
  $("mk-width").value = String(draft.width);
  $("mk-height").value = String(draft.height);
  $("mk-bg-text").value = draft.background || "#000000";
  if (/^#[0-9a-fA-F]{6}$/.test(draft.background || "")) $("mk-bg").value = draft.background;
  const baseSrc = state.maker.baseUpload || (state.maker.removeBase ? null : state.maker.baseUrl);
  const overlaySrc = state.maker.overlayUpload || (state.maker.removeOverlay ? null : state.maker.overlayUrl);
  paintAssetThumb($("mk-base-thumb"), baseSrc, "i-image");
  paintAssetThumb($("mk-overlay-thumb"), overlaySrc, "i-layers");
}

function renderMaker() {
  const on = state.maker.enabled;
  $("maker-root").hidden = !on;
  $("maker-off").hidden = on;
  if (!on) {
    updateStatusLine();
    return;
  }
  renderMakerList();
  renderInspector();
  renderStage();
  renderLayers();
  renderSlotForm();
  $("stage-grid").classList.toggle("is-on", state.maker.grid);
  updateStatusLine();
}

async function loadMakerTemplates() {
  if (!state.maker.enabled) {
    state.maker.templates = [];
    renderMaker();
    return;
  }
  try {
    const payload = await apiGet("dashboard/maker/templates");
    state.maker.templates = payload.items || [];
    if (payload.limits) state.maker.limits = payload.limits;
    renderMaker();
  } catch (error) {
    state.maker.templates = [];
    renderMaker();
    reportError(error, "自制模板");
  }
}

async function openTemplate(key) {
  const payload = await apiGet("dashboard/maker/template", { key });
  const item = payload.item || {};
  if (payload.limits) state.maker.limits = payload.limits;
  resetMakerAssets();
  state.maker.baseUrl = item.base_data_url || null;
  state.maker.overlayUrl = item.overlay_data_url || null;
  setDraft({
    key: item.key,
    title: item.title || "",
    keywords: item.keywords || [],
    width: item.width,
    height: item.height,
    background: item.background || "#000000",
    base: item.base || null,
    overlay: item.overlay || null,
    tags: item.tags || [],
    author: item.author || "",
    slots: (item.slots || []).map((slot) => Object.assign({}, slot)),
  }, item.key);
}

function makerBody() {
  const draft = state.maker.draft;
  const body = { template: Object.assign({}, draft) };
  if (state.maker.baseUpload) body.base_image = state.maker.baseUpload;
  if (state.maker.overlayUpload) body.overlay_image = state.maker.overlayUpload;
  if (state.maker.removeBase) body.remove_base = true;
  if (state.maker.removeOverlay) body.remove_overlay = true;
  return body;
}

async function runMakerPreview() {
  const draft = state.maker.draft;
  if (!draft) return;
  state.maker.busy = true;
  renderInspector();
  const button = $("maker-preview");
  button.disabled = true;
  try {
    const payload = await apiPost("dashboard/maker/preview", makerBody());
    $("preview-image").src = payload.data_url;
    $("stage-preview").hidden = false;
    toast("预览已更新", "ok");
  } catch (error) {
    reportError(error, "预览失败");
  } finally {
    state.maker.busy = false;
    renderInspector();
  }
}

async function saveDraft() {
  const draft = state.maker.draft;
  if (!draft) return;
  state.maker.busy = true;
  renderInspector();
  try {
    const payload = await apiPost("dashboard/maker/save", makerBody());
    const item = payload.item || {};
    toast("已保存并加载「" + (item.title || item.key) + "」", "ok");
    resetMakerAssets();
    await loadMakerTemplates();
    await openTemplate(item.key);
    previewCache.clear();
    await loadOverview();
    if (state.tab === "library") await loadLibrary(false);
  } catch (error) {
    reportError(error, "保存失败");
  } finally {
    state.maker.busy = false;
    renderInspector();
  }
}

async function deleteDraft() {
  const key = state.maker.savedKey;
  if (!key) return;
  if (!(await askConfirm("确定删除模板「" + key + "」？该操作不可撤销。", { confirmText: "删除", danger: true }))) return;
  state.maker.busy = true;
  renderInspector();
  try {
    await apiPost("dashboard/maker/delete", { key });
    toast("已删除 " + key, "ok");
    resetMakerAssets();
    state.maker.draft = null;
    state.maker.savedKey = null;
    state.maker.dirty = false;
    await loadMakerTemplates();
    previewCache.clear();
    await loadOverview();
  } catch (error) {
    reportError(error, "删除失败");
  } finally {
    state.maker.busy = false;
    renderInspector();
  }
}

async function scaffoldDraft() {
  const key = uniqueKey("caption");
  try {
    const payload = await apiGet("dashboard/maker/scaffold", {
      key,
      keywords: key,
      width: 640,
      height: 640,
      title: "底部字幕",
      image_slot: "1",
    });
    resetMakerAssets();
    setDraft(payload.draft, null);
    toast("已生成字幕模板草稿，记得改成自己的触发词", "ok");
  } catch (error) {
    reportError(error, "生成草稿");
  }
}

async function pickAsset(input, which) {
  const file = input.files && input.files[0];
  input.value = "";
  if (!file) return;
  const limitMb = (state.maker.limits && state.maker.limits.asset_mb) || 8;
  if (file.size > limitMb * 1024 * 1024) {
    toast("单张素材不能超过 " + limitMb + "MB", "error");
    return;
  }
  try {
    const dataUrl = await readFileAsDataUrl(file);
    if (which === "base") {
      state.maker.baseUpload = dataUrl;
      state.maker.removeBase = false;
    } else {
      state.maker.overlayUpload = dataUrl;
      state.maker.removeOverlay = false;
    }
    markDirty();
    renderInspector();
    renderStage();
  } catch (error) {
    reportError(error, "读取图片");
  }
}

function clearAsset(which) {
  if (which === "base") {
    state.maker.baseUpload = null;
    state.maker.removeBase = true;
  } else {
    state.maker.overlayUpload = null;
    state.maker.removeOverlay = true;
  }
  markDirty();
  renderInspector();
  renderStage();
}


/* ---------- 记录 ---------- */

function recordRow(item) {
  const tr = el("tr");
  tr.appendChild(el("td", "mono", formatTime(item.created_at)));

  const keyCell = el("td");
  const keyLink = el("button", "keylink mono");
  keyLink.type = "button";
  keyLink.textContent = item.key;
  keyLink.title = "查看「" + item.key + "」详情";
  keyLink.addEventListener("click", () => {
    openMeme(item.key).catch((error) => reportError(error, "表情详情"));
  });
  keyCell.appendChild(keyLink);
  if (item.trigger && item.trigger !== item.key) {
    keyCell.appendChild(el("small", "cell-sub", "触发词 " + item.trigger));
  }
  tr.appendChild(keyCell);

  const sessionCell = el("td", "mono");
  sessionCell.textContent = shortSession(item.session);
  sessionCell.title = String(item.session || "");
  if (item.platform) sessionCell.appendChild(el("small", "cell-sub", item.platform));
  tr.appendChild(sessionCell);

  tr.appendChild(el("td", null, item.sender_name || item.sender_id || "匿名"));
  return tr;
}

function renderRecords() {
  const rec = state.records;
  const body = clear($("rec-body"));
  for (const item of rec.items) body.appendChild(recordRow(item));

  const hasItems = rec.items.length > 0;
  $("rec-empty").hidden = hasItems;
  $("rec-table").hidden = !hasItems;
  $("rec-meta").textContent = hasItems
    ? rec.items.length + " 条" + (rec.session ? " · 已按会话筛选" : " · 全部会话")
    : "暂无记录";

  const counts = new Map();
  for (const item of rec.items) counts.set(item.key, (counts.get(item.key) || 0) + 1);
  const ranking = Array.from(counts, ([key, count]) => ({ key, count }))
    .sort((a, b) => b.count - a.count || a.key.localeCompare(b.key))
    .slice(0, 8);
  renderBars($("rec-top"), ranking, "本页还没有记录");

  const picker = $("rec-session");
  fillSelect(picker, rec.conversations.map((item) => item.session), "全部会话", shortSession);
  picker.value = rec.session || "";
  renderSessionList($("rec-convs"), rec.conversations, (session) => {
    state.records.session = session === state.records.session ? "" : session;
    loadRecords().catch((error) => reportError(error, "记录"));
  });
}

async function loadRecords() {
  const rec = state.records;
  try {
    const payload = await apiGet("dashboard/history", { session: rec.session, limit: rec.limit });
    rec.items = payload.items || [];
    rec.conversations = payload.conversations || [];
    renderRecords();
  } catch (error) {
    reportError(error, "记录");
  }
}

/* ---------- 标签页 ---------- */

const tabLoaded = { overview: false, library: false, maker: false, records: false };

function moveInk() {
  const ink = $("tab-ink");
  const active = document.querySelector(".tab.is-active");
  if (!ink || !active) return;
  ink.style.width = active.offsetWidth + "px";
  ink.style.transform = "translateX(" + active.offsetLeft + "px)";
}

function ensureTabData(name) {
  if (tabLoaded[name]) return;
  tabLoaded[name] = true;
  let job = null;
  if (name === "library") job = loadLibrary(true);
  else if (name === "maker") job = loadMakerTemplates();
  else if (name === "records") job = loadRecords();
  if (job) {
    job.catch((error) => {
      tabLoaded[name] = false;
      reportError(error, "加载");
    });
  }
}

function switchTab(name) {
  const target = TABS.includes(name) ? name : "overview";
  const changed = state.tab !== target;
  state.tab = target;

  for (const button of document.querySelectorAll(".tab")) {
    const on = button.dataset.tab === target;
    button.classList.toggle("is-active", on);
    button.setAttribute("aria-selected", on ? "true" : "false");
  }
  for (const panel of document.querySelectorAll(".panel")) {
    const on = panel.id === "panel-" + target;
    panel.classList.toggle("is-active", on);
    panel.hidden = !on;
  }

  moveInk();
  if (window.location.hash.slice(1) !== target) {
    try {
      window.history.replaceState(null, "", "#" + target);
    } catch (error) {
      window.location.hash = target;
    }
  }
  if (changed) window.scrollTo(0, 0);
  ensureTabData(target);
  if (target === "maker") renderStage();
  updateStatusLine();
  updateSpy();
}

/* ---------- 主题与密度 ---------- */

function applyTheme(name) {
  const theme = THEMES.includes(name) ? name : THEMES[0];
  document.documentElement.dataset.theme = theme;
  document.body.dataset.theme = theme;
  $("theme-select").value = theme;
  const accent = window.getComputedStyle(document.documentElement).getPropertyValue("--accent").trim();
  if (accent) $("theme-swatch").style.background = accent;
  try {
    window.localStorage.setItem(THEME_KEY, theme);
  } catch (error) {
    /* 隐私模式下忽略 */
  }
  window.requestAnimationFrame(moveInk);
}

function applyDensity(mode) {
  const density = mode === "compact" ? "compact" : "cozy";
  document.documentElement.dataset.density = density;
  document.body.dataset.density = density;
  $("density-label").textContent = density === "compact" ? "紧凑" : "宽松";
  $("density-toggle").classList.toggle("is-on", density === "compact");
  try {
    window.localStorage.setItem(DENSITY_KEY, density);
  } catch (error) {
    /* 隐私模式下忽略 */
  }
  window.requestAnimationFrame(() => {
    moveInk();
    if (state.tab === "maker") renderStage();
  });
}

function readPref(key, fallback) {
  try {
    const value = window.localStorage.getItem(key);
    return value === null ? fallback : value;
  } catch (error) {
    return fallback;
  }
}

function writePref(key, value) {
  try {
    window.localStorage.setItem(key, value);
  } catch (error) {
    /* 忽略 */
  }
}

/* ---------- 滚动进度 ---------- */

const SPY_SEGMENTS = 14;

function buildSpy() {
  const spy = clear($("status-spy"));
  for (let index = 0; index < SPY_SEGMENTS; index += 1) spy.appendChild(el("i"));
}

function updateSpy() {
  const spy = $("status-spy");
  const cells = spy.children;
  if (!cells.length) return;
  const doc = document.documentElement;
  const scrollable = doc.scrollHeight - window.innerHeight;
  let lit = cells.length;
  if (scrollable > 8) {
    const ratio = Math.min(1, Math.max(0, window.scrollY / scrollable));
    lit = Math.max(1, Math.round(ratio * cells.length));
  }
  for (let index = 0; index < cells.length; index += 1) {
    cells[index].classList.toggle("is-on", index < lit);
  }
}

/* ---------- 事件绑定 ---------- */

function bindShell() {
  for (const button of document.querySelectorAll(".tab")) {
    button.addEventListener("click", () => switchTab(button.dataset.tab));
  }
  for (const button of document.querySelectorAll("[data-goto]")) {
    button.addEventListener("click", () => switchTab(button.dataset.goto));
  }
  $("theme-select").addEventListener("change", (event) => applyTheme(event.target.value));
  $("density-toggle").addEventListener("click", () => {
    applyDensity(document.documentElement.dataset.density === "compact" ? "cozy" : "compact");
  });
  $("refresh-all").addEventListener("click", async () => {
    const button = $("refresh-all");
    button.disabled = true;
    previewCache.clear();
    materialCache.clear();
    try {
      await loadOverview();
      if (tabLoaded.library) await loadLibrary(false);
      if (tabLoaded.maker) await loadMakerTemplates();
      if (tabLoaded.records) await loadRecords();
      toast("数据已刷新", "ok");
    } catch (error) {
      reportError(error, "刷新失败");
    } finally {
      button.disabled = false;
    }
  });

  window.addEventListener("hashchange", () => switchTab(window.location.hash.slice(1)));
  window.addEventListener("scroll", updateSpy, { passive: true });
  const onResize = debounce(() => {
    moveInk();
    updateSpy();
    if (state.tab === "maker") renderStage();
  }, 140);
  window.addEventListener("resize", onResize);
  window.addEventListener("beforeunload", (event) => {
    if (!state.maker.dirty) return undefined;
    event.preventDefault();
    event.returnValue = "";
    return "";
  });
}

function bindLibrary() {
  const lib = state.library;
  const search = $("lib-search");
  const runSearch = debounce(() => {
    lib.query = search.value.trim();
    loadLibrary(true);
  }, 220);
  search.addEventListener("input", runSearch);
  search.addEventListener("keydown", (event) => {
    if (event.key !== "Enter") return;
    event.preventDefault();
    lib.query = search.value.trim();
    loadLibrary(true);
  });
  $("lib-search-clear").addEventListener("click", () => {
    search.value = "";
    lib.query = "";
    loadLibrary(true);
    search.focus();
  });

  const selects = [["lib-source", "source"], ["lib-tag", "tag"], ["lib-status", "status"], ["lib-sort", "sort"]];
  for (const [id, field] of selects) {
    $(id).addEventListener("change", (event) => {
      lib[field] = event.target.value;
      loadLibrary(true);
    });
  }

  for (const button of document.querySelectorAll(".segmented [data-view]")) {
    button.addEventListener("click", () => {
      lib.view = button.dataset.view;
      writePref(VIEW_KEY, lib.view);
      for (const sibling of document.querySelectorAll(".segmented [data-view]")) {
        sibling.classList.toggle("is-active", sibling === button);
      }
      renderLibraryGrid();
    });
  }

  $("lib-thumbs").addEventListener("click", () => {
    lib.thumbs = !lib.thumbs;
    writePref(THUMB_KEY, lib.thumbs ? "1" : "0");
    $("lib-thumbs").classList.toggle("is-on", lib.thumbs);
    renderLibraryGrid();
  });

  $("lib-select").addEventListener("click", () => {
    lib.selecting = !lib.selecting;
    if (!lib.selecting) lib.picked.clear();
    $("lib-select").classList.toggle("is-on", lib.selecting);
    renderLibraryGrid();
    renderBulkbar();
  });

  $("lib-prev").addEventListener("click", () => {
    lib.offset = Math.max(0, lib.offset - PAGE_SIZE);
    loadLibrary(false);
  });
  $("lib-next").addEventListener("click", () => {
    if (lib.offset + PAGE_SIZE >= lib.total) return;
    lib.offset += PAGE_SIZE;
    loadLibrary(false);
  });

  const reset = $("lib-reset");
  if (reset) {
    reset.addEventListener("click", () => {
      lib.query = "";
      lib.tag = "";
      lib.status = "";
      lib.source = "";
      lib.sort = "key";
      search.value = "";
      $("lib-tag").value = "";
      $("lib-status").value = "";
      $("lib-source").value = "";
      $("lib-sort").value = "key";
      loadLibrary(true);
    });
  }

  $("bulk-page").addEventListener("click", () => {
    for (const item of lib.items) {
      if (lib.picked.size >= BULK_LIMIT) break;
      lib.picked.add(item.key);
    }
    renderLibraryGrid();
    renderBulkbar();
  });
  $("bulk-clear").addEventListener("click", () => {
    lib.picked.clear();
    renderLibraryGrid();
    renderBulkbar();
  });
  for (const [id, enabled] of [["bulk-enable", true], ["bulk-disable", false]]) {
    $(id).addEventListener("click", async () => {
      const keys = Array.from(lib.picked);
      if (!keys.length) return;
      const button = $(id);
      button.disabled = true;
      try {
        const payload = await apiPost("dashboard/memes-enabled", { keys, enabled });
        const done = (payload.items || []).length;
        const missing = (payload.missing || []).length;
        toast((enabled ? "已启用 " : "已禁用 ") + done + " 个表情" + (missing ? "，" + missing + " 个未找到" : ""), "ok");
        lib.picked.clear();
        await loadLibrary(false);
        await loadOverview();
      } catch (error) {
        reportError(error, "批量操作失败");
      } finally {
        renderBulkbar();
        button.disabled = false;
      }
    });
  }
}

let confirmResolve = null;

/* Plugin pages run inside the dashboard iframe, where native modals can be
   suppressed. Use an in-page dialog so destructive prompts always appear. */
function closeConfirm(result) {
  if (!confirmResolve) return;
  const resolve = confirmResolve;
  confirmResolve = null;
  const node = $("confirm");
  if (node) node.hidden = true;
  resolve(result);
}

function askConfirm(message, options) {
  const opts = options || {};
  const node = $("confirm");
  if (!node) return Promise.resolve(true);
  closeConfirm(false);
  $("confirm-title").textContent = opts.title || "请确认";
  $("confirm-text").textContent = message;
  const ok = $("confirm-ok");
  ok.querySelector("span").textContent = opts.confirmText || "确定";
  ok.classList.toggle("is-danger", Boolean(opts.danger));
  ok.classList.toggle("is-accent", !opts.danger);
  node.hidden = false;
  try { ok.focus(); } catch { /* focus is best-effort */ }
  return new Promise((resolve) => { confirmResolve = resolve; });
}

function bindOverlays() {
  $("drawer-close").addEventListener("click", closeDrawer);
  $("drawer-backdrop").addEventListener("click", closeDrawer);
  $("lightbox-close").addEventListener("click", closeLightbox);
  $("lightbox").addEventListener("click", (event) => {
    if (event.target === $("lightbox")) closeLightbox();
  });
  document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape") return;
    if (!$("lightbox").hidden) {
      closeLightbox();
      return;
    }
    if (!$("confirm").hidden) {
      closeConfirm(false);
      return;
    }
    if (!$("drawer").hidden) closeDrawer();
  });
  $("confirm-ok").addEventListener("click", () => closeConfirm(true));
  $("confirm-cancel").addEventListener("click", () => closeConfirm(false));
  $("confirm-cancel-bg").addEventListener("click", () => closeConfirm(false));
}

function bindMaker() {
  const maker = state.maker;

  $("maker-new").addEventListener("click", async () => {
    if (maker.dirty && !(await askConfirm("当前草稿尚未保存，确定新建空白模板？", { confirmText: "新建" }))) return;
    resetMakerAssets();
    setDraft(blankDraft(), null);
  });
  $("maker-scaffold").addEventListener("click", async () => {
    if (maker.dirty && !(await askConfirm("当前草稿尚未保存，确定生成字幕模板草稿？", { confirmText: "生成" }))) return;
    scaffoldDraft();
  });
  $("maker-reload").addEventListener("click", () => {
    loadMakerTemplates().catch((error) => reportError(error, "自制模板"));
  });
  $("maker-preview").addEventListener("click", () => runMakerPreview());
  $("preview-close").addEventListener("click", () => {
    $("stage-preview").hidden = true;
  });
  $("stage-grid").addEventListener("click", () => {
    maker.grid = !maker.grid;
    $("stage-grid").classList.toggle("is-on", maker.grid);
    renderStage();
  });

  const textFields = [["mk-key", (draft, value) => { draft.key = value.trim(); }],
    ["mk-title", (draft, value) => { draft.title = value; }],
    ["mk-keywords", (draft, value) => { draft.keywords = value.split(/[\s,，、]+/).filter(Boolean); }]];
  for (const [id, setter] of textFields) {
    $(id).addEventListener("input", (event) => {
      if (!maker.draft) return;
      setter(maker.draft, event.target.value);
      markDirty();
      renderStage();
    });
  }

  for (const [id, field] of [["mk-width", "width"], ["mk-height", "height"]]) {
    $(id).addEventListener("change", (event) => {
      if (!maker.draft) return;
      const canvas = (maker.limits && maker.limits.canvas) || { min: 64, max: 2048 };
      const next = Math.round(clamp(event.target.value, canvas.min, canvas.max, maker.draft[field]));
      maker.draft[field] = next;
      event.target.value = String(next);
      markDirty();
      renderStage();
      renderSlotForm();
    });
  }

  $("mk-bg").addEventListener("input", (event) => {
    if (!maker.draft) return;
    maker.draft.background = event.target.value;
    $("mk-bg-text").value = event.target.value;
    markDirty();
    renderStage();
  });
  $("mk-bg-text").addEventListener("change", (event) => {
    if (!maker.draft) return;
    const value = event.target.value.trim();
    if (!/^#[0-9a-fA-F]{6}$/.test(value)) {
      toast("背景色请填写 #RRGGBB 格式", "error");
      event.target.value = maker.draft.background || "#000000";
      return;
    }
    maker.draft.background = value;
    $("mk-bg").value = value;
    markDirty();
    renderStage();
  });

  $("mk-base-file").addEventListener("change", (event) => pickAsset(event.target, "base"));
  $("mk-overlay-file").addEventListener("change", (event) => pickAsset(event.target, "overlay"));
  $("mk-base-clear").addEventListener("click", () => clearAsset("base"));
  $("mk-overlay-clear").addEventListener("click", () => clearAsset("overlay"));

  $("mk-add-image").addEventListener("click", () => addSlot("image"));
  $("mk-add-text").addEventListener("click", () => addSlot("text"));
  $("mk-save").addEventListener("click", () => saveDraft());
  $("mk-delete").addEventListener("click", () => deleteDraft());

  $("maker-canvas").addEventListener("keydown", (event) => {
    const draft = maker.draft;
    const index = maker.activeSlot;
    if (!draft || index < 0 || !draft.slots[index]) return;
    const slot = draft.slots[index];
    if (event.key === "Delete" || event.key === "Backspace") {
      event.preventDefault();
      removeSlot(index);
      return;
    }
    const step = event.shiftKey ? 10 : 1;
    const moves = { ArrowLeft: [-step, 0], ArrowRight: [step, 0], ArrowUp: [0, -step], ArrowDown: [0, step] };
    const delta = moves[event.key];
    if (!delta) return;
    event.preventDefault();
    slot.x = Math.round(clamp(slot.x + delta[0], 0, draft.width - slot.width, slot.x));
    slot.y = Math.round(clamp(slot.y + delta[1], 0, draft.height - slot.height, slot.y));
    markDirty();
    renderStage();
    renderSlotForm();
  });
}

/* ---------- 启动 ---------- */

async function boot() {
  applyTheme(readPref(THEME_KEY, "aurora"));
  applyDensity(readPref(DENSITY_KEY, "cozy"));
  buildSpy();

  const lib = state.library;
  lib.view = readPref(VIEW_KEY, "grid") === "list" ? "list" : "grid";
  lib.thumbs = readPref(THUMB_KEY, "0") === "1";
  for (const button of document.querySelectorAll(".segmented [data-view]")) {
    button.classList.toggle("is-active", button.dataset.view === lib.view);
  }
  $("lib-thumbs").classList.toggle("is-on", lib.thumbs);
  $("lib-grid").dataset.view = lib.view;

  const limitSelect = $("rec-limit");
  state.records.limit = clamp(limitSelect.value, 1, 500, HISTORY_LIMIT);
  limitSelect.addEventListener("change", (event) => {
    state.records.limit = clamp(event.target.value, 1, 500, HISTORY_LIMIT);
    loadRecords().catch((error) => reportError(error, "记录"));
  });
  $("rec-session").addEventListener("change", (event) => {
    state.records.session = event.target.value;
    loadRecords().catch((error) => reportError(error, "记录"));
  });
  $("rec-refresh").addEventListener("click", () => {
    loadRecords().catch((error) => reportError(error, "记录"));
  });

  bindShell();
  bindLibrary();
  bindOverlays();
  bindMaker();
  renderBulkbar();

  if (!bridge || typeof bridge.ready !== "function") {
    throw new Error("未检测到 AstrBot 页面桥接，请在 AstrBot WebUI 中打开本页面。");
  }
  await bridge.ready();
  await loadOverview();
  switchTab(window.location.hash.slice(1) || "overview");
  updateSpy();
}

boot().catch((error) => {
  reportError(error, "初始化失败");
  const status = $("status-left");
  if (status) status.textContent = "初始化失败：" + ((error && error.message) || error);
});
