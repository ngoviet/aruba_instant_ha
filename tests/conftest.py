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


def _data(items: dict[str, str]) -> str:
    return "".join(f'<data name="{k}" pn="true">{v}</data>' for k, v in items.items())


# --- Chi tiết từng AP (`show ap …` với ip=<AP>), hình dạng đo trên Instant 8.10 (2026-11-20), số giả.
# "espressif" (aa:..:03) đang bám AP Ngu với SNR 12 nhưng AP Khach nghe nó 30 ⇒ louder_ap.
BSSID = {MASTER: ("02:00:00:00:01:0", "02:00:00:00:01:1"), MEMBER: ("02:00:00:00:02:0", "02:00:00:00:02:1")}
AP_NAME = {MASTER: "AP Khach", MEMBER: "AP Ngu"}


def detail_show(ip: str, cmd: str, tick: int) -> str:
    b24, b5 = BSSID[ip]
    name = AP_NAME[ip]
    ch24, ch5 = ("6", "44+") if ip == MASTER else ("1", "100E")
    if cmd == "show ap bss-table":
        return _table(
            "Aruba AP BSS Table",
            ["bss", "ess", "port", "ip", "band/ht-mode/bandwidth", "ch/EIRP/max-EIRP", "type", "cur-cl", "ap name", "in-t(s)", "tot-t", "flags"],
            [
                [b24, "IoT", "?/?", ip, "2.4GHz/HT/20MHz", f"{ch24}/24.0/25.0", "ap", "1", name, "0", "2d:0h:0m:0s", ""],
                [b5, "Home", "?/?", ip, "5GHz/VHT/40MHz", f"{ch5.rstrip('+E')}/22.0/22.0", "ap", "1", name, "0", "2d:0h:0m:0s", ""],
            ],
        )
    if cmd == "show ap-env":
        return _data({"wifi0_arm_channel": ch5, "wifi0_arm_power_10x": "22.0", "wifi1_arm_channel": ch24, "wifi1_arm_power_10x": "24.0"})
    if cmd.startswith("show ap debug radio-stats"):
        idx = cmd[-1]
        resets = "9" if (ip == MEMBER and idx == "1") else "1"  # AP Ngu 2.4 GHz: 9 lần / 2 ngày
        frames, retried = 1000 + 1000 * tick, 50 + (400 * tick if ip == MEMBER else 20 * tick)
        rows = [["Channel Busy 64s", "17"], ["Tx Frames Transmitted", str(frames)], ["Tx Data Transmitted Retried", str(retried)],
                ["Total Radio Resets", resets], ["Tx Time BC/MC Data", "10"], ["Tx Time Data Transmitted", "100"]]  # fmt: skip
        return _table("RADIO Stats", ["Parameter", "Value"], rows)
    if cmd == "show ap debug client-table":
        rows = [r for r in CLIENTS if r[5] == name]
        hdr = ["MAC", "ESSID", "BSSID", "HT_State", "Tx_Pkts", "Tx_Retries", "Tx_Rate", "Rx_Rate", "Client health (C/R)", "Tx_Bytes", "Rx_Bytes"]
        out = []
        for r in rows:
            vht = "cAWvSsEeBbM" if r[0] == "iPhone" else "AWSsBbM"
            out.append([r[2], r[4], b24, vht, str(100 + 100 * tick), str(10 + 60 * tick), "58", "24", "100/90", str(1000 * (1 + tick)), str(500 * (1 + tick))])
        return _table("Client Table", hdr, out)
    if cmd == "show ap virtual-beacon-report":
        rows = [["aa:bb:cc:00:00:03", "Normal", "0", "0", "Yes" if ip == MEMBER else "No", f"{b24} (Local 1)", "12" if ip == MEMBER else "30", "0s"]]
        return _table("Virtual Beacon Table", ["Station", "CM State", "Triggered", "Succeeded", "Owner", "AP", "RSSI", "Received"], rows)
    if cmd == "show ap monitor ap-list":
        hdr = ["bssid", "essid", "band/chan/ch-width/ht-type", "encr", "curr-rssi"]
        return _table("Monitored AP Table", hdr, [["0e:00:00:00:00:01", "SetupAP", f"2.4GHz/{ch24}/20MHz/HT", "open", "48"]])
    return ""


class FakeCluster:
    """Hành vi swarm.cgi: master trả đủ AP; member trả "0 Access Point"; sid hỏng → lỗi."""

    def __init__(self) -> None:
        self.master = MASTER
        self.password = "pw"
        self.sessions: set[tuple[str, str]] = set()
        self.logins: list[str] = []
        self.logouts: list[str] = []
        self.calls: list[tuple[str, str]] = []
        self.detail_calls: list[str] = []  # ip của mỗi lượt đọc chi tiết
        self.detail_tick = 0  # tăng để bộ đếm cộng dồn lớn dần giữa hai lượt
        self.detail_down: set[str] = set()  # ip trả lỗi khi đọc chi tiết

    def show(self, host: str, cmd: str, ip: str = "127.0.0.1") -> str:
        if cmd.startswith("show ap"):
            target = self.master if ip == "127.0.0.1" else ip
            return detail_show(target, cmd, self.detail_tick)
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
        ip = q.get("ip", "127.0.0.1")
        self.calls.append((host, q.get("cmd", "")))
        if cmds[0].startswith("show ap "):
            self.detail_calls.append(ip)
            if ip in self.detail_down:
                return AiohttpClientMockResponse(
                    method, url, text="<?xml version='1.0'?><re><error>AP not reachable</error></re>"
                )
        if len(cmds) == 1:
            body = self.show(host, cmds[0], ip)
        else:
            body = "".join(
                f'<output command="{c}">{self.show(host, c, ip)}</output>' for c in cmds
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
