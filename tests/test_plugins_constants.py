"""
Tests for flame_po/plugins/constants.py

Covers:
  - get_plugins: shipped config is complete and well-formed
  - _sanitize_plugin_configs: drops malformed/incomplete entries, discards unknown keys
"""

from unittest.mock import patch

import pytest

from flame_po.plugins.constants import get_plugins, _sanitize_plugin_configs


_VALID = {
    "name": "Plugin",
    "component": "flame-plugin",
    "location": "/plugin",
    "endpoints": ["/a", "/b"],
}


def _sanitize(*plugins):
    with patch("flame_po.plugins.constants._PLUGINS", list(plugins)):
        return _sanitize_plugin_configs()


class TestGetPlugins:
    def test_default_config_contains_nextflow_launcher(self):
        components = [p["component"] for p in get_plugins()]
        assert "flame-nextflow-launcher" in components

    def test_default_config_is_well_formed(self):
        for plugin in get_plugins():
            assert set(plugin) == {"name", "component", "location", "endpoints"}
            assert plugin["location"].startswith("/")
            assert all(e.startswith("/") for e in plugin["endpoints"])


class TestSanitizePluginConfigs:
    def test_valid_entry_is_kept(self):
        assert _sanitize(_VALID) == [_VALID]

    def test_unknown_keys_are_discarded(self):
        assert _sanitize({**_VALID, "extra": "value"}) == [_VALID]

    @pytest.mark.parametrize("missing", ["name", "component", "location", "endpoints"])
    def test_incomplete_entry_is_dropped(self, missing):
        entry = {k: v for k, v in _VALID.items() if k != missing}
        assert _sanitize(entry) == []

    def test_location_without_leading_slash_is_dropped(self):
        assert _sanitize({**_VALID, "location": "plugin"}) == []

    def test_endpoint_without_leading_slash_is_dropped(self):
        assert _sanitize({**_VALID, "endpoints": ["/a", "b"]}) == []

    def test_only_malformed_entries_are_dropped(self):
        other = {**_VALID, "component": "flame-other", "location": "/other"}
        assert _sanitize({**_VALID, "location": "bad"}, other) == [other]

    def test_empty_config_returns_empty_list(self):
        assert _sanitize() == []
