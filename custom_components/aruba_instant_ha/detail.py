"""Chi tiết từng AP và từng thiết bị (đọc mỗi 5 phút, không phụ thuộc Home Assistant để test thuần).

Nguồn: các lệnh `show ap …` gửi tới từng AP qua master bằng tham số `ip=<IP AP>` (đúng cách giao diện
web Instant làm). Đo thật trên cụm 3 × IAP-335, Instant 8.10.0.23 (2026-11-20, công cụ aruba-axi):

- `show ap debug client-table`: Tx_Pkts / Tx_Retries / Tx_Bytes / Rx_Bytes CỘNG DỒN từ lúc client nối;
  Tx_Retries đếm số LẦN thử lại (có thể > Tx_Pkts) ⇒ tỉ lệ = retries / (pkts + retries).
  `Client health (C/R)` dạng "100/93" (chưa rõ nghĩa C/R ⇒ chỉ hiển thị nguyên văn).
  HT_State có cờ VHT (C E V c e v) ⇒ máy có 5 GHz.
- `show ap debug radio-stats <0|1>`: bộ đếm từ lúc radio khởi động; `Channel Busy 64s` là số đo tức thời.
  AP-335: radio 0 / wifi0 = 5 GHz, radio 1 / wifi1 = 2.4 GHz.
- `show ap virtual-beacon-report`: RSSI mỗi AP nghe từng client (cột AP = BSSID của radio nghe).
- `show ap bss-table`: BSSID → AP + băng; cột tot-t = uptime AP.
- `show ap-env`: wifiN_arm_channel / wifiN_arm_power_10x = kênh, công suất do quản trị ghim.
- `show ap monitor ap-list`: AP hàng xóm (essid, kênh, RSSI dương = −dBm, mã hoá).

Bộ đếm cộng dồn ⇒ tỉ lệ "5 phút gần nhất" tính từ CHÊNH LỆCH giữa hai lần đọc; lần đầu (chưa có mốc)
chỉ có số "từ lúc nối".
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Any

DETAIL_INTERVAL = 300
DETAIL_COMMANDS: tuple[str, ...] = (
    "show ap debug client-table",
    "show ap virtual-beacon-report",
    "show ap debug radio-stats 0",
    "show ap debug radio-stats 1",
    "show ap bss-table",
    "show ap-env",
    "show ap monitor ap-list",
)

# Ngưỡng — trùng `aruba-axi plan rebalance` / audit để hai công cụ nói cùng một điều.
LOUDER_MIN_GAIN = 10  # dB: AP khác nghe client mạnh hơn ít nhất chừng này
LOUDER_MAX_SNR = 25  # chỉ xét client đang yếu
RADIO_RETRY_ALERT = 15  # % retry radio trong 5 phút
RESETS_PER_DAY_ALERT = 2
OPEN_NET_RSSI = -65  # dBm: mạng mở lạ mạnh hơn mức này
MIN_DELTA_TX = 20  # gói: ít hơn thì không tính tỉ lệ 5 phút (nhiễu)

_IDX_BAND = {0: "5", 1: "2.4"}


# ---------------------------------------------------------------- đọc XML


@dataclass(frozen=True)
class Output:
    tables: list[tuple[str, list[str], list[list[str]]]]
    data: list[tuple[str, str]]

    def table(self, name_re: str | None = None) -> list[dict[str, str]]:
        for name, header, rows in self.tables:
            if name_re is None or re.search(name_re, name):
                return [dict(zip(header, r, strict=False)) for r in rows]
        return []

    def value(self, name: str) -> str | None:
        want = name.strip().lower()
        for n, v in self.data:
            if n.strip().lower() == want:
                return v.strip()
        return None


def _parse_block(node: ET.Element) -> Output:
    tables = []
    for t in node.findall("t"):
        th = t.find("th")
        header = [(h.text or "").strip() for h in th] if th is not None else []
        rows = [[(c.text or "").strip() for c in r] for r in t.findall("r")]
        tables.append(((t.get("tn") or "").strip(), header, rows))
    data = [((d.get("name") or ""), (d.text or "")) for d in node.findall("data")]
    return Output(tables=tables, data=data)


def parse_outputs(
    text: str, commands: list[str] | tuple[str, ...]
) -> dict[str, Output]:
    """XML nhiều lệnh → {lệnh: Output}. Một lệnh ⇒ AP không bọc `<output>`. Lệnh AP bỏ qua ⇒ vắng."""
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return {}
    outs = root.findall("output")
    if outs:
        return {(o.get("command") or "").strip(): _parse_block(o) for o in outs}
    if len(commands) == 1:
        block = _parse_block(root)
        if block.tables or any(v.strip() for _n, v in block.data):
            return {commands[0]: block}
    return {}


# ---------------------------------------------------------------- tiện ích

_NUM = re.compile(r"-?\d+(?:\.\d+)?")


def num(text: str | None) -> float | None:
    m = _NUM.search(text or "")
    return float(m.group(0)) if m else None


def pct(part: float | None, whole: float | None) -> float | None:
    if part is None or whole is None or whole <= 0:
        return None
    return round(part / whole * 100, 1)


def uptime_seconds(text: str | None) -> int | None:
    """ "8d:4h:42m:51s" → giây."""
    if not text:
        return None
    total = 0
    for value, unit in re.findall(r"(\d+)([dhms])", text):
        total += int(value) * {"d": 86400, "h": 3600, "m": 60, "s": 1}[unit]
    return total or None


def band_of_channel(ch: float | None) -> str | None:
    if ch is None:
        return None
    return "2.4" if ch <= 14 else "5"


# ---------------------------------------------------------------- trạng thái


@dataclass
class Counters:
    """Bộ đếm cộng dồn đọc lần trước (để tính chênh lệch)."""

    at: float
    client: dict[str, tuple[float, float, float, float]] = field(
        default_factory=dict
    )  # mac → pkts, retries, txB, rxB
    radio: dict[tuple[str, str], tuple[float, float]] = field(
        default_factory=dict
    )  # (ap, band) → frames, retried


@dataclass
class Detail:
    at: float
    clients: dict[str, dict[str, Any]]
    aps: dict[str, dict[str, Any]]
    alerts: list[dict[str, Any]]
    counters: Counters
    failed: list[str]


def _client_rows(per_ap: dict[str, dict[str, Output]]) -> dict[str, dict[str, str]]:
    out: dict[str, dict[str, str]] = {}
    for outs in per_ap.values():
        for row in outs.get("show ap debug client-table", Output([], [])).table(
            "Client"
        ):
            mac = (row.get("MAC") or "").strip().upper()
            if mac:
                out[mac] = row
    return out


def compute(
    per_ap: dict[str, dict[str, Output]],
    clients: list[dict[str, Any]],
    prev: Detail | None,
    now: float,
    failed: list[str] | None = None,
) -> Detail:
    """per_ap: {tên AP: {lệnh: Output}}; clients: danh sách cơ bản (mac viết hoa, ap, band, signal, essid)."""
    failed = list(failed or [])
    old = prev.counters if prev else None
    counters = Counters(at=now)

    # BSSID → (AP, băng) từ bss-table của mọi AP; uptime AP.
    bss: dict[str, tuple[str, str]] = {}
    bss_channel: dict[tuple[str, str], float] = {}
    uptime: dict[str, int | None] = {}
    for ap, outs in per_ap.items():
        rows = outs.get("show ap bss-table", Output([], [])).table()
        for b in rows:
            band = "2.4" if "2.4" in (b.get("band/ht-mode/bandwidth") or "") else "5"
            bss[(b.get("bss") or "").lower()] = (ap, band)
            if (ch := num((b.get("ch/EIRP/max-EIRP") or "").split("/")[0])) is not None:
                bss_channel[(ap, band)] = ch
        uptime[ap] = uptime_seconds(rows[0].get("tot-t")) if rows else None

    # ---- client
    rows = _client_rows(per_ap)
    dual_ssids = {
        c.get("essid") for c in clients if c.get("band") == "5" and c.get("essid")
    }
    vbr: dict[str, dict[tuple[str, str], float]] = {}
    for outs in per_ap.values():
        for v in outs.get("show ap virtual-beacon-report", Output([], [])).table(
            "Virtual Beacon"
        ):
            mac = (v.get("Station") or "").strip().upper()
            info = bss.get((v.get("AP") or "").split(" ")[0].lower())
            rssi = num(v.get("RSSI"))
            if not mac or not info or rssi is None:
                continue
            key = (info[0], info[1])
            vbr.setdefault(mac, {})[key] = max(rssi, vbr.get(mac, {}).get(key, -1e9))

    out_clients: dict[str, dict[str, Any]] = {}
    for c in clients:
        mac = str(c.get("mac") or "").upper()
        row = rows.get(mac)
        d: dict[str, Any] = {}
        if row:
            pkts, retries = num(row.get("Tx_Pkts")), num(row.get("Tx_Retries"))
            txb, rxb = num(row.get("Tx_Bytes")), num(row.get("Rx_Bytes"))
            if pkts is not None and retries is not None:
                d["retry_pct"] = pct(retries, pkts + retries)
                counters.client[mac] = (pkts, retries, txb or 0, rxb or 0)
                before = old.client.get(mac) if old else None
                # Bộ đếm tụt ⇒ client đã nối lại: không có chênh lệch hợp lệ.
                if before and pkts >= before[0] and retries >= before[1]:
                    dp, dr = pkts - before[0], retries - before[1]
                    if dp + dr >= MIN_DELTA_TX:
                        d["retry_5m"] = pct(dr, dp + dr)
                    dt = now - old.at if old else 0
                    if (
                        dt > 0
                        and txb is not None
                        and rxb is not None
                        and txb >= before[2]
                        and rxb >= before[3]
                    ):
                        d["tx_kbps"] = round((txb - before[2]) * 8 / dt / 1000, 1)
                        d["rx_kbps"] = round((rxb - before[3]) * 8 / dt / 1000, 1)
            for key, col in (("tx_rate", "Tx_Rate"), ("rx_rate", "Rx_Rate")):
                if (v := num(row.get(col))) is not None:
                    d[key] = int(v)
            if (h := (row.get("Client health (C/R)") or "").strip()) and h not in (
                "-",
                "--",
            ):
                d["health"] = h
            vht = bool(re.search(r"[CEVcev]", row.get("HT_State") or ""))
            if c.get("band") == "2.4" and vht and c.get("essid") in dual_ssids:
                d["stuck_24"] = True
        # AP khác nghe mạnh hơn (cùng băng, client đang yếu) — "nghe to hơn", KHÔNG phải nơi nó sẽ tới.
        heard = vbr.get(mac, {})
        band = c.get("band")
        cur = heard.get((str(c.get("ap") or ""), str(band)))
        if cur is None and c.get("signal") is not None:
            cur = float(c["signal"])
        others = [
            (ap, r) for (ap, b), r in heard.items() if b == band and ap != c.get("ap")
        ]
        if cur is not None and cur < LOUDER_MAX_SNR and others:
            best_ap, best = max(others, key=lambda x: x[1])
            if best - cur >= LOUDER_MIN_GAIN:
                d["louder_ap"] = best_ap
                d["louder_gain"] = int(best - cur)
        if d:
            out_clients[mac] = d

    # ---- AP + radio
    out_aps: dict[str, dict[str, Any]] = {}
    alerts: list[dict[str, Any]] = []
    open_seen: dict[str, dict[str, Any]] = {}
    for ap, outs in per_ap.items():
        env = outs.get("show ap-env")
        neighbors = outs.get("show ap monitor ap-list", Output([], [])).table(
            "Monitored"
        )
        radios: dict[str, dict[str, Any]] = {}
        for idx, band in _IDX_BAND.items():
            st_rows = outs.get(
                f"show ap debug radio-stats {idx}", Output([], [])
            ).table("^RADIO Stats")
            stats = {
                (r.get("Parameter") or "").strip(): (r.get("Value") or "").strip()
                for r in st_rows
            }
            r: dict[str, Any] = {}
            if stats:
                busy = num(stats.get("Channel Busy 64s"))
                frames, retried = (
                    num(stats.get("Tx Frames Transmitted")),
                    num(stats.get("Tx Data Transmitted Retried")),
                )
                resets = num(stats.get("Total Radio Resets"))
                if busy is not None:
                    r["busy_64s"] = int(busy)
                if frames is not None and retried is not None:
                    r["retry_pct"] = pct(retried, frames)
                    counters.radio[(ap, band)] = (frames, retried)
                    before = old.radio.get((ap, band)) if old else None
                    if (
                        before
                        and frames >= before[0]
                        and retried >= before[1]
                        and frames - before[0] >= MIN_DELTA_TX
                    ):
                        r["retry_5m"] = pct(retried - before[1], frames - before[0])
                if resets is not None:
                    r["resets"] = int(resets)
                    up = uptime.get(ap)
                    if up:
                        r["resets_per_day"] = round(resets / (up / 86400), 1)
                bcmc = pct(
                    num(stats.get("Tx Time BC/MC Data")),
                    num(stats.get("Tx Time Data Transmitted")),
                )
                if bcmc is not None:
                    r["bcmc_pct"] = bcmc
            if env is not None:
                ch = env.value(f"wifi{idx}_arm_channel")
                pinned = bool(ch) and ch != "0"
                r["pinned"] = pinned
                if pinned:
                    r["set_channel"] = ch
                    if (p := num(env.value(f"wifi{idx}_arm_power_10x"))) is not None:
                        r["set_power"] = p
            # Hàng xóm cùng kênh chính (không tính BSSID của chính cụm).
            # Kênh đang phát: ghim trong ap-env, không thì kênh BSS thật (radio do ARM quản).
            cur_ch = (
                num(r.get("set_channel"))
                if r.get("set_channel")
                else bss_channel.get((ap, band))
            )
            foreign = []
            for n in neighbors:
                raw_b = n.get("bssid") or ""
                bssid = re.sub(r"\(.*\)$", "", raw_b).lower()
                if "(+)" in raw_b or bssid in bss:
                    continue
                parts = (n.get("band/chan/ch-width/ht-type") or "").split("/")
                n_ch = num(parts[1]) if len(parts) > 1 else None
                if band_of_channel(n_ch) != band:
                    continue
                rssi = num(n.get("curr-rssi"))
                dbm = -abs(rssi) if rssi is not None else None
                if cur_ch is not None and n_ch == cur_ch:
                    foreign.append(dbm)
                enc = (n.get("encr") or "").lower()
                if enc in ("open", "none") and dbm is not None and dbm > OPEN_NET_RSSI:
                    ssid = n.get("essid") or "(ẩn)"
                    if bssid not in open_seen or dbm > open_seen[bssid]["rssi"]:
                        open_seen[bssid] = {
                            "ssid": ssid,
                            "rssi": int(dbm),
                            "channel": int(n_ch or 0),
                            "ap": ap,
                        }
            if cur_ch is not None:
                r["cochannel"] = len(foreign)
                loud = [x for x in foreign if x is not None]
                if loud:
                    r["cochannel_loudest"] = int(max(loud))
            if r:
                radios[band] = r
            if (r.get("resets_per_day") or 0) > RESETS_PER_DAY_ALERT:
                alerts.append(
                    {
                        "code": "radio_resets",
                        "ap": ap,
                        "band": band,
                        "value": r["resets_per_day"],
                    }
                )
            if (r.get("retry_5m") or 0) > RADIO_RETRY_ALERT:
                alerts.append(
                    {
                        "code": "radio_retry",
                        "ap": ap,
                        "band": band,
                        "value": r["retry_5m"],
                    }
                )
        a: dict[str, Any] = {"radios": radios}
        if uptime.get(ap):
            a["uptime_s"] = uptime[ap]
        out_aps[ap] = a

    for o in sorted(open_seen.values(), key=lambda x: -x["rssi"]):
        alerts.append(
            {
                "code": "open_network",
                "ap": o["ap"],
                "ssid": o["ssid"],
                "value": o["rssi"],
                "channel": o["channel"],
            }
        )
    louder = [m for m, d in out_clients.items() if d.get("louder_ap")]
    if louder:
        alerts.append({"code": "louder_ap", "value": len(louder)})
    stuck = [m for m, d in out_clients.items() if d.get("stuck_24")]
    if stuck:
        alerts.append({"code": "stuck_24", "value": len(stuck)})
    for f in failed:
        alerts.append({"code": "detail_failed", "ap": f})
    return Detail(
        at=now,
        clients=out_clients,
        aps=out_aps,
        alerts=alerts,
        counters=counters,
        failed=failed,
    )
