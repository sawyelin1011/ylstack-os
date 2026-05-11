"""
YL StackOS — Andronix Edition
System configuration and version info.
Forked from FlyOS (DigitalPlat, AGPL-3.0).
"""

# ── Version ───────────────────────────────────────────────────────────────────
os_ver = "4.0"
os_build_channel = "4000"
cust_build = "andronix-edition"

# ── Linux base ────────────────────────────────────────────────────────────────
linux_base = "Ubuntu 22.04.5 LTS"
linux_codename = "Jammy Jellyfish"
linux_arch = "aarch64"
min_android = "8.0"
requires_root = True
requires_arch = "arm64"

# ── Branding ──────────────────────────────────────────────────────────────────
brand_name = "YL StackOS"
brand_edition = "Andronix Edition"
brand_full = "YL StackOS — Andronix Edition"

# ── Execution mode ────────────────────────────────────────────────────────────
# Set by installer: "rooted" | "proot"
# "rooted" = chroot with full kernel access (all features)
# "proot"  = userspace chroot via ptrace (no root required, limited features)
execution_mode = "rooted"

# ── Auth ──────────────────────────────────────────────────────────────────────
no_pwd_login = False

# ── Update server ─────────────────────────────────────────────────────────────
# Replace with your own update server URL
sys_update_check_server = 'https://update.ylstackos.dev/latest_ver'

# ── Non-root feature restrictions ─────────────────────────────────────────────
# Features disabled when execution_mode == "proot"
PROOT_DISABLED_FEATURES = [
    'usb_tethering',
    'screen_mirror',
    'system_partition_write',
    'cgroup_limits',
    'kernel_modules',
    'adb_root_commands',
    'virtual_network_adapter',
    'android_notifications',
]
