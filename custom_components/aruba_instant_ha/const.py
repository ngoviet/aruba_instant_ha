"""Hằng số cho Aruba Instant (đo trên cụm 3 × IAP-335, firmware Instant 8.x, 2026-10-18)."""

from __future__ import annotations

DOMAIN = "aruba_instant_ha"
MANUFACTURER = "Aruba"

CONF_HOSTS = "hosts"
CONF_VERIFY_SSL = "verify_ssl"
CONF_SCAN_INTERVAL = "scan_interval"

DEFAULT_PORT = 4343
DEFAULT_SCAN_INTERVAL = 60
MIN_SCAN_INTERVAL = 30
MAX_SCAN_INTERVAL = 600
REQUEST_TIMEOUT = 20

CMD_APS = "show aps"
CMD_CLIENTS = "show clients"
CMD_SUMMARY = "show summary"

# Integration của router (MikroTik) có bảng DHCP lease kèm comment → tên thiết bị dễ đọc
# thay cho hostname Wi-Fi kiểu "wlan0", "espressif". Không bắt buộc cài.
LEASE_SOURCE_DOMAIN = "routeros_ha"
