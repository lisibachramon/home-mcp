"""Deploy tools built on `docker compose` (v2) and git.

A "project" is either a name from HOME_MCP_PROJECTS or, when
HOME_MCP_ALLOW_ANY_PATH=true, a raw directory path. This scoping keeps deploys
constrained to directories you've explicitly blessed.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any

from pydantic import Field

from ..config import Settings
from ..proc import run_command
from ..registry import ToolRegistry
from ..security import find_compose_file, resolve_project


def _compose_base(project_dir: Path) -> list[str]:
    return ["docker", "compose", "--project-directory", str(project_dir)]


def register(reg: ToolRegistry, settings: Settings) -> None:
    def _project_dir(project: str) -> Path:
        project_dir = resolve_project(project, settings)
        if find_compose_file(project_dir) is None:
            raise ValueError(
                f"No compose file (compose.yaml / docker-compose.yml) found in {project_dir}"
            )
        return project_dir

    def deploy_list_projects() -> dict:
        """List configured deploy projects and whether arbitrary paths are allowed."""
        return {
            "projects": dict(settings.projects),
            "allow_any_path": settings.allow_any_path,
        }

    def compose_ps(project: Annotated[str, Field(description="Project name or path")]) -> dict:
        """Show the status of a compose project's services."""
        return run_command(_compose_base(_project_dir(project)) + ["ps", "--all"], settings)

    def compose_config(project: Annotated[str, Field(description="Project name or path")]) -> dict:
        """Validate and render the resolved compose configuration."""
        return run_command(_compose_base(_project_dir(project)) + ["config"], settings)

    def compose_up(
        project: Annotated[str, Field(description="Project name or path")],
        services: Annotated[list[str] | None, Field(description="Limit to these services")] = None,
        build: Annotated[bool, Field(description="Build images before starting")] = False,
        pull: Annotated[bool, Field(description="Always pull newer images first")] = False,
        force_recreate: Annotated[bool, Field(description="Recreate containers even if unchanged")] = False,
        remove_orphans: Annotated[bool, Field(description="Remove containers for services no longer defined")] = True,
    ) -> dict:
        """Start (or update) a compose project in detached mode."""
        args = _compose_base(_project_dir(project)) + ["up", "-d"]
        if build:
            args.append("--build")
        if pull:
            args += ["--pull", "always"]
        if force_recreate:
            args.append("--force-recreate")
        if remove_orphans:
            args.append("--remove-orphans")
        if services:
            args += services
        return run_command(args, settings)

    def compose_down(
        project: Annotated[str, Field(description="Project name or path")],
        volumes: Annotated[bool, Field(description="Also remove named volumes")] = False,
        remove_orphans: Annotated[bool, Field(description="Remove orphan containers")] = True,
    ) -> dict:
        """Stop and remove a compose project's containers (and optionally volumes)."""
        args = _compose_base(_project_dir(project)) + ["down"]
        if volumes:
            args.append("--volumes")
        if remove_orphans:
            args.append("--remove-orphans")
        return run_command(args, settings)

    def compose_restart(
        project: Annotated[str, Field(description="Project name or path")],
        services: Annotated[list[str] | None, Field(description="Limit to these services")] = None,
    ) -> dict:
        """Restart a compose project's services."""
        args = _compose_base(_project_dir(project)) + ["restart"]
        if services:
            args += services
        return run_command(args, settings)

    def compose_pull(
        project: Annotated[str, Field(description="Project name or path")],
        services: Annotated[list[str] | None, Field(description="Limit to these services")] = None,
    ) -> dict:
        """Pull the latest images for a compose project."""
        args = _compose_base(_project_dir(project)) + ["pull"]
        if services:
            args += services
        return run_command(args, settings)

    def compose_build(
        project: Annotated[str, Field(description="Project name or path")],
        services: Annotated[list[str] | None, Field(description="Limit to these services")] = None,
        no_cache: Annotated[bool, Field(description="Build without using cache")] = False,
    ) -> dict:
        """Build (or rebuild) images for a compose project."""
        args = _compose_base(_project_dir(project)) + ["build"]
        if no_cache:
            args.append("--no-cache")
        if services:
            args += services
        return run_command(args, settings)

    def compose_logs(
        project: Annotated[str, Field(description="Project name or path")],
        services: Annotated[list[str] | None, Field(description="Limit to these services")] = None,
        tail: Annotated[int, Field(description="Lines from the end per service")] = 200,
    ) -> dict:
        """Fetch recent logs for a compose project."""
        args = _compose_base(_project_dir(project)) + ["logs", "--no-color", "--tail", str(tail)]
        if services:
            args += services
        return run_command(args, settings)

    def git_pull(
        project: Annotated[str, Field(description="Project name or path")],
        remote: Annotated[str, Field(description="Git remote")] = "origin",
        branch: Annotated[str | None, Field(description="Branch to pull (defaults to current)")] = None,
    ) -> dict:
        """Run `git pull` in a project directory (for git-backed deploys)."""
        project_dir = resolve_project(project, settings)
        args = ["git", "-C", str(project_dir), "pull", "--ff-only", remote]
        if branch:
            args.append(branch)
        return run_command(args, settings)

    def git_status(project: Annotated[str, Field(description="Project name or path")]) -> dict:
        """Show `git status` and the current commit for a project directory."""
        project_dir = resolve_project(project, settings)
        status = run_command(["git", "-C", str(project_dir), "status", "--short", "--branch"], settings)
        head = run_command(["git", "-C", str(project_dir), "log", "-1", "--oneline"], settings)
        return {"status": status, "head": head}

    def deploy(
        project: Annotated[str, Field(description="Project name or path")],
        git_pull_first: Annotated[bool, Field(description="git pull --ff-only before deploying")] = False,
        pull_images: Annotated[bool, Field(description="docker compose pull before starting")] = True,
        build: Annotated[bool, Field(description="Build images as part of the deploy")] = False,
        prune_images: Annotated[bool, Field(description="Prune dangling images afterwards")] = False,
    ) -> dict:
        """High-level deploy: (optional git pull) -> pull/build -> up -d --remove-orphans.

        Runs the common redeploy flow for a project and returns each step's output.
        Stops early and reports if any step exits non-zero.
        """
        project_dir = _project_dir(project)
        steps: list[dict[str, Any]] = []

        def _record(result: dict) -> bool:
            steps.append(result)
            return result["exit_code"] == 0

        if git_pull_first:
            res = run_command(["git", "-C", str(project_dir), "pull", "--ff-only"], settings)
            if not _record(res):
                return {"project": project, "ok": False, "failed_step": "git_pull", "steps": steps}

        if pull_images and not build:
            res = run_command(_compose_base(project_dir) + ["pull"], settings)
            if not _record(res):
                return {"project": project, "ok": False, "failed_step": "pull", "steps": steps}

        up_args = _compose_base(project_dir) + ["up", "-d", "--remove-orphans"]
        if build:
            up_args.append("--build")
        elif pull_images:
            up_args += ["--pull", "always"]
        res = run_command(up_args, settings)
        if not _record(res):
            return {"project": project, "ok": False, "failed_step": "up", "steps": steps}

        if prune_images:
            client_res = run_command(["docker", "image", "prune", "-f"], settings)
            _record(client_res)

        return {"project": project, "ok": True, "steps": steps}

    for fn in (
        deploy_list_projects, compose_ps, compose_config, compose_up, compose_down,
        compose_restart, compose_pull, compose_build, compose_logs,
        git_pull, git_status, deploy,
    ):
        reg.add(fn)
