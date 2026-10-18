"""
Onryo – REST + WebSocket API (FastAPI).
Serves the frontend SPA and all backend operations.
Runs as the non-root 'onryo' user on port 8080.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from pathlib import Path

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from db.database import get_db, log_event, init_db
from scanner.scanner import run_scan
from service_manager.service_manager import (
    enable_service, disable_service, start_service, stop_service,
    service_status, write_unit,
)
from network_manager.network_manager import (
    list_adapters, set_role, bridge_add, bridge_remove,
    list_bridge_members, load_wifi_networks, add_wifi_network, remove_wifi_network,
)
from network_manager.ap_manager import APManager
from docker_manager.docker_manager import (
    list_containers, start_container, stop_container,
    restart_container, remove_container, container_logs, pull_image, list_images,
)
from auth.auth import AuthManager, require_auth
from system_resources.resources import get_system_info, get_process_list

logger = logging.getLogger("onryo.api")
logging.basicConfig(level=logging.INFO)

FRONTEND_DIR = os.environ.get("ONRYO_FRONTEND", "/opt/onryo/frontend")

app = FastAPI(title="Onryo", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def startup():
    init_db()
    run_scan()


# ---------------------------------------------------------------------------
# Auth (simple password check; replace with full session/JWT for production)
# ---------------------------------------------------------------------------

def _check_auth(token: str | None = None):
    # Token validation placeholder – integrate with app_settings pw_hash
    pass


# ---------------------------------------------------------------------------
# Services
# ---------------------------------------------------------------------------

@app.get("/api/services")
def get_services():
    with get_db() as db:
        rows = db.execute(
            "SELECT * FROM services ORDER BY type, name"
        ).fetchall()
        return [dict(r) for r in rows]


@app.get("/api/services/{service_id}")
def get_service(service_id: int):
    with get_db() as db:
        row = db.execute("SELECT * FROM services WHERE id=?", (service_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Service not found")
        return dict(row)


class ToggleRequest(BaseModel):
    enabled: bool


@app.post("/api/services/{service_id}/toggle")
def toggle_service(service_id: int, body: ToggleRequest):
    with get_db() as db:
        row = db.execute("SELECT * FROM services WHERE id=?", (service_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Service not found")
        svc = dict(row)
        db.execute("UPDATE services SET enabled=? WHERE id=?", (int(body.enabled), service_id))
        log_event("start" if body.enabled else "stop", svc["name"], service_id)

    if body.enabled:
        write_unit(svc["name"], svc["path"], svc["entrypoint"], svc["log_location"])
        enable_service(svc["name"])
    else:
        disable_service(svc["name"])
    return {"ok": True}


@app.get("/api/services/{service_id}/status")
def get_service_status(service_id: int):
    with get_db() as db:
        row = db.execute("SELECT name FROM services WHERE id=?", (service_id,)).fetchone()
        if not row:
            raise HTTPException(404)
        status = service_status(row["name"])
        db.execute("UPDATE services SET status=? WHERE id=?", (status, service_id))
        return {"status": status}


# ---------------------------------------------------------------------------
# Settings editor
# ---------------------------------------------------------------------------

@app.get("/api/services/{service_id}/settings")
def get_settings(service_id: int):
    with get_db() as db:
        row = db.execute("SELECT settings_file FROM services WHERE id=?", (service_id,)).fetchone()
        if not row or not row["settings_file"]:
            return {"raw": "", "format": "unknown"}
        sf = Path(row["settings_file"])
        if not sf.exists():
            return {"raw": "", "format": sf.suffix.lstrip(".") or "unknown"}
        return {"raw": sf.read_text(), "format": sf.suffix.lstrip(".") or "text"}


class SettingsSaveRequest(BaseModel):
    content: str


@app.post("/api/services/{service_id}/settings")
def save_settings(service_id: int, body: SettingsSaveRequest):
    with get_db() as db:
        row = db.execute("SELECT settings_file, name FROM services WHERE id=?", (service_id,)).fetchone()
        if not row or not row["settings_file"]:
            raise HTTPException(400, "No settings file defined for this service")
        sf = Path(row["settings_file"])
        # Backup
        backup = sf.with_suffix(sf.suffix + ".bak")
        if sf.exists():
            sf.rename(backup)
        try:
            sf.write_text(body.content)
        except Exception as exc:
            if backup.exists():
                backup.rename(sf)
            raise HTTPException(500, f"Failed to write settings: {exc}")
        return {"ok": True}


# ---------------------------------------------------------------------------
# Scanner
# ---------------------------------------------------------------------------

@app.post("/api/scan")
def trigger_scan():
    count = run_scan()
    return {"discovered": count}


# ---------------------------------------------------------------------------
# Network
# ---------------------------------------------------------------------------

@app.get("/api/network/adapters")
def network_adapters():
    return list_adapters()


class RoleRequest(BaseModel):
    mac: str
    role: str


@app.post("/api/network/role")
def assign_role(body: RoleRequest):
    try:
        set_role(body.mac, body.role)
        return {"ok": True}
    except (ValueError, PermissionError) as exc:
        raise HTTPException(400, str(exc))


class BridgeRequest(BaseModel):
    iface: str
    bridge: str = "br0"


@app.post("/api/network/bridge/add")
def api_bridge_add(body: BridgeRequest):
    try:
        bridge_add(body.iface, body.bridge)
        return {"ok": True}
    except PermissionError as exc:
        raise HTTPException(403, str(exc))


@app.post("/api/network/bridge/remove")
def api_bridge_remove(body: BridgeRequest):
    bridge_remove(body.iface, body.bridge)
    return {"ok": True}


@app.get("/api/network/bridge")
def api_bridge_members():
    return {"members": list_bridge_members()}


@app.get("/api/network/wifi")
def api_wifi_list():
    networks = load_wifi_networks()
    # Redact PSKs from the response
    return [{"ssid": n["ssid"], "priority": n.get("priority", 0), "enabled": n.get("enabled", True)}
            for n in networks]


class WifiAddRequest(BaseModel):
    ssid: str
    psk: str
    priority: int = 0


@app.post("/api/network/wifi")
def api_wifi_add(body: WifiAddRequest):
    add_wifi_network(body.ssid, body.psk, body.priority)
    return {"ok": True}


@app.delete("/api/network/wifi/{ssid}")
def api_wifi_remove(ssid: str):
    remove_wifi_network(ssid)
    return {"ok": True}


# ---------------------------------------------------------------------------
# Docker
# ---------------------------------------------------------------------------

@app.get("/api/docker/containers")
def api_containers(all: bool = True):
    try:
        return list_containers(all=all)
    except RuntimeError as exc:
        raise HTTPException(503, str(exc))


@app.post("/api/docker/containers/{name}/start")
def api_container_start(name: str):
    start_container(name)
    return {"ok": True}


@app.post("/api/docker/containers/{name}/stop")
def api_container_stop(name: str):
    stop_container(name)
    return {"ok": True}


@app.post("/api/docker/containers/{name}/restart")
def api_container_restart(name: str):
    restart_container(name)
    return {"ok": True}


@app.get("/api/docker/containers/{name}/logs")
def api_container_logs(name: str, tail: int = 200):
    return {"logs": container_logs(name, tail)}


@app.get("/api/docker/images")
def api_images():
    return list_images()


class PullRequest(BaseModel):
    image: str


@app.post("/api/docker/images/pull")
def api_pull(body: PullRequest):
    return pull_image(body.image)


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------

@app.get("/api/dashboard/widgets")
def dashboard_widgets():
    with get_db() as db:
        rows = db.execute("SELECT * FROM dashboard_widgets ORDER BY position").fetchall()
        return [dict(r) for r in rows]


class WidgetUpdateRequest(BaseModel):
    enabled: bool
    position: int | None = None


@app.patch("/api/dashboard/widgets/{widget_key}")
def update_widget(widget_key: str, body: WidgetUpdateRequest):
    with get_db() as db:
        updates = {"enabled": int(body.enabled)}
        if body.position is not None:
            updates["position"] = body.position
        db.execute(
            "UPDATE dashboard_widgets SET enabled=?, position=COALESCE(?,position) WHERE widget_key=?",
            (updates["enabled"], body.position, widget_key),
        )
    return {"ok": True}


@app.get("/api/dashboard/activity")
def activity_feed(limit: int = 50):
    with get_db() as db:
        rows = db.execute(
            "SELECT * FROM activity_log ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# System / settings
# ---------------------------------------------------------------------------

@app.get("/api/system/settings")
def system_settings():
    with get_db() as db:
        rows = db.execute("SELECT key, value FROM app_settings").fetchall()
        return {r["key"]: r["value"] for r in rows}


class SystemSettingRequest(BaseModel):
    value: str


@app.put("/api/system/settings/{key}")
def update_system_setting(key: str, body: SystemSettingRequest):
    with get_db() as db:
        db.execute(
            "INSERT INTO app_settings (key, value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, body.value),
        )
    return {"ok": True}


# ---------------------------------------------------------------------------
# WebSocket – live log streaming
# ---------------------------------------------------------------------------

@app.websocket("/ws/logs/{service_id}")
async def log_stream(websocket: WebSocket, service_id: int):
    await websocket.accept()
    with get_db() as db:
        row = db.execute("SELECT log_location FROM services WHERE id=?", (service_id,)).fetchone()
    if not row or not row["log_location"]:
        await websocket.send_text("No log file configured.")
        await websocket.close()
        return

    log_path = Path(row["log_location"])
    try:
        with open(log_path, "r") as fh:
            fh.seek(0, 2)  # seek to end
            while True:
                line = fh.readline()
                if line:
                    await websocket.send_text(line.rstrip())
                else:
                    await asyncio.sleep(0.5)
    except (WebSocketDisconnect, FileNotFoundError):
        pass


# ---------------------------------------------------------------------------
# Auth routes
# ---------------------------------------------------------------------------

class LoginBody(BaseModel):
    password: str

@app.post("/api/auth/login")
async def api_login(body: LoginBody):
    token = AuthManager.login(body.password)
    if token is None:
        raise HTTPException(status_code=401, detail="Invalid password")
    return {"token": token}

@app.post("/api/auth/logout")
async def api_logout(token: str = Depends(require_auth)):
    AuthManager.logout(token)
    return {"ok": True}

@app.post("/api/auth/change-password")
async def api_change_password(req: dict, _token: str = Depends(require_auth)):
    old_pw = req.get("old_password", "")
    new_pw = req.get("new_password", "")
    if not AuthManager.change_password(old_pw, new_pw):
        raise HTTPException(status_code=400, detail="Old password incorrect or new password too short")
    return {"ok": True}


# ---------------------------------------------------------------------------
# System resource routes
# ---------------------------------------------------------------------------

@app.get("/api/system/resources")
async def api_system_resources(_token: str = Depends(require_auth)):
    return get_system_info()

@app.get("/api/system/processes")
async def api_system_processes(_token: str = Depends(require_auth)):
    return {"processes": get_process_list()}


# ---------------------------------------------------------------------------
# AP routes
# ---------------------------------------------------------------------------

_ap = APManager()

class APConfigBody(BaseModel):
    ssid: str = ""
    password: str = ""
    channel: int = 6
    band: str = "bg"           # "bg" = 2.4 GHz, "a" = 5 GHz
    width: int = 20            # 20 | 40 | 80
    ieee80211ac: bool = True   # enable VHT on 5 GHz
    country: str = "US"
    ap_ip: str = "192.168.42.1"
    dhcp_start: str = "192.168.42.10"
    dhcp_end: str = "192.168.42.100"
    channel_hop: bool = False
    channel_hop_interval: int = 30
    channel_hop_list: list[int] = []

class ChannelHopBody(BaseModel):
    channel_list: list[int] = []
    interval: int = 30

@app.get("/api/network/ap")
async def api_ap_get(_token: str = Depends(require_auth)):
    return _ap.get_config()

@app.post("/api/network/ap")
async def api_ap_save(body: APConfigBody, _token: str = Depends(require_auth)):
    _ap.save_config(body.dict())
    return {"ok": True}

@app.post("/api/network/ap/start")
async def api_ap_start(_token: str = Depends(require_auth)):
    ok, msg = _ap.start()
    if not ok:
        raise HTTPException(status_code=500, detail=msg)
    return {"ok": True, "message": msg}

@app.post("/api/network/ap/stop")
async def api_ap_stop(_token: str = Depends(require_auth)):
    ok, msg = _ap.stop()
    if not ok:
        raise HTTPException(status_code=500, detail=msg)
    return {"ok": True, "message": msg}

@app.post("/api/network/ap/regen-password")
async def api_ap_regen_password(_token: str = Depends(require_auth)):
    pw = _ap.regen_password()
    return {"password": pw}

@app.get("/api/network/ap/clients")
async def api_ap_clients(_token: str = Depends(require_auth)):
    return {"clients": _ap.connected_clients()}


@app.get("/api/network/ap/channels")
async def api_ap_channels(_token: str = Depends(require_auth)):
    """Return phy-supported channels for both bands plus VHT capability flag."""
    return _ap.get_available_channels()


@app.post("/api/network/ap/best-channel")
async def api_ap_best_channel(_token: str = Depends(require_auth)):
    """Scan the air and return the least-congested channel for the current band."""
    ch = _ap.auto_best_channel()
    return {"best_channel": ch}


@app.post("/api/network/ap/hop/start")
async def api_ap_hop_start(body: ChannelHopBody, _token: str = Depends(require_auth)):
    """Start channel hopping with the given list and interval."""
    _ap.start_channel_hopping(body.channel_list, body.interval)
    return {"ok": True, "status": _ap.get_hop_status()}


@app.post("/api/network/ap/hop/stop")
async def api_ap_hop_stop(_token: str = Depends(require_auth)):
    """Stop channel hopping and stay on the current channel."""
    _ap.stop_channel_hopping()
    return {"ok": True}


@app.get("/api/network/ap/hop/status")
async def api_ap_hop_status(_token: str = Depends(require_auth)):
    """Return current channel-hopper state."""
    return _ap.get_hop_status()


# ---------------------------------------------------------------------------
# Purge missing plugins/containers from DB
# ---------------------------------------------------------------------------

@app.post("/api/scan/purge-missing")
async def api_purge_missing(_token: str = Depends(require_auth)):
    """Remove DB entries whose base directory no longer exists on disk."""
    removed = []
    with get_db() as conn:
        rows = conn.execute("SELECT id, name, base_path FROM plugins").fetchall()
        for row in rows:
            if not Path(row["base_path"]).exists():
                conn.execute("DELETE FROM plugins WHERE id=?", (row["id"],))
                removed.append(row["name"])
    log_event("purge_missing", json.dumps({"removed": removed}))
    return {"removed": removed}


# ---------------------------------------------------------------------------
# Vision plugin API
# ---------------------------------------------------------------------------

_VISION_CONFIG = Path("/etc/onryo/plugins/vision/config.json")
_VISION_SETTINGS = Path("/opt/onryo/plugins/vision/settings.yaml")
_VISION_HELPER = "/opt/onryo/backend/privileged_helper/helper.sh"

def _vision_cfg() -> dict:
    if _VISION_CONFIG.exists():
        return json.loads(_VISION_CONFIG.read_text())
    return {}

def _vision_save(cfg: dict):
    _VISION_CONFIG.parent.mkdir(parents=True, exist_ok=True)
    _VISION_CONFIG.write_text(json.dumps(cfg, indent=2))

class VisionAPBody(BaseModel):
    enabled: bool | None = None
    ssid: str | None = None
    password: str | None = None
    interface: str | None = None
    band: str | None = None
    channel: int | None = None
    channel_width: int | None = None
    hidden: bool | None = None
    wpa_mode: str | None = None
    mac_filter_mode: str | None = None
    mac_allowlist: list[str] | None = None
    mac_denylist: list[str] | None = None
    max_clients: int | None = None
    channel_hop: bool | None = None
    channel_hop_interval: int | None = None
    channel_hop_list: list[int] | None = None

class VisionScannerBody(BaseModel):
    enabled: bool | None = None
    interface: str | None = None
    scan_interval: int | None = None
    active_scan: bool | None = None
    band: str | None = None
    hop_dwell_ms: int | None = None
    save_pcap: bool | None = None

@app.get("/api/plugins/vision/config")
async def vision_get_config(_t: str = Depends(require_auth)):
    return _vision_cfg()

@app.post("/api/plugins/vision/ap")
async def vision_set_ap(body: VisionAPBody, _t: str = Depends(require_auth)):
    """Save Vision AP config. Does NOT start/stop the AP; use /ap/start and /ap/stop."""
    cfg = _vision_cfg()
    ap = cfg.setdefault("ap", {})
    for field, val in body.model_dump(exclude_none=True).items():
        ap[field] = val
    _vision_save(cfg)
    return {"ok": True, "ap": ap}

@app.post("/api/plugins/vision/ap/start")
async def vision_ap_start(_t: str = Depends(require_auth)):
    import subprocess
    r = subprocess.run(["sudo", _VISION_HELPER, "start", "onryo-plugin-vision-ap.service"],
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise HTTPException(500, r.stderr.strip())
    return {"ok": True}

@app.post("/api/plugins/vision/ap/stop")
async def vision_ap_stop(_t: str = Depends(require_auth)):
    import subprocess
    r = subprocess.run(["sudo", _VISION_HELPER, "stop", "onryo-plugin-vision-ap.service"],
                       capture_output=True, text=True)
    return {"ok": r.returncode == 0}

@app.post("/api/plugins/vision/scanner")
async def vision_set_scanner(body: VisionScannerBody, _t: str = Depends(require_auth)):
    cfg = _vision_cfg()
    sc = cfg.setdefault("scanner", {})
    for field, val in body.model_dump(exclude_none=True).items():
        sc[field] = val
    _vision_save(cfg)
    return {"ok": True, "scanner": sc}

@app.get("/api/plugins/vision/status")
async def vision_status(_t: str = Depends(require_auth)):
    import subprocess
    results = {}
    for unit in ("onryo-plugin-vision-scanner",
                 "onryo-plugin-vision-ap",
                 "onryo-plugin-vision-gui"):
        r = subprocess.run(["systemctl", "is-active", f"{unit}.service"],
                           capture_output=True, text=True)
        results[unit.replace("onryo-plugin-vision-", "")] = r.stdout.strip()
    return results

@app.websocket("/ws/plugins/vision/logs")
async def ws_vision_logs(websocket: WebSocket):
    await websocket.accept()
    proc = await asyncio.create_subprocess_exec(
        "journalctl",
        "-u", "onryo-plugin-vision-scanner.service",
        "-u", "onryo-plugin-vision-ap.service",
        "-u", "onryo-plugin-vision-gui.service",
        "-f", "--no-pager", "-n", "50",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    try:
        while True:
            line = await proc.stdout.readline()
            if not line:
                break
            await websocket.send_text(line.decode("utf-8", errors="replace").rstrip())
    except WebSocketDisconnect:
        pass
    finally:
        proc.kill()
        try:
            await websocket.close()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Docker WebSocket – live log stream
# ---------------------------------------------------------------------------

@app.websocket("/ws/docker/{container_id}/logs")
async def ws_docker_logs(websocket: WebSocket, container_id: str):
    await websocket.accept()
    try:
        import docker as dockerlib
        client = dockerlib.from_env()
        container = client.containers.get(container_id)
        for chunk in container.logs(stream=True, follow=True, tail=100):
            line = chunk.decode("utf-8", errors="replace").rstrip()
            await websocket.send_text(line)
    except Exception as exc:
        await websocket.send_text(f"ERROR: {exc}")
    finally:
        try:
            await websocket.close()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Serve frontend SPA
# ---------------------------------------------------------------------------

frontend_path = Path(FRONTEND_DIR)
if frontend_path.exists():
    app.mount("/static", StaticFiles(directory=str(frontend_path / "static")), name="static")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def serve_spa(full_path: str):
        index = frontend_path / "index.html"
        return FileResponse(str(index))
