"""
YL StackOS — Device capability detection.
Run once at startup, cache results.
Determines which features are available on this device.
"""
import os
import shutil
import subprocess
import logging

log = logging.getLogger(__name__)

_cache: dict | None = None


def probe(force: bool = False) -> dict:
    """
    Probe device capabilities. Results are cached after first call.

    Returns a dict of capability_name → bool/str/int.
    """
    global _cache
    if _cache is not None and not force:
        return _cache

    caps = {}

    # ── Execution mode ────────────────────────────────────────────────────────
    caps['proot_mode'] = os.environ.get('YLSTACK_PROOT', '0') == '1'
    caps['root_available'] = _is_root()

    # ── Required binaries ─────────────────────────────────────────────────────
    caps['adb_available'] = shutil.which('adb') is not None
    caps['vnc_available'] = shutil.which('vncserver') is not None
    caps['ttyd_available'] = shutil.which('ttyd') is not None
    caps['code_server_available'] = shutil.which('code-server') is not None
    caps['wine_available'] = shutil.which('wine') is not None
    caps['filebrowser_available'] = shutil.which('filebrowser') is not None

    # noVNC — check for the proxy script
    novnc_paths = [
        '/ylstackosext/novnc/utils/novnc_proxy',
        '/flyosext/novnc/utils/novnc_proxy',
    ]
    caps['novnc_available'] = any(os.path.exists(p) for p in novnc_paths)

    # Cloudflared
    cloudflared_paths = [
        '/ylstackosext/cloudflared/cloudflared',
        '/flyosext/cloudflared/cloudflared',
    ]
    caps['cloudflared_available'] = any(os.path.exists(p) for p in cloudflared_paths)

    # ── Kernel features (root only) ───────────────────────────────────────────
    if caps['root_available']:
        caps['cgroup_v1'] = os.path.exists('/sys/fs/cgroup/memory')
        caps['cgroup_v2'] = os.path.exists('/sys/fs/cgroup/cgroup.controllers')
        caps['namespace_support'] = _check_namespaces()
    else:
        caps['cgroup_v1'] = False
        caps['cgroup_v2'] = False
        caps['namespace_support'] = False

    # ── Device info (via ADB if available) ────────────────────────────────────
    if caps['adb_available']:
        caps['android_version'] = _adb_prop('ro.build.version.release')
        caps['sdk_version'] = _safe_int(_adb_prop('ro.build.version.sdk'))
        caps['cpu_arch'] = _adb_prop('ro.product.cpu.abi')
        caps['device_model'] = _adb_prop('ro.product.model')
        caps['manufacturer'] = _adb_prop('ro.product.manufacturer')
    else:
        # Fallback: read from /proc or uname
        caps['android_version'] = _read_file('/proc/version', default='unknown')
        caps['sdk_version'] = 0
        caps['cpu_arch'] = _uname_arch()
        caps['device_model'] = 'unknown'
        caps['manufacturer'] = 'unknown'

    # ── Storage & RAM ─────────────────────────────────────────────────────────
    try:
        import psutil
        disk = psutil.disk_usage('/')
        caps['storage_gb'] = round(disk.free / (1024 ** 3), 1)
        mem = psutil.virtual_memory()
        caps['ram_total_mb'] = mem.total // (1024 * 1024)
    except Exception:
        caps['storage_gb'] = 0
        caps['ram_total_mb'] = 0

    log.info(
        "Capabilities probed: root=%s proot=%s adb=%s vnc=%s",
        caps['root_available'], caps['proot_mode'],
        caps['adb_available'], caps['vnc_available']
    )

    _cache = caps
    return caps


def get(key: str, default=None):
    """Get a single capability value."""
    return probe().get(key, default)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _is_root() -> bool:
    try:
        result = subprocess.run(
            ['id', '-u'], capture_output=True, text=True, timeout=3
        )
        return result.stdout.strip() == '0'
    except Exception:
        return False


def _adb_prop(prop: str) -> str:
    try:
        result = subprocess.run(
            ['adb', 'shell', 'getprop', prop],
            capture_output=True, text=True, timeout=5
        )
        return result.stdout.strip()
    except Exception:
        return ''


def _check_namespaces() -> bool:
    """Check if user namespaces are available."""
    return os.path.exists('/proc/self/ns/user')


def _read_file(path: str, default: str = '') -> str:
    try:
        return open(path).read().strip()
    except Exception:
        return default


def _uname_arch() -> str:
    try:
        result = subprocess.run(['uname', '-m'], capture_output=True, text=True, timeout=3)
        return result.stdout.strip()
    except Exception:
        return 'unknown'


def _safe_int(s: str) -> int:
    try:
        return int(s)
    except (ValueError, TypeError):
        return 0
