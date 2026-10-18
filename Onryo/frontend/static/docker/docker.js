/* Onryo – Docker page */

async function renderDocker() {
  const container = document.getElementById('docker-page');
  container.innerHTML = `
    <div class="page-header">
      <h1 class="page-title">Docker</h1>
      <div style="display:flex;gap:0.5rem">
        <input id="pull-image-input" class="form-input" style="width:260px" placeholder="image:tag" />
        <button class="btn btn-primary" onclick="pullImage()">Pull Image</button>
      </div>
    </div>
    <h2 class="section-heading">Containers</h2>
    <div id="container-list">Loading...</div>
    <h2 class="section-heading" style="margin-top:2rem">Images</h2>
    <div id="image-list">Loading...</div>
    <!-- Log modal -->
    <div id="docker-log-modal" style="display:none;position:fixed;inset:0;background:rgba(0,0,0,0.7);z-index:100;align-items:center;justify-content:center;" onclick="closeDockerLog()">
      <div style="background:var(--card-bg);border:1px solid var(--border);border-radius:10px;padding:2rem;width:800px;max-width:95vw;" onclick="event.stopPropagation()">
        <h2 id="docker-log-title" style="margin-bottom:1rem">Container Logs</h2>
        <div class="log-output" id="docker-log-output"></div>
        <div style="margin-top:1rem;text-align:right"><button class="btn btn-ghost" onclick="closeDockerLog()">Close</button></div>
      </div>
    </div>`;

  await Promise.all([loadContainers(), loadImages()]);
}

async function loadContainers() {
  let containers;
  try {
    containers = await fetch('/api/docker/containers?all=true').then(r => r.json());
  } catch {
    document.getElementById('container-list').innerHTML =
      '<p style="color:var(--text-muted)">Docker not available on this system.</p>';
    return;
  }

  if (!containers.length) {
    document.getElementById('container-list').innerHTML =
      '<p style="color:var(--text-muted)">No containers found.</p>';
    return;
  }

  document.getElementById('container-list').innerHTML = `
    <table>
      <thead><tr><th>Name</th><th>Image</th><th>Status</th><th>Ports</th><th>Actions</th></tr></thead>
      <tbody>${containers.map(c => `
        <tr>
          <td><code>${c.name}</code></td>
          <td>${c.image}</td>
          <td><span class="pill pill-${c.status === 'running' ? 'running' : 'stopped'}">${c.status}</span></td>
          <td style="font-size:0.78rem">${formatPorts(c.ports)}</td>
          <td style="display:flex;gap:0.25rem;flex-wrap:wrap">
            ${c.status === 'running'
              ? `<button class="btn btn-ghost" onclick="containerAction('${c.name}','stop')">Stop</button>
                 <button class="btn btn-ghost" onclick="containerAction('${c.name}','restart')">Restart</button>`
              : `<button class="btn btn-primary" onclick="containerAction('${c.name}','start')">Start</button>`}
            <button class="btn btn-ghost" onclick="viewDockerLog('${c.name}')">Logs</button>
            <button class="btn btn-danger" onclick="removeContainer('${c.name}')">✕</button>
          </td>
        </tr>`).join('')}
      </tbody>
    </table>`;
}

function formatPorts(ports) {
  if (!ports || !Object.keys(ports).length) return '—';
  return Object.entries(ports).map(([k, v]) => {
    if (!v) return k;
    return v.map(b => `${b.HostIp || ''}:${b.HostPort}→${k}`).join(', ');
  }).join(', ');
}

async function loadImages() {
  let images;
  try {
    images = await fetch('/api/docker/images').then(r => r.json());
  } catch {
    document.getElementById('image-list').innerHTML = '';
    return;
  }
  document.getElementById('image-list').innerHTML = `
    <table>
      <thead><tr><th>Tag</th><th>ID</th><th>Size</th></tr></thead>
      <tbody>${images.map(i => `
        <tr>
          <td>${i.tags.join(', ') || '<em>untagged</em>'}</td>
          <td><code>${i.id}</code></td>
          <td>${(i.size / 1024 / 1024).toFixed(1)} MB</td>
        </tr>`).join('')}
      </tbody>
    </table>`;
}

async function containerAction(name, action) {
  await fetch(`/api/docker/containers/${encodeURIComponent(name)}/${action}`, {method:'POST'});
  await loadContainers();
}

async function removeContainer(name) {
  if (!confirm(`Remove container "${name}"?`)) return;
  await fetch(`/api/docker/containers/${encodeURIComponent(name)}`, {method:'DELETE'});
  await loadContainers();
}

async function pullImage() {
  const image = document.getElementById('pull-image-input').value.trim();
  if (!image) { alert('Enter an image name'); return; }
  alert(`Pulling ${image}... (this may take a while)`);
  const res = await fetch('/api/docker/images/pull', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({image}),
  });
  if (res.ok) { await loadImages(); alert('Pull complete!'); }
  else alert('Pull failed: ' + await res.text());
}

async function viewDockerLog(name) {
  const data = await fetch(`/api/docker/containers/${encodeURIComponent(name)}/logs?tail=300`).then(r => r.json());
  document.getElementById('docker-log-title').textContent = `Logs – ${name}`;
  document.getElementById('docker-log-output').textContent = data.logs || '(empty)';
  document.getElementById('docker-log-modal').style.display = 'flex';
}

function closeDockerLog() {
  document.getElementById('docker-log-modal').style.display = 'none';
  // Close any live WS
  if (window._dockerLogSocket) {
    window._dockerLogSocket.close();
    window._dockerLogSocket = null;
  }
}

function openDockerLogWS(containerId) {
  const proto = location.protocol === 'https:' ? 'wss' : 'ws';
  const url = `${proto}://${location.host}/ws/docker/${encodeURIComponent(containerId)}/logs`;
  if (window._dockerLogSocket) {
    window._dockerLogSocket.close();
  }
  const output = document.getElementById('docker-log-output');
  output.textContent = '';
  const modal = document.getElementById('docker-log-modal');
  document.getElementById('docker-log-title').textContent = `Live Logs – ${containerId}`;
  modal.style.display = 'flex';
  const ws = new WebSocket(url);
  window._dockerLogSocket = ws;
  ws.onmessage = e => {
    output.textContent += e.data + '\n';
    output.scrollTop = output.scrollHeight;
  };
  ws.onerror = () => { output.textContent += '\n[WebSocket error]\n'; };
  ws.onclose = () => { output.textContent += '\n[Stream ended]\n'; };
}
