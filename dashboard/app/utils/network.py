"""
YL StackOS — Network utilities.
Replaces netifaces (unmaintained) with psutil.
"""
import socket
import psutil


def get_local_ip() -> str:
    """
    Return the device's LAN IP address.
    Prefers wlan/eth/rmnet interfaces over loopback.
    Falls back to 127.0.0.1 if nothing found.
    """
    try:
        for iface, addrs in psutil.net_if_addrs().items():
            # Prefer wireless and ethernet interfaces
            if iface.startswith(('wlan', 'eth', 'en', 'rmnet', 'wlp', 'ens', 'enp')):
                for addr in addrs:
                    if (addr.family == socket.AF_INET
                            and not addr.address.startswith('127.')
                            and not addr.address.startswith('169.254.')):
                        return addr.address
    except Exception:
        pass
    return '127.0.0.1'


def get_all_interfaces() -> dict[str, list[str]]:
    """Return dict of interface name → list of IPv4 addresses."""
    result: dict[str, list[str]] = {}
    try:
        for iface, addrs in psutil.net_if_addrs().items():
            ips = [
                a.address for a in addrs
                if a.family == socket.AF_INET
            ]
            if ips:
                result[iface] = ips
    except Exception:
        pass
    return result
