"""
YL StackOS — Andronix Edition
Login message of the day (MOTD).
Shown on SSH/shell login.
"""
import socket
import psutil
import sys
import os

# Add both possible paths to sys.path for compatibility
# /ylstackos is the current path; /flyos is the legacy fallback
sys.path.insert(0, '/ylstackos')
sys.path.insert(0, '/flyos')  # legacy fallback — keep for backward compat

try:
    import config
    import tools
except ImportError as e:
    # If imports fail, print error and exit gracefully
    print(f"Warning: Could not load MOTD config: {e}", file=sys.stderr)
    sys.exit(0)

if config.show_motd == False:
    sys.exit()


def get_cpu_usage():
    return psutil.cpu_percent(interval=1)


def get_memory_usage():
    return psutil.virtual_memory().percent


def get_disk_usage():
    return psutil.disk_usage('/').percent


def get_local_ip():
    """Get LAN IP using psutil (no netifaces dependency)."""
    try:
        for iface, addrs in psutil.net_if_addrs().items():
            if iface.startswith(('wlan', 'eth', 'usb', 'rmnet')):
                for addr in addrs:
                    if addr.family == socket.AF_INET and not addr.address.startswith('127.'):
                        return addr.address
        return '127.0.0.1'
    except Exception:
        return '127.0.0.1'


def check_port_open(port):
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(1)
        result = s.connect_ex(('localhost', port))
        s.close()
        return result == 0
    except Exception:
        return False


ip = get_local_ip()
ver = tools.get_version()

print(f"""
╔══════════════════════════════════════════════╗
║         YL StackOS — Andronix Edition        ║
╚══════════════════════════════════════════════╝

  Version : {ver}
  Docs    : https://github.com/sawyelin/ylstack-os

  Network : {ip}
  CPU     : {get_cpu_usage()}%
  Memory  : {get_memory_usage()}%
  Disk    : {get_disk_usage()}%
""")

if check_port_open(config.server_port):
    print(f"  ✓ Dashboard : http://{ip}:{config.server_port}/ui/")
    print(f"  ✓ Dashboard : http://localhost:{config.server_port}/ui/\n")
else:
    print(f"  ⚠ Dashboard not running — start with: python3 /ylstackos/start.py\n")
