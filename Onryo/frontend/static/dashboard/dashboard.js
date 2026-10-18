/* Onryo – Dashboard page */

async function renderDashboard() {
  const container = document.getElementById('dashboard-page');
  container.innerHTML = `
    <div class="page-header">
      <h1 class="page-title">Dashboard</h1>
      <button class="btn btn-ghost" onclick="renderDashboard()">↻ Refresh</button>
    </div>
    <div class="widget-grid" id="widget-grid">
      <div class="card"><div class="card-title">Loading widgets...</div></div>
    </div>
    <h2 class="section-heading">Activity Feed</h2>
    <ul class="activity-feed" id="activity-feed">
      <li class="activity-item">Loading...</li>
    </ul>`;

  const [widgets, activity] = await Promise.all([
    fetch('/api/dashboard/widgets').then(r => r.json()),
    fetch('/api/dashboard/activity').then(r => r.json()),
  ]);

  // Render widgets
  const grid = document.getElementById('widget-grid');
  const activeWidgets = widgets.filter(w => w.enabled);
  if (activeWidgets.length === 0) {
    grid.innerHTML = '<p style="color:var(--text-muted)">No widgets enabled. Configure in System settings.</p>';
  } else {
    grid.innerHTML = activeWidgets.map(w => widgetCard(w)).join('');
    // Populate with live data
    populateWidgets();
  }

  // Render activity feed
  const feed = document.getElementById('activity-feed');
  feed.innerHTML = activity.length === 0
    ? '<li class="activity-item">No recent activity.</li>'
    : activity.map(a => `
        <li class="activity-item">
          <span class="activity-time">${a.created_at.slice(0,19).replace('T',' ')}</span>
          <span>[${a.event_type}]</span>
          <span>${a.message}</span>
        </li>`).join('');
}

function widgetCard(w) {
  return `<div class="card" id="widget-${w.widget_key}">
    <div class="card-title">${w.label}</div>
    <div class="card-value" id="wval-${w.widget_key}">—</div>
  </div>`;
}

async function populateWidgets() {
  // Service health
  try {
    const services = await fetch('/api/services').then(r => r.json());
    const running = services.filter(s => s.status === 'running').length;
    const el = document.getElementById('wval-service_health');
    if (el) el.textContent = `${running} / ${services.length} running`;
  } catch {}

  // Docker status
  try {
    const containers = await fetch('/api/docker/containers?all=true').then(r => r.json());
    const up = containers.filter(c => c.status === 'running').length;
    const el = document.getElementById('wval-docker_status');
    if (el) el.textContent = `${up} / ${containers.length} up`;
  } catch {}

  // Network status
  try {
    const adapters = await fetch('/api/network/adapters').then(r => r.json());
    const up = adapters.filter(a => a.state === 'up').length;
    const el = document.getElementById('wval-network_status');
    if (el) el.textContent = `${up} / ${adapters.length} adapters up`;
  } catch {}

  // System resources (battery hidden if not present — handled server-side)
  const resEl = document.getElementById('wval-system_resources');
  if (resEl) {
    try {
      const res = await fetch('/api/system/resources', {headers: {'X-Onryo-Token': localStorage.getItem('onryo_token')||''}}).then(r => r.json());
      resEl.textContent = `CPU ${res.cpu_percent}% · RAM ${res.memory.percent}% · ${res.disk.percent}% disk`;
    } catch { resEl.textContent = 'See System page'; }
  }

  // Purge-missing button (injects into DOM if card present)
  const purgeCard = document.getElementById('purge-card');
  if (purgeCard) {
    purgeCard.querySelector('button')?.addEventListener('click', async () => {
      const tok = localStorage.getItem('onryo_token') || '';
      const data = await fetch('/api/scan/purge-missing', {method:'POST', headers:{'X-Onryo-Token':tok}}).then(r => r.json());
      alert(data.removed.length ? 'Purged: ' + data.removed.join(', ') : 'Nothing to purge.');
    });
  }
}
