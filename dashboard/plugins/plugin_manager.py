"""
YL StackOS — Plugin Manager
============================
Plugin-driven architecture. Base OS = Ubuntu 22.04 + SSH + Flask only.
Everything else is a plugin: VNC, code-server, filebrowser, wine, etc.

Plugin manifest schema:
  id, name, version, description, author, category, tags, source,
  requires[], apt_packages[], pip_packages[], install_script,
  remove_script, service{name,start,stop,check_port}, dashboard{port,route,iframe}

Installed registry: /ylstackos/plugins/installed.json
Custom plugins:     /ylstackos/plugins/custom/<id>/manifest.json
"""
from __future__ import annotations

import os, sys, json, socket, time, argparse
from pathlib import Path
from datetime import datetime
from typing import Iterator

# ── Paths ─────────────────────────────────────────────────────────────────────
_BASE       = Path('/ylstackos') if Path('/ylstackos').exists() else Path('/flyos')
PLUGINS_DIR = _BASE / 'plugins'
INSTALLED   = PLUGINS_DIR / 'installed.json'
CUSTOM_DIR  = PLUGINS_DIR / 'custom'
LOGS_DIR    = _BASE / 'logs'

# ── Official plugin catalog ───────────────────────────────────────────────────
CATALOG: dict[str, dict] = {
    "vnc": {
        "id": "vnc", "name": "VNC Desktop", "version": "1.0.0",
        "description": "Remote desktop via TigerVNC + noVNC web viewer",
        "author": "YL StackOS Team", "category": "desktop",
        "tags": ["vnc", "desktop", "gui"], "source": "official", "requires": [],
        "apt_packages": ["tigervnc-standalone-server", "xfce4", "xfce4-goodies", "dbus-x11"],
        "pip_packages": [],
        # install_script uses {{vnc_password}} — substituted from saved config at install time
        "install_script": """
mkdir -p /root/.vnc
printf '{{vnc_password}}\n{{vnc_password}}\nn\n' | vncpasswd
cat > /root/.vnc/xstartup << 'EOF'
#!/bin/sh
unset SESSION_MANAGER DBUS_SESSION_BUS_ADDRESS
exec startxfce4
EOF
chmod +x /root/.vnc/xstartup
""",
        "remove_script": "vncserver -kill :1 2>/dev/null; rm -rf /root/.vnc",
        "service": {"name": "vncserver",
                    "binary": "vncserver",
                    "start": "vncserver :1 -geometry 1280x720 -localhost no -rfbport 5900",
                    "stop": "vncserver -kill :1 2>/dev/null || true",
                    "check_port": 5900},
        "dashboard": {"port": 5003, "route": "/ui/system/vnc", "iframe": True},
        "config": {"geometry": "1280x720", "display": "1", "vnc_password": ""},
        # setup_fields: shown BEFORE install — values saved to config then used in install_script
        "setup_fields": [
            {"key": "vnc_password", "label": "VNC Password", "type": "password",
             "placeholder": "Min 6 characters", "required": True,
             "description": "Password required to connect to the VNC desktop"},
        ],
        "config_fields": [
            {"key": "geometry", "label": "Resolution", "type": "select",
             "options": ["1280x720", "1920x1080", "1024x768", "800x600"], "default": "1280x720"},
            {"key": "display", "label": "Display Number", "type": "text", "default": "1"},
        ],
    },
    "novnc": {
        "id": "novnc", "name": "noVNC Proxy", "version": "1.0.0",
        "description": "Browser-based VNC viewer (web proxy for VNC)",
        "author": "YL StackOS Team", "category": "desktop",
        "tags": ["vnc", "web", "proxy"], "source": "official", "requires": ["vnc"],
        "apt_packages": ["novnc", "websockify"],
        "pip_packages": [], "install_script": "", "remove_script": "",
        "service": {"name": "novnc",
                    "start": "/usr/share/novnc/utils/novnc_proxy --vnc localhost:5900 --listen 0.0.0.0:5003",
                    "stop": "pkill -f novnc_proxy",
                    "check_port": 5003},
        "dashboard": {"port": 5003, "route": "/ui/system/vnc", "iframe": True},
    },
    "code-server": {
        "id": "code-server", "name": "Code Server", "version": "4.96.2",
        "description": "VS Code in the browser (Coder)",
        "author": "Coder", "category": "dev",
        "tags": ["vscode", "editor", "ide"], "source": "official", "requires": [],
        "apt_packages": ["curl"],
        "pip_packages": [],
        # Direct GitHub release download — avoids install.sh using /system/bin/* (Android paths)
        "install_script": (
            "/usr/bin/curl -fsSL "
            "https://github.com/coder/code-server/releases/download/v4.96.2/"
            "code-server-4.96.2-linux-arm64.tar.gz "
            "-o /tmp/code-server.tar.gz && "
            "cd /tmp && /bin/tar -xzf code-server.tar.gz && "
            "/bin/cp -r /tmp/code-server-4.96.2-linux-arm64 /usr/lib/code-server && "
            "/bin/ln -sf /usr/lib/code-server/bin/code-server /usr/local/bin/code-server && "
            "/bin/rm -rf /tmp/code-server.tar.gz /tmp/code-server-4.96.2-linux-arm64"
        ),
        "remove_script": (
            "/bin/rm -f /usr/local/bin/code-server; "
            "/bin/rm -rf /usr/lib/code-server"
        ),
        "service": {
            "name": "code-server",
            "binary": "code-server",
            # {{auth}} substituted from saved config at start time
            # PASSWORD env var set automatically when auth=password
            "start": "code-server --bind-addr 0.0.0.0:{{port}} --auth {{auth}}",
            "stop": "ss -tlnp | grep :5004 | grep -o 'pid=[0-9]*' | cut -d= -f2 | xargs -r kill -9 2>/dev/null || true",
            "check_port": 5004
        },
        "dashboard": {"port": 5004, "route": "/ui/apps/code-server", "iframe": True},
        "config": {"port": "5004", "auth": "none", "password": ""},
        "config_fields": [
            {"key": "port", "label": "Port", "type": "text", "default": "5004"},
            {"key": "auth", "label": "Authentication", "type": "select",
             "options": ["none", "password"], "default": "none",
             "description": "Enable password protection for Code Server"},
            {"key": "password", "label": "Password", "type": "password",
             "default": "", "placeholder": "Required when auth = password",
             "description": "Set a password (only used when Authentication is set to 'password')",
             "show_if": {"key": "auth", "value": "password"}},
        ],
    },
    "filebrowser": {
        "id": "filebrowser", "name": "File Browser", "version": "latest",
        "description": "Web-based file manager",
        "author": "filebrowser", "category": "tools",
        "tags": ["files", "web", "manager"], "source": "official", "requires": [],
        "apt_packages": [],
        "pip_packages": [],
        "install_script": "curl -fsSL https://raw.githubusercontent.com/filebrowser/get/master/get.sh | bash",
        "remove_script": "rm -f /usr/local/bin/filebrowser",
        "service": {"name": "filebrowser",
                    "binary": "filebrowser",
                    "start": "filebrowser -p 5008 -a 0.0.0.0 -r / -d /ylstackosext/filebrowser/filebrowser.db",
                    "stop": "pkill -f filebrowser",
                    "check_port": 5008},
        "dashboard": {"port": 5008, "route": "/ui/system/files", "iframe": True},
        "config": {"port": "5008", "root": "/"},
        "config_fields": [
            {"key": "port", "label": "Port", "type": "text", "default": "5008"},
            {"key": "root", "label": "Root Directory", "type": "text", "default": "/"},
        ],
    },
    "wine": {
        "id": "wine", "name": "WINE", "version": "8.0",
        "description": "Run Windows applications",
        "author": "WineHQ", "category": "desktop",
        "tags": ["wine", "windows", "apps"], "source": "official", "requires": ["vnc"],
        "apt_packages": ["wine64"],
        "pip_packages": [],
        "install_script": "dpkg --add-architecture i386; apt-get update; DEBIAN_FRONTEND=noninteractive apt-get install -y wine32:i386 winetricks",
        "remove_script": "rm -rf /root/.wine",
        "service": None,
        "dashboard": {"port": None, "route": "/ui/apps/wine", "iframe": False},
    },
    "jupyter": {
        "id": "jupyter", "name": "Jupyter Notebook", "version": "latest",
        "description": "Interactive Python notebooks in the browser",
        "author": "Project Jupyter", "category": "dev",
        "tags": ["python", "notebook", "data", "ml"], "source": "official", "requires": [],
        "apt_packages": ["python3-pip"],
        "pip_packages": ["jupyter", "notebook"],
        "install_script": "", "remove_script": "",
        "service": {"name": "jupyter",
                    "start": "jupyter notebook --ip=0.0.0.0 --port=5996 --no-browser --allow-root --NotebookApp.token=''",
                    "stop": "pkill -f jupyter",
                    "check_port": 5996},
        "dashboard": {"port": 5996, "route": "/ui/apps/jupyter", "iframe": True},
    },
    "nginx": {
        "id": "nginx", "name": "Nginx", "version": "latest",
        "description": "Web server and reverse proxy",
        "author": "nginx", "category": "server",
        "tags": ["web", "server", "proxy"], "source": "official", "requires": [],
        "apt_packages": ["nginx"],
        "pip_packages": [], "install_script": "", "remove_script": "",
        "service": {"name": "nginx", "start": "nginx", "stop": "nginx -s stop", "check_port": 80},
        "dashboard": None,
    },
    "mysql": {
        "id": "mysql", "name": "MySQL", "version": "8.0",
        "description": "MySQL database server",
        "author": "Oracle", "category": "data",
        "tags": ["database", "sql", "mysql"], "source": "official", "requires": [],
        "apt_packages": ["mysql-server"],
        "pip_packages": [],
        "pre_install_notes": "MySQL requires ~200MB disk space and may take several minutes to install.",
        "install_script": "DEBIAN_FRONTEND=noninteractive apt-get install -y mysql-server && mysqld --initialize-insecure --user=root 2>/dev/null || true",
        "remove_script": "",
        "service": {"name": "mysql", "start": "mysqld_safe --user=root &", "stop": "mysqladmin -u root shutdown 2>/dev/null || pkill mysqld", "check_port": 3306},
        "dashboard": None,
        "config": {"port": "3306"},
        "config_fields": [
            {"key": "port", "label": "Port", "type": "text", "default": "3306"},
        ],
    },
    "redis": {
        "id": "redis", "name": "Redis", "version": "latest",
        "description": "In-memory data store and cache",
        "author": "Redis Ltd.", "category": "data",
        "tags": ["cache", "redis", "nosql"], "source": "official", "requires": [],
        "apt_packages": ["redis-server"],
        "pip_packages": [],
        "pre_install_notes": "Redis will be installed via apt. Requires ~5MB disk space.",
        "install_script": "",
        "remove_script": "",
        "service": {
            "name": "redis",
            "binary": "redis-server",
            "start": "redis-server --daemonize yes --bind 0.0.0.0 --port 6379",
            "stop": "redis-cli shutdown 2>/dev/null || /bin/kill $(/bin/cat /var/run/redis/redis-server.pid 2>/dev/null) 2>/dev/null || true",
            "check_port": 6379
        },
        "dashboard": None,
        "config": {"port": "6379", "bind": "0.0.0.0"},
        "config_fields": [
            {"key": "port", "label": "Port", "type": "text", "default": "6379"},
            {"key": "bind", "label": "Bind Address", "type": "text", "default": "0.0.0.0"},
        ],
    },
    "cloudflared": {
        "id": "cloudflared", "name": "Cloudflare Tunnel", "version": "latest",
        "description": "Expose services via Cloudflare Zero Trust tunnel",
        "author": "Cloudflare", "category": "network",
        "tags": ["cloudflare", "tunnel", "network"], "source": "official", "requires": [],
        "apt_packages": [],
        "pip_packages": [],
        "install_script": (
            "mkdir -p /ylstackosext/cloudflared && "
            "curl -L https://github.com/cloudflare/cloudflared/releases/latest/download/"
            "cloudflared-linux-arm64 -o /ylstackosext/cloudflared/cloudflared && "
            "chmod +x /ylstackosext/cloudflared/cloudflared"
        ),
        "remove_script": "rm -f /ylstackosext/cloudflared/cloudflared",
        "service": None,
        "dashboard": {"port": None, "route": "/ui/network/cloudflare", "iframe": False},
    },
    "openclaw": {
        "id": "openclaw", "name": "OpenClaw AI Agent", "version": "latest",
        "description": "Self-hosted AI agent with 20+ messaging channels (Telegram, Discord, WhatsApp), 13,700+ skills, and local LLM support via Ollama. Runs as a persistent Gateway on port 18789.",
        "author": "YL StackOS Community", "category": "ai",
        "tags": ["ai", "agent", "llm", "telegram", "discord", "ollama", "automation", "openclaw"],
        "source": "community", "requires": [],
        "apt_packages": ["curl", "git"],
        "pip_packages": [],
        "pre_install_notes": "Requires ~200MB disk space. Node.js 22 will be installed automatically. Choose a model provider — use Ollama for fully local/private AI with no API costs.",
        # setup_fields: collected BEFORE install, values substituted into install_script
        "setup_fields": [
            # ── Gateway Network Settings ─────────────────────────────────────────
            {"key": "gateway_bind", "label": "Gateway Bind Address", "type": "select",
             "options": ["lan", "loopback"],
             "default": "lan", "required": True,
             "description": "lan = accessible from network (0.0.0.0), loopback = localhost only"},
            {"key": "gateway_port", "label": "Gateway Port", "type": "number",
             "default": "18789", "required": True,
             "description": "Port for OpenClaw Control UI"},
            {"key": "gateway_token", "label": "Gateway Access Token", "type": "password",
             "default": "ylstackos-openclaw-token", "placeholder": "Set a secure token",
             "required": True,
             "description": "Token to access the OpenClaw Control UI."},
            # ── AI Model Configuration ───────────────────────────────────────────
            {"key": "model_provider", "label": "AI Model Provider", "type": "select",
             "options": ["ollama", "anthropic", "openai", "openrouter", "google", "deepseek"],
             "default": "ollama", "required": True,
             "description": "Choose your AI provider. Ollama = fully local. OpenAI = any OpenAI-compatible endpoint."},
            {"key": "model_id", "label": "Model ID", "type": "text",
             "default": "llama3.1:8b", "required": True,
             "description": "e.g. llama3.1:8b, gpt-4o, claude-opus-4-6-20260205, qwen2.5:7b"},
            {"key": "custom_base_url", "label": "Custom Base URL (OpenAI-compatible)", "type": "text",
             "default": "", "placeholder": "http://localhost:11434/v1",
             "required": False,
             "description": "Override API endpoint for LM Studio, vLLM, Ollama, or any OpenAI-compatible server.",
             "show_if": {"key": "model_provider", "value": "openai"}},
            {"key": "api_key", "label": "API Key", "type": "password",
             "default": "", "placeholder": "sk-ant-... or sk-... or AIza...",
             "required": False,
             "description": "API key for your chosen provider. Not needed for Ollama.",
             "show_if": {"key": "model_provider", "value": "anthropic"}},
            {"key": "api_key_openai", "label": "API Key (OpenAI / Custom)", "type": "password",
             "default": "", "placeholder": "sk-... or any-key for local servers",
             "required": False, "description": "API key. For local servers use any non-empty string.",
             "show_if": {"key": "model_provider", "value": "openai"}},
            {"key": "api_key_openrouter", "label": "OpenRouter API Key", "type": "password",
             "default": "", "placeholder": "sk-or-...",
             "required": False, "description": "Your OpenRouter API key.",
             "show_if": {"key": "model_provider", "value": "openrouter"}},
            {"key": "api_key_google", "label": "Google API Key", "type": "password",
             "default": "", "placeholder": "AIza...",
             "required": False, "description": "Your Google AI Studio API key.",
             "show_if": {"key": "model_provider", "value": "google"}},
            {"key": "api_key_deepseek", "label": "DeepSeek API Key", "type": "password",
             "default": "", "placeholder": "sk-...",
             "required": False, "description": "Your DeepSeek API key.",
             "show_if": {"key": "model_provider", "value": "deepseek"}},
            # ── Messaging Channels (optional) ─────────────────────────────────────
            {"key": "telegram_bot_token", "label": "Telegram Bot Token (optional)", "type": "text",
             "default": "", "placeholder": "123456789:ABCdef...",
             "required": False,
             "description": "Create a bot via @BotFather on Telegram. Leave empty to use Web UI only."},
            {"key": "telegram_allow_from", "label": "Telegram Allowed Chat IDs (optional)", "type": "text",
             "default": "", "placeholder": "123456789, 987654321",
             "required": False,
             "description": "Comma-separated Telegram user IDs allowed to use the bot. Leave empty to allow all."},
            {"key": "discord_bot_token", "label": "Discord Bot Token (optional)", "type": "text",
             "default": "", "placeholder": "MTk4NjIyNDgzNDc...",
             "required": False,
             "description": "Create via Discord Developer Portal. Leave empty to use Web UI only."},
        ],
        # Install: Node.js 22 via NodeSource → npm install openclaw → init dirs → doctor fix
        # openclaw.json is written by install_stream() post-install (not here)
        "install_script": (
            "export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin && "
            "/usr/bin/curl -fsSL https://deb.nodesource.com/setup_22.x | /bin/bash - && "
            "/usr/bin/apt-get install -y nodejs && "
            "/usr/bin/npm install -g openclaw@latest --unsafe-perm && "
            "/bin/mkdir -p /root/.openclaw/agents/main/sessions /root/.openclaw/agents/main/agent /root/.openclaw/credentials && "
            "/bin/chmod 700 /root/.openclaw"
        ),
        # Remove: stop gateway, remove config, uninstall npm packages (openclaw + clawhub)
        "remove_script": (
            "/usr/bin/ss -tlnp | /bin/grep 18789 | /usr/bin/awk '{print $6}' | /usr/bin/awk -F= '{print $2}' | /usr/bin/xargs -r /bin/kill -9 2>/dev/null || true; "
            "/bin/rm -rf /root/.openclaw 2>/dev/null || true; "
            "/usr/bin/npm uninstall -g openclaw clawhub 2>/dev/null || true"
        ),
        "service": {
            "name": "openclaw-gateway",
            "binary": "openclaw",
            # openclaw gateway run --bind {{gateway_bind}} — foreground, setsid handles backgrounding
            # --bind lan = 0.0.0.0 (network), --bind loopback = 127.0.0.1 (local only)
            "start": "openclaw gateway run --bind {{gateway_bind}}",
            "stop": "/usr/bin/ss -tlnp | /bin/grep 18789 | /usr/bin/awk '{print $6}' | /usr/bin/awk -F= '{print $2}' | /usr/bin/xargs -r /bin/kill -9 2>/dev/null || true",
            "check_port": 18789
        },
        "dashboard": {"port": None, "route": "/openclaw-proxy/", "iframe": False},
        "config": {
            "model_provider": "ollama",
            "model_id": "llama3.1:8b",
            "api_key": "",
            "telegram_bot_token": "",
            "telegram_allow_from": "",
            "discord_bot_token": "",
            "gateway_token": "ylstackos-openclaw-token",
            "gateway_port": "18789",
            "gateway_bind": "lan",
            "gateway_mode": "local",
            "allow_insecure_auth": True,
            "custom_base_url": "",
            "extra_allowed_origins": "",
        },
        "config_fields": [
            # ── Gateway Network Settings ─────────────────────────────────────────
            {"key": "gateway_bind", "label": "Gateway Bind Address", "type": "select",
             "options": ["lan", "loopback"],
             "default": "lan",
             "description": "lan = accessible from network (0.0.0.0), loopback = localhost only"},
            {"key": "gateway_port", "label": "Gateway Port", "type": "number",
             "default": "18789",
             "description": "Port for OpenClaw Control UI"},
            {"key": "gateway_mode", "label": "Gateway Mode", "type": "select",
             "options": ["local", "cloud"],
             "default": "local",
             "description": "local = self-hosted, cloud = OpenClaw cloud relay"},
            {"key": "allow_insecure_auth", "label": "Allow Insecure Auth", "type": "checkbox",
             "default": True,
             "description": "Allow token auth over HTTP (not HTTPS). Disable if using reverse proxy with SSL."},
            # ── Token Management ─────────────────────────────────────────────────
            {"key": "gateway_token", "label": "Gateway Access Token", "type": "password",
             "default": "ylstackos-openclaw-token",
             "description": "Token to access Control UI. Change this for security!"},
            # ── AI Model Configuration ───────────────────────────────────────────
            {"key": "model_provider", "label": "AI Model Provider", "type": "select",
             "options": ["ollama", "anthropic", "openai", "openrouter", "google", "deepseek"],
             "default": "ollama",
             "description": "Ollama = fully local, no API key needed. OpenAI = any OpenAI-compatible endpoint."},
            {"key": "model_id", "label": "Model ID", "type": "text",
             "default": "llama3.1:8b",
             "description": "e.g. llama3.1:8b, gpt-4o, claude-opus-4-6-20260205, qwen2.5:7b"},
            {"key": "custom_base_url", "label": "Custom Base URL (OpenAI-compatible)", "type": "text",
             "default": "", "placeholder": "http://localhost:11434/v1",
             "description": "Override the API endpoint. Use for LM Studio, vLLM, Ollama, or any OpenAI-compatible server.",
             "show_if": {"key": "model_provider", "value": "openai"}},
            {"key": "api_key", "label": "API Key (Anthropic)", "type": "password",
             "default": "",
             "description": "Anthropic API key",
             "show_if": {"key": "model_provider", "value": "anthropic"}},
            {"key": "api_key_openai", "label": "API Key (OpenAI / Custom)", "type": "password",
             "default": "", "placeholder": "sk-... or any-key for local servers",
             "description": "API key. For local servers (LM Studio, vLLM) use any non-empty string.",
             "show_if": {"key": "model_provider", "value": "openai"}},
            {"key": "api_key_openrouter", "label": "API Key (OpenRouter)", "type": "password",
             "default": "",
             "description": "OpenRouter API key",
             "show_if": {"key": "model_provider", "value": "openrouter"}},
            {"key": "api_key_google", "label": "API Key (Google)", "type": "password",
             "default": "",
             "description": "Google AI Studio API key",
             "show_if": {"key": "model_provider", "value": "google"}},
            {"key": "api_key_deepseek", "label": "API Key (DeepSeek)", "type": "password",
             "default": "",
             "description": "DeepSeek API key",
             "show_if": {"key": "model_provider", "value": "deepseek"}},
            # ── Messaging Channels ───────────────────────────────────────────────
            {"key": "telegram_bot_token", "label": "Telegram Bot Token", "type": "text",
             "default": "", "placeholder": "123456789:ABCdef...",
             "description": "Create via @BotFather. Enables Telegram channel."},
            {"key": "telegram_allow_from", "label": "Telegram Allowed Chat IDs", "type": "text",
             "default": "", "placeholder": "123456789, 987654321",
             "description": "Comma-separated Telegram user/chat IDs allowed to use the bot. Leave empty to allow all. Prevents unauthorized access."},
            {"key": "discord_bot_token", "label": "Discord Bot Token", "type": "text",
             "default": "", "placeholder": "MTk4NjIyNDgzNDc...",
             "description": "Create via Discord Developer Portal. Enables Discord channel."},
            # ── Advanced / Origins ───────────────────────────────────────────────
            {"key": "extra_allowed_origins", "label": "Extra Allowed Origins", "type": "text",
             "default": "", "placeholder": "http://192.168.1.100:18789, http://myhost:5000",
             "description": "Comma-separated extra origins allowed to access Control UI. Add your browser's URL if you see 'origin not allowed' errors."},
        ],
    },
    "fastclaw": {
        "id": "fastclaw", "name": "FastClaw AI Agent", "version": "latest",
        "description": (
            "Lightweight Go-based AI Agent Factory. Single binary, any LLM, multi-agent, "
            "sandbox, cloud-ready. Runs a persistent gateway on port 18953 with a built-in "
            "web dashboard. Supports OpenAI, Anthropic, Ollama, OpenRouter, Groq, DeepSeek, "
            "Mistral and any OpenAI-compatible API. Per-agent Telegram/Discord/Slack channels."
        ),
        "author": "FastClaw AI", "category": "ai",
        "tags": ["ai", "agent", "llm", "telegram", "discord", "ollama", "automation", "fastclaw", "go"],
        "source": "community", "requires": [],
        "apt_packages": ["curl"],
        "pip_packages": [],
        # native_setup: True — this plugin has its own first-run setup wizard in its web UI.
        # setup_fields below are OPTIONAL pre-configuration (port/bind only).
        # The frontend shows them as optional with a "Skip — configure in FastClaw UI" button.
        # Model provider, API keys, agents etc. are all configured inside FastClaw's own dashboard.
        "native_setup": True,
        "native_setup_note": (
            "FastClaw has its own setup wizard at http://<device-ip>:18953/ on first launch. "
            "You can configure LLM providers, agents, channels, and skills there. "
            "Only port and bind address need to be set here."
        ),
        "pre_install_notes": (
            "Single Go binary (~30MB). No Node.js required. "
            "Data stored in /root/.fastclaw/ (SQLite + skills + agents). "
            "Model providers, agents, and channels are configured in FastClaw's own web UI after install."
        ),
        # setup_fields: ALL optional — only port/bind matter here.
        # Model/API config is handled by FastClaw's own first-run wizard.
        "setup_fields": [
            # ── Gateway Network Settings (the only things we actually need) ───────
            {"key": "gateway_bind", "label": "Gateway Bind Address", "type": "select",
             "options": ["all", "loopback"],
             "default": "all", "required": False,
             "description": "all = accessible from network (0.0.0.0), loopback = localhost only"},
            {"key": "gateway_port", "label": "Gateway Port", "type": "number",
             "default": "18953", "required": False,
             "description": "Port for FastClaw web dashboard"},
            # ── Optional pre-config (can be done in FastClaw UI instead) ─────────
            {"key": "model_provider", "label": "AI Model Provider (optional)", "type": "select",
             "options": ["ollama", "openai", "anthropic", "openrouter", "groq", "deepseek", "mistral"],
             "default": "ollama", "required": False,
             "description": "Optional — configure in FastClaw UI after install. Ollama = fully local."},
            {"key": "model_id", "label": "Default Model ID (optional)", "type": "text",
             "default": "llama3.1:8b", "required": False,
             "description": "Optional — configure in FastClaw UI after install. e.g. llama3.1:8b, gpt-4o"},
            {"key": "api_key", "label": "API Key (optional)", "type": "password",
             "default": "", "placeholder": "sk-... or leave empty",
             "required": False,
             "description": "Optional — configure in FastClaw UI after install. Not needed for Ollama."},
        ],
        # Install: download official install.sh → installs binary to /usr/local/bin (system-wide)
        # FASTCLAW_INSTALL_DIR must be exported BEFORE the pipe — env var prefix on os.system()
        # is not inherited by the subshell. Use 'export' inside the script instead.
        # HOME=/root ensures ~/.local/bin resolves correctly if FASTCLAW_INSTALL_DIR is unset.
        "install_script": (
            "export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin && "
            "export HOME=/root && "
            "export FASTCLAW_INSTALL_DIR=/usr/local/bin && "
            "/usr/bin/curl -fsSL https://raw.githubusercontent.com/fastclaw-ai/fastclaw/main/install.sh -o /tmp/fastclaw_install.sh && "
            "/bin/sh /tmp/fastclaw_install.sh && "
            "/bin/rm -f /tmp/fastclaw_install.sh && "
            "/bin/mkdir -p /root/.fastclaw"
        ),
        # Remove: stop gateway, remove data dir, remove binary
        "remove_script": (
            "/usr/bin/ss -tlnp | /bin/grep 18953 | /usr/bin/awk '{print $6}' | "
            "/usr/bin/awk -F= '{print $2}' | /usr/bin/xargs -r /bin/kill -9 2>/dev/null || true; "
            "/bin/rm -rf /root/.fastclaw 2>/dev/null || true; "
            "/bin/rm -f /usr/local/bin/fastclaw 2>/dev/null || true"
        ),
        "service": {
            "name": "fastclaw-gateway",
            "binary": "fastclaw",
            # Run foreground — setsid in start_service handles backgrounding
            # FASTCLAW_* env vars are the only config mechanism (no config file)
            # {{key}} placeholders are substituted from saved config at start time
            "start": (
                "FASTCLAW_PORT={{gateway_port}} "
                "FASTCLAW_BIND={{gateway_bind}} "
                "FASTCLAW_HOME=/root/.fastclaw "
                "FASTCLAW_LOG_LEVEL=info "
                "fastclaw"
            ),
            "stop": (
                "/usr/bin/ss -tlnp | /bin/grep {{gateway_port}} | "
                "/usr/bin/awk '{print $6}' | /usr/bin/awk -F= '{print $2}' | "
                "/usr/bin/xargs -r /bin/kill -9 2>/dev/null || true"
            ),
            "check_port": 18953,
        },
        # Direct iframe — fastclaw serves its own web UI, no proxy needed
        # (Go binary, no WebCrypto same-origin issue unlike openclaw's Node.js Control UI)
        "dashboard": {"port": 18953, "route": "/ui/apps/fastclaw", "iframe": True},
        "config": {
            "gateway_bind": "all",
            "gateway_port": "18953",
            "admin_token": "ylstackos-fastclaw-token",
            "model_provider": "ollama",
            "model_id": "llama3.1:8b",
            "api_key": "",
            "custom_base_url": "",
        },
        "config_fields": [
            # ── Gateway Network Settings ─────────────────────────────────────────
            {"key": "gateway_bind", "label": "Gateway Bind Address", "type": "select",
             "options": ["all", "loopback"],
             "default": "all",
             "description": "all = accessible from network (0.0.0.0), loopback = localhost only"},
            {"key": "gateway_port", "label": "Gateway Port", "type": "number",
             "default": "18953",
             "description": "Port for FastClaw web dashboard"},
            {"key": "admin_token", "label": "Admin Token", "type": "password",
             "default": "ylstackos-fastclaw-token",
             "description": "Admin access token. Change this for security!"},
            # ── AI Model Configuration ───────────────────────────────────────────
            {"key": "model_provider", "label": "AI Model Provider", "type": "select",
             "options": ["ollama", "openai", "anthropic", "openrouter", "groq", "deepseek", "mistral"],
             "default": "ollama",
             "description": "Ollama = fully local, no API key needed. OpenAI = any OpenAI-compatible endpoint."},
            {"key": "model_id", "label": "Default Model ID", "type": "text",
             "default": "llama3.1:8b",
             "description": "e.g. llama3.1:8b, gpt-4o, claude-opus-4-5, qwen2.5:7b"},
            {"key": "api_key", "label": "API Key", "type": "password",
             "default": "",
             "description": "API key for your chosen provider. Not needed for Ollama."},
            {"key": "custom_base_url", "label": "Custom Base URL (OpenAI-compatible)", "type": "text",
             "default": "", "placeholder": "http://localhost:11434/v1",
             "description": "Override the API endpoint. Use for LM Studio, vLLM, Ollama, or any OpenAI-compatible server.",
             "show_if": {"key": "model_provider", "value": "openai"}},
        ],
    },
    "postgresql": {
        "id": "postgresql", "name": "PostgreSQL", "version": "14",
        "description": "Advanced open-source relational database",
        "author": "PostgreSQL", "category": "data",
        "tags": ["database", "sql", "postgres"], "source": "official", "requires": [],
        "apt_packages": ["postgresql", "postgresql-contrib"],
        "pip_packages": [], "install_script": "", "remove_script": "",
        "service": {"name": "postgresql", "start": "pg_ctlcluster 14 main start", "stop": "pg_ctlcluster 14 main stop", "check_port": 5432},
        "dashboard": None,
    },
}


# ── OpenClaw provider config builder ─────────────────────────────────────────
# OpenClaw schema requires: baseUrl (string), apiKey, models (array with id+name required)
# All three fields are required for every provider entry.
_PROVIDER_DEFAULTS = {
    'ollama':      {'baseUrl': 'http://127.0.0.1:11434/v1', 'api': 'openai-completions'},
    'anthropic':   {'baseUrl': 'https://api.anthropic.com', 'api': 'anthropic-messages'},
    'openai':      {'baseUrl': 'https://api.openai.com/v1', 'api': 'openai-responses'},
    'openrouter':  {'baseUrl': 'https://openrouter.ai/api/v1', 'api': 'openai-responses'},
    'google':      {'baseUrl': 'https://generativelanguage.googleapis.com/v1beta', 'api': 'google-generative-ai'},
    'deepseek':    {'baseUrl': 'https://api.deepseek.com/v1', 'api': 'openai-responses'},
}
_PROVIDER_DEFAULT_MODELS = {
    'ollama':      [{'id': 'qwen2.5:7b',          'name': 'Qwen 2.5 (7B)',          'api': 'openai-completions', 'input': ['text'], 'cost': {'input': 0, 'output': 0, 'cacheRead': 0, 'cacheWrite': 0}}],
    'anthropic':   [{'id': 'claude-opus-4-6-20260205', 'name': 'Claude Opus 4.6',   'api': 'anthropic-messages', 'input': ['text', 'image']}],
    'openai':      [{'id': 'gpt-4o',               'name': 'GPT-4o',                'api': 'openai-responses',   'input': ['text', 'image']}],
    'openrouter':  [{'id': 'openai/gpt-4o',        'name': 'GPT-4o (OpenRouter)',   'api': 'openai-responses',   'input': ['text', 'image']}],
    'google':      [{'id': 'gemini-2.0-flash',     'name': 'Gemini 2.0 Flash',      'api': 'google-generative-ai', 'input': ['text', 'image']}],
    'deepseek':    [{'id': 'deepseek-chat',        'name': 'DeepSeek Chat',         'api': 'openai-responses',   'input': ['text']}],
}

def _build_allowed_origins(extra_origins_str: str = '') -> list:
    """Build the allowedOrigins list for OpenClaw controlUi.
    Always includes the required dashboard proxy origins.
    extra_origins_str: comma-separated extra origins from user config.
    """
    # Always required — dashboard proxy + direct gateway access
    base = [
        'http://localhost:18789',
        'http://127.0.0.1:18789',
        'http://192.168.1.188:18789',  # direct gateway access from LAN
        'http://192.168.1.188:5000',   # dashboard proxy origin
        'http://localhost:5000',
    ]
    if extra_origins_str and extra_origins_str.strip():
        for o in extra_origins_str.split(','):
            o = o.strip().rstrip('/')
            if o and o not in base:
                base.append(o)
    return base


def _openclaw_provider_config(provider: str, api_key: str, model_id: str = '', custom_base_url: str = '') -> dict:
    """Return a valid models.providers entry for the given provider.
    
    OpenClaw schema requires: baseUrl (string), apiKey, models (array, each needs id+name).
    custom_base_url: overrides the default baseUrl — for LM Studio, vLLM, Ollama, any OpenAI-compatible server.
    """
    defaults = _PROVIDER_DEFAULTS.get(provider, {'baseUrl': '', 'api': 'openai-responses'})
    # Use custom_base_url if provided (for OpenAI-compatible custom endpoints)
    base_url = custom_base_url.strip() if custom_base_url and custom_base_url.strip() else defaults['baseUrl']
    api_format = defaults.get('api', 'openai-responses')
    # Use the user's model_id if provided, otherwise use the default for this provider
    default_models = _PROVIDER_DEFAULT_MODELS.get(provider, [{'id': model_id or provider, 'name': model_id or provider}])
    if model_id and model_id != default_models[0].get('id', ''):
        # User specified a different model — use it as the primary model entry
        model_entry = {'id': model_id, 'name': model_id, 'api': api_format, 'input': ['text']}
        if provider == 'ollama' or custom_base_url:
            model_entry['cost'] = {'input': 0, 'output': 0, 'cacheRead': 0, 'cacheWrite': 0}
        models_list = [model_entry]
    else:
        models_list = list(default_models)
        # Update model api format if using custom endpoint
        if custom_base_url and models_list:
            models_list[0] = dict(models_list[0])
            models_list[0]['api'] = 'openai-completions'
    return {
        'baseUrl': base_url,
        'apiKey': api_key or ('ollama-local' if provider == 'ollama' else 'local'),
        'models': models_list,
    }


class PluginManager:
    def __init__(self):
        PLUGINS_DIR.mkdir(parents=True, exist_ok=True)
        LOGS_DIR.mkdir(parents=True, exist_ok=True)

    # ── Registry ──────────────────────────────────────────────────────────────

    def all_plugins(self) -> dict[str, dict]:
        plugins = dict(CATALOG)
        if CUSTOM_DIR.exists():
            for d in CUSTOM_DIR.iterdir():
                if d.is_dir():
                    mf = d / 'manifest.json'
                    if mf.exists():
                        try:
                            m = json.loads(mf.read_text())
                            m['source'] = 'custom'
                            plugins[m['id']] = m
                        except Exception:
                            pass
        return plugins

    def get(self, pid: str) -> dict | None:
        return self.all_plugins().get(pid)

    def installed_db(self) -> dict:
        try:
            return json.loads(INSTALLED.read_text()) if INSTALLED.exists() else {}
        except Exception:
            return {}

    def is_installed(self, pid: str) -> bool:
        return pid in self.installed_db()

    def _save(self, db: dict):
        INSTALLED.write_text(json.dumps(db, indent=2))

    # ── Status ────────────────────────────────────────────────────────────────

    def port_running(self, port: int | None) -> bool:
        if not port:
            return False
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(0.3)
            ok = s.connect_ex(('127.0.0.1', port)) == 0
            s.close()
            return ok
        except Exception:
            return False

    def service_status(self, pid: str) -> str:
        m = self.get(pid)
        if not m or not m.get('service'):
            return 'n/a'
        port = m['service'].get('check_port')
        return 'running' if self.port_running(port) else 'stopped'

    def check_existing(self, pid: str) -> dict:
        """Check if plugin has existing config/service before install.
        Returns dict with: has_config, has_service_running, config_file, backup_suggested
        """
        m = self.get(pid)
        if not m:
            return {'has_config': False, 'has_service_running': False}
        
        result = {'has_config': False, 'has_service_running': False, 'config_file': None, 'backup_suggested': False}
        
        # Check for existing config file
        config_file = PLUGINS_DIR / f"{pid}.config.json"
        if config_file.exists():
            result['has_config'] = True
            result['config_file'] = str(config_file)
        
        # Check for plugin-specific config locations
        if pid == 'openclaw':
            openclaw_config = Path('/root/.openclaw/openclaw.json')
            if openclaw_config.exists():
                result['has_config'] = True
                result['config_file'] = str(openclaw_config)

        if pid == 'fastclaw':
            fastclaw_db = Path('/root/.fastclaw/fastclaw.db')
            if fastclaw_db.exists():
                result['has_config'] = True
                result['config_file'] = str(fastclaw_db)
        
        # Check if service is already running (port in use)
        svc = m.get('service')
        if svc and svc.get('check_port'):
            if self.port_running(svc['check_port']):
                result['has_service_running'] = True
        
        # Suggest backup if any existing data found
        result['backup_suggested'] = result['has_config'] or result['has_service_running']
        
        return result

    def list_status(self) -> list[dict]:
        installed = self.installed_db()
        return [{
            'id': pid,
            'name': m['name'],
            'version': m['version'],
            'description': m['description'],
            'category': m.get('category', 'tools'),
            'tags': m.get('tags', []),
            'source': m.get('source', 'official'),
            'requires': m.get('requires', []),
            'pre_install_notes': m.get('pre_install_notes', ''),
            'installed': pid in installed,
            'installed_at': installed.get(pid, {}).get('installed_at'),
            'boot': installed.get(pid, {}).get('boot', False),
            'service_status': self.service_status(pid) if pid in installed else None,
            'has_service': bool(m.get('service')),
            'dashboard': m.get('dashboard'),
            'config_fields': m.get('config_fields', []),
            'setup_fields': m.get('setup_fields', []),
            'native_setup': m.get('native_setup', False),
            'native_setup_note': m.get('native_setup_note', ''),
            # Existing detection for non-installed plugins
            'existing': None if pid in installed else self.check_existing(pid),
        } for pid, m in self.all_plugins().items()]

    # ── Install / Remove ──────────────────────────────────────────────────────

    def install_stream(self, pid: str) -> Iterator[str]:
        m = self.get(pid)
        if not m:
            yield f"error: Plugin '{pid}' not found\n"; return
        if self.is_installed(pid):
            yield f"info: {m['name']} already installed\n"; return
        for req in m.get('requires', []):
            if not self.is_installed(req):
                yield f"error: Requires '{req}' to be installed first\n"; return

        yield f"[*] Installing {m['name']} v{m['version']}...\n"
        log = LOGS_DIR / f"plugin_{pid}_install.log"

        if m.get('apt_packages'):
            pkgs = ' '.join(m['apt_packages'])
            yield f"[apt] Updating package list...\n"
            # --allow-unauthenticated handles missing gpgv in chroot
            os.system(f"/usr/bin/apt-get update -qq --allow-unauthenticated >> {log} 2>&1")
            yield f"[apt] Installing: {pkgs}\n"
            ret = os.system(
                f"DEBIAN_FRONTEND=noninteractive /usr/bin/apt-get install -y "
                f"--no-install-recommends --allow-unauthenticated {pkgs} >> {log} 2>&1"
            )
            if ret != 0:
                yield f"error: apt install failed — check {log}\n"
                return

        for pkg in m.get('pip_packages', []):
            yield f"[pip] {pkg}\n"
            os.system(f"/usr/bin/pip3 install {pkg} >> {log} 2>&1")

        if m.get('install_script', '').strip():
            yield "[sh] Running install script...\n"
            # Substitute {{key}} placeholders from saved config
            script = m['install_script']
            saved_cfg = self.get_config(pid)
            for k, v in saved_cfg.items():
                script = script.replace('{{' + k + '}}', str(v))
            # Warn if any unresolved placeholders remain
            import re as _re
            unresolved = _re.findall(r'\{\{(\w+)\}\}', script)
            if unresolved:
                yield f"warning: unresolved placeholders: {', '.join(unresolved)}\n"
            ret = os.system(f"/bin/bash -c '{script}' >> {log} 2>&1")
            if ret != 0:
                yield f"warning: script returned {ret}\n"

        # ── Post-install: discover binary path ────────────────────────────────
        # If the service has a 'binary' hint, find where it was installed
        # and store the resolved path so start_service doesn't need hardcoded paths
        svc = m.get('service')
        if svc and svc.get('binary'):
            binary_name = svc['binary']
            yield f"[discover] Finding {binary_name}...\n"
            import subprocess as _sp
            try:
                # Search common install locations
                result = _sp.run(
                    ['/bin/bash', '-c',
                     f'export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:/root/.local/bin:/root/.cargo/bin; '
                     f'which {binary_name} 2>/dev/null || find /usr /root /opt //.local -name "{binary_name}" -type f 2>/dev/null | head -1'],
                    capture_output=True, text=True, timeout=20
                )
                found = result.stdout.strip().split('\n')[0] if result.stdout.strip() else ''
                if found:
                    yield f"[discover] Found at: {found}\n"
                    db = self.installed_db()
                    if pid in db:
                        db[pid]['binary_path'] = found
                        self._save(db)
                else:
                    yield f"warning: {binary_name} not found in PATH — start may fail\n"
            except Exception as e:
                yield f"warning: binary discovery failed: {e}\n"

        # ── Post-install: OpenClaw config file ───────────────────────────────────
        # Write a complete, correct openclaw.json so the gateway starts properly
        # with no manual steps needed. All settings come from setup_fields values.
        if pid == 'openclaw':
            yield "[config] Writing openclaw.json...\n"
            saved_cfg = self.get_config(pid)

            gateway_port = int(saved_cfg.get('gateway_port', '18789'))
            gateway_bind = saved_cfg.get('gateway_bind', 'lan')
            gateway_mode = saved_cfg.get('gateway_mode', 'local')
            gateway_token = saved_cfg.get('gateway_token', 'ylstackos-openclaw-token')
            allow_insecure = bool(saved_cfg.get('allow_insecure_auth', True))

            model_provider = saved_cfg.get('model_provider', 'ollama')
            model_id = saved_cfg.get('model_id', 'llama3.1:8b')

            api_key = ''
            if model_provider == 'anthropic':
                api_key = saved_cfg.get('api_key', '')
            elif model_provider == 'openai':
                api_key = saved_cfg.get('api_key_openai', '')
            elif model_provider == 'openrouter':
                api_key = saved_cfg.get('api_key_openrouter', '')
            elif model_provider == 'google':
                api_key = saved_cfg.get('api_key_google', '')
            elif model_provider == 'deepseek':
                api_key = saved_cfg.get('api_key_deepseek', '')

            custom_base_url = saved_cfg.get('custom_base_url', '')
            telegram_bot_token = saved_cfg.get('telegram_bot_token', '')
            telegram_allow_from = saved_cfg.get('telegram_allow_from', '')
            discord_bot_token = saved_cfg.get('discord_bot_token', '')
            extra_allowed_origins = saved_cfg.get('extra_allowed_origins', '')

            # Build complete openclaw.json
            #   needed because we access via HTTP proxy (not HTTPS), browser blocks WebCrypto
            # - allowedOrigins: includes dashboard proxy origin so Control UI loads correctly
            # - models.pricing.enabled: false — skips OpenRouter/LiteLLM pricing fetch on ARM64 (~2-3s faster)
            # - skills: empty entries = minimal, no skills pre-enabled (user installs from Control UI)
            # - reload.hybrid: hot-reload where possible, restart only when required
            openclaw_config = {
                "gateway": {
                    "port": gateway_port,
                    "mode": gateway_mode,
                    "bind": gateway_bind,
                    "auth": {"mode": "token", "token": gateway_token},
                    "controlUi": {
                        "allowInsecureAuth": allow_insecure,
                        # Required for HTTP LAN access — browser blocks WebCrypto on plain HTTP
                        # Our /openclaw-proxy/ route provides same-origin context but WS still goes direct
                        "dangerouslyDisableDeviceAuth": allow_insecure,
                        "allowedOrigins": _build_allowed_origins(extra_allowed_origins)
                    },
                    # hybrid: hot-reload where possible, full restart only when required
                    # deferralTimeoutMs: max 2s wait for in-flight ops before forcing restart
                    "reload": {"mode": "hybrid", "debounceMs": 300, "deferralTimeoutMs": 2000}
                },
                "agents": {
                    "defaults": {
                        "workspace": "/root/.openclaw/workspace",
                        "model": {"primary": f"{model_provider}/{model_id}"},
                        # Agent timeout — prevent infinite waits on slow/unreliable models
                        "timeoutSeconds": 60,
                        # Context pruning — trim old tool results before each LLM call
                        # Prevents session files from growing huge (causes 10s+ sessions.list lag)
                        "contextPruning": {
                            "mode": "cache-ttl",
                            "ttl": "10m",
                            "keepLastAssistants": 2,
                            "minPrunableToolChars": 5000,
                            "softTrim": {"maxChars": 1500, "headChars": 500, "tailChars": 500},
                            "hardClear": {"enabled": True, "placeholder": "[cleared]"},
                        },
                        "compaction": {
                            "mode": "safeguard",
                            "reserveTokensFloor": 8000,
                        }
                    },
                    "list": [{"id": "main", "name": "Main", "default": True,
                              "workspace": "/root/.openclaw/workspace",
                              "agentDir": "/root/.openclaw/agents/main/agent"}]
                },
                "models": {
                    # pricing.enabled: false — skip OpenRouter/LiteLLM pricing bootstrap
                    # saves ~2-3s on ARM64 startup, not needed for local Ollama usage
                    "pricing": {"enabled": False},
                    "providers": {
                        model_provider: _openclaw_provider_config(model_provider, api_key, model_id, custom_base_url)
                    }
                },
                # skills: empty = minimal, no skills pre-enabled
                "skills": {"entries": {}},
                # plugins: only ollama enabled — disable acpx (ACP runtime bridge)
                # acpx loads heavy Node.js runtimes that block the event loop on ARM64
                # causing 12-14s event loop delays during chat
                "plugins": {
                    "entries": {
                        "ollama": {"enabled": True},
                        "acpx": {
                            "enabled": False,
                            "config": {"nonInteractivePermissions": "deny"}
                        },
                        "openai": {"enabled": False},
                    }
                },
                # ACP dispatch disabled — prevents automatic ACP agent spawning
                # ACP is CPU-intensive on ARM64 and causes event loop blocking
                "acp": {"dispatch": {"enabled": False}},
                # Sandbox off — not needed for personal use, saves resources
                "sandbox": {"mode": "off"},
                # Session reset daily at 4am — prevents session files from growing huge
                # Large session files cause sessions.list to take 10+ seconds
                "session": {"reset": {"mode": "daily", "atHour": 4}},
            }

            # Add channels only if tokens provided — don't add empty channel blocks
            channels = {}
            if telegram_bot_token:
                tg_entry = {"enabled": True, "botToken": telegram_bot_token}
                # allowFrom: list of Telegram user/chat IDs allowed to use the bot
                # Prevents unauthorized access when bot token is exposed
                if telegram_allow_from.strip():
                    allow_ids = [x.strip() for x in telegram_allow_from.split(',') if x.strip()]
                    # Convert to int where possible (Telegram IDs are integers)
                    parsed_ids = []
                    for id_str in allow_ids:
                        try:
                            parsed_ids.append(int(id_str))
                        except ValueError:
                            parsed_ids.append(id_str)  # keep as string (e.g. @username)
                    if parsed_ids:
                        tg_entry["allowFrom"] = parsed_ids
                channels["telegram"] = tg_entry
            if discord_bot_token:
                channels["discord"] = {"enabled": True, "botToken": discord_bot_token}
            if channels:
                openclaw_config["channels"] = channels

            config_path = Path('/root/.openclaw/openclaw.json')
            try:
                config_path.write_text(json.dumps(openclaw_config, indent=2))
                yield f"[config] Written to {config_path}\n"
            except Exception as e:
                yield f"warning: failed to write openclaw.json: {e}\n"

            # Run openclaw doctor --fix to validate config and fix any schema issues
            yield "[doctor] Running openclaw doctor --fix...\n"
            import subprocess as _sp
            try:
                result = _sp.run(
                    ['/bin/bash', '-c',
                     'export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin && '
                     'openclaw doctor --fix --non-interactive 2>&1 | tail -5'],
                    capture_output=True, text=True, timeout=30
                )
                if result.stdout.strip():
                    yield f"[doctor] {result.stdout.strip()}\n"
                yield "[doctor] Done\n"
            except Exception as e:
                yield f"[doctor] warning: {e}\n"

        # ── Post-install: FastClaw first-run init ─────────────────────────────
        # FastClaw has no config file — bootstrap is env-only.
        # On first run it creates ~/.fastclaw/fastclaw.db and prints the admin password.
        # We do a short daemon start → capture admin token → stop → record in installed.json.
        if pid == 'fastclaw':
            yield "[init] Running FastClaw first-run setup...\n"
            import subprocess as _sp
            saved_cfg = self.get_config(pid)
            fc_port = saved_cfg.get('gateway_port', '18953')
            fc_bind = saved_cfg.get('gateway_bind', 'all')
            fc_home = '/root/.fastclaw'
            try:
                # Start fastclaw briefly to initialise the DB and print the admin password
                result = _sp.run(
                    ['/bin/bash', '-c',
                     f'export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin; '
                     f'FASTCLAW_PORT={fc_port} FASTCLAW_BIND={fc_bind} FASTCLAW_HOME={fc_home} '
                     f'FASTCLAW_LOG_LEVEL=info '
                     f'timeout 8 fastclaw 2>&1 | head -30'],
                    capture_output=True, text=True, timeout=15
                )
                output = result.stdout.strip()
                if output:
                    yield f"[init] {output}\n"
                # Kill any lingering process on the port
                _sp.run(
                    ['/bin/bash', '-c',
                     f'/usr/bin/ss -tlnp | /bin/grep {fc_port} | '
                     f'/usr/bin/awk \'{{print $6}}\' | /usr/bin/awk -F= \'{{print $2}}\' | '
                     f'/usr/bin/xargs -r /bin/kill -9 2>/dev/null || true'],
                    timeout=5
                )
                yield "[init] FastClaw DB initialised. Use 'Start' to launch the gateway.\n"
                yield f"[init] Dashboard will be at http://<device-ip>:{fc_port}/\n"
            except Exception as e:
                yield f"[init] warning: first-run init failed: {e}\n"
                yield "[init] FastClaw is still installed — run 'Start' to launch.\n"

        db = self.installed_db()
        db[pid] = {**db.get(pid, {}), "version": m['version'], "installed_at": datetime.now().isoformat()}
        self._save(db)
        yield f"[✓] {m['name']} installed!\n"
        if m.get('dashboard', {}).get('route'):
            yield f"    Dashboard: {m['dashboard']['route']}\n"

    def remove_stream(self, pid: str) -> Iterator[str]:
        m = self.get(pid)
        if not m:
            yield f"error: Plugin '{pid}' not found\n"; return
        if not self.is_installed(pid):
            yield f"info: {m['name']} not installed\n"; return

        yield f"[*] Removing {m['name']}...\n"
        log = LOGS_DIR / f"plugin_{pid}_remove.log"
        _APT = "/usr/bin/apt-get"
        _BASH = "/bin/bash"

        if m.get('service', {}).get('stop'):
            yield "[svc] Stopping service...\n"
            os.system(f"{m['service']['stop']} >> {log} 2>&1")

        if m.get('remove_script', '').strip():
            yield "[sh] Running remove script...\n"
            os.system(f"{_BASH} -c '{m['remove_script']}' >> {log} 2>&1")

        if m.get('apt_packages'):
            pkgs = ' '.join(m['apt_packages'])
            yield f"[apt] Removing {pkgs}\n"
            os.system(f"{_APT} remove -y {pkgs} >> {log} 2>&1")
            os.system(f"{_APT} autoremove -y >> {log} 2>&1")

        for pkg in m.get('pip_packages', []):
            os.system(f"/usr/bin/pip3 uninstall -y {pkg} >> {log} 2>&1")

        db = self.installed_db()
        db.pop(pid, None)
        self._save(db)
        yield f"[✓] {m['name']} removed.\n"

    def start_service(self, pid: str) -> str:
        m = self.get(pid)
        if not m or not m.get('service'):
            return 'no service'
        log = LOGS_DIR / f"plugin_{pid}.log"
        svc = m['service']

        # Build the start command — prefer discovered binary_path over manifest start cmd
        db = self.installed_db()
        binary_path = db.get(pid, {}).get('binary_path', '')

        if binary_path and svc.get('binary'):
            binary_name = svc['binary']
            cmd = svc['start'].replace(binary_name, binary_path, 1)
        else:
            cmd = svc['start']

        # Substitute {{key}} placeholders from saved config
        # This allows config_fields (auth, port, password, etc.) to affect the start command
        saved_cfg = self.get_config(pid)
        for k, v in saved_cfg.items():
            cmd = cmd.replace('{{' + k + '}}', str(v))

        # Special: {{_password_flag}} — sets PASSWORD env var when auth=password
        # code-server does NOT accept --password as a CLI flag — must use $PASSWORD env var
        auth = saved_cfg.get('auth', 'none')
        password = saved_cfg.get('password', '')
        if '{{_password_flag}}' in cmd:
            cmd = cmd.replace('{{_password_flag}}', '')  # remove the placeholder, handled via env below

        # Build env string — include PASSWORD if auth=password
        env = "PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:/root/.local/bin:/root/.cargo/bin"
        if auth == 'password' and password:
            # Escape single quotes in password for shell safety
            safe_pwd = password.replace("'", "'\\''")
            env = f"PASSWORD='{safe_pwd}' {env}"
        os.system(f"/usr/bin/setsid /bin/bash -c 'export {env}; {cmd} >> {log} 2>&1' &")

        # OpenClaw installs bundled deps on first run (~60-90s on ARM64)
        # FastClaw is a Go binary — starts in ~2s. Other plugins start in 3s.
        # Poll up to 5s for normal plugins, 10s for openclaw, 5s for fastclaw.
        import time as _t
        wait = 10 if pid == 'openclaw' else 5 if pid == 'fastclaw' else 3
        _t.sleep(wait)
        status = 'running' if self.port_running(svc.get('check_port')) else 'started (check port)'
        return status

    def stop_service(self, pid: str) -> str:
        m = self.get(pid)
        if not m or not m.get('service'):
            return 'no service'

        port = m['service'].get('check_port')
        if port:
            import subprocess as _sp
            import re
            try:
                result = _sp.run(['/usr/bin/ss', '-tlnp'], capture_output=True, text=True, timeout=5)
                killed_pids = []
                for line in result.stdout.split('\n'):
                    if f':{port}' in line and 'pid=' in line:
                        match = re.search(r'pid=(\d+)', line)
                        if match:
                            kill_pid = match.group(1)
                            _sp.run(['/bin/kill', '-9', kill_pid], timeout=5)
                            killed_pids.append(kill_pid)
                log = LOGS_DIR / f"plugin_{pid}_stop.log"
                log.write_text(f"Killed PIDs: {killed_pids}\n")
            except Exception as e:
                log = LOGS_DIR / f"plugin_{pid}_stop.log"
                log.write_text(f"Error: {e}\n")
        else:
            cmd = m['service']['stop']
            os.system(f"/bin/bash -c '{cmd}'")
        return 'stopped'

    def hard_stop_service(self, pid: str) -> str:
        """Hard stop: kill by port AND kill any orphaned child processes.
        
        More aggressive than stop_service — kills all processes that inherited
        the port fd, not just the one currently listening. Fixes the issue where
        openclaw-gateway inherits Flask's fd and appears running but isn't reachable.
        """
        m = self.get(pid)
        if not m or not m.get('service'):
            return 'no service'

        port = m['service'].get('check_port')
        binary = m['service'].get('binary', '')
        import subprocess as _sp
        import re

        killed = []

        # Step 1: kill by port (primary listener)
        if port:
            try:
                result = _sp.run(['/usr/bin/ss', '-tlnp'], capture_output=True, text=True, timeout=5)
                for line in result.stdout.split('\n'):
                    if f':{port}' in line and 'pid=' in line:
                        match = re.search(r'pid=(\d+)', line)
                        if match:
                            _sp.run(['/bin/kill', '-9', match.group(1)], timeout=5)
                            killed.append(f'port:{match.group(1)}')
            except Exception:
                pass

        # Step 2: kill by binary name (catches orphaned processes)
        if binary:
            try:
                result = _sp.run(['/bin/ps', 'aux'], capture_output=True, text=True, timeout=5)
                for line in result.stdout.split('\n'):
                    if binary in line and 'grep' not in line:
                        parts = line.split()
                        if len(parts) > 1:
                            try:
                                _sp.run(['/bin/kill', '-9', parts[1]], timeout=5)
                                killed.append(f'binary:{parts[1]}')
                            except Exception:
                                pass
            except Exception:
                pass

        # Step 3: wait for port to be fully released
        import time as _t
        for _ in range(10):
            _t.sleep(0.5)
            try:
                result = _sp.run(['/usr/bin/ss', '-tlnp'], capture_output=True, text=True, timeout=3)
                if port and f':{port}' not in result.stdout:
                    break
            except Exception:
                break

        log = LOGS_DIR / f"plugin_{pid}_stop.log"
        log.write_text(f"Hard stop killed: {killed}\n")
        return 'stopped'

    def get_config(self, pid: str) -> dict:
        """Get saved config for a plugin (merges defaults with saved values)."""
        m = self.get(pid)
        defaults = dict(m.get('config', {})) if m else {}
        saved_file = PLUGINS_DIR / f"{pid}.config.json"
        if saved_file.exists():
            try:
                saved = json.loads(saved_file.read_text())
                defaults.update(saved)
            except Exception:
                pass
        return defaults

    def save_config(self, pid: str, config: dict, auto_restart: bool = True) -> str:
        """Save plugin config values. Optionally restart service if running.
        
        auto_restart=True  → restart immediately (default for most plugins)
        auto_restart=False → save only, no restart (use when making multiple changes)
        """
        saved_file = PLUGINS_DIR / f"{pid}.config.json"
        saved_file.write_text(json.dumps(config, indent=2))
        
        # Special handling for OpenClaw: also update openclaw.json
        if pid == 'openclaw':
            self._update_openclaw_config(config)
        
        if not auto_restart:
            return 'saved'

        # Auto-restart service if it was running (config changes need restart)
        m = self.get(pid)
        if m and m.get('service'):
            port = m['service'].get('check_port')
            if port and self.port_running(port):
                # Hard stop — kills by port AND binary name, waits for port release
                self.hard_stop_service(pid)
                self.start_service(pid)
                return 'saved and restarted'

        return 'saved'
    
    def _update_openclaw_config(self, saved_cfg: dict) -> str:
        """Update /root/.openclaw/openclaw.json from saved config."""
        config_path = Path('/root/.openclaw/openclaw.json')
        if not config_path.exists():
            return 'openclaw.json not found'
        
        try:
            # Read existing config
            existing = json.loads(config_path.read_text())
            
            # Gateway settings
            if 'gateway_port' in saved_cfg:
                existing.setdefault('gateway', {})['port'] = int(saved_cfg['gateway_port'])
            if 'gateway_bind' in saved_cfg:
                existing.setdefault('gateway', {})['bind'] = saved_cfg['gateway_bind']
            if 'gateway_mode' in saved_cfg:
                existing.setdefault('gateway', {})['mode'] = saved_cfg['gateway_mode']
            if 'gateway_token' in saved_cfg:
                existing.setdefault('gateway', {}).setdefault('auth', {})['token'] = saved_cfg['gateway_token']
            if 'allow_insecure_auth' in saved_cfg:
                existing.setdefault('gateway', {}).setdefault('controlUi', {})['allowInsecureAuth'] = bool(saved_cfg['allow_insecure_auth'])
                # dangerouslyDisableDeviceAuth is the actual flag that bypasses device identity checks
                # allowInsecureAuth alone does NOT bypass WebCrypto/device identity — only this flag does
                existing.setdefault('gateway', {}).setdefault('controlUi', {})['dangerouslyDisableDeviceAuth'] = bool(saved_cfg['allow_insecure_auth'])
            
            # Model settings
            model_provider = saved_cfg.get('model_provider', 'ollama')
            model_id = saved_cfg.get('model_id', 'llama3.1:8b')
            existing.setdefault('agents', {}).setdefault('defaults', {})['model'] = {"primary": f"{model_provider}/{model_id}"}

            # API key + custom base URL for provider
            api_key = ''
            if model_provider == 'anthropic':
                api_key = saved_cfg.get('api_key', '')
            elif model_provider == 'openai':
                api_key = saved_cfg.get('api_key_openai', '')
            elif model_provider == 'openrouter':
                api_key = saved_cfg.get('api_key_openrouter', '')
            elif model_provider == 'google':
                api_key = saved_cfg.get('api_key_google', '')
            elif model_provider == 'deepseek':
                api_key = saved_cfg.get('api_key_deepseek', '')
            custom_base_url = saved_cfg.get('custom_base_url', '')
            existing.setdefault('models', {}).setdefault('providers', {})[model_provider] = _openclaw_provider_config(model_provider, api_key, model_id, custom_base_url)
            
            # Channels
            channels = existing.get('channels', {})
            if saved_cfg.get('telegram_bot_token'):
                tg_entry = {"enabled": True, "botToken": saved_cfg['telegram_bot_token']}
                telegram_allow_from = saved_cfg.get('telegram_allow_from', '')
                if telegram_allow_from.strip():
                    allow_ids = [x.strip() for x in telegram_allow_from.split(',') if x.strip()]
                    parsed_ids = []
                    for id_str in allow_ids:
                        try:
                            parsed_ids.append(int(id_str))
                        except ValueError:
                            parsed_ids.append(id_str)
                    if parsed_ids:
                        tg_entry["allowFrom"] = parsed_ids
                channels["telegram"] = tg_entry
            if saved_cfg.get('discord_bot_token'):
                channels['discord'] = {"enabled": True, "botToken": saved_cfg['discord_bot_token']}
            if channels:
                existing['channels'] = channels

            # Preserve gateway.reload — always keep hybrid mode
            existing.setdefault('gateway', {}).setdefault('reload', {})
            if existing['gateway']['reload'].get('mode') not in ('hybrid', 'hot', 'off'):
                existing['gateway']['reload'] = {'mode': 'hybrid', 'debounceMs': 300, 'deferralTimeoutMs': 2000}

            # Preserve allowedOrigins — always include dashboard proxy origin + user extras
            extra_origins = saved_cfg.get('extra_allowed_origins', '')
            ctrl_ui = existing.setdefault('gateway', {}).setdefault('controlUi', {})
            ctrl_ui['allowedOrigins'] = _build_allowed_origins(extra_origins)

            # Preserve pricing disabled — skip OpenRouter/LiteLLM bootstrap on ARM64
            existing.setdefault('models', {}).setdefault('pricing', {})
            if existing['models']['pricing'].get('enabled') is not False:
                existing['models']['pricing']['enabled'] = False

            # Preserve skills.entries — never overwrite user's skill config from dashboard
            existing.setdefault('skills', {}).setdefault('entries', {})

            # Preserve plugins.entries — never overwrite user's plugin config from dashboard
            # But always ensure acpx is disabled (causes event loop blocking on ARM64)
            existing.setdefault('plugins', {}).setdefault('entries', {})
            existing['plugins']['entries'].setdefault('acpx', {
                'enabled': False,
                'config': {'nonInteractivePermissions': 'deny'}
            })
            existing['plugins']['entries'].setdefault('openai', {'enabled': False})

            # Preserve ACP dispatch disabled
            existing.setdefault('acp', {}).setdefault('dispatch', {})['enabled'] = False

            # Preserve sandbox off
            existing.setdefault('sandbox', {})['mode'] = 'off'

            # Preserve session reset policy
            existing.setdefault('session', {}).setdefault('reset', {'mode': 'daily', 'atHour': 4})

            config_path.write_text(json.dumps(existing, indent=2))
            return 'ok'
        except Exception as e:
            return f'error: {e}'

    def add_custom(self, url: str) -> str:
        """Fetch manifest.json from URL and register as custom plugin."""
        import urllib.request
        try:
            with urllib.request.urlopen(url, timeout=10) as r:
                data = json.loads(r.read())
            pid = data.get('id')
            if not pid:
                return 'error: manifest missing id'
            dest = CUSTOM_DIR / pid
            dest.mkdir(parents=True, exist_ok=True)
            (dest / 'manifest.json').write_text(json.dumps(data, indent=2))
            return f'ok: plugin {pid} added'
        except Exception as e:
            return f'error: {e}'


# ── Flask Blueprint ───────────────────────────────────────────────────────────

def get_blueprint():
    from flask import Blueprint, jsonify, request, Response, stream_with_context
    from flask_login import login_required, current_user
    from functools import wraps

    bp = Blueprint('plugins', __name__, url_prefix='/api/plugins')
    pm = PluginManager()

    def _get_token():
        try:
            return (PLUGINS_DIR.parent / 'files' / 'token' / 'token').read_text().strip()
        except Exception:
            return ''

    def plugin_auth(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            if current_user.is_authenticated:
                return f(*args, **kwargs)
            token = (request.headers.get('X-Token') or
                     request.headers.get('X-API-Token') or
                     request.args.get('token'))
            if not token:
                auth = request.headers.get('Authorization', '')
                if auth.startswith('Bearer '):
                    token = auth[7:]
            if token and token == _get_token():
                return f(*args, **kwargs)
            return jsonify({'error': 'Unauthorized', 'status': 401}), 401
        return decorated

    @bp.route('/installed')
    @plugin_auth
    def installed_plugins():
        """Lightweight endpoint — only installed plugins with service status."""
        installed = pm.installed_db()
        result = []
        for pid, info in installed.items():
            m = pm.get(pid)
            if not m:
                continue
            result.append({
                'id': pid,
                'name': m['name'],
                'category': m.get('category', 'tools'),
                'dashboard': m.get('dashboard'),
                'has_service': bool(m.get('service')),
                'service_status': pm.service_status(pid),
                'boot': info.get('boot', False),
            })
        return jsonify(result)

    @bp.route('/')
    @plugin_auth
    def list_plugins():
        return jsonify(pm.list_status())

    @bp.route('/<pid>')
    @plugin_auth
    def plugin_info(pid):
        m = pm.get(pid)
        if not m:
            return jsonify({'error': 'not found'}), 404
        db = pm.installed_db()
        return jsonify({**m,
                        'installed': pid in db,
                        'installed_at': db.get(pid, {}).get('installed_at'),
                        'service_status': pm.service_status(pid),
                        'has_service': bool(m.get('service')),
                        'existing': None if pid in db else pm.check_existing(pid)})

    @bp.route('/<pid>/existing', methods=['GET'])
    @plugin_auth
    def check_existing(pid):
        """Check if plugin has existing config/service before install."""
        if pm.is_installed(pid):
            return jsonify({'error': 'already installed'}), 400
        return jsonify(pm.check_existing(pid))

    @bp.route('/<pid>/backup', methods=['POST'])
    @plugin_auth
    def backup_config(pid):
        """Backup existing config before reinstall."""
        existing = pm.check_existing(pid)
        if not existing.get('has_config'):
            return jsonify({'result': 'no config to backup'})
        
        import shutil
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        backup_dir = PLUGINS_DIR / 'backups'
        backup_dir.mkdir(parents=True, exist_ok=True)
        
        backed_up = []
        
        # Backup plugin config
        config_file = PLUGINS_DIR / f"{pid}.config.json"
        if config_file.exists():
            backup_path = backup_dir / f"{pid}.config.{timestamp}.json"
            shutil.copy(config_file, backup_path)
            backed_up.append(str(backup_path))
        
        # Backup plugin-specific configs
        if pid == 'openclaw':
            openclaw_config = Path('/root/.openclaw/openclaw.json')
            if openclaw_config.exists():
                backup_path = backup_dir / f"openclaw.json.{timestamp}"
                shutil.copy(openclaw_config, backup_path)
                backed_up.append(str(backup_path))
        
        return jsonify({'result': 'ok', 'backed_up': backed_up, 'timestamp': timestamp})

    @bp.route('/<pid>/install', methods=['POST'])
    @plugin_auth
    def install(pid):
        def _gen():
            for line in pm.install_stream(pid):
                yield f"data: {json.dumps({'log': line})}\n\n"
            yield f"data: {json.dumps({'done': True})}\n\n"
        return Response(stream_with_context(_gen()), mimetype='text/event-stream',
                        headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})

    @bp.route('/<pid>/remove', methods=['POST'])
    @plugin_auth
    def remove(pid):
        def _gen():
            for line in pm.remove_stream(pid):
                yield f"data: {json.dumps({'log': line})}\n\n"
            yield f"data: {json.dumps({'done': True})}\n\n"
        return Response(stream_with_context(_gen()), mimetype='text/event-stream',
                        headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})

    @bp.route('/<pid>/start', methods=['POST'])
    @plugin_auth
    def start(pid):
        return jsonify({'status': pm.start_service(pid)})

    @bp.route('/<pid>/stop', methods=['POST'])
    @plugin_auth
    def stop(pid):
        return jsonify({'status': pm.stop_service(pid)})

    @bp.route('/<pid>/restart', methods=['POST'])
    @plugin_auth
    def restart(pid):
        """Restart a plugin service (stop then start)."""
        import time
        pm.stop_service(pid)
        time.sleep(1)
        return jsonify({'status': pm.start_service(pid)})

    @bp.route('/<pid>/hard-restart', methods=['POST'])
    @plugin_auth
    def hard_restart(pid):
        """Hard restart: kill by port AND binary name, wait for port release, then start.
        
        Use when normal restart leaves the service unreachable (fd inheritance issue).
        """
        pm.hard_stop_service(pid)
        return jsonify({'status': pm.start_service(pid)})

    @bp.route('/<pid>/boot', methods=['POST'])
    @plugin_auth
    def toggle_boot(pid):
        """Enable/disable auto-start on boot for a plugin service."""
        if not pm.is_installed(pid):
            return jsonify({'error': 'not installed'}), 400
        data = request.json or {}
        enable = bool(data.get('enable', True))
        db = pm.installed_db()
        if pid in db:
            db[pid]['boot'] = enable
            pm._save(db)
        return jsonify({'boot': enable})

    @bp.route('/<pid>/config', methods=['GET'])
    @plugin_auth
    def get_config(pid):
        m = pm.get(pid)
        if not m:
            return jsonify({'error': 'not found'}), 404
        return jsonify({
            'config': pm.get_config(pid),
            'config_fields': m.get('config_fields', []),
        })

    @bp.route('/<pid>/logs', methods=['GET'])
    @plugin_auth
    def get_logs(pid):
        """Read plugin log file for debugging service startup issues."""
        lines = request.args.get('lines', 100, type=int)
        
        # OpenClaw logs to /tmp/openclaw/openclaw-YYYY-MM-DD.log
        if pid == 'openclaw':
            from datetime import date
            today = date.today().isoformat()
            log_file = Path(f'/tmp/openclaw/openclaw-{today}.log')
            if not log_file.exists():
                # Fallback to the plugin log file
                log_file = LOGS_DIR / f"plugin_{pid}.log"
        else:
            log_file = LOGS_DIR / f"plugin_{pid}.log"
        
        if not log_file.exists():
            return jsonify({'error': 'no log file', 'path': str(log_file)}), 404
        
        try:
            # Read last N lines efficiently (tail -n)
            import subprocess as _sp
            result = _sp.run(
                ['/usr/bin/tail', '-n', str(lines), str(log_file)],
                capture_output=True, text=True, timeout=5
            )
            return jsonify({
                'log': result.stdout,
                'file': str(log_file),
                'lines': lines,
            })
        except Exception as e:
            return jsonify({'error': str(e)}), 500

    @bp.route('/<pid>/config', methods=['POST'])
    @plugin_auth
    def save_config(pid):
        data = request.json or {}
        # ?restart=true  → save + restart (explicit)
        # ?restart=false → save only, no restart
        # default: no restart (safer — user clicks Restart when ready)
        restart_param = request.args.get('restart', 'false').lower()
        auto_restart = restart_param == 'true'
        result = pm.save_config(pid, data, auto_restart=auto_restart)
        return jsonify({'result': result})

    @bp.route('/custom/add', methods=['POST'])
    @plugin_auth
    def add_custom():
        url = (request.json or {}).get('url', '')
        if not url:
            return jsonify({'error': 'url required'}), 400
        return jsonify({'result': pm.add_custom(url)})

    return bp


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    pm = PluginManager()
    p = argparse.ArgumentParser(prog='ylplugin')
    s = p.add_subparsers(dest='cmd')
    s.add_parser('list')
    s.add_parser('installed')
    pi = s.add_parser('info');    pi.add_argument('id')
    pi = s.add_parser('install'); pi.add_argument('id')
    pi = s.add_parser('remove');  pi.add_argument('id')
    pi = s.add_parser('start');   pi.add_argument('id')
    pi = s.add_parser('stop');    pi.add_argument('id')
    pi = s.add_parser('add');     pi.add_argument('url')
    args = p.parse_args()

    if args.cmd == 'list':
        db = pm.installed_db()
        print(f"\n  {'ID':<20} {'Name':<20} {'Cat':<10} {'Inst':<6} Description")
        print(f"  {'-'*20} {'-'*20} {'-'*10} {'-'*6} {'-'*35}")
        for pl in pm.list_status():
            inst = '✓' if pl['installed'] else ' '
            print(f"  {pl['id']:<20} {pl['name']:<20} {pl['category']:<10} {inst:<6} {pl['description'][:40]}")
        print()
    elif args.cmd == 'installed':
        for pid, info in pm.installed_db().items():
            m = pm.get(pid)
            status = pm.service_status(pid)
            print(f"  {pid:<20} {info.get('version','?'):<10} {status:<10} {m['name'] if m else '?'}")
    elif args.cmd == 'info':
        m = pm.get(args.id)
        if not m: print(f"Not found: {args.id}"); sys.exit(1)
        for k, v in m.items():
            if k not in ('install_script', 'remove_script'):
                print(f"  {k}: {v}")
    elif args.cmd == 'install':
        for line in pm.install_stream(args.id): print(line, end='')
    elif args.cmd == 'remove':
        for line in pm.remove_stream(args.id): print(line, end='')
    elif args.cmd == 'start':
        print(pm.start_service(args.id))
    elif args.cmd == 'stop':
        print(pm.stop_service(args.id))
    elif args.cmd == 'add':
        print(pm.add_custom(args.url))
    else:
        p.print_help()


if __name__ == '__main__':
    main()
