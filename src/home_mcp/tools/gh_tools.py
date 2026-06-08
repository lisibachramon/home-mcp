"""GitHub CLI tools: read and fully control GitHub through the `gh` binary.

`gh` authenticates with its own credentials (GH_TOKEN / GITHUB_TOKEN in the
environment, or a mounted ~/.config/gh). All commands run as an argument list
without a shell, so the raw passthrough (`gh_command`) is safe from injection
while still offering complete control.
"""

from __future__ import annotations

import json
import re
from typing import Annotated, Any

from pydantic import Field

from ..config import Settings
from ..proc import run_command
from ..registry import ToolRegistry

_REPO_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")


def _validate_repo(repo: str | None) -> None:
    if repo and not _REPO_RE.match(repo):
        raise ValueError(f"Invalid repo {repo!r}; expected 'owner/name'")


def _repo_args(repo: str | None) -> list[str]:
    _validate_repo(repo)
    return ["-R", repo] if repo else []


def _kv_flags(flag: str, items: dict[str, str] | None) -> list[str]:
    out: list[str] = []
    for key, value in (items or {}).items():
        out += [flag, f"{key}={value}"]
    return out


def register(reg: ToolRegistry, settings: Settings) -> None:
    def _gh(args: list[str], input_text: str | None = None) -> dict:
        return run_command([settings.gh_bin] + args, settings, input_text=input_text)

    def _gh_json(args: list[str], fields: list[str]) -> dict:
        res = _gh(args + ["--json", ",".join(fields)])
        if res["exit_code"] == 0 and res["stdout"]:
            try:
                res["data"] = json.loads(res["stdout"])
            except json.JSONDecodeError:
                pass
        return res

    def gh_auth_status() -> dict:
        """Show whether `gh` is authenticated and as which account."""
        return _gh(["auth", "status"])

    def gh_repo_view(repo: Annotated[str | None, Field(description="owner/name")] = None) -> dict:
        """View repository metadata (description, default branch, visibility, etc.)."""
        fields = ["name", "owner", "description", "defaultBranchRef", "visibility", "url", "isPrivate", "pushedAt"]
        return _gh_json(["repo", "view"] + ([repo] if repo else []), fields)

    def gh_repo_list(
        owner: Annotated[str | None, Field(description="User/org to list repos for")] = None,
        limit: Annotated[int, Field(description="Max repos")] = 30,
    ) -> dict:
        """List repositories for a user or org."""
        args = ["repo", "list"]
        if owner:
            args.append(owner)
        args += ["--limit", str(limit)]
        return _gh_json(args, ["name", "owner", "description", "visibility", "url", "updatedAt"])

    # ----- pull requests --------------------------------------------------- #
    def gh_pr_list(
        repo: Annotated[str | None, Field(description="owner/name")] = None,
        state: Annotated[str, Field(description="open/closed/merged/all")] = "open",
        limit: Annotated[int, Field(description="Max PRs")] = 30,
    ) -> dict:
        """List pull requests."""
        args = ["pr", "list"] + _repo_args(repo) + ["--state", state, "--limit", str(limit)]
        return _gh_json(
            args,
            ["number", "title", "state", "author", "headRefName", "baseRefName", "isDraft", "createdAt", "updatedAt", "url"],
        )

    def gh_pr_view(
        number: Annotated[int, Field(description="PR number")],
        repo: Annotated[str | None, Field(description="owner/name")] = None,
    ) -> dict:
        """View a pull request's details."""
        args = ["pr", "view", str(number)] + _repo_args(repo)
        return _gh_json(
            args,
            ["number", "title", "state", "author", "body", "headRefName", "baseRefName", "url", "labels", "reviewDecision", "mergeable", "mergeStateStatus", "isDraft"],
        )

    def gh_pr_diff(
        number: Annotated[int, Field(description="PR number")],
        repo: Annotated[str | None, Field(description="owner/name")] = None,
    ) -> dict:
        """Show a pull request's diff."""
        return _gh(["pr", "diff", str(number)] + _repo_args(repo))

    def gh_pr_checks(
        number: Annotated[int, Field(description="PR number")],
        repo: Annotated[str | None, Field(description="owner/name")] = None,
    ) -> dict:
        """Show CI check status for a pull request."""
        return _gh(["pr", "checks", str(number)] + _repo_args(repo))

    def gh_pr_create(
        title: Annotated[str, Field(description="PR title")],
        body: Annotated[str, Field(description="PR body")],
        repo: Annotated[str | None, Field(description="owner/name")] = None,
        base: Annotated[str | None, Field(description="Base branch")] = None,
        head: Annotated[str | None, Field(description="Head branch")] = None,
        draft: Annotated[bool, Field(description="Create as draft")] = False,
    ) -> dict:
        """Create a pull request."""
        args = ["pr", "create"] + _repo_args(repo) + ["--title", title, "--body", body]
        if base:
            args += ["--base", base]
        if head:
            args += ["--head", head]
        if draft:
            args.append("--draft")
        return _gh(args)

    def gh_pr_comment(
        number: Annotated[int, Field(description="PR number")],
        body: Annotated[str, Field(description="Comment body")],
        repo: Annotated[str | None, Field(description="owner/name")] = None,
    ) -> dict:
        """Add a comment to a pull request."""
        return _gh(["pr", "comment", str(number)] + _repo_args(repo) + ["--body", body])

    def gh_pr_merge(
        number: Annotated[int, Field(description="PR number")],
        repo: Annotated[str | None, Field(description="owner/name")] = None,
        method: Annotated[str, Field(description="merge method: squash/merge/rebase")] = "squash",
        delete_branch: Annotated[bool, Field(description="Delete branch after merge")] = False,
        admin: Annotated[bool, Field(description="Use admin privileges to override checks")] = False,
    ) -> dict:
        """Merge a pull request."""
        flag = {"squash": "--squash", "merge": "--merge", "rebase": "--rebase"}.get(method)
        if not flag:
            raise ValueError("method must be one of: squash, merge, rebase")
        args = ["pr", "merge", str(number)] + _repo_args(repo) + [flag]
        if delete_branch:
            args.append("--delete-branch")
        if admin:
            args.append("--admin")
        return _gh(args)

    def gh_pr_close(
        number: Annotated[int, Field(description="PR number")],
        repo: Annotated[str | None, Field(description="owner/name")] = None,
        comment: Annotated[str | None, Field(description="Optional closing comment")] = None,
    ) -> dict:
        """Close a pull request without merging."""
        args = ["pr", "close", str(number)] + _repo_args(repo)
        if comment:
            args += ["--comment", comment]
        return _gh(args)

    def gh_pr_review(
        number: Annotated[int, Field(description="PR number")],
        action: Annotated[str, Field(description="approve/request-changes/comment")] = "comment",
        body: Annotated[str | None, Field(description="Review body")] = None,
        repo: Annotated[str | None, Field(description="owner/name")] = None,
    ) -> dict:
        """Review a pull request (approve, request changes, or comment)."""
        flag = {"approve": "--approve", "request-changes": "--request-changes", "comment": "--comment"}.get(action)
        if not flag:
            raise ValueError("action must be one of: approve, request-changes, comment")
        args = ["pr", "review", str(number)] + _repo_args(repo) + [flag]
        if body:
            args += ["--body", body]
        return _gh(args)

    # ----- issues ---------------------------------------------------------- #
    def gh_issue_list(
        repo: Annotated[str | None, Field(description="owner/name")] = None,
        state: Annotated[str, Field(description="open/closed/all")] = "open",
        limit: Annotated[int, Field(description="Max issues")] = 30,
    ) -> dict:
        """List issues."""
        args = ["issue", "list"] + _repo_args(repo) + ["--state", state, "--limit", str(limit)]
        return _gh_json(args, ["number", "title", "state", "author", "labels", "createdAt", "updatedAt", "url"])

    def gh_issue_view(
        number: Annotated[int, Field(description="Issue number")],
        repo: Annotated[str | None, Field(description="owner/name")] = None,
    ) -> dict:
        """View an issue's details."""
        args = ["issue", "view", str(number)] + _repo_args(repo)
        return _gh_json(args, ["number", "title", "state", "author", "body", "labels", "url"])

    def gh_issue_create(
        title: Annotated[str, Field(description="Issue title")],
        body: Annotated[str, Field(description="Issue body")],
        repo: Annotated[str | None, Field(description="owner/name")] = None,
        labels: Annotated[list[str] | None, Field(description="Labels to apply")] = None,
    ) -> dict:
        """Create an issue."""
        args = ["issue", "create"] + _repo_args(repo) + ["--title", title, "--body", body]
        for label in labels or []:
            args += ["--label", label]
        return _gh(args)

    def gh_issue_comment(
        number: Annotated[int, Field(description="Issue number")],
        body: Annotated[str, Field(description="Comment body")],
        repo: Annotated[str | None, Field(description="owner/name")] = None,
    ) -> dict:
        """Comment on an issue."""
        return _gh(["issue", "comment", str(number)] + _repo_args(repo) + ["--body", body])

    def gh_issue_close(
        number: Annotated[int, Field(description="Issue number")],
        repo: Annotated[str | None, Field(description="owner/name")] = None,
    ) -> dict:
        """Close an issue."""
        return _gh(["issue", "close", str(number)] + _repo_args(repo))

    # ----- workflow runs --------------------------------------------------- #
    def gh_run_list(
        repo: Annotated[str | None, Field(description="owner/name")] = None,
        workflow: Annotated[str | None, Field(description="Workflow file or name to filter by")] = None,
        limit: Annotated[int, Field(description="Max runs")] = 20,
    ) -> dict:
        """List recent GitHub Actions workflow runs."""
        args = ["run", "list"] + _repo_args(repo) + ["--limit", str(limit)]
        if workflow:
            args += ["--workflow", workflow]
        return _gh_json(
            args,
            ["databaseId", "name", "displayTitle", "status", "conclusion", "headBranch", "event", "createdAt", "url"],
        )

    def gh_run_view(
        run_id: Annotated[int, Field(description="Workflow run id (databaseId)")],
        repo: Annotated[str | None, Field(description="owner/name")] = None,
        log: Annotated[bool, Field(description="Include the full run log")] = False,
    ) -> dict:
        """View a workflow run, optionally including its logs."""
        args = ["run", "view", str(run_id)] + _repo_args(repo)
        if log:
            args.append("--log")
        return _gh(args)

    def gh_run_rerun(
        run_id: Annotated[int, Field(description="Workflow run id")],
        repo: Annotated[str | None, Field(description="owner/name")] = None,
        failed_only: Annotated[bool, Field(description="Only rerun failed jobs")] = False,
    ) -> dict:
        """Re-run a workflow run."""
        args = ["run", "rerun", str(run_id)] + _repo_args(repo)
        if failed_only:
            args.append("--failed")
        return _gh(args)

    def gh_workflow_run(
        workflow: Annotated[str, Field(description="Workflow file name or id")],
        repo: Annotated[str | None, Field(description="owner/name")] = None,
        ref: Annotated[str | None, Field(description="Branch or tag to run on")] = None,
        inputs: Annotated[dict[str, str] | None, Field(description="workflow_dispatch inputs")] = None,
    ) -> dict:
        """Trigger a workflow_dispatch run."""
        args = ["workflow", "run", workflow] + _repo_args(repo)
        if ref:
            args += ["--ref", ref]
        args += _kv_flags("-f", inputs)
        return _gh(args)

    # ----- releases -------------------------------------------------------- #
    def gh_release_list(repo: Annotated[str | None, Field(description="owner/name")] = None) -> dict:
        """List releases."""
        return _gh(["release", "list"] + _repo_args(repo))

    def gh_release_create(
        tag: Annotated[str, Field(description="Tag name")],
        repo: Annotated[str | None, Field(description="owner/name")] = None,
        title: Annotated[str | None, Field(description="Release title")] = None,
        notes: Annotated[str | None, Field(description="Release notes")] = None,
        target: Annotated[str | None, Field(description="Target commitish/branch")] = None,
    ) -> dict:
        """Create a release."""
        args = ["release", "create", tag] + _repo_args(repo)
        if title:
            args += ["--title", title]
        args += ["--notes", notes] if notes else ["--generate-notes"]
        if target:
            args += ["--target", target]
        return _gh(args)

    # ----- escape hatches -------------------------------------------------- #
    def gh_api(
        endpoint: Annotated[str, Field(description="API path, e.g. 'repos/{owner}/{repo}/issues'")],
        method: Annotated[str, Field(description="HTTP method")] = "GET",
        fields: Annotated[dict[str, str] | None, Field(description="String fields (-f key=value)")] = None,
        body: Annotated[str | None, Field(description="Raw JSON body, sent on stdin")] = None,
    ) -> dict:
        """Call any GitHub REST/GraphQL endpoint via `gh api` (full API access)."""
        args = ["api", "-X", method.upper(), endpoint]
        args += _kv_flags("-f", fields)
        if body:
            args.append("--input")
            args.append("-")
        return _gh(args, input_text=body)

    def gh_command(
        args: Annotated[list[str], Field(description="Raw gh arguments, e.g. ['pr', 'list', '-R', 'owner/repo']")],
    ) -> dict:
        """Run an arbitrary `gh` command (argument list, no shell). Full control."""
        if not args or not all(isinstance(a, str) for a in args):
            raise ValueError("args must be a non-empty list of strings")
        return _gh(list(args))

    for fn in (
        gh_auth_status, gh_repo_view, gh_repo_list,
        gh_pr_list, gh_pr_view, gh_pr_diff, gh_pr_checks, gh_pr_create,
        gh_pr_comment, gh_pr_merge, gh_pr_close, gh_pr_review,
        gh_issue_list, gh_issue_view, gh_issue_create, gh_issue_comment, gh_issue_close,
        gh_run_list, gh_run_view, gh_run_rerun, gh_workflow_run,
        gh_release_list, gh_release_create,
        gh_api, gh_command,
    ):
        reg.add(fn)
