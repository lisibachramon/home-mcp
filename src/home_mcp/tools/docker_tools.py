"""Docker tools: inspect and fully control containers, images, networks, volumes.

Destructive operations (stop/remove/prune/exec/run) are enabled by design. The
only built-in guard is self-protection: by default the server refuses to stop or
remove its own container so a session can't sever its own connection. Disable
with HOME_MCP_PROTECT_SELF=false.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Annotated, Any

import docker
from pydantic import Field

from ..config import Settings
from ..docker_client import get_client
from ..registry import ToolRegistry
from ..security import truncate


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def _ports(container) -> list[str]:
    out: list[str] = []
    ports = (container.attrs.get("NetworkSettings") or {}).get("Ports") or {}
    for container_port, bindings in ports.items():
        if not bindings:
            out.append(container_port)
            continue
        for binding in bindings:
            host_ip = binding.get("HostIp") or "0.0.0.0"
            host_port = binding.get("HostPort")
            out.append(f"{host_ip}:{host_port}->{container_port}")
    return out


def _compose_meta(container) -> dict[str, str]:
    labels = (container.attrs.get("Config") or {}).get("Labels") or {}
    meta = {}
    if labels.get("com.docker.compose.project"):
        meta["compose_project"] = labels["com.docker.compose.project"]
    if labels.get("com.docker.compose.service"):
        meta["compose_service"] = labels["com.docker.compose.service"]
    return meta


def _image_name(container) -> str | None:
    try:
        tags = container.image.tags
        if tags:
            return tags[0]
        return container.image.short_id
    except Exception:
        return (container.attrs.get("Config") or {}).get("Image")


def _summary(container) -> dict[str, Any]:
    return {
        "id": container.short_id,
        "name": container.name,
        "image": _image_name(container),
        "status": container.status,
        "state": (container.attrs.get("State") or {}).get("Status"),
        "health": ((container.attrs.get("State") or {}).get("Health") or {}).get("Status"),
        "created": container.attrs.get("Created"),
        "ports": _ports(container),
        **_compose_meta(container),
    }


def _self_identifiers(settings: Settings) -> set[str]:
    ids = set()
    if settings.self_container:
        ids.add(settings.self_container)
    hostname = os.environ.get("HOSTNAME")
    if hostname:
        ids.add(hostname)
    return {i for i in ids if i}


def _is_self(container, settings: Settings) -> bool:
    ids = _self_identifiers(settings)
    if not ids:
        return False
    if container.name in ids:
        return True
    for ident in ids:
        if container.id == ident or container.id.startswith(ident):
            return True
        if container.short_id == ident or ident.startswith(container.short_id):
            return True
    return False


def _guard_self(container, action: str, settings: Settings) -> None:
    if settings.protect_self and _is_self(container, settings):
        raise ValueError(
            f"Refusing to {action} the home-mcp server's own container "
            f"({container.name}). Set HOME_MCP_PROTECT_SELF=false to override."
        )


def _cpu_percent(stats: dict) -> float | None:
    try:
        cpu = stats["cpu_stats"]
        pre = stats["precpu_stats"]
        cpu_delta = cpu["cpu_usage"]["total_usage"] - pre["cpu_usage"]["total_usage"]
        system_delta = cpu.get("system_cpu_usage", 0) - pre.get("system_cpu_usage", 0)
        ncpus = cpu.get("online_cpus") or len(
            cpu["cpu_usage"].get("percpu_usage") or [1]
        )
        if system_delta > 0 and cpu_delta > 0:
            return round((cpu_delta / system_delta) * ncpus * 100.0, 2)
    except (KeyError, TypeError, ZeroDivisionError):
        return None
    return 0.0


# --------------------------------------------------------------------------- #
# registration
# --------------------------------------------------------------------------- #
def register(reg: ToolRegistry, settings: Settings) -> None:
    def docker_list_containers(
        all: Annotated[bool, Field(description="Include stopped containers too")] = False,
        label: Annotated[
            str | None, Field(description="Filter by label, e.g. 'com.docker.compose.project=blog'")
        ] = None,
        status: Annotated[
            str | None,
            Field(description="Filter by status: created/running/paused/exited/etc."),
        ] = None,
    ) -> list[dict]:
        """List Docker containers with id, name, image, status, health and ports."""
        client = get_client(settings)
        filters: dict[str, Any] = {}
        if label:
            filters["label"] = label
        if status:
            filters["status"] = status
        containers = client.containers.list(all=all, filters=filters or None)
        return [_summary(c) for c in containers]

    def docker_inspect(
        container: Annotated[str, Field(description="Container name or id")],
        full: Annotated[bool, Field(description="Return the full raw inspect payload")] = False,
    ) -> dict:
        """Inspect a container. Returns a curated view, or the full payload if full=True."""
        client = get_client(settings)
        c = client.containers.get(container)
        if full:
            return c.attrs
        attrs = c.attrs
        config = attrs.get("Config") or {}
        host_config = attrs.get("HostConfig") or {}
        net = attrs.get("NetworkSettings") or {}
        return {
            **_summary(c),
            "state_detail": attrs.get("State"),
            "restart_count": attrs.get("RestartCount"),
            "restart_policy": host_config.get("RestartPolicy"),
            "command": config.get("Cmd"),
            "entrypoint": config.get("Entrypoint"),
            "env": config.get("Env"),
            "mounts": [
                {"source": m.get("Source"), "destination": m.get("Destination"), "mode": m.get("Mode"), "rw": m.get("RW")}
                for m in attrs.get("Mounts", [])
            ],
            "networks": list((net.get("Networks") or {}).keys()),
        }

    def docker_logs(
        container: Annotated[str, Field(description="Container name or id")],
        tail: Annotated[int, Field(description="Number of lines from the end")] = 200,
        since_seconds: Annotated[
            int | None, Field(description="Only logs newer than this many seconds ago")
        ] = None,
        timestamps: Annotated[bool, Field(description="Prefix each line with a timestamp")] = False,
    ) -> dict:
        """Fetch recent stdout/stderr logs for a container."""
        client = get_client(settings)
        c = client.containers.get(container)
        kwargs: dict[str, Any] = {"tail": tail, "timestamps": timestamps, "stdout": True, "stderr": True}
        if since_seconds:
            kwargs["since"] = datetime.now(timezone.utc) - timedelta(seconds=since_seconds)
        raw = c.logs(**kwargs)
        text = raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else str(raw)
        return {"container": c.name, "logs": truncate(text, settings)}

    def docker_stats(
        container: Annotated[str, Field(description="Container name or id")],
    ) -> dict:
        """One-shot CPU / memory / network stats snapshot for a running container."""
        client = get_client(settings)
        c = client.containers.get(container)
        stats = c.stats(stream=False)
        mem = stats.get("memory_stats", {}) or {}
        usage = mem.get("usage")
        limit = mem.get("limit")
        mem_pct = round(usage / limit * 100, 2) if usage and limit else None
        return {
            "container": c.name,
            "cpu_percent": _cpu_percent(stats),
            "memory_usage_bytes": usage,
            "memory_limit_bytes": limit,
            "memory_percent": mem_pct,
            "pids": (stats.get("pids_stats") or {}).get("current"),
        }

    def docker_start(container: Annotated[str, Field(description="Container name or id")]) -> dict:
        """Start a stopped container."""
        client = get_client(settings)
        c = client.containers.get(container)
        c.start()
        c.reload()
        return _summary(c)

    def docker_stop(
        container: Annotated[str, Field(description="Container name or id")],
        timeout: Annotated[int, Field(description="Seconds to wait before killing")] = 10,
    ) -> dict:
        """Stop a running container (SIGTERM, then SIGKILL after timeout)."""
        client = get_client(settings)
        c = client.containers.get(container)
        _guard_self(c, "stop", settings)
        c.stop(timeout=timeout)
        c.reload()
        return _summary(c)

    def docker_restart(
        container: Annotated[str, Field(description="Container name or id")],
        timeout: Annotated[int, Field(description="Seconds to wait before killing")] = 10,
    ) -> dict:
        """Restart a container."""
        client = get_client(settings)
        c = client.containers.get(container)
        _guard_self(c, "restart", settings)
        c.restart(timeout=timeout)
        c.reload()
        return _summary(c)

    def docker_kill(
        container: Annotated[str, Field(description="Container name or id")],
        signal: Annotated[str, Field(description="Signal to send, e.g. SIGKILL or SIGHUP")] = "SIGKILL",
    ) -> dict:
        """Send a signal to a container (defaults to SIGKILL)."""
        client = get_client(settings)
        c = client.containers.get(container)
        _guard_self(c, "kill", settings)
        c.kill(signal=signal)
        c.reload()
        return _summary(c)

    def docker_remove(
        container: Annotated[str, Field(description="Container name or id")],
        force: Annotated[bool, Field(description="Remove even if running")] = False,
        volumes: Annotated[bool, Field(description="Also remove anonymous volumes")] = False,
    ) -> dict:
        """Remove a container."""
        client = get_client(settings)
        c = client.containers.get(container)
        _guard_self(c, "remove", settings)
        name = c.name
        c.remove(force=force, v=volumes)
        return {"removed": name, "force": force, "volumes": volumes}

    def docker_rename(
        container: Annotated[str, Field(description="Container name or id")],
        name: Annotated[str, Field(description="New name")],
    ) -> dict:
        """Rename a container."""
        client = get_client(settings)
        c = client.containers.get(container)
        c.rename(name)
        c.reload()
        return _summary(c)

    def docker_exec(
        container: Annotated[str, Field(description="Container name or id")],
        cmd: Annotated[
            str | list[str],
            Field(description="Command to run; a string is run via 'sh -c', a list is run directly"),
        ],
        workdir: Annotated[str | None, Field(description="Working directory inside the container")] = None,
        user: Annotated[str | None, Field(description="User to run as, e.g. 'root' or '1000'")] = None,
        environment: Annotated[
            dict[str, str] | None, Field(description="Extra environment variables")
        ] = None,
    ) -> dict:
        """Execute a command inside a running container and return its output."""
        client = get_client(settings)
        c = client.containers.get(container)
        exec_cmd = ["sh", "-c", cmd] if isinstance(cmd, str) else list(cmd)
        result = c.exec_run(
            exec_cmd,
            workdir=workdir,
            user=user or "",
            environment=environment,
            demux=True,
        )
        stdout, stderr = result.output if isinstance(result.output, tuple) else (result.output, None)
        return {
            "container": c.name,
            "exit_code": result.exit_code,
            "stdout": truncate(stdout.decode("utf-8", "replace") if stdout else "", settings),
            "stderr": truncate(stderr.decode("utf-8", "replace") if stderr else "", settings),
        }

    def docker_pull(
        image: Annotated[str, Field(description="Image reference, e.g. 'nginx:latest'")],
    ) -> dict:
        """Pull (or update) an image from its registry."""
        client = get_client(settings)
        img = client.images.pull(image)
        if isinstance(img, list):
            img = img[0]
        return {"pulled": image, "id": img.short_id, "tags": img.tags}

    def docker_run(
        image: Annotated[str, Field(description="Image to run")],
        name: Annotated[str | None, Field(description="Container name")] = None,
        command: Annotated[str | list[str] | None, Field(description="Command to run")] = None,
        environment: Annotated[dict[str, str] | None, Field(description="Environment variables")] = None,
        ports: Annotated[
            dict[str, int] | None,
            Field(description="Port map, e.g. {'80/tcp': 8080} (container -> host)"),
        ] = None,
        volumes: Annotated[
            list[str] | None,
            Field(description="Bind mounts as 'host:container[:ro]' strings"),
        ] = None,
        restart_policy: Annotated[
            str | None, Field(description="Restart policy name: no/on-failure/always/unless-stopped")
        ] = None,
        network: Annotated[str | None, Field(description="Network to attach to")] = None,
        remove: Annotated[bool, Field(description="Auto-remove when it exits")] = False,
    ) -> dict:
        """Create and start a new detached container from an image."""
        client = get_client(settings)
        kwargs: dict[str, Any] = {"detach": True, "name": name, "remove": remove}
        if command is not None:
            kwargs["command"] = command
        if environment:
            kwargs["environment"] = environment
        if ports:
            kwargs["ports"] = ports
        if volumes:
            kwargs["volumes"] = volumes
        if network:
            kwargs["network"] = network
        if restart_policy:
            kwargs["restart_policy"] = {"Name": restart_policy}
        c = client.containers.run(image, **kwargs)
        c.reload()
        return _summary(c)

    def docker_prune(
        target: Annotated[
            str,
            Field(description="What to prune: containers, images, volumes, networks, or all"),
        ] = "images",
    ) -> dict:
        """Reclaim space by pruning unused Docker objects."""
        client = get_client(settings)
        target = target.lower()
        valid = {"containers", "images", "volumes", "networks", "all"}
        if target not in valid:
            raise ValueError(f"target must be one of {sorted(valid)}")
        result: dict[str, Any] = {}
        if target in ("containers", "all"):
            result["containers"] = client.containers.prune()
        if target in ("images", "all"):
            result["images"] = client.images.prune(filters={"dangling": target != "all"})
        if target in ("networks", "all"):
            result["networks"] = client.networks.prune()
        if target in ("volumes", "all"):
            result["volumes"] = client.volumes.prune()
        return result

    def docker_list_images() -> list[dict]:
        """List images with tags and size."""
        client = get_client(settings)
        return [
            {"id": img.short_id, "tags": img.tags, "size_bytes": img.attrs.get("Size")}
            for img in client.images.list()
        ]

    def docker_list_volumes() -> list[dict]:
        """List Docker volumes."""
        client = get_client(settings)
        return [
            {"name": v.name, "driver": v.attrs.get("Driver"), "mountpoint": v.attrs.get("Mountpoint")}
            for v in client.volumes.list()
        ]

    def docker_list_networks() -> list[dict]:
        """List Docker networks."""
        client = get_client(settings)
        return [
            {"id": n.short_id, "name": n.name, "driver": n.attrs.get("Driver"), "scope": n.attrs.get("Scope")}
            for n in client.networks.list()
        ]

    def docker_info() -> dict:
        """Daemon-level info: container/image counts, OS, kernel, driver, resources."""
        client = get_client(settings)
        info = client.info()
        keys = (
            "ServerVersion", "Containers", "ContainersRunning", "ContainersPaused",
            "ContainersStopped", "Images", "Driver", "OperatingSystem", "KernelVersion",
            "Architecture", "NCPU", "MemTotal", "Name",
        )
        return {k: info.get(k) for k in keys}

    def docker_df() -> dict:
        """Docker disk usage summary (images, containers, volumes, build cache)."""
        client = get_client(settings)
        data = client.df()

        def _section(items):
            return {"count": len(items or []), "size_bytes": sum((i or {}).get("Size", 0) for i in (items or []))}

        return {
            "images": _section(data.get("Images")),
            "containers": _section(data.get("Containers")),
            "volumes": _section(data.get("Volumes")),
            "build_cache": _section(data.get("BuildCache")),
        }

    for fn in (
        docker_list_containers, docker_inspect, docker_logs, docker_stats,
        docker_start, docker_stop, docker_restart, docker_kill, docker_remove,
        docker_rename, docker_exec, docker_pull, docker_run, docker_prune,
        docker_list_images, docker_list_volumes, docker_list_networks,
        docker_info, docker_df,
    ):
        reg.add(fn)
