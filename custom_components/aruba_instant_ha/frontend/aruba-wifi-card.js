/**
 * aruba-wifi-card — thẻ Lovelace cho integration aruba_instant_ha: thiết bị Wi-Fi theo từng AP (sóng, băng tần,
 * SSID, tốc độ), tải kênh và sức khoẻ từng radio, cảnh báo cụm, chi tiết 5 phút (phát lại, AP nghe to hơn…).
 *
 * Integration tự phục vụ tệp này (`/aruba_instant_ha/aruba-wifi-card.js`) và tự nạp vào frontend ⇒ cài
 * integration là có thẻ, không cần resource riêng. Không bước build: Lit lấy từ frontend Home Assistant
 * (dự phòng CDN). Phần logic thuần được export để test bằng `node --test`.
 *
 * Tách từ lan-wifi-card của lan-topo-card v0.11.0 (cùng tác giả). MIT © ngoviet —
 * https://github.com/ngoviet/aruba_instant_ha
 */

export const VERSION = "0.3.0";

/** So sánh tự nhiên: ether2 < ether10 < sfp-sfpplus1. */
export function naturalCompare(a, b) {
  return String(a).localeCompare(String(b), "en", { numeric: true, sensitivity: "base" });
}

// ═══════════════════════════════ Wi-Fi ═══════════════════════════════

export const QUALITY_COLORS = { good: "#22c55e", ok: "#f59e0b", poor: "#ef4444" };

/** Số vạch sóng 1..4 theo chỉ số signal của Aruba (SNR, dB): ≥40 → 4, ≥30 → 3, ≥20 → 2. */
export function signalBars(signal) {
  if (signal === null || signal === undefined || !Number.isFinite(Number(signal))) return 0;
  const v = Number(signal);
  return v >= 40 ? 4 : v >= 30 ? 3 : v >= 20 ? 2 : 1;
}

/** Màu theo nhãn chất lượng của Aruba; không có nhãn thì suy từ số vạch. */
export function qualityColor(quality, signal) {
  if (quality && QUALITY_COLORS[quality]) return QUALITY_COLORS[quality];
  const b = signalBars(signal);
  return b >= 3 ? QUALITY_COLORS.good : b === 2 ? QUALITY_COLORS.ok : b === 1 ? QUALITY_COLORS.poor : "#94a3b8";
}

/** AP dùng chung kênh trên cùng băng → {apName: [tên AP trùng kênh]} (kênh 2,4 GHz chồng nhau gây nhiễu). */
export function coChannel(aps) {
  const byKey = new Map();
  for (const [name, ap] of Object.entries(aps || {})) {
    for (const r of ap.radios || []) {
      const ch = String(r.channel ?? "").match(/^\d+/)?.[0];
      if (!ch || !r.band) continue;
      const key = `${r.band}:${ch}`;
      if (byKey.has(key)) byKey.get(key).push(name);
      else byKey.set(key, [name]);
    }
  }
  const out = {};
  for (const [key, names] of byKey) {
    if (names.length < 2) continue;
    for (const n of names) {
      out[n] = out[n] || [];
      out[n].push({ band: key.split(":")[0], channel: key.split(":")[1], with: names.filter((x) => x !== n) });
    }
  }
  return out;
}

/** Lọc + nhóm + sắp xếp danh sách client. by: ap | ssid | band; sort: name | signal (yếu trước) | speed. */
export function groupClients(clients, { by = "ap", sort = "name", ssid = null, band = null } = {}) {
  const list = (clients || []).filter((c) => (!ssid || c.essid === ssid) && (!band || c.band === band));
  const cmp = {
    name: (a, b) => naturalCompare(a.name || "", b.name || ""),
    signal: (a, b) => (a.signal ?? -1) - (b.signal ?? -1) || naturalCompare(a.name || "", b.name || ""),
    speed: (a, b) => (b.speed_mbps ?? -1) - (a.speed_mbps ?? -1) || naturalCompare(a.name || "", b.name || ""),
  }[sort] || ((a, b) => naturalCompare(a.name || "", b.name || ""));
  const key = (c) => (by === "ssid" ? c.essid : by === "band" ? (c.band ? `${c.band} GHz` : null) : c.ap) || "?";
  const groups = new Map();
  for (const c of list) {
    const k = key(c);
    if (groups.has(k)) groups.get(k).push(c);
    else groups.set(k, [c]);
  }
  return [...groups.entries()]
    .sort((a, b) => naturalCompare(a[0], b[0]))
    .map(([name, items]) => ({ name, clients: items.sort(cmp) }));
}

/** "Aruba T2" → "T2" (tên AP ngắn trong huy hiệu). */
export function shortAp(name) {
  return String(name ?? "").replace(/^Aruba\s+/i, "");
}

/** Retry nên hiện: số 5 phút gần nhất nếu có, không thì số từ lúc nối (integration ≥ 0.2.0). */
export function clientRetry(c) {
  const v = c?.retry_5m ?? c?.retry_pct;
  return Number.isFinite(Number(v)) && v !== null ? Number(v) : null;
}

export const RETRY_BADGE_PCT = 30;

/**
 * Tối đa 2 huy hiệu cho ô thiết bị, theo thứ tự ưu tiên: AP khác nghe to hơn (gợi ý việc làm được) →
 * retry cao → máy 5 GHz kẹt 2,4 GHz. Mọi trường đều tuỳ chọn: integration cũ ⇒ không huy hiệu nào.
 */
export function clientBadges(c) {
  const out = [];
  if (c?.louder_ap && Number(c.louder_gain) > 0) out.push({ kind: "louder", ap: shortAp(c.louder_ap), gain: Number(c.louder_gain) });
  // Huy hiệu CHỈ dùng retry 5 phút. Đo 20/11/2026 trên 55 máy thật: "từ lúc nối" ≥ 30 % ở 17 máy (kéo lên bởi
  // lúc chập chờn cũ, vd 72,7 % trong khi 5 phút gần nhất 2,4 %), "5 phút" ≥ 30 % chỉ 2 máy ⇒ chỉ số này báo đúng.
  const r5 = Number(c?.retry_5m);
  if (c?.retry_5m !== null && c?.retry_5m !== undefined && Number.isFinite(r5) && r5 >= RETRY_BADGE_PCT) out.push({ kind: "retry", pct: Math.round(r5) });
  if (c?.stuck_24) out.push({ kind: "stuck" });
  return out.slice(0, 2);
}

/** Giây → "3n 17g" / "3d 17h" (đơn vị lấy từ bảng chuỗi). */
export function fmtUptime(s, T = { d: "d", h: "h", m: "m" }) {
  const v = Number(s);
  if (!Number.isFinite(v) || v <= 0) return null;
  const d = Math.floor(v / 86400);
  const h = Math.floor((v % 86400) / 3600);
  const m = Math.floor((v % 3600) / 60);
  if (d) return `${d}${T.d} ${h}${T.h}`;
  if (h) return `${h}${T.h} ${m}${T.m}`;
  return `${m}${T.m}`;
}

/** kbps → "850 kb/s" / "1.2 Mb/s". */
export function fmtKbps(kbps) {
  const v = Number(kbps);
  if (!Number.isFinite(v) || kbps === null) return null;
  return v >= 1000 ? `${(v / 1000).toFixed(v >= 10000 ? 0 : 1)} Mb/s` : `${Math.round(v)} kb/s`;
}

/** Radio có điều đáng báo? Reset > 2 lần/ngày, retry ≥ 15 %. */
export function radioWarnings(r) {
  const w = [];
  if (Number(r?.resets_per_day) > 2) w.push({ kind: "resets", value: Number(r.resets_per_day) });
  const retry = r?.retry_5m ?? r?.retry_pct;
  if (Number.isFinite(Number(retry)) && retry !== null && Number(retry) >= 15) w.push({ kind: "retry", value: Math.round(Number(retry)) });
  return w;
}

const STRINGS = {
  vi: {
    ports_up: (n, m) => `${n}/${m} cổng có link`,
    no_device: "không thấy thiết bị",
    no_ports: "chưa có cổng",
    tap_open: "chạm để mở",
    down_dev: "↓ về phía thiết bị",
    up_dev: "↑ từ thiết bị",
    no_link: "Không có link",
    backbone: "trục chính",
    core: "thiết bị chính",
    poe: "PoE",
    empty: "trống",
    fault: "lỗi: phải có link",
    slow: "chậm hơn kỳ vọng",
    slow_tip: (want) => `chậm hơn kỳ vọng ${want}`,
    uplink: "uplink",
    n_ports: (n) => `${n} cổng`,
    behind: (n) => `${n} phía sau`,
    poe_n: (n) => `${n} cổng PoE`,
    fold: "Thu nhánh",
    unfold: "Mở nhánh",
    d_status: "Trạng thái",
    d_up: "Có link",
    d_peer: "Nối tới",
    d_device: "Thiết bị",
    d_ip: "IP",
    d_mac: "MAC",
    d_traffic: "Lưu lượng",
    d_downs: "Mất link từ lúc khởi động",
    d_on: "Đang cấp",
    d_more: "Mở chi tiết",
    d_close: "Đóng",
    face: (n) => `Cổng của ${n}`,
    days: (n) => `${n} ngày`,
    hours: (n) => `${n} giờ`,
    detail_simple: "Đơn giản",
    detail_full: "Đầy đủ",
    moving: "đường chạy = có lưu lượng",
    top: "Đang dùng mạng nhiều nhất",
    view_auto: "Tự động",
    view_horizontal: "Sơ đồ ngang",
    view_down: "Cây dọc",
    view_radial: "Tâm – viền",
    view_arc: "Vòng cung",
    view_cards: "Thẻ",
    view_vertical: "Danh sách",
    top_none: "Không có thiết bị nào đang dùng đáng kể",
    disabled: "cổng tắt",
    traffic: "sáng viền = có lưu lượng",
    clients: (n) => `${n} thiết bị`,
    all: "Tất cả",
    busy: "bận",
    same_channel: (ch, who) => `trùng kênh ${ch} với ${who}`,
    weak: (n) => `${n} máy sóng yếu`,
    no_entity: "không thấy entity",
    up: "chạy",
    unit: { d: "n", h: "g", m: "p" },
    retry: "phát lại",
    resets_day: (v) => `reset ${v}/ngày`,
    pinned: "kênh ghim tay",
    arm: "ARM tự chọn kênh",
    stale: "số cũ (lần đọc chi tiết lỗi)",
    louder: (ap, g) => `${ap} nghe to hơn ${g} dB`,
    stuck: "có 5 GHz, đang ở 2,4",
    detail_age: (t) => `chi tiết lúc ${t}`,
    d_rate: "Tốc độ gửi / nhận",
    d_traffic: "Lưu lượng 5 phút",
    d_retry: "Phát lại 5 phút / từ lúc nối",
    d_health: "Client health (C/R)",
    d_louder: "AP nghe to hơn",
    d_louder_hint: "Ngắt máy này để nó chọn lại AP: aruba-axi plan rebalance",
    d_stuck: "Máy có 5 GHz nhưng đang ở 2,4 GHz",
    d_net: "IP · SSID",
    d_ident: "MAC · hostname · hệ điều hành",
    d_radio: "Chuẩn · kênh · AP",
    d_close: "Đóng",
    alerts: {
      radio_resets: (a) => `${shortAp(a.ap)} ${a.band} GHz reset radio ${a.value} lần/ngày`,
      radio_retry: (a) => `${shortAp(a.ap)} ${a.band} GHz phát lại ${Math.round(a.value)}% (5 phút)`,
      open_network: (a) => `Mạng mở "${a.ssid}" ${a.value} dBm kênh ${a.channel} (cạnh ${shortAp(a.ap)})`,
      louder_ap: (a) => `${a.value} máy bám AP xa trong khi AP khác nghe to hơn`,
      stuck_24: (a) => `${a.value} máy có 5 GHz đang ở 2,4 GHz`,
      detail_failed: (a) => `Không đọc được chi tiết ${shortAp(a.ap)}`,
    },
  },
  en: {
    ports_up: (n, m) => `${n}/${m} ports up`,
    no_device: "device not found",
    no_ports: "no ports",
    tap_open: "tap to expand",
    down_dev: "↓ towards device",
    up_dev: "↑ from device",
    no_link: "No link",
    backbone: "backbone",
    core: "core device",
    poe: "PoE",
    empty: "empty",
    fault: "fault: should be linked",
    slow: "slower than expected",
    slow_tip: (want) => `slower than expected ${want}`,
    uplink: "uplink",
    n_ports: (n) => `${n} ports`,
    behind: (n) => `${n} behind`,
    poe_n: (n) => `${n} PoE ports`,
    fold: "Collapse branch",
    unfold: "Expand branch",
    d_status: "Status",
    d_up: "Link up",
    d_peer: "Connected to",
    d_device: "Device",
    d_ip: "IP",
    d_mac: "MAC",
    d_traffic: "Traffic",
    d_downs: "Link drops since boot",
    d_on: "Powering",
    d_more: "More info",
    d_close: "Close",
    face: (n) => `${n} ports`,
    days: (n) => `${n}d`,
    hours: (n) => `${n}h`,
    detail_simple: "Simple",
    detail_full: "Full",
    moving: "moving line = traffic",
    top: "Top talkers",
    view_auto: "Auto",
    view_horizontal: "Tree",
    view_down: "Top-down",
    view_radial: "Hub",
    view_arc: "Arc",
    view_cards: "Cards",
    view_vertical: "List",
    top_none: "No device is using noticeable bandwidth",
    disabled: "port disabled",
    traffic: "glowing edge = traffic",
    clients: (n) => `${n} clients`,
    all: "All",
    busy: "busy",
    same_channel: (ch, who) => `same channel ${ch} as ${who}`,
    weak: (n) => `${n} weak signal`,
    no_entity: "entity not found",
    up: "up",
    unit: { d: "d", h: "h", m: "m" },
    retry: "retry",
    resets_day: (v) => `${v} resets/day`,
    pinned: "channel pinned",
    arm: "ARM picks the channel",
    stale: "old numbers (detail read failed)",
    louder: (ap, g) => `${ap} hears it ${g} dB louder`,
    stuck: "5 GHz-capable, on 2.4",
    detail_age: (t) => `detail at ${t}`,
    d_rate: "Tx / Rx rate",
    d_traffic: "Traffic, last 5 min",
    d_retry: "Retry, 5 min / since connect",
    d_health: "Client health (C/R)",
    d_louder: "Heard louder by",
    d_louder_hint: "Disconnect it so it re-picks an AP: aruba-axi plan rebalance",
    d_stuck: "5 GHz-capable device sitting on 2.4 GHz",
    d_net: "IP · SSID",
    d_ident: "MAC · hostname · OS",
    d_radio: "PHY · channel · AP",
    d_close: "Close",
    alerts: {
      radio_resets: (a) => `${shortAp(a.ap)} ${a.band} GHz radio resets ${a.value}/day`,
      radio_retry: (a) => `${shortAp(a.ap)} ${a.band} GHz retry ${Math.round(a.value)}% (5 min)`,
      open_network: (a) => `Open network "${a.ssid}" ${a.value} dBm ch ${a.channel} (near ${shortAp(a.ap)})`,
      louder_ap: (a) => `${a.value} device(s) on a far AP while another hears them louder`,
      stuck_24: (a) => `${a.value} 5 GHz-capable device(s) on 2.4 GHz`,
      detail_failed: (a) => `Detail of ${shortAp(a.ap)} unreadable`,
    },
  },
};

export function strings(lang) {
  return String(lang || "").toLowerCase().startsWith("vi") ? STRINGS.vi : STRINGS.en;
}

// ═══════════════════════════════ Phần tử Lovelace ═══════════════════════════════

async function loadLit() {
  const fromHa = () => {
    const el = customElements.get("ha-panel-lovelace") || customElements.get("hui-view") || customElements.get("ha-card");
    if (!el) return null;
    let base = Object.getPrototypeOf(el);
    while (base && base !== HTMLElement && !(base.prototype && base.prototype.html && base.prototype.css)) {
      base = Object.getPrototypeOf(base);
    }
    return base && base.prototype?.html ? { LitElement: base, html: base.prototype.html, css: base.prototype.css } : null;
  };
  let lit = fromHa();
  if (!lit) {
    await Promise.race([customElements.whenDefined("ha-card"), new Promise((r) => setTimeout(r, 3000))]);
    lit = fromHa();
  }
  if (!lit) {
    // Frontend HA không còn gắn html/css lên LitElement → nạp Lit (bản ghim) từ CDN.
    const m = await import("https://cdn.jsdelivr.net/npm/lit@3.2.1/+esm");
    lit = { LitElement: m.LitElement, html: m.html, css: m.css };
  }
  return lit;
}

async function defineCard() {
  const { LitElement, html, css } = await loadLit();

  // Nền, màu chữ, khung thẻ (giống lan-topo-card để hai thẻ đứng cạnh nhau cùng phong cách).
  const BASE_STYLES = css`
    :host {
      display: block;
      --ltc-bg: radial-gradient(120% 140% at 0% 0%, #142443 0%, #0a1122 55%, #060a14 100%);
      --ltc-fg: #e6edf7;
      --ltc-dim: #8ea3c2;
      --ltc-panel: rgba(14, 24, 46, 0.86);
      --ltc-border: rgba(120, 160, 255, 0.18);
      --ltc-up: #e879f9;
    }
    ha-card {
      background: var(--ltc-bg);
      color: var(--ltc-fg);
      border-radius: var(--ha-card-border-radius, 18px);
      border: 1px solid var(--ltc-border);
      box-shadow: inset 0 0 28px rgba(56, 189, 248, 0.07);
      overflow: hidden;
    }
    .title {
      font-weight: 600;
    }
    .legend i {
      display: inline-block;
      width: 10px;
      height: 10px;
      border-radius: 3px;
      background: var(--c);
      margin-right: 5px;
      vertical-align: -1px;
    }
    .legend i.off,
    .legend i.dis,
    .legend i.fault {
      box-shadow: none;
      box-sizing: border-box;
    }
    .legend i.off {
      background: rgba(148, 163, 184, 0.07);
      border: 1px solid rgba(148, 163, 184, 0.35);
    }
    .legend i.dis {
      background: repeating-linear-gradient(45deg, rgba(148, 163, 184, 0.08) 0 3px, rgba(148, 163, 184, 0.26) 3px 5px);
    }
    .legend i.fault {
      background: rgba(239, 68, 68, 0.12);
      border: 1px solid #ef4444;
    }
    /* Ống bọc trục chính: hai viền song song, lõi trong suốt (giống hình trên sơ đồ). */
    .legend i.bb {
      width: 18px;
      height: 8px;
      border-radius: 4px;
      background: transparent;
      border: 1.5px solid #cbd5e1;
      box-sizing: border-box;
    }
    /* Thiết bị chính: khối nổi (nền ngả màu, viền, bóng đổ), giống ô router/switch trên sơ đồ. */
    .legend i.core {
      --c: #22d3ee;
      width: 14px;
      background: linear-gradient(180deg, color-mix(in srgb, var(--c) 45%, #0e1a33), color-mix(in srgb, var(--c) 15%, #0b1428));
      border: 1px solid var(--c);
      box-sizing: border-box;
      box-shadow: 0 2px 4px rgba(0, 0, 0, 0.7);
    }
    .legend i.slow {
      --c: #9ca3af;
      outline: 1.5px solid #fbbf24;
      outline-offset: 1px;
    }
    .pt {
      position: relative;
      box-sizing: border-box;
      min-width: 30px;
      height: 26px;
      padding: 0 5px;
      border-radius: 7px;
      display: flex;
      align-items: center;
      justify-content: center;
      gap: 1px;
      font-size: 0.8rem;
      font-weight: 700;
      font-variant-numeric: tabular-nums;
      cursor: pointer;
      user-select: none;
      -webkit-tap-highlight-color: transparent;
      transition: box-shadow 0.2s, filter 0.2s;
    }
    .pt.on {
      background: var(--c);
      color: #06101f;
    }
    .pt.on.busy,
    .pt.on.hot {
      outline: 1px solid #fff8;
      outline-offset: 0;
    }
    .pt.off {
      background: rgba(148, 163, 184, 0.07);
      border: 1px solid rgba(148, 163, 184, 0.2);
      color: #64748b;
    }
    .pt.fault {
      background: rgba(239, 68, 68, 0.12);
      border: 1px solid #ef4444;
      color: #fca5a5;
    }
    .pt.dis {
      background: repeating-linear-gradient(45deg, rgba(148, 163, 184, 0.08) 0 3px, rgba(148, 163, 184, 0.26) 3px 5px);
      color: #64748b;
    }
    .pt.slow {
      outline: 1.5px solid #fbbf24;
      outline-offset: 1px;
    }
    .pt:hover {
      filter: brightness(1.2);
    }
    /* Vòng focus khi đi bằng bàn phím: xanh lơ 2px trên nền tối, khác viền trắng của ô đang chọn. */
    button:focus-visible,
    [tabindex]:focus-visible {
      outline: 2px solid #67e8f9;
      outline-offset: 2px;
    }
  `;

  class ArubaWifiCard extends LitElement {
    static get properties() {
      return {
        hass: { attribute: false },
        _config: { state: true },
        _ssid: { state: true },
        _band: { state: true },
        _narrow: { state: true },
        _toggled: { state: true },
        _sel: { state: true },
      };
    }

    getGridOptions() {
      return { columns: "full", min_columns: 6 };
    }

    static getStubConfig() {
      return { entity: "sensor.aruba_instant_clients" };
    }

    connectedCallback() {
      super.connectedCallback();
      // Khung hẹp (điện thoại) → thu gọn từng nhóm, chạm tiêu đề để mở.
      this._ro = new ResizeObserver(() => {
        const narrow = this.clientWidth > 0 && this.clientWidth < (this._config?.breakpoint ?? 600);
        if (narrow !== this._narrow) this._narrow = narrow;
      });
      this._ro.observe(this);
    }

    disconnectedCallback() {
      super.disconnectedCallback();
      this._ro?.disconnect();
    }

    _isOpen(name) {
      const mode = this._config.collapse ?? "auto";
      const base = mode === true ? false : mode === false ? true : !this._narrow;
      return this._toggled?.has(name) ? !base : base;
    }

    _toggle(name) {
      const next = new Set(this._toggled || []);
      if (next.has(name)) next.delete(name);
      else next.add(name);
      this._toggled = next;
    }

    setConfig(config) {
      if (!config || !config.entity) throw new Error("aruba-wifi-card: cần `entity` (sensor tổng thiết bị Wi-Fi)");
      this._config = config;
      this._ssid = config.ssid ?? null;
      this._band = config.band ?? null;
      this._toggled = new Set();
    }

    getCardSize() {
      return 6;
    }

    // Mọi dữ liệu nằm trong thuộc tính của 1 entity → chỉ cần so entity đó.
    shouldUpdate(changed) {
      if (changed.size > 1 || !changed.has("hass")) return true;
      const old = changed.get("hass");
      return !old || old.states[this._config.entity] !== this.hass.states[this._config.entity];
    }

    _chip(label, active, onClick, color) {
      return html`<button class="chip ${active ? "on" : ""}" style=${color ? `--c:${color}` : ""} @click=${onClick}>${label}</button>`;
    }

    render() {
      if (!this._config || !this.hass) return html``;
      const cfg = this._config;
      const T = strings(cfg.language || this.hass.locale?.language || this.hass.language);
      const st = this.hass.states[cfg.entity];
      if (!st) return html`<ha-card><div class="empty">${T.no_entity}: ${cfg.entity}</div></ha-card>`;
      const clients = st.attributes.clients || [];
      const aps = st.attributes.aps || {};
      const ssids = st.attributes.ssids || {};
      const bands = [...new Set(clients.map((c) => c.band).filter(Boolean))].sort();
      const by = cfg.group_by || "ap";
      const groups = groupClients(clients, { by, sort: cfg.sort || "name", ssid: this._ssid, band: this._band });
      const overlap = coChannel(aps);
      const shown = groups.reduce((n, g) => n + g.clients.length, 0);
      return html`<ha-card>
        <div class="head">
          <div class="title">${cfg.title ?? "Wi-Fi"}</div>
          <div class="sub">${T.clients(shown)}${shown !== clients.length ? ` / ${clients.length}` : ""}</div>
        </div>
        <div class="filters">
          ${this._chip(T.all, !this._ssid && !this._band, () => ((this._ssid = null), (this._band = null)))}
          ${Object.entries(ssids).map(([name, n]) => this._chip(`${name} · ${n}`, this._ssid === name, () => (this._ssid = this._ssid === name ? null : name)))}
          ${bands.map((b) => this._chip(`${b} GHz`, this._band === b, () => (this._band = this._band === b ? null : b), b === "5" ? "#a78bfa" : "#38bdf8"))}
        </div>
        ${this._alerts(st.attributes.alerts, st.attributes.detail_updated, T)}
        <div class="groups">
          ${groups.map((g) => this._renderGroup(g, by === "ap" ? aps[g.name] : null, overlap[g.name], T))}
        </div>
      </ha-card>`;
    }

    // Cảnh báo cấp cụm (integration ≥ 0.2.0). Không có ⇒ không vẽ gì.
    _alerts(alerts, updated, T) {
      const list = (alerts || []).filter((a) => T.alerts?.[a.code]);
      if (!list.length) return "";
      const when = updated ? new Date(updated) : null;
      const age = when && !Number.isNaN(when.getTime()) ? when.toLocaleTimeString(this.hass?.locale?.language || undefined, { hour: "2-digit", minute: "2-digit" }) : null;
      return html`<div class="alerts" role="list">
        ${list.map((a) => html`<span class="alert ${a.code}" role="listitem"><ha-icon icon=${a.code === "open_network" ? "mdi:wifi-lock-open" : a.code === "louder_ap" ? "mdi:swap-horizontal" : "mdi:alert"}></ha-icon>${T.alerts[a.code](a)}</span>`)}
        ${age ? html`<span class="age">${T.detail_age(age)}</span>` : ""}
      </div>`;
    }

    _renderGroup(group, ap, overlap, T) {
      const open = this._isOpen(group.name);
      const weak = group.clients.filter((c) => c.quality === "poor" || (c.quality !== "good" && signalBars(c.signal) <= 1)).length;
      return html`<div class="grp ${open ? "" : "closed"}">
        <div class="ghead" @click=${() => this._toggle(group.name)}>
          <ha-icon class="chev" icon=${open ? "mdi:chevron-down" : "mdi:chevron-right"}></ha-icon>
          <ha-icon icon=${ap ? "mdi:access-point" : "mdi:wifi"}></ha-icon>
          <span class="gname">${group.name}</span>
          <span class="gsub">${T.clients(group.clients.length)}${ap?.ip ? ` · ${ap.ip}` : ""}${fmtUptime(ap?.uptime_s, T.unit) ? ` · ${T.up} ${fmtUptime(ap.uptime_s, T.unit)}` : ""}</span>
          ${ap?.stale ? html`<span class="stale" title=${T.stale}><ha-icon icon="mdi:clock-alert-outline"></ha-icon></span>` : ""}
          ${ap ? (ap.radios || []).map((r) => this._radio(r, T)) : ""}
          ${(overlap || []).map((o) => html`<span class="warn"><ha-icon icon="mdi:alert"></ha-icon>${o.band} GHz · ${T.same_channel(o.channel, o.with.join(", "))}</span>`)}
          ${weak ? html`<span class="weak">${T.weak(weak)}</span>` : ""}
        </div>
        ${open ? html`<div class="clients">${group.clients.map((c) => this._client(c, T))}</div>${this._detail(group.clients.find((c) => c.mac && c.mac === this._sel), T)}` : ""}
      </div>`;
    }

    _radio(r, T) {
      const util = Number(r.utilization) || 0;
      const col = util >= 60 ? "#ef4444" : util >= 35 ? "#f59e0b" : "#22c55e";
      const warns = radioWarnings(r);
      const retry = r.retry_5m ?? r.retry_pct;
      const tip = [
        `${r.band} GHz · ch ${r.channel} · ${r.power_dbm ?? "?"} dBm · noise ${r.noise_dbm ?? "?"} dBm`,
        r.pinned === true ? `${T.pinned}${r.set_power !== undefined ? ` · ${r.set_power} dBm` : ""}` : r.pinned === false ? T.arm : null,
        r.busy_64s !== undefined ? `${T.busy} 64 s: ${r.busy_64s}%` : null,
        retry !== undefined && retry !== null ? `${T.retry}: ${retry}%` : null,
        r.resets !== undefined ? `reset: ${r.resets}${r.resets_per_day !== undefined ? ` (${T.resets_day(r.resets_per_day)})` : ""}` : null,
        r.cochannel !== undefined ? `co-channel: ${r.cochannel}${r.cochannel_loudest !== undefined ? ` · ${r.cochannel_loudest} dBm` : ""}` : null,
      ]
        .filter(Boolean)
        .join("\n");
      return html`<span class="radio" title=${tip}>
        <b>${r.band}G</b> ch${r.channel}${r.pinned === true ? html`<ha-icon class="pin" icon="mdi:pin" aria-label=${T.pinned}></ha-icon>` : ""}
        <span class="bar"><i style="width:${Math.min(100, util)}%;background:${col}"></i></span>${util}% ${T.busy}
        ${retry !== undefined && retry !== null ? html`<span class=${Number(retry) >= 15 ? "rbad" : "rok"}>↻ ${Math.round(Number(retry))}%</span>` : ""}
        ${warns.filter((w) => w.kind === "resets").map((w) => html`<span class="rbad">⟳ ${T.resets_day(w.value)}</span>`)}
      </span>`;
    }

    _badge(b, T) {
      if (b.kind === "louder") return html`<span class="bdg louder" title=${T.louder(b.ap, b.gain)}>→${b.ap} +${b.gain}</span>`;
      if (b.kind === "retry") return html`<span class="bdg retry" title=${`${T.retry} ${b.pct}%`}>↻${b.pct}%</span>`;
      return html`<span class="bdg stuck" title=${T.stuck}>5G?</span>`;
    }

    _pick(c) {
      if (!c.mac) return;
      this._sel = this._sel === c.mac ? null : c.mac;
    }

    // Khung chi tiết (chạm/bấm một ô): mọi trường tuỳ chọn — thiếu thì bỏ dòng, không in "undefined".
    _detail(c, T) {
      if (!c) return "";
      const rows = [];
      const both = (a, b, unit = "") => (a === undefined && b === undefined ? null : `${a ?? "—"} / ${b ?? "—"}${unit}`);
      const rate = both(c.tx_rate, c.rx_rate, " Mbps");
      if (rate) rows.push([T.d_rate, rate]);
      const tr = c.tx_kbps !== undefined || c.rx_kbps !== undefined ? `↑ ${fmtKbps(c.tx_kbps) ?? "—"} · ↓ ${fmtKbps(c.rx_kbps) ?? "—"}` : null;
      if (tr) rows.push([T.d_traffic, tr]);
      const rt = both(c.retry_5m !== undefined ? `${c.retry_5m}%` : undefined, c.retry_pct !== undefined ? `${c.retry_pct}%` : undefined);
      if (rt) rows.push([T.d_retry, rt]);
      if (c.health) rows.push([T.d_health, c.health]);
      if (c.louder_ap) rows.push([T.d_louder, `${shortAp(c.louder_ap)} (+${c.louder_gain} dB) — ${T.d_louder_hint}`]);
      if (c.stuck_24) rows.push([T.d_stuck, "✓"]);
      // IP + SSID nhắc lại ở đây: trong ô 230 px chúng hay bị cắt bằng "…" (nhất là khi có huy hiệu).
      if (c.ip || c.essid) rows.push([T.d_net, [c.ip, c.essid].filter(Boolean).join(" · ")]);
      rows.push([T.d_ident, [c.mac, c.hostname, c.os && c.os !== "NOFP" ? c.os : null].filter(Boolean).join(" · ")]);
      rows.push([T.d_radio, [c.phy, c.channel ? `ch ${c.channel}` : null, c.ap].filter(Boolean).join(" · ")]);
      return html`<div class="detail" role="region" aria-label=${c.name}>
        <div class="dhead"><b>${c.name}</b><button class="dclose" @click=${() => (this._sel = null)}>${T.d_close}</button></div>
        <dl>${rows.map(([k, v]) => html`<dt>${k}</dt><dd>${v}</dd>`)}</dl>
      </div>`;
    }

    _client(c, T) {
      const color = qualityColor(c.quality, c.signal);
      const bars = signalBars(c.signal);
      const badges = clientBadges(c);
      const tip = [c.name, c.hostname && c.hostname !== c.name ? `host: ${c.hostname}` : null, c.mac, c.os && c.os !== "NOFP" ? c.os : null, c.phy ? `PHY ${c.phy} · ch ${c.channel}` : null, c.ap]
        .filter(Boolean)
        .join("\n");
      const sel = c.mac && c.mac === this._sel;
      return html`<div class="cl ${sel ? "sel" : ""}" style="--c:${color}" title=${tip} role="button" tabindex="0" aria-expanded=${sel ? "true" : "false"}
        @click=${() => this._pick(c)} @keydown=${(e) => (e.key === "Enter" || e.key === " ") && (e.preventDefault(), this._pick(c))}>
        <span class="sig">${[1, 2, 3, 4].map((i) => html`<i class=${i <= bars ? "on" : ""} style="height:${3 + i * 3}px"></i>`)}</span>
        <div class="cmain">
          <div class="cname">${c.name}</div>
          <div class="csub">${badges.map((b) => this._badge(b, T))}${[c.ip, c.essid].filter(Boolean).join(" · ")}</div>
        </div>
        <div class="cright">
          ${c.band ? html`<span class="band b${String(c.band).replace(".", "")}">${c.band}</span>` : ""}
          <span class="spd">${c.speed_mbps ?? "—"}<small>M</small></span>
          <span class="snr">${c.signal ?? "—"}<small>dB</small></span>
        </div>
      </div>`;
    }

    static get styles() {
      return [BASE_STYLES, css`
        ha-card {
          padding-bottom: 8px;
        }
        .empty {
          padding: 16px;
          color: #fbbf24;
        }
        .head {
          display: flex;
          align-items: baseline;
          gap: 10px;
          padding: 12px 16px 4px;
        }
        .title {
          font-size: 1.05rem;
        }
        .sub {
          color: var(--ltc-dim);
          font-size: 0.8rem;
        }
        .filters {
          display: flex;
          flex-wrap: wrap;
          gap: 6px;
          padding: 4px 16px 6px;
        }
        .chip {
          --c: #22d3ee;
          font: inherit;
          font-size: 0.8rem;
          color: var(--ltc-fg);
          background: rgba(255, 255, 255, 0.04);
          border: 1px solid var(--ltc-border);
          border-radius: 999px;
          padding: 3px 10px;
          cursor: pointer;
        }
        .chip.on {
          border-color: var(--c);
          color: var(--c);
          background: color-mix(in srgb, var(--c) 14%, transparent);
        }
        .groups {
          display: flex;
          flex-direction: column;
          gap: 10px;
          padding: 4px 12px 4px;
        }
        .grp {
          background: var(--ltc-panel);
          border: 1px solid color-mix(in srgb, #60a5fa 45%, transparent);
          border-radius: 14px;
          padding: 8px 10px 10px;
        }
        .ghead {
          display: flex;
          flex-wrap: wrap;
          align-items: center;
          gap: 4px 10px;
          margin-bottom: 8px;
          cursor: pointer;
          user-select: none;
          -webkit-tap-highlight-color: transparent;
        }
        .grp.closed .ghead {
          margin-bottom: 0;
        }
        .ghead ha-icon.chev {
          --mdc-icon-size: 16px;
          color: var(--ltc-dim);
          filter: none;
          margin-right: -6px;
        }
        .weak {
          font-size: 0.8rem;
          color: #f87171;
        }
        .ghead ha-icon {
          --mdc-icon-size: 18px;
          color: #60a5fa;
        }
        .gname {
          font-weight: 600;
        }
        .gsub {
          color: var(--ltc-dim);
          font-size: 0.8rem;
        }
        .radio {
          display: inline-flex;
          align-items: center;
          gap: 5px;
          font-size: 0.8rem;
          color: var(--ltc-dim);
          padding: 1px 8px;
          border: 1px solid var(--ltc-border);
          border-radius: 8px;
        }
        .radio b {
          color: var(--ltc-fg);
        }
        .bar {
          display: inline-block;
          width: 40px;
          height: 5px;
          border-radius: 3px;
          background: rgba(255, 255, 255, 0.1);
          overflow: hidden;
        }
        .bar i {
          display: block;
          height: 100%;
        }
        .warn {
          display: inline-flex;
          align-items: center;
          gap: 4px;
          font-size: 0.8rem;
          color: #fbbf24;
        }
        .warn ha-icon {
          --mdc-icon-size: 14px;
          color: #fbbf24;
          filter: none;
        }
        .clients {
          display: grid;
          grid-template-columns: repeat(auto-fill, minmax(230px, 1fr));
          gap: 6px;
        }
        .cl {
          display: flex;
          align-items: center;
          gap: 8px;
          min-width: 0;
          padding: 5px 8px;
          border-radius: 10px;
          background: rgba(255, 255, 255, 0.03);
          border: 1px solid color-mix(in srgb, var(--c) 55%, transparent);
        }
        .sig {
          display: inline-flex;
          align-items: flex-end;
          gap: 2px;
          height: 15px;
          flex: none;
        }
        .sig i {
          width: 3px;
          border-radius: 1px;
          background: rgba(255, 255, 255, 0.15);
        }
        .sig i.on {
          background: var(--c);
        }
        .cmain {
          flex: 1;
          min-width: 0;
        }
        .cname {
          font-size: 0.8rem;
          font-weight: 600;
          white-space: nowrap;
          overflow: hidden;
          text-overflow: ellipsis;
        }
        .csub {
          font-size: 0.75rem;
          color: var(--ltc-dim);
          white-space: nowrap;
          overflow: hidden;
          text-overflow: ellipsis;
        }
        .cright {
          display: flex;
          align-items: center;
          gap: 6px;
          flex: none;
          font-size: 0.8rem;
          font-variant-numeric: tabular-nums;
        }
        .cright small {
          color: var(--ltc-dim);
          margin-left: 1px;
          font-size: 12px;
        }
        .band {
          font-size: 0.75rem;
          font-weight: 700;
          padding: 1px 4px;
          border-radius: 5px;
          border: 1px solid currentColor;
        }
        .band.b24 {
          color: #38bdf8;
        }
        .band.b5 {
          color: #a78bfa;
        }
        .snr {
          color: var(--c);
        }
        .snr small {
          font-size: 12px;
        }
        .alerts {
          display: flex;
          flex-wrap: wrap;
          align-items: center;
          gap: 6px 12px;
          padding: 2px 16px 6px;
          font-size: 0.8rem;
        }
        .alert {
          display: inline-flex;
          align-items: center;
          gap: 4px;
          color: #fbbf24;
        }
        .alert.louder_ap,
        .alert.stuck_24 {
          color: #7dd3fc;
        }
        .alert ha-icon {
          --mdc-icon-size: 15px;
          color: currentColor;
          filter: none;
        }
        .alerts .age {
          color: var(--ltc-dim);
        }
        .stale ha-icon {
          --mdc-icon-size: 16px;
          color: #fbbf24;
          filter: none;
        }
        .radio ha-icon.pin {
          --mdc-icon-size: 12px;
          color: var(--ltc-dim);
          filter: none;
          margin-left: -3px;
        }
        .radio .rok {
          color: var(--ltc-dim);
        }
        .radio .rbad {
          color: #f87171;
          font-weight: 600;
        }
        .cl {
          cursor: pointer;
        }
        .cl:focus-visible {
          outline: 2px solid #7dd3fc;
          outline-offset: 1px;
        }
        .cl.sel {
          background: color-mix(in srgb, var(--c) 14%, transparent);
        }
        .bdg {
          display: inline-block;
          font-size: 0.75rem;
          font-weight: 700;
          padding: 0 4px;
          margin-right: 4px;
          border-radius: 4px;
          border: 1px solid currentColor;
          vertical-align: 1px;
        }
        .bdg.louder {
          color: #7dd3fc;
        }
        .bdg.retry {
          color: #f87171;
        }
        .bdg.stuck {
          color: #c4b5fd;
        }
        .detail {
          margin-top: 8px;
          padding: 8px 12px 10px;
          border-radius: 10px;
          border: 1px solid var(--ltc-border);
          background: rgba(255, 255, 255, 0.04);
          font-size: 0.875rem;
        }
        .dhead {
          display: flex;
          align-items: center;
          justify-content: space-between;
          gap: 8px;
          margin-bottom: 6px;
        }
        .dclose {
          font: inherit;
          font-size: 0.8rem;
          color: var(--ltc-fg);
          background: transparent;
          border: 1px solid var(--ltc-border);
          border-radius: 8px;
          padding: 4px 12px;
          min-height: 32px;
          cursor: pointer;
        }
        .detail dl {
          display: grid;
          grid-template-columns: minmax(0, max-content) minmax(0, 1fr);
          gap: 4px 14px;
          margin: 0;
        }
        .detail dt {
          color: var(--ltc-dim);
        }
        .detail dd {
          margin: 0;
          overflow-wrap: anywhere;
          font-variant-numeric: tabular-nums;
        }
        @media (max-width: 480px) {
          .detail dl {
            grid-template-columns: minmax(0, 1fr);
          }
          .detail dd {
            margin-bottom: 4px;
          }
        }
      `];
    }
  }

  if (!customElements.get("aruba-wifi-card")) customElements.define("aruba-wifi-card", ArubaWifiCard);
  window.customCards = window.customCards || [];
  if (!window.customCards.some((c) => c.type === "aruba-wifi-card")) {
    window.customCards.push({
      type: "aruba-wifi-card",
      name: "Aruba Wi-Fi Card",
      description: "Thiết bị Wi-Fi theo AP (Aruba Instant): sóng, băng tần, SSID, tải kênh, sức khoẻ radio, cảnh báo",
      documentationURL: "https://github.com/ngoviet/aruba_instant_ha",
    });
  }
  console.info(`%c ARUBA-WIFI-CARD %c v${VERSION} `, "color:#0a1122;background:#f59e0b;font-weight:700", "color:#f59e0b;background:#0a1122");
}

if (typeof window !== "undefined" && window.customElements) defineCard();
