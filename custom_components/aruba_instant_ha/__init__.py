"""Aruba Instant — thiết bị Wi-Fi (RSSI, băng tần, SSID, AP) + tải radio của cụm IAP qua API web."""

from __future__ import annotations

from pathlib import Path

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD, CONF_PORT, CONF_USERNAME, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.typing import ConfigType
from homeassistant.loader import async_get_integration

from .api import ArubaInstantApi
from .const import (
    CONF_HOSTS,
    CONF_SCAN_INTERVAL,
    CONF_VERIFY_SSL,
    DEFAULT_PORT,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
)
from .coordinator import ArubaCoordinator

PLATFORMS: list[Platform] = [Platform.SENSOR]

type ArubaConfigEntry = ConfigEntry[ArubaCoordinator]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

# Thẻ Lovelace đi kèm integration: phục vụ tệp JS trong frontend/ và tự nạp vào frontend ⇒ cài integration
# là dùng được `type: custom:aruba-wifi-card`, không cần thêm resource. `?v=` = phiên bản để trình duyệt
# bỏ bản cũ khi nâng cấp.
CARD_FILE = Path(__file__).parent / "frontend" / "aruba-wifi-card.js"
CARD_URL = f"/{DOMAIN}/aruba-wifi-card.js"
_CARD_KEY = f"{DOMAIN}_card_registered"


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    await async_register_card(hass)
    return True


async def async_register_card(hass: HomeAssistant) -> bool:
    """Đăng ký thẻ một lần. Không có http/frontend (vd khi test) thì bỏ qua, không lỗi."""
    if hass.data.get(_CARD_KEY):
        return True
    if getattr(hass, "http", None) is None or "frontend" not in hass.config.components:
        return False
    from homeassistant.components.frontend import add_extra_js_url
    from homeassistant.components.http import StaticPathConfig

    integration = await async_get_integration(hass, DOMAIN)
    await hass.http.async_register_static_paths(
        [StaticPathConfig(CARD_URL, str(CARD_FILE), cache_headers=True)]
    )
    add_extra_js_url(hass, f"{CARD_URL}?v={integration.version}")
    hass.data[_CARD_KEY] = True
    return True


def parse_hosts(value: str | list[str]) -> list[str]:
    """ "192.168.10.51, 192.168.10.52" → ["192.168.10.51", "192.168.10.52"] (bỏ trùng, giữ thứ tự)."""
    items = (
        value if isinstance(value, list) else str(value).replace(";", ",").split(",")
    )
    out: list[str] = []
    for item in items:
        host = (
            str(item)
            .strip()
            .removeprefix("https://")
            .removeprefix("http://")
            .split("/")[0]
        )
        host = host.split(":")[0] if host.count(":") == 1 else host
        if host and host not in out:
            out.append(host)
    return out


def build_api(hass: HomeAssistant, data: dict) -> ArubaInstantApi:
    return ArubaInstantApi(
        async_get_clientsession(hass, verify_ssl=data.get(CONF_VERIFY_SSL, False)),
        parse_hosts(data[CONF_HOSTS]),
        data[CONF_USERNAME],
        data[CONF_PASSWORD],
        port=int(data.get(CONF_PORT, DEFAULT_PORT)),
        verify_ssl=data.get(CONF_VERIFY_SSL, False),
    )


async def async_setup_entry(hass: HomeAssistant, entry: ArubaConfigEntry) -> bool:
    coordinator = ArubaCoordinator(
        hass,
        build_api(hass, dict(entry.data)),
        entry,
        int(entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)),
    )
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ArubaConfigEntry) -> bool:
    ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if ok:
        # Instant giới hạn số phiên quản trị → trả phiên khi gỡ / nạp lại
        await entry.runtime_data.api.close()
    return ok


async def _async_update_listener(hass: HomeAssistant, entry: ArubaConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)
