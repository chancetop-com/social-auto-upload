from pathlib import Path

import pytest

from sau_worker.desktop import configure


def test_reinstall_reuses_settings_and_only_prompts_for_a_new_selected_provider(tmp_path):
    state = tmp_path / "Worker Data"
    state.mkdir()
    initial = dict(SAU_GATEWAY_URL="https://example.test/gateway", SAU_DESKTOP_TOKEN="fixture-cloud",
                   BITBROWSER_API_KEY="local-bit-key", BITBROWSER_API_BASE="http://127.0.0.1:4444",
                   WORKER_MAX_CONCURRENCY="3")
    asked = []
    def prompt(name):
        asked.append(name)
        return "local-ads-key"
    first = configure(state, initial, prompt)
    assert first["SAU_PROVIDERS"] == "bitbrowser"
    assert not asked
    second = configure(state, {"SAU_PROVIDERS": "bitbrowser,adspower"}, prompt)
    assert second["ADSPOWER_API_KEY"] == "local-ads-key"
    assert len(asked) == 1 and "ADSPOWER_API_KEY" in asked[0]
    assert second["SAU_GATEWAY_URL"] == "https://example.test/gateway"
    assert second["WORKER_MAX_CONCURRENCY"] == "3"
    assert second["BITBROWSER_API_BASE"] == "http://127.0.0.1:4444"
