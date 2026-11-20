import { api, state } from "./utils/api.js";
import { dateOnly, dateTime, escapeHtml, money, statusLabel } from "./utils/format.js";
import { FREIGHT_SERVICES, TRANSPORT_MODES, categoryLabel, renderCheckboxes } from "./utils/categories.js";
import { renderBarChart, renderSparkChart } from "./utils/charts.js";
import { renderPagination } from "./utils/pagination.js";
import { signOut } from "./utils/session.js";

const $ = (selector) => document.querySelector(selector);
const ui = {
  rfqPage: 1,
  rfqPageSize: 12,
  activityPage: 1,
  activityPageSize: 10,
  bidPage: 1,
  bidPageSize: 10,
  currentRfqId: null,
  bidFilters: { leaders_only: false, top_three: false },
  analytics: null,
};

function showMessage(message, success = false) {
  const element = $("#auth-message");
  element.textContent = message;
  element.style.color = success ? "var(--accent)" : "var(--danger)";
}

function showCapabilityMessage(message, success = false) {
  const element = $("#capability-message");
  element.textContent = message;
  element.style.color = success ? "var(--accent)" : "var(--danger)";
}

function flash(message, isError = false) {
  const element = $("#flash");
  element.textContent = message;
  element.classList.remove("hidden");
  element.classList.toggle("flash-error", isError);
  window.setTimeout(() => element.classList.add("hidden"), 5000);
}

function passwordIsStrong(password) {
  return password.length >= 12 && /[a-z]/.test(password) && /[A-Z]/.test(password) && /\d/.test(password) && /[^A-Za-z0-9]/.test(password);
}

function confirmWeakPassword() {
  const dialog = $("#password-warning");
  return new Promise((resolve) => {
    dialog.addEventListener("close", () => resolve(dialog.returnValue === "continue"), { once: true });
    dialog.showModal();
  });
}

function switchView(view) {
  const viewIds = { overview: "#overview-view", rfqs: "#dashboard-view", analytics: "#analytics-view", account: "#account-view" };
  for (const [name, selector] of Object.entries(viewIds)) $(selector).classList.toggle("hidden", name !== view);
  document.querySelectorAll("[data-app-view]").forEach((button) => button.classList.toggle("active", button.dataset.appView === view));
  if (view === "account") {
    ui.activityPage = 1;
    loadAccountActivity();
    if (state.me.role === "supplier") loadSupplierCapabilities();
  }
  if (view === "analytics" && !ui.analytics) loadAnalytics();
}

function setLoggedIn() {
  if (!state.me) return;
  const isBuyer = state.me.role === "buyer" && !state.me.is_admin;
  const isSupplier = state.me.role === "supplier" && !state.me.is_admin;
  if (state.me.is_admin) {
    window.location.assign("/admin");
    return;
  }

  $("#auth-panel").classList.add("hidden");
  $("#auth-nav").classList.add("hidden");
  $("#workspace").classList.remove("hidden");
  $("#logout-btn").classList.remove("hidden");
  $("#account-btn").classList.remove("hidden");
  $("#admin-users-link").classList.add("hidden");
  $("#user-chip").classList.remove("hidden");
  $("#user-chip").textContent = `${state.me.username} · ${state.me.role}`;
  $("#sidebar-avatar").textContent = state.me.username.slice(0, 1).toUpperCase();
  $("#sidebar-username").textContent = state.me.username;
  $("#sidebar-role").textContent = isBuyer ? "Buyer account" : "Supplier account";

  $("#new-rfq-btn").classList.toggle("hidden", !isBuyer);
  $("#overview-create-btn").classList.toggle("hidden", !isBuyer);
  $("#supplier-capabilities-panel").classList.toggle("hidden", !isSupplier);
  $("#supplier-filter-form").elements.matching_only.closest("label").classList.toggle("hidden", !isSupplier);
  $("#nav-rfqs-label").textContent = isBuyer ? "My RFQs" : "RFQ marketplace";
  $("#dashboard-eyebrow").textContent = isBuyer ? "BUYER PROCUREMENT" : "SUPPLIER MARKETPLACE";
  $("#dashboard-title").textContent = isBuyer ? "Your RFQs" : "Freight opportunities";
  $("#dashboard-description").textContent = isBuyer
    ? "Track sourcing requests, compare quotes, and keep your procurement moving."
    : "Find the routes and services that fit your fleet.";
  $("#filter-title").textContent = isBuyer ? "Narrow your RFQ list" : "Find your next lane";
  $("#empty-title").textContent = isBuyer ? "No RFQs match these filters" : "No matching opportunities";
  $("#empty-description").textContent = isBuyer
    ? "Adjust the filters or create an RFQ to start a new sourcing request."
    : "Try broadening your filters or update your service capabilities.";
  $("#account-description").textContent = isBuyer
    ? "Your buyer profile and sourcing history."
    : "Your supplier profile, service coverage, and quote history.";
  $("#account-username").textContent = state.me.username;
  $("#account-email").textContent = state.me.email;
  $("#account-role").textContent = state.me.role;
  switchView("overview");
  loadAuctions(1);
  loadAnalytics();
}

function makeFilterQuery(page) {
  const form = $("#supplier-filter-form");
  const params = new URLSearchParams({ page: String(page), page_size: String(ui.rfqPageSize) });
  for (const [key, value] of new FormData(form).entries()) {
    if (String(value).trim()) params.set(key, String(value).trim());
  }
  return params.toString();
}

function renderActiveFilters() {
  const form = $("#supplier-filter-form");
  const chips = [];
  for (const field of form.querySelectorAll("input, select")) {
    if (field.type === "submit" || field.type === "button" || field.name === "matching_only" && state.me?.role !== "supplier") continue;
    if (field.type === "checkbox" && !field.checked) continue;
    if (field.type !== "checkbox" && !String(field.value || "").trim()) continue;
    const label = field.closest("label")?.innerText.trim().replace(/\s+/g, " ") || field.name;
    const selected = field.type === "checkbox" ? "On" : field.tagName === "SELECT" ? field.selectedOptions[0]?.textContent : field.value;
    const concise = label.split("\n")[0];
    chips.push(`<span class="filter-chip">${escapeHtml(concise)} · ${escapeHtml(selected)}</span>`);
  }
  $("#active-filter-chips").innerHTML = chips.join("");
}

function renderRfqCard(rfq) {
  const categories = [
    ...rfq.transport_modes.map((item) => [item, "mode-chip"]),
    ...rfq.services.map((item) => [item, "service-chip"]),
  ].map(([item, type]) => `<span class="category-chip ${type}">${escapeHtml(categoryLabel(item))}</span>`).join("");
  const price = state.me.role === "supplier" ? "Buyer view only" : money(rfq.current_lowest_bid);
  return `<article class="card auction-card" data-rfq="${rfq.id}" tabindex="0" role="button" aria-label="Open ${escapeHtml(rfq.reference_id)} ${escapeHtml(rfq.name)}">
    <div class="card-top"><span class="ref">${escapeHtml(rfq.reference_id)}</span><span class="status status-${escapeHtml(rfq.status)}">${escapeHtml(statusLabel(rfq.status))}</span></div>
    <h3>${escapeHtml(rfq.name)}</h3>
    <p class="route-line"><span>${escapeHtml(rfq.origin || "Origin TBD")}</span><b aria-hidden="true">→</b><span>${escapeHtml(rfq.destination || "Destination TBD")}</span></p>
    <div class="category-chips">${categories}</div>
    <div class="metric-row"><div class="metric"><label>Leading quote</label><strong class="small">${escapeHtml(price)}</strong></div><div class="metric"><label>Pickup</label><strong class="small">${dateOnly(rfq.pickup_service_date)}</strong></div></div>
    <div class="card-foot"><span>Closes ${dateTime(rfq.current_close_at)}</span><span>${escapeHtml(statusLabel(rfq.trigger_mode))}</span></div>
  </article>`;
}

async function loadAuctions(page = ui.rfqPage) {
  ui.rfqPage = Math.max(1, page);
  try {
    renderActiveFilters();
    const data = await api(`/rfqs?${makeFilterQuery(ui.rfqPage)}`);
    $("#results-summary").textContent = `${data.total} ${data.total === 1 ? "RFQ" : "RFQs"}`;
    const grid = $("#auction-grid");
    grid.innerHTML = data.items.map(renderRfqCard).join("");
    $("#empty-state").classList.toggle("hidden", data.items.length > 0);
    grid.querySelectorAll("[data-rfq]").forEach((card) => {
      const open = () => openDetails(card.dataset.rfq);
      card.addEventListener("click", open);
      card.addEventListener("keydown", (event) => {
        if (event.key === "Enter" || event.key === " ") { event.preventDefault(); open(); }
      });
    });
    renderPagination($("#rfq-pagination"), {
      page: data.page,
      pageSize: data.page_size,
      total: data.total,
      onPage: loadAuctions,
    });
  } catch (error) {
    flash(error.message, true);
  }
}

function metricCard(label, value, note = "") {
  return `<article class="metric-card"><span>${escapeHtml(label)}</span><strong>${escapeHtml(value)}</strong><small>${escapeHtml(note)}</small></article>`;
}

function analyticsViewData(data) {
  if (state.me.role === "buyer") {
    return {
      metrics: [
        ["RFQs created", data.rfq_total, "All sourcing requests"],
        ["Open RFQs", data.rfq_active, "Currently accepting quotes"],
        ["Quotes received", data.quote_total, "Across your RFQs"],
        ["Quotes per RFQ", Number(data.average_quotes_per_rfq).toFixed(1), "Average supplier competition"],
      ],
      trend: data.activity_trend,
      breakdown: data.status_breakdown,
      legend: "RFQs created",
      breakdownTitle: "RFQ status",
    };
  }
  const trend = data.activity_trend.map((point) => ({ label: point.label, value: point.count }));
  return {
    metrics: [
      ["Quotes submitted", data.quote_total, "Your submitted quotations"],
      ["Auctions quoted", data.auctions_quoted, "Distinct buyer RFQs"],
      ["Leading quotes", data.leading_quotes, "Auctions where you are L1"],
      ["Average quote", money(data.average_quote), "Across your accepted quotes"],
    ],
    trend,
    breakdown: [
      { label: "Auctions quoted", value: data.auctions_quoted },
      { label: "Leading quotes", value: data.leading_quotes },
      { label: "Other quotes", value: Math.max(0, data.quote_total - data.leading_quotes) },
    ],
    legend: "Quotes submitted",
    breakdownTitle: "Quote performance",
  };
}

function renderAnalytics(data) {
  ui.analytics = data;
  const view = analyticsViewData(data);
  const cards = view.metrics.map(([label, value, note]) => metricCard(label, value, note)).join("");
  $("#overview-kpis").innerHTML = cards;
  $("#analytics-kpis").innerHTML = cards;
  $("#trend-chart-legend").innerHTML = `<i></i>${escapeHtml(view.legend)}`;
  $("#breakdown-title").textContent = view.breakdownTitle;
  $("#analytics-breakdown-title").textContent = view.breakdownTitle;
  $("#analytics-trend-title").textContent = view.legend;
  const trend = view.trend;
  renderSparkChart($("#overview-trend"), trend);
  renderSparkChart($("#analytics-trend"), trend);
  renderBarChart($("#overview-breakdown"), view.breakdown);
  renderBarChart($("#analytics-breakdown"), view.breakdown);
}

async function loadAnalytics() {
  if (!state.me || state.me.is_admin) return;
  try {
    const route = state.me.role === "buyer" ? "/buyers/me/analytics" : "/suppliers/me/analytics";
    const data = await api(route);
    renderAnalytics(data);
  } catch (error) {
    flash(`Analytics could not load: ${error.message}`, true);
  }
}

async function loadAccountActivity(page = ui.activityPage) {
  ui.activityPage = Math.max(1, page);
  const isBuyer = state.me.role === "buyer";
  const list = $("#account-history-list");
  const empty = $("#account-history-empty");
  list.innerHTML = '<p class="muted">Loading your activity…</p>';
  empty.classList.add("hidden");
  try {
    const rolePath = isBuyer ? "/buyers/me/activity" : "/suppliers/me/activity";
    const data = await api(`${rolePath}?page=${ui.activityPage}&page_size=${ui.activityPageSize}`);
    const rows = data.items;
    if (!rows.length) {
      list.innerHTML = "";
      empty.textContent = isBuyer ? "Your RFQs will appear here after you publish one." : "Your submitted quotes will appear here.";
      empty.classList.remove("hidden");
    } else {
      list.innerHTML = rows.map((row) => {
        const action = isBuyer ? "Published RFQ" : "Submitted quote";
        const occurred = isBuyer ? row.created_at : row.submitted_at;
        const status = isBuyer ? row.status : row.bid_status;
        const amount = isBuyer ? null : row.amount;
        return `<article class="history-item"><div class="history-top"><strong>${action} · ${escapeHtml(row.auction_id)}</strong><time>${dateTime(occurred)}</time></div><p>${escapeHtml(row.auction_name)}</p><div class="history-meta"><span>${escapeHtml(status)}</span>${amount != null ? `<strong>${money(amount)}</strong>` : ""}</div></article>`;
      }).join("");
    }
    renderPagination($("#account-pagination"), {
      page: data.page,
      pageSize: data.page_size,
      total: data.total,
      onPage: loadAccountActivity,
    });
  } catch (error) {
    list.innerHTML = `<p class="form-message">${escapeHtml(error.message)}</p>`;
  }
}

async function loadSupplierCapabilities() {
  try {
    const profile = await api("/suppliers/me");
    renderCheckboxes($("#supplier-transport-options"), TRANSPORT_MODES, "transport_modes", profile.transport_modes);
    renderCheckboxes($("#supplier-service-options"), FREIGHT_SERVICES, "services", profile.services);
    showCapabilityMessage("");
  } catch (error) {
    showCapabilityMessage(error.message);
  }
}

function bidFilterQuery() {
  const params = new URLSearchParams({ bid_page: String(ui.bidPage), bid_page_size: String(ui.bidPageSize) });
  if (ui.bidFilters.leaders_only) params.set("leaders_only", "true");
  if (ui.bidFilters.top_three) params.set("top_three", "true");
  return params.toString();
}

async function openDetails(id, page = 1) {
  ui.currentRfqId = Number(id);
  ui.bidPage = Math.max(1, page);
  try {
    const rfq = await api(`/rfqs/${id}?${bidFilterQuery()}`);
    const bids = rfq.bids.map((bid) => `<tr><td class="rank">${bid.rank ? `L${bid.rank}` : "—"}</td><td>${escapeHtml(bid.supplier_name)}</td><td>${escapeHtml(bid.carrier_name)}</td><td><strong>${money(bid.comparison_total)}</strong></td><td>${bid.transit_time_hours}h</td><td>${dateTime(bid.submitted_at)}</td></tr>`).join("");
    const activities = rfq.activities.map((item) => `<div class="activity"><time>${dateTime(item.created_at)}</time><span>${escapeHtml(item.message)}</span></div>`).join("");
    const categories = [...rfq.transport_modes, ...rfq.services].map((item) => `<span class="category-chip">${escapeHtml(categoryLabel(item))}</span>`).join("");
    const isBuyer = state.me.role === "buyer";
    $("#detail-content").innerHTML = `
      <div class="detail-header"><div class="detail-top"><span class="ref">${escapeHtml(rfq.reference_id)}</span><span class="status status-${escapeHtml(rfq.status)}">${escapeHtml(statusLabel(rfq.status))}</span></div>
      <h2>${escapeHtml(rfq.name)}</h2><p class="route-line">${escapeHtml(rfq.origin || "Origin TBD")} <b>→</b> ${escapeHtml(rfq.destination || "Destination TBD")}</p>
      <p class="muted">Pickup ${dateOnly(rfq.pickup_service_date)} · closes ${dateTime(rfq.current_close_at)} · forced close ${dateTime(rfq.forced_close_at)}</p><div class="category-chips">${categories}</div></div>
      ${rfq.remarks ? `<div class="detail-section remarks"><h3>Buyer notes</h3><p>${escapeHtml(rfq.remarks)}</p></div>` : ""}
      <div class="detail-section"><div class="chart-heading"><div><h3>${isBuyer ? "Supplier quotations" : "Your quotations"}</h3><p class="muted">${rfq.bid_total} results · filtered for your account permissions</p></div></div>
        <form id="bid-filter-form" class="bid-filter-ticks"><label class="match-option"><input type="checkbox" name="leaders_only" ${ui.bidFilters.leaders_only ? "checked" : ""}><span>Current best quote per supplier</span></label><label class="match-option"><input type="checkbox" name="top_three" ${ui.bidFilters.top_three ? "checked" : ""}><span>Top three ranks only</span></label></form>
        <div class="table-wrap"><table><thead><tr><th>Rank</th><th>Supplier</th><th>Carrier</th><th>Comparison total</th><th>Transit</th><th>Submitted</th></tr></thead><tbody>${bids || '<tr><td colspan="6">No quotes match these filters.</td></tr>'}</tbody></table></div><nav id="bid-pagination" class="pagination-bar" aria-label="Quotation pages"></nav>
      </div>
      ${!isBuyer && rfq.status === "active" ? `<div class="detail-section"><h3>Submit a lower quote</h3><form id="bid-form" class="form-grid"><label>Carrier name<input name="carrier_name" required minlength="2"></label><label>Quote valid until<input type="datetime-local" name="quote_valid_until" required></label><label>Freight charges<input type="number" name="freight_charges" min="0" step="0.01" required></label><label>Origin charges<input type="number" name="origin_charges" min="0" step="0.01" required></label><label>Destination charges<input type="number" name="destination_charges" min="0" step="0.01" required></label><label>Transit time (hours)<input type="number" name="transit_time_hours" min="1" required></label><div class="form-actions full"><button class="button button-primary" type="submit">Submit quote</button></div></form></div>` : ""}
      <div class="detail-section"><h3>Extension history</h3>${rfq.extensions.length ? rfq.extensions.map((item) => `<div class="activity"><time>${dateTime(item.triggered_at)}</time><span>${escapeHtml(item.trigger_reason)} · closes ${dateTime(item.new_close_at)}</span></div>`).join("") : '<p class="muted">No extensions recorded.</p>'}</div>
      <div class="detail-section"><h3>Activity</h3>${activities || '<p class="muted">No activity yet.</p>'}</div>`;

    $("#detail-panel").classList.remove("hidden");
    renderPagination($("#bid-pagination"), {
      page: rfq.bid_page,
      pageSize: rfq.bid_page_size,
      total: rfq.bid_total,
      onPage: (nextPage) => openDetails(ui.currentRfqId, nextPage),
    });
    $("#bid-filter-form").addEventListener("change", (event) => {
      ui.bidFilters[event.target.name] = event.target.checked;
      openDetails(ui.currentRfqId, 1);
    });
    const bidForm = $("#bid-form");
    if (bidForm) {
      bidForm.addEventListener("submit", async (event) => {
        event.preventDefault();
        const values = new FormData(event.currentTarget);
        const body = Object.fromEntries(values);
        body.quote_valid_until = new Date(body.quote_valid_until).toISOString();
        body.idempotency_key = crypto.randomUUID();
        const button = event.currentTarget.querySelector('button[type="submit"]');
        button.disabled = true;
        try {
          await api(`/rfqs/${id}/bids`, { method: "POST", body: JSON.stringify(body) });
          flash("Quote submitted and ranking refreshed.");
          ui.bidPage = 1;
          await Promise.all([loadAuctions(ui.rfqPage), loadAccountActivity(ui.activityPage), loadAnalytics()]);
          await openDetails(id, 1);
        } catch (error) {
          flash(error.message, true);
        } finally {
          button.disabled = false;
        }
      });
    }
  } catch (error) {
    flash(error.message, true);
  }
}

document.querySelectorAll("[data-auth-tab]").forEach((button) => {
  button.addEventListener("click", () => {
    document.querySelectorAll("[data-auth-tab]").forEach((item) => item.setAttribute("aria-pressed", String(item === button)));
    $("#login-form").classList.toggle("hidden", button.dataset.authTab !== "login");
    $("#register-form").classList.toggle("hidden", button.dataset.authTab !== "register");
    $("#admin-login-form").classList.toggle("hidden", button.dataset.authTab !== "admin");
    showMessage("");
  });
});

$("#login-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const values = new FormData(event.currentTarget);
  showMessage("");
  try {
    const body = new URLSearchParams({ username: values.get("email").trim(), password: values.get("password") });
    const response = await fetch("/api/auth/token", { method: "POST", headers: { "Content-Type": "application/x-www-form-urlencoded" }, body });
    const result = await response.json();
    if (!response.ok) throw new Error(result.detail || `Sign in failed (${response.status})`);
    state.token = result.access_token;
    state.me = await api("/auth/me");
    sessionStorage.setItem("rfq_token", state.token);
    setLoggedIn();
  } catch (error) {
    state.token = null;
    state.me = null;
    sessionStorage.removeItem("rfq_token");
    showMessage(error.message || "Could not reach BidBolt. Try again.");
  }
});

$("#register-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const values = new FormData(form);
  const button = form.querySelector('button[type="submit"]');
  const password = values.get("password");
  button.disabled = true;
  showMessage("");
  try {
    if (!passwordIsStrong(password) && !(await confirmWeakPassword())) {
      form.elements.password.focus();
      return;
    }
    const role = values.get("role");
    await api("/auth/register", {
      method: "POST",
      body: JSON.stringify({ username: values.get("username").trim(), email: values.get("email").trim(), password, role }),
    });
    form.reset();
    document.querySelector('[data-auth-tab="login"]').click();
    showMessage(`${role === "buyer" ? "Buyer" : "Supplier"} account created. Sign in to continue.`, true);
  } catch (error) {
    showMessage(error.message || "Could not reach BidBolt. Try again.");
  } finally {
    button.disabled = false;
  }
});

$("#admin-login-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const values = new FormData(form);
  const button = form.querySelector('button[type="submit"]');
  button.disabled = true;
  showMessage("");
  try {
    const response = await fetch("/api/auth/admin/token", {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: new URLSearchParams({ username: values.get("username").trim(), password: values.get("password") }),
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.detail || `Admin sign in failed (${response.status})`);
    sessionStorage.removeItem("rfq_token");
    window.location.assign("/admin");
  } catch (error) {
    showMessage(error.message || "Could not reach BidBolt. Try again.");
  } finally {
    button.disabled = false;
  }
});

document.querySelectorAll("[data-password-choice]").forEach((button) => {
  button.addEventListener("click", () => $("#password-warning").close(button.dataset.passwordChoice));
});

document.querySelectorAll("[data-app-view]").forEach((button) => {
  button.addEventListener("click", () => switchView(button.dataset.appView));
});

$("#account-btn").addEventListener("click", () => switchView("account"));
$("#back-to-dashboard").addEventListener("click", () => switchView("overview"));
$("#logout-btn").addEventListener("click", () => signOut());
$("#new-rfq-btn").addEventListener("click", () => $("#rfq-panel").classList.remove("hidden"));
$("#overview-create-btn").addEventListener("click", () => $("#rfq-panel").classList.remove("hidden"));

document.querySelectorAll("[data-close]").forEach((button) => {
  button.addEventListener("click", () => $(`#${button.dataset.close}`).classList.add("hidden"));
});

$("#supplier-filter-form").addEventListener("submit", (event) => {
  event.preventDefault();
  loadAuctions(1);
});
$("#supplier-filter-form").addEventListener("change", (event) => {
  if (["checkbox", "select-one", "date"].includes(event.target.type) || event.target.tagName === "SELECT") loadAuctions(1);
});
$("#clear-filters").addEventListener("click", () => {
  $("#supplier-filter-form").reset();
  loadAuctions(1);
});

$("#supplier-capabilities-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const values = new FormData(form);
  const button = form.querySelector('button[type="submit"]');
  const transportModes = values.getAll("transport_modes");
  const services = values.getAll("services");
  if (!transportModes.length) {
    showCapabilityMessage("Choose at least one transport mode.");
    return;
  }
  button.disabled = true;
  showCapabilityMessage("");
  try {
    await api("/suppliers/me/capabilities", { method: "PUT", body: JSON.stringify({ transport_modes: transportModes, services }) });
    showCapabilityMessage("Your capabilities are saved.", true);
    await Promise.all([loadAuctions(1), loadAnalytics()]);
  } catch (error) {
    showCapabilityMessage(error.message);
  } finally {
    button.disabled = false;
  }
});

renderCheckboxes($("#rfq-transport-options"), TRANSPORT_MODES, "transport_modes", ["road"]);
renderCheckboxes($("#rfq-service-options"), FREIGHT_SERVICES, "services");
$("#rfq-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const values = new FormData(form);
  const button = form.querySelector('button[type="submit"]');
  const transportModes = values.getAll("transport_modes");
  const services = values.getAll("services");
  if (!transportModes.length) {
    flash("Choose at least one transport mode.", true);
    return;
  }
  const body = Object.fromEntries(values);
  body.origin = body.origin.trim();
  body.destination = body.destination.trim();
  body.transport_modes = transportModes;
  body.services = services;
  for (const key of ["bid_start_at", "initial_close_at", "forced_close_at"]) body[key] = new Date(body[key]).toISOString();
  button.disabled = true;
  try {
    const rfq = await api("/rfqs", { method: "POST", body: JSON.stringify(body) });
    $("#rfq-panel").classList.add("hidden");
    form.reset();
    renderCheckboxes($("#rfq-transport-options"), TRANSPORT_MODES, "transport_modes", ["road"]);
    renderCheckboxes($("#rfq-service-options"), FREIGHT_SERVICES, "services");
    flash(`${rfq.reference_id} is live and added to your history.`);
    switchView("rfqs");
    await Promise.all([loadAuctions(1), loadAccountActivity(1), loadAnalytics()]);
  } catch (error) {
    flash(error.message, true);
  } finally {
    button.disabled = false;
  }
});

async function boot() {
  if (!state.token) return;
  try {
    state.me = await api("/auth/me");
    setLoggedIn();
  } catch {
    state.token = null;
    sessionStorage.removeItem("rfq_token");
  }
}

boot();
