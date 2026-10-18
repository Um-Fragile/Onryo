# Onryo – Plugin Author Guide

## What is a plugin?

A plugin (or "service") is any directory containing:

  info.json       -- required manifest
  run.sh          -- entrypoint the service manager wraps
  settings.yaml   -- optional, rendered in the GUI settings editor

Drop the directory into any path listed in /etc/onryo/directories.json
and it appears in the Services page on the next scan (automatic every 60s,
or click "Rescan" in the GUI).  No core code changes required.

---

## info.json schema

{
  "name":               "My Script",          // required, shown as card title
  "description":        "One-line summary",   // required, shown below title
  "type":               "utility",            // required — see Types below
  "entrypoint":         "run.sh",             // required, relative to plugin dir
  "log_location":       "/var/log/onryo/my-script.log",  // optional
  "settings_file":      "settings.yaml",      // optional; YAML, JSON, or .env
  "version":            "1.0.0",              // optional
  "enabled_by_default": false                 // optional (default false)
}

### Types

  network     -- networking tools (scanners, monitors, VPNs)
  automation  -- scheduled tasks, IFTTT-style scripts
  pentest     -- security / recon tools (gets access to pentest adapter)
  media       -- media servers, downloaders, players
  utility     -- general-purpose scripts
  docker      -- Docker Compose stacks
  custom      -- anything else (won't break the UI)

---

## run.sh contract

- Runs in WorkingDirectory = the plugin directory.
- Receives no arguments by default (the service manager wraps it in a
  systemd unit with ExecStart=/bin/bash entrypoint).
- For long-running services: loop forever or use a process that doesn't exit.
  systemd will restart on failure (RestartSec=5s).
- For one-shot jobs: exit 0 on success.  The GUI will show status=stopped
  after the process exits, which is expected for one-shot scripts.
- Write log output to stdout/stderr — systemd redirects it to log_location.

---

## settings_file

Supported formats: .yaml, .json, .env

The GUI settings editor opens this file as a form (simple key=value YAML/JSON)
or falls back to a raw syntax-highlighted text editor.  Saves go through a
backup-then-replace pattern; the previous version is kept as settings.yaml.bak.

The service is restarted automatically after a settings save if it's currently
running.

---

## Example plugin layout

  my-scanner/
  ├── info.json
  ├── run.sh
  └── settings.yaml

  info.json:
  {
    "name": "My Scanner",
    "description": "Scans local subnet every N minutes",
    "type": "network",
    "entrypoint": "run.sh",
    "log_location": "/var/log/onryo/my-scanner.log",
    "settings_file": "settings.yaml",
    "version": "1.0.0",
    "enabled_by_default": false
  }

  settings.yaml:
  interval_minutes: 5
  subnet: 192.168.1.0/24

  run.sh:
  #!/bin/bash
  INTERVAL=$(grep interval_minutes settings.yaml | awk '{print $2}')
  while true; do
    nmap -sn "$(grep subnet settings.yaml | awk '{print $2}')"
    sleep $((INTERVAL * 60))
  done

---

## Pentest adapter

Plugins of type "pentest" may request exclusive access to the pentest adapter.
Only one pentest plugin should be active at a time — the GUI shows which plugin
currently owns the adapter to prevent two tools fighting over the same radio.

The adapter is left unmanaged by NetworkManager (set to 'unmanaged' on boot),
so your script can call `ip link set <iface> up` and use it freely.

---

## API reference (brief)

GET  /api/services              -- list all services
GET  /api/services/{id}         -- single service
POST /api/services/{id}/toggle  -- {"enabled": true|false}
GET  /api/services/{id}/status  -- {"status": "running|stopped|error"}
GET  /api/services/{id}/settings
POST /api/services/{id}/settings -- {"content": "..."}
POST /api/scan                  -- trigger an on-demand scan

Full OpenAPI docs available at http://<host>:8080/docs when Onryo is running.
