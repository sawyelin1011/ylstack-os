"""
YL StackOS Dashboard UI Blueprint
==================================

Serves the Vite-built React SPA from Flask at root (/).

Routes:
    /                   → static/dist/index.html  (React SPA entry)
    /assets/*           → static/dist/assets/*   (JS/CSS/fonts)
    /images/*           → static/dist/images/*
    /openclaw-proxy/*   → proxy to localhost:18789 (HTTP assets only)
                          WebSocket connects directly to ws://host:18789
    /*                  → static/dist/index.html  (SPA catch-all)
"""

from pathlib import Path
from flask import Blueprint, send_from_directory, redirect, request, Response
import urllib.request
import urllib.error

DIST = Path(__file__).parent.parent.parent / 'static' / 'dist'

dashboard_ui = Blueprint('dashboard_ui', __name__)

_OPENCLAW_UPSTREAM = 'http://127.0.0.1:18789'


# ── OpenClaw HTTP proxy ───────────────────────────────────────────────────────
# Strategy:
#   1. Browser opens /openclaw-proxy/ — same origin as dashboard (port 5000)
#      → WebCrypto API is available (secure context via same-origin trust)
#   2. The HTML is served with a <base> tag pointing to the real gateway
#      AND a meta-redirect / injected script that sets gatewayUrl in the hash
#      so OpenClaw JS connects WebSocket to ws://device:18789 directly
#   3. All asset requests (/assets/*, /favicon*, etc.) are proxied from localhost:18789

@dashboard_ui.route('/openclaw-proxy/', defaults={'path': ''})
@dashboard_ui.route('/openclaw-proxy/<path:path>', methods=['GET', 'POST', 'PUT', 'DELETE', 'PATCH', 'OPTIONS'])
def openclaw_proxy(path: str):
    """HTTP reverse proxy to OpenClaw gateway at localhost:18789.
    
    For the root HTML page, injects the real gateway URL into the hash
    so OpenClaw JS connects WebSocket to the correct host:port.
    """
    upstream_url = f'{_OPENCLAW_UPSTREAM}/{path}'
    if request.query_string:
        upstream_url += '?' + request.query_string.decode('utf-8')

    # Forward headers, rewrite Host
    headers = {}
    skip = {'host', 'content-length', 'transfer-encoding', 'connection'}
    for k, v in request.headers:
        if k.lower() not in skip:
            headers[k] = v
    headers['Host'] = '127.0.0.1:18789'
    headers['X-Forwarded-Host'] = request.host
    headers['X-Forwarded-Proto'] = 'http'

    try:
        req = urllib.request.Request(
            upstream_url,
            data=request.get_data() or None,
            headers=headers,
            method=request.method,
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            body = resp.read()
            content_type = resp.headers.get('Content-Type', '')

            # For the root HTML page: inject a script that sets gatewayUrl
            # OpenClaw JS reads gatewayUrl from URL hash (#gatewayUrl=ws://...)
            # This tells it to connect WebSocket to the real gateway port, not port 5000
            if 'text/html' in content_type and not path:
                device_host = request.host.split(':')[0]  # e.g. 192.168.1.188
                gateway_ws_url = f'ws://{device_host}:18789'
                inject = (
                    f'<script>'
                    f'(function(){{'
                    f'  var h = window.location.hash;'
                    f'  if (!h || h.indexOf("gatewayUrl") === -1) {{'
                    f'    window.location.hash = "gatewayUrl={gateway_ws_url}";'
                    f'  }}'
                    f'}})();'
                    f'</script>'
                ).encode()
                # Insert before </head>
                body = body.replace(b'</head>', inject + b'</head>', 1)

            # Forward response headers (skip hop-by-hop)
            excluded = {'transfer-encoding', 'connection', 'keep-alive', 'content-encoding'}
            response_headers = {
                k: v for k, v in resp.headers.items()
                if k.lower() not in excluded
            }
            return Response(body, status=resp.status, headers=response_headers)
    except urllib.error.HTTPError as e:
        return Response(e.read(), status=e.code, content_type='application/json')
    except Exception as e:
        return Response(f'{{"error": "proxy error: {e}"}}', status=502, content_type='application/json')


# ── SPA entry ─────────────────────────────────────────────────────────────────

@dashboard_ui.route('/')
def ui_index():
    """Serve the React SPA root."""
    return send_from_directory(DIST, 'index.html')


# ── Vite assets (JS/CSS/images/fonts) ────────────────────────────────────────

@dashboard_ui.route('/assets/<path:filename>')
def ui_assets(filename: str):
    return send_from_directory(DIST / 'assets', filename)


@dashboard_ui.route('/images/<path:filename>')
def ui_images(filename: str):
    return send_from_directory(DIST / 'images', filename)


@dashboard_ui.route('/manifest.webmanifest')
def ui_manifest():
    return send_from_directory(DIST, 'manifest.webmanifest')


# ── Legacy /ui/* redirects — keep old bookmarks working ──────────────────────

@dashboard_ui.route('/ui/')
@dashboard_ui.route('/ui')
def ui_legacy_redirect():
    return redirect('/')


@dashboard_ui.route('/ui/<path:path>')
def ui_legacy_path_redirect(path: str):
    return redirect(f'/{path}')


# ── SPA catch-all — client-side routes ───────────────────────────────────────
# TanStack Router handles /sign-in, /settings, /containers, /monitoring etc.
# Any path that isn't a real file or Flask route returns index.html.

@dashboard_ui.route('/<path:path>')
def ui_catchall(path: str):
    # Serve real files (favicon, robots.txt, etc.)
    target = DIST / path
    if target.is_file():
        return send_from_directory(DIST, path)
    # Everything else → SPA
    return send_from_directory(DIST, 'index.html')
