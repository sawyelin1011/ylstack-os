"""
YL StackOS — System tools
Forked from FlyOS (DigitalPlat, AGPL-3.0)
"""
import subprocess
import psutil
import socket
import os
import requests
import random
import time
import secrets
import string
import re
from config import *
from sysconf import *
from werkzeug.security import generate_password_hash, check_password_hash

# userspace CLI — only available in YL StackOS (not original FlyOS)
try:
    from files.userspace.cli import *
except ImportError:
    def userspace_execute(cmd): os.system(cmd)
    def userspace_start(): pass

# ── Paths ─────────────────────────────────────────────────────────────────────
# Base path — /ylstackos/ on device
import os as _os
if _os.path.exists('/ylstackos/files/pwd.conf'):
    _BASE = '/ylstackos'
else:
    _BASE = '/flyos'  # legacy fallback

PASSWORDS_FILE = f"{_BASE}/files/pwd.conf"
TOKEN_FILE     = f"{_BASE}/files/token/token"
SETUP_LOCK     = f"{_BASE}/files/setup/setup_lock"
LOGS_DIR       = f"{_BASE}/logs"


# ── Auth ──────────────────────────────────────────────────────────────────────

def check_password(password):
    with open(PASSWORDS_FILE, "r") as f:
        stored = f.read().strip()
        return check_password_hash(stored, password)


# ── Shell ─────────────────────────────────────────────────────────────────────

def run_system(cmd):
    return os.popen(cmd).read()


# ── Storage ───────────────────────────────────────────────────────────────────

def get_device_storage():
    try:
        disk = psutil.disk_usage('/')
        return round(disk.free / (1024 ** 3), 2)
    except Exception:
        return 0.0


# ── Kernel ────────────────────────────────────────────────────────────────────

def get_kernel_version():
    try:
        return open('/proc/version').read().strip()
    except Exception:
        return 'unknown'


# ── Service checks ────────────────────────────────────────────────────────────

def check_ssh_process():
    return "Running" if os.path.exists('/var/run/sshd.pid') else "Stopped"


def check_vnc_process():
    for proc in psutil.process_iter(['name']):
        try:
            if 'vnc' in proc.info['name'].lower():
                return "Running"
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    return "Stopped"


def check_codeserver_process():
    # pgrep may not be in PATH inside chroot — use psutil instead
    for proc in psutil.process_iter(['name', 'cmdline']):
        try:
            cmdline = ' '.join(proc.info.get('cmdline') or []).lower()
            if 'code-server' in cmdline:
                return "Running"
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    return "Stopped"


def check_ttyd_process():
    for proc in psutil.process_iter(['name']):
        try:
            if 'ttyd' in proc.info['name'].lower():
                return "Running"
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    return "Stopped"


def check_jupyter_process():
    for proc in psutil.process_iter(['name', 'cmdline']):
        try:
            name = proc.info['name'].lower()
            cmdline = ' '.join(proc.info.get('cmdline') or []).lower()
            if 'jupyter' in name or 'jupyter' in cmdline:
                return "Running"
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    return "Stopped"


def check_plugin_process(process_name: str) -> str:
    """Generic process check for plugins."""
    for proc in psutil.process_iter(['name', 'cmdline']):
        try:
            name = proc.info['name'].lower()
            cmdline = ' '.join(proc.info.get('cmdline') or []).lower()
            if process_name.lower() in name or process_name.lower() in cmdline:
                return "Running"
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    return "Stopped"


# ── Framework status ──────────────────────────────────────────────────────────

def ylstack_framework_status():
    """Check if ADB is available — use psutil, no subprocess PATH issues."""
    for proc in psutil.process_iter(['name']):
        try:
            if 'adb' in proc.info['name'].lower():
                return True
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    return False


# ── Battery ───────────────────────────────────────────────────────────────────

def battery_status():
    try:
        cap = open('/sys/class/power_supply/battery/capacity').read().strip()
        sta = open('/sys/class/power_supply/battery/status').read().strip()
        return f"{cap}% {sta}"
    except Exception:
        return 'Unknown'


# ── Network ───────────────────────────────────────────────────────────────────

def get_local_ip():
    """Get LAN IP using psutil — no netifaces dependency."""
    try:
        for iface, addrs in psutil.net_if_addrs().items():
            if iface.startswith(('wlan', 'eth', 'usb', 'rmnet')):
                for addr in addrs:
                    if addr.family == socket.AF_INET and not addr.address.startswith('127.'):
                        return addr.address
        return '127.0.0.1'
    except Exception:
        return '127.0.0.1'


# ── Version ───────────────────────────────────────────────────────────────────

def get_version():
    ver = f"{os_ver}_{os_build_channel}"
    if cust_build:
        ver += f"_{cust_build}"
    return ver


# ── Notifications ─────────────────────────────────────────────────────────────

def send_android_msg(title, msg, msg_id):
    cmd = f'adb shell "su -lp 2000 -c \\"cmd notification post -S bigtext -t \'{title}\' \'{msg_id}\' \'{msg}\'\\""'
    os.system(cmd)


# ── Setup ─────────────────────────────────────────────────────────────────────

def setup_check():
    return os.path.exists(SETUP_LOCK)


# ── Desktop launch ────────────────────────────────────────────────────────────

def launch_linux_mode():
    log = f"{LOGS_DIR}/launch_linux.log"
    os.system(f"rm -rf {log} && touch {log}")
    # adb is at /usr/bin/adb inside the chroot — connects to Android via loopback (emulator-5554)
    # Use setsid instead of nohup — nohup is not in PATH in the chroot
    os.popen(f"/usr/bin/setsid /bin/bash -c '/usr/bin/adb shell input keyevent KEYCODE_HOME >> {log} 2>&1' &").read()
    time.sleep(1)
    os.popen(f"/usr/bin/setsid /bin/bash -c '/usr/bin/adb shell am start -n x.org.server/x.org.server.MainActivity >> {log} 2>&1' &").read()
    time.sleep(10)
    os.popen(f"/usr/bin/setsid /bin/bash -c 'export DISPLAY=:0 PULSE_SERVER=tcp:127.0.0.1:4713 && startxfce4 >> {log} 2>&1' &").read()
    try:
        return open(log).read()
    except Exception:
        return "Launch initiated — check logs for details."


# ── Token ─────────────────────────────────────────────────────────────────────

def gen_newtoken():
    token = ''.join(secrets.choice(string.ascii_letters + string.digits) for _ in range(20))
    os.makedirs(os.path.dirname(TOKEN_FILE), exist_ok=True)
    with open(TOKEN_FILE, 'w') as f:
        f.write(token)
    return token


def get_token():
    try:
        with open(TOKEN_FILE) as f:
            return f.read().strip()
    except FileNotFoundError:
        return gen_newtoken()


# ── RAM / CPU ─────────────────────────────────────────────────────────────────

def get_available_ram():
    try:
        mem = psutil.virtual_memory()
        return f"{mem.available / (1024**3):.1f} GB"
    except Exception:
        return "Unknown"


def get_cpu_usage():
    return psutil.cpu_percent(interval=1)


# ── Userspace ─────────────────────────────────────────────────────────────────

def exec_userspace(cmd):
    userspace_execute(cmd)


def exec_userspace_user(cmd, user):
    userspace_execute(f'su - {user} -c """{cmd}"""')
