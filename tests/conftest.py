"""Fixture chung: cụm Aruba Instant giả lập đúng hình dạng XML của swarm.cgi (đo trên 3 × IAP-335,
firmware Instant 8.x, 2026-10-18). Tên, IP, MAC, serial là giả.
"""

from __future__ import annotations

import sys
from urllib.parse import parse_qs

import pytest
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMockResponse,
)
from yarl import URL

pytest_plugins = "pytest_homeassistant_custom_component"

if sys.platform == "win32":
    import pytest_socket

    pytest_socket.disable_socket = lambda *args, **kwargs: None

MASTER = "192.168.88.51"
MEMBER = "192.168.88.52"
USER_INPUT = {
    "hosts": f"{MEMBER}, {MASTER}",
    "port": 4343,
    "verify_ssl": False,
    "username": "admin",
    "password": "pw",
}
SID = "c0ffee"

AP_HEADER = [
    "Name", "IP Address", "Mode", "Clients", "Type", "Serial #",
    "radio0 Channel", "radio0 Power (dBm)", "radio0 Utilization (%)", "radio0 Noise Floor (dBm)",
    "radio1 Channel", "radio1 Power (dBm)", "radio1 Utilization (%)", "radio1 Noise Floor (dBm)",
    "radio2 Channel", "radio2 Power (dBm)", "radio2 Utilization (%)", "radio2 Noise Floor (dBm)",
]  # fmt: skip
APS = [
    ["AP Khach", MASTER, "access", "2", "335(indoor)", "SER1", "44+", "22", "3(good)", "-94(good)",
     "6", "25", "26(good)", "-96(good)", "-", "-", "-", "-"],
    ["AP Ngu", MEMBER, "access", "1", "335(indoor)", "SER2", "100E", "27", "0(good)", "-91(good)",
     "1", "24", "21(good)", "-96(good)", "-", "-", "-", "-"],
]  # fmt: skip
CLIENT_HEADER = [
    "Name", "IP Address", "MAC Address", "OS", "ESSID", "Access Point", "Channel", "Type",
    "Role", "IPv6 Address", "Signal", "Speed (mbps)",
]  # fmt: skip
CLIENTS = [
    ["wlan0", "192.168.20.69", "aa:bb:cc:00:00:01", "NOFP", "IoT", "AP Khach", "6", "GN", "r", "--", "39(good)", "58(good)"],
    ["iPhone", "192.168.10.27", "aa:bb:cc:00:00:02", "iOS", "Home", "AP Khach", "44+", "AC", "r", "--", "41(good)", "866(good)"],
    ["espressif", "192.168.20.16", "aa:bb:cc:00:00:03", "NOFP", "IoT", "AP Ngu", "1", "GN", "r", "--", "12(poor)", "6(poor)"],
]  # fmt: skip


def _table(name: str, header: list[str], rows: list[list[str]]) -> str:
    th = "".join(f"<h>{h}</h>" for h in header)
    body = "".join("<r>" + "".join(f"<c>{c}</c>" for c in r) + "</r>" for r in rows)
    return f'<t tn="{name}" nc="{len(header)}"><th>{th}</th>{body}</t>'


class FakeCluster:
    """Hành vi swarm.cgi: master trả đủ AP; member trả "0 Access Point"; sid hỏng → lỗi."""

    def __init__(self) -> None:
        self.master = MASTER
        self.password = "pw"
        self.sessions: set[tuple[str, str]] = set()
        self.logins: list[str] = []
        self.logouts: list[str] = []
        self.calls: list[tuple[str, str]] = []

    def show(self, host: str, cmd: str) -> str:
        if cmd == "show aps":
            rows = APS if host == self.master else []
            return _table(f"{len(rows)} Access Points", AP_HEADER, rows)
        if cmd == "show clients":
            rows = (
                CLIENTS
                if host == self.master
                else [r for r in CLIENTS if r[5] == "AP Ngu"]
            )
            return _table("Client List", CLIENT_HEADER, rows)
        if cmd == "show summary":
            return '<data name="Name">NhaTest</data><data name="IP Address">x</data>'
        return ""

    async def handle(self, method: str, url: URL, data):
        host = url.host
        if method.upper() == "POST":
            form = data or {}
            if form.get("opcode") == "login":
                self.logins.append(host)
                if form.get("passwd") != self.password:
                    return AiohttpClientMockResponse(
                        method, url, text="<?xml version='1.0'?><re></re>"
                    )
                self.sessions.add((host, SID))
                return AiohttpClientMockResponse(
                    method,
                    url,
                    text=f'<?xml version=\'1.0\'?><re><data name="sid" pn="true">{SID}</data>'
                    '<data name="type" pn="true">Admin</data></re>',
                )
            if form.get("opcode") == "logout":
                self.logouts.append(host)
                self.sessions.discard((host, form.get("sid")))
                return AiohttpClientMockResponse(
                    method, url, text="<?xml version='1.0'?><re></re>"
                )
        q = {k: v[0] for k, v in parse_qs(url.query_string).items()}
        if (host, q.get("sid")) not in self.sessions:
            return AiohttpClientMockResponse(
                method,
                url,
                text="<?xml version='1.0'?><re><error>Invalid Session ID</error></re>",
            )
        cmds = q.get("cmd", "").split("\n")
        self.calls.append((host, q.get("cmd", "")))
        if len(cmds) == 1:
            body = self.show(host, cmds[0])
        else:
            body = "".join(
                f'<output command="{c}">{self.show(host, c)}</output>' for c in cmds
            )
        return AiohttpClientMockResponse(
            method, url, text=f"<?xml version='1.0'?><re>{body}</re>"
        )


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    yield


@pytest.fixture
def cluster(aioclient_mock) -> FakeCluster:
    fake = FakeCluster()
    for host in (MASTER, MEMBER):
        url = f"https://{host}:4343/swarm.cgi"
        aioclient_mock.post(url, side_effect=fake.handle)
        aioclient_mock.get(url, side_effect=fake.handle)
    return fake
