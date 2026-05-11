"""
YL StackOS — Plugin API Blueprint
"""
import sys
import os

# Ensure /ylstackos is on sys.path so plugins.plugin_manager can be found
_base = '/ylstackos' if os.path.exists('/ylstackos') else '/flyos'
if _base not in sys.path:
    sys.path.insert(0, _base)

_load_error = None
try:
    from plugins.plugin_manager import get_blueprint
    api_plugins = get_blueprint()
except Exception as _e:
    _load_error = str(_e)
    from flask import Blueprint, jsonify
    api_plugins = Blueprint('api_plugins', __name__, url_prefix='/api/plugins')

    @api_plugins.route('/')
    @api_plugins.route('/<path:subpath>', methods=['GET', 'POST'])
    def _unavailable(subpath=''):
        return jsonify({'error': f'Plugin manager unavailable: {_load_error}'}), 503
