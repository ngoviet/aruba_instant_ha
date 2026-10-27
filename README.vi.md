# Aruba Instant cho Home Assistant

[English](README.md) · **Tiếng Việt**

Xem mọi thiết bị Wi-Fi của cụm **Aruba Instant** (IAP) ngay trong Home Assistant: đang bắt AP nào, sóng, băng
tần, SSID, tốc độ PHY. Kèm số thiết bị và độ chiếm kênh của từng AP.

- Đọc đúng API mà giao diện web Instant đang dùng (`https://<ap>:4343/swarm.cgi`) — **không cần bật REST API**,
  không sửa gì trên cụm (chỉ đọc).
- Tự tìm AP **master** trong các AP được khai báo (AP thành viên chỉ thấy client của chính nó) và tự chuyển
  theo khi cụm bầu master mới.
- Dùng lại một phiên quản trị, đăng xuất khi gỡ (Instant giới hạn số phiên quản trị).
- Tuỳ chọn: nếu có cài [routeros_ha](https://github.com/ngoviet/routeros_ha), tên thiết bị lấy từ **comment
  DHCP lease** trên router MikroTik thay cho hostname Wi-Fi kiểu `wlan0`, `espressif`.
- Không thư viện ngoài, cài bằng giao diện, đăng nhập lại, tuỳ chọn, diagnostics, giao diện Anh + Việt.

> Đã chạy trên cụm 3 × **IAP-335**, Instant 8.x. Cần **Home Assistant 2026.9** trở lên.

## Cài đặt

**HACS**: HACS → ⋮ → *Custom repositories* → `https://github.com/ngoviet/aruba_instant_ha`, loại
*Integration* → cài **Aruba Instant** → khởi động lại Home Assistant.

**Cài tay**: chép `custom_components/aruba_instant_ha` vào `/config/custom_components/` rồi khởi động lại.

## Thiết lập

**Cài đặt → Thiết bị & Dịch vụ → Thêm integration → Aruba Instant**

| Ô | Ý nghĩa |
|---|---|
| IP các AP | IP các AP, cách nhau bằng dấu phẩy (vd `192.168.10.51, 192.168.10.52, 192.168.10.53`). Một IP là đủ nếu AP đó luôn là master; khai báo hết thì vẫn chạy khi đổi master |
| Cổng | `4343` (giao diện web Instant) |
| Kiểm tra chứng chỉ SSL | Để tắt với chứng chỉ tự ký mặc định |
| Tên đăng nhập / Mật khẩu | Tài khoản quản trị giao diện web Instant |

Tuỳ chọn: chu kỳ cập nhật (mặc định 60 s, 30–600 s).

## Entity

| Entity | Loại | Ghi chú |
|---|---|---|
| **Aruba Instant · Thiết bị Wi-Fi** | sensor | Tổng số thiết bị Wi-Fi. Thuộc tính: `clients` (danh sách bên dưới), `ssids` (`{ssid: số máy}`), `aps` (từng AP: IP, số client, radio), `conductor` (IP master). Các thuộc tính danh sách **không ghi vào recorder** |
| **&lt;AP&gt; · Thiết bị** | sensor | Số thiết bị đang bắt AP đó |
| **&lt;AP&gt; · Tải kênh 2,4 GHz / 5 GHz** | sensor (%) | Thời gian kênh bận của radio. Thuộc tính: `channel`, `power_dbm`, `noise_dbm` |

Mỗi mục trong `clients`: `name` (comment DHCP lease nếu có, không thì hostname), `hostname`, `ip`, `mac`, `os`,
`essid`, `ap`, `channel`, `band` (`2.4` / `5`), `phy` (`GN`, `AC`…), `signal`, `quality` (`good` / `ok` / `poor`),
`speed_mbps`.

Card hiển thị danh sách này đi kèm [lan-topo-card](https://github.com/ngoviet/lan-topo-card)
(`custom:lan-wifi-card`).

## Phát triển

```bash
pip install -r requirements_test.txt
pytest
```

Test chạy trên Linux (Home Assistant không chạy trên Windows).

<!-- support:start -->
## Ủng hộ dự án

<p align="center">
  <img src="https://raw.githubusercontent.com/ngoviet/.github/main/assets/support/banner.svg" width="720" alt="Built and maintained by one person in Việt Nam">
</p>

<p align="center">
  <a href="https://buymeacoffee.com/ngoviet"><img src="https://raw.githubusercontent.com/ngoviet/.github/main/assets/support/btn-coffee.svg" height="56" alt="Buy me a coffee"></a>
  &nbsp;
  <a href="https://github.com/sponsors/ngoviet"><img src="https://raw.githubusercontent.com/ngoviet/.github/main/assets/support/btn-sponsors.svg" height="56" alt="GitHub Sponsors"></a>
</p>

<p align="center">
  <img src="https://raw.githubusercontent.com/ngoviet/.github/main/assets/support/vietqr-card.svg" width="300" alt="VietQR — MB Bank — NGO DUC VIET — 911051212">
</p>

<p align="center"><sub>🇻🇳 VietQR: quét bằng app ngân hàng bất kỳ, nội dung <code>Ung ho aruba_instant_ha</code>. Cảm ơn bạn! · Thank you for keeping this project alive.</sub></p>
<!-- support:end -->

## Giấy phép

MIT © ngoviet. Không liên quan tới Aruba / HPE; icon là thiết kế riêng.
