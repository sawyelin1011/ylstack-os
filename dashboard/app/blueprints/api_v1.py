"""
YL StackOS — API v1 Blueprint
Optimized for low-end Android devices:
  - CPU metric uses non-blocking interval=0 (reads cached kernel value)
  - Services use port checks (no psutil process scan)
  - Device info reads from file cache (no subprocess/adb calls)
  - Services cache result for 3s to reduce port-check overhead
  - Storage/battery read from /proc and /sys directly (no subprocess)
  - Supports both Flask session cookie AND X-Token header auth
"""
import os
import socket
import time
from functools import wraps
from flask import Blueprint, jsonify, request
from flask_login import login_required, current_user
from app.utils.network import get_local_ip

api_v1 = Blueprint('api_v1', __name__, url_prefix='/api/v1')

# ── Simple in-memory cache (avoids repeated expensive calls) ──────────────────
_cache: dict = {}

def _cached(key: str, ttl: float, fn):
    """Return cached value if fresh, else call fn() and cache result."""
    now = time.monotonic()
    if key in _cache and now - _cache[key][0] < ttl:
        return _cache[key][1]
    val = fn()
    _cache[key] = (now, val)
    return val


def _get_token_from_file() -> str:
    """Read the API token from the token file."""
    try:
        from pathlib import Path
        _BASE = Path('/ylstackos') if Path('/ylstackos').exists() else Path('/flyos')
        return (_BASE / 'files' / 'token' / 'token').read_text().strip()
    except Exception:
        return ''


def api_auth_required(f):
    """Allow access via Flask session cookie OR X-Token / Authorization header."""
    @wraps(f)
    def decorated(*args, **kwargs):
        # 1. Flask session (browser login)
        if current_user.is_authenticated:
            return f(*args, **kwargs)
        # 2. X-Token header
        token = (request.headers.get('X-Token') or
                 request.headers.get('X-API-Token') or
                 request.args.get('token'))
        if token:
            valid = _get_token_from_file()
            if valid and token == valid:
                return f(*args, **kwargs)
        # 3. Authorization: Bearer <token>
        auth = request.headers.get('Authorization', '')
        if auth.startswith('Bearer '):
            token = auth[7:]
            valid = _get_token_from_file()
            if valid and token == valid:
                return f(*args, **kwargs)
        return jsonify({'error': 'Unauthorized', 'status': 401}), 401
    return decorated


# ── Session check ─────────────────────────────────────────────────────────────

@api_v1.route('/me')
@api_auth_required
def me():
    return jsonify({'authenticated': True})


# ── App config ────────────────────────────────────────────────────────────────

@api_v1.route('/config')
@api_auth_required
def config():
    from config import (
        server_port, terminal_port, vnc_port, code_server_port,
        file_browser_port, android_terminal_port, userspace_ttyd_port,
        server_ip_get_method
    )
    if server_ip_get_method == 'url_root':
        hostname = request.url_root.split('//', 1)[-1].split(':')[0]
    elif server_ip_get_method == 'host_spilt':
        hostname = request.host.split(':')[0]
    else:
        hostname = get_local_ip()

    return jsonify({
        'terminal_port':        terminal_port,
        'vnc_port':             vnc_port,
        'code_server_port':     code_server_port,
        'file_browser_port':    file_browser_port,
        'android_terminal_port': android_terminal_port,
        'userspace_ttyd_port':  userspace_ttyd_port,
        'hostname':             hostname,
    })


# ── System metrics ────────────────────────────────────────────────────────────

@api_v1.route('/metrics')
@api_auth_required
def metrics():
    import psutil

    # interval=0 reads the cached kernel CPU counter — no blocking wait
    # Accurate enough for a dashboard; saves 500ms per request on slow devices
    cpu_percent = psutil.cpu_percent(interval=0)

    mem = psutil.virtual_memory()
    ram_available = f"{mem.available / (1024**3):.1f} GB"

    try:
        storage_gb = round(psutil.disk_usage('/').free / (1024**3), 1)
    except Exception:
        storage_gb = 0.0

    return jsonify({
        'cpu_percent':  cpu_percent,
        'ram_available': ram_available,
        'storage_gb':   storage_gb,
        'battery':      _get_battery(),
    })


# ── Service statuses ──────────────────────────────────────────────────────────

@api_v1.route('/services')
@api_auth_required
def services():
    """Port-based checks — includes base services + installed plugins with service ports."""
    from config import terminal_port, vnc_port

    def _check():
        # Base services — always present (not plugin-managed)
        result = {
            'framework': 'Running',
            'ssh':       _check_port(2222),
            'ttyd':      _check_port(terminal_port),
        }
        # VNC only if vncserver port is open (may not be installed)
        vnc_status = _check_port(5900)
        if vnc_status == 'Running':
            result['vnc'] = vnc_status

        # Plugin-managed services — only show if installed
        try:
            import json, sys
            from pathlib import Path
            _BASE = Path('/ylstackos') if Path('/ylstackos').exists() else Path('/flyos')
            installed_file = _BASE / 'plugins' / 'installed.json'
            if installed_file.exists():
                installed = json.loads(installed_file.read_text())
                sys.path.insert(0, str(_BASE))
                from plugins.plugin_manager import CATALOG
                # Canonical name map — avoid duplicates
                CANONICAL = {'filebrowser': 'file_browser', 'code-server': 'code_server'}
                seen = set()
                for pid in installed:
                    canonical = CANONICAL.get(pid, pid)
                    if canonical in seen:
                        continue
                    seen.add(canonical)
                    m = CATALOG.get(pid)
                    if m and m.get('service') and m['service'].get('check_port'):
                        result[canonical] = _check_port(m['service']['check_port'])
        except Exception:
            pass
        return result

    return jsonify(_cached('services', 3.0, _check))


# ── Device info ───────────────────────────────────────────────────────────────

@api_v1.route('/device')
@api_auth_required
def device():
    """Read from cached file — no subprocess, no adb, cached 60s."""
    def _load():
        import json
        props = {}
        for path in ['/ylstackos/files/android_props.json', '/flyos/files/android_props.json']:
            try:
                props = json.load(open(path))
                break
            except Exception:
                pass
        if not props:
            for path in ['/system/build.prop', '/vendor/build.prop']:
                try:
                    for line in open(path):
                        line = line.strip()
                        if '=' in line and not line.startswith('#'):
                            k, _, v = line.partition('=')
                            props[k.strip()] = v.strip()
                except Exception:
                    pass

        def _read(p, d=''):
            try: return open(p).read().strip()
            except: return d

        return {
            'android_version': props.get('ro.build.version.release', ''),
            'sdk_version':     props.get('ro.build.version.sdk', ''),
            'model':           (props.get('ro.product.vendor.model') or props.get('ro.product.model', '')),
            'manufacturer':    (props.get('ro.product.vendor.manufacturer') or props.get('ro.product.manufacturer', '')),
            'android_id':      (props.get('_serialno') or props.get('ro.serialno') or props.get('ro.boot.serialno', '')),
            'kernel':          _read('/proc/version'),
            'hostname':        _read('/etc/hostname', 'ylstackos'),
        }

    return jsonify(_cached('device', 60.0, _load))


# ── Containers ────────────────────────────────────────────────────────────────

@api_v1.route('/containers')
@api_auth_required
def containers():
    container_dir = '/container/list'
    result = []
    try:
        for name in os.listdir(container_dir):
            path = os.path.join(container_dir, name)
            if os.path.isdir(path):
                mtime = os.path.getmtime(path)
                result.append({
                    'name': name,
                    'created_at': time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(mtime))
                })
    except FileNotFoundError:
        pass
    return jsonify(result)


# ── Capabilities ─────────────────────────────────────────────────────────────

@api_v1.route('/capabilities')
@api_auth_required
def capabilities():
    from app.services import capability_probe
    return jsonify(_cached('capabilities', 30.0, capability_probe.probe))


# ── Notice ────────────────────────────────────────────────────────────────────

@api_v1.route('/notice')
@api_auth_required
def notice():
    import requests as req
    from sysconf import sys_update_check_server
    url = sys_update_check_server.replace('latest_ver', 'notice')
    try:
        r = req.get(url, timeout=3)
        r.raise_for_status()
        return jsonify({'content': r.text})
    except Exception as e:
        return jsonify({'content': '', 'error': str(e)}), 200


# ── Helpers ───────────────────────────────────────────────────────────────────

def _get_battery() -> str:
    try:
        cap = open('/sys/class/power_supply/battery/capacity').read().strip()
        sta = open('/sys/class/power_supply/battery/status').read().strip()
        return f"{cap}% {sta}"
    except Exception:
        return 'Unknown'


def _check_port(port: int) -> str:
    """Non-blocking TCP port check. Timeout 0.3s — fast on LAN."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(0.3)
        result = s.connect_ex(('127.0.0.1', port))
        s.close()
        return 'Running' if result == 0 else 'Stopped'
    except Exception:
        return 'Stopped'


# ── Backup & Restore ──────────────────────────────────────────────────────────

import tarfile
import glob
import re
from datetime import datetime
from pathlib import Path as _Path
from flask import send_file

_BASE_PATH = _Path('/ylstackos') if _Path('/ylstackos').exists() else _Path('/flyos')
_BACKUP_DIR = _BASE_PATH / 'backups'

# Files/dirs included in every backup — relative to _BASE_PATH
_BACKUP_ITEMS = [
    'files/pwd.conf',
    'files/token/token',
    'files/secret_key',
    'files/setup',
    'files/android_props.json',
    'plugins/installed.json',
    'config.py',
    'sysconf.py',
]
# Glob patterns for plugin configs
_PLUGIN_CONFIG_GLOB = 'plugins/*.config.json'
# Optional extras (backed up if they exist)
_OPTIONAL_ITEMS = [
    '../ylstackosext/filebrowser/filebrowser.db',
]


def _ensure_backup_dir():
    _BACKUP_DIR.mkdir(parents=True, exist_ok=True)


def _list_backups() -> list[dict]:
    """Return list of backup files sorted newest first."""
    _ensure_backup_dir()
    backups = []
    for f in sorted(_BACKUP_DIR.glob('*.tar.gz'), reverse=True):
        stat = f.stat()
        backups.append({
            'filename': f.name,
            'size_bytes': stat.st_size,
            'size_human': _human_size(stat.st_size),
            'created_at': datetime.fromtimestamp(stat.st_mtime).isoformat(),
        })
    return backups


def _human_size(b: int) -> str:
    for unit in ['B', 'KB', 'MB', 'GB']:
        if b < 1024:
            return f'{b:.1f} {unit}'
        b /= 1024
    return f'{b:.1f} GB'


def _safe_filename(prefix: str) -> str:
    """Sanitize prefix — alphanumeric, dash, underscore only."""
    clean = re.sub(r'[^a-zA-Z0-9_-]', '_', prefix.strip())[:32]
    return clean or 'ylstackos'


@api_v1.route('/backup/list')
@api_auth_required
def backup_list():
    """List all backup files."""
    return jsonify(_list_backups())


@api_v1.route('/backup/create', methods=['POST'])
@api_auth_required
def backup_create():
    """
    Create a new backup tarball.
    Body: { "prefix": "optional-prefix" }
    Returns: { filename, size_human, created_at }
    """
    data = request.get_json(silent=True) or {}
    prefix = _safe_filename(data.get('prefix', 'ylstackos'))
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    filename = f'{prefix}_{ts}.tar.gz'
    _ensure_backup_dir()
    out_path = _BACKUP_DIR / filename

    try:
        with tarfile.open(out_path, 'w:gz') as tar:
            # Add fixed items
            for item in _BACKUP_ITEMS:
                p = _BASE_PATH / item
                if p.exists():
                    tar.add(str(p), arcname=item)

            # Add plugin configs (glob)
            for p in _BASE_PATH.glob(_PLUGIN_CONFIG_GLOB):
                arcname = str(p.relative_to(_BASE_PATH))
                tar.add(str(p), arcname=arcname)

            # Add optional items
            for item in _OPTIONAL_ITEMS:
                p = (_BASE_PATH / item).resolve()
                if p.exists():
                    tar.add(str(p), arcname=f'extras/{p.name}')

            # Add backup manifest
            import json as _json
            manifest = {
                'created_at': datetime.now().isoformat(),
                'prefix': prefix,
                'base_path': str(_BASE_PATH),
                'version': '1',
            }
            import io as _io
            manifest_bytes = _json.dumps(manifest, indent=2).encode()
            info = tarfile.TarInfo(name='backup_manifest.json')
            info.size = len(manifest_bytes)
            tar.addfile(info, _io.BytesIO(manifest_bytes))

        stat = out_path.stat()
        return jsonify({
            'filename': filename,
            'size_bytes': stat.st_size,
            'size_human': _human_size(stat.st_size),
            'created_at': datetime.fromtimestamp(stat.st_mtime).isoformat(),
        })
    except Exception as e:
        if out_path.exists():
            out_path.unlink()
        return jsonify({'error': str(e)}), 500


@api_v1.route('/backup/download/<filename>')
@api_auth_required
def backup_download(filename: str):
    """Download a backup file."""
    # Sanitize — no path traversal
    if '/' in filename or '..' in filename or not filename.endswith('.tar.gz'):
        return jsonify({'error': 'Invalid filename'}), 400
    path = _BACKUP_DIR / filename
    if not path.exists():
        return jsonify({'error': 'Not found'}), 404
    return send_file(str(path), as_attachment=True, download_name=filename)


@api_v1.route('/backup/delete/<filename>', methods=['DELETE'])
@api_auth_required
def backup_delete(filename: str):
    """Delete a backup file."""
    if '/' in filename or '..' in filename or not filename.endswith('.tar.gz'):
        return jsonify({'error': 'Invalid filename'}), 400
    path = _BACKUP_DIR / filename
    if not path.exists():
        return jsonify({'error': 'Not found'}), 404
    path.unlink()
    return jsonify({'ok': True})


@api_v1.route('/backup/restore', methods=['POST'])
@api_auth_required
def backup_restore():
    """
    Restore from an uploaded .tar.gz file OR from a stored backup by filename.
    Multipart: file field 'backup'
    JSON: { "filename": "stored-backup.tar.gz" }
    Returns: { restored: [...], skipped: [...], warnings: [...] }
    """
    import io as _io
    import json as _json

    restored = []
    skipped = []
    warnings = []

    # Determine source
    if 'backup' in request.files:
        f = request.files['backup']
        if not f.filename or not f.filename.endswith('.tar.gz'):
            return jsonify({'error': 'Must be a .tar.gz file'}), 400
        buf = _io.BytesIO(f.read())
    else:
        data = request.get_json(silent=True) or {}
        fname = data.get('filename', '')
        if '/' in fname or '..' in fname or not fname.endswith('.tar.gz'):
            return jsonify({'error': 'Invalid filename'}), 400
        path = _BACKUP_DIR / fname
        if not path.exists():
            return jsonify({'error': 'Backup not found'}), 404
        buf = _io.BytesIO(path.read_bytes())

    try:
        with tarfile.open(fileobj=buf, mode='r:gz') as tar:
            members = tar.getnames()

            # Read manifest if present
            manifest = {}
            if 'backup_manifest.json' in members:
                try:
                    mf = tar.extractfile('backup_manifest.json')
                    if mf:
                        manifest = _json.loads(mf.read())
                except Exception:
                    pass

            # Restore each item
            for member in tar.getmembers():
                name = member.name
                if name == 'backup_manifest.json':
                    continue

                # Determine destination
                if name.startswith('extras/'):
                    # Optional extras — restore to ylstackosext
                    dest = _Path('/ylstackosext') / name[7:]
                else:
                    dest = _BASE_PATH / name

                try:
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    fobj = tar.extractfile(member)
                    if fobj is None:
                        # Directory entry
                        dest.mkdir(parents=True, exist_ok=True)
                        restored.append(name)
                        continue
                    dest.write_bytes(fobj.read())
                    restored.append(name)
                except Exception as e:
                    warnings.append(f'{name}: {e}')
                    skipped.append(name)

        return jsonify({
            'ok': True,
            'restored': restored,
            'skipped': skipped,
            'warnings': warnings,
            'manifest': manifest,
            'message': f'Restored {len(restored)} items. Restart Flask to apply changes.',
        })
    except Exception as e:
        return jsonify({'error': f'Failed to read backup: {e}'}), 500


# Fix typo in restore — _PATH should be _Path
# (already defined above as _Path = Path)
