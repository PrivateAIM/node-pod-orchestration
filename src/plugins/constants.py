"""Static configuration of optional node plugins reachable from analyses.

Each plugin entry describes a node service an analysis may talk to through its
nginx sidecar:

* ``name``: human-readable name, used in nginx comments and log messages.
* ``component``: value of the ``component`` label selecting the plugin's
  service/pods; pods with this label are also allowed ingress to the nginx.
* ``location``: nginx path prefix (must start with ``/``).
* ``endpoints``: paths below ``location`` the analysis may call (each must
  start with ``/``; matched exactly).
"""
from typing import Any


_PLUGINS = [
    {
        "name": "Nextflow Launcher",                # arbitrary service name
        "component": "flame-nextflow-launcher",     # plugin component label
        "location": "/nextflow",                    # nginx proxy path
        "endpoints": ["/run",                       # list of endpoints
                      "/delete",
                      "/token_refresh"]
    }
]


def get_plugins() -> list[dict[str, Any]]:
    """Return the sanitized plugin configs (see ``_sanitize_plugin_configs``)."""
    return _sanitize_plugin_configs()


def _sanitize_plugin_configs() -> list[dict[str, Any]]:
    """Filter ``_PLUGINS`` down to complete, well-formed entries.

    Entries whose ``location`` or any ``endpoints`` entry does not start with
    ``/``, or which miss one of the required keys, are dropped. Unknown keys
    are discarded.

    Returns:
        List of plugin dicts with ``name``, ``component``, ``location`` and ``endpoints``.
    """
    plugins = []
    for plugin_vals in _PLUGINS:
        sanitized_vals = {}
        for key, value in plugin_vals.items():
            if key in ["name", "component"]:
                sanitized_vals[key] = value
            elif key == "location":
                if value.startswith('/'):
                    sanitized_vals[key] = value
                else:
                    break
            elif key == "endpoints":
                if all(e.startswith('/') for e in value):
                    sanitized_vals[key] = value
                else:
                    break
        if all(k in sanitized_vals for k in ["name", "component", "location", "endpoints"]):
            plugins.append(sanitized_vals)

    return plugins
