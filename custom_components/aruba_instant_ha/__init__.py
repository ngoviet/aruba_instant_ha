"""Aruba Instant — thiết bị Wi-Fi (RSSI, băng tần, SSID, AP) + tải radio của cụm IAP qua API web."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD, CONF_PORT, CONF_USERNAME, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession

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
