"""Diagnostics: snapshot cụm (che mật khẩu / tài khoản / serial / MAC / IP client)."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant

from . import ArubaConfigEntry

TO_REDACT = {CONF_PASSWORD, CONF_USERNAME, "serial", "mac", "ip", "hostname", "name"}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ArubaConfigEntry
) -> dict[str, Any]:
    coordinator = entry.runtime_data
    data = asdict(coordinator.data) if coordinator.data else None
    return async_redact_data(
        {
            "entry": {"data": dict(entry.data), "options": dict(entry.options)},
            "conductor": coordinator.api.host,
            "last_update_success": coordinator.last_update_success,
            "data": data,
        },
        TO_REDACT,
    )
