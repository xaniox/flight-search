"""Shared fixtures for the whole suite."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def xdg_config_home(tmp_path_factory, monkeypatch):
    """Point XDG_CONFIG_HOME at an empty directory for every test.

    No test may read the developer's real ``config.toml``; a test that needs
    a config file writes it below this directory (PRTWO-CRITERION-11).
    """
    directory = tmp_path_factory.mktemp("xdg-config")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(directory))
    return directory
