# Onryo – Architecture Overview

## Seven-service architecture

All components coordinate through a shared SQLite catalog database.
None of them import each other directly at runtime.

  onryo-core.service        FastAPI backend + web GUI SPA
  onryo-scan.service        One-shot discovery scanner (+ onryo-scan.timer)
  onryo-netmgr.service      Boot-time network setup (bridge, AP, client)
  onryo-input-guard.service evdev grab/release daemon
  onryo-svc-<name>.service  Generated per discovered service

## Boot order

  network-online.target
    └─> onryo-netmgr.service   (bridge, AP, client wifi)
          └─> onryo-scan.service (discover plugins → SQLite)
                └─> onryo-core.service (API + GUI)
                      └─> onryo-svc-*.service (per-plugin, enabled=true)
  onryo-input-guard.service (independent, after onryo-core)
  onryo-scan.timer           (every 60s rescan, independent)

## Privilege model

  onryo user  -- runs onryo-core, the scanner, and generates unit files
  root        -- runs onryo-netmgr, onryo-input-guard, privileged_helper

  onryo user has a sudoers entry for one script:
    /opt/onryo/backend/privileged_helper/helper.sh

  The helper is root-owned, not writable by the onryo user, and only
  accepts an explicit allow-list of actions (enable/disable/start/stop
  onryo-svc-* units, bridge-add/remove, wifi-reload, lockout-release,
  uninstall).

## Database tables

  services          -- discovered plugins, their state, enabled flag
  categories        -- type_key → display_name, icon
  settings_cache    -- per-service key/value cache (optional)
  network_profiles  -- saved Wi-Fi networks (priority ordered)
  dashboard_widgets -- per-user widget visibility + position
  app_settings      -- theme, admin password hash, scan interval, etc.
  activity_log      -- timestamped event feed (start/stop/error/scan)

## Config files (canonical, on disk)

  /etc/onryo/directories.json     -- watch directories for scanner
  /etc/onryo/network-roles.json   -- MAC → role mapping
  /etc/onryo/wifi-networks.json   -- saved client Wi-Fi networks
  /etc/onryo/ap-config.json       -- AP SSID, password, channel
  /etc/onryo/input-lockout.json   -- lockout enabled, grace period

## Runtime paths (created by installer)

  /opt/onryo/           -- application root
  /opt/onryo/venv/      -- Python virtualenv
  /opt/onryo/onryo.db   -- SQLite catalog database
  /opt/onryo/frontend/  -- SPA static files (served by FastAPI)
  /opt/onryo/plugins/   -- default plugin scan directory
  /opt/onryo/containers/ -- Docker Compose stacks (e.g. Minecraft)
  /var/log/onryo/       -- per-service and framework logs
