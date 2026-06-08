# home-mcp

A secure, self-hosted **MCP server** that lets authorized Claude sessions control
your home server: **Docker** (every container, plus images/networks/volumes),
**deploys** (docker compose stacks + git), and the **GitHub CLI** (`gh`).

It speaks the Model Context Protocol over **Streamable HTTP**, is designed to sit
behind a **TLS-terminating reverse proxy**, and requires a **bearer token on
every request** so it is never open to the public or to attackers.

---

## Security model

This is the part you asked me to get right. Defense in depth:

| Layer | What it does |
| --- | --- |
| **Bearer token (always on)** | Every request to `/mcp` must carry `Authorization: Bearer <token>`. Checked in **constant time**; all configured tokens are compared so timing doesn't leak which matched. The server **refuses to start** without a token of at least 24 chars (fail-closed). |
| **TLS via reverse proxy** | The app speaks plain HTTP and is meant to live behind Caddy/nginx (or a tunnel) that terminates HTTPS. The token therefore only ever travels encrypted. |
| **Not directly exposed** | In the bundled compose, the app is only reachable by the proxy on an internal Docker network — it has no published host port. |
| **Optional IP allowlist** | `HOME_MCP_IP_ALLOWLIST` restricts which source IPs/CIDRs may connect (pairs perfectly with a VPN/Tailscale range). |
| **Deploy scoping** | Deploys target **named projects** by default; arbitrary filesystem paths require explicitly setting `HOME_MCP_ALLOW_ANY_PATH=true`. |
| **Self-protection** | The server refuses to stop/kill/remove **its own container** so a session can't sever its own connection (toggle with `HOME_MCP_PROTECT_SELF`). |
| **Full audit log** | Every tool call and every auth decision is written as a JSON line, with secrets/tokens redacted. |
| **No shell** | `gh` and `docker compose`/`git` always run as argument lists — there is no shell-injection surface, even for the raw `gh_command` / `gh_api` passthroughs. |

> **Threat model.** The bearer token + TLS + (optional) IP allowlist keep *everyone
> except the token holder* out. The token holder — your authorized Claude session —
> intentionally has **full control** (start/stop/remove/exec containers, prune,
> deploy, merge/close PRs). That's the capability you chose; the locks above are
> what keep it yours.

**Keep the token secret.** Anyone with it can control your server. Rotate it by
setting `HOME_MCP_TOKENS=new,old`, switching clients over, then dropping `old`.

---

## Architecture

```
  Claude session ──HTTPS──▶  nginx-proxy +   ──HTTP──▶  home-mcp  ──▶  Docker socket
 (Bearer token)            letsencrypt-companion       (this app) ──▶  docker compose + git
                            (shared proxy_default net)             ──▶  gh CLI ──▶ GitHub
```

The container publishes no host ports; only the proxy reaches it over the shared
`proxy_default` network, and the bearer token is enforced on every request.

---

## Deploy (CI → GHCR → SSH, behind nginx-proxy)

Assumes your server already runs jwilder/nginx-proxy + acme/letsencrypt-companion
on an external `proxy_default` network and is logged into GHCR. `docker-compose.yml`
joins that network and sets `VIRTUAL_HOST`/`LETSENCRYPT_HOST` from `HOME_MCP_DOMAIN`,
so the proxy routes `https://HOME_MCP_DOMAIN` to the container and the companion
issues the cert. No host ports are published.

`.github/workflows/deploy.yml` does it all on push to `main` (or via the
Actions "Run workflow" button): build the image → push to GHCR → render `.env`
from repo secrets → scp `docker-compose.yml` + `.env` to `REMOTE_DIR` → `docker
compose pull && up -d` over SSH.

**One-time: set the repo secrets** (see "Required secrets" below), then push to
`main`. Verify once it's up (health needs no auth; `/mcp` requires the token):

```bash
curl https://mcp.example.com/healthz
# {"status":"ok","server":"home-mcp","version":"0.1.0"}
```

### Required secrets (GitHub → repo → Settings → Secrets → Actions)

| Secret | Purpose |
| --- | --- |
| `HOME_MCP_TOKEN` | Bearer token Claude presents (generate with `scripts/gen_token.py`). |
| `HOME_MCP_DOMAIN` | The vhost, e.g. `mcp.example.com` (drives `VIRTUAL_HOST`/cert). |
| `LETSENCRYPT_EMAIL` | Email for the TLS certificate. |
| `SSH_HOST`, `SSH_USER`, `SSH_PW` | SSH access for the deploy step. |
| `GH_TOKEN` *(optional)* | PAT so home-mcp's `gh_*` tools can drive GitHub. |
| `HOME_MCP_PROJECTS`, `STACKS_DIR` *(optional)* | Compose projects home-mcp may deploy. |
| `HOME_MCP_IP_ALLOWLIST` *(optional)* | Restrict source IPs/CIDRs (e.g. your VPN). |

> No proxy yet? `deploy/Caddyfile` and `deploy/nginx.conf` are standalone
> alternatives — run one of those in front and skip the nginx-proxy bits.

---

## Connect a Claude session to it

### Claude Code (CLI)

```bash
claude mcp add --transport http home-mcp https://home-mcp.example.com/mcp \
  --header "Authorization: Bearer YOUR_TOKEN"
```

Then in a session: *"call server_info"* to confirm the connection and see what's enabled.

### Claude API (MCP connector)

```json
{
  "model": "claude-opus-4-8",
  "max_tokens": 1024,
  "messages": [{"role": "user", "content": "List my running containers"}],
  "mcp_servers": [{
    "type": "url",
    "url": "https://home-mcp.example.com/mcp",
    "name": "home-mcp",
    "authorization_token": "YOUR_TOKEN"
  }]
}
```

(Send the `anthropic-beta: mcp-client-2025-04-04` header as required by the API.)

> **Note on claude.ai web custom connectors:** the web UI's custom connectors
> are built around OAuth, whereas this server uses a static bearer token. Claude
> Code and the API connector (above) are the directly supported clients. If you
> need the web UI, put an OAuth-capable gateway in front, or use a tunnel
> (e.g. Cloudflare Access) that injects the `Authorization` header.

---

## Configuration

All configuration is via environment variables (see `.env.example`).

| Variable | Default | Description |
| --- | --- | --- |
| `HOME_MCP_TOKEN` | — (**required**) | Bearer token clients must present. |
| `HOME_MCP_TOKENS` | — | Extra comma-separated tokens (for rotation). |
| `HOME_MCP_HOST` | `127.0.0.1` (`0.0.0.0` in Docker) | Bind address. |
| `HOME_MCP_PORT` | `8848` | Bind port. |
| `HOME_MCP_PATH` | `/mcp` | MCP endpoint path. |
| `HOME_MCP_DOMAIN` | — | The vhost; sets `VIRTUAL_HOST`/`LETSENCRYPT_HOST` for nginx-proxy. |
| `HOME_MCP_JSON_RESPONSE` | `true` | Return JSON (not SSE) — friendlier behind nginx-proxy. |
| `HOME_MCP_IP_ALLOWLIST` | — | Comma-separated IPs/CIDRs allowed to connect. |
| `HOME_MCP_TRUST_PROXY` | `true` | Trust `X-Forwarded-For`/`X-Real-IP` from the proxy. |
| `HOME_MCP_PROJECTS` | — | Named deploy projects: JSON `{name:path}` or `name=path,...`. |
| `STACKS_DIR` | `/srv/stacks` | Host dir mounted into the container (compose only). |
| `HOME_MCP_ALLOW_ANY_PATH` | `false` | Allow deploys against arbitrary directory paths. |
| `HOME_MCP_PROTECT_SELF` | `true` | Refuse to stop/remove the server's own container. |
| `HOME_MCP_SELF_CONTAINER` | `$HOSTNAME` | Name/id identifying this container. |
| `HOME_MCP_ENABLE_DOCKER` / `_COMPOSE` / `_GH` | `true` | Toggle capability groups. |
| `GH_TOKEN` / `GITHUB_TOKEN` | — | Credentials `gh` uses (a fine-grained PAT). |
| `HOME_MCP_CMD_TIMEOUT` | `300` | Timeout (s) for compose/git/gh commands. |
| `HOME_MCP_MAX_OUTPUT` | `100000` | Max chars of command/log output returned. |
| `HOME_MCP_AUDIT_LOG` | — | Also write the JSON audit log to this file. |
| `HOME_MCP_LOG_LEVEL` | `info` | Log level. |

---

## Tools

Call **`server_info`** first to see what's enabled. ~57 tools across three groups:

**Docker** — `docker_list_containers`, `docker_inspect`, `docker_logs`,
`docker_stats`, `docker_start`, `docker_stop`, `docker_restart`, `docker_kill`,
`docker_remove`, `docker_rename`, `docker_exec`, `docker_pull`, `docker_run`,
`docker_prune`, `docker_list_images`, `docker_list_volumes`,
`docker_list_networks`, `docker_info`, `docker_df`.

**Deploy** — `deploy_list_projects`, `deploy`, `compose_up`, `compose_down`,
`compose_ps`, `compose_config`, `compose_restart`, `compose_pull`,
`compose_build`, `compose_logs`, `git_pull`, `git_status`.

**GitHub** — `gh_auth_status`, `gh_repo_view`, `gh_repo_list`, `gh_pr_list`,
`gh_pr_view`, `gh_pr_diff`, `gh_pr_checks`, `gh_pr_create`, `gh_pr_comment`,
`gh_pr_merge`, `gh_pr_close`, `gh_pr_review`, `gh_issue_*`, `gh_run_*`,
`gh_workflow_run`, `gh_release_*`, and the escape hatches `gh_api` and
`gh_command` (run any `gh` invocation).

### A note on deploy paths

`home-mcp` runs `docker compose` *inside its own container* but against the
*host's* Docker daemon (via the mounted socket). So a project directory must:

1. exist **inside the container** (to read the compose file), and
2. match the **host path** (so bind mounts resolve correctly on the daemon side).

The simplest way to satisfy both: keep your stacks under one root (e.g.
`/srv/stacks`) and mount it at the identical path — which is exactly what
`STACKS_DIR` does in `docker-compose.yml`.

---

## Hardening checklist

- [ ] Strong, unique `HOME_MCP_TOKEN` (use `scripts/gen_token.py`); never committed.
- [ ] Reached only over **HTTPS** (proxy/tunnel terminates TLS).
- [ ] App **not** published directly to the internet (proxy-only, as in compose).
- [ ] Prefer a **VPN/Tailscale** + `HOME_MCP_IP_ALLOWLIST` so the port isn't even
      reachable publicly.
- [ ] Scope `GH_TOKEN` to only the repos/permissions you actually want managed.
- [ ] Keep deploys to **named projects** (leave `HOME_MCP_ALLOW_ANY_PATH=false`).
- [ ] Ship the **audit log** (`HOME_MCP_AUDIT_LOG`) somewhere you review.
- [ ] Consider a [docker-socket-proxy](https://github.com/Tecnativa/docker-socket-proxy)
      in front of the Docker socket to limit which API calls are even possible,
      and point the app at it with `DOCKER_HOST=tcp://docker-socket-proxy:2375`.

---

## Bare-metal install (no Docker for the server itself)

Requires Python 3.10+, plus `docker`, `docker compose`, `git` and `gh` on `PATH`.

```bash
pip install .
export HOME_MCP_TOKEN="$(python scripts/gen_token.py)"
export HOME_MCP_HOST=127.0.0.1 HOME_MCP_PORT=8848
export HOME_MCP_PROJECTS='{"blog":"/srv/stacks/blog"}'
home-mcp
```

Then front it with the provided `deploy/nginx.conf` or `deploy/Caddyfile`.

---

## Development

```bash
python -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
pytest
```

The tests cover auth, config parsing, deploy-path scoping, secret redaction and
the `gh` argument helpers — none require Docker or `gh` to be installed.

## License

MIT — see `pyproject.toml`.
