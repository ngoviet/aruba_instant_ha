"""Chi tiết 5 phút: đọc theo từng AP (ip=), tính theo chênh lệch, lỗi một AP không làm hỏng cập nhật."""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.aruba_instant_ha.const import DOMAIN
from custom_components.aruba_instant_ha.detail import (
    DETAIL_COMMANDS,
    DETAIL_INTERVAL,
    parse_outputs,
    uptime_seconds,
)

from .conftest import MASTER, MEMBER, USER_INPUT


async def _setup(hass: HomeAssistant) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN, title="NhaTest", unique_id="nhatest", data=dict(USER_INPUT)
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


def _attrs(hass: HomeAssistant) -> dict:
    eid = er.async_get(hass).async_get_entity_id(
        "sensor", DOMAIN, "nhatest_wifi_clients"
    )
    return hass.states.get(eid).attributes


async def _next_detail(hass: HomeAssistant, entry, cluster) -> None:
    coord = entry.runtime_data
    coord._detail.at -= DETAIL_INTERVAL + 1
    cluster.detail_tick += 1
    await coord.async_refresh()
    await hass.async_block_till_done()


def test_parse_outputs_and_uptime():
    xml = '<re><output command="show ap-env"><data name="wifi1_arm_channel">6</data></output></re>'
    out = parse_outputs(xml, ["show ap-env", "show ap bss-table"])
    assert out["show ap-env"].value("wifi1_arm_channel") == "6"
    assert "show ap bss-table" not in out  # AP bỏ qua lệnh ⇒ vắng, không đoán
    assert uptime_seconds("8d:4h:42m:51s") == 8 * 86400 + 4 * 3600 + 42 * 60 + 51
    assert parse_outputs("not xml", ["show ap-env"]) == {}


async def test_detail_attributes_are_additive(hass: HomeAssistant, cluster):
    await _setup(hass)
    # Mỗi AP một lượt đọc chi tiết, gửi tới đúng IP AP, chỉ lệnh show.
    assert sorted(cluster.detail_calls) == sorted([MASTER, MEMBER])
    assert all(
        cmd.split("\n") == list(DETAIL_COMMANDS)
        for host, cmd in cluster.calls
        if cmd.startswith("show ap ")
    )

    a = _attrs(hass)
    # Khoá cũ giữ nguyên.
    assert a["aps"]["AP Khach"]["radios"][1]["channel"] == "6"
    esp = next(c for c in a["clients"] if c["hostname"] == "espressif")
    assert esp["signal"] == 12
    # Khoá mới.
    assert esp["louder_ap"] == "AP Khach" and esp["louder_gain"] == 18
    assert esp["retry_pct"] == round(10 / 110 * 100, 1)
    assert "retry_5m" not in esp  # lần đầu chưa có mốc so sánh
    assert esp["tx_rate"] == 58 and esp["health"] == "100/90"
    r24 = next(r for r in a["aps"]["AP Ngu"]["radios"] if r["band"] == "2.4")
    assert r24["busy_64s"] == 17 and r24["pinned"] is True and r24["set_power"] == 24.0
    assert r24["resets_per_day"] == 4.5
    assert a["aps"]["AP Ngu"]["uptime_s"] == 2 * 86400
    codes = [x["code"] for x in a["alerts"]]
    assert "radio_resets" in codes and "open_network" in codes and "louder_ap" in codes
    assert a["detail_updated"]


async def test_detail_runs_every_5_minutes_and_uses_deltas(
    hass: HomeAssistant, cluster
):
    entry = await _setup(hass)
    n = len(cluster.detail_calls)
    await entry.runtime_data.async_refresh()  # 60 s sau: chưa tới hạn chi tiết
    await hass.async_block_till_done()
    assert len(cluster.detail_calls) == n

    await _next_detail(hass, entry, cluster)
    assert len(cluster.detail_calls) == n + 2
    a = _attrs(hass)
    esp = next(c for c in a["clients"] if c["hostname"] == "espressif")
    assert esp["retry_5m"] == round(
        60 / 160 * 100, 1
    )  # chênh lệch: 60 lần thử lại / 160 lần phát
    assert esp["tx_kbps"] > 0
    r24 = next(r for r in a["aps"]["AP Ngu"]["radios"] if r["band"] == "2.4")
    assert r24["retry_5m"] == 40.0
    assert any(x["code"] == "radio_retry" and x["ap"] == "AP Ngu" for x in a["alerts"])


async def test_one_ap_failing_keeps_old_detail_and_update_succeeds(
    hass: HomeAssistant, cluster
):
    entry = await _setup(hass)
    cluster.detail_down.add(MEMBER)
    await _next_detail(hass, entry, cluster)
    assert entry.runtime_data.last_update_success
    a = _attrs(hass)
    assert a["aps"]["AP Ngu"]["stale"] is True
    assert a["aps"]["AP Ngu"]["uptime_s"] == 2 * 86400  # số cũ còn đó
    assert {"code": "detail_failed", "ap": "AP Ngu"} in a["alerts"]
    assert a["clients"]  # danh sách chính vẫn đủ
