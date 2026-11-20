"""Thẻ Lovelace đi kèm: tệp có thật, cùng phiên bản với manifest, đăng ký đúng một lần."""

from __future__ import annotations

import json
import re
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant.core import HomeAssistant

from custom_components.aruba_instant_ha import CARD_FILE, CARD_URL, async_register_card

MANIFEST = Path(CARD_FILE).parents[1] / "manifest.json"


def test_card_file_matches_manifest_version():
    js = CARD_FILE.read_text(encoding="utf-8")
    version = json.loads(MANIFEST.read_text(encoding="utf-8"))["version"]
    assert re.search(r'export const VERSION = "([^"]+)"', js).group(1) == version
    assert 'customElements.define("aruba-wifi-card"' in js
    assert (
        "lan-wifi-card" not in js.split("Tách từ", 1)[1].split("\n", 1)[1]
    )  # không đè thẻ cũ của lan-topo-card


async def test_register_card_skips_without_frontend(hass: HomeAssistant):
    assert await async_register_card(hass) is False


async def test_register_card_once_with_versioned_url(hass: HomeAssistant):
    hass.config.components.add("frontend")
    hass.http = MagicMock(async_register_static_paths=AsyncMock())
    with patch("homeassistant.components.frontend.add_extra_js_url") as add:
        assert await async_register_card(hass) is True
        assert await async_register_card(hass) is True  # lần hai: không đăng ký lại
    hass.http.async_register_static_paths.assert_awaited_once()
    cfg = hass.http.async_register_static_paths.await_args.args[0][0]
    assert cfg.url_path == CARD_URL and cfg.path == str(CARD_FILE)
    version = json.loads(MANIFEST.read_text(encoding="utf-8"))["version"]
    add.assert_called_once_with(hass, f"{CARD_URL}?v={version}")
