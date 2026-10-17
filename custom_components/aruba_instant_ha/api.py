"""Client cho API web của Aruba Instant (`https://<ap>:4343/swarm.cgi`).

Đây là API mà chính giao diện web Instant dùng (đọc từ `jscripts/app.js` của firmware
8.x) — KHÔNG phải REST API chính thức (`/rest/...` cần `allow-rest-api` và chỉ chạy trên
AP master). Đặc điểm đo thật trên cụm 3 × IAP-335 (2026-10-18):

- Đăng nhập: POST `opcode=login&user=…&passwd=…` → XML `<data name="sid">…</data>`;
  sai mật khẩu trả `<re></re>` rỗng (vẫn HTTP 200).
- Lệnh: GET `opcode=show&cmd=<lệnh1>\\n<lệnh2>&ip=127.0.0.1&sid=…`. Nhiều lệnh thì mỗi
  bảng nằm trong `<output command="…">`, một lệnh thì `<t>` nằm thẳng dưới `<re>`.
- Bảng: `<t tn="tên"><th><h>cột</h>…</th><r><c>ô</c>…</r>…</t>`.
- Phiên hết hạn / đã logout: `<re><error>Invalid Session ID</error></re>`.
- AP thành viên cũng đăng nhập được nhưng `show aps` ra "0 Access Point" và `show clients`
  chỉ có client của chính nó ⇒ phải hỏi đúng AP **master** (conductor) của cụm.
- Instant giới hạn số phiên quản trị ⇒ dùng lại sid giữa các lần đọc, logout khi gỡ.
"""

from __future__ import annotations

import logging
import xml.etree.ElementTree as ET
from dataclasses import dataclass

import aiohttp

from .const import REQUEST_TIMEOUT

_LOGGER = logging.getLogger(__name__)


class ArubaApiError(Exception):
    """Lỗi mạng / AP trả dữ liệu không đọc được."""


class ArubaAuthError(ArubaApiError):
    """Sai tài khoản quản trị."""


class ArubaSessionExpired(ArubaApiError):
    """sid hết hạn hoặc đã bị đăng xuất."""


@dataclass(frozen=True)
class Table:
    name: str
    header: list[str]
    rows: list[list[str]]

    def dicts(self) -> list[dict[str, str]]:
        return [dict(zip(self.header, row, strict=False)) for row in self.rows]


def _table(node: ET.Element) -> Table:
    th = node.find("th")
    header = [(h.text or "").strip() for h in th] if th is not None else []
    rows = [[(c.text or "").strip() for c in r] for r in node.findall("r")]
    return Table(name=node.get("tn") or "", header=header, rows=rows)


def parse_show(text: str, commands: list[str]) -> dict[str, Table]:
    """XML của `opcode=show` → {lệnh: bảng đầu tiên của lệnh đó}."""
    try:
        root = ET.fromstring(text)
    except ET.ParseError as err:
        raise ArubaApiError(f"XML hỏng: {text[:120]!r}") from err
    error = root.find("error")
    if error is not None:
        msg = (error.text or "").strip()
        if "session" in msg.lower():
            raise ArubaSessionExpired(msg)
        raise ArubaApiError(msg)
    out: dict[str, Table] = {}
    outputs = root.findall("output")
    if outputs:
        for o in outputs:
            t = o.find("t")
            if t is not None:
                out[o.get("command") or ""] = _table(t)
    elif len(commands) == 1 and (t := root.find("t")) is not None:
        out[commands[0]] = _table(t)
    return out


def parse_data(text: str) -> dict[str, str]:
    """`<data name="X">giá trị</data>` ở mọi cấp → {X: giá trị} (giữ lần xuất hiện đầu)."""
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return {}
    out: dict[str, str] = {}
    for d in root.iter("data"):
        name = (d.get("name") or "").strip()
        if name and name not in out:
            out[name] = (d.text or "").strip()
    return out


def parse_sid(text: str) -> str | None:
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return None
    for d in root.findall("data"):
        if d.get("name") == "sid" and (d.text or "").strip():
            return d.text.strip()
    return None


class ArubaInstantApi:
    def __init__(
        self,
        session: aiohttp.ClientSession,
        hosts: list[str],
        username: str,
        password: str,
        port: int = 4343,
        verify_ssl: bool = False,
    ) -> None:
        self._session = session
        self.hosts = hosts
        self._port = port
        self._user = username
        self._pw = password
        self._ssl: bool | None = None if verify_ssl else False
        self.host: str | None = None  # AP master đang dùng
        self._sid: str | None = None

    def web_url(self, host: str | None = None) -> str:
        return f"https://{host or self.host or self.hosts[0]}:{self._port}"

    async def _call(self, host: str, method: str, params: dict[str, str]) -> str:
        url = f"https://{host}:{self._port}/swarm.cgi"
        try:
            async with self._session.request(
                method,
                url,
                params=params if method == "GET" else None,
                data=params if method == "POST" else None,
                ssl=self._ssl,
                timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT),
            ) as resp:
                text = await resp.text()
                if resp.status >= 400:
                    raise ArubaApiError(f"{host}: HTTP {resp.status}")
                return text
        except (aiohttp.ClientError, TimeoutError) as err:
            raise ArubaApiError(f"{host}: {err!r}") from err

    async def _login(self, host: str) -> str:
        text = await self._call(
            host,
            "POST",
            {
                "opcode": "login",
                "user": self._user,
                "passwd": self._pw,
                "refresh": "false",
            },
        )
        sid = parse_sid(text)
        if not sid:
            raise ArubaAuthError(f"{host}: đăng nhập bị từ chối")
        return sid

    async def _logout(self, host: str, sid: str) -> None:
        try:
            await self._call(host, "POST", {"opcode": "logout", "sid": sid})
        except ArubaApiError as err:
            _LOGGER.debug("aruba: logout %s lỗi: %s", host, err)

    async def _show_on(
        self, host: str, sid: str, commands: list[str]
    ) -> dict[str, Table]:
        return parse_show(await self._show_raw(host, sid, commands), commands)

    async def _show_raw(self, host: str, sid: str, commands: list[str]) -> str:
        text = await self._call(
            host,
            "GET",
            {
                "opcode": "show",
                "cmd": "\n".join(commands),
                "ip": "127.0.0.1",
                "refresh": "false",
                "sid": sid,
            },
        )
        if "<error>" in text:
            parse_show(text, commands)  # ném ArubaSessionExpired / ArubaApiError
        return text

    async def connect(self) -> None:
        """Tìm AP master: AP nào `show aps` ra nhiều AP nhất (thành viên trả 0)."""
        auth_errors = 0
        last: ArubaApiError | None = None
        for host in self.hosts:
            try:
                sid = await self._login(host)
            except ArubaAuthError as err:
                auth_errors += 1
                last = err
                continue
            except ArubaApiError as err:
                last = err
                continue
            try:
                aps = (await self._show_on(host, sid, ["show aps"])).get("show aps")
            except ArubaApiError as err:
                last = err
                await self._logout(host, sid)
                continue
            if aps and aps.rows:
                if self.host and self._sid and self.host != host:
                    await self._logout(self.host, self._sid)
                self.host, self._sid = host, sid
                return
            await self._logout(host, sid)
        if auth_errors and auth_errors == len(self.hosts):
            raise ArubaAuthError(str(last))
        raise ArubaApiError(f"không tìm thấy AP master trong {self.hosts}: {last}")

    async def show(self, *commands: str) -> dict[str, Table]:
        cmds = list(commands)
        if self.host and self._sid:
            try:
                result = await self._show_on(self.host, self._sid, cmds)
            except ArubaSessionExpired:
                pass
            except ArubaApiError:
                # master có thể đã đổi (AP khởi động lại) → dò lại bên dưới
                self.host = self._sid = None
            else:
                aps = result.get("show aps")
                if aps is None or aps.rows:
                    return result
                # AP này không còn là master
        await self.connect()
        assert self.host and self._sid
        return await self._show_on(self.host, self._sid, cmds)

    async def cluster_name(self) -> str | None:
        """Tên cụm Instant (`show summary` → Name), dùng làm tên + unique id của entry."""
        if not (self.host and self._sid):
            await self.connect()
        assert self.host and self._sid
        try:
            text = await self._show_raw(self.host, self._sid, ["show summary"])
        except ArubaSessionExpired:
            await self.connect()
            text = await self._show_raw(self.host, self._sid, ["show summary"])
        return parse_data(text).get("Name") or None

    async def close(self) -> None:
        if self.host and self._sid:
            await self._logout(self.host, self._sid)
        self.host = self._sid = None
