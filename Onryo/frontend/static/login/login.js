/* ============================================================
   Onryo – Login page controller
   Shown when no valid session token exists.
   ============================================================ */

const LoginPage = (() => {
  let _el = null;

  function render() {
    _el = document.getElementById("page-login");
    if (!_el) return;
    _el.innerHTML = `
      <div class="login-wrap">
        <div class="login-card card">
          <div class="login-logo">
            <span class="login-icon">&#9760;</span>
            <h1>Onryo</h1>
            <p class="login-subtitle">Homelab Server Manager</p>
          </div>
          <form id="login-form" autocomplete="on">
            <label for="login-password">Password</label>
            <input
              type="password"
              id="login-password"
              name="password"
              placeholder="Admin password"
              autofocus
              required
            />
            <button type="submit" class="btn btn-primary" id="login-btn">
              Sign in
            </button>
            <p id="login-error" class="login-error" hidden></p>
          </form>
        </div>
      </div>
    `;

    document.getElementById("login-form").addEventListener("submit", _handleLogin);
  }

  async function _handleLogin(e) {
    e.preventDefault();
    const btn = document.getElementById("login-btn");
    const errEl = document.getElementById("login-error");
    const pw = document.getElementById("login-password").value;

    btn.disabled = true;
    btn.textContent = "Signing in…";
    errEl.hidden = true;

    try {
      const res = await fetch("/api/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ password: pw }),
        credentials: "include",
      });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data.detail || "Invalid password");
      }
      const data = await res.json();
      // Store token in sessionStorage for Bearer header use
      sessionStorage.setItem("onryo_token", data.token);
      // Navigate to dashboard
      window.location.hash = "#dashboard";
      window.dispatchEvent(new Event("onryo:authed"));
    } catch (err) {
      errEl.textContent = err.message;
      errEl.hidden = false;
    } finally {
      btn.disabled = false;
      btn.textContent = "Sign in";
    }
  }

  return { render };
})();
