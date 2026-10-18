# Onryo

Onryo is a self-hosted homelab server management framework.
It provides a web UI and REST/WebSocket API for:

  - Plugin/container discovery and management
  - Systemd service control (start, stop, enable, disable, live logs)
  - Network adapter role assignment, bridge creation, Wi-Fi client networks
  - Wireless Access Point management (hostapd + dnsmasq)
  - Docker container lifecycle management with live log streaming
  - Input device lockout (EVIOCGRAB) for headless kiosk use
  - System resource monitoring (CPU, RAM, disk, temperature)
  - Settings versioning with rotating backups

---

## Quick start (single command)

    sudo bash install.sh

The installer is interactive by default.
For unattended install, copy preseed.json.example to preseed.json,
fill in your values, then run:

    sudo bash install.sh --non-interactive --config preseed.json

After install the web UI is reachable at:

    http://<your-server-ip>:8080

Default credentials are printed at the end of the install run and
stored in /etc/onryo/credentials (readable only by root and the onryo user).

---

## Directory layout

    Onryo/
      backend/
        api/               FastAPI server (REST + WebSocket)
        auth/              Session token + password management
        db/                SQLite schema + helpers
        docker_manager/    Docker Engine API wrapper
        input_guard/       evdev EVIOCGRAB daemon
        network_manager/   Adapter roles, bridge, Wi-Fi, hostapd/dnsmasq AP
        privileged_helper/ Root-owned narrow-scope bash helper
        scanner/           Plugin discovery, inotify watcher
        service_manager/   Systemd unit generator + settings versioning
        system_resources/  psutil-based resource metrics
        requirements.txt
      containers/
        minecraft/         Example Docker-based container plugin
      docs/
        architecture.md
        plugin-author-guide.md
      frontend/
        index.html         SPA shell
        static/
          app.css          Base styles
          app.js           Router + auth gate + API client
          themes/          dark.css  light.css  high-contrast.css
          dashboard/
          docker/
          login/
          network/
          services/
          system/
      plugins/
        example-script/    Starter utility plugin
      systemd/
        onryo-core.service
        onryo-scan.service + .timer
        onryo-netmgr.service
        onryo-input-guard.service
        99-onryo-input.rules
      install.sh
      uninstall.sh
      preseed.json.example

---

## Architecture overview

See docs/architecture.md for the full description.
Key points:

  - The main service runs as the unprivileged user "onryo".
  - All privileged operations (network config, AP start/stop, input grab,
    systemd unit install) go through backend/privileged_helper/helper.sh,
    which is owned by root and installed setuid or invoked via sudo with a
    tight sudoers rule written by install.sh.
  - Docker operations go through docker_manager.py; the Docker socket is
    never exposed directly to the frontend.
  - The SQLite database at /var/lib/onryo/onryo.db is a cache.
    info.json files on disk are the canonical source of truth.
    Dropping or rebuilding the DB is safe at any time; the scanner recreates it.

---

## Plugin authoring

See docs/plugin-author-guide.md.
The minimum required file in a plugin directory is info.json:

    {
      "name":        "my-plugin",
      "version":     "1.0.0",
      "description": "What it does",
      "type":        "utility",
      "entrypoint":  "run.sh"
    }

Supported types: service, docker, utility, network, pentest-adapter.

---

## API

The REST API is documented at http://<server>:8080/docs (Swagger UI, auto-generated).
Authentication: all endpoints (except POST /api/auth/login) require the header:

    X-Onryo-Token: <token>

Obtain a token via:

    POST /api/auth/login  {"password": "your-password"}

WebSocket endpoints:

    ws://<server>:8080/ws/services/<service-name>/logs
    ws://<server>:8080/ws/docker/<container-id>/logs

---

## Uninstall

    sudo bash uninstall.sh

Flags:
  --keep-config     Preserve /etc/onryo/
  --keep-logs       Preserve /var/log/onryo/
  --remove-docker   Also remove Docker itself (use with caution)

---

## Themes

Three themes ship out of the box: dark (default), light, high-contrast.
Toggle via the button in the top-right corner of the UI.
Theme preference is saved in localStorage.

---

## Development

    cd backend
    python -m venv .venv
    source .venv/bin/activate
    pip install -r requirements.txt
    ONRYO_FRONTEND=../frontend uvicorn api.app:app --reload --port 8080

The API docs live at http://localhost:8080/docs.
