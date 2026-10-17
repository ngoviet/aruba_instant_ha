"""API, config flow, setup và entity — HTTP mô phỏng bằng FakeCluster (conftest)."""

from __future__ import annotations

import pytest
from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.aruba_instant_ha import parse_hosts
from custom_components.aruba_instant_ha.api import (
    ArubaSessionExpired,
    parse_data,
    parse_show,
)
from custom_components.aruba_instant_ha.const import DOMAIN
from custom_components.aruba_instant_ha.coordinator import band_of, parse_value

from .conftest import MASTER, MEMBER, USER_INPUT


def _entry() -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN, title="NhaTest", unique_id="nhatest", data=dict(USER_INPUT)
    )


async def _setup(hass: HomeAssistant) -> MockConfigEntry:
    entry = _entry()
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


def _eid(hass: HomeAssistant, unique_id: str) -> str:
    eid = er.async_get(hass).async_get_entity_id("sensor", DOMAIN, unique_id)
    assert eid, f"thiếu entity {unique_id}"
    return eid


# --- hàm thuần ------------------------------------------------------------


@pytest.mark.parametrize(
    "text,expected",
    [
        ("45(good)", (45, "good")),
        ("-94(good)", (-94, "good")),
        ("12(poor)", (12, "poor")),
        ("866", (866, None)),
        ("--", (None, None)),
        (None, (None, None)),
    ],
)
def test_parse_value(text, expected):
    assert parse_value(text) == expected


@pytest.mark.parametrize(
    "channel,band",
    [
        ("6", "2.4"),
        ("1", "2.4"),
        ("44+", "5"),
        ("100E", "5"),
        ("52E", "5"),
        ("-", None),
    ],
)
def test_band_of(channel, band):
    assert band_of(channel) == band


def test_parse_hosts():
    assert parse_hosts(" 1.1.1.1, https://2.2.2.2:4343/ ;1.1.1.1") == [
        "1.1.1.1",
        "2.2.2.2",
    ]
    assert parse_hosts("") == []


def test_parse_show_single_multi_and_errors():
    single = "<re><t tn='X'><th><h>A</h></th><r><c>1</c></r></t></re>"
    assert parse_show(single, ["show x"])["show x"].dicts() == [{"A": "1"}]
    multi = (
        "<re><output command='show a'><t tn='A'><th><h>K</h></th><r><c>v</c></r></t></output>"
        "<output command='show b'><t tn='B'><th><h>K</h></th></t></output></re>"
    )
    out = parse_show(multi, ["show a", "show b"])
    assert out["show a"].dicts() == [{"K": "v"}] and out["show b"].rows == []
    with pytest.raises(ArubaSessionExpired):
        parse_show("<re><error>Invalid Session ID</error></re>", ["show a"])
    assert parse_data("<re><data name='Name'>Nha</data></re>") == {"Name": "Nha"}


# --- config flow ----------------------------------------------------------


async def test_config_flow_finds_master(hass: HomeAssistant, cluster):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], dict(USER_INPUT)
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "NhaTest"
    assert result["result"].unique_id == "nhatest"
    # thử member trước (đăng nhập được nhưng 0 AP) rồi mới tới master; phiên đều được trả
    assert cluster.logins[:2] == [MEMBER, MASTER]
    assert MEMBER in cluster.logouts and MASTER in cluster.logouts
    assert not cluster.sessions


async def test_config_flow_invalid_auth(hass: HomeAssistant, cluster):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {**USER_INPUT, "password": "sai"}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_auth"}


async def test_config_flow_no_master(hass: HomeAssistant, cluster):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {**USER_INPUT, "hosts": MEMBER}
    )
    assert result["errors"] == {"base": "cannot_connect"}


# --- setup + entity -------------------------------------------------------


async def test_setup_creates_entities(hass: HomeAssistant, cluster):
    entry = await _setup(hass)
    assert entry.state is ConfigEntryState.LOADED

    total = hass.states.get(_eid(hass, "nhatest_wifi_clients"))
    assert total.state == "3"
    clients = total.attributes["clients"]
    assert len(clients) == 3
    iphone = next(c for c in clients if c["hostname"] == "iPhone")
    assert iphone["band"] == "5" and iphone["essid"] == "Home"
    assert iphone["signal"] == 41 and iphone["quality"] == "good"
    assert iphone["speed_mbps"] == 866 and iphone["mac"] == "AA:BB:CC:00:00:02"
    assert total.attributes["ssids"] == {"IoT": 2, "Home": 1}
    assert total.attributes["aps"]["AP Khach"]["radios"][1]["channel"] == "6"
    assert total.attributes["conductor"] == MASTER

    assert hass.states.get(_eid(hass, "SER1_clients")).state == "2"
    util24 = hass.states.get(_eid(hass, "SER1_utilization_2_4"))
    assert util24.state == "26" and util24.attributes["channel"] == "6"
    assert hass.states.get(_eid(hass, "SER2_utilization_5")).state == "0"


async def test_session_expiry_relogs_in(hass: HomeAssistant, cluster):
    entry = await _setup(hass)
    cluster.sessions.clear()  # AP khởi động lại / phiên hết hạn
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    assert entry.runtime_data.last_update_success
    assert cluster.sessions  # đã đăng nhập lại


async def test_master_failover(hass: HomeAssistant, cluster):
    entry = await _setup(hass)
    cluster.master = MEMBER  # cụm bầu lại master
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    assert entry.runtime_data.api.host == MEMBER
    total = hass.states.get(_eid(hass, "nhatest_wifi_clients"))
    assert total.attributes["conductor"] == MEMBER


async def test_unload_logs_out(hass: HomeAssistant, cluster):
    entry = await _setup(hass)
    assert await hass.config_entries.async_unload(entry.entry_id)
    assert not cluster.sessions


async def test_auth_failure_starts_reauth(hass: HomeAssistant, cluster):
    cluster.password = "doi-roi"
    entry = _entry()
    entry.add_to_hass(hass)
    assert not await hass.config_entries.async_setup(entry.entry_id)
    assert entry.state is ConfigEntryState.SETUP_ERROR
    flows = hass.config_entries.flow.async_progress()
    assert any(f["context"]["source"] == "reauth" for f in flows)


async def test_options_flow(hass: HomeAssistant, cluster):
    entry = await _setup(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"scan_interval": 120}
    )
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options["scan_interval"] == 120
    assert entry.state is ConfigEntryState.LOADED
