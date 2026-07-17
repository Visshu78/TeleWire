/* =========================================================
   dashboard.js  --  TeleIntel Frontend
   Sections: dashboard | messages | timerange | groups | keywords | export | health
   ========================================================= */

"use strict";

// ── State ─────────────────────────────────────────────────────────────────────
let currentPage   = 1;

// ── Custom MultiSelect Component ──────────────────────────────────────────────
const multiselects = {};

class MultiSelect {
  constructor(containerId, placeholder, options = [], onChange = null) {
    this.container = document.getElementById(containerId);
    this.placeholder = placeholder;
    this.options = options; // array of { value, label }
    this.selected = [];     // array of selected values string
    this.onChange = onChange;
    
    this.init();
  }
  
  init() {
    this.container.innerHTML = `
      <button type="button" class="multiselect-btn" id="${this.container.id}-btn">${e(this.placeholder)}</button>
    `;
    
    // Create the dropdown content and move it to document.body
    // so it is NEVER clipped by a parent backdrop-filter stacking context
    this.content = document.createElement('div');
    this.content.className = 'multiselect-content';
    this.content.id = `${this.container.id}-content`;
    this.content.innerHTML = `
      <div class="multiselect-search-wrap">
        <span class="multiselect-search-icon">🔍</span>
        <input type="text" class="multiselect-search" placeholder="Search..." autocomplete="off" />
      </div>
      <div class="multiselect-actions">
        <a class="select-all-btn">Select All</a>
        <a class="clear-btn">Clear</a>
      </div>
      <div class="multiselect-options-list"></div>
      <div class="multiselect-no-results" style="display:none;">No results found</div>
    `;
    document.body.appendChild(this.content);
    this.optionsList = this.content.querySelector('.multiselect-options-list');
    this.searchInput = this.content.querySelector('.multiselect-search');
    this.noResults  = this.content.querySelector('.multiselect-no-results');

    // Live search filtering
    this.searchInput.addEventListener('input', () => this._filterOptions(this.searchInput.value));
    // Stop clicks inside search from closing the dropdown
    this.searchInput.addEventListener('click', ev => ev.stopPropagation());
    this.searchInput.addEventListener('keydown', ev => {
      if (ev.key === 'Escape') { this.content.classList.remove('show'); }
      ev.stopPropagation();
    });
    
    this.btn = this.container.querySelector('.multiselect-btn');
    
    // Toggle dropdown: compute position from button's screen rect
    this.btn.addEventListener('click', (ev) => {
      ev.stopPropagation();
      // Close all other dropdowns first
      document.querySelectorAll('.multiselect-content.show').forEach(el => {
        if (el !== this.content) el.classList.remove('show');
      });
      const isShown = this.content.classList.contains('show');
      if (isShown) {
        this.content.classList.remove('show');
      } else {
        this._positionDropdown();
        this.content.classList.add('show');
        // Reset search and focus it
        this.searchInput.value = '';
        this._filterOptions('');
        setTimeout(() => this.searchInput.focus(), 30);
      }
    });
    
    // Prevent dropdown from closing when clicking inside it
    this.content.addEventListener('click', (ev) => {
      ev.stopPropagation();
    });
    
    // Close dropdown on click outside
    document.addEventListener('click', () => {
      this.content.classList.remove('show');
    });
    
    // Reposition on scroll/resize
    window.addEventListener('scroll', () => {
      if (this.content.classList.contains('show')) this._positionDropdown();
    }, true);
    window.addEventListener('resize', () => {
      if (this.content.classList.contains('show')) this._positionDropdown();
    });
    
    // Select All / Clear
    this.content.querySelector('.select-all-btn').addEventListener('click', () => this.selectAll());
    this.content.querySelector('.clear-btn').addEventListener('click', () => this.clearAll());
    
    this.renderOptions();
  }
  
  _positionDropdown() {
    const rect = this.btn.getBoundingClientRect();
    const spaceBelow = window.innerHeight - rect.bottom;
    const dropdownHeight = Math.min(340, this.content.scrollHeight || 340);
    
    // Preferred: below the button. If not enough space: above it.
    if (spaceBelow >= dropdownHeight || spaceBelow >= 120) {
      this.content.style.top = `${rect.bottom + 4 + window.scrollY}px`;
    } else {
      this.content.style.top = `${rect.top - dropdownHeight - 4 + window.scrollY}px`;
    }
    this.content.style.left = `${rect.left + window.scrollX}px`;
    this.content.style.width = `${Math.max(rect.width, 180)}px`;
    this.content.style.position = 'absolute';
  }
  
  _filterOptions(query) {
    const q = query.trim().toLowerCase();
    let visibleCount = 0;
    this.optionsList.querySelectorAll('label.multiselect-option').forEach(label => {
      const text = (label.querySelector('span')?.textContent || '').toLowerCase();
      const matches = !q || text.includes(q);
      label.style.display = matches ? '' : 'none';
      if (matches) visibleCount++;
    });
    // Show "no results" message when nothing matches
    if (this.noResults) {
      this.noResults.style.display = visibleCount === 0 ? 'block' : 'none';
    }
  }
  
  updateOptions(newOptions) {
    this.options = newOptions;
    const validValues = new Set(newOptions.map(o => String(o.value)));
    this.selected = this.selected.filter(val => validValues.has(String(val)));
    this.renderOptions();
    this.updateButtonText();
  }
  
  renderOptions() {
    this.optionsList.innerHTML = this.options.map(opt => {
      const isChecked = this.selected.includes(String(opt.value));
      return `
        <label class="multiselect-option">
          <input type="checkbox" value="${e(opt.value)}" ${isChecked ? 'checked' : ''} />
          <span title="${e(opt.label)}">${e(opt.label)}</span>
        </label>
      `;
    }).join('');
    
    // Attach event listeners to checkboxes
    this.optionsList.querySelectorAll('input').forEach(input => {
      input.addEventListener('change', (ev) => {
        const val = ev.target.value;
        if (ev.target.checked) {
          if (!this.selected.includes(val)) this.selected.push(val);
        } else {
          this.selected = this.selected.filter(v => v !== val);
        }
        this.updateButtonText();
        if (this.onChange) this.onChange(this.selected);
      });
    });
  }
  
  updateButtonText() {
    if (this.selected.length === 0) {
      this.btn.textContent = this.placeholder;
    } else if (this.selected.length === this.options.length) {
      this.btn.textContent = `All (${this.selected.length})`;
    } else {
      this.btn.textContent = `${this.selected.length} selected`;
    }
  }
  
  selectAll() {
    this.selected = this.options.map(o => String(o.value));
    this.optionsList.querySelectorAll('input').forEach(input => input.checked = true);
    this.updateButtonText();
    if (this.onChange) this.onChange(this.selected);
  }
  
  clearAll() {
    this.selected = [];
    this.optionsList.querySelectorAll('input').forEach(input => input.checked = false);
    this.updateButtonText();
    if (this.onChange) this.onChange(this.selected);
  }
  
  getSelectedValues() {
    return this.selected;
  }
  
  setSelectedValues(values) {
    this.selected = (values || []).map(String);
    this.renderOptions();
    this.updateButtonText();
  }
}

function getFilterValue(id) {
  if (multiselects[id]) {
    const selected = multiselects[id].getSelectedValues();
    return selected.length > 0 ? selected.join(',') : '';
  }
  const el = document.getElementById(id);
  return el ? el.value : '';
}

function setFilterValue(id, value) {
  if (multiselects[id]) {
    const vals = typeof value === 'string' && value ? value.split(',') : (Array.isArray(value) ? value : []);
    multiselects[id].setSelectedValues(vals);
  } else {
    const el = document.getElementById(id);
    if (el) el.value = value || "";
  }
}
let totalMessages = 0;
let pageSize      = 50;
let autoRefresh   = null;

let trCurrentPage = 1;
let trTotal       = 0;

let chartDay, chartKw, chartGrp;

// ── Boot ──────────────────────────────────────────────────────────────────────
document.addEventListener("DOMContentLoaded", () => {
  showSection("dashboard");
  loadKeywordsIntoDropdowns();
  loadGroupsIntoDropdowns();
  loadAccountsIntoFilterDropdown();
  startAutoRefresh();
});

function startAutoRefresh() {
  if (autoRefresh) clearInterval(autoRefresh);
  autoRefresh = setInterval(() => {
    const active = document.querySelector(".section.active");
    if (!active) return;
    const id = active.id;
    if (id === "section-dashboard")  refreshDashboard();
    if (id === "section-messages")   loadMessages(currentPage);
    if (id === "section-campaigns")  loadCampaigns();
    if (id === "section-network")    loadNetworkIntel();
    if (id === "section-actors")     loadActors();
    if (id === "section-cases")      loadCasesAndWatchlists();
    if (id === "section-health")     loadHealth();
  }, 30_000);
}

function manualRefresh() {
  const active = document.querySelector(".section.active");
  if (!active) return;
  const id = active.id;
  if (id === "section-dashboard")  refreshDashboard();
  if (id === "section-messages")   loadMessages(currentPage);
  if (id === "section-groups")     loadGroups();
  if (id === "section-keywords")   loadKeywords();
  if (id === "section-campaigns")  loadCampaigns();
  if (id === "section-network")    loadNetworkIntel();
  if (id === "section-actors")     loadActors();
  if (id === "section-cases")      loadCasesAndWatchlists();
  if (id === "section-health")     loadHealth();
}

// ── Section routing ───────────────────────────────────────────────────────────
function showSection(name) {
  document.querySelectorAll(".section").forEach(s => s.classList.remove("active"));
  document.querySelectorAll(".nav-item").forEach(n => n.classList.remove("active"));
  document.getElementById(`section-${name}`).classList.add("active");
  document.getElementById(`nav-${name}`).classList.add("active");
  document.getElementById("page-title").textContent = {
    dashboard: "Dashboard",
    messages:  "Messages",
    timerange: "Time Range",
    groups:    "Groups",
    keywords:  "Keywords",
    export:    "Export",
    campaigns: "Campaign Intel",
    network:   "Network Intel",
    actors:    "Actor Profiles",
    cases:     "Case Files",
    health:    "Pipeline Health",
  }[name] || name;

  if (name === "dashboard")  refreshDashboard();
  if (name === "messages")   loadMessages(1);
  if (name === "groups")   { loadGroups(); loadDiscoveredGroups(); }
  if (name === "keywords")   loadKeywords();
  if (name === "campaigns")  loadCampaigns();
  if (name === "network")    loadNetworkIntel();
  if (name === "actors")     loadActors();
  if (name === "cases")      loadCasesAndWatchlists();
  if (name === "health")     loadHealth();
}

// ── Helpers ───────────────────────────────────────────────────────────────────
function buildDatetimeParam(dateId, timeId) {
  const d = document.getElementById(dateId)?.value;
  const t = document.getElementById(timeId)?.value;
  if (!d) return null;
  return t ? `${d}T${t}` : d;
}

function fmtTs(ts) {
  if (!ts) return "—";
  return ts.replace("T", " ").substring(0, 16);
}

function fmtSec(s) {
  if (s == null || s === 0) return "—";
  const sec = Math.round(s);
  if (sec < 60)  return `${sec}s`;
  if (sec < 3600) return `${Math.floor(sec/60)}m ${sec%60}s`;
  return `${Math.floor(sec/3600)}h ${Math.floor((sec%3600)/60)}m`;
}

function toast(msg, type = "info") {
  const c = document.getElementById("toast-container");
  const t = document.createElement("div");
  t.className = `toast toast-${type}`;
  t.textContent = msg;
  c.appendChild(t);
  setTimeout(() => t.remove(), 3500);
}

function setLastRefresh() {
  document.getElementById("last-refresh-time").textContent =
    new Date().toLocaleTimeString();
}

// ── Dropdowns ─────────────────────────────────────────────────────────────────
async function loadKeywordsIntoDropdowns() {
  try {
    const kws = await fetch("/api/keywords").then(r => r.json());
    const ids = ["filter-keyword", "exp-keyword", "tr-keyword"];
    const options = kws.map(k => ({ value: k, label: k }));
    ids.forEach(id => {
      const el = document.getElementById(id);
      if (!el) return;
      if (!multiselects[id]) {
        multiselects[id] = new MultiSelect(id, id.includes("filter") ? "All keywords" : "All", options);
      } else {
        multiselects[id].updateOptions(options);
      }
    });
  } catch (e) { /* silent */ }
}

async function loadGroupsIntoDropdowns() {
  try {
    const groups = await fetch("/api/groups").then(r => r.json());
    const ids = ["filter-group", "exp-group", "tr-group"];
    const options = groups.map(g => ({ value: String(g.group_id), label: g.group_name || String(g.group_id) }));
    ids.forEach(id => {
      const el = document.getElementById(id);
      if (!el) return;
      if (!multiselects[id]) {
        multiselects[id] = new MultiSelect(id, id.includes("filter") ? "All groups" : "All", options);
      } else {
        multiselects[id].updateOptions(options);
      }
    });
  } catch (e) { /* silent */ }
}

// ── Dashboard ─────────────────────────────────────────────────────────────────
async function refreshDashboard() {
  await Promise.all([refreshStats(), refreshCharts()]);
  loadHeatmap();
  setLastRefresh();
}

async function refreshStats() {
  try {
    const account = getGlobalAccountFilter();
    const statsUrl = account ? `/api/stats?fetched_by=${encodeURIComponent(account)}` : "/api/stats";
    const [stats, groups, kws] = await Promise.all([
      fetch(statsUrl).then(r => r.json()),
      fetch("/api/groups").then(r => r.json()),
      fetch("/api/keywords").then(r => r.json()),
    ]);
    document.getElementById("stat-total").textContent   = stats.total.toLocaleString();
    document.getElementById("stat-matched").textContent = stats.matched.toLocaleString();
    document.getElementById("stat-groups").textContent  = groups.filter(g => g.is_active).length;
    document.getElementById("stat-keywords").textContent = kws.length;
  } catch (e) { console.error(e); }
}

async function refreshCharts() {
  const from = document.getElementById("chart-date-from").value || null;
  const to   = document.getElementById("chart-date-to").value   || null;
  const account = getGlobalAccountFilter();
  let url = "/api/stats";
  const params = [];
  if (from) params.push(`datetime_from=${from}`);
  if (to)   params.push(`datetime_to=${to}`);
  if (account) params.push(`fetched_by=${encodeURIComponent(account)}`);
  if (params.length) url += "?" + params.join("&");

  try {
    const stats = await fetch(url).then(r => r.json());

    // Messages per day
    const days  = stats.per_day.slice().reverse();
    const dayLabels = days.map(d => d.day);
    const dayCounts = days.map(d => d.cnt);
    if (chartDay) chartDay.destroy();
    chartDay = new Chart(document.getElementById("chart-per-day"), {
      type: "line",
      data: {
        labels: dayLabels,
        datasets: [{ label: "Messages", data: dayCounts,
          borderColor: "#9f63f3", backgroundColor: "rgba(159,99,243,.15)",
          fill: true, tension: 0.4, pointRadius: 3 }]
      },
      options: { plugins: { legend: { display: false } }, scales: {
        x: { ticks: { color: "#94a3b8" }, grid: { color: "#2a2a3e" } },
        y: { ticks: { color: "#94a3b8" }, grid: { color: "#2a2a3e" } }
      }}
    });

    // Top keywords
    const kwLabels = stats.per_keyword.map(k => k.matched_keyword);
    const kwCounts = stats.per_keyword.map(k => k.cnt);
    if (chartKw) chartKw.destroy();
    chartKw = new Chart(document.getElementById("chart-keywords"), {
      type: "bar",
      data: {
        labels: kwLabels,
        datasets: [{ label: "Hits", data: kwCounts,
          backgroundColor: "rgba(96,165,250,.6)", borderColor: "#60a5fa", borderWidth: 1 }]
      },
      options: {
        indexAxis: "y",
        plugins: { legend: { display: false } },
        scales: {
          x: { ticks: { color: "#94a3b8" }, grid: { color: "#2a2a3e" } },
          y: { ticks: { color: "#ccc", font: { size: 11 } }, grid: { display: false } }
        }
      }
    });

    // Top groups donut
    const grpLabels = stats.per_group.map(g => g.group_name);
    const grpCounts = stats.per_group.map(g => g.cnt);
    if (chartGrp) chartGrp.destroy();
    chartGrp = new Chart(document.getElementById("chart-groups"), {
      type: "doughnut",
      data: {
        labels: grpLabels,
        datasets: [{ data: grpCounts,
          backgroundColor: ["#9f63f3","#60a5fa","#34d399","#f59e0b","#f87171",
                            "#a78bfa","#38bdf8","#4ade80","#fb923c","#ef4444"] }]
      },
      options: { plugins: { legend: { position: "right", labels: { color: "#ccc", font: { size: 11 } } } } }
    });
  } catch (e) { console.error(e); }
}

function clearChartDates() {
  document.getElementById("chart-date-from").value = "";
  document.getElementById("chart-date-to").value   = "";
  refreshCharts();
}

// ── Messages ──────────────────────────────────────────────────────────────────
async function loadMessages(page = 1) {
  currentPage = page;
  const kw       = getFilterValue("filter-keyword");
  const grp      = getFilterValue("filter-group");
  const dtFrom   = buildDatetimeParam("filter-date-from", "filter-time-from");
  const dtTo     = buildDatetimeParam("filter-date-to",   "filter-time-to");
  const hitsOnly = document.getElementById("filter-matched-only").checked;

  const account = getGlobalAccountFilter();
  let url = `/api/messages?page=${page}&page_size=${pageSize}`;
  if (kw)       url += `&keyword=${encodeURIComponent(kw)}`;
  if (grp)      url += `&group_id=${grp}`;
  if (dtFrom)   url += `&datetime_from=${encodeURIComponent(dtFrom)}`;
  if (dtTo)     url += `&datetime_to=${encodeURIComponent(dtTo)}`;
  if (hitsOnly) url += `&matched_only=true`;
  if (account)  url += `&fetched_by=${encodeURIComponent(account)}`;
  if (window.filterHeatmapDow !== undefined && window.filterHeatmapDow !== null)   url += `&dow=${window.filterHeatmapDow}`;
  if (window.filterHeatmapHour !== undefined && window.filterHeatmapHour !== null) url += `&hour=${window.filterHeatmapHour}`;
  if (window.filterQuery) url += `&q=${encodeURIComponent(window.filterQuery)}`;

  const qi = document.getElementById("query-filter-indicator");
  const qt = document.getElementById("query-filter-text");
  if (qi && qt) {
    if (window.filterQuery) {
      qt.textContent = window.filterQuery;
      qi.style.display = "flex";
    } else {
      qi.style.display = "none";
    }
  }

  try {

    const data = await fetch(url).then(r => r.json());
    renderMessagesTable(data.messages);
    totalMessages = data.total;
    document.getElementById("page-info").textContent = `Page ${page}`;
    document.getElementById("total-info").textContent = `${data.total.toLocaleString()} total`;
    document.getElementById("prev-page").disabled = page <= 1;
    document.getElementById("next-page").disabled = page * pageSize >= data.total;
    setLastRefresh();
  } catch (e) { console.error(e); }
}

function renderMessagesTable(msgs) {
  window.currentMessages = msgs; // Store locally for click detail
  const tbody = document.getElementById("messages-body");
  if (!msgs.length) {
    tbody.innerHTML = `<tr><td colspan="11" class="loading-cell">No messages match the filters.</td></tr>`;
    return;
  }
  tbody.innerHTML = msgs.map((m, index) => {
    const isHit   = m.is_matched;
    const isCross = m.cross_group_forward || (m.is_forwarded && m.forward_from_id);
    const rowCls  = isHit ? (isCross ? "row-both" : "row-hit") : (isCross ? "row-cross" : "");
    const fwdSrc  = m.forward_from_name || (m.forward_from_id ? `#${m.forward_from_id}` : "—");
    return `<tr class="${rowCls}" onclick="openMessageDetail(${index})">
      <td>${fmtTs(m.timestamp)}</td>
      <td class="ellipsis" title="${e(m.group_name)}">${e(m.group_name)}</td>
      <td class="ellipsis" title="${e(m.sender_name)}${m.sender_id ? ` (${m.sender_id})` : ''}">${e(m.sender_name)}${m.sender_id ? ` <span class="muted" style="font-size:11px;">(${m.sender_id})</span>` : ""}</td>
      <td>${m.language || "?"}</td>
      <td>${getThreatBadge(m.threat_category)}</td>
      <td>${getRiskScoreBadge(m.risk_score)}</td>
      <td>${m.matched_keyword ? `<span class="kw-badge">${e(m.matched_keyword)}</span>` : "—"}</td>
      <td>${m.fuzzy_score ? m.fuzzy_score.toFixed(0) : "—"}</td>
      <td>${m.is_forwarded ? "✅" : ""}</td>
      <td class="ellipsis" title="${e(fwdSrc)}">${e(fwdSrc)}</td>
      <td class="msg-text" title="${e(m.text)}">${e((m.text||"").substring(0,120))}</td>
    </tr>`;
  }).join("");
}

function getThreatBadge(cat) {
  if (!cat) return "—";
  const key = cat.toLowerCase();
  let badgeClass = "threat-legit";
  if (key.includes("scam") || key.includes("fraud")) badgeClass = "threat-scam";
  else if (key.includes("weapons") || key.includes("violence") || key.includes("extremism")) badgeClass = "threat-weapons";
  else if (key.includes("cyber") || key.includes("hack")) badgeClass = "threat-cyber";
  else if (key.includes("mule") || key.includes("financial")) badgeClass = "threat-mule";
  else if (key.includes("drug") || key.includes("traffic")) badgeClass = "threat-drugs";
  else if (key.includes("legit") || key.includes("other")) badgeClass = "threat-legit";
  return `<span class="threat-badge ${badgeClass}">${cat}</span>`;
}

function openMessageDetail(index) {
  const m = window.currentMessages[index];
  if (!m) return;
  
  // Store reference to current message row ID globally for adding to cases
  window.currentMessageId = m.id;
  populateCaseDropdownInModal();
  
  document.getElementById("modal-group").textContent = m.group_name || m.group_id;
  let senderText = m.sender_name || m.sender_phone || "Unknown";
  if (m.sender_id) senderText += ` (ID: ${m.sender_id})`;
  document.getElementById("modal-sender").textContent = senderText;
  document.getElementById("modal-time").textContent = fmtTs(m.timestamp);
  document.getElementById("modal-lang").textContent = m.language || "Unknown";
  document.getElementById("modal-keyword").textContent = m.matched_keyword || "None";
  document.getElementById("modal-score").textContent = m.fuzzy_score ? m.fuzzy_score.toFixed(0) : "—";
  document.getElementById("modal-threat-category").innerHTML = getThreatBadge(m.threat_category);
  document.getElementById("modal-campaign").textContent = m.campaign_id || "None";
  document.getElementById("modal-risk-score").innerHTML = getRiskScoreBadge(m.risk_score);

  // Reset Translation UI
  const transBox = document.getElementById("modal-translation-box");
  const transText = document.getElementById("modal-translation-text");
  const transBtn = document.getElementById("modal-btn-translate");
  if (transBox) transBox.style.display = "none";
  if (transText) transText.textContent = "";
  if (transBtn) {
    if (m.language && m.language.toLowerCase() !== "en" && m.language.toLowerCase() !== "unknown") {
      transBtn.style.display = "block";
      transBtn.textContent = "🌐 Translate";
      transBtn.disabled = false;
    } else {
      transBtn.style.display = "none";
    }
  }
  
  // Highlight entities
  const text = m.text || "";
  const entities = m.entities || [];
  
  let lastIdx = 0;
  let htmlText = "";
  // Sort entities left-to-right to build the text sequentially
  const ltrEntities = entities.slice()
    .filter(ent => ent.position_in_text != null && ent.entity_value)
    .sort((a, b) => a.position_in_text - b.position_in_text);
     
  ltrEntities.forEach(ent => {
    const pos = ent.position_in_text;
    const val = ent.entity_value;
    
    if (pos >= lastIdx) {
      // Append escaped text before the entity
      htmlText += e(text.substring(lastIdx, pos));
      
      // Append styled entity
      const isSanctioned = ent.is_sanctioned === 1;
      const hlClass = isSanctioned ? "hl-sanctioned" : `hl-${ent.entity_type}`;
      const badge = isSanctioned ? ' <span class="sanctioned-badge">⚠️ OFAC Sanctioned</span>' : "";
      
      const pivotable = ["phone", "email", "url", "upi_id", "telegram_handle",
                         "crypto_btc", "crypto_eth", "crypto_trx", "crypto_usdt"];
      const isPivotable = pivotable.some(t => ent.entity_type.includes(t.split("_")[1] || t) 
                            || ent.entity_type === t);

      if (isPivotable) {
        htmlText += `<span class="highlight-entity clickable-hl ${hlClass}" ondblclick="showIocPivot('${e(ent.entity_type)}', '${e(val).replace(/'/g,"\\'")}')" title="Double-click to pivot search: ${ent.entity_type}">${e(val)}${badge}</span>`;
      } else {
        htmlText += `<span class="highlight-entity ${hlClass}" title="${ent.entity_type}">${e(val)}${badge}</span>`;
      }
      lastIdx = pos + val.length;
    }
  });
  // Append the remainder of the text
  htmlText += e(text.substring(lastIdx));
  
  document.getElementById("modal-text").innerHTML = htmlText;
  
  // Render entities list in the sidebar
  const listDiv = document.getElementById("modal-entities-list");
  if (!entities.length) {
    listDiv.innerHTML = `<div class="muted" style="font-size:13px;">No entities extracted from this message.</div>`;
  } else {
    listDiv.innerHTML = entities.map(renderEntityItemMarkup).join("");
  }
  
  // Set current phash/index for similar image queries
  window.currentMessagePhash = m.phash;
  window.currentMessageIndex = index;

  // Media image container
  const mediaBox = document.getElementById("modal-media-box");
  const modalImg = document.getElementById("modal-img");
  const similarContainer = document.getElementById("modal-similar-images-container");
  
  if (similarContainer) similarContainer.style.display = "none";
  const similarList = document.getElementById("modal-similar-images-list");
  if (similarList) similarList.innerHTML = "";

  if (m.media_path && modalImg && mediaBox) {
    modalImg.src = `/${m.media_path}`;
    const phashSpan = document.getElementById("modal-phash-val");
    if (phashSpan) phashSpan.textContent = m.phash ? `pHash: ${m.phash}` : "";
    mediaBox.style.display = "block";
  } else {
    if (modalImg) modalImg.src = "";
    if (mediaBox) mediaBox.style.display = "none";
  }

  // OCR Text container
  const ocrBox = document.getElementById("modal-ocr-box");
  const ocrTextPara = document.getElementById("modal-ocr-text");
  if (m.ocr_text && ocrTextPara && ocrBox) {
    ocrTextPara.textContent = m.ocr_text;
    ocrBox.style.display = "block";
  } else {
    if (ocrBox) ocrBox.style.display = "none";
  }

  // QR Codes container
  const qrSection = document.getElementById("modal-qrs-section");
  const qrList = document.getElementById("modal-qrs-list");
  let qrs = [];
  if (m.qr_codes) {
    try {
      qrs = JSON.parse(m.qr_codes);
      if (!Array.isArray(qrs)) qrs = [qrs];
    } catch(e) {
      qrs = [m.qr_codes];
    }
  }

  if (qrs.length > 0 && qrList && qrSection) {
    qrList.innerHTML = qrs.map(qr => `
      <div class="qr-badge" onclick="navigator.clipboard.writeText('${e(qr)}'); showToast('Copied QR code to clipboard!')" title="Click to copy contents">
        🔍 ${e(qr)}
      </div>
    `).join("");
    qrSection.style.display = "block";
  } else {
    if (qrSection) qrSection.style.display = "none";
  }
  
  document.getElementById("message-detail-modal").classList.add("active");
}

function closeModal() {
  document.getElementById("message-detail-modal").classList.remove("active");
  closeModalPivotPane();
}

async function fetchEnrichmentForWallet(address, entityId) {
  try {
    const res = await fetch(`/api/wallets/${address}/enrichment`).then(r => r.json());
    if (res && !res.error) {
      const activeModal = document.getElementById("message-detail-modal").classList.contains("active");
      if (activeModal) {
        const selectedIndex = window.currentMessages.findIndex(m => m.entities && m.entities.some(e => e.id === entityId));
        if (selectedIndex !== -1) {
          const entIdx = window.currentMessages[selectedIndex].entities.findIndex(e => e.id === entityId);
          if (entIdx !== -1) {
            window.currentMessages[selectedIndex].entities[entIdx].balance = res.balance;
            window.currentMessages[selectedIndex].entities[entIdx].tx_count = res.tx_count;
            window.currentMessages[selectedIndex].entities[entIdx].last_enriched_at = res.last_enriched_at;
            window.currentMessages[selectedIndex].entities[entIdx].enrichment_source = res.enrichment_source;
          }
          const entities = window.currentMessages[selectedIndex].entities;
          const listDiv = document.getElementById("modal-entities-list");
          listDiv.innerHTML = entities.map(renderEntityItemMarkup).join("");
        }
      }
    }
  } catch(e){}
}

async function fetchEnrichmentForPhone(phoneVal, entityId) {
  try {
    const res = await fetch(`/api/phones/${encodeURIComponent(phoneVal)}/enrichment`).then(r => r.json());
    if (res && !res.error) {
      const activeModal = document.getElementById("message-detail-modal").classList.contains("active");
      if (activeModal) {
        const selectedIndex = window.currentMessages.findIndex(m => m.entities && m.entities.some(e => e.id === entityId));
        if (selectedIndex !== -1) {
          const entIdx = window.currentMessages[selectedIndex].entities.findIndex(e => e.id === entityId);
          if (entIdx !== -1) {
            window.currentMessages[selectedIndex].entities[entIdx].country_name = res.country_name;
            window.currentMessages[selectedIndex].entities[entIdx].location = res.location;
            window.currentMessages[selectedIndex].entities[entIdx].carrier = res.carrier;
            window.currentMessages[selectedIndex].entities[entIdx].is_valid = res.is_valid;
            window.currentMessages[selectedIndex].entities[entIdx].phone_last_enriched = res.last_enriched_at;
          }
          const entities = window.currentMessages[selectedIndex].entities;
          const listDiv = document.getElementById("modal-entities-list");
          listDiv.innerHTML = entities.map(renderEntityItemMarkup).join("");
        }
      }
    }
  } catch(e){}
}

function renderEntityItemMarkup(ent) {
  const isCrypto = ent.entity_type.startsWith("crypto_");
  const isPhone = ent.entity_type === "phone_number";
  const isSanctioned = ent.is_sanctioned === 1;
  const itemClass = isSanctioned ? "entity-item sanctioned-alert" : `entity-item entity-${ent.entity_type}`;
  
  let detailsHtml = "";
  if (isCrypto) {
    const balance = ent.balance != null ? `${Number(ent.balance).toFixed(4)}` : "Loading...";
    const txCount = ent.tx_count != null ? ent.tx_count : "Loading...";
    const source = ent.last_enriched_at ? `via ${ent.enrichment_source || 'Explorer'}` : "Pending background check";
    
    detailsHtml = `
      <div class="entity-wallet-details">
        <div><strong>Balance:</strong> ${balance}</div>
        <div><strong>Transactions:</strong> ${txCount}</div>
        <div style="font-size:9px; margin-top:2px; opacity:0.6;">${source}</div>
      </div>
    `;
    if (ent.balance == null) {
      setTimeout(() => fetchEnrichmentForWallet(ent.entity_value, ent.id), 1000);
    }
  } else if (isPhone) {
    const country = ent.country_name || "Unknown";
    const location = ent.location || "Unknown Location";
    const carrier = ent.carrier || "Unknown Carrier";
    const isValid = ent.is_valid === 1 ? "Valid" : (ent.is_valid === 0 ? "Invalid" : "Unverified");
    const validityColor = ent.is_valid === 1 ? "#34d399" : "#f87171";
    
    detailsHtml = `
      <div class="entity-phone-details">
        <div><strong>Country:</strong> ${country}</div>
        <div><strong>Location:</strong> ${location}</div>
        <div><strong>Carrier:</strong> ${carrier}</div>
        <div><strong>Status:</strong> <span style="color: ${validityColor}; font-weight: bold;">${isValid}</span></div>
      </div>
    `;
    if (!ent.country_name) {
      setTimeout(() => fetchEnrichmentForPhone(ent.entity_value, ent.id), 1000);
    }
  }
  
  const pivotable = ["phone", "email", "url", "upi_id",
                     "crypto_btc", "crypto_eth", "crypto_trx", "crypto_usdt", "phone_number"];
  const isPivotable = pivotable.some(t => ent.entity_type.includes(t.split("_")[1] || t) 
                        || ent.entity_type === t);
  const valueHtml = isPivotable
    ? `<button class="ioc-chip" onclick="showIocPivot('${e(ent.entity_type)}', '${e(ent.entity_value).replace(/'/g,"\\'")}')">
         <span class="ioc-chip-icon">🔗</span>${e(ent.entity_value)}
       </button>`
    : `<div class="entity-item-value">${e(ent.entity_value)}</div>`;

  return `
    <div class="${itemClass}">
      <div class="entity-item-header">
        <span>${ent.entity_type.replace("crypto_", "").toUpperCase()}</span>
        ${isSanctioned ? '<span class="sanctioned-badge">⚠️ Sanctioned</span>' : ""}
      </div>
      ${valueHtml}
      ${detailsHtml}
    </div>
  `;
}

function e(s) { return (s||"").replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;"); }

function changePage(delta) { loadMessages(currentPage + delta); }

function clearFilters() {
  setFilterValue("filter-keyword", "");
  setFilterValue("filter-group", "");
  ["filter-date-from","filter-time-from",
   "filter-date-to","filter-time-to"].forEach(id => {
     const el = document.getElementById(id);
     if (el) el.value = "";
  });
  document.getElementById("filter-matched-only").checked = false;
  clearHeatmapFilter(false);
  window.filterQuery = null;
  loadMessages(1);
}

function pivotToMessagesSearch(query) {
  window.filterQuery = query;
  showSection("messages");
  loadMessages(1);
}

function clearQueryFilter() {
  window.filterQuery = null;
  loadMessages(1);
}



// ── Time Range ────────────────────────────────────────────────────────────────
function trPreset(type) {
  const today = new Date();
  const fmt = d => d.toISOString().split("T")[0];

  const setRange = (fromDate, fromTime, toDate, toTime) => {
    document.getElementById("tr-date-from").value = fromDate;
    document.getElementById("tr-time-from").value = fromTime || "";
    document.getElementById("tr-date-to").value   = toDate;
    document.getElementById("tr-time-to").value   = toTime || "";
  };

  const yesterday = new Date(today); yesterday.setDate(today.getDate() - 1);
  const last7 = new Date(today); last7.setDate(today.getDate() - 7);

  if (type === "today")     setRange(fmt(today), "", fmt(today), "");
  if (type === "yesterday") setRange(fmt(yesterday), "", fmt(yesterday), "");
  if (type === "last7")     setRange(fmt(last7), "", fmt(today), "");
  if (type === "morning")   setRange(fmt(today), "09:00", fmt(today), "12:00");
  if (type === "afternoon") setRange(fmt(today), "12:00", fmt(today), "18:00");
  if (type === "evening")   setRange(fmt(today), "18:00", fmt(today), "23:00");
}

function clearTimeRange() {
  ["tr-date-from","tr-time-from","tr-date-to","tr-time-to","tr-keyword","tr-group"]
    .forEach(id => { const el = document.getElementById(id); if (el) el.value = ""; });
  document.getElementById("tr-summary").style.display  = "none";
  document.getElementById("tr-table-wrap").style.display   = "none";
  document.getElementById("tr-pagination").style.display  = "none";
}

async function runTimeRange(page = 1) {
  trCurrentPage = page;
  const dtFrom = buildDatetimeParam("tr-date-from", "tr-time-from");
  const dtTo   = buildDatetimeParam("tr-date-to",   "tr-time-to");
  if (!dtFrom && !dtTo) { toast("Please set at least a start or end date.", "warn"); return; }

  const kw  = document.getElementById("tr-keyword").value;
  const grp = document.getElementById("tr-group").value;

  const account = getGlobalAccountFilter();
  let url = `/api/messages?page=${page}&page_size=100`;
  if (dtFrom) url += `&datetime_from=${encodeURIComponent(dtFrom)}`;
  if (dtTo)   url += `&datetime_to=${encodeURIComponent(dtTo)}`;
  if (kw)     url += `&keyword=${encodeURIComponent(kw)}`;
  if (grp)    url += `&group_id=${grp}`;
  if (account) url += `&fetched_by=${encodeURIComponent(account)}`;

  try {
    const data = await fetch(url).then(r => r.json());
    trTotal = data.total;

    // Summary cards
    const hits    = data.messages.filter(m => m.is_matched).length;
    const cross   = data.messages.filter(m => m.is_forwarded).length;
    const groups  = new Set(data.messages.map(m => m.group_id)).size;
    document.getElementById("tr-summary-cards").innerHTML = `
      <div class="stat-card mini"><div class="stat-value">${data.total}</div><div class="stat-label">Messages</div></div>
      <div class="stat-card mini accent-green"><div class="stat-value">${hits}</div><div class="stat-label">Keyword Hits</div></div>
      <div class="stat-card mini accent-orange"><div class="stat-value">${cross}</div><div class="stat-label">Forwarded</div></div>
      <div class="stat-card mini accent-blue"><div class="stat-value">${groups}</div><div class="stat-label">Groups</div></div>`;
    document.getElementById("tr-summary").style.display = "block";

    // Table
    const tbody = document.getElementById("tr-body");
    if (!data.messages.length) {
      tbody.innerHTML = `<tr><td colspan="7" class="loading-cell">No messages in this time range.</td></tr>`;
    } else {
      tbody.innerHTML = data.messages.map(m => {
        const rowCls = m.is_matched ? "row-hit" : (m.is_forwarded ? "row-cross" : "");
        return `<tr class="${rowCls}">
          <td>${fmtTs(m.timestamp)}</td>
          <td class="ellipsis">${e(m.group_name)}</td>
          <td class="ellipsis">${e(m.sender_name)}</td>
          <td>${m.matched_keyword ? `<span class="kw-badge">${e(m.matched_keyword)}</span>` : "—"}</td>
          <td>${m.fuzzy_score ? m.fuzzy_score.toFixed(0) : "—"}</td>
          <td>${m.is_forwarded ? "✅" : ""}</td>
          <td class="msg-text" title="${e(m.text)}">${e((m.text||"").substring(0,120))}</td>
        </tr>`;
      }).join("");
    }
    document.getElementById("tr-table-wrap").style.display  = "block";

    // Pagination
    document.getElementById("tr-pagination").style.display = "flex";
    document.getElementById("tr-page-info").textContent = `Page ${page}`;
    document.getElementById("tr-total").textContent = `${data.total.toLocaleString()} total`;
    document.getElementById("tr-prev").disabled = page <= 1;
    document.getElementById("tr-next").disabled = page * 100 >= data.total;

    toast(`Found ${data.total} messages in range.`);
  } catch (e) { console.error(e); toast("Error fetching time range.", "error"); }
}

function trChangePage(delta) { runTimeRange(trCurrentPage + delta); }

function trExport(fmt) {
  const dtFrom = buildDatetimeParam("tr-date-from", "tr-time-from");
  const dtTo   = buildDatetimeParam("tr-date-to",   "tr-time-to");
  const kw  = document.getElementById("tr-keyword").value;
  const grp = document.getElementById("tr-group").value;
  const account = getGlobalAccountFilter();
  let url = `/export/${fmt}?`;
  if (dtFrom) url += `&datetime_from=${encodeURIComponent(dtFrom)}`;
  if (dtTo)   url += `&datetime_to=${encodeURIComponent(dtTo)}`;
  if (kw)     url += `&keyword=${encodeURIComponent(kw)}`;
  if (grp)    url += `&group_id=${grp}`;
  if (account) url += `&fetched_by=${encodeURIComponent(account)}`;
  window.open(url, "_blank");
}

// ── Groups ────────────────────────────────────────────────────────────────────
async function loadGroups() {
  try {
    const groups = await fetch("/api/groups").then(r => r.json());
    const grid = document.getElementById("groups-grid");
    if (!groups.length) {
      grid.innerHTML = `<p class="muted">No groups synced yet. Run python main.py to sync.</p>`;
      return;
    }
    grid.innerHTML = groups.map(g => `
      <div class="group-card ${g.is_active ? 'active' : ''}" id="gcard-${g.group_id}">
        <div class="group-info">
          <div class="group-name">${e(g.group_name || "Unknown")}</div>
          <div class="group-meta muted">${g.group_type} · ${(g.member_count||0).toLocaleString()} members</div>
          ${g.last_message_at ? `<div class="group-meta muted">Last: ${fmtTs(g.last_message_at)}</div>` : ""}
        </div>
        <div class="group-controls">
          <label class="toggle-switch" title="${g.is_active ? 'Monitoring ON' : 'Monitoring OFF'}">
            <input type="checkbox" ${g.is_active ? "checked" : ""}
              onchange="toggleGroup(${g.group_id}, this)"/>
            <span class="toggle-slider"></span>
          </label>
          <button class="btn-leave-group" onclick="leaveGroup(${g.group_id}, '${e(g.group_name || 'this group')}')" title="Leave group and stop monitoring">
            🚪 Leave
          </button>
        </div>
      </div>`).join("");
  } catch (err) { console.error(err); }
}

async function toggleGroup(groupId, checkbox) {
  try {
    const res = await fetch(`/api/groups/${groupId}/toggle`, { method: "POST" }).then(r => r.json());
    const card = checkbox.closest(".group-card");
    if (res.is_active) { card.classList.add("active"); toast("Monitoring ON"); }
    else               { card.classList.remove("active"); toast("Monitoring OFF"); }
  } catch (e) { toast("Toggle failed", "error"); checkbox.checked = !checkbox.checked; }
}

/**
 * Leave a Telegram group and permanently stop monitoring it.
 * Shows a confirmation dialog first.
 */
async function leaveGroup(groupId, groupName) {
  const confirmed = window.confirm(
    `Leave "${groupName}"?\n\nThis will:\n• Make your account exit the Telegram group\n• Stop monitoring new messages from it\n\nYour existing messages and data will be kept for analysis.`
  );
  if (!confirmed) return;

  const card = document.getElementById(`gcard-${groupId}`);
  if (card) {
    card.style.transition = "opacity 0.4s, transform 0.4s";
    card.style.opacity = "0.4";
    card.style.pointerEvents = "none";
  }

  try {
    const res  = await fetch(`/api/groups/${groupId}/leave`, { method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({})
    });
    const data = await res.json();

    if (data.status === "success" || data.status === "partial") {
      showToast(`🚪 Left "${groupName}" and stopped monitoring.`, "success");
      if (card) {
        card.style.transform = "translateX(30px)";
        setTimeout(() => card.remove(), 400);
      } else {
        await loadGroups();
      }
    } else {
      showToast(data.error || "Leave failed.", "error");
      if (card) { card.style.opacity = "1"; card.style.pointerEvents = ""; }
    }
  } catch (err) {
    showToast("Network error while leaving group.", "error");
    if (card) { card.style.opacity = "1"; card.style.pointerEvents = ""; }
  }
}

async function loadKeywords() {
  try {
    const kws = await fetch("/api/keywords").then(r => r.json());
    const cloud = document.getElementById("keywords-cloud");
    if (!kws.length) { cloud.innerHTML = `<p class="muted">No keywords. Add some above.</p>`; return; }
    cloud.innerHTML = kws.map(k =>
      `<span class="kw-chip">${e(k)} <button class="kw-remove" onclick="removeKeyword('${e(k)}')">×</button></span>`
    ).join("");
    loadKeywordsIntoDropdowns();
    loadKeywordEffectiveness();
  } catch (err) { console.error(err); }
}

async function loadKeywordEffectiveness() {
  const tbody = document.getElementById("keywords-effectiveness-body");
  if (!tbody) return;
  try {
    const stats = await fetch("/api/keywords/effectiveness").then(r => r.json());
    if (!stats || !stats.length) {
      tbody.innerHTML = `<tr><td colspan="5" class="loading-cell">No keyword alerts tracked yet.</td></tr>`;
      return;
    }
    
    tbody.innerHTML = stats.map(s => {
      const risk = s.avg_risk || 0.0;
      const riskCls = risk >= 70 ? "risk-high" : risk >= 40 ? "risk-medium" : "risk-low";
      
      // Determine effectiveness rating
      let rating = "—";
      let ratingStyle = "background: rgba(255,255,255,0.05); color: #fff;";
      if (s.total_hits === 0) {
        rating = "INACTIVE";
        ratingStyle = "background: rgba(148,163,184,0.15); color: #94a3b8;";
      } else if (risk < 25.0 && s.total_hits > 15) {
        rating = "⚠️ NOISY";
        ratingStyle = "background: rgba(59,130,246,0.15); color: #60a5fa;";
      } else if (risk >= 60.0 || s.high_risk_hits > 5) {
        rating = "🔥 HIGH YIELD";
        ratingStyle = "background: rgba(239,68,68,0.15); color: #f87171;";
      } else {
        rating = "MODERATE";
        ratingStyle = "background: rgba(249,115,22,0.15); color: #fb923c;";
      }

      return `
        <tr>
          <td style="font-weight:600; color: #a78bfa;">${e(s.keyword)}</td>
          <td><strong>${s.total_hits}</strong></td>
          <td><span style="font-weight:600;">${s.high_risk_hits}</span></td>
          <td><span class="${riskCls}">${risk.toFixed(1)}</span></td>
          <td><span style="display:inline-block; padding: 2px 8px; border-radius: 4px; font-size:11px; font-weight:700; ${ratingStyle}">${rating}</span></td>
        </tr>
      `;
    }).join("");
  } catch (err) {
    console.error("Failed to load keyword effectiveness:", err);
    tbody.innerHTML = `<tr><td colspan="5" class="loading-cell" style="color:#ef4444;">Failed to load keyword analytics.</td></tr>`;
  }
}

async function addKeyword() {
  const input = document.getElementById("new-keyword-input");
  const kw = input.value.trim();
  if (!kw) return;
  try {
    const res = await fetch("/api/keywords", {
      method: "POST", headers: {"Content-Type":"application/json"},
      body: JSON.stringify({keyword: kw})
    }).then(r => r.json());
    if (res.added) { toast(`Added: ${kw}`, "ok"); input.value = ""; loadKeywords(); }
    else toast("Already exists or invalid.", "warn");
  } catch (e) { toast("Error adding keyword.", "error"); }
}

async function removeKeyword(kw) {
  if (!confirm(`Remove keyword "${kw}"?`)) return;
  try {
    await fetch(`/api/keywords/${encodeURIComponent(kw)}`, {method:"DELETE"});
    toast(`Removed: ${kw}`);
    loadKeywords();
  } catch (e) { toast("Error removing keyword.", "error"); }
}

// ── Export ────────────────────────────────────────────────────────────────────
function doExport(fmt) {
  const kw      = getFilterValue("exp-keyword");
  const grp     = getFilterValue("exp-group");
  const dtFrom  = buildDatetimeParam("exp-date-from", "exp-time-from");
  const dtTo    = buildDatetimeParam("exp-date-to",   "exp-time-to");
  const matched = document.getElementById("exp-matched-only").checked;
  const account = getGlobalAccountFilter();

  let url = `/export/${fmt}?`;
  if (kw)      url += `&keyword=${encodeURIComponent(kw)}`;
  if (grp)     url += `&group_id=${grp}`;
  if (dtFrom)  url += `&datetime_from=${encodeURIComponent(dtFrom)}`;
  if (dtTo)    url += `&datetime_to=${encodeURIComponent(dtTo)}`;
  if (matched) url += `&matched_only=true`;
  if (account) url += `&fetched_by=${encodeURIComponent(account)}`;
  window.open(url, "_blank");
}

// ── Pipeline Health ───────────────────────────────────────────────────────────
async function loadHealth() {
  try {
    loadPipelineStatus();
    const h = await fetch("/api/pipeline/health").then(r => r.json());
    document.getElementById("h-disconnects").textContent = h.disconnect_count_today;
    document.getElementById("h-downtime").textContent    = fmtSec(h.total_downtime_seconds_today);

    const backfilled = h.events
      .filter(ev => ev.event_type === "reconnect")
      .reduce((s, ev) => {
        const m = (ev.details || "").match(/backfilled=(\d+)/);
        return s + (m ? parseInt(m[1]) : 0);
      }, 0);
    document.getElementById("h-backfilled").textContent = backfilled;

    const typeIcon = { disconnect:"🔌", reconnect:"🔗", backfill:"📦", startup:"🚀" };
    const tbody = document.getElementById("health-body");
    if (!h.events.length) {
      tbody.innerHTML = `<tr><td colspan="5" class="loading-cell">No events today — pipeline running cleanly.</td></tr>`;
      return;
    }
    tbody.innerHTML = h.events.map(ev => `
      <tr class="${ev.event_type === 'disconnect' ? 'row-cross' : ''}">
        <td>${typeIcon[ev.event_type] || "⚙️"} ${ev.event_type}</td>
        <td>${fmtTs(ev.started_at)}</td>
        <td>${fmtTs(ev.ended_at)}</td>
        <td>${fmtSec(ev.duration_seconds)}</td>
        <td class="muted">${e(ev.details||"")}</td>
      </tr>`).join("");
    setLastRefresh();
    loadAlertSettings();
  } catch (err) { console.error(err); }
}

// ── Network & Behavioral Intelligence ──────────────────────────────────────────
async function loadNetworkIntel() {
  await Promise.all([loadNetworkGraph(), loadCadenceChart()]);
}

let cy = null;

async function loadNetworkGraph() {
  try {
    const account = getGlobalAccountFilter();
    const mode = document.getElementById("network-graph-mode")?.value || "forwards";
    let url = `/api/network/graph?mode=${mode}`;
    if (account) url += `&fetched_by=${encodeURIComponent(account)}`;
    const data = await fetch(url).then(r => r.json());
    
    // Update legends dynamically
    const legend = document.querySelector(".graph-legend");
    if (legend) {
      if (mode === "entity_connection") {
        legend.innerHTML = `
          <span class="legend-item"><span class="legend-dot" style="background:#8b5cf6;"></span> Actor / Sender</span>
          <span class="legend-item"><span class="legend-dot" style="background:#06b6d4;"></span> Monitored Group</span>
          <span class="legend-item"><span class="legend-dot" style="background:#fbbf24;"></span> Extracted Entity (IOC)</span>
        `;
      } else {
        legend.innerHTML = `
          <span class="legend-item"><span class="legend-dot source-dot"></span> Forward Source Channel</span>
          <span class="legend-item"><span class="legend-dot target-dot"></span> Ingested Group</span>
        `;
      }
    }

    // Initialize Cytoscape.js
    cy = cytoscape({
      container: document.getElementById('cy'),
      elements: data.elements,
      style: [
        {
          selector: 'node',
          style: {
            'background-color': function(ele) {
              const t = ele.data('type');
              if (t === 'actor') return '#8b5cf6';
              if (t === 'entity') return '#fbbf24';
              if (t === 'source') return '#f43f5e';
              return '#06b6d4';
            },
            'label': 'data(label)',
            'width': function(ele) {
              const t = ele.data('type');
              if (t === 'actor' || t === 'entity') return 22;
              const pr = ele.data('pagerank') || 0.0;
              return 15 + Math.min(30, pr * 400);
            },
            'height': function(ele) {
              const t = ele.data('type');
              if (t === 'actor' || t === 'entity') return 22;
              const pr = ele.data('pagerank') || 0.0;
              return 15 + Math.min(30, pr * 400);
            },
            'color': '#cbd5e1',
            'font-size': '10px',
            'text-valign': 'bottom',
            'text-margin-y': '6px',
            'text-wrap': 'wrap',
            'text-max-width': '90px'
          }
        },
        {
          selector: 'node:selected',
          style: {
            'border-width': '2px',
            'border-color': '#fff',
            'background-color': '#a78bfa'
          }
        },
        {
          selector: 'edge',
          style: {
            'width': function(ele) {
              const w = ele.data('weight') || 1;
              return Math.min(6, 1 + w * 0.2);
            },
            'line-color': 'rgba(148, 163, 184, 0.3)',
            'target-arrow-color': 'rgba(148, 163, 184, 0.3)',
            'target-arrow-shape': 'triangle',
            'curve-style': 'bezier'
          }
        }
      ],
      layout: {
        name: 'cose',
        idealEdgeLength: 100,
        nodeOverlap: 20,
        refresh: 20,
        fit: true,
        padding: 30,
        randomize: false,
        componentSpacing: 100,
        nodeRepulsion: 400000,
        edgeElasticity: 100,
        nestingFactor: 5,
        gravity: 80,
        numIter: 1000,
        initialTemp: 200,
        coolingFactor: 0.95,
        minTemp: 1.0
      }
    });
    
    // Click Node Handler
    cy.on('tap', 'node', function(evt){
      const node = evt.target;
      displayNodeDetails(node.data());
    });
    
    cy.on('tap', function(evt){
      if(evt.target === cy){
        resetNodeDetails();
      }
    });
    
  } catch (e) {
    console.error("Failed to load network graph:", e);
    document.getElementById('cy').innerHTML = `<div class="loading-cell">Failed to load directed network graph.</div>`;
  }
}

function displayNodeDetails(data) {
  const panel = document.getElementById("network-node-details");
  
  if (data.type === 'actor') {
    const rawKey = data.id.substring(6);
    panel.innerHTML = `
      <div class="metric-row">
        <span class="metric-label">Actor Name</span>
        <span class="metric-value" style="font-family: inherit;">${e(data.label)}</span>
      </div>
      <div class="metric-row">
        <span class="metric-label">Type</span>
        <span class="metric-value">Threat Actor / Sender</span>
      </div>
      <div class="metric-row">
        <span class="metric-label">Unique ID / Name</span>
        <span class="metric-value" style="font-family: monospace;">${e(rawKey)}</span>
      </div>
      <div style="margin-top: 15px; text-align: center; color: #94a3b8;">
        <span class="spinner" style="font-size: 11px;">⏳ Loading node details...</span>
      </div>
    `;
    loadCadenceChart();
    
    fetch(`/api/network/node-details?id=${encodeURIComponent(data.id)}&type=actor`)
      .then(r => r.json())
      .then(details => {
        const groupsHtml = details.groups && details.groups.length > 0
          ? details.groups.map(g => `<span class="tag-chip" style="background:rgba(6,182,212,0.1);color:#22d3ee;font-size:10px;padding:2px 6px;border-radius:4px;margin-right:4px;margin-top:4px;display:inline-block;">${e(g.group_name)}</span>`).join("")
          : `<span class="muted">None</span>`;
          
        const iocsHtml = details.iocs && details.iocs.length > 0
          ? details.iocs.map(ent => `<span class="tag-chip" style="background:rgba(251,191,36,0.1);color:#fbbf24;font-size:10px;padding:2px 6px;border-radius:4px;margin-right:4px;margin-top:4px;display:inline-block;cursor:pointer;font-family:monospace;" onclick="navigator.clipboard.writeText('${e(ent.entity_value)}'); showToast('Copied to clipboard!', 'success');" title="Click to copy">${e(ent.entity_value)} (${e(ent.entity_type.toUpperCase().replace("CRYPTO_",""))})</span>`).join("")
          : `<span class="muted">None</span>`;

        panel.innerHTML = `
          <div class="metric-row">
            <span class="metric-label">Actor Name</span>
            <span class="metric-value" style="font-family: inherit;">${e(data.label)}</span>
          </div>
          <div class="metric-row">
            <span class="metric-label">Type</span>
            <span class="metric-value">Threat Actor / Sender</span>
          </div>
          <div class="metric-row">
            <span class="metric-label">Unique ID / Name</span>
            <span class="metric-value" style="font-family: monospace;">${e(rawKey)}</span>
          </div>
          <div class="metric-row">
            <span class="metric-label">Messages Posted</span>
            <span class="metric-value" style="font-weight:bold;color:#a78bfa;">${details.msg_count}</span>
          </div>
          <div class="metric-row">
            <span class="metric-label">First Seen</span>
            <span class="metric-value" style="font-size:11px;">${details.first_seen ? fmtTs(details.first_seen) : '—'}</span>
          </div>
          <div class="metric-row">
            <span class="metric-label">Last Seen</span>
            <span class="metric-value" style="font-size:11px;">${details.last_seen ? fmtTs(details.last_seen) : '—'}</span>
          </div>
          
          <div style="margin-top: 12px; border-top:1px solid rgba(255,255,255,0.06); padding-top:10px;">
            <h4 style="margin:0 0 4px 0;font-size:11px;color:#a78bfa;text-transform:uppercase;letter-spacing:0.5px;">Active In Groups</h4>
            <div style="display:flex;flex-wrap:wrap;">${groupsHtml}</div>
          </div>
          
          <div style="margin-top: 12px; border-top:1px solid rgba(255,255,255,0.06); padding-top:10px;">
            <h4 style="margin:0 0 4px 0;font-size:11px;color:#fbbf24;text-transform:uppercase;letter-spacing:0.5px;">Posted IOCs (Click to Copy)</h4>
            <div style="display:flex;flex-wrap:wrap;">${iocsHtml}</div>
          </div>
          
          <button class="btn btn-primary btn-sm" style="width:100%;margin-top:15px;justify-content:center;" onclick="pivotToMessagesSearch('${e(rawKey)}')">
            🔍 Pivot to Messages
          </button>
        `;
      });
      
  } else if (data.type === 'entity') {
    const rawVal = data.label;
    panel.innerHTML = `
      <div class="metric-row">
        <span class="metric-label">IOC Value</span>
        <span class="metric-value" style="font-family: monospace; word-break: break-all;">${e(rawVal)}</span>
      </div>
      <div class="metric-row">
        <span class="metric-label">IOC Type</span>
        <span class="metric-value">${e(data.entity_type.toUpperCase().replace("CRYPTO_", ""))}</span>
      </div>
      <div style="margin-top: 15px; text-align: center; color: #94a3b8;">
        <span class="spinner" style="font-size: 11px;">⏳ Loading node details...</span>
      </div>
    `;
    loadCadenceChart();
    
    fetch(`/api/network/node-details?id=${encodeURIComponent(data.id)}&type=entity`)
      .then(r => r.json())
      .then(details => {
        const actorsHtml = details.actors && details.actors.length > 0
          ? details.actors.map(a => `<span class="tag-chip" style="background:rgba(139,92,246,0.1);color:#a78bfa;font-size:10px;padding:2px 6px;border-radius:4px;margin-right:4px;margin-top:4px;display:inline-block;">${e(a.sender_name)}</span>`).join("")
          : `<span class="muted">None</span>`;
          
        const groupsHtml = details.groups && details.groups.length > 0
          ? details.groups.map(g => `<span class="tag-chip" style="background:rgba(6,182,212,0.1);color:#22d3ee;font-size:10px;padding:2px 6px;border-radius:4px;margin-right:4px;margin-top:4px;display:inline-block;">${e(g.group_name)}</span>`).join("")
          : `<span class="muted">None</span>`;

        panel.innerHTML = `
          <div class="metric-row">
            <span class="metric-label">IOC Value</span>
            <span class="metric-value" style="font-family: monospace; word-break: break-all;">${e(rawVal)}</span>
          </div>
          <div class="metric-row">
            <span class="metric-label">IOC Type</span>
            <span class="metric-value">${e(data.entity_type.toUpperCase().replace("CRYPTO_", ""))}</span>
          </div>
          <div class="metric-row">
            <span class="metric-label">Times Extracted</span>
            <span class="metric-value" style="font-weight:bold;color:#fbbf24;">${details.msg_count}</span>
          </div>
          <div class="metric-row">
            <span class="metric-label">First Seen</span>
            <span class="metric-value" style="font-size:11px;">${details.first_seen ? fmtTs(details.first_seen) : '—'}</span>
          </div>
          <div class="metric-row">
            <span class="metric-label">Last Seen</span>
            <span class="metric-value" style="font-size:11px;">${details.last_seen ? fmtTs(details.last_seen) : '—'}</span>
          </div>
          
          <div style="margin-top: 12px; border-top:1px solid rgba(255,255,255,0.06); padding-top:10px;">
            <h4 style="margin:0 0 4px 0;font-size:11px;color:#a78bfa;text-transform:uppercase;letter-spacing:0.5px;">Associated Senders</h4>
            <div style="display:flex;flex-wrap:wrap;">${actorsHtml}</div>
          </div>
          
          <div style="margin-top: 12px; border-top:1px solid rgba(255,255,255,0.06); padding-top:10px;">
            <h4 style="margin:0 0 4px 0;font-size:11px;color:#22d3ee;text-transform:uppercase;letter-spacing:0.5px;">Spotted In Groups</h4>
            <div style="display:flex;flex-wrap:wrap;">${groupsHtml}</div>
          </div>
          
          <button class="btn btn-primary btn-sm" style="width:100%;margin-top:15px;justify-content:center;" onclick="pivotToMessagesSearch('${e(rawVal)}')">
            🔍 Pivot to Messages
          </button>
        `;
      });
      
  } else {
    const typeText = data.type === 'source' ? 'Forward Source Channel' : 'Ingested Target Group';
    const centralityScaled = data.pagerank ? (data.pagerank * 100).toFixed(2) + '%' : '0.00%';
    
    panel.innerHTML = `
      <div class="metric-row">
        <span class="metric-label">Name</span>
        <span class="metric-value" style="font-family: inherit;">${e(data.label)}</span>
      </div>
      <div class="metric-row">
        <span class="metric-label">Type</span>
        <span class="metric-value">${typeText}</span>
      </div>
      <div class="metric-row">
        <span class="metric-label">In-degree (Forwards In)</span>
        <span class="metric-value">${data.indegree}</span>
      </div>
      <div class="metric-row">
        <span class="metric-label">Out-degree (Forwards Out)</span>
        <span class="metric-value">${data.outdegree}</span>
      </div>
      <div class="metric-row" title="PageRank centrality represents the proportional probability of message forwards routing through this channel.">
        <span class="metric-label">PageRank Centrality</span>
        <span class="metric-value">${centralityScaled}</span>
      </div>
    `;
    
    if (data.type === 'target') {
      const rawId = parseInt(data.id.substring(2));
      loadCadenceChart(rawId);
    } else {
      loadCadenceChart();
    }
  }
}


function resetNodeDetails() {
  const panel = document.getElementById("network-node-details");
  panel.innerHTML = `Select a channel or group in the graph to view centrality scores and influence statistics.`;
  loadCadenceChart();
}

let chartCadence = null;

async function loadCadenceChart(groupId = null) {
  const account = getGlobalAccountFilter();
  let url = "/api/network/cadence";
  const params = [];
  if (groupId) params.push(`group_id=${groupId}`);
  if (account) params.push(`fetched_by=${encodeURIComponent(account)}`);
  if (params.length) url += "?" + params.join("&");
  
  try {
    const data = await fetch(url).then(r => r.json());
    
    const counts = Array(24).fill(0);
    data.forEach(item => {
      const h = parseInt(item.hour);
      if (!isNaN(h) && h >= 0 && h < 24) {
        counts[h] = item.msg_count;
      }
    });
    
    const labels = Array.from({length: 24}, (_, i) => `${String(i).padStart(2, '0')}:00`);
    
    if (chartCadence) chartCadence.destroy();
    
    const ctx = document.getElementById("chart-cadence").getContext("2d");
    chartCadence = new Chart(ctx, {
      type: "bar",
      data: {
        labels: labels,
        datasets: [{
          label: "Messages",
          data: counts,
          backgroundColor: "rgba(167, 139, 250, 0.4)",
          borderColor: "#a78bfa",
          borderWidth: 1,
          borderRadius: 4
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { display: false }
        },
        scales: {
          x: { 
            ticks: { color: "#94a3b8", font: { size: 9 } }, 
            grid: { color: "#2a2a3e" } 
          },
          y: { 
            ticks: { color: "#94a3b8", font: { size: 9 } }, 
            grid: { color: "#2a2a3e" } 
          }
        }
      }
    });
  } catch (e) {
    console.error("Failed to load cadence chart:", e);
  }
}

// ── Campaigns ─────────────────────────────────────────────────────────────────
async function loadCampaigns() {
  try {
    const data = await fetch("/api/campaigns").then(r => r.json());
    renderCampaignsDeck(data);
  } catch (e) {
    console.error("Failed to load campaigns:", e);
    document.getElementById("campaigns-deck").innerHTML = `<div class="loading-cell">Failed to load active campaigns.</div>`;
  }
}

function renderCampaignsDeck(campaigns) {
  const deck = document.getElementById("campaigns-deck");
  if (!campaigns.length) {
    deck.innerHTML = `<div class="loading-cell">No campaign clusters detected yet.</div>`;
    return;
  }
  
  deck.innerHTML = campaigns.map(c => {
    const activeClass = window.selectedCampaignId === c.id ? "active" : "";
    return `
      <div class="campaign-card ${activeClass}" onclick="selectCampaign('${c.id}')" id="campaign-card-${c.id}">
        <div class="campaign-card-header">
          <span class="campaign-name">${e(c.campaign_name)}</span>
          <span class="campaign-count">${c.message_count} msgs</span>
        </div>
        <div class="campaign-rep-text">${e(c.representative_text || "")}</div>
        <div class="campaign-dates">
          <span>First: ${fmtTs(c.first_seen_at)}</span>
          <span>Last: ${fmtTs(c.last_seen_at)}</span>
        </div>
      </div>
    `;
  }).join("");
}

async function selectCampaign(campId) {
  window.selectedCampaignId = campId;
  
  // Highlight active card
  document.querySelectorAll(".campaign-card").forEach(card => card.classList.remove("active"));
  const activeCard = document.getElementById(`campaign-card-${campId}`);
  if (activeCard) activeCard.classList.add("active");
  
  const listContainer = document.getElementById("campaign-messages-list");
  listContainer.innerHTML = `<div class="loading-cell">Loading campaign messages…</div>`;
  
  try {
    const data = await fetch(`/api/campaigns/${campId}`).then(r => r.json());
    renderCampaignMessages(data.messages);
  } catch (e) {
    console.error("Failed to load campaign details:", e);
    listContainer.innerHTML = `<div class="loading-cell">Failed to load campaign messages.</div>`;
  }
}

function renderCampaignMessages(messages) {
  const container = document.getElementById("campaign-messages-list");
  if (!messages.length) {
    container.innerHTML = `<div class="loading-cell">No messages in this campaign.</div>`;
    return;
  }
  
  // Save messages globally for detail viewing if clicked
  window.currentMessages = messages;
  
  container.innerHTML = messages.map((m, index) => {
    const entsHtml = (m.entities || []).map(ent => {
      const isSanc = ent.is_sanctioned ? "hl-sanctioned" : "";
      return `<span class="entity-badge ${isSanc}" title="${ent.entity_type}">${e(ent.entity_value)}</span>`;
    }).join(" ");
    
    return `
      <div class="campaign-msg-item clickable-msg" onclick="openCampaignMessageDetail(${index})" style="cursor: pointer; margin-bottom: 10px;">
        <div class="campaign-msg-header">
          <span>📅 ${fmtTs(m.timestamp)} | 👥 ${e(m.group_name)} | 👤 ${e(m.sender_name)}${m.sender_id ? ` (${m.sender_id})` : ""}</span>
          <span>${m.language || "?"}</span>
        </div>
        <div class="campaign-msg-text">${e(m.text)}</div>
        ${entsHtml ? `<div style="margin-top: 8px; display: flex; flex-wrap: wrap; gap: 4px;">${entsHtml}</div>` : ""}
      </div>
    `;
  }).join("");
}

function openCampaignMessageDetail(index) {
  openMessageDetail(index);
}

async function findSimilarImages() {
  const m = window.currentMessages[window.currentMessageIndex];
  if (!m || !window.currentMessagePhash) return;
  
  const container = document.getElementById("modal-similar-images-container");
  const list = document.getElementById("modal-similar-images-list");
  
  if (container) container.style.display = "block";
  if (list) list.innerHTML = `<div class="loading-cell">Searching for similar images…</div>`;
  
  try {
    const data = await fetch(`/api/media/similar?phash=${window.currentMessagePhash}`).then(r => r.json());
    
    // Filter out the current message itself from results
    const filtered = data.filter(res => res.message_id !== m.message_id || res.group_id !== m.group_id);
    
    if (!filtered.length) {
      if (list) list.innerHTML = `<div class="muted" style="text-align: center; padding: 6px 0; font-size: 11px;">No matching similar image campaigns found.</div>`;
      return;
    }
    
    if (list) {
      list.innerHTML = filtered.map(res => `
        <div class="similar-img-item" style="margin-top: 4px;">
          <span class="similar-img-meta">📅 ${fmtTs(res.timestamp)} | 👥 ${e(res.group_name)}</span>
          <span class="similar-img-dist">Distance: ${res.distance}</span>
        </div>
      `).join("");
    }
  } catch (e) {
    console.error("Failed to find similar images:", e);
    if (list) list.innerHTML = `<div class="loading-cell">Search failed.</div>`;
  }
}

function showToast(msg) {
  const container = document.getElementById("toast-container");
  if (!container) {
    alert(msg);
    return;
  }
  const toast = document.createElement("div");
  toast.className = "toast";
  toast.textContent = msg;
  container.appendChild(toast);
  setTimeout(() => toast.classList.add("show"), 10);
  setTimeout(() => {
    toast.classList.remove("show");
    setTimeout(() => toast.remove(), 300);
  }, 3000);
}

// ── Actor Profiles (Phase 5) ──────────────────────────────────────────────────
let chartActorTimezone = null;
let chartActorSpecialties = null;
window.selectedActorId = null;


async function loadActors() {
  const deck = document.getElementById("actors-list-deck");
  if (!deck) return;
  deck.innerHTML = `<div class="loading-cell">Loading actor profiles…</div>`;
  try {
    const account = getGlobalAccountFilter();
    const url = account ? `/api/actors/high-risk?fetched_by=${encodeURIComponent(account)}` : "/api/actors/high-risk";
    const actors = await fetch(url).then(r => r.json());
    if (!actors.length) {
      deck.innerHTML = `<div class="loading-cell">No high-risk actor profiles found.</div>`;
      return;
    }
    window.currentActors = actors;
    deck.innerHTML = actors.map((a, idx) => {
      const activeClass = window.selectedActorId === a.sender_id ? "active" : "";
      return `
        <div class="actor-card ${activeClass}" onclick="selectActor(${idx})" id="actor-card-${idx}">
          <div class="actor-card-header">
            <span class="actor-name">${e(a.sender_id)}</span>
            ${getRiskBadge(a.risk_tier)}
          </div>
          <div class="actor-meta">
            <span>📨 Messages: ${a.total_messages}</span>
            <span>🔥 Risk: ${a.cumulative_risk.toFixed(0)}</span>
          </div>
        </div>
      `;
    }).join("");
  } catch (e) {
    console.error("Failed to load high-risk actors:", e);
    deck.innerHTML = `<div class="loading-cell">Failed to load actors.</div>`;
  }
}

async function selectActor(idx) {
  const a = window.currentActors[idx];
  if (!a) return;
  window.selectedActorId = a.sender_id;

  // Highlight card
  document.querySelectorAll(".actor-card").forEach(c => c.classList.remove("active"));
  const activeCard = document.getElementById(`actor-card-${idx}`);
  if (activeCard) activeCard.classList.add("active");

  const placeholder = document.getElementById("actor-detail-placeholder");
  const content = document.getElementById("actor-detail-content");
  if (placeholder) placeholder.style.display = "none";
  if (content) content.style.display = "block";

  document.getElementById("actor-profile-title").textContent = a.sender_id;
  document.getElementById("actor-profile-phone").textContent = a.sender_phone || "None";
  document.getElementById("actor-profile-total").textContent = a.total_messages;
  document.getElementById("actor-profile-avgrisk").textContent = a.average_risk.toFixed(1);
  document.getElementById("actor-profile-cumrisk").textContent = a.cumulative_risk.toFixed(1);

  // Clear fingerprint elements with loading text
  document.getElementById("bf-op-mode").textContent = "Loading...";
  document.getElementById("bf-group-count").textContent = "Loading...";
  document.getElementById("bf-urgency").textContent = "Loading...";
  document.getElementById("bf-media").textContent = "Loading...";
  document.getElementById("actor-timezone-inference").textContent = "Analyzing operational timezone...";

  const listContainer = document.getElementById("actor-messages-list");
  listContainer.innerHTML = `<div class="loading-cell">Loading actor messages…</div>`;

  try {
    const data = await fetch(`/api/messages?sender_name=${encodeURIComponent(a.sender_id)}&page_size=100`).then(r => r.json());
    renderActorMessages(data.messages);
    renderActorTimezoneChart(data.messages);
    
    // Fetch behavior fingerprint
    const behavior = await fetch(`/api/actors/behavior?id=${encodeURIComponent(a.sender_id)}`).then(r => r.json());
    renderActorBehaviorFingerprint(behavior);
  } catch (e) {
    console.error("Failed to load actor messages:", e);
    listContainer.innerHTML = `<div class="loading-cell">Failed to load messages.</div>`;
  }
}

function renderActorBehaviorFingerprint(behavior) {
  if (!behavior) return;

  document.getElementById("bf-op-mode").textContent = behavior.op_mode;
  document.getElementById("bf-group-count").textContent = behavior.group_count;
  document.getElementById("bf-urgency").textContent = (behavior.urgency_bias || 0).toFixed(1) + "%";
  document.getElementById("bf-media").textContent = (behavior.media_ratio || 0).toFixed(1) + "%";
  document.getElementById("actor-timezone-inference").textContent = behavior.timezone_inference || "";

  const cats = behavior.categories || {};
  const labels = Object.keys(cats);
  const data = Object.values(cats);

  if (chartActorSpecialties) chartActorSpecialties.destroy();

  const ctx = document.getElementById("actor-specialties-chart").getContext("2d");
  
  if (labels.length === 0) {
    labels.push("Benign / Unclassified");
    data.push(1);
  }

  const borderColors = {
    "Scam/Fraud": "#3b82f6",
    "Weapons/Violent Extremism": "#ef4444",
    "Cybersecurity/Hacking": "#10b981",
    "Financial Crimes/Money Mule": "#fbbf24",
    "Drug Trafficking": "#ec4899",
    "Legitimate": "#6b7280",
    "Benign": "#6b7280"
  };
  const backgroundColors = {
    "Scam/Fraud": "rgba(59, 130, 246, 0.4)",
    "Weapons/Violent Extremism": "rgba(239, 68, 68, 0.4)",
    "Cybersecurity/Hacking": "rgba(16, 185, 129, 0.4)",
    "Financial Crimes/Money Mule": "rgba(251, 191, 36, 0.4)",
    "Drug Trafficking": "rgba(236, 72, 153, 0.4)",
    "Legitimate": "rgba(107, 114, 128, 0.4)",
    "Benign": "rgba(107, 114, 128, 0.4)"
  };

  const bgCols = labels.map(l => backgroundColors[l] || "rgba(167, 139, 250, 0.4)");
  const borderCols = labels.map(l => borderColors[l] || "#a78bfa");

  chartActorSpecialties = new Chart(ctx, {
    type: "doughnut",
    data: {
      labels: labels,
      datasets: [{
        data: data,
        backgroundColor: bgCols,
        borderColor: borderCols,
        borderWidth: 1
      }]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: {
          position: "right",
          labels: {
            color: "#94a3b8",
            font: { size: 9 },
            boxWidth: 8
          }
        }
      }
    }
  });
}


// ── OSINT Dossier ─────────────────────────────────────────────────────────────
async function pullActorDossier() {
  if (!window.selectedActorId) {
    showToast("Please select an actor first.", "warning");
    return;
  }

  const btn = document.getElementById("btn-pull-dossier");
  const panel = document.getElementById("actor-dossier-panel");
  const loading = document.getElementById("dossier-loading");
  const tgSection = document.getElementById("dossier-tg-profile");
  const iocSection = document.getElementById("dossier-ioc-panel");
  const pivotsSection = document.getElementById("dossier-pivots-panel");

  // Show panel in loading state
  panel.style.display = "block";
  loading.style.display = "block";
  tgSection.style.display = "none";
  iocSection.style.display = "none";
  pivotsSection.style.display = "none";
  btn.textContent = "⏳ Loading...";
  btn.disabled = true;

  try {
    const actorName = encodeURIComponent(window.selectedActorId);
    const url = `/api/actors/dossier?id=${actorName}&name=${actorName}`;
    const data = await fetch(url).then(r => r.json());
    loading.style.display = "none";
    renderActorDossier(data);
  } catch (err) {
    loading.textContent = `❌ Failed to fetch dossier: ${err.message}`;
    console.error("Dossier fetch failed:", err);
  } finally {
    btn.textContent = "🔄 Refresh Dossier";
    btn.disabled = false;
  }
}

function renderActorDossier(data) {
  const tgProfile = data.telegram_profile || {};
  const dbIntel = data.db_intel || {};
  const pivots = data.osint_pivots || [];

  // ── Telegram Profile ────────────────────────────────────────────────────
  const tgSection = document.getElementById("dossier-tg-profile");
  tgSection.style.display = "block";

  const fullName = [tgProfile.first_name, tgProfile.last_name].filter(Boolean).join(" ") || "—";
  document.getElementById("d-fullname").textContent = fullName;
  document.getElementById("d-username").textContent = tgProfile.username ? `@${tgProfile.username}` : "—";
  document.getElementById("d-status").textContent = tgProfile.status || "—";
  document.getElementById("d-userid").textContent = tgProfile.tg_user_id || "—";

  const phoneEl = document.getElementById("d-phone");
  if (tgProfile.phone) {
    phoneEl.textContent = tgProfile.phone;
    phoneEl.style.color = "#4ade80";
  } else {
    phoneEl.textContent = "Hidden / Not Resolved";
    phoneEl.style.color = "#f59e0b";
  }

  const acctFlags = [];
  if (tgProfile.is_bot) acctFlags.push("🤖 Bot");
  else acctFlags.push("👤 Human");
  if (tgProfile.is_verified) acctFlags.push("✅ Verified");
  if (tgProfile.is_restricted) acctFlags.push("🚫 Restricted");
  document.getElementById("d-acct-type").textContent = acctFlags.join(" · ") || "—";

  const bioRow = document.getElementById("d-bio-row");
  if (tgProfile.bio) {
    document.getElementById("d-bio").textContent = tgProfile.bio;
    bioRow.style.display = "block";
  } else {
    bioRow.style.display = "none";
  }

  const privNote = document.getElementById("d-privacy-note");
  if (tgProfile.privacy_note) {
    privNote.textContent = `⚠️ ${tgProfile.privacy_note}`;
    privNote.style.display = "block";
  } else {
    privNote.style.display = "none";
  }

  // ── IOC Intelligence ────────────────────────────────────────────────────
  const iocSection = document.getElementById("dossier-ioc-panel");
  let hasIoc = false;

  function renderChips(containerId, rowId, items, color, copyable = true) {
    const row = document.getElementById(rowId);
    if (items && items.length > 0) {
      document.getElementById(containerId).innerHTML = items.map(v =>
        `<span class="tag-chip" style="background:${color}1a;color:${color};font-size:11px;padding:2px 8px;border-radius:4px;font-family:monospace;cursor:${copyable ? 'pointer' : 'default'};"
          ${copyable ? `onclick="navigator.clipboard.writeText('${e(v)}'); showToast('Copied!', 'success');" title="Click to copy"` : ''}>${e(v)}</span>`
      ).join("");
      row.style.display = "block";
      hasIoc = true;
    } else {
      row.style.display = "none";
    }
  }

  renderChips("d-phones", "d-phones-row", dbIntel.phones_posted, "#4ade80");
  renderChips("d-upi", "d-upi-row", dbIntel.upi_posted, "#fbbf24");
  renderChips("d-emails", "d-email-row", dbIntel.emails_posted, "#22d3ee");

  // Crypto — richer display
  const cryptoRow = document.getElementById("d-crypto-row");
  const cryptoContainer = document.getElementById("d-crypto");
  if (dbIntel.crypto_posted && dbIntel.crypto_posted.length > 0) {
    cryptoContainer.innerHTML = dbIntel.crypto_posted.map(w => {
      const sanctionBadge = w.is_sanctioned ? `<span style="color:#ef4444; font-size:10px; font-weight:bold; margin-left:6px;">⚠️ SANCTIONED (${e(w.sanction_source || '')})</span>` : "";
      const balText = w.balance != null ? `  |  Balance: ${parseFloat(w.balance).toFixed(6)}` : "";
      return `<div style="background:rgba(251,191,36,0.06); padding:6px 10px; border-radius:6px; border-left:3px solid #f59e0b; font-size:11px; cursor:pointer;"
        onclick="navigator.clipboard.writeText('${e(w.entity_value)}'); showToast('Copied!', 'success');" title="Click to copy">
        <span style="color:#f59e0b; font-weight:bold;">${e(w.entity_type.toUpperCase().replace("CRYPTO_",""))}</span>&nbsp;
        <span style="font-family:monospace; color:#e2e8f0;">${e(w.entity_value)}</span>${balText}${sanctionBadge}
      </div>`;
    }).join("");
    cryptoRow.style.display = "block";
    hasIoc = true;
  } else {
    cryptoRow.style.display = "none";
  }

  iocSection.style.display = hasIoc ? "block" : "none";

  // ── OSINT Pivot Links ───────────────────────────────────────────────────
  const pivotsSection = document.getElementById("dossier-pivots-panel");
  const pivotsContainer = document.getElementById("d-pivots");
  if (pivots.length > 0) {
    pivotsContainer.innerHTML = pivots.map(p =>
      `<a href="${p.url}" target="_blank" rel="noopener noreferrer" class="btn btn-sm btn-ghost" style="font-size:11px; padding:3px 10px; color:#22d3ee; border-color:rgba(34,211,238,0.3);">↗ ${e(p.label)}</a>`
    ).join("");
    pivotsSection.style.display = "block";
  } else {
    pivotsSection.style.display = "none";
  }
}


function renderActorMessages(messages) {

  const container = document.getElementById("actor-messages-list");
  if (!messages || !messages.length) {
    container.innerHTML = `<div class="loading-cell">No message data available for this actor.</div>`;
    return;
  }
  
  // Set current messages for click viewing
  window.currentMessages = messages;

  container.innerHTML = messages.map((m, index) => {
    const isHit = m.is_matched;
    const entsHtml = (m.entities || []).map(ent => {
      const isSanc = ent.is_sanctioned ? "hl-sanctioned" : "";
      return `<span class="entity-badge ${isSanc}">${e(ent.entity_value)}</span>`;
    }).join(" ");

    return `
      <div class="campaign-msg-item clickable-msg" onclick="openActorMessageDetail(${index})" style="cursor: pointer; margin-bottom: 8px;">
        <div class="campaign-msg-header">
          <span>📅 ${fmtTs(m.timestamp)} | 👥 ${e(m.group_name)}</span>
          ${getRiskScoreBadge(m.risk_score)}
        </div>
        <div class="campaign-msg-text">${e(m.text)}</div>
        ${entsHtml ? `<div style="margin-top: 6px; display: flex; flex-wrap: wrap; gap: 4px;">${entsHtml}</div>` : ""}
      </div>
    `;
  }).join("");
}

function renderActorTimezoneChart(messages) {
  const hourCounts = Array(24).fill(0);
  messages.forEach(m => {
    try {
      const date = new Date(m.timestamp);
      const h = date.getHours();
      if (!isNaN(h) && h >= 0 && h < 24) {
        hourCounts[h]++;
      }
    } catch(e) {}
  });

  const labels = Array.from({length: 24}, (_, i) => `${String(i).padStart(2, '0')}:00`);

  if (chartActorTimezone) chartActorTimezone.destroy();

  const ctx = document.getElementById("actor-timezone-chart").getContext("2d");
  chartActorTimezone = new Chart(ctx, {
    type: "bar",
    data: {
      labels: labels,
      datasets: [{
        label: "Messages Posted",
        data: hourCounts,
        backgroundColor: "rgba(249, 115, 22, 0.4)",
        borderColor: "#f97316",
        borderWidth: 1,
        borderRadius: 4
      }]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: { legend: { display: false } },
      scales: {
        x: { ticks: { color: "#94a3b8", font: { size: 9 } }, grid: { color: "#2a2a3e" } },
        y: { ticks: { color: "#94a3b8", font: { size: 9 } }, grid: { color: "#2a2a3e" } }
      }
    }
  });
}

function openActorMessageDetail(index) {
  openMessageDetail(index);
}

function getRiskScoreBadge(score) {
  if (score == null) return "—";
  let tier = "Low";
  if (score >= 80) tier = "Critical";
  else if (score >= 60) tier = "High";
  else if (score >= 30) tier = "Medium";
  return `<span class="risk-badge risk-${tier.toLowerCase()}">${score.toFixed(0)}</span>`;
}

function getRiskBadge(tier) {
  const t = (tier || "Low").toLowerCase();
  return `<span class="risk-badge risk-${t}">${tier || 'Low'}</span>`;
}

// ── Cases & Watchlists (Phase 6) ──────────────────────────────────────────────
window.currentCases = [];
window.selectedCaseId = null;

async function populateCaseDropdownInModal() {
  const select = document.getElementById("modal-case-select");
  if (!select) return;
  try {
    const cases = await fetch("/api/cases").then(r => r.json());
    select.innerHTML = cases.map(c => `<option value="${c.id}">${e(c.title)}</option>`).join("");
    if (!cases.length) {
      select.innerHTML = `<option value="">No cases active</option>`;
    }
  } catch (e) {
    console.error("Failed to populate case dropdown in modal:", e);
  }
}

async function addCurrentMessageToCase() {
  const select = document.getElementById("modal-case-select");
  if (!select || !window.currentMessageId) return;
  const caseId = select.value;
  if (!caseId) {
    showToast("Please create a case folder first!");
    return;
  }
  
  try {
    const res = await fetch(`/api/cases/${caseId}/items`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ item_type: "message", item_value: window.currentMessageId })
    }).then(r => r.json());
    
    if (res.status === "item_added") {
      showToast("Message added to case successfully!");
    } else {
      showToast("Failed to add message to case.");
    }
  } catch (e) {
    console.error(e);
    showToast("Error adding to case.");
  }
}

async function loadCasesAndWatchlists() {
  try {
    const [cases, watchlists] = await Promise.all([
      fetch("/api/cases").then(r => r.json()),
      fetch("/api/watchlists").then(r => r.json())
    ]);
    renderCasesDeck(cases);
    renderWatchlistsDeck(watchlists);
  } catch (e) {
    console.error("Failed to load Cases/Watchlists:", e);
  }
}

function renderCasesDeck(cases) {
  const deck = document.getElementById("cases-list-deck");
  if (!deck) return;
  window.currentCases = cases;
  
  if (!cases.length) {
    deck.innerHTML = `<div class="loading-cell" style="font-size:12px;">No active investigation cases.</div>`;
    return;
  }
  
  deck.innerHTML = cases.map((c, idx) => {
    const activeClass = window.selectedCaseId === c.id ? "active" : "";
    return `
      <div class="actor-card ${activeClass}" onclick="selectCase(${idx})" id="case-card-${idx}">
        <div class="actor-card-header">
          <span class="actor-name">📂 ${e(c.title)}</span>
        </div>
        <div class="actor-meta">
          <span>Created: ${fmtTs(c.created_at).substring(0, 10)}</span>
        </div>
      </div>
    `;
  }).join("");
}

function renderWatchlistsDeck(watchlists) {
  const deck = document.getElementById("watchlists-list-deck");
  
  // Populate preset dropdown in messages tab
  const presetDropdown = document.getElementById("filter-watchlist-preset");
  if (presetDropdown) {
    presetDropdown.innerHTML = '<option value="">-- Select Watchlist --</option>';
    watchlists.forEach(w => {
      const opt = document.createElement("option");
      opt.value = JSON.stringify(w.query_params);
      opt.textContent = w.name;
      presetDropdown.appendChild(opt);
    });
  }

  if (!deck) return;
  
  if (!watchlists.length) {
    deck.innerHTML = `<div class="loading-cell" style="font-size:12px;">No saved query watchlists.</div>`;
    return;
  }
  
  deck.innerHTML = watchlists.map(w => {
    const paramsStr = JSON.stringify(w.query_params);
    return `
      <div class="actor-card" onclick='runSavedWatchlist(${paramsStr})' style="position: relative;">
        <div class="actor-card-header">
          <span class="actor-name">🔍 ${e(w.name)}</span>
          <button class="btn btn-sm btn-ghost" onclick="deleteWatchlist('${w.id}', event)" style="padding: 2px 6px; color:#ef4444; border:0; background:transparent;">✕</button>
        </div>
        <div class="actor-meta">
          <span>Params: ${e(w.query_params.keyword || "All keywords")}</span>
        </div>
      </div>
    `;
  }).join("");
}

async function selectCase(idx) {
  const c = window.currentCases[idx];
  if (!c) return;
  window.selectedCaseId = c.id;
  
  document.querySelectorAll("[id^='case-card-']").forEach(card => card.classList.remove("active"));
  const activeCard = document.getElementById(`case-card-${idx}`);
  if (activeCard) activeCard.classList.add("active");
  
  document.getElementById("case-detail-placeholder").style.display = "none";
  document.getElementById("case-detail-content").style.display = "block";
  
  document.getElementById("case-profile-title").textContent = c.title;
  document.getElementById("case-profile-date").textContent = `Established: ${fmtTs(c.created_at)}`;
  document.getElementById("case-profile-desc").textContent = c.description || "No description provided.";
  
  const listContainer = document.getElementById("case-items-list");
  listContainer.innerHTML = `<div class="loading-cell">Loading compiled inventory…</div>`;
  
  try {
    const data = await fetch(`/api/cases/${c.id}`).then(r => r.json());
    renderCaseItems(data.items);
  } catch (e) {
    console.error(e);
    listContainer.innerHTML = `<div class="loading-cell">Failed to load case items.</div>`;
  }
}

function renderCaseItems(items) {
  const container = document.getElementById("case-items-list");
  if (!items || !items.length) {
    container.innerHTML = `<div class="loading-cell">No items cataloged inside this folder. Add messages from detail modals or assign wallets.</div>`;
    return;
  }
  
  container.innerHTML = items.map((item, index) => {
    let detailsHtml = "";
    if (item.item_type === "message" && item.message_details) {
      const m = item.message_details;
      detailsHtml = `
        <div style="font-size: 12px; color: #fff; margin-top: 4px;">"${e(m.text)}"</div>
        <div style="font-size: 11px; color: #94a3b8; margin-top: 2px;">Posted inside <strong>${e(m.group_name)}</strong> by <strong>${e(m.sender_name)}</strong>${m.sender_id ? ` <span class="muted" style="font-size:10px;">(${m.sender_id})</span>` : ""}</div>
      `;
    } else {
      detailsHtml = `<div style="font-size: 12px; color: #fff; margin-top: 4px; font-family: monospace;">${e(item.item_value)}</div>`;
    }
    
    return `
      <div class="campaign-msg-item" style="display: flex; justify-content: space-between; align-items: center; gap: 15px; margin-bottom: 8px;">
        <div style="flex: 1;">
          <div style="display: flex; gap: 8px; align-items: center;">
            <span class="kw-badge" style="text-transform: uppercase;">${item.item_type}</span>
            <span style="font-size: 11px; color: #94a3b8;">Added: ${fmtTs(item.added_at)}</span>
          </div>
          ${detailsHtml}
        </div>
        <button class="btn btn-sm btn-ghost" onclick="removeCaseItem(${item.id})" style="color: #ef4444; border-color: rgba(239,68,68,0.15);">Remove</button>
      </div>
    `;
  }).join("");
}

async function promptCreateCase() {
  const title = prompt("Enter Case Title:");
  if (!title) return;
  const desc = prompt("Enter Case Description:");
  const id = "case_" + Math.random().toString(36).substring(2, 9);
  
  try {
    const res = await fetch("/api/cases", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ id: id, title: title, description: desc })
    }).then(r => r.json());
    
    if (res.status === "created") {
      showToast("Case created successfully!");
      loadCasesAndWatchlists();
    }
  } catch (e) {
    console.error(e);
    showToast("Error creating case.");
  }
}

async function deleteCurrentCase() {
  if (!window.selectedCaseId) return;
  if (!confirm("Are you sure you want to delete this case? All saved associations will be lost.")) return;
  
  try {
    await fetch(`/api/cases/${window.selectedCaseId}`, { method: "DELETE" }).then(r => r.json());
    showToast("Case deleted successfully.");
    window.selectedCaseId = null;
    document.getElementById("case-detail-content").style.display = "none";
    document.getElementById("case-detail-placeholder").style.display = "block";
    loadCasesAndWatchlists();
  } catch (e) {
    console.error(e);
    showToast("Failed to delete case.");
  }
}

async function removeCaseItem(itemId) {
  if (!itemId) return;
  try {
    await fetch(`/api/cases/items/${itemId}`, { method: "DELETE" }).then(r => r.json());
    showToast("Item removed from case.");
    
    // Refresh case display
    const idx = window.currentCases.findIndex(c => c.id === window.selectedCaseId);
    if (idx !== -1) {
      selectCase(idx);
    }
  } catch (e) {
    console.error(e);
    showToast("Failed to remove item.");
  }
}

function downloadCaseBriefing() {
  if (!window.selectedCaseId) return;
  const url = `/api/cases/${window.selectedCaseId}/report`;
  window.open(url, "_blank");
}

async function saveCurrentWatchlist() {
  const kw = getFilterValue("filter-keyword");
  const grp = getFilterValue("filter-group");
  const dateFrom = document.getElementById("filter-date-from").value;
  const timeFrom = document.getElementById("filter-time-from").value;
  const dateTo = document.getElementById("filter-date-to").value;
  const timeTo = document.getElementById("filter-time-to").value;
  const hitsOnly = document.getElementById("filter-matched-only").checked;
  
  if (!kw && !grp && !dateFrom && !dateTo && !hitsOnly) {
    showToast("Please choose some query filters before saving watchlists!");
    return;
  }
  
  const name = prompt("Enter a friendly name for this saved query watchlist:");
  if (!name) return;
  
  const wid = "wl_" + Math.random().toString(36).substring(2, 9);
  const params = {
    keyword: kw,
    group_id: grp,
    date_from: dateFrom,
    time_from: timeFrom,
    date_to: dateTo,
    time_to: timeTo,
    matched_only: hitsOnly
  };
  
  try {
    const res = await fetch("/api/watchlists", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ id: wid, name: name, query_params: params })
    }).then(r => r.json());
    
    if (res.status === "saved") {
      showToast("Watchlist saved successfully!");
      if (document.getElementById("section-cases").classList.contains("active")) {
        loadCasesAndWatchlists();
      }
    }
  } catch (e) {
    console.error(e);
    showToast("Failed to save watchlist.");
  }
}

function runSavedWatchlist(params) {
  setFilterValue("filter-keyword", params.keyword || "");
  setFilterValue("filter-group", params.group_id || "");
  document.getElementById("filter-date-from").value = params.date_from || "";
  document.getElementById("filter-time-from").value = params.time_from || "";
  document.getElementById("filter-date-to").value = params.date_to || "";
  document.getElementById("filter-time-to").value = params.time_to || "";
  document.getElementById("filter-matched-only").checked = !!params.matched_only;
  
  showSection("messages");
  loadMessages(1);
}

function loadWatchlistPreset(paramsStr) {
  if (!paramsStr) return;
  try {
    const params = JSON.parse(paramsStr);
    runSavedWatchlist(params);
  } catch(e) {
    console.error("Failed to parse watchlist preset:", e);
  }
}

async function deleteWatchlist(wid, event) {
  if (event) event.stopPropagation();
  if (!wid) return;
  if (!confirm("Are you sure you want to delete this saved watchlist query?")) return;
  
  try {
    await fetch(`/api/watchlists/${wid}`, { method: "DELETE" }).then(r => r.json());
    showToast("Watchlist deleted.");
    loadCasesAndWatchlists();
  } catch (e) {
    console.error(e);
    showToast("Failed to delete watchlist.");
  }
}


// ── Ingestion Control Center & Multi-Account Setup ─────────────────────────────
let pipelineStatus = { is_fetching: true, accounts: [] };

async function loadPipelineStatus() {
  try {
    const res = await fetch("/api/pipeline/status").then(r => r.json());
    pipelineStatus = res;
    
    // Update fetching switch
    const runStatusLabel = document.getElementById("pipeline-run-status");
    const toggleBtn = document.getElementById("btn-toggle-pipeline");
    
    if (res.is_fetching) {
      runStatusLabel.textContent = "RUNNING";
      runStatusLabel.style.color = "#10b981";
      toggleBtn.textContent = "Stop Ingestion";
      toggleBtn.className = "btn btn-sm btn-danger";
    } else {
      runStatusLabel.textContent = "STOPPED";
      runStatusLabel.style.color = "#ef4444";
      toggleBtn.textContent = "Start Ingestion";
      toggleBtn.className = "btn btn-sm btn-success";
    }

    // Render accounts cards
    const deck = document.getElementById("pipeline-accounts-deck");
    if (!res.accounts || !res.accounts.length) {
      deck.innerHTML = `
        <div class="loading-cell" style="grid-column: 1/-1; padding: 20px; text-align: center; border: 1px dashed rgba(255,255,255,0.1); border-radius: 6px;">
          No Telegram accounts configured. Click "+ Add Telegram Account" to configure one.
        </div>`;
      return;
    }

    deck.innerHTML = res.accounts.map(acc => {
      let statusColor = "#94a3b8"; // disconnected
      let statusLabel = "Disconnected";
      let btnHtml = "";

      if (acc.status === "connected") {
        statusColor = "#10b981";
        statusLabel = "Connected";
      } else if (acc.status === "needs_otp") {
        statusColor = "#f97316";
        statusLabel = "Needs Verification";
        btnHtml = `<button class="btn btn-sm btn-warning" onclick="showVerifyOtpModal('${acc.phone}')" style="margin-right: 8px; padding: 4px 8px;">Verify Code</button>`;
      }

      return `
        <div class="glass-card" style="padding: 15px; background: rgba(0,0,0,0.3); border: 1px solid rgba(255,255,255,0.08); display: flex; flex-direction: column; justify-content: space-between; gap: 10px;">
          <div>
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 5px;">
              <span style="font-size: 14px; font-weight: bold; color: #fff;">${e(acc.phone)}</span>
              <span style="display: inline-flex; align-items: center; gap: 6px; font-size: 11px; color: ${statusColor}; font-weight: bold;">
                <span style="width: 8px; height: 8px; border-radius: 50%; background: ${statusColor}; display: inline-block;"></span>
                ${statusLabel}
              </span>
            </div>
            <div style="font-size: 11px; color: #94a3b8; font-family: monospace;">
              <div>API ID: ${acc.api_id}</div>
            </div>
          </div>
          <div style="display: flex; justify-content: space-between; align-items: center; border-top: 1px solid rgba(255,255,255,0.05); padding-top: 10px; margin-top: 5px;">
            <label style="display: inline-flex; align-items: center; gap: 6px; font-size: 11px; color: #cbd5e1; cursor: pointer; user-select: none;">
              <input type="checkbox" ${acc.is_active === 1 ? 'checked' : ''} onchange="toggleAccountActive('${acc.phone}', this.checked)" style="cursor: pointer;">
              Active Ingestion
            </label>
            <div>
              ${btnHtml}
              <button class="btn btn-sm btn-ghost" onclick="deleteAccount('${acc.phone}')" style="color: #ef4444; padding: 4px 8px;">Remove</button>
            </div>
          </div>
        </div>`;
    }).join("");
    loadAccountsIntoFilterDropdown();
  } catch (err) {
    console.error(err);
  }
}

async function toggleAccountActive(phone, isChecked) {
  const isActive = isChecked ? 1 : 0;
  try {
    showToast(isChecked ? "Connecting account..." : "Disconnecting account...");
    const res = await fetch("/api/pipeline/accounts/toggle", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ phone, is_active: isActive })
    }).then(r => r.json());

    if (res.error) {
      showToast(res.error, "error");
      loadPipelineStatus();
    } else {
      showToast(isChecked ? "Account activated." : "Account deactivated.");
      loadPipelineStatus();
      if (res.status === "needs_otp") {
        showVerifyOtpModal(phone);
      }
    }
  } catch (err) {
    console.error(err);
    showToast("Error updating account active status.", "error");
    loadPipelineStatus();
  }
}

async function togglePipelineFetching() {
  const nextState = !pipelineStatus.is_fetching;
  try {
    const res = await fetch("/api/pipeline/toggle", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ enabled: nextState })
    }).then(r => r.json());
    
    if (res.error) {
      showToast(res.error, "error");
    } else {
      showToast(nextState ? "Ingestion resumed." : "Ingestion stopped.");
      loadPipelineStatus();
    }
  } catch (err) {
    console.error(err);
    showToast("Error toggling pipeline fetching state.", "error");
  }
}

function showAddAccountModal() {
  document.getElementById("acc-phone").value = "";
  document.getElementById("acc-api-id").value = "";
  document.getElementById("acc-api-hash").value = "";
  document.getElementById("add-account-modal").style.display = "flex";
}

function hideAddAccountModal() {
  document.getElementById("add-account-modal").style.display = "none";
}

async function submitAddAccount() {
  const phone = document.getElementById("acc-phone").value.trim();
  const api_id = document.getElementById("acc-api-id").value.trim();
  const api_hash = document.getElementById("acc-api-hash").value.trim();
  
  if (!phone || !api_id || !api_hash) {
    showToast("Please fill in all configuration parameters.", "error");
    return;
  }

  try {
    showToast("Initiating connection request...");
    const res = await fetch("/api/pipeline/accounts", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ phone, api_id, api_hash })
    }).then(r => r.json());

    if (res.error) {
      showToast(res.error, "error");
    } else {
      hideAddAccountModal();
      loadPipelineStatus();
      if (res.status === "needs_otp") {
        showVerifyOtpModal(phone);
      } else {
        showToast("Account successfully registered & connected!");
      }
    }
  } catch (err) {
    console.error(err);
    showToast("Failed to connect Telegram client session.", "error");
  }
}

function showVerifyOtpModal(phone) {
  document.getElementById("verify-phone-label").textContent = phone;
  document.getElementById("acc-otp-code").value = "";
  document.getElementById("verify-otp-modal").style.display = "flex";
}

function hideVerifyOtpModal() {
  document.getElementById("verify-otp-modal").style.display = "none";
}

async function submitVerifyOtp() {
  const phone = document.getElementById("verify-phone-label").textContent;
  const code = document.getElementById("acc-otp-code").value.trim();

  if (!code) {
    showToast("Please enter the verification code.", "error");
    return;
  }

  try {
    showToast("Verifying code...");
    const res = await fetch("/api/pipeline/accounts/verify", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ phone, code })
    }).then(r => r.json());

    if (res.error) {
      showToast(res.error, "error");
    } else if (res.status === "connected") {
      hideVerifyOtpModal();
      showToast("OTP Verification successful! Session is now live.");
      loadPipelineStatus();
    } else {
      showToast("Failed verification: " + JSON.stringify(res), "error");
    }
  } catch (err) {
    console.error(err);
    showToast("Failed to verify SMS code.", "error");
  }
}

async function deleteAccount(phone) {
  if (!confirm(`Are you sure you want to remove the session for ${phone}?`)) return;

  try {
    const res = await fetch(`/api/pipeline/accounts/${encodeURIComponent(phone)}`, {
      method: "DELETE"
    }).then(r => r.json());

    if (res.status === "deleted") {
      showToast("Account configuration removed successfully.");
      loadPipelineStatus();
    } else {
      showToast("Error unregistering account.", "error");
    }
  } catch (err) {
    console.error(err);
    showToast("Failed to remove account.", "error");
  }
}

function getGlobalAccountFilter() {
  const el = document.getElementById("filter-global-account");
  return el ? el.value : "";
}

async function loadAccountsIntoFilterDropdown() {
  try {
    const res = await fetch("/api/pipeline/status").then(r => r.json());
    const dropdown = document.getElementById("filter-global-account");
    if (!dropdown) return;

    const currentValue = dropdown.value;

    // Reset dropdown
    dropdown.innerHTML = '<option value="">All Accounts</option>';

    if (res.accounts && res.accounts.length) {
      res.accounts.forEach(acc => {
        const option = document.createElement("option");
        option.value = acc.phone;
        option.textContent = acc.phone + (acc.is_active ? " (Active)" : " (Inactive)");
        dropdown.appendChild(option);
      });
    }

    // Restore selection if it still exists
    if (Array.from(dropdown.options).some(opt => opt.value === currentValue)) {
      dropdown.value = currentValue;
    }
  } catch (e) {
    console.error("Failed to load accounts into filter dropdown:", e);
  }
}

function onGlobalAccountChanged() {
  // Reload current active view metrics with the selected filter
  manualRefresh();
}

async function joinDirectGroup() {
  const linkInput = document.getElementById("join-group-link");
  const link = linkInput.value.trim();
  if (!link) {
    toast("Please enter a group link or username.", "warn");
    return;
  }

  const account = getGlobalAccountFilter();
  toast("Attempting to join group...", "info");
  
  try {
    const res = await fetch("/api/groups/join", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ link: link, phone: account })
    }).then(r => r.json());
    
    if (res.status === "success") {
      toast(`Successfully joined: ${res.group_name || link}`, "ok");
      linkInput.value = "";
      loadGroups();
    } else {
      toast(res.message || "Failed to join group.", "error");
    }
  } catch (e) {
    console.error(e);
    toast("An error occurred while joining group.", "error");
  }
}

async function searchPublicGroups() {
  const queryInput = document.getElementById("search-group-query");
  const query = queryInput.value.trim();
  if (!query) {
    toast("Please enter a search keyword.", "warn");
    return;
  }

  const resultsContainer = document.getElementById("group-search-results");
  resultsContainer.innerHTML = '<div class="loading-cell">Searching public groups...</div>';
  
  const account = getGlobalAccountFilter();
  let url = `/api/groups/search?q=${encodeURIComponent(query)}`;
  if (account) url += `&phone=${encodeURIComponent(account)}`;
  
  try {
    const data = await fetch(url).then(r => r.json());
    if (!data || !data.length) {
      resultsContainer.innerHTML = '<div class="muted" style="font-size: 13px; text-align: center; padding: 20px 0;">No public groups found matching the keyword.</div>';
      return;
    }
    
    resultsContainer.innerHTML = data.map(g => {
      const displayLink = g.username ? `@${g.username}` : `ID: ${g.group_id}`;
      const joinArg = g.username ? `@${g.username}` : String(g.group_id);
      return `
        <div class="search-result-card">
          <div class="search-result-header">
            <span class="search-result-title" title="${e(g.group_name)}">${e(g.group_name)}</span>
            <span class="search-result-type">${g.group_type}</span>
          </div>
          <div class="search-result-meta">
            <span>${e(displayLink)}</span>
            <span>👥 ${g.member_count.toLocaleString()}</span>
          </div>
          <div style="margin-top: 6px; display: flex; justify-content: flex-end;">
            <button class="btn btn-sm btn-primary" onclick="joinSearchedGroup('${e(joinArg)}')" style="font-size: 11px; padding: 4px 10px;">Join</button>
          </div>
        </div>
      `;
    }).join("");
    
  } catch (e) {
    console.error(e);
    resultsContainer.innerHTML = '<div class="muted" style="font-size: 13px; text-align: center; padding: 20px 0; color: #ef4444;">Failed to perform group search.</div>';
  }
}

async function joinSearchedGroup(link) {
  const linkInput = document.getElementById("join-group-link");
  linkInput.value = link;
  await joinDirectGroup();
}

// ══════════════════════════════════════════════════════════════════════════════
// FEATURE 1: TEMPORAL HEATMAP
// ══════════════════════════════════════════════════════════════════════════════

const DAYS   = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
const HOURS  = Array.from({length: 24}, (_, i) => `${i}h`);
const CELL_W = 26, CELL_H = 22, LABEL_W = 34, LABEL_H = 20, PAD = 6;

window.filterHeatmapDow = null;
window.filterHeatmapHour = null;

function clearHeatmapFilter(shouldReload = true) {
  window.filterHeatmapDow = null;
  window.filterHeatmapHour = null;
  const indicator = document.getElementById("heatmap-filter-indicator");
  if (indicator) indicator.style.display = "none";
  if (shouldReload) loadMessages(1);
}

async function loadHeatmap() {
  const canvas = document.getElementById("heatmap-canvas");
  if (!canvas) return;

  // Retrieve current active filters to sync heatmap data with dashboard cards/charts
  const from = document.getElementById("chart-date-from").value || null;
  const to   = document.getElementById("chart-date-to").value   || null;
  const account = getGlobalAccountFilter();
  
  let url = "/api/stats/heatmap";
  const params = [];
  if (from) params.push(`datetime_from=${from}`);
  if (to)   params.push(`datetime_to=${to}`);
  if (account) params.push(`fetched_by=${encodeURIComponent(account)}`);
  if (params.length) url += "?" + params.join("&");

  let data = [];
  try {
    data = await fetch(url).then(r => r.json());
  } catch (_) { return; }

  // Build lookup: grid[day][hour] = {count, avg_risk}
  const grid = Array.from({length: 7}, () => Array(24).fill(null));
  let maxCount = 0;
  for (const row of data) {
    grid[row.day][row.hour] = row;
    if (row.count > maxCount) maxCount = row.count;
  }

  const W = LABEL_W + 24 * (CELL_W + PAD) + PAD;
  const H = LABEL_H + 7  * (CELL_H + PAD) + PAD;
  canvas.width  = W;
  canvas.height = H;

  const ctx = canvas.getContext("2d");
  ctx.clearRect(0, 0, W, H);

  // Hour labels (top)
  ctx.font = "9px Inter, sans-serif";
  ctx.fillStyle = "#64748b";
  ctx.textAlign = "center";
  for (let h = 0; h < 24; h++) {
    if (h % 3 === 0) {
      ctx.fillText(`${h}h`, LABEL_W + h * (CELL_W + PAD) + CELL_W / 2, LABEL_H - 4);
    }
  }

  // Day labels (left)
  ctx.textAlign = "right";
  for (let d = 0; d < 7; d++) {
    ctx.fillText(DAYS[d], LABEL_W - 4, LABEL_H + d * (CELL_H + PAD) + CELL_H / 2 + 4);
  }

  // Cells
  for (let d = 0; d < 7; d++) {
    for (let h = 0; h < 24; h++) {
      const cell = grid[d][h];
      const x = LABEL_W + h * (CELL_W + PAD);
      const y = LABEL_H + d * (CELL_H + PAD);
      const intensity = cell ? cell.count / Math.max(1, maxCount) : 0;
      const risk      = cell ? cell.avg_risk / 100 : 0;

      // Base colour: purple → deeper purple for volume; red tint for risk
      const r = Math.round(50  + risk * 150 + intensity * 30);
      const g = Math.round(20  - risk * 10  + intensity * 5);
      const b = Math.round(100 - risk * 50  + intensity * 60);
      const alpha = cell ? 0.15 + intensity * 0.75 : 0.05;

      ctx.fillStyle = `rgba(${r},${g},${b},${alpha})`;
      ctx.beginPath();
      ctx.roundRect(x, y, CELL_W, CELL_H, 3);
      ctx.fill();

      if (!cell) {
        ctx.fillStyle = "rgba(255,255,255,0.03)";
        ctx.beginPath();
        ctx.roundRect(x, y, CELL_W, CELL_H, 3);
        ctx.fill();
      }
    }
  }

  // Tooltip & Hover Coordinates
  const tooltip = document.getElementById("heatmap-tooltip");
  
  const getCellFromEvent = (ev) => {
    const rect = canvas.getBoundingClientRect();
    const mx = ev.clientX - rect.left;
    const my = ev.clientY - rect.top;
    const h = Math.floor((mx - LABEL_W) / (CELL_W + PAD));
    const d = Math.floor((my - LABEL_H) / (CELL_H + PAD));
    if (h >= 0 && h < 24 && d >= 0 && d < 7) {
      return { day: d, hour: h, cell: grid[d][h] };
    }
    return null;
  };

  canvas.onmousemove = (ev) => {
    const info = getCellFromEvent(ev);
    if (info && info.cell) {
      tooltip.style.display = "block";
      tooltip.style.left = `${ev.clientX + 12}px`;
      tooltip.style.top  = `${ev.clientY - 10}px`;
      tooltip.innerHTML = `
        <strong>${DAYS[info.day]} ${info.hour}:00–${info.hour}:59</strong><br>
        Messages: <strong>${info.cell.count}</strong><br>
        Avg Risk: <strong>${info.cell.avg_risk}</strong><br>
        <span style="color:#a78bfa; font-size:10px; font-weight:600;">Click to filter messages</span>
      `;
      return;
    }
    tooltip.style.display = "none";
  };
  
  canvas.onmouseleave = () => { tooltip.style.display = "none"; };

  // Click handler to filter message dashboard
  canvas.onclick = (ev) => {
    const info = getCellFromEvent(ev);
    if (info && info.cell) {
      window.filterHeatmapDow = info.day;
      window.filterHeatmapHour = info.hour;
      
      // Update Filter Indicator UI
      const indicator = document.getElementById("heatmap-filter-indicator");
      const textSpan  = document.getElementById("heatmap-filter-text");
      if (indicator && textSpan) {
        textSpan.textContent = `${DAYS[info.day]}s around ${info.hour}:00 - ${info.hour}:59`;
        indicator.style.display = "flex";
      }

      // Hide tooltip
      tooltip.style.display = "none";

      // Show toast alert
      showToast(`Filtering messages to Wednesdays at 14:00 (example) DOW ${DAYS[info.day]} @ ${info.hour}:00`);

      // Switch to Messages section and load
      showSection("messages");
      loadMessages(1);
    }
  };
}


// ══════════════════════════════════════════════════════════════════════════════
// FEATURE 2: IN-PLACE IOC PIVOT PANEL
// ══════════════════════════════════════════════════════════════════════════════

function closeModalPivotPane() {
  const modalContent = document.querySelector("#message-detail-modal .modal-content");
  const modalLayout = document.querySelector("#message-detail-modal .modal-body-layout");
  const pivotSidebar = document.getElementById("modal-pivot-sidebar");

  if (modalContent) modalContent.classList.remove("pivot-wide");
  if (modalLayout) modalLayout.classList.remove("pivot-active");
  if (pivotSidebar) pivotSidebar.style.display = "none";
}

async function showIocPivot(iocType, iocValue) {
  const modalContent = document.querySelector("#message-detail-modal .modal-content");
  const modalLayout = document.querySelector("#message-detail-modal .modal-body-layout");
  const pivotSidebar = document.getElementById("modal-pivot-sidebar");
  const subtitle = document.getElementById("modal-pivot-subtitle");
  const loading = document.getElementById("modal-pivot-loading");
  const listDiv = document.getElementById("modal-pivot-list");

  if (!pivotSidebar) return;

  // Slide open the side panel
  if (modalContent) modalContent.classList.add("pivot-wide");
  if (modalLayout) modalLayout.classList.add("pivot-active");
  pivotSidebar.style.display = "block";

  subtitle.textContent = `${iocType.replace("crypto_", "").toUpperCase()}: "${iocValue}"`;
  listDiv.innerHTML = "";
  loading.style.display = "block";

  try {
    const params = new URLSearchParams({ type: iocType, value: iocValue });
    const rows = await fetch(`/api/ioc/pivot?${params}`).then(r => r.json());
    loading.style.display = "none";
    
    // Store pivot results globally
    window.currentPivotMessages = rows;

    if (!rows.length) {
      listDiv.innerHTML = `<div class="muted" style="font-size:12px; text-align:center; padding:20px 0;">No matching messages found for this IOC.</div>`;
      return;
    }

    listDiv.innerHTML = rows.map((row, index) => {
      const ts = row.timestamp ? row.timestamp.slice(11, 16) : "—";
      const risk = row.risk_score || 0;
      const riskCls = risk >= 70 ? "risk-high" : risk >= 40 ? "risk-medium" : "risk-low";
      const txt = (row.text || "").slice(0, 110);
      const kw = row.matched_keyword ? `<span class="tag-kw" style="font-size:9px; padding:1px 5px;">${e(row.matched_keyword)}</span>` : "";
      const cat = row.threat_category ? `<span class="entity-badge" style="font-size:9px; padding:1px 5px;">${e(row.threat_category)}</span>` : "";
      
      return `
        <div class="pivot-message-card" onclick="openPivotMessageDetailInPlace(${index})" title="Click to view details in-place">
          <div class="pivot-card-header">
            <span class="pivot-card-group">${e(row.group_name || "Unknown")}</span>
            <span class="pivot-card-time">${ts} &nbsp; <span class="${riskCls}" style="font-weight:700;">${risk.toFixed(0)}</span></span>
          </div>
          <div class="pivot-card-body">${e(txt)}${txt.length < (row.text||"").length ? "…" : ""}</div>
          <div class="pivot-card-meta">
            ${kw}
            ${cat}
          </div>
        </div>
      `;
    }).join("");
  } catch (err) {
    loading.style.display = "none";
    listDiv.innerHTML = `<div class="muted" style="font-size:12px; color:#ef4444; text-align:center; padding:20px 0;">Error loading pivot data.</div>`;
  }
}

function openPivotMessageDetailInPlace(index) {
  const m = window.currentPivotMessages[index];
  if (!m) return;
  
  // Pivot message has full fields. We temporarily override window.currentMessages
  // so openMessageDetail can extract all attributes correctly.
  // Note: We DO NOT close the pivot sidebar pane, allowing the analyst to browse items in place!
  window.currentMessages = [m];
  openMessageDetail(0);
}

async function translateMessage() {
  const msgId = window.currentMessageId;
  if (!msgId) return;

  const btn = document.getElementById("modal-btn-translate");
  const transBox = document.getElementById("modal-translation-box");
  const transText = document.getElementById("modal-translation-text");

  if (!btn || !transBox || !transText) return;

  btn.disabled = true;
  btn.textContent = "⏳ Translating...";

  try {
    const res = await fetch(`/api/messages/${msgId}/translate`).then(r => r.json());
    if (res.error) {
      showToast(`Translation error: ${res.error}`);
      btn.disabled = false;
      btn.textContent = "🌐 Translate";
      return;
    }

    transText.textContent = res.translated_text || "[No translated text returned]";
    transBox.style.display = "block";
    btn.textContent = "✅ Translated";
  } catch (err) {
    console.error("Translation request failed:", err);
    showToast("Failed to request translation from backend.");
    btn.disabled = false;
    btn.textContent = "🌐 Translate";
  }
}




// =========================================================
// -- Group Discovery Scanner UI
// =========================================================

let _discoveryPollTimer = null;

async function loadDiscoveredGroups() {
  const list = document.getElementById("discovery-cards-list");
  if (!list) return;
  list.innerHTML = `<div class="muted" style="font-size:13px;text-align:center;padding:20px 0;">Loading...</div>`;
  try {
    const res  = await fetch("/api/discovery/pending");
    const data = await res.json();
    _renderDiscoveryCards(data.groups || []);
    _updateDiscoveryBadge(data.count || 0);
  } catch (err) {
    list.innerHTML = `<div class="muted" style="font-size:12px;text-align:center;padding:15px 0;color:#ef4444;">Error loading discoveries.</div>`;
  }
}

function _updateDiscoveryBadge(count) {
  const badge = document.getElementById("discovery-nav-badge");
  if (!badge) return;
  if (count > 0) {
    badge.textContent = count;
    badge.style.display = "inline-flex";
  } else {
    badge.style.display = "none";
  }
}

function _renderDiscoveryCards(groups) {
  const list = document.getElementById("discovery-cards-list");
  if (!list) return;
  if (!groups.length) {
    list.innerHTML = `
      <div style="text-align:center; padding:30px 10px;">
        <div style="font-size:28px; margin-bottom:8px;">📡</div>
        <div style="font-size:13px; color:#64748b;">Scanner is running...</div>
        <div style="font-size:11px; color:#475569; margin-top:4px;">New groups will appear here when found.</div>
      </div>`;
    return;
  }
  list.innerHTML = groups.map(g => {
    const isInvite = g.source === "invite_link";

    // Source badge
    const srcChip = isInvite
      ? `<span class="discovery-chip inv">🔗 Invite Link</span>`
      : `<span class="discovery-chip kw">🔑 ${e(g.source_keyword || "keyword")}</span>`;

    // Member count badge (prominent if available)
    const membersHtml = g.member_count > 0
      ? `<span class="discovery-chip" style="background:rgba(251,191,36,0.1);border-color:rgba(251,191,36,0.3);color:#fde68a;">
           👥 ${Number(g.member_count).toLocaleString()} members
         </span>` : "";

    // Timestamp
    const ts = g.discovered_at ? fmtTs(g.discovered_at) : "";
    const tsChip = ts ? `<span class="discovery-chip">⏰ ${ts}</span>` : "";

    // Link display (shorter, cleaner)
    const linkHtml = g.invite_link
      ? `<a href="${e(g.invite_link)}" target="_blank"
            style="font-size:10px;color:#60a5fa;text-decoration:none;display:block;margin:4px 0;
                   overflow:hidden;text-overflow:ellipsis;white-space:nowrap;"
            title="${e(g.invite_link)}">${e(g.invite_link)}</a>`
      : g.group_username
        ? `<span style="font-size:11px;color:#60a5fa;display:block;margin:3px 0;">@${e(g.group_username)}</span>`
        : "";

    // Context snippet — the message text where the invite link appeared
    const ctxHtml = (isInvite && g.context_text)
      ? `<div style="
            margin-top:7px;
            padding:6px 8px;
            background:rgba(255,255,255,0.03);
            border-left:2px solid rgba(245,158,11,0.4);
            border-radius:0 4px 4px 0;
            font-size:11px;
            color:#94a3b8;
            line-height:1.45;
            word-break:break-word;
          ">
           <span style="font-size:9px;text-transform:uppercase;letter-spacing:0.05em;color:#64748b;display:block;margin-bottom:3px;">
             📨 Found in message:
           </span>
           ${e(g.context_text)}
         </div>` : "";

    return `
      <div class="discovery-card" id="dcard-${g.id}">
        <div style="display:flex;align-items:flex-start;justify-content:space-between;gap:6px;">
          <div class="discovery-card-name" title="${e(g.group_name)}">${e(g.group_name)}</div>
          ${membersHtml}
        </div>
        ${linkHtml}
        ${ctxHtml}
        <div class="discovery-card-meta" style="margin-top:6px;">${srcChip}${tsChip}</div>
        <div class="discovery-card-actions">
          <button class="btn-approve" onclick="approveDiscoveredGroup(${g.id})">✅ Start Monitoring</button>
          <button class="btn-dismiss" onclick="dismissDiscoveredGroup(${g.id})" title="Dismiss">✕</button>
        </div>
      </div>`;
  }).join("");
}


async function approveDiscoveredGroup(id) {
  const card = document.getElementById(`dcard-${id}`);
  if (card) { card.style.opacity = "0.5"; card.style.pointerEvents = "none"; }
  try {
    const res  = await fetch(`/api/discovery/${id}/approve`, { method: "POST" });
    const data = await res.json();
    if (data.success) showToast("✅ Group approved and monitoring request sent!", "success");
    else showToast(data.error || "Approve failed", "error");
  } catch (err) { showToast("Network error during approve.", "error"); }
  await loadDiscoveredGroups();
  await loadGroups();
}

async function dismissDiscoveredGroup(id) {
  const card = document.getElementById(`dcard-${id}`);
  if (card) {
    card.style.transition = "opacity 0.3s, transform 0.3s";
    card.style.opacity    = "0";
    card.style.transform  = "translateX(20px)";
  }
  setTimeout(async () => {
    try { await fetch(`/api/discovery/${id}/dismiss`, { method: "POST" }); } catch (_) {}
    await loadDiscoveredGroups();
  }, 300);
}

function startDiscoveryBadgePoll() {
  if (_discoveryPollTimer) clearInterval(_discoveryPollTimer);
  _discoveryPollTimer = setInterval(async () => {
    try {
      const res  = await fetch("/api/discovery/count");
      const data = await res.json();
      _updateDiscoveryBadge(data.count || 0);
    } catch (_) {}
  }, 60000);
}

document.addEventListener("DOMContentLoaded", () => {
  startDiscoveryBadgePoll();
  fetch("/api/discovery/count")
    .then(r => r.json())
    .then(d => _updateDiscoveryBadge(d.count || 0))
    .catch(() => {});
});

// ── Settings & Integrations ────────────────────────────────────────────────
async function loadAlertSettings() {
  try {
    const res = await fetch("/api/settings").then(r => r.json());
    if (res) {
      document.getElementById("settings-threshold").value = res.alert_threshold || "70";
      document.getElementById("threshold-val").textContent = res.alert_threshold || "70";
      document.getElementById("settings-webhook").value = res.alert_webhook_url || "";
      document.getElementById("settings-tg-token").value = res.alert_telegram_bot_token || "";
      document.getElementById("settings-tg-chat").value = res.alert_telegram_chat_id || "";
    }
  } catch (err) {
    console.error("Failed to load alert settings:", err);
  }
}

async function saveAlertSettings(event) {
  if (event) event.preventDefault();
  
  const payload = {
    alert_threshold: document.getElementById("settings-threshold").value,
    alert_webhook_url: document.getElementById("settings-webhook").value.trim(),
    alert_telegram_bot_token: document.getElementById("settings-tg-token").value.trim(),
    alert_telegram_chat_id: document.getElementById("settings-tg-chat").value.trim()
  };

  try {
    const res = await fetch("/api/settings", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    }).then(r => r.json());

    if (res && res.status === "success") {
      showToast("💾 Alert integration settings saved successfully.", "success");
    } else {
      showToast(res.error || "Failed to save settings.", "error");
    }
  } catch (err) {
    showToast("Network error while saving settings.", "error");
  }
}

async function sendTestAlert() {
  try {
    showToast("🔔 Triggering test alert verification...", "success");
    const res = await fetch("/api/settings/test-alert", { method: "POST" }).then(r => r.json());
    if (res && res.status === "success") {
      showToast("✅ Test alert dispatched successfully.", "success");
    } else {
      showToast(res.error || "Test alert failed.", "error");
    }
  } catch (err) {
    showToast("Network error during test alert.", "error");
  }
}

