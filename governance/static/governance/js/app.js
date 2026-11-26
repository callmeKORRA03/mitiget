(() => {
  const API = "/api";
  const MODULE_PERMISSIONS = {
    risk: ["view_risk", "create_risk", "edit_risk", "delete_risk"],
    audit: ["view_audit", "create_audit", "edit_audit", "approve_finding", "close_finding"],
  };
  const $ = (selector, root = document) => root.querySelector(selector);
  const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
  const store = window.sessionStorage;
  const tokenKey = "mitiget.access";
  const refreshKey = "mitiget.refresh";
  const tenantKey = "mitiget.tenant";
  let activeTenant = null;
  let memberships = [];
  let membersCache = [];
  let nodesCache = [];
  let risksCache = [];
  let findingsCache = [];

  const escapeHTML = value => String(value ?? "").replace(/[&<>"']/g, ch => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch]));
  const displayRole = role => ({ super_admin: "Super Admin", module_admin: "Module Admin", user: "Regular User" }[role] || role || "Unknown");
  const statusLabel = status => ({ 200: "OK", 201: "CREATED", 204: "NO CONTENT", 400: "BAD REQUEST", 401: "UNAUTHORIZED", 403: "FORBIDDEN", 404: "NOT FOUND", 500: "SERVER ERROR" }[status] || "RESPONSE");
  const dateLabel = value => value ? new Date(value).toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" }) : "—";

  async function request(path, options = {}, allowRefresh = true, unauthenticated = false) {
    const headers = new Headers(options.headers || {});
    if (!unauthenticated && store.getItem(tokenKey)) headers.set("Authorization", `Bearer ${store.getItem(tokenKey)}`);
    if (activeTenant && path !== `${API}/tenants/`) headers.set("X-Tenant-ID", activeTenant.id);
    if (options.body && !(options.body instanceof FormData)) headers.set("Content-Type", "application/json");
    let response;
    try {
      response = await fetch(path, { ...options, headers, credentials: "omit" });
    } catch (error) {
      return { ok: false, status: 0, data: { detail: "Could not reach the API. Check that Django is running." } };
    }
    if (response.status === 401 && allowRefresh && !unauthenticated && store.getItem(refreshKey)) {
      const refreshed = await fetch(`${API}/auth/token/refresh/`, {
        method: "POST", credentials: "omit", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ refresh: store.getItem(refreshKey) }),
      });
      if (refreshed.ok) {
        const tokens = await refreshed.json();
        store.setItem(tokenKey, tokens.access);
        if (tokens.refresh) store.setItem(refreshKey, tokens.refresh);
        return request(path, options, false, unauthenticated);
      }
    }
    let data = null;
    if (response.status !== 204) {
      const text = await response.text();
      try { data = text ? JSON.parse(text) : null; } catch { data = { detail: text || response.statusText }; }
    }
    return { ok: response.ok, status: response.status, data };
  }

  function showNotice(message, kind = "info") {
    const notice = $("#notice");
    if (!notice) return;
    notice.className = `notice ${kind}`;
    notice.textContent = message;
    notice.hidden = false;
    window.clearTimeout(showNotice.timer);
    showNotice.timer = window.setTimeout(() => { notice.hidden = true; }, kind === "error" ? 6500 : 3600);
  }

  function errorText(data) {
    if (!data) return "The request failed.";
    if (typeof data === "string") return data;
    if (data.detail) return data.detail;
    return Object.entries(data).map(([key, value]) => `${key}: ${Array.isArray(value) ? value.join(", ") : value}`).join(" · ") || "The request failed.";
  }

  async function checked(path, options) {
    const result = await request(path, options);
    if (!result.ok) {
      showNotice(`${result.status || "Network"} ${statusLabel(result.status)} · ${errorText(result.data)}`, "error");
      if (result.status === 401) window.setTimeout(() => logout(), 900);
    }
    return result;
  }

  function logout() {
    [tokenKey, refreshKey, tenantKey, "mitiget.email"].forEach(key => store.removeItem(key));
    window.location.assign("/app/login/");
  }

  function setupNavigation() {
    const page = document.body.dataset.page;
    const current = $(`[data-nav="${page}"]`);
    if (current) current.classList.add("active");
    $$('[data-logout]').forEach(button => button.addEventListener("click", logout));
    const toggle = $("[data-menu-toggle]");
    if (toggle) toggle.addEventListener("click", () => $("#sidebar").classList.toggle("open"));
    document.addEventListener("click", event => {
      if (event.target.matches("[data-close-form]")) {
        const panel = event.target.closest(".form-panel");
        if (panel) panel.hidden = true;
      }
    });
  }

  async function initLogin() {
    if (store.getItem(tokenKey)) { window.location.replace("/app/"); return; }
    const form = $("#login-form");
    form.addEventListener("submit", async event => {
      event.preventDefault();
      const button = $("button[type=submit]", form);
      const error = $("#login-error");
      button.disabled = true;
      button.innerHTML = "Signing in…";
      error.hidden = true;
      const result = await request(`${API}/auth/token/`, {
        method: "POST", body: JSON.stringify({ email: form.email.value.trim(), password: form.password.value }),
      }, false, true);
      button.disabled = false;
      button.innerHTML = '<span>Sign in</span><span aria-hidden="true">?</span>';
      if (!result.ok) {
        error.textContent = errorText(result.data) || "Email or password is incorrect.";
        error.hidden = false;
        return;
      }
      store.setItem(tokenKey, result.data.access);
      store.setItem(refreshKey, result.data.refresh);
      store.setItem("mitiget.email", form.email.value.trim());
      form.password.value = "";
      window.location.assign("/app/");
    });
  }

  async function loadTenantContext() {
    if (!store.getItem(tokenKey)) { window.location.replace("/app/login/"); return false; }
    const result = await request(`${API}/tenants/`);
    if (result.status === 401) { logout(); return false; }
    if (!result.ok) { showNotice(errorText(result.data), "error"); return false; }
    memberships = result.data || [];
    if (!memberships.length) {
      showNotice("Your account has no active tenant membership. Ask a tenant administrator for access.", "error");
      return false;
    }
    const previous = store.getItem(tenantKey);
    activeTenant = memberships.find(item => item.id === previous) || memberships[0];
    store.setItem(tenantKey, activeTenant.id);
    const picker = $("#tenant-select");
    if (picker) {
      picker.innerHTML = memberships.map(item => `<option value="${escapeHTML(item.id)}">${escapeHTML(item.name)}</option>`).join("");
      picker.value = activeTenant.id;
      picker.addEventListener("change", () => {
        store.setItem(tenantKey, picker.value);
        window.location.reload();
      });
    }
    updateIdentity();
    return true;
  }

  function updateIdentity() {
    const email = store.getItem("mitiget.email") || "Signed-in user";
    const role = activeTenant?.role;
    const name = email.split("@")[0].replace(/[._-]+/g, " ");
    const headerUser = $("#header-user");
    if (headerUser) headerUser.textContent = email;
    const headerRole = $("#header-role");
    if (headerRole) headerRole.textContent = `${displayRole(role)} · ${activeTenant?.name || ""}`;
    const avatar = $("#user-avatar");
    if (avatar) avatar.textContent = (name.trim()[0] || "U").toUpperCase();
    const roleCard = $("#stat-role");
    if (roleCard) roleCard.textContent = displayRole(role);
    const welcome = $("#welcome-user");
    if (welcome) welcome.textContent = `Welcome back, ${name}`;
    const subtitle = $("#welcome-subtitle");
    if (subtitle) subtitle.textContent = `You're working in ${activeTenant?.name}. Your access is based on your tenant membership.`;
    const roleBadge = $("#welcome-role");
    if (roleBadge) roleBadge.textContent = displayRole(role).toUpperCase();
  }

  async function loadDashboard() {
    const [licenseResult, riskResult, auditResult] = await Promise.all([
      request(`${API}/admin/licenses/`), request(`${API}/risks/`), request(`${API}/findings/`),
    ]);
    const licenses = licenseResult.ok ? licenseResult.data : [];
    const riskAllowed = riskResult.ok;
    const auditAllowed = auditResult.ok;
    const riskCount = $("#stat-risks");
    if (riskCount) riskCount.textContent = riskAllowed ? (riskResult.data || []).length : "—";
    const auditCount = $("#stat-findings");
    if (auditCount) auditCount.textContent = auditAllowed ? (auditResult.data || []).length : "—";
    const licensedCount = $("#stat-licensed");
    if (licensedCount) {
      if (licenseResult.ok) licensedCount.textContent = licenses.filter(license => license.active && (!license.expires_at || new Date(license.expires_at) > new Date())).length;
      else licensedCount.textContent = `${Number(riskAllowed) + Number(auditAllowed)} accessible`;
    }
    updateModuleStatus("risk", riskAllowed);
    updateModuleStatus("audit", auditAllowed);
    if (!licenseResult.ok && activeTenant.role !== "super_admin") {
      const el = $("#stat-licensed")?.nextElementSibling;
      if (el) el.textContent = "Accessible modules (licence details are admin-only)";
    }
  }

  function updateModuleStatus(module, accessible) {
    const badge = $(`#${module}-module-status`);
    if (!badge) return;
    badge.className = `status-badge ${accessible ? "allowed" : "denied"}`;
    badge.textContent = accessible ? "Accessible" : "Denied";
    const note = $(`#${module}-access-note`);
    if (note) note.textContent = accessible ? "Visible within your access scope" : "No access · API denied or unlicensed";
  }

  function probeResult(element, result, label) {
    const codeClass = result.ok ? "http-code" : "http-code error";
    const body = escapeHTML(JSON.stringify(result.data ?? {}, null, 2));
    element.classList.remove("empty");
    element.innerHTML = `<span class="result-icon">?</span><div><b>${escapeHTML(label)}</b><p>${body}</p></div><span class="${codeClass}">${result.status || "ERR"} ${statusLabel(result.status)}</span>`;
  }

  function initProbe() {
    const run = $("#run-probe");
    if (!run) return;
    const resultEl = $("#probe-result");
    run.addEventListener("click", async () => {
      const path = $("#probe-operation").value;
      const result = await request(path);
      probeResult(resultEl, result, `GET ${path}`);
    });
    $("#run-unauthenticated").addEventListener("click", async () => {
      const path = $("#probe-operation").value;
      const result = await request(path, {}, false, true);
      probeResult(resultEl, result, `Unauthenticated GET ${path}`);
    });
  }

  async function loadUsers() {
    const result = await checked(`${API}/admin/users/`);
    const body = $("#users-table");
    if (!result.ok) {
      if (body) body.innerHTML = `<tr><td colspan="5" class="table-empty">${escapeHTML(result.status)} ${escapeHTML(statusLabel(result.status))} ? ${escapeHTML(errorText(result.data))}</td></tr>`;
      return;
    }
    membersCache = result.data || [];
    if (!body) return;
    $("#member-count").textContent = `${membersCache.length} active tenant member${membersCache.length === 1 ? "" : "s"}.`;
    if (!membersCache.length) { body.innerHTML = '<tr><td colspan="5" class="table-empty">No tenant members found.</td></tr>'; return; }
    body.innerHTML = membersCache.map(member => {
      const assigned = (member.modules || []).map(module => `<span class="assignment-chip">${module === "audit" ? "Audit" : "Risk"}<button class="chip-remove" data-unassign="${member.membership_id}" data-module="${escapeHTML(module)}" aria-label="Remove ${escapeHTML(module)} assignment">×</button></span>`).join("") || '<span class="muted-cell">No module assignment</span>';
      const moduleOptions = ["risk", "audit"].filter(module => !(member.modules || []).includes(module)).map(module => `<option value="${module}">${module === "audit" ? "Internal Audit" : "Risk"}</option>`).join("");
      const assign = member.role === "super_admin" ? "" : `<div class="inline-assign"><select aria-label="Module to assign" data-module-choice="${member.membership_id}">${moduleOptions}</select><button class="mini-add" data-assign="${member.membership_id}" title="Assign module">+</button></div>`;
      return `<tr><td><b>${escapeHTML(member.user.first_name || member.user.email)}</b><small>${escapeHTML(member.user.email)}</small></td><td><span class="role-badge ${escapeHTML(member.role)}">${escapeHTML(displayRole(member.role))}</span></td><td>${assigned}</td><td><span class="member-active"><i></i> Active</span></td><td>${assign}</td></tr>`;
    }).join("");
    body.onclick = async event => {
      const assignButton = event.target.closest("[data-assign]");
      const removeButton = event.target.closest("[data-unassign]");
      if (assignButton) {
        const membershipId = assignButton.dataset.assign;
        const module = $(`[data-module-choice="${membershipId}"]`, body)?.value;
        if (!module) return;
        const response = await checked(`${API}/admin/memberships/${membershipId}/modules/`, { method: "POST", body: JSON.stringify({ module }) });
        if (response.ok) { showNotice("Module assignment updated.", "success"); await loadUsers(); }
      }
      if (removeButton) {
        const response = await checked(`${API}/admin/memberships/${removeButton.dataset.unassign}/modules/${removeButton.dataset.module}/`, { method: "DELETE" });
        if (response.ok) { showNotice("Module assignment removed.", "success"); await loadUsers(); }
      }
    };
  }

  function initUserForm() {
    const show = $("#show-user-form");
    if (!show) return;
    show.addEventListener("click", () => { $("#user-form-panel").hidden = false; $("#user-form-panel").scrollIntoView({ behavior: "smooth", block: "nearest" }); });
    $("#user-form").addEventListener("submit", async event => {
      event.preventDefault();
      const form = event.currentTarget;
      const payload = Object.fromEntries(new FormData(form));
      const result = await checked(`${API}/admin/users/`, { method: "POST", body: JSON.stringify(payload) });
      if (result.ok) { showNotice(`Created ${result.data.user.email}.`, "success"); form.reset(); $("#user-form-panel").hidden = true; await loadUsers(); }
    });
    $("#refresh-users").addEventListener("click", loadUsers);
  }

  async function loadGrantFormData() {
    const [users, nodes] = await Promise.all([checked(`${API}/admin/users/`), checked(`${API}/org-nodes/`)]);
    if (users.ok) {
      membersCache = users.data || [];
      const selectable = membersCache.filter(member => member.role === "user");
      $("#grant-user").innerHTML = selectable.length ? selectable.map(member => `<option value="${member.user.id}">${escapeHTML(member.user.email)}</option>`).join("") : '<option value="">No regular users available</option>';
    } else {
      $("#grant-user").innerHTML = `<option value="">${escapeHTML(users.status)} ${escapeHTML(statusLabel(users.status))}</option>`;
    }
    if (nodes.ok) {
      nodesCache = nodes.data || [];
      $("#grant-node").innerHTML = '<option value="">Tenant-wide</option>' + nodesCache.map(node => `<option value="${node.id}">${escapeHTML(node.name)} · ${escapeHTML(node.kind)}</option>`).join("");
    }
    updatePermissionOptions();
  }

  function updatePermissionOptions() {
    const module = $("#grant-module")?.value || "risk";
    const select = $("#grant-permission");
    if (select) select.innerHTML = MODULE_PERMISSIONS[module].map(permission => `<option value="${permission}">${permission}</option>`).join("");
  }

  async function loadGrants() {
    const result = await checked(`${API}/admin/grants/`);
    const tbody = $("#grants-table");
    if (!result.ok) {
      if (tbody) tbody.innerHTML = `<tr><td colspan="6" class="table-empty">${escapeHTML(result.status)} ${escapeHTML(statusLabel(result.status))} ? ${escapeHTML(errorText(result.data))}</td></tr>`;
      return;
    }
    if (!result.data.length) { tbody.innerHTML = '<tr><td colspan="6" class="table-empty">No permission grants yet.</td></tr>'; return; }
    tbody.innerHTML = result.data.map(grant => `<tr><td><b>${escapeHTML(grant.email)}</b></td><td>${grant.module === "audit" ? "Internal Audit" : "Risk"}</td><td><code>${escapeHTML(grant.permission)}</code></td><td>${escapeHTML(grant.scope || "Tenant-wide")}</td><td>${dateLabel(grant.created_at)}</td><td><button class="table-action" data-revoke="${grant.id}">Revoke</button></td></tr>`).join("");
    tbody.onclick = async event => {
      const button = event.target.closest("[data-revoke]");
      if (!button || !window.confirm("Revoke this permission grant?")) return;
      const response = await checked(`${API}/admin/grants/${button.dataset.revoke}/`, { method: "DELETE" });
      if (response.ok) { showNotice("Permission revoked.", "success"); await loadGrants(); }
    };
  }

  function initPermissionForm() {
    const form = $("#grant-form");
    if (!form) return;
    $("#grant-module").addEventListener("change", updatePermissionOptions);
    form.addEventListener("submit", async event => {
      event.preventDefault();
      const data = new FormData(form);
      const payload = { target_user_id: Number(data.get("target_user_id")), module: data.get("module"), permission: data.get("permission"), node: data.get("node") ? Number(data.get("node")) : null };
      const result = await checked(`${API}/admin/grants/`, { method: "POST", body: JSON.stringify(payload) });
      if (result.ok) { showNotice("Permission granted.", "success"); await loadGrants(); }
    });
    $("#refresh-grants").addEventListener("click", loadGrants);
  }

  async function loadLicenses() {
    const result = await checked(`${API}/admin/licenses/`);
    const container = $("#licenses-list");
    if (!result.ok) {
      if (container) container.innerHTML = `<div class="empty-card">${escapeHTML(result.status)} ${escapeHTML(statusLabel(result.status))} ? ${escapeHTML(errorText(result.data))}</div>`;
      return;
    }
    const licenses = result.data || [];
    const modules = [{ key: "risk", label: "Risk", symbol: "?", tone: "risk-symbol" }, { key: "audit", label: "Internal Audit", symbol: "?", tone: "audit-symbol" }];
    container.innerHTML = modules.map(module => {
      const license = licenses.find(item => item.module === module.key);
      const enabled = !!license?.active && (!license.expires_at || new Date(license.expires_at) > new Date());
      const expired = !!license?.expires_at && new Date(license.expires_at) <= new Date();
      const expiry = license?.expires_at ? `Expires ${dateLabel(license.expires_at)}` : "No expiry date";
      return `<article class="license-card"><div class="license-head"><div class="module-symbol ${module.tone}">${module.symbol}</div><div><h2>${module.label}</h2><p>${module.key === "risk" ? "Enterprise risk management" : "Assurance and findings"}</p></div></div><div class="license-status ${enabled ? "active" : "inactive"}"><div><b>${enabled ? "Active" : expired ? "Expired" : "Inactive / not configured"}</b><small>${escapeHTML(expiry)}</small></div><span class="status-badge ${enabled ? "allowed" : "denied"}">${enabled ? "Licensed" : "Unavailable"}</span></div><button class="button ${enabled ? "secondary" : "primary"}" data-toggle-license="${module.key}" data-active="${enabled}">${enabled ? "Disable licence" : "Enable licence"}</button></article>`;
    }).join("");
    container.onclick = async event => {
      const button = event.target.closest("[data-toggle-license]");
      if (!button) return;
      const module = button.dataset.toggleLicense;
      const active = button.dataset.active !== "true";
      const response = await checked(`${API}/admin/licenses/${module}/`, { method: "PUT", body: JSON.stringify({ active, expires_at: null }) });
      if (response.ok) { showNotice(`${module === "risk" ? "Risk" : "Internal Audit"} licence ${active ? "enabled" : "disabled"}.", "success"); await loadLicenses(); }
    };
  }

  function showForm(formId, titleId, title) {
    const panel = $(`#${formId}`);
    if (!panel) return;
    panel.hidden = false;
    if (titleId) $(`#${titleId}`).textContent = title;
    panel.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }

  function resetBusinessForm(form) {
    form.reset();
    form.elements.id.value = "";
  }

  async function loadRisks() {
    const result = await checked(`${API}/risks/`);
    const tbody = $("#risks-table");
    if (!result.ok) {
      if (tbody) tbody.innerHTML = `<tr><td colspan="6" class="table-empty">${escapeHTML(result.status)} ${escapeHTML(statusLabel(result.status))} ? ${escapeHTML(errorText(result.data))}</td></tr>`;
      return;
    }
    risksCache = result.data || [];
    $("#risk-count").textContent = `${risksCache.length} record${risksCache.length === 1 ? "" : "s"} visible in your current scope.`;
    if (!risksCache.length) { tbody.innerHTML = '<tr><td colspan="6" class="table-empty">No accessible Risk records. You may not have a view permission or the module licence may be inactive.</td></tr>'; return; }
    tbody.innerHTML = risksCache.map(risk => `<tr><td><b>${escapeHTML(risk.title)}</b><small>Risk #${risk.id}</small></td><td><span class="severity ${escapeHTML(risk.severity)}">${escapeHTML(risk.severity)}</span></td><td>Node ${risk.node}</td><td>${escapeHTML(risk.description || "—")}</td><td>${dateLabel(risk.created_at)}</td><td><div class="table-buttons"><button class="table-action" data-view-risk="${risk.id}">View</button><button class="table-action" data-edit-risk="${risk.id}">Edit</button><button class="table-action" data-delete-risk="${risk.id}">Delete</button></div></td></tr>`).join("");
    tbody.onclick = async event => {
      const view = event.target.closest("[data-view-risk]");
      const edit = event.target.closest("[data-edit-risk]");
      const remove = event.target.closest("[data-delete-risk]");
      const item = risksCache.find(risk => risk.id === Number((view || edit || remove)?.dataset.viewRisk || (view || edit || remove)?.dataset.editRisk || (view || edit || remove)?.dataset.deleteRisk));
      if (!item) return;
      if (view) { showDetail("#risk-detail", "Risk record", item, ["title", "severity", "node", "description", "created_at"]); return; }
      if (edit) {
        const form = $("#risk-form");
        form.elements.id.value = item.id; form.elements.title.value = item.title; form.elements.severity.value = item.severity; form.elements.node.value = item.node; form.elements.description.value = item.description;
        showForm("risk-form-panel", "risk-form-title", "Edit risk"); return;
      }
      if (remove && window.confirm(`Delete risk “${item.title}”?`)) {
        const response = await checked(`${API}/risks/${item.id}/`, { method: "DELETE" });
        if (response.ok) { showNotice("Risk record deleted.", "success"); await loadRisks(); }
      }
    };
  }

  async function initRiskPage() {
    $("#show-risk-form").addEventListener("click", () => { resetBusinessForm($("#risk-form")); showForm("risk-form-panel", "risk-form-title", "Create risk"); });
    $("#refresh-risks").addEventListener("click", loadRisks);
    $("#risk-form").addEventListener("submit", async event => {
      event.preventDefault();
      const form = event.currentTarget; const data = new FormData(form); const id = data.get("id");
      const payload = { title: data.get("title"), severity: data.get("severity"), node: Number(data.get("node")), description: data.get("description") };
      const result = await checked(`${API}/risks/${id ? `${id}/` : ""}`, { method: id ? "PATCH" : "POST", body: JSON.stringify(payload) });
      if (result.ok) { showNotice(id ? "Risk updated." : "Risk created.", "success"); resetBusinessForm(form); $("#risk-form-panel").hidden = true; await loadRisks(); }
    });
    await loadRisks();
  }

  function showDetail(selector, title, data, keys) {
    const panel = $(selector);
    panel.innerHTML = `<button class="icon-button detail-close" aria-label="Close">×</button><h2>${escapeHTML(title)}</h2>${keys.map(key => `<div class="detail-field"><small>${escapeHTML(key.replaceAll("_", " "))}</small><p>${escapeHTML(key.endsWith("_at") ? dateLabel(data[key]) : data[key] || "—")}</p></div>`).join("")}`;
    panel.hidden = false;
    $(".detail-close", panel).addEventListener("click", () => { panel.hidden = true; });
  }

  async function loadFindings() {
    const result = await checked(`${API}/findings/`);
    const tbody = $("#findings-table");
    if (!result.ok) {
      if (tbody) tbody.innerHTML = `<tr><td colspan="6" class="table-empty">${escapeHTML(result.status)} ${escapeHTML(statusLabel(result.status))} ? ${escapeHTML(errorText(result.data))}</td></tr>`;
      return;
    }
    findingsCache = result.data || [];
    $("#finding-count").textContent = `${findingsCache.length} finding${findingsCache.length === 1 ? "" : "s"} visible in your current scope.`;
    if (!findingsCache.length) { tbody.innerHTML = '<tr><td colspan="6" class="table-empty">No accessible findings. You may not have a view permission or the module licence may be inactive.</td></tr>'; return; }
    tbody.innerHTML = findingsCache.map(item => `<tr><td><b>${escapeHTML(item.title)}</b><small>Finding #${item.id}</small></td><td><span class="finding-status ${escapeHTML(item.status)}">${escapeHTML(item.status)}</span></td><td>Node ${item.node}</td><td>${escapeHTML(item.description || "—")}</td><td>${dateLabel(item.created_at)}</td><td><div class="table-buttons"><button class="table-action" data-view-finding="${item.id}">View</button><button class="table-action" data-edit-finding="${item.id}">Edit</button><button class="table-action approve" data-approve-finding="${item.id}">Approve</button><button class="table-action close-action" data-close-finding="${item.id}">Close</button></div></td></tr>`).join("");
    tbody.onclick = async event => {
      const button = event.target.closest("[data-view-finding],[data-edit-finding],[data-approve-finding],[data-close-finding]");
      if (!button) return;
      const item = findingsCache.find(finding => finding.id === Number(Object.values(button.dataset)[0]));
      if (!item) return;
      if (button.hasAttribute("data-view-finding")) { showDetail("#finding-detail", "Audit finding", item, ["title", "status", "node", "description", "created_at"]); return; }
      if (button.hasAttribute("data-edit-finding")) {
        const form = $("#finding-form"); form.elements.id.value = item.id; form.elements.title.value = item.title; form.elements.node.value = item.node; form.elements.description.value = item.description;
        showForm("finding-form-panel", "finding-form-title", "Edit finding"); return;
      }
      if (button.hasAttribute("data-approve-finding") && !window.confirm(`Approve “${item.title}”?`)) return;
      if (button.hasAttribute("data-close-finding") && !window.confirm(`Close “${item.title}”?`)) return;
      const action = button.hasAttribute("data-approve-finding") ? "approve" : "close";
      const response = await checked(`${API}/findings/${item.id}/${action}/`, { method: "POST", body: JSON.stringify({}) });
      if (response.ok) { showNotice(`Finding ${action} action completed.`, "success"); await loadFindings(); }
    };
  }

  async function initAuditPage() {
    $("#show-finding-form").addEventListener("click", () => { resetBusinessForm($("#finding-form")); showForm("finding-form-panel", "finding-form-title", "Create finding"); });
    $("#refresh-findings").addEventListener("click", loadFindings);
    $("#finding-form").addEventListener("submit", async event => {
      event.preventDefault();
      const form = event.currentTarget; const data = new FormData(form); const id = data.get("id");
      const payload = { title: data.get("title"), node: Number(data.get("node")), description: data.get("description") };
      const result = await checked(`${API}/findings/${id ? `${id}/` : ""}`, { method: id ? "PATCH" : "POST", body: JSON.stringify(payload) });
      if (result.ok) { showNotice(id ? "Finding updated." : "Finding created.", "success"); resetBusinessForm(form); $("#finding-form-panel").hidden = true; await loadFindings(); }
    });
    await loadFindings();
  }

  async function boot() {
    setupNavigation();
    if (document.body.dataset.page === "login") { await initLogin(); return; }
    const ready = await loadTenantContext();
    if (!ready) return;
    initProbe();
    const page = document.body.dataset.page;
    if (page === "dashboard") await loadDashboard();
    if (page === "users") { initUserForm(); await loadUsers(); }
    if (page === "permissions") { initPermissionForm(); await Promise.all([loadGrantFormData(), loadGrants()]); }
    if (page === "licences") await loadLicenses();
    if (page === "risks") await initRiskPage();
    if (page === "audits") await initAuditPage();
  }

  document.addEventListener("DOMContentLoaded", boot);
})();
