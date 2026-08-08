const bridge = window.AstrBotPluginPage;
const PAGE_SIZE = 40;

const VIEW_INFO = {
  overview: {
    kicker: "CONTROL / OVERVIEW",
    title: "概览",
    description: "表情库状态与近期使用情况。",
  },
  library: {
    kicker: "LIBRARY / MANAGE",
    title: "表情库",
    description: "浏览、筛选和管理当前已加载的 meme。",
  },
  history: {
    kicker: "ACTIVITY / HISTORY",
    title: "最近记录",
    description: "按会话查看最近成功生成的 meme。",
  },
};

const state = {
  activeView: "overview",
  catalog: { items: [], total: 0, tags: [] },
  detail: null,
  overview: null,
  history: { items: [], conversations: [] },
  offset: 0,
  selectedKey: "",
  catalogRequest: 0,
  detailRequest: 0,
  historyRequest: 0,
};

const elements = {
  activeConversations: document.getElementById("active-conversations"),
  catalogCount: document.getElementById("catalog-count"),
  catalogMessage: document.getElementById("catalog-message"),
  detailPane: document.getElementById("detail-pane"),
  extensionState: document.getElementById("extension-state"),
  historyList: document.getElementById("history-list"),
  historyMessage: document.getElementById("history-message"),
  historySessionFilter: document.getElementById("history-session-filter"),
  memeList: document.getElementById("meme-list"),
  metricDisabled: document.getElementById("metric-disabled"),
  metricEnabled: document.getElementById("metric-enabled"),
  metricHistory: document.getElementById("metric-history"),
  metricTotal: document.getElementById("metric-total"),
  navItems: [...document.querySelectorAll("[data-view-target]")],
  nextPage: document.getElementById("next-page"),
  openHistoryButton: document.getElementById("open-history-button"),
  pageStatus: document.getElementById("page-status"),
  previousPage: document.getElementById("previous-page"),
  recentActivity: document.getElementById("recent-activity"),
  refreshButton: document.getElementById("refresh-button"),
  searchInput: document.getElementById("search-input"),
  statusFilter: document.getElementById("status-filter"),
  tagFilter: document.getElementById("tag-filter"),
  themeDark: document.getElementById("theme-dark"),
  themeLight: document.getElementById("theme-light"),
  toast: document.getElementById("toast"),
  topMemes: document.getElementById("top-memes"),
  viewDescription: document.getElementById("view-description"),
  viewKicker: document.getElementById("view-kicker"),
  viewPanels: [...document.querySelectorAll("[data-view-panel]")],
  viewTitle: document.getElementById("view-title"),
};

function createElement(tagName, className = "", text = undefined) {
  const element = document.createElement(tagName);
  if (className) {
    element.className = className;
  }
  if (text !== undefined) {
    element.textContent = text;
  }
  return element;
}

function setMessage(element, text = "", isError = false) {
  element.textContent = text;
  element.classList.toggle("is-error", Boolean(text) && isError);
}

function showToast(text, isError = false) {
  const { toast } = elements;
  window.clearTimeout(showToast.timeout);
  toast.textContent = text;
  toast.classList.toggle("is-error", isError);
  toast.hidden = false;
  showToast.timeout = window.setTimeout(() => {
    toast.hidden = true;
  }, 3600);
}

function responseData(payload) {
  if (!payload || payload.ok !== true) {
    throw new Error(payload?.error || "请求未返回可用数据。");
  }
  return payload;
}

async function apiGet(endpoint, params = {}) {
  if (!bridge) {
    throw new Error("AstrBot 页面桥接未加载。");
  }
  return responseData(await bridge.apiGet(endpoint, params));
}

async function apiPost(endpoint, body) {
  if (!bridge) {
    throw new Error("AstrBot 页面桥接未加载。");
  }
  return responseData(await bridge.apiPost(endpoint, body));
}

function formatBytes(bytes) {
  const amount = Number(bytes) || 0;
  if (amount < 1024) {
    return `${amount} B`;
  }
  if (amount < 1024 * 1024) {
    return `${(amount / 1024).toFixed(1)} KB`;
  }
  return `${(amount / 1024 / 1024).toFixed(1)} MB`;
}

function formatDate(value) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value || "--";
  }
  return new Intl.DateTimeFormat("zh-CN", {
    dateStyle: "short",
    timeStyle: "short",
  }).format(date);
}

function textList(values, fallback = "--") {
  const result = Array.isArray(values)
    ? values.map((value) => String(value).trim()).filter(Boolean)
    : [];
  return result.length ? result.join("、") : fallback;
}

function keyGlyph(key) {
  const normalized = String(key || "MF").replace(/[^\p{L}\p{N}]/gu, "");
  return (normalized.slice(0, 2) || "MF").toUpperCase();
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

function commandPrefix() {
  const prefix = String(state.overview?.trigger_prefix ?? "meme").trim();
  return prefix ? `/${prefix}${/[A-Za-z0-9]$/.test(prefix) ? " " : ""}` : "/";
}

function commandFor(detail) {
  const trigger = detail.keywords?.[0] || detail.key;
  const optionExamples = (detail.options || [])
    .slice(0, 2)
    .map((option) => {
      const flag = option.flags?.[0] || `--${option.name}`;
      return option.type === "bool" ? flag : `${flag} <${option.name}>`;
    });
  return `${commandPrefix()}${trigger}${optionExamples.length ? ` ${optionExamples.join(" ")}` : ""}`;
}

function normalizedView(value) {
  return Object.hasOwn(VIEW_INFO, value) ? value : "overview";
}

function viewFromHash() {
  return normalizedView(window.location.hash.replace(/^#/, ""));
}

function renderViewHeader() {
  const detail = VIEW_INFO[state.activeView];
  elements.viewKicker.textContent = detail.kicker;
  elements.viewTitle.textContent = detail.title;
  elements.viewDescription.textContent = detail.description;
  document.title = `Meme 工坊 · ${detail.title}`;
}

function setActiveView(view, { syncHash = true } = {}) {
  const nextView = normalizedView(view);
  state.activeView = nextView;
  for (const item of elements.navItems) {
    const selected = item.dataset.viewTarget === nextView;
    item.classList.toggle("is-active", selected);
    item.setAttribute("aria-current", selected ? "page" : "false");
  }
  for (const panel of elements.viewPanels) {
    panel.hidden = panel.dataset.viewPanel !== nextView;
  }
  renderViewHeader();
  if (syncHash && window.location.hash !== `#${nextView}`) {
    window.location.hash = nextView;
  }
}

function updateTagOptions(tags) {
  const previous = elements.tagFilter.value;
  const select = elements.tagFilter;
  select.replaceChildren();
  select.append(createOption("", "全部标签"));
  for (const tag of tags) {
    select.append(createOption(tag, tag));
  }
  select.value = tags.includes(previous) ? previous : "";
}

function createOption(value, label) {
  const option = document.createElement("option");
  option.value = value;
  option.textContent = label;
  return option;
}

function renderSummaryEmpty(container, text) {
  container.replaceChildren(createElement("p", "empty-summary", text));
}

function renderTopMemes(items) {
  const list = elements.topMemes;
  list.replaceChildren();
  if (!items.length) {
    renderSummaryEmpty(list, "暂无成功生成记录。");
    return;
  }
  for (const [index, item] of items.entries()) {
    const row = createElement("button", "summary-row");
    row.type = "button";
    row.title = `查看 ${item.key} 的详情`;
    const rank = createElement("span", "summary-rank", String(index + 1).padStart(2, "0"));
    const content = createElement("span", "summary-content");
    content.append(
      createElement("strong", "", item.key),
      createElement("small", "", item.last_trigger || "--"),
    );
    const metric = createElement("span", "summary-metric", `${item.count} 次`);
    row.append(rank, content, metric);
    row.addEventListener("click", () => void openMeme(item.key));
    list.append(row);
  }
}

function renderConversations(items) {
  const list = elements.activeConversations;
  list.replaceChildren();
  if (!items.length) {
    renderSummaryEmpty(list, "暂无会话活动。");
    return;
  }
  for (const item of items) {
    const row = createElement("button", "summary-row conversation-row");
    row.type = "button";
    row.title = "查看此会话的最近记录";
    const content = createElement("span", "summary-content");
    content.append(
      createElement("strong", "", item.last_sender_name || item.session || "--"),
      createElement("small", "", item.session || "--"),
    );
    const metric = createElement("span", "summary-metric", `${item.count} 次`);
    row.append(content, metric);
    row.addEventListener("click", () => void openConversation(item.session));
    list.append(row);
  }
}

function renderRecentActivity(items) {
  const list = elements.recentActivity;
  list.replaceChildren();
  if (!items.length) {
    renderSummaryEmpty(list, "暂无成功生成记录。");
    return;
  }
  for (const item of items) {
    const row = createElement("button", "activity-row");
    row.type = "button";
    row.title = "查看此会话的最近记录";
    const primary = createElement("span", "activity-primary");
    primary.append(
      createElement("strong", "", item.trigger || item.key || "--"),
      createElement("small", "", `${item.sender_name || item.sender_id || "--"} · ${item.key || "--"}`),
    );
    const secondary = createElement("span", "activity-secondary");
    secondary.append(
      createElement("time", "", formatDate(item.created_at)),
      createElement("small", "", item.session || "--"),
    );
    row.append(primary, secondary);
    row.addEventListener("click", () => void openConversation(item.session));
    list.append(row);
  }
}

function renderOverview() {
  const data = state.overview;
  if (!data) {
    renderTopMemes([]);
    renderConversations([]);
    renderRecentActivity([]);
    return;
  }
  elements.metricTotal.textContent = data.total_memes;
  elements.metricEnabled.textContent = data.enabled_memes;
  elements.metricDisabled.textContent = data.disabled_memes;
  elements.metricHistory.textContent = data.usage_records;

  const extension = data.extension || {};
  const status = extension.installed
    ? `meme_emoji 扩展已安装${extension.tag ? ` (${extension.tag})` : ""}`
    : "meme_emoji 扩展未安装";
  const ready = extension.installed && extension.library_valid && extension.resources_present;
  elements.extensionState.textContent = ready
    ? `${status}，运行资源可用`
    : extension.installed
      ? `${status}，请检查动态库与资源状态`
      : status;
  elements.extensionState.classList.toggle("is-ready", ready);
  elements.extensionState.classList.toggle("is-warning", !ready);

  renderTopMemes(data.top_memes || []);
  renderConversations(data.active_conversations || []);
  renderRecentActivity(data.recent_records || []);
}

function renderCatalog() {
  const { items, total } = state.catalog;
  const list = elements.memeList;
  list.replaceChildren();
  elements.catalogCount.textContent = `${total} 个`;

  if (!items.length) {
    list.append(createElement("p", "region-message", "没有符合筛选条件的表情包。"));
  }

  for (const item of items) {
    const row = createElement("article", "meme-row");
    row.classList.toggle("is-disabled", !item.enabled);
    row.classList.toggle("is-selected", item.key === state.selectedKey);
    row.tabIndex = 0;
    row.setAttribute("role", "button");
    row.setAttribute("aria-label", `查看 ${item.key} 的详情`);

    const glyph = createElement("div", "meme-glyph", keyGlyph(item.key));
    glyph.setAttribute("aria-hidden", "true");
    const main = createElement("div", "meme-main");
    main.append(
      createElement("span", "meme-name", item.key),
      createElement("span", "meme-keywords", textList(item.keywords, "无关键词")),
    );

    const controls = createElement("div", "meme-controls");
    controls.append(createElement("span", "state-label", item.enabled ? "已启用" : "已禁用"));
    const toggle = document.createElement("input");
    toggle.className = "switch-input";
    toggle.type = "checkbox";
    toggle.checked = Boolean(item.enabled);
    toggle.setAttribute("aria-label", `${item.key} ${item.enabled ? "已启用，点击禁用" : "已禁用，点击启用"}`);
    toggle.addEventListener("click", (event) => event.stopPropagation());
    toggle.addEventListener("change", async () => {
      await toggleMeme(item.key, toggle.checked, toggle);
    });
    controls.append(toggle);
    row.append(glyph, main, controls);
    row.addEventListener("click", () => void showDetail(item.key));
    row.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        void showDetail(item.key);
      }
    });
    list.append(row);
  }

  const page = Math.floor(state.offset / PAGE_SIZE) + 1;
  const pages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  elements.pageStatus.textContent = `${page} / ${pages}`;
  elements.previousPage.disabled = state.offset <= 0;
  elements.nextPage.disabled = state.offset + PAGE_SIZE >= total;
}

function makeDetailBadge(label, value, className = "") {
  const badge = createElement("span", `detail-badge ${className}`.trim());
  badge.append(createElement("strong", "", label));
  badge.append(document.createTextNode(value));
  return badge;
}

function makeDetailBlock(title) {
  const block = createElement("section", "detail-block");
  block.append(createElement("h3", "", title));
  return block;
}

function renderOption(option) {
  const row = createElement("div", "option-row");
  const head = createElement("div", "option-head");
  head.append(
    createElement("code", "option-name", option.name || "--"),
    createElement("span", "option-type", option.type || "unknown"),
  );
  row.append(head);
  if (option.description) {
    row.append(createElement("p", "option-description", option.description));
  }
  const values = createElement("p", "option-values");
  const descriptors = [];
  if (option.flags?.length) {
    descriptors.push(`参数 ${option.flags.join(" / ")}`);
  }
  if (option.aliases?.length) {
    descriptors.push(`别名 ${option.aliases.join(" / ")}`);
  }
  if (option.choices?.length) {
    descriptors.push(`可选 ${option.choices.join(" / ")}`);
  }
  if (option.minimum !== null && option.minimum !== undefined) {
    descriptors.push(`最小 ${option.minimum}`);
  }
  if (option.maximum !== null && option.maximum !== undefined) {
    descriptors.push(`最大 ${option.maximum}`);
  }
  descriptors.push(`默认 ${formatOptionDefault(option.default)}`);
  values.textContent = descriptors.join(" · ");
  row.append(values);
  return row;
}

function renderDetail(detail) {
  const root = createElement("div", "detail-content");
  const heading = createElement("div", "detail-title-row");
  const headingText = createElement("div");
  headingText.append(
    createElement("p", "eyebrow", "TEMPLATE DETAIL"),
    createElement("h2", "", detail.key),
  );
  const toggle = document.createElement("input");
  toggle.className = "switch-input";
  toggle.type = "checkbox";
  toggle.checked = Boolean(detail.enabled);
  toggle.setAttribute("aria-label", `${detail.key} ${detail.enabled ? "已启用，点击禁用" : "已禁用，点击启用"}`);
  toggle.addEventListener("change", async () => {
    await toggleMeme(detail.key, toggle.checked, toggle);
  });
  heading.append(headingText, toggle);
  root.append(heading);

  const meta = createElement("div", "detail-meta");
  meta.append(
    makeDetailBadge("图片", detail.images?.label || "0"),
    makeDetailBadge("文本", detail.texts?.label || "0"),
    makeDetailBadge("状态", detail.enabled ? "已启用" : "已禁用", detail.enabled ? "is-enabled" : "is-disabled"),
  );
  root.append(meta);

  const commandBlock = makeDetailBlock("调用与参数");
  commandBlock.append(createElement("pre", "command-preview", commandFor(detail)));
  root.append(commandBlock);

  const previewBlock = makeDetailBlock("预览");
  const previewFrame = createElement("div", "preview-frame");
  previewFrame.append(createElement("span", "", "等待生成预览"));
  const previewButton = createElement("button", "preview-button", "生成预览");
  previewButton.type = "button";
  previewButton.addEventListener("click", () => void loadPreview(detail.key, previewFrame, previewButton));
  previewBlock.append(previewFrame, previewButton);
  root.append(previewBlock);

  if (detail.default_texts?.length) {
    const defaultsBlock = makeDetailBlock("默认文本");
    defaultsBlock.append(createElement("p", "option-description", textList(detail.default_texts)));
    root.append(defaultsBlock);
  }

  const optionsBlock = makeDetailBlock("可传选项");
  const optionList = createElement("div", "option-list");
  if (detail.options?.length) {
    for (const option of detail.options) {
      optionList.append(renderOption(option));
    }
  } else {
    optionList.append(createElement("p", "option-description", "该表情没有额外可传选项。"));
  }
  optionsBlock.append(optionList);
  root.append(optionsBlock);

  if (detail.keywords?.length || detail.tags?.length) {
    const tagBlock = makeDetailBlock("关键词与标签");
    const tags = createElement("div", "tag-list");
    for (const keyword of detail.keywords || []) {
      tags.append(createElement("span", "tag", keyword));
    }
    for (const tag of detail.tags || []) {
      tags.append(createElement("span", "tag", `#${tag}`));
    }
    tagBlock.append(tags);
    root.append(tagBlock);
  }

  const materials = detail.materials || { total: 0, items: [] };
  const materialsBlock = makeDetailBlock("素材图片");
  const materialHead = createElement("div", "material-head");
  materialHead.append(
    createElement("span", "material-count", materials.total ? `${materials.total} 个素材${materials.truncated ? "，当前显示前 60 个" : ""}` : "没有本地素材"),
  );
  materialsBlock.append(materialHead);
  if (materials.items?.length) {
    const materialList = createElement("div", "material-list");
    for (const material of materials.items) {
      const button = createElement("button", "material-button");
      button.type = "button";
      button.title = material.name;
      button.append(
        createElement("strong", "", material.name),
        createElement("small", "", formatBytes(material.size)),
      );
      button.addEventListener("click", () => void loadMaterial(detail.key, material.name, previewFrame, button));
      materialList.append(button);
    }
    materialsBlock.append(materialList);
  }
  root.append(materialsBlock);

  elements.detailPane.replaceChildren(root);
}

function renderDetailLoading() {
  const container = createElement("div", "detail-empty");
  container.append(createElement("p", "eyebrow", "INSPECT"), createElement("p", "", "正在读取表情详情..."));
  elements.detailPane.replaceChildren(container);
}

function renderDetailError(message) {
  const container = createElement("div", "detail-empty");
  container.append(createElement("p", "eyebrow", "INSPECT"), createElement("p", "region-message is-error", message));
  elements.detailPane.replaceChildren(container);
}

function setPreviewFrame(frame, dataUrl, error = "") {
  frame.replaceChildren();
  frame.classList.toggle("is-error", Boolean(error));
  if (error) {
    frame.append(createElement("span", "", error));
    return;
  }
  const image = document.createElement("img");
  image.src = dataUrl;
  image.alt = "Meme 预览";
  frame.append(image);
}

async function loadPreview(key, frame, button) {
  button.disabled = true;
  button.textContent = "正在生成...";
  frame.classList.remove("is-error");
  frame.replaceChildren(createElement("span", "", "正在生成预览..."));
  try {
    const data = await apiGet("dashboard/preview", { key });
    setPreviewFrame(frame, data.data_url);
  } catch (error) {
    setPreviewFrame(frame, "", error.message || "预览生成失败。");
  } finally {
    button.disabled = false;
    button.textContent = "重新生成预览";
  }
}

async function loadMaterial(key, name, frame, button) {
  const group = button.parentElement;
  for (const child of group?.children || []) {
    child.classList?.remove("is-selected");
  }
  button.classList.add("is-selected");
  button.disabled = true;
  frame.classList.remove("is-error");
  frame.replaceChildren(createElement("span", "", "正在读取素材..."));
  try {
    const data = await apiGet("dashboard/material", { key, name });
    setPreviewFrame(frame, data.data_url);
  } catch (error) {
    setPreviewFrame(frame, "", error.message || "素材读取失败。");
  } finally {
    button.disabled = false;
  }
}

function updateHistorySessionOptions(conversations) {
  const previous = elements.historySessionFilter.value;
  elements.historySessionFilter.replaceChildren(createOption("", "全部会话"));
  for (const conversation of conversations) {
    const detail = `${conversation.session} · ${conversation.count} 次`;
    elements.historySessionFilter.append(createOption(conversation.session, detail));
  }
  elements.historySessionFilter.value = conversations.some((item) => item.session === previous)
    ? previous
    : "";
}

function renderHistory() {
  const list = elements.historyList;
  list.replaceChildren();
  if (!state.history.items.length) {
    const row = document.createElement("tr");
    const cell = createElement("td", "empty-cell", "暂无符合范围的成功生成记录。");
    cell.colSpan = 5;
    row.append(cell);
    list.append(row);
    return;
  }
  for (const record of state.history.items) {
    const row = document.createElement("tr");
    const values = [
      formatDate(record.created_at),
      record.sender_name || record.sender_id || "--",
      record.trigger || "--",
      record.key || "--",
      record.session || "--",
    ];
    for (const value of values) {
      row.append(createElement("td", "", value));
    }
    list.append(row);
  }
}

async function loadOverview() {
  const data = await apiGet("dashboard/overview");
  state.overview = data;
  renderOverview();
}

async function loadCatalog({ resetOffset = false } = {}) {
  if (resetOffset) {
    state.offset = 0;
  }
  const requestId = ++state.catalogRequest;
  setMessage(elements.catalogMessage, "正在读取表情库...");
  try {
    const data = await apiGet("dashboard/memes", {
      q: elements.searchInput.value.trim(),
      tag: elements.tagFilter.value,
      status: elements.statusFilter.value,
      offset: state.offset,
      limit: PAGE_SIZE,
    });
    if (requestId !== state.catalogRequest) {
      return;
    }
    state.catalog = data;
    if (state.offset >= data.total && data.total > 0) {
      state.offset = Math.max(0, Math.floor((data.total - 1) / PAGE_SIZE) * PAGE_SIZE);
      return loadCatalog();
    }
    updateTagOptions(data.tags || []);
    setMessage(elements.catalogMessage);
    renderCatalog();
  } catch (error) {
    if (requestId !== state.catalogRequest) {
      return;
    }
    state.catalog = { items: [], total: 0, tags: [] };
    renderCatalog();
    setMessage(elements.catalogMessage, error.message || "读取表情库失败。", true);
  }
}

async function showDetail(key) {
  state.selectedKey = key;
  state.detail = null;
  renderCatalog();
  renderDetailLoading();
  const requestId = ++state.detailRequest;
  try {
    const data = await apiGet("dashboard/meme", { key });
    if (requestId !== state.detailRequest || state.selectedKey !== key) {
      return;
    }
    state.detail = data.item;
    renderDetail(data.item);
  } catch (error) {
    if (requestId !== state.detailRequest || state.selectedKey !== key) {
      return;
    }
    renderDetailError(error.message || "读取详情失败。");
  }
}

async function openMeme(key) {
  setActiveView("library");
  elements.searchInput.value = key;
  elements.tagFilter.value = "";
  elements.statusFilter.value = "all";
  await loadCatalog({ resetOffset: true });
  await showDetail(key);
}

async function openConversation(session) {
  if (!session) {
    setActiveView("history");
    return;
  }
  setActiveView("history");
  elements.historySessionFilter.value = session;
  await loadHistory();
}

async function toggleMeme(key, enabled, toggle) {
  toggle.disabled = true;
  try {
    const data = await apiPost("dashboard/meme-enabled", { key, enabled });
    for (const item of state.catalog.items) {
      if (item.key === data.item.key) {
        Object.assign(item, data.item);
      }
    }
    if (state.detail?.key === data.item.key) {
      Object.assign(state.detail, data.item);
      renderDetail(state.detail);
    }
    renderCatalog();
    await loadOverview();
    showToast(`${data.item.key} 已${enabled ? "启用" : "禁用"}。`);
  } catch (error) {
    renderCatalog();
    if (state.detail) {
      renderDetail(state.detail);
    }
    showToast(error.message || "保存状态失败。", true);
  } finally {
    toggle.disabled = false;
  }
}

async function loadHistory() {
  const requestId = ++state.historyRequest;
  setMessage(elements.historyMessage, "正在读取最近生成记录...");
  try {
    const data = await apiGet("dashboard/history", {
      session: elements.historySessionFilter.value,
      limit: 30,
    });
    if (requestId !== state.historyRequest) {
      return;
    }
    state.history = data;
    updateHistorySessionOptions(data.conversations || []);
    setMessage(elements.historyMessage);
    renderHistory();
  } catch (error) {
    if (requestId !== state.historyRequest) {
      return;
    }
    state.history = { items: [], conversations: [] };
    renderHistory();
    setMessage(elements.historyMessage, error.message || "读取最近记录失败。", true);
  }
}

async function refreshAll() {
  elements.refreshButton.disabled = true;
  try {
    await Promise.all([loadOverview(), loadCatalog(), loadHistory()]);
    if (state.selectedKey) {
      await showDetail(state.selectedKey);
    }
  } catch (error) {
    showToast(error.message || "刷新失败。", true);
  } finally {
    elements.refreshButton.disabled = false;
  }
}

function applyTheme(theme) {
  const normalized = theme === "light" ? "light" : "dark";
  document.documentElement.dataset.theme = normalized;
  elements.themeLight.setAttribute("aria-pressed", String(normalized === "light"));
  elements.themeDark.setAttribute("aria-pressed", String(normalized === "dark"));
  try {
    window.localStorage.setItem("meme-forge-theme", normalized);
  } catch {
    // Private browsing or an embedded Dashboard can block local storage.
  }
}

function setupEvents() {
  let searchTimer = 0;
  elements.searchInput.addEventListener("input", () => {
    window.clearTimeout(searchTimer);
    searchTimer = window.setTimeout(() => void loadCatalog({ resetOffset: true }), 220);
  });
  elements.tagFilter.addEventListener("change", () => void loadCatalog({ resetOffset: true }));
  elements.statusFilter.addEventListener("change", () => void loadCatalog({ resetOffset: true }));
  elements.previousPage.addEventListener("click", () => {
    state.offset = Math.max(0, state.offset - PAGE_SIZE);
    void loadCatalog();
  });
  elements.nextPage.addEventListener("click", () => {
    state.offset += PAGE_SIZE;
    void loadCatalog();
  });
  elements.historySessionFilter.addEventListener("change", () => void loadHistory());
  elements.openHistoryButton.addEventListener("click", () => setActiveView("history"));
  elements.refreshButton.addEventListener("click", () => void refreshAll());
  elements.themeLight.addEventListener("click", () => applyTheme("light"));
  elements.themeDark.addEventListener("click", () => applyTheme("dark"));
  for (const item of elements.navItems) {
    item.addEventListener("click", () => setActiveView(item.dataset.viewTarget));
  }
  window.addEventListener("hashchange", () => setActiveView(viewFromHash(), { syncHash: false }));
}

async function boot() {
  setupEvents();
  try {
    const preferredTheme = window.localStorage.getItem("meme-forge-theme");
    applyTheme(preferredTheme || "dark");
  } catch {
    applyTheme("dark");
  }
  setActiveView(viewFromHash(), { syncHash: false });
  if (!bridge) {
    const message = "AstrBot 页面桥接未加载。";
    elements.extensionState.textContent = message;
    elements.extensionState.classList.add("is-warning");
    setMessage(elements.catalogMessage, message, true);
    setMessage(elements.historyMessage, message, true);
    renderOverview();
    return;
  }
  try {
    await bridge.ready();
    await refreshAll();
  } catch (error) {
    const message = error.message || "页面初始化失败。";
    elements.extensionState.textContent = message;
    elements.extensionState.classList.add("is-warning");
    setMessage(elements.catalogMessage, message, true);
    setMessage(elements.historyMessage, message, true);
  }
}

boot();
