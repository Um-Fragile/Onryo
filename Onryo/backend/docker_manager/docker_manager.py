"""
Onryo – Docker manager.
Thin wrapper around the Docker Engine API via the Unix socket.
Never exposes the socket directly to the frontend; all Docker operations
go through this module called by the backend API.
"""

from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger("onryo.docker_manager")

try:
    import docker  # type: ignore
    _client = docker.from_env()
except ImportError:
    logger.warning("docker SDK not installed – Docker management disabled")
    _client = None  # type: ignore
except Exception as exc:
    logger.warning("Docker not available: %s", exc)
    _client = None


def _require_docker():
    if _client is None:
        raise RuntimeError("Docker is not available on this system")


def list_containers(all: bool = True) -> list[dict]:
    _require_docker()
    containers = []
    for c in _client.containers.list(all=all):
        containers.append({
            "id":     c.short_id,
            "name":   c.name,
            "image":  c.image.tags[0] if c.image.tags else c.image.short_id,
            "status": c.status,
            "ports":  c.ports,
        })
    return containers


def start_container(name_or_id: str) -> None:
    _require_docker()
    _client.containers.get(name_or_id).start()
    logger.info("Started container %s", name_or_id)


def stop_container(name_or_id: str, timeout: int = 10) -> None:
    _require_docker()
    _client.containers.get(name_or_id).stop(timeout=timeout)
    logger.info("Stopped container %s", name_or_id)


def restart_container(name_or_id: str) -> None:
    _require_docker()
    _client.containers.get(name_or_id).restart()
    logger.info("Restarted container %s", name_or_id)


def remove_container(name_or_id: str, force: bool = False) -> None:
    _require_docker()
    _client.containers.get(name_or_id).remove(force=force)
    logger.info("Removed container %s", name_or_id)


def container_logs(name_or_id: str, tail: int = 200) -> str:
    _require_docker()
    c = _client.containers.get(name_or_id)
    return c.logs(tail=tail, timestamps=True).decode("utf-8", errors="replace")


def pull_image(image: str) -> dict:
    _require_docker()
    logger.info("Pulling image %s", image)
    img = _client.images.pull(image)
    return {"id": img.short_id, "tags": img.tags}


def list_images() -> list[dict]:
    _require_docker()
    images = []
    for img in _client.images.list():
        images.append({
            "id":   img.short_id,
            "tags": img.tags,
            "size": img.attrs.get("Size", 0),
        })
    return images


def exec_in_container(name_or_id: str, command: str) -> str:
    """Run a command inside a running container and return its output."""
    _require_docker()
    c = _client.containers.get(name_or_id)
    exit_code, output = c.exec_run(command, demux=False)
    return output.decode("utf-8", errors="replace") if output else ""
