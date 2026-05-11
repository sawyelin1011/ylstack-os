"""
YL StackOS — Andronix Edition
Service startup script.
Runs inside the container at boot via: python3 /ylstackos/start.py
Forked from FlyOS (DigitalPlat, AGPL-3.0)
"""
import os
import subprocess
from config import *

# userspace CLI — only available in YL StackOS (not original FlyOS)
try:
    from files.userspace.cli import userspace_start, exec_userspace
except ImportError:
    def userspace_start(): pass
    def exec_userspace(cmd): os.system(cmd)

# ── Paths ─────────────────────────────────────────────────────────────────────
# Auto-detect base path (supports both /flyos and /ylstackos)
import os as _os
BASE    = "/ylstackos" if _os.path.exists("/ylstackos") else "/flyos"
EXT     = "/ylstackosext" if _os.path.exists("/ylstackosext") else "/flyosext"
LOGS    = f"{BASE}/logs"

# ── Helpers ───────────────────────────────────────────────────────────────────

def log(msg: str):
    os.makedirs(LOGS, exist_ok=True)
    print(f"[ylstackos] {msg}")


def run(cmd: str, log_file: str = None):
    """Run a shell command, optionally logging output."""
    if log_file:
        os.system(f"nohup {cmd} >> {LOGS}/{log_file} 2>&1 &")
    else:
        os.system(cmd)


def logs_check():
    """Rotate log files larger than 1 MB."""
    log_files = [
        f"{LOGS}/ylstackos_main.log",
        f"{LOGS}/ttyd.log",
        f"{LOGS}/ttyd_android.log",
        f"{LOGS}/ttyd_userspace.log",
        f"{LOGS}/vnc_default.log",
        f"{LOGS}/novnc.log",
        f"{LOGS}/ssh.log",
        f"{LOGS}/code_server.log",
        f"{LOGS}/file_browser.log",
        f"{LOGS}/boot_scripts.log",
    ]
    threshold_bytes = 1024 * 1024  # 1 MB
    for f in log_files:
        try:
            if os.path.getsize(f) > threshold_bytes:
                os.remove(f)
        except FileNotFoundError:
            pass


# ── Boot ──────────────────────────────────────────────────────────────────────

log("Starting YL StackOS services...")
os.makedirs(LOGS, exist_ok=True)

# ADB server (needed for Android manager features)
os.system("adb start-server")

# Write Android device properties to a cache file readable from chroot
# getprop is only available on Android side, not inside chroot
try:
    import json, subprocess
    props_to_cache = [
        'ro.product.model', 'ro.product.manufacturer', 'ro.product.brand',
        'ro.build.version.release', 'ro.build.version.sdk',
        'ro.serialno', 'ro.boot.serialno', 'ro.product.device',
    ]
    cached = {}
    for prop in props_to_cache:
        try:
            r = subprocess.run(['getprop', prop], capture_output=True, text=True, timeout=3)
            val = r.stdout.strip()
            if val:
                cached[prop] = val
        except Exception:
            pass
    if cached:
        cache_path = f'{BASE}/files/android_props.json'
        os.makedirs(os.path.dirname(cache_path), exist_ok=True)
        with open(cache_path, 'w') as f:
            json.dump(cached, f)
        log(f"Android props cached: {list(cached.keys())}")
except Exception as e:
    log(f"Warning: could not cache Android props: {e}")

# Set hostname
os.system(f"hostname {hostname}")

# Rotate old logs
logs_check()

# ── Dashboard ─────────────────────────────────────────────────────────────────

if boot_dashboard:
    log(f"Starting dashboard ({dashboard_server}) on port {server_port}...")
    if dashboard_server == 'dev':
        run(f"python3 {BASE}/main_ylstack.py", "ylstackos_main.log")
    elif dashboard_server == 'gunicorn':
        if server_enable_ssl:
            run(
                f"gunicorn -b {dashboard_host_addr}:{server_port} "
                f"--chdir {BASE} main_ylstack:app "
                f"--certfile={ssl_cert_path} --keyfile={ssl_key_path}",
                "ylstackos_main.log"
            )
        else:
            run(
                f"gunicorn -b {dashboard_host_addr}:{server_port} "
                f"--chdir {BASE} main_ylstack:app",
                "ylstackos_main.log"
            )

# ── Userspace ─────────────────────────────────────────────────────────────────

if boot_userspace:
    log("Starting userspace container...")
    userspace_start()

if userspace_ttyd:
    run(f"ttyd -p {userspace_ttyd_port} --writable userspace_login", "ttyd_userspace.log")

# ── SSH + Web Terminal ────────────────────────────────────────────────────────

if boot_ssh:
    log(f"Starting SSH on port 2222 and web terminals (ports {terminal_port}, {android_terminal_port})...")
    # Start sshd with absolute path on port 2222 (avoids port <1024 restrictions on Android)
    run("/usr/sbin/sshd -p 2222", "ssh.log")
    run(f"ttyd -p {terminal_port} --writable login", "ttyd.log")
    run(f"ttyd -p {android_terminal_port} --writable android_shell", "ttyd_android.log")

# ── VNC ───────────────────────────────────────────────────────────────────────

if boot_default_vnc:
    log(f"Starting VNC server (display :{vnc_default_port}, geometry {vnc_default_geometry})...")
    user = userspace_vnc_login_user
    exec_userspace(f"""
rm -rf /tmp/.X11-unix/X{vnc_default_port}
rm -rf /tmp/.X{vnc_default_port}-lock
su - {user} -c 'nohup vncserver :{vnc_default_port} -geometry {vnc_default_geometry} -localhost {vnc_default_localhost} >> /ylstackos/logs/vnc_default.log 2>&1 &'
""")

if boot_vnc_1920x1080:
    user = userspace_vnc_login_user
    exec_userspace(f"""
su - {user} -c 'nohup vncserver :2 -geometry 1920x1080 -localhost {vnc_default_localhost} >> /ylstackos/logs/vnc_1920x1080.log 2>&1 &'
""")

if boot_vnc:
    log(f"Starting noVNC proxy on port {vnc_port}...")
    run(
        f"{EXT}/novnc/utils/novnc_proxy "
        f"--vnc localhost:590{vnc_default_port} "
        f"--listen {novnc_proxy_addr}:{vnc_port}",
        "novnc.log"
    )

# ── Apps ──────────────────────────────────────────────────────────────────────

if boot_code_server:
    log(f"Starting code-server on port {code_server_port}...")
    run("code-server", "code_server.log")

if boot_file_browser:
    log(f"Starting file browser on port {file_browser_port}...")
    run(
        f"/usr/local/bin/filebrowser "
        f"-p {file_browser_port} "
        f"-a {file_browser_addr} "
        f"-r {file_browser_listen_dir} "
        f"-d {EXT}/filebrowser/filebrowser.db",
        "file_browser.log"
    )

# ── Boot scripts ──────────────────────────────────────────────────────────────

if boot_runscripts:
    log("Running boot scripts from /boot/scripts/...")
    run('find /boot/scripts -name "*.sh" -exec bash {} \\;', "boot_scripts.log")

log("All services started.")

# ── Auto-start plugins with boot=true ─────────────────────────────────────────

try:
    import json
    _installed_file = f'{BASE}/plugins/installed.json'
    if os.path.exists(_installed_file):
        _installed = json.load(open(_installed_file))
        # Import catalog
        import sys as _sys
        _sys.path.insert(0, BASE)
        from plugins.plugin_manager import CATALOG as _CATALOG
        for _pid, _info in _installed.items():
            if not _info.get('boot'):
                continue
            _m = _CATALOG.get(_pid)
            if not _m or not _m.get('service', {}).get('start'):
                continue
            log(f"Auto-starting plugin: {_m['name']}...")
            run(f"/bin/bash -c '{_m['service']['start']}'", f"plugin_{_pid}.log")
except Exception as _e:
    log(f"Warning: plugin auto-start failed: {_e}")
