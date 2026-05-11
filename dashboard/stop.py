"""
YL StackOS — Andronix Edition
Service shutdown script.
Runs inside the container via: python3 /ylstackos/stop.py
Forked from FlyOS (DigitalPlat, AGPL-3.0)
"""
import os
import subprocess
from config import server_port, terminal_port, android_terminal_port

BASE = "/ylstackos"
LOGS = f"{BASE}/logs"


def kill(pattern: str):
    os.system(f"pkill -f '{pattern}' 2>/dev/null")


def killall(name: str):
    os.system(f"killall -9 {name} 2>/dev/null")


def service(name: str, action: str):
    os.system(f"/etc/init.d/{name} {action} 2>/dev/null")


print("[ylstackos] Stopping all services...")

# Dashboard
kill(f"python3 {BASE}/main.py")
kill("gunicorn")

# Web terminals
kill(f"ttyd -p {terminal_port}")
kill(f"ttyd -p {android_terminal_port}")
killall("ttyd")

# VNC
os.system("vncserver -kill :1 2>/dev/null")
os.system("vncserver -kill :2 2>/dev/null")
os.system("vncserver -kill :3 2>/dev/null")
killall("Xtightvnc")
killall("Xtigervnc")

# noVNC proxy
kill("novnc_proxy")

# code-server
kill("code-server")

# File browser
kill("/usr/local/bin/filebrowser")

# SSH
service("ssh", "stop")

print("[ylstackos] All services stopped.")
