"""Config flow (IP các AP + tài khoản quản trị Instant) + reauth + options."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_PASSWORD, CONF_PORT, CONF_USERNAME
from homeassistant.core import HomeAssistant, callback

from . import build_api, parse_hosts
from .api import ArubaApiError, ArubaAuthError
from .const import (
    CONF_HOSTS,
    CONF_SCAN_INTERVAL,
    CONF_VERIFY_SSL,
    DEFAULT_PORT,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    MAX_SCAN_INTERVAL,
    MIN_SCAN_INTERVAL,
)

_LOGGER = logging.getLogger(__name__)


async def _validate(
    hass: HomeAssistant, data: dict[str, Any]
) -> tuple[str | None, str | None]:
    """Đăng nhập thử + tìm AP master. Trả (error_key, tên cụm)."""
    api = build_api(hass, data)
    try:
        name = await api.cluster_name()
    except ArubaAuthError:
        return "invalid_auth", None
    except ArubaApiError:
        return "cannot_connect", None
    except Exception:
        _LOGGER.exception("aruba: lỗi không xác định khi kết nối")
        return "unknown", None
    finally:
        await api.close()
    return None, name or api.hosts[0]


USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOSTS): str,
        vol.Required(CONF_PORT, default=DEFAULT_PORT): vol.All(
            vol.Coerce(int), vol.Range(min=1, max=65535)
        ),
        vol.Required(CONF_VERIFY_SSL, default=False): bool,
        vol.Required(CONF_USERNAME, default="admin"): str,
        vol.Required(CONF_PASSWORD): str,
    }
)


class ArubaConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            hosts = parse_hosts(user_input[CONF_HOSTS])
            if not hosts:
                errors[CONF_HOSTS] = "no_hosts"
            else:
                user_input[CONF_HOSTS] = ", ".join(hosts)
                error, name = await _validate(self.hass, user_input)
                if error is None:
                    await self.async_set_unique_id(str(name).lower())
                    self._abort_if_unique_id_configured()
                    return self.async_create_entry(title=str(name), data=user_input)
                errors["base"] = error
        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(USER_SCHEMA, user_input),
            errors=errors,
        )

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        entry = self._get_reauth_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            error, _name = await _validate(self.hass, {**entry.data, **user_input})
            if error is None:
                return self.async_update_reload_and_abort(
                    entry, data_updates=user_input
                )
            errors["base"] = error
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_USERNAME, default=entry.data[CONF_USERNAME]): str,
                    vol.Required(CONF_PASSWORD): str,
                }
            ),
            description_placeholders={"hosts": entry.data[CONF_HOSTS]},
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return ArubaOptionsFlow()


class ArubaOptionsFlow(OptionsFlow):
    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data=user_input)
        current = self.config_entry.options.get(
            CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL
        )
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_SCAN_INTERVAL, default=current): vol.All(
                        vol.Coerce(int),
                        vol.Range(min=MIN_SCAN_INTERVAL, max=MAX_SCAN_INTERVAL),
                    )
                }
            ),
        )
