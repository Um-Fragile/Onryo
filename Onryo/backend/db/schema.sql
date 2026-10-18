-- Onryo SQLite schema
-- The DB is a cache; info.json files on disk are canonical.

CREATE TABLE IF NOT EXISTS services (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    name          TEXT    NOT NULL,
    description   TEXT,
    type          TEXT    NOT NULL DEFAULT 'custom',
    path          TEXT    NOT NULL UNIQUE,
    entrypoint    TEXT,
    log_location  TEXT,
    settings_file TEXT,
    version       TEXT,
    enabled       INTEGER NOT NULL DEFAULT 0,
    status        TEXT    NOT NULL DEFAULT 'stopped',  -- running|stopped|error|missing
    last_seen     TEXT,
    created_at    TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS categories (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    type_key     TEXT    NOT NULL UNIQUE,
    display_name TEXT    NOT NULL,
    icon         TEXT    NOT NULL DEFAULT 'puzzle-piece'
);

INSERT OR IGNORE INTO categories (type_key, display_name, icon) VALUES
    ('network',    'Network',    'network-wired'),
    ('automation', 'Automation', 'robot'),
    ('pentest',    'Pentest',    'bug'),
    ('media',      'Media',      'film'),
    ('utility',    'Utility',    'tools'),
    ('docker',     'Docker',     'docker'),
    ('custom',     'Custom',     'star');

CREATE TABLE IF NOT EXISTS settings_cache (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    service_id INTEGER NOT NULL REFERENCES services(id) ON DELETE CASCADE,
    key        TEXT    NOT NULL,
    value      TEXT,
    UNIQUE(service_id, key)
);

CREATE TABLE IF NOT EXISTS network_profiles (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    ssid     TEXT NOT NULL,
    psk      TEXT,
    priority INTEGER NOT NULL DEFAULT 0,
    enabled  INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS dashboard_widgets (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    widget_key TEXT    NOT NULL UNIQUE,
    label      TEXT    NOT NULL,
    enabled    INTEGER NOT NULL DEFAULT 1,
    position   INTEGER NOT NULL DEFAULT 0,
    config     TEXT    NOT NULL DEFAULT '{}'   -- JSON blob per widget
);

INSERT OR IGNORE INTO dashboard_widgets (widget_key, label, enabled, position) VALUES
    ('battery',         'Battery Status',     1, 0),
    ('system_resources','System Resources',   1, 1),
    ('docker_status',   'Docker Containers',  1, 2),
    ('network_status',  'Network Status',     1, 3),
    ('service_health',  'Service Health',     1, 4);

CREATE TABLE IF NOT EXISTS app_settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

INSERT OR IGNORE INTO app_settings (key, value) VALUES
    ('theme',          'dark'),
    ('admin_pw_hash',  ''),
    ('scan_interval',  '60'),
    ('input_lockout',  '1'),
    ('grace_period',   '5');

CREATE TABLE IF NOT EXISTS activity_log (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    event_type TEXT NOT NULL,  -- start|stop|error|scan|network|docker
    service_id INTEGER REFERENCES services(id) ON DELETE SET NULL,
    message    TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
