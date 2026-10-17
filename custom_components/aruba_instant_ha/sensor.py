"""Sensor: tổng thiết bị Wi-Fi (kèm danh sách chi tiết) + số client / tải kênh từng AP."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.const import PERCENTAGE
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import ArubaConfigEntry
from .const import DOMAIN, MANUFACTURER
from .coordinator import ArubaCoordinator

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ArubaConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    async_add_entities([WifiClientsSensor(coordinator)])

    known: set[str] = set()

    @callback
    def _add_aps() -> None:
        new = [n for n in coordinator.data.aps if n not in known]
        known.update(new)
        entities: list[SensorEntity] = []
        for name in new:
            entities.append(ApClientsSensor(coordinator, name))
            entities.extend(
                ApUtilizationSensor(coordinator, name, band) for band in ("2.4", "5")
            )
        if entities:
            async_add_entities(entities)

    _add_aps()
    entry.async_on_unload(coordinator.async_add_listener(_add_aps))


def _hub_device(coordinator: ArubaCoordinator) -> DeviceInfo:
    return DeviceInfo(
        identifiers={(DOMAIN, coordinator.cluster_id)},
        name="Aruba Instant",
        manufacturer=MANUFACTURER,
        model=f"Instant cluster {coordinator.cluster}",
        configuration_url=coordinator.api.web_url(),
    )


class WifiClientsSensor(CoordinatorEntity[ArubaCoordinator], SensorEntity):
    """State = tổng số thiết bị Wi-Fi. Thuộc tính `clients` = danh sách chi tiết cho card.

    Danh sách đổi mỗi lần đọc (RSSI, tốc độ) nên không ghi vào recorder.
    """

    _attr_has_entity_name = True
    _attr_translation_key = "wifi_clients"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:wifi"
    _unrecorded_attributes = frozenset({"clients", "ssids", "aps"})

    def __init__(self, coordinator: ArubaCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.cluster_id}_wifi_clients"
        self._attr_device_info = _hub_device(coordinator)

    @property
    def native_value(self) -> int:
        return len(self.coordinator.data.clients)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        data = self.coordinator.data
        return {
            "clients": [c.as_dict() for c in data.clients],
            "ssids": data.ssids(),
            "aps": {
                ap.name: {
                    "ip": ap.ip,
                    "clients": ap.clients,
                    "radios": [
                        {
                            "band": r.band,
                            "channel": r.channel,
                            "power_dbm": r.power_dbm,
                            "utilization": r.utilization,
                            "noise_dbm": r.noise_dbm,
                        }
                        for r in ap.radios
                    ],
                }
                for ap in data.aps.values()
            },
            "conductor": self.coordinator.api.host,
        }


class _ApEntity(CoordinatorEntity[ArubaCoordinator], SensorEntity):
    _attr_has_entity_name = True

    def __init__(self, coordinator: ArubaCoordinator, ap_name: str, key: str) -> None:
        super().__init__(coordinator)
        self._ap = ap_name
        ap = coordinator.data.aps[ap_name]
        ident = ap.serial or f"{coordinator.cluster_id}_{ap_name}"
        self._attr_unique_id = f"{ident}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, ident)},
            name=ap_name,
            manufacturer=MANUFACTURER,
            model=f"IAP-{ap.model.split('(')[0]}" if ap.model else None,
            serial_number=ap.serial,
            via_device=(DOMAIN, coordinator.cluster_id),
            configuration_url=coordinator.api.web_url(ap.ip),
        )

    @property
    def available(self) -> bool:
        return super().available and self._ap in self.coordinator.data.aps


class ApClientsSensor(_ApEntity):
    _attr_translation_key = "ap_clients"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:access-point"

    def __init__(self, coordinator: ArubaCoordinator, ap_name: str) -> None:
        super().__init__(coordinator, ap_name, "clients")

    @property
    def native_value(self) -> int | None:
        ap = self.coordinator.data.aps.get(self._ap)
        return ap.clients if ap else None


class ApUtilizationSensor(_ApEntity):
    """% thời gian kênh bận của radio 2,4 / 5 GHz. Thuộc tính: kênh, công suất, noise."""

    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:chart-donut"

    def __init__(self, coordinator: ArubaCoordinator, ap_name: str, band: str) -> None:
        key = "utilization_2_4" if band == "2.4" else "utilization_5"
        super().__init__(coordinator, ap_name, key)
        self._band = band
        self._attr_translation_key = key

    def _radio(self):
        ap = self.coordinator.data.aps.get(self._ap)
        return ap.radio(self._band) if ap else None

    @property
    def available(self) -> bool:
        return super().available and self._radio() is not None

    @property
    def native_value(self) -> int | None:
        radio = self._radio()
        return radio.utilization if radio else None

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        radio = self._radio()
        if radio is None:
            return None
        return {
            "channel": radio.channel,
            "power_dbm": radio.power_dbm,
            "noise_dbm": radio.noise_dbm,
        }
