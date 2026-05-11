"""
YL StackOS — Flask entry point
================================

Wraps the original main.py, registers YL StackOS blueprints,
then runs the app. This replaces calling main.py directly.

Blueprints registered:
  - dashboard_ui   → serves Vite-built React SPA at /ui/
  - api_v1         → JSON API at /api/v1/
  - api_plugins    → plugin management at /api/plugins/

The original main.py routes are untouched and still work:
  /auth/login, /dashboard/home/view, /api/system/cmd, etc.
"""

import sys
import os

# Ensure /ylstackos is on the path so main.py imports work
sys.path.insert(0, '/ylstackos')

# ── Read Android device props at startup (from Android side via /proc/cmdline etc) ──
# getprop is not available inside chroot, so we read from files Android exposes.
# These are written by the Android init system and accessible from chroot.

def _read_android_props() -> dict:
    """Read Android device properties — cache file written by start.py on Android side."""
    props = {}

    # Method 1: Cache file written by start.py via getprop (most accurate)
    for cache_path in ['/ylstackos/files/android_props.json', '/flyos/files/android_props.json']:
        try:
            import json
            props.update(json.load(open(cache_path)))
            break
        except Exception:
            pass

    # Method 2: build.prop files (fallback — may have generic values)
    for path in ['/system/build.prop', '/vendor/build.prop',
                 '/product/build.prop', '/odm/build.prop']:
        try:
            for line in open(path):
                line = line.strip()
                if '=' in line and not line.startswith('#'):
                    k, _, v = line.partition('=')
                    k = k.strip()
                    if k not in props:  # don't overwrite cache values
                        props[k] = v.strip()
        except Exception:
            pass

    # Method 3: /proc/cmdline for serial number
    try:
        cmdline = open('/proc/cmdline').read()
        for part in cmdline.split():
            if '=' in part:
                k, _, v = part.partition('=')
                if 'serial' in k.lower() and '_serialno' not in props:
                    props['_serialno'] = v.strip()
    except Exception:
        pass

    # Method 4: USB serial
    try:
        s = open('/sys/class/android_usb/android0/iSerial').read().strip()
        if s and '_serialno' not in props:
            props['_serialno'] = s
    except Exception:
        pass

    return props

_ANDROID_PROPS = _read_android_props()

# Import the Flask app from original main.py
from main import app, login_manager

# ── Persistent secret key — MUST be set immediately after import ─────────────
# main.py sets app.secret_key = os.urandom(24) which changes on every restart.
# We override it here with a file-backed key so sessions survive restarts.
import secrets as _sec

_key_file = '/ylstackos/files/secret_key'
try:
    if os.path.exists(_key_file):
        app.secret_key = open(_key_file, 'rb').read()
    else:
        _new_key = _sec.token_bytes(32)
        os.makedirs(os.path.dirname(_key_file), exist_ok=True)
        open(_key_file, 'wb').write(_new_key)
        app.secret_key = _new_key
except Exception:
    pass  # keep the random key from main.py as last resort

# ── Session config — ensure cookie works across page navigations ──────────────
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'   # allows same-site navigation
app.config['SESSION_COOKIE_SECURE'] = False       # HTTP (not HTTPS)
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_PATH'] = '/'           # cookie valid for all paths

# ── Fix login_manager — return 401 for API/AJAX, redirect for browser ────────
# Original main.py sets login_manager.login_view = 'login' which redirects
# to /auth/login (old HTML page). We override the unauthorized handler so:
#   - API/AJAX requests (Accept: application/json or /api/* paths) → 401 JSON
#   - Browser requests to /dashboard/* → redirect to /ui/sign-in (our React UI)

from flask import request, redirect, jsonify
from flask_login import login_required
from functools import wraps

@login_manager.unauthorized_handler
def unauthorized():
    # API requests — return 401 JSON (React app handles this)
    if (request.path.startswith('/api/') or
        'application/json' in request.headers.get('Accept', '') or
        request.headers.get('X-Requested-With') == 'XMLHttpRequest'):
        return jsonify({'error': 'Unauthorized', 'status': 401}), 401
    # Browser navigating to a protected page → send to React sign-in
    return redirect(f'/sign-in?redirect={request.path}')

# ── Register YL StackOS blueprints ───────────────────────────────────────────

from app.blueprints.dashboard_ui import dashboard_ui
from app.blueprints.api_plugins import api_plugins

app.register_blueprint(dashboard_ui)
app.register_blueprint(api_plugins)

# Override main.py's / route — it redirects to /ui/ which no longer exists.
# Our dashboard_ui blueprint serves the SPA at / but main.py registered first.
# Remove the old route and let the blueprint handle it.
try:
    app.view_functions.pop('redirectmain', None)
    # Remove the rule from url_map
    rules_to_remove = [r for r in app.url_map._rules if r.rule == '/' and r.endpoint == 'redirectmain']
    for r in rules_to_remove:
        app.url_map._rules.remove(r)
        app.url_map._rules_by_endpoint.get('redirectmain', []).clear()
except Exception:
    pass

try:
    from app.blueprints.api_v1 import api_v1
    app.register_blueprint(api_v1)
except Exception as e:
    print(f"[ylstackos] api_v1 not loaded: {e}")

# ── Setup status API ──────────────────────────────────────────────────────────
# Used by the React frontend to detect first-run setup.

from flask import jsonify, request as flask_request
from werkzeug.security import generate_password_hash
import secrets, string

# Detect base path (supports both /flyos and /ylstackos)
_BASE = '/ylstackos' if os.path.exists('/ylstackos/files') else '/flyos'

@app.route('/api/setup/status')
def api_setup_status():
    """Check if first-run setup has been completed."""
    done = os.path.exists(f'{_BASE}/files/setup/setup_lock')
    return jsonify({'setup_done': done})


@app.route('/api/me')
def api_me():
    """Check if current session is authenticated. Returns 200 or 401."""
    from flask_login import current_user
    if current_user.is_authenticated:
        return jsonify({'authenticated': True, 'user_id': current_user.id})
    return jsonify({'authenticated': False}), 401


@app.route('/api/metrics')
@login_required
def api_metrics():
    """Return system metrics as JSON — no HTML scraping needed."""
    try:
        from tools import (
            get_device_storage, battery_status, get_available_ram,
            get_cpu_usage, check_vnc_process,
            check_codeserver_process, ylstack_framework_status,
            get_local_ip, get_kernel_version
        )

        def _read(path, default=''):
            try: return open(path).read().strip()
            except: return default

        # Android version from build.prop
        android_ver = _ANDROID_PROPS.get('ro.build.version.release', '')
        sdk_ver = _ANDROID_PROPS.get('ro.build.version.sdk', '')

        # Model/manufacturer — try multiple keys (vendor partition has real values)
        model = (
            _ANDROID_PROPS.get('ro.product.vendor.model') or
            _ANDROID_PROPS.get('ro.product.odm.model') or
            _ANDROID_PROPS.get('ro.product.model') or
            _ANDROID_PROPS.get('ro.product.system.model') or ''
        )
        manufacturer = (
            _ANDROID_PROPS.get('ro.product.vendor.manufacturer') or
            _ANDROID_PROPS.get('ro.product.odm.manufacturer') or
            _ANDROID_PROPS.get('ro.product.manufacturer') or
            _ANDROID_PROPS.get('ro.product.system.manufacturer') or ''
        )

        # Serial number / Android ID
        android_id = (
            _ANDROID_PROPS.get('_serialno') or
            _ANDROID_PROPS.get('ro.serialno') or
            _ANDROID_PROPS.get('ro.boot.serialno') or
            _read('/sys/class/android_usb/android0/iSerial') or ''
        )

        # If model still empty, try to get from overview HTML cache
        if not model:
            try:
                import re
                html = open('/ylstackos/logs/_overview_cache.html').read()
                m = re.search(r'Device Model</td>\s*<td>([^<]+)</td>', html)
                if m: model = m.group(1).strip()
                m2 = re.search(r'Device Manufacturer</td>\s*<td>([^<]+)</td>', html)
                if m2: manufacturer = m2.group(1).strip()
            except Exception:
                pass

        return jsonify({
            'storage_gb': get_device_storage(),
            'battery': battery_status(),
            'ram_available': get_available_ram(),
            'cpu_percent': get_cpu_usage(),
            'vnc': check_vnc_process(),
            'code_server': check_codeserver_process(),
            'framework': 'Running' if ylstack_framework_status() else 'Stopped',
            'ip': get_local_ip(),
            'kernel': get_kernel_version(),
            'hostname': _read('/etc/hostname', 'ylstackos'),
            'android_version': android_ver,
            'sdk_version': sdk_ver,
            'model': model,
            'manufacturer': manufacturer,
            'android_id': android_id,
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/setup/complete', methods=['POST'])
def api_setup_complete():
    """
    Complete first-run setup from the React UI.
    Body: { "dashboard_password": "...", "root_password": "..." }
    Sets passwords, generates token, creates setup_lock.
    """
    # Already done
    if os.path.exists(f'{_BASE}/files/setup/setup_lock'):
        return jsonify({'error': 'Setup already completed'}), 400

    data = flask_request.get_json(silent=True) or {}
    dashboard_pwd = data.get('dashboard_password', '').strip()
    root_pwd = data.get('root_password', '').strip()

    if not dashboard_pwd:
        return jsonify({'error': 'Dashboard password is required'}), 400

    # Set dashboard password
    try:
        pwd_file = f'{_BASE}/files/pwd.conf'
        os.makedirs(os.path.dirname(pwd_file), exist_ok=True)
        with open(pwd_file, 'w') as f:
            f.write(generate_password_hash(dashboard_pwd))
    except Exception as e:
        return jsonify({'error': f'Failed to set dashboard password: {e}'}), 500

    # Set root password if provided
    if root_pwd:
        os.system(f'echo root:{root_pwd} | chpasswd 2>/dev/null')

    # Generate API token
    token = ''.join(secrets.choice(string.ascii_letters + string.digits) for _ in range(20))
    try:
        token_file = f'{_BASE}/files/token/token'
        os.makedirs(os.path.dirname(token_file), exist_ok=True)
        with open(token_file, 'w') as f:
            f.write(token)
    except Exception as e:
        return jsonify({'error': f'Failed to generate token: {e}'}), 500

    # Create setup lock
    try:
        lock = f'{_BASE}/files/setup/setup_lock'
        os.makedirs(os.path.dirname(lock), exist_ok=True)
        open(lock, 'w').close()
    except Exception as e:
        return jsonify({'error': f'Failed to create setup lock: {e}'}), 500

    return jsonify({'success': True, 'message': 'Setup complete. Please log in.'})


# ── Redirect / and /dashboard to the new UI ──────────────────────────────────

@app.before_request
def _redirect_to_new_ui():
    if request.method != 'GET':
        return  # never redirect POST/PUT/DELETE
    path = request.path
    # Old HTML login page → React sign-in (browser navigation only)
    if path == '/auth/login':
        return redirect('/sign-in')
    # Old setup pages → React setup
    if path.startswith('/setup/') and path != '/setup/login':
        return redirect('/setup')
    # Old /dashboard route → root
    if path == '/dashboard':
        qs = f'?{request.query_string.decode()}' if request.query_string else ''
        return redirect(f'/{qs}')

# ── Auto-start services (SSH, VNC, terminals) ────────────────────────────────
# Run start.py to start all services when Flask starts
# This ensures SSH, VNC, terminals auto-start on boot or restart

def _start_services():
    """Run start.py to start all services (SSH, VNC, terminals, etc.)"""
    try:
        import subprocess
        import threading
        
        def _run_start_py():
            try:
                # Run start.py in background
                subprocess.Popen(
                    ['/usr/bin/python3', '/ylstackos/start.py'],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    start_new_session=True
                )
            except Exception as e:
                print(f"[ylstackos] Warning: Could not start services: {e}")
        
        # Run in separate thread so Flask can start immediately
        thread = threading.Thread(target=_run_start_py, daemon=True)
        thread.start()
        print("[ylstackos] Services auto-start initiated (SSH, VNC, terminals)")
    except Exception as e:
        print(f"[ylstackos] Warning: Service auto-start failed: {e}")

# ── Run ───────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    from config import dashboard_host_addr, server_port
    
    # Start services before Flask starts
    _start_services()

    app.run(
        host=dashboard_host_addr,
        port=server_port,
        debug=False,
        use_reloader=False,
        threaded=True,   # needed for proxy routes and concurrent requests
    )
