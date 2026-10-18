/* Onryo – System page */

async function renderSystem() {
  const container = document.getElementById('system-page');
  container.innerHTML = `
    <div class="page-header"><h1 class="page-title">System</h1></div>

    <h2 class="section-heading">Application Settings</h2>
    <div id="app-settings-form" style="max-width:480px">Loading...</div>

    <h2 class="section-heading" style="margin-top:2rem">Dashboard Widgets</h2>
    <div id="widget-config">Loading...</div>

    <h2 class="section-heading" style="margin-top:2rem">Danger Zone</h2>
    <div class="card" style="border-color:#dc2626;max-width:480px">
      <p style="margin-bottom:1rem;color:var(--text-muted)">
        Uninstall Onryo — stops all services, removes all files, restores network and input state.
      </p>
      <button class="btn btn-danger" onclick="confirmUninstall()">Uninstall Onryo…</button>
    </div>`;

  const [settings, widgets] = await Promise.all([
    fetch('/api/system/settings').then(r => r.json()),
    fetch('/api/dashboard/widgets').then(r => r.json()),
  ]);

  renderAppSettings(settings);
  renderWidgetConfig(widgets);
}

function renderAppSettings(settings) {
  const el = document.getElementById('app-settings-form');
  el.innerHTML = `
    <div class="form-group">
      <label class="form-label">Scan interval (seconds)</label>
      <input class="form-input" id="setting-scan_interval" type="number" value="${settings.scan_interval || 60}" />
    </div>
    <div class="form-group">
      <label class="form-label">Input Lockout</label>
      <label class="toggle-switch">
        <input type="checkbox" id="setting-input_lockout" ${settings.input_lockout === '1' ? 'checked' : ''}
          onchange="saveSetting('input_lockout', this.checked ? '1' : '0')">
        <span class="toggle-slider"></span>
      </label>
      <small style="color:var(--text-muted); display:block; margin-top:0.25rem">
        Grabs keyboard/mouse/touchpad when no display is connected.
      </small>
    </div>
    <div style="display:flex;gap:0.5rem">
      <button class="btn btn-primary" onclick="saveScanInterval()">Save Scan Interval</button>
    </div>`;
}

async function saveSetting(key, value) {
  await fetch(`/api/system/settings/${key}`, {
    method: 'PUT',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({value}),
  });
}

async function saveScanInterval() {
  const v = document.getElementById('setting-scan_interval').value;
  await saveSetting('scan_interval', v);
  alert('Saved.');
}

function renderWidgetConfig(widgets) {
  const el = document.getElementById('widget-config');
  el.innerHTML = `
    <table>
      <thead><tr><th>Widget</th><th>Enabled</th><th>Position</th></tr></thead>
      <tbody>${widgets.map(w => `
        <tr>
          <td>${w.label}</td>
          <td>
            <label class="toggle-switch">
              <input type="checkbox" ${w.enabled ? 'checked' : ''}
                onchange="updateWidget('${w.widget_key}', this.checked, null)">
              <span class="toggle-slider"></span>
            </label>
          </td>
          <td>
            <input type="number" value="${w.position}" style="width:60px;background:var(--input-bg);color:var(--text);border:1px solid var(--border);border-radius:4px;padding:2px 6px;"
              onchange="updateWidget('${w.widget_key}', ${w.enabled ? 'true' : 'false'}, parseInt(this.value))">
          </td>
        </tr>`).join('')}
      </tbody>
    </table>`;
}

async function updateWidget(key, enabled, position) {
  await fetch(`/api/dashboard/widgets/${key}`, {
    method: 'PATCH',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({enabled, position}),
  });
}

async function confirmUninstall() {
  const hostname = prompt('Type the hostname to confirm uninstall:');
  if (!hostname) return;
  if (hostname !== location.hostname && hostname !== window.location.hostname) {
    alert('Hostname does not match. Uninstall cancelled.');
    return;
  }
  if (!confirm('This will PERMANENTLY remove Onryo. Are you sure?')) return;
  await fetch('/api/system/settings/uninstall', {
    method: 'PUT',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({value: 'confirm'}),
  });
  // Trigger uninstall via helper
  alert('Uninstall initiated. Check /var/log/onryo-uninstall.log for progress.');
}
