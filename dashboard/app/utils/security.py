"""
YL StackOS — Input validation and security utilities.
All user input must be validated before use in shell commands or file paths.
"""
import re
import secrets
import string
from functools import wraps
from flask import jsonify, request
from sysconf import execution_mode, PROOT_DISABLED_FEATURES


# ── Input validators ──────────────────────────────────────────────────────────

def validate_container_name(name: str) -> str:
    """
    Validate and return a safe container name.
    Raises ValueError if invalid.
    """
    if not name or not name.strip():
        raise ValueError("Container name cannot be empty")
    name = name.strip()
    if len(name) > 64:
        raise ValueError("Container name too long (max 64 chars)")
    if not re.match(r'^[a-zA-Z0-9][a-zA-Z0-9_-]*$', name):
        raise ValueError(
            "Container name must start with a letter/number and contain "
            "only letters, numbers, hyphens, and underscores"
        )
    return name


def validate_container_path(path: str) -> str:
    """Validate a .flycontainer image path."""
    if not path or not path.strip():
        raise ValueError("Image path cannot be empty")
    path = path.strip()
    if not path.endswith('.flycontainer'):
        raise ValueError("Image must be a .flycontainer file")
    # No shell metacharacters
    if re.search(r'[;&|`$<>\\]', path):
        raise ValueError("Invalid characters in path")
    return path


def validate_cidr(cidr: str) -> str:
    """Validate a CIDR notation string like 10.10.0.1/24."""
    if not re.match(r'^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}/\d{1,2}$', cidr):
        raise ValueError(f"Invalid CIDR format: {cidr!r}. Example: 10.10.0.1/24")
    return cidr


def validate_adapter_name(name: str) -> str:
    """Validate a network adapter name (max 15 chars, alphanumeric + hyphen)."""
    if not name or not name.strip():
        raise ValueError("Adapter name cannot be empty")
    name = name.strip()
    if len(name) > 15:
        raise ValueError("Adapter name too long (max 15 chars, Linux limit)")
    if not re.match(r'^[a-zA-Z][a-zA-Z0-9_-]*$', name):
        raise ValueError("Adapter name must start with a letter and contain only letters, numbers, hyphens, underscores")
    return name


def validate_linux_username(username: str) -> str:
    """Validate a Linux username."""
    if not username or not username.strip():
        raise ValueError("Username cannot be empty")
    username = username.strip()
    if not re.match(r'^[a-z_][a-z0-9_-]{0,31}$', username):
        raise ValueError("Invalid Linux username format")
    return username


def validate_timezone(tz: str) -> str:
    """Validate an IANA timezone string."""
    if not tz or not tz.strip():
        raise ValueError("Timezone cannot be empty")
    tz = tz.strip()
    # Basic format check — slashes and underscores only
    if not re.match(r'^[A-Za-z][A-Za-z0-9_+\-/]*$', tz):
        raise ValueError(f"Invalid timezone format: {tz!r}")
    return tz


def validate_cloudflare_token(token: str) -> str:
    """Validate a Cloudflare tunnel token (basic sanity check)."""
    if not token or not token.strip():
        raise ValueError("Token cannot be empty")
    token = token.strip()
    if len(token) < 20:
        raise ValueError("Token too short — check your Cloudflare dashboard")
    # No shell metacharacters
    if re.search(r'[;&|`$<>\\\'"]', token):
        raise ValueError("Invalid characters in token")
    return token


# ── Token generation ──────────────────────────────────────────────────────────

def generate_token(length: int = 20) -> str:
    """Generate a cryptographically secure random token."""
    alphabet = string.ascii_letters + string.digits
    return ''.join(secrets.choice(alphabet) for _ in range(length))


def read_token(token_file: str) -> str:
    """Read API token from file, fresh on each call."""
    try:
        with open(token_file, 'r') as f:
            return f.read().strip()
    except FileNotFoundError:
        return ''


# ── Flask decorators ──────────────────────────────────────────────────────────

def require_token(token_file: str):
    """
    Decorator factory: validate API token from query param.
    Reads token fresh from file on each request (fixes original bug).
    """
    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            provided = request.args.get('token', '')
            valid = read_token(token_file)
            if not provided or provided != valid:
                return jsonify({
                    'status': 401,
                    'error': 'Unauthorized',
                    'message': 'Invalid or missing API token'
                }), 401
            return f(*args, **kwargs)
        return wrapper
    return decorator


def requires_root(f):
    """
    Decorator: return 403 with explanation if running in proot (non-root) mode.
    Apply to any route that requires root access.
    """
    @wraps(f)
    def wrapper(*args, **kwargs):
        if execution_mode == 'proot':
            return jsonify({
                'error': 'root_required',
                'message': (
                    'This feature requires root access. '
                    'YL StackOS is running in non-root (proot) mode.'
                ),
                'upgrade_hint': 'Root your device to unlock all features.',
                'disabled_features': PROOT_DISABLED_FEATURES,
            }), 403
        return f(*args, **kwargs)
    return wrapper
