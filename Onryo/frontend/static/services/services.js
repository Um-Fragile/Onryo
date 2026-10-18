/* Onryo – Services page */

let _activeLogSocket = null;

async function renderServices() {
  const container = document.getElementById('services-page');
  container.innerHTML = `
    <div class="page-header">
      <h1 class="page-title">Services</h1>
      <button class="btn btn-primary" onclick="triggerScan()">⟳ Rescan</button>
    </div>
    <div id="service-list">Loading...</div>
    <!-- Settings modal -->
    <div id="settings-modal" style="display:none; position:fixed; inset:0; background:rgba(0,0,0,0.7); z-index:100; display:flex; align-items:center; justify-content:center;" onclick="closeSettings()">
      <div style="background:var(--card-bg);border:1px solid var(--border);border-radius:10px;padding:2rem;width:600px;max-width:95vw;max-height:80vh;overflow:auto;" onclick="event.stopPropagation()">
        <h2 id="settings-title" style="margin-bottom:1rem">Settings</h2>
        <textarea class="form-input" id="settings-editor" style="min-height:300px;font-family:monospace;"></textarea>
        <div style="display:flex;gap:0.5rem;margin-top:1rem;justify-content:flex-end">
          <button class="btn btn-ghost" onclick="closeSettings()">Cancel</button>
          <button class="btn btn-primary" onclick="saveSettings()">Save</button>
        </div>
      </div>
    </div>
    <!-- Log modal -->
    <div id="log-modal" style="display:none; position:fixed; inset:0; background:rgba(0,0,0,0.7); z-index:100; align-items:center; justify-content:center;" onclick="closeLog()">
      <div style="background:var(--card-bg);border:1px solid var(--border);border-radius:10px;padding:2rem;width:800px;max-width:95vw;" onclick="event.stopPropagation()">
        <h2 id="log-title" style="margin-bottom:1rem">Log</h2>
        <div class="log-output" id="log-output"></div>
        <div style="margin-top:1rem;text-align:right"><button class="btn btn-ghost" onclick="closeLog()">Close</button></div>
      </div>
    </div>`;

  await refreshServiceList();
}

async function refreshServiceList() {
  const services = await fetch('/api/services').then(r => r.json());
  const byType = {};
  for (const s of services) {
    (byType[s.type] = byType[s.type] || []).push(s);
  }
  const list = document.getElementById('service-list');
  if (!list) return;
  if (services.length === 0) {
    list.innerHTML = '<p style="color:var(--text-muted)">No services discovered yet. Click Rescan.</p>';
    return;
  }
  list.innerHTML = Object.entries(byType).map(([type, svcs]) => `
    <div class="service-section">
      <div class="section-heading">${type}</div>
      ${svcs.map(serviceCard).join('')}
    </div>`).join('');
}

function serviceCard(s) {
  const pillClass = `pill pill-${s.status}`;
  return `<div class="service-card">
    <div class="service-info">
      <div class="service-name">${s.name} <span class="${pillClass}">${s.status}</span></div>
      <div class="service-desc">${s.description || ''} ${s.version ? `<em>v${s.version}</em>` : ''}</div>
    </div>
    <label class="toggle-switch" title="${s.enabled ? 'Disable' : 'Enable'}">
      <input type="checkbox" ${s.enabled ? 'checked' : ''} onchange="toggleService(${s.id}, this.checked)">
      <span class="toggle-slider"></span>
    </label>
    ${s.settings_file ? `<button class="btn btn-ghost" onclick="openSettings(${s.id}, '${s.name}')">Settings</button>` : ''}
    <button class="btn btn-ghost" onclick="openLog(${s.id}, '${s.name}')">Log</button>
  </div>`;
}

async function toggleService(id, enabled) {
  await fetch(`/api/services/${id}/toggle`, {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({enabled}),
  });
  await refreshServiceList();
}

async function triggerScan() {
  const res = await fetch('/api/scan', {method: 'POST'}).then(r => r.json());
  alert(`Scan complete: ${res.discovered} service(s) found.`);
  await refreshServiceList();
}

let _editingServiceId = null;

async function openSettings(id, name) {
  _editingServiceId = id;
  const data = await fetch(`/api/services/${id}/settings`).then(r => r.json());
  document.getElementById('settings-title').textContent = `Settings – ${name}`;
  document.getElementById('settings-editor').value = data.raw || '';
  document.getElementById('settings-modal').style.display = 'flex';
}

function closeSettings() {
  document.getElementById('settings-modal').style.display = 'none';
  _editingServiceId = null;
}

async function saveSettings() {
  if (!_editingServiceId) return;
  const content = document.getElementById('settings-editor').value;
  const res = await fetch(`/api/services/${_editingServiceId}/settings`, {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({content}),
  });
  if (res.ok) { closeSettings(); }
  else { alert('Save failed: ' + await res.text()); }
}

function openLog(id, name) {
  document.getElementById('log-title').textContent = `Log – ${name}`;
  document.getElementById('log-output').textContent = '';
  document.getElementById('log-modal').style.display = 'flex';

  if (_activeLogSocket) _activeLogSocket.close();
  const proto = location.protocol === 'https:' ? 'wss' : 'ws';
  _activeLogSocket = new WebSocket(`${proto}://${location.host}/ws/logs/${id}`);
  const out = document.getElementById('log-output');
  _activeLogSocket.onmessage = (e) => {
    out.textContent += e.data + '\n';
    out.scrollTop = out.scrollHeight;
  };
}

function closeLog() {
  if (_activeLogSocket) { _activeLogSocket.close(); _activeLogSocket = null; }
  document.getElementById('log-modal').style.display = 'none';
}
