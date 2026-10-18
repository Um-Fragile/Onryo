/* ============================================================
   Onryo – SPA main router + API client
   Loaded by index.html. Handles:
     - Auth gate (redirects to login if no token)
     - Hash-based routing
     - Global API helper with Bearer token injection
     - Theme persistence
     - WebSocket lifecycle management
   ============================================================ */

// ---------------------------------------------------------------------------
// API client
// ---------------------------------------------------------------------------
const Api = (() => {
  function _token() {
    return sessionStorage.getItem("onryo_token") || "";
  }

  async function request(method, path, body = null) {
    const opts = {
      method,
      credentials: "include",
      headers: {
        "Content-Type": "application/json",
        ..._token() ? { Authorization: `Bearer ${_token()}` } : {},
      },
    };
    if (body !== null) opts.body = JSON.stringify(body);
    const res = await fetch(path, opts);
    if (res.status === 401) {
      sessionStorage.removeItem("onryo_token");
      window.location.hash = "#login";
      throw new Error("Session expired – please log in again");
    }
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || `HTTP ${res.status}`);
    }
    const ct = res.headers.get("content-type") || "";
    return ct.includes("application/json") ? res.json() : res.text();
  }

  const get    = (path)        => request("GET",    path);
  const post   = (path, body)  => request("POST",   path, body ?? {});
  const put    = (path, body)  => request("PUT",    path, body ?? {});
  const del    = (path)        => request("DELETE", path);

  function ws(path) {
    const proto = location.protocol === "https:" ? "wss" : "ws";
    const token = _token();
    const sep   = path.includes("?") ? "&" : "?";
    return new WebSocket(`${proto}://${location.host}${path}${token ? sep + "token=" + token : ""}`);
  }

  return { get, post, put, del, ws };
})();

// ---------------------------------------------------------------------------
// Theme
// ---------------------------------------------------------------------------
const Theme = (() => {
  const THEMES = ["dark", "light", "high-contrast"];
  const KEY = "onryo_theme";

  function apply(name) {
    if (!THEMES.includes(name)) name = "dark";
    document.documentElement.setAttribute("data-theme", name);
    // Swap theme stylesheet
    let link = document.getElementById("theme-css");
    if (!link) {
      link = document.createElement("link");
      link.id = "theme-css";
      link.rel = "stylesheet";
      document.head.appendChild(link);
    }
    link.href = `/static/themes/${name}.css`;
    localStorage.setItem(KEY, name);
    // Update toggle button label
    const btn = document.getElementById("theme-toggle");
    if (btn) btn.textContent = { dark: "☀️", light: "🌙", "high-contrast": "🔆" }[name] || "🎨";
  }

  function load() {
    apply(localStorage.getItem(KEY) || "dark");
  }

  function cycle() {
    const current = document.documentElement.getAttribute("data-theme") || "dark";
    const next = THEMES[(THEMES.indexOf(current) + 1) % THEMES.length];
    apply(next);
  }

  return { apply, load, cycle };
})();

// ---------------------------------------------------------------------------
// Router
// ---------------------------------------------------------------------------
const Router = (() => {
  const pages = {
    login:     { el: "page-login",     module: () => typeof LoginPage     !== "undefined" && LoginPage.render()     },
    dashboard: { el: "page-dashboard", module: () => typeof DashboardPage !== "undefined" && DashboardPage.render() },
    services:  { el: "page-services",  module: () => typeof ServicesPage  !== "undefined" && ServicesPage.render()  },
    network:   { el: "page-network",   module: () => typeof NetworkPage   !== "undefined" && NetworkPage.render()   },
    docker:    { el: "page-docker",    module: () => typeof DockerPage    !== "undefined" && DockerPage.render()    },
    system:    { el: "page-system",    module: () => typeof SystemPage    !== "undefined" && SystemPage.render()    },
  };

  let _current = null;

  function navigate(hash) {
    const name = (hash || "").replace(/^#/, "") || "dashboard";

    // Auth gate
    if (name !== "login" && !sessionStorage.getItem("onryo_token")) {
      // Check cookie exists (httpOnly – can't read, so probe /api/auth/me)
      _checkAuthThenRoute(name);
      return;
    }

    _show(name);
  }

  async function _checkAuthThenRoute(target) {
    try {
      await Api.get("/api/auth/me");
      // Cookie is valid
      _show(target);
    } catch (_) {
      _show("login");
    }
  }

  function _show(name) {
    if (!pages[name]) name = "dashboard";
    if (_current === name) return;

    // Hide all pages
    Object.values(pages).forEach(p => {
      const el = document.getElementById(p.el);
      if (el) el.hidden = true;
    });

    // Show target
    const target = pages[name];
    const el = document.getElementById(target.el);
    if (el) el.hidden = false;

    // Update nav active state
    document.querySelectorAll(".nav-link").forEach(a => {
      a.classList.toggle("active", a.getAttribute("href") === `#${name}`);
    });

    _current = name;
    target.module();
  }

  function init() {
    window.addEventListener("hashchange", () => navigate(location.hash));
    window.addEventListener("onryo:authed", () => navigate("#dashboard"));
    navigate(location.hash);
  }

  return { init, navigate };
})();

// ---------------------------------------------------------------------------
// Logout button
// ---------------------------------------------------------------------------
function setupLogout() {
  const btn = document.getElementById("logout-btn");
  if (!btn) return;
  btn.addEventListener("click", async () => {
    await Api.post("/api/auth/logout").catch(() => {});
    sessionStorage.removeItem("onryo_token");
    Router.navigate("#login");
  });
}

// ---------------------------------------------------------------------------
// Toast notifications
// ---------------------------------------------------------------------------
const Toast = (() => {
  let _container = null;

  function _ensure() {
    if (_container) return;
    _container = document.createElement("div");
    _container.id = "toast-container";
    _container.setAttribute("aria-live", "polite");
    document.body.appendChild(_container);
  }

  function show(message, type = "info", durationMs = 3500) {
    _ensure();
    const t = document.createElement("div");
    t.className = `toast toast-${type}`;
    t.textContent = message;
    _container.appendChild(t);
    // Animate in
    requestAnimationFrame(() => t.classList.add("toast-visible"));
    setTimeout(() => {
      t.classList.remove("toast-visible");
      t.addEventListener("transitionend", () => t.remove(), { once: true });
    }, durationMs);
  }

  const info    = (msg, ms) => show(msg, "info", ms);
  const success = (msg, ms) => show(msg, "success", ms);
  const error   = (msg, ms) => show(msg, "error", ms);
  const warn    = (msg, ms) => show(msg, "warn", ms);

  return { show, info, success, error, warn };
})();

// ---------------------------------------------------------------------------
// Boot
// ---------------------------------------------------------------------------
document.addEventListener("DOMContentLoaded", () => {
  Theme.load();
  setupLogout();
  document.getElementById("theme-toggle")?.addEventListener("click", Theme.cycle);
  Router.init();
});
