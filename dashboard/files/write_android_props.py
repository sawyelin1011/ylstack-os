 #!/usr/bin/env python3
"""
Runs on Android side (NOT inside chroot) to write Android device properties
to a JSON cache file readable by Flask inside the chroot.

Run from Android shell: python3 /data/local/tmp/write_props.py
"""
import subprocess, json, os, sys

# Try multiple getprop locations
GETPROP = None
for p in ['/system/bin/getprop', '/vendor/bin/getprop', 'getprop']:
    try:
        r = subprocess.run([p, 'ro.product.model'], capture_output=True, text=True, timeout=3)
        if r.returncode == 0 and r.stdout.strip():
            GETPROP = p
            break
    except Exception:
        continue

if not GETPROP:
    print("ERROR: getprop not found")
    sys.exit(1)

CACHE = '/data/local/flyos/rootfs/ylstackos/files/android_props.json'

props_to_read = [
    'ro.product.model',
    'ro.product.manufacturer',
    'ro.product.brand',
    'ro.build.version.release',
    'ro.build.version.sdk',
    'ro.serialno',
    'ro.boot.serialno',
    'ro.product.device',
    'ro.product.name',
]

result = {}
for prop in props_to_read:
    try:
        r = subprocess.run([GETPROP, prop], capture_output=True, text=True, timeout=3)
        val = r.stdout.strip()
        if val:
            result[prop] = val
    except Exception as e:
        print(f"  skip {prop}: {e}")

os.makedirs(os.path.dirname(CACHE), exist_ok=True)
with open(CACHE, 'w') as f:
    json.dump(result, f, indent=2)

print("Written to", CACHE)
print(json.dumps(result, indent=2))
