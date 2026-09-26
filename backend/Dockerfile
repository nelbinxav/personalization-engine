FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ca-certificates tar \
    && rm -rf /var/lib/apt/lists/*

# The `ant` CLI provides the Claude OAuth device flow. Pinned by ANT_VERSION;
# leave it empty to resolve the latest release at build time.
#
# A failure here is deliberately non-fatal. The image still works in API-key
# mode, `ant_available()` reports false, and the Settings page explains that
# OAuth is unavailable -- far better than an unbuildable image because an
# upstream release URL moved.
ARG ANT_VERSION=""
RUN set -eux; \
    arch="$(uname -m | sed -e 's/x86_64/amd64/' -e 's/aarch64/arm64/')"; \
    version="${ANT_VERSION}"; \
    if [ -z "$version" ]; then \
        version="$(curl -fsSL https://api.github.com/repos/anthropics/anthropic-cli/releases/latest \
            | grep -m1 '"tag_name"' | sed -E 's/.*"v?([^"]+)".*/\1/')" || version=""; \
    fi; \
    if [ -n "$version" ]; then \
        url="https://github.com/anthropics/anthropic-cli/releases/download/v${version}/ant_${version}_linux_${arch}.tar.gz"; \
        if curl -fsSL "$url" | tar -xz -C /usr/local/bin ant; then \
            chmod +x /usr/local/bin/ant; \
            echo "Installed ant ${version}"; \
        else \
            echo "WARNING: could not install the ant CLI from ${url}; OAuth mode will be unavailable."; \
        fi; \
    else \
        echo "WARNING: could not resolve an ant CLI release; OAuth mode will be unavailable."; \
    fi

# Claude Code, installed unmodified from Anthropic's own installer, for the
# `claude_code` credential mode (the operator's own Claude subscription). Same
# non-fatal policy as `ant`: the image still builds without it, and Settings
# reports the mode as unavailable. Never patch or wrap this binary -- running it
# unmodified is what makes subscription use permissible.
RUN set -eux; \
    if curl -fsSL https://claude.ai/install.sh | bash; then \
        ln -sf "$(readlink -f /root/.local/bin/claude)" /usr/local/bin/claude; \
        claude --version; \
    else \
        echo "WARNING: could not install Claude Code; subscription mode will be unavailable."; \
    fi

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

# Profile volume, shared with the worker so both see the same credential.
ENV ANTHROPIC_CONFIG_DIR=/var/lib/anthropic \
    CLAUDE_CONFIG_DIR=/var/lib/claude-code
RUN mkdir -p /var/lib/anthropic /var/lib/claude-code

EXPOSE 8000

# Single worker is REQUIRED, not a default: the OAuth device flow holds a live
# `ant auth login` subprocess in memory between the /start and /complete calls.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
