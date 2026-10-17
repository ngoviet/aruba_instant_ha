"""DataUpdateCoordinator: 1 cụm Instant = 1 coordinator, đọc `show aps` + `show clients`."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import ArubaApiError, ArubaAuthError, ArubaInstantApi, Table
from .const import CMD_APS, CMD_CLIENTS, DOMAIN, LEASE_SOURCE_DOMAIN

_LOGGER = logging.getLogger(__name__)

_VALUE_RE = re.compile(r"^\s*(-?\d+)\s*(?:\(([^)]*)\))?")
_CHANNEL_RE = re.compile(r"^\s*(\d+)")


def parse_value(text: str | None) -> tuple[int | None, str | None]:
    """ "45(good)" → (45, "good"); "-94(good)" → (-94, "good"); "--" → (None, None)."""
    m = _VALUE_RE.match(text or "")
    if not m:
        return None, None
    return int(m.group(1)), (m.group(2) or None)


def band_of(channel: str | None) -> str | None:
    """Kênh Wi-Fi → băng tần: "6" → "2.4", "44+" / "100E" → "5"."""
    m = _CHANNEL_RE.match(channel or "")
    if not m:
        return None
    return "2.4" if int(m.group(1)) <= 14 else "5"


@dataclass(frozen=True)
class Radio:
    index: int
    band: str | None
    channel: str
    power_dbm: int | None
    utilization: int | None  # % thời gian kênh bận
    noise_dbm: int | None


@dataclass(frozen=True)
class AccessPoint:
    name: str
    ip: str | None
    serial: str | None
    model: str | None
    clients: int | None
    radios: tuple[Radio, ...]

    def radio(self, band: str) -> Radio | None:
        return next((r for r in self.radios if r.band == band), None)


@dataclass(frozen=True)
class Client:
    mac: str
    name: str  # comment DHCP lease (nếu có) hoặc hostname Wi-Fi
    hostname: str | None
    ip: str | None
    os: str | None
    essid: str | None
    ap: str | None
    channel: str | None
    band: str | None
    phy: str | None  # "GN" (2.4 GHz 802.11n), "AC" (5 GHz 802.11ac), …
    signal: int | None
    quality: str | None  # "good" | "ok" | "poor"
    speed_mbps: int | None
    role: str | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "hostname": self.hostname,
            "ip": self.ip,
            "mac": self.mac,
            "os": self.os,
            "essid": self.essid,
            "ap": self.ap,
            "channel": self.channel,
            "band": self.band,
            "phy": self.phy,
            "signal": self.signal,
            "quality": self.quality,
            "speed_mbps": self.speed_mbps,
        }


@dataclass
class WifiData:
    aps: dict[str, AccessPoint] = field(default_factory=dict)
    clients: list[Client] = field(default_factory=list)

    def ssids(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for c in self.clients:
            if c.essid:
                out[c.essid] = out.get(c.essid, 0) + 1
        return out


def _clean(value: str | None) -> str | None:
    value = (value or "").strip()
    return None if value in ("", "--", "-") else value


def parse_aps(table: Table | None) -> dict[str, AccessPoint]:
    aps: dict[str, AccessPoint] = {}
    for row in table.dicts() if table else []:
        name = _clean(row.get("Name"))
        if not name:
            continue
        radios = []
        for i in range(3):
            channel = _clean(row.get(f"radio{i} Channel"))
            if not channel:
                continue
            util, _q = parse_value(row.get(f"radio{i} Utilization (%)"))
            noise, _q = parse_value(row.get(f"radio{i} Noise Floor (dBm)"))
            power, _q = parse_value(row.get(f"radio{i} Power (dBm)"))
            radios.append(
                Radio(
                    index=i,
                    band=band_of(channel),
                    channel=channel,
                    power_dbm=power,
                    utilization=util,
                    noise_dbm=noise,
                )
            )
        clients, _q = parse_value(row.get("Clients"))
        aps[name] = AccessPoint(
            name=name,
            ip=_clean(row.get("IP Address")),
            serial=_clean(row.get("Serial #")),
            model=_clean(row.get("Type")),
            clients=clients,
            radios=tuple(radios),
        )
    return aps


def parse_clients(table: Table | None, names: dict[str, str]) -> list[Client]:
    clients = []
    for row in table.dicts() if table else []:
        mac = (_clean(row.get("MAC Address")) or "").upper()
        if not mac:
            continue
        hostname = _clean(row.get("Name"))
        channel = _clean(row.get("Channel"))
        signal, quality = parse_value(row.get("Signal"))
        speed, _q = parse_value(row.get("Speed (mbps)"))
        clients.append(
            Client(
                mac=mac,
                name=names.get(mac) or hostname or mac,
                hostname=hostname,
                ip=_clean(row.get("IP Address")),
                os=_clean(row.get("OS")),
                essid=_clean(row.get("ESSID")),
                ap=_clean(row.get("Access Point")),
                channel=channel,
                band=band_of(channel),
                phy=_clean(row.get("Type")),
                signal=signal,
                quality=quality,
                speed_mbps=speed,
                role=_clean(row.get("Role")),
            )
        )
    return sorted(clients, key=lambda c: (c.ap or "", c.name.lower()))


def lease_names(hass: HomeAssistant) -> dict[str, str]:
    """MAC → comment DHCP lease từ routeros_ha (nếu có cài). Chỉ lấy lease có comment."""
    out: dict[str, str] = {}
    for entry in hass.config_entries.async_loaded_entries(LEASE_SOURCE_DOMAIN):
        data = getattr(getattr(entry, "runtime_data", None), "data", None)
        for mac, lease in (getattr(data, "leases", None) or {}).items():
            if getattr(lease, "commented", False) and getattr(lease, "name", None):
                out[str(mac).upper()] = lease.name
    return out


class ArubaCoordinator(DataUpdateCoordinator[WifiData]):
    def __init__(
        self,
        hass: HomeAssistant,
        api: ArubaInstantApi,
        entry: ConfigEntry,
        update_interval: int,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=timedelta(seconds=update_interval),
        )
        self.api = api
        self.cluster: str = entry.title
        self.cluster_id: str = entry.unique_id or entry.entry_id

    async def _async_update_data(self) -> WifiData:
        try:
            result = await self.api.show(CMD_APS, CMD_CLIENTS)
        except ArubaAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except ArubaApiError as err:
            raise UpdateFailed(str(err)) from err
        return WifiData(
            aps=parse_aps(result.get(CMD_APS)),
            clients=parse_clients(result.get(CMD_CLIENTS), lease_names(self.hass)),
        )
