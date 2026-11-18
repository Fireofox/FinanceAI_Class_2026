import json

import pytest

from simple_agent.config import load_config


def test_api_key_from_config_and_environment_precedence(tmp_path, monkeypatch):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"apiKey": "config-key"}), encoding="utf-8")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert load_config(path).api_key == "config-key"
    monkeypatch.setenv("OPENAI_API_KEY", "")
    assert load_config(path).api_key == "config-key"
    monkeypatch.setenv("OPENAI_API_KEY", "environment-key")
    assert load_config(path).api_key == "environment-key"


def test_missing_api_key_and_invalid_config_type(tmp_path, monkeypatch):
    path = tmp_path / "config.json"
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert load_config(path).api_key == ""
    path.write_text(json.dumps({"apiKey": None}), encoding="utf-8")
    with pytest.raises(ValueError, match="apiKey must be a string"):
        load_config(path)


def test_script_settings_default_and_override(tmp_path):
    path = tmp_path / "config.json"
    defaults = load_config(path)
    assert (defaults.script_approval, defaults.script_timeout, defaults.script_output_limit) == (False, 60, 32768)
    path.write_text(json.dumps({"scriptApproval": True, "scriptTimeout": 3.5, "scriptOutputLimit": 42}), encoding="utf-8")
    configured = load_config(path)
    assert (configured.script_approval, configured.script_timeout, configured.script_output_limit) == (True, 3.5, 42)


@pytest.mark.parametrize("settings", [
    {"scriptApproval": "false"}, {"scriptTimeout": 0}, {"scriptTimeout": True},
    {"scriptOutputLimit": -1}, {"scriptOutputLimit": 1.5},
])
def test_invalid_script_settings_are_rejected(tmp_path, settings):
    path = tmp_path / "config.json"
    path.write_text(json.dumps(settings), encoding="utf-8")
    with pytest.raises(ValueError):
        load_config(path)
