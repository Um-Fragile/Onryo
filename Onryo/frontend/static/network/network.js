/* Onryo – Network page */

async function renderNetwork() {
  const container = document.getElementById('network-page');
  container.innerHTML = `
    <div class="page-header"><h1 class="page-title">Network</h1></div>
    <h2 class="section-heading">Adapters</h2>
    <div id="adapter-table">Loading...</div>
    <h2 class="section-heading" style="margin-top:2rem">Bridge Members (br0)</h2>
    <div id="bridge-members">Loading...</div>
    <h2 class="section-heading" style="margin-top:2rem">Wi-Fi Client Networks</h2>
    <div id="wifi-list">Loading...</div>
    <div style="margin-top:1rem">
      <button class="btn btn-primary" onclick="showAddWifi()">+ Add Network</button>
    </div>
    <div id="add-wifi-form" style="display:none; margin-top:1rem; background:var(--card-bg); border:1px solid var(--border); border-radius:8px; padding:1.25rem; max-width:400px;">
      <div class="form-group">
        <label class="form-label">SSID</label>
        <input class="form-input" id="wifi-ssid" type="text" placeholder="Network name" />
      </div>
      <div class="form-group">
        <label class="form-label">Password</label>
        <input class="form-input" id="wifi-psk" type="password" placeholder="WPA2 password" />
      </div>
      <div class="form-group">
        <label class="form-label">Priority (higher = preferred)</label>
        <input class="form-input" id="wifi-priority" type="number" value="0" />
      </div>
      <div style="display:flex;gap:0.5rem">
        <button class="btn btn-ghost" onclick="document.getElementById('add-wifi-form').style.display='none'">Cancel</button>
        <button class="btn btn-primary" onclick="addWifi()">Save</button>
      </div>
    </div>`;

  await Promise.all([loadAdapters(), loadBridgeMembers(), loadWifiNetworks()]);
}

async function loadAdapters() {
  const adapters = await fetch('/api/network/adapters').then(r => r.json());
  const tbody = adapters.map(a => `
    <tr>
      <td>${a.name}</td>
      <td><code>${a.mac}</code></td>
      <td>${a.state}</td>
      <td>
        <select onchange="setRole('${a.mac}', this.value)" style="background:var(--input-bg);color:var(--text);border:1px solid var(--border);border-radius:4px;padding:2px 4px;">
          ${['uplink','client','ap','pentest','unassigned'].map(r =>
            `<option value="${r}" ${a.role===r?'selected':''}>${r}</option>`
          ).join('')}
        </select>
      </td>
      <td>
        ${a.role !== 'uplink' ? `<button class="btn btn-ghost" onclick="bridgeAdd('${a.name}')">+ Bridge</button>` : '<em style="color:var(--text-muted)">protected</em>'}
      </td>
    </tr>`).join('');

  document.getElementById('adapter-table').innerHTML = `
    <table>
      <thead><tr><th>Name</th><th>MAC</th><th>State</th><th>Role</th><th>Actions</th></tr></thead>
      <tbody>${tbody}</tbody>
    </table>`;
}

async function loadBridgeMembers() {
  const data = await fetch('/api/network/bridge').then(r => r.json());
  const el = document.getElementById('bridge-members');
  if (!data.members.length) {
    el.innerHTML = '<p style="color:var(--text-muted)">No interfaces in bridge.</p>';
    return;
  }
  el.innerHTML = data.members.map(m => `
    <span style="display:inline-flex;align-items:center;gap:0.5rem;background:var(--card-bg);border:1px solid var(--border);border-radius:6px;padding:0.3rem 0.75rem;margin:0.25rem;">
      ${m}
      <button class="btn btn-ghost" style="padding:0.15rem 0.5rem;font-size:0.75rem;" onclick="bridgeRemove('${m}')">✕</button>
    </span>`).join('');
}

async function loadWifiNetworks() {
  const networks = await fetch('/api/network/wifi').then(r => r.json());
  const el = document.getElementById('wifi-list');
  if (!networks.length) {
    el.innerHTML = '<p style="color:var(--text-muted)">No saved networks.</p>';
    return;
  }
  el.innerHTML = `<table>
    <thead><tr><th>SSID</th><th>Priority</th><th>Enabled</th><th></th></tr></thead>
    <tbody>${networks.map(n => `
      <tr>
        <td>${n.ssid}</td>
        <td>${n.priority}</td>
        <td>${n.enabled ? '✓' : '—'}</td>
        <td><button class="btn btn-ghost" onclick="removeWifi('${n.ssid}')">Remove</button></td>
      </tr>`).join('')}
    </tbody>
  </table>`;
}

async function setRole(mac, role) {
  try {
    await fetch('/api/network/role', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({mac, role}),
    });
  } catch (e) { alert('Failed to set role: ' + e.message); }
}

async function bridgeAdd(iface) {
  if (!confirm(`Add ${iface} to br0?`)) return;
  const res = await fetch('/api/network/bridge/add', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({iface}),
  });
  if (!res.ok) { alert('Failed: ' + await res.text()); }
  else loadBridgeMembers();
}

async function bridgeRemove(iface) {
  await fetch('/api/network/bridge/remove', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({iface}),
  });
  loadBridgeMembers();
}

function showAddWifi() {
  document.getElementById('add-wifi-form').style.display = 'block';
}

async function addWifi() {
  const ssid     = document.getElementById('wifi-ssid').value.trim();
  const psk      = document.getElementById('wifi-psk').value;
  const priority = parseInt(document.getElementById('wifi-priority').value, 10) || 0;
  if (!ssid) { alert('SSID required'); return; }
  await fetch('/api/network/wifi', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({ssid, psk, priority}),
  });
  document.getElementById('add-wifi-form').style.display = 'none';
  loadWifiNetworks();
}

async function removeWifi(ssid) {
  if (!confirm(`Remove network "${ssid}"?`)) return;
  await fetch(`/api/network/wifi/${encodeURIComponent(ssid)}`, {method: 'DELETE'});
  loadWifiNetworks();
}

/* ============================================================
   Access Point section – appended to network page
   ============================================================ */

async function renderNetwork() {
  // Call the original renderNetwork stub and append AP section
  const container = document.getElementById('network-page');
  if (!container) return;
  // Append AP section if not already present
  if (!document.getElementById('ap-section')) {
    container.insertAdjacentHTML('beforeend', `
      <h2 class="section-heading" style="margin-top:2rem">Access Point</h2>
      <div id="ap-section">
        <div id="ap-config-body">Loading…</div>
        <div style="margin-top:1rem;display:flex;gap:.5rem">
          <button class="btn btn-success" onclick="startAP()">Start AP</button>
          <button class="btn btn-danger"  onclick="stopAP()">Stop AP</button>
          <button class="btn btn-ghost"   onclick="regenAPPassword()">&#128260; Regen Password</button>
        </div>
        <h3 style="margin-top:1.5rem">Connected Clients</h3>
        <div id="ap-clients">Loading…</div>
        <button class="btn btn-ghost" style="margin-top:.5rem" onclick="loadAPClients()">Refresh Clients</button>
      </div>
    `);
  }
  await Promise.all([loadAPConfig(), loadAPClients()]);
}

async function loadAPConfig() {
  const body = document.getElementById('ap-config-body');
  try {
    const [cfg, chans] = await Promise.all([
      fetch('/api/network/ap').then(r => r.json()),
      fetch('/api/network/ap/channels').then(r => r.json()).catch(() => null),
    ]);

    const is5g = cfg.band === 'a';
    const chList2g = chans?.channels_2g || Array.from({length:13}, (_,i)=>i+1);
    const chList5g = chans?.channels_5g || [36,40,44,48,149,153,157,161,165];
    const supportsAC = chans?.supports_ac ?? true;

    // Build channel options for the current band
    const channelOptions = (is5g ? chList5g : chList2g)
      .map(ch => `<option value="${ch}" ${cfg.channel==ch?'selected':''}>${ch}</option>`)
      .join('');

    // Channel hop list defaults
    const hopListStr = (cfg.channel_hop_list||[]).join(', ');

    body.innerHTML = `
      <div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(190px,1fr));gap:1rem;margin-top:.5rem">

        <div class="form-group">
          <label class="form-label">SSID</label>
          <input id="ap-ssid" class="form-input" value="${cfg.ssid||''}" />
        </div>

        <div class="form-group">
          <label class="form-label">Password</label>
          <input id="ap-password" class="form-input" value="${cfg.password||''}" />
        </div>

        <div class="form-group">
          <label class="form-label">Country Code</label>
          <input id="ap-country" class="form-input" value="${cfg.country||'US'}" maxlength="2" style="max-width:80px;text-transform:uppercase" />
        </div>

        <div class="form-group">
          <label class="form-label">Band</label>
          <select id="ap-band" class="form-input" onchange="onAPBandChange()" style="max-width:160px">
            <option value="bg" ${!is5g?'selected':''}>2.4 GHz (b/g/n)</option>
            <option value="a"  ${is5g ?'selected':''}>5 GHz (a/n/ac)</option>
          </select>
        </div>

        <div class="form-group">
          <label class="form-label">Channel width</label>
          <select id="ap-width" class="form-input" style="max-width:120px">
            <option value="20" ${cfg.width==20?'selected':''}>20 MHz</option>
            <option value="40" ${cfg.width==40?'selected':''}>40 MHz (HT40)</option>
            ${is5g && supportsAC ? `<option value="80" ${cfg.width==80?'selected':''}>80 MHz (VHT)</option>` : ''}
          </select>
        </div>

        <div class="form-group">
          <label class="form-label">Channel</label>
          <select id="ap-channel" class="form-input" style="max-width:120px">
            ${channelOptions}
          </select>
          <button class="btn btn-ghost" style="margin-top:.3rem;font-size:.8rem" onclick="apBestChannel()">
            &#128270; Auto-select best
          </button>
        </div>

        ${is5g && supportsAC ? `
        <div class="form-group">
          <label class="form-label" style="display:flex;align-items:center;gap:.5rem">
            <input type="checkbox" id="ap-ieee80211ac" ${cfg.ieee80211ac!==false?'checked':''} />
            Enable 802.11ac (VHT)
          </label>
        </div>` : ''}

        <div class="form-group">
          <label class="form-label">AP IP Address</label>
          <input id="ap-ip" class="form-input" value="${cfg.ap_ip||'192.168.42.1'}" />
        </div>

      </div>

      <!-- Channel hopping -->
      <details style="margin-top:1rem">
        <summary style="cursor:pointer;font-weight:600;padding:.4rem 0">Channel Hopping</summary>
        <div style="margin-top:.75rem;display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:1rem">

          <div class="form-group">
            <label class="form-label" style="display:flex;align-items:center;gap:.5rem">
              <input type="checkbox" id="ap-hop-enabled" ${cfg.channel_hop?'checked':''} />
              Enable on AP start
            </label>
          </div>

          <div class="form-group">
            <label class="form-label">Hop interval (seconds)</label>
            <input id="ap-hop-interval" class="form-input" type="number" value="${cfg.channel_hop_interval||30}" min="5" max="3600" style="max-width:100px" />
          </div>

          <div class="form-group" style="grid-column:1/-1">
            <label class="form-label">Channel list (comma-separated, blank = auto)</label>
            <input id="ap-hop-list" class="form-input" value="${hopListStr}" placeholder="e.g. 36, 40, 44, 48" />
          </div>

          <div style="display:flex;gap:.5rem;flex-wrap:wrap;grid-column:1/-1">
            <button class="btn btn-success" onclick="startChannelHopping()">Start Hopping</button>
            <button class="btn btn-danger"  onclick="stopChannelHopping()">Stop Hopping</button>
            <button class="btn btn-ghost"   onclick="getHopStatus()">Status</button>
          </div>
          <div id="ap-hop-status" style="grid-column:1/-1;font-size:.85rem;color:var(--text-muted)"></div>

        </div>
      </details>

      <div style="margin-top:1rem;display:flex;gap:.5rem;flex-wrap:wrap">
        <button class="btn btn-primary" onclick="saveAPConfig()">Save AP Config</button>
      </div>
    `;
  } catch (err) {
    body.innerHTML = `<p style="color:var(--danger)">Failed: ${err.message}</p>`;
  }
}

async function onAPBandChange() {
  // Re-populate channel list when band changes without full reload
  const band = document.getElementById('ap-band')?.value;
  const widthSel = document.getElementById('ap-width');
  if (!band || !widthSel) return;
  // Remove VHT option if switching to 2.4
  const vhtOpt = widthSel.querySelector('option[value="80"]');
  if (band !== 'a' && vhtOpt) vhtOpt.remove();
  // Refresh channel select
  try {
    const chans = await fetch('/api/network/ap/channels').then(r => r.json());
    const chList = band === 'a' ? chans.channels_5g : chans.channels_2g;
    const chSel = document.getElementById('ap-channel');
    if (chSel && chList) {
      chSel.innerHTML = chList.map(ch => `<option value="${ch}">${ch}</option>`).join('');
      // Default sensible channel
      chSel.value = band === 'a' ? '36' : '6';
    }
  } catch (_) {}
}

async function apBestChannel() {
  try {
    const data = await fetch('/api/network/ap/best-channel', {method:'POST'}).then(r => r.json());
    const chSel = document.getElementById('ap-channel');
    if (chSel) chSel.value = data.best_channel;
    alert('Recommended channel: ' + data.best_channel);
  } catch (err) {
    alert('Scan failed: ' + err.message);
  }
}

async function startChannelHopping() {
  const intervalEl = document.getElementById('ap-hop-interval');
  const listEl     = document.getElementById('ap-hop-list');
  const interval   = parseInt(intervalEl?.value||'30');
  const rawList    = listEl?.value.trim();
  const channel_list = rawList
    ? rawList.split(',').map(s => parseInt(s.trim())).filter(n => !isNaN(n))
    : [];
  try {
    const data = await fetch('/api/network/ap/hop/start', {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify({channel_list, interval}),
    }).then(r => r.json());
    _showHopStatus(data.status);
    alert('Channel hopping started');
  } catch (err) { alert('Failed: ' + err.message); }
}

async function stopChannelHopping() {
  await fetch('/api/network/ap/hop/stop', {method:'POST'});
  document.getElementById('ap-hop-status').textContent = 'Hopper stopped.';
  alert('Channel hopping stopped');
}

async function getHopStatus() {
  try {
    const s = await fetch('/api/network/ap/hop/status').then(r => r.json());
    _showHopStatus(s);
  } catch (err) { alert(err.message); }
}

function _showHopStatus(s) {
  const el = document.getElementById('ap-hop-status');
  if (!el) return;
  if (!s.running) { el.textContent = 'Hopper not running.'; return; }
  el.textContent = `Running · current channel: ${s.current_ch} · hops: ${s.hop_count} · interval: ${s.interval}s · list: [${s.channel_list.join(', ')}]`;
}

async function saveAPConfig() {
  const getVal  = id => document.getElementById(id)?.value?.trim();
  const getInt  = id => parseInt(document.getElementById(id)?.value) || 0;
  const getBool = id => document.getElementById(id)?.checked ?? false;
  const rawList = getVal('ap-hop-list');
  const cfg = {
    ssid:                 getVal('ap-ssid'),
    password:             document.getElementById('ap-password')?.value||'',
    country:              (getVal('ap-country')||'US').toUpperCase().slice(0,2),
    band:                 document.getElementById('ap-band')?.value || 'bg',
    width:                getInt('ap-width') || 20,
    ieee80211ac:          getBool('ap-ieee80211ac'),
    channel:              getInt('ap-channel') || 6,
    ap_ip:                getVal('ap-ip') || '192.168.42.1',
    channel_hop:          getBool('ap-hop-enabled'),
    channel_hop_interval: getInt('ap-hop-interval') || 30,
    channel_hop_list:     rawList
      ? rawList.split(',').map(s=>parseInt(s.trim())).filter(n=>!isNaN(n))
      : [],
  };
  const res = await fetch('/api/network/ap', {
    method: 'POST',
    headers: {'Content-Type':'application/json'},
    body: JSON.stringify(cfg),
  });
  alert(res.ok ? 'AP config saved. Restart AP to apply.' : 'Save failed: ' + await res.text());
}

async function startAP() {
  const res = await fetch('/api/network/ap/start', {method:'POST'});
  alert(res.ok ? 'AP starting…' : 'Failed: ' + await res.text());
}

async function stopAP() {
  const res = await fetch('/api/network/ap/stop', {method:'POST'});
  alert(res.ok ? 'AP stopped.' : 'Failed: ' + await res.text());
}

async function regenAPPassword() {
  const res = await fetch('/api/network/ap/regen-password', {method:'POST'});
  if (!res.ok) { alert('Failed'); return; }
  const data = await res.json();
  const el = document.getElementById('ap-password');
  if (el) el.value = data.password;
  alert('New password generated: ' + data.password + '\nSave config to persist it.');
}

async function loadAPClients() {
  const el = document.getElementById('ap-clients');
  if (!el) return;
  try {
    const data = await fetch('/api/network/ap/clients').then(r => r.json());
    if (!data.clients || !data.clients.length) {
      el.innerHTML = '<p style="color:var(--text-muted)">No clients connected.</p>';
      return;
    }
    el.innerHTML = `<table>
      <thead><tr><th>MAC</th><th>IP</th><th>Hostname</th></tr></thead>
      <tbody>${data.clients.map(c => `<tr><td><code>${c.mac}</code></td><td>${c.ip}</td><td>${c.hostname||'—'}</td></tr>`).join('')}</tbody>
    </table>`;
  } catch (_) {
    el.innerHTML = '<p style="color:var(--text-muted)">Client list unavailable.</p>';
  }
}
