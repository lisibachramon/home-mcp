# home-mcp server image: Python + Docker CLI (+ compose plugin) + GitHub CLI + git.
# The Docker daemon is NOT included; mount the host's /var/run/docker.sock instead.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HOME_MCP_HOST=0.0.0.0 \
    HOME_MCP_PORT=8848

# Base tools + third-party apt repos for docker-cli, compose plugin and gh.
RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends ca-certificates curl gnupg git lsb-release; \
    install -m 0755 -d /etc/apt/keyrings; \
    # Docker CLI + compose plugin
    curl -fsSL https://download.docker.com/linux/debian/gpg -o /etc/apt/keyrings/docker.asc; \
    chmod a+r /etc/apt/keyrings/docker.asc; \
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/debian $(. /etc/os-release && echo \"$VERSION_CODENAME\") stable" \
        > /etc/apt/sources.list.d/docker.list; \
    # GitHub CLI
    curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg -o /etc/apt/keyrings/githubcli-archive-keyring.gpg; \
    chmod a+r /etc/apt/keyrings/githubcli-archive-keyring.gpg; \
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" \
        > /etc/apt/sources.list.d/github-cli.list; \
    apt-get update; \
    apt-get install -y --no-install-recommends docker-ce-cli docker-compose-plugin gh; \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install .

EXPOSE 8848

# Basic container healthcheck against the unauthenticated /healthz endpoint.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import os,urllib.request,sys; \
url='http://127.0.0.1:%s/healthz' % os.environ.get('HOME_MCP_PORT','8848'); \
sys.exit(0 if urllib.request.urlopen(url, timeout=3).status==200 else 1)"

CMD ["home-mcp"]
