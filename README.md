# Dashboard "Báo cáo sáng" — VITRAN BOUTIQUE HCM

Dashboard web (Streamlit + Plotly) thay cho báo cáo PNG tự động. Hiển thị 3 phần:

1. **Chờ xác nhận** — đơn mới cần xác nhận, thống kê theo sàn / ĐVVC / SKU.
2. **Đã đẩy VC → hủy (7 ngày)** — đơn đã đẩy vận chuyển rồi bị hủy, tách *đã đóng gói* (kho cần lấy lại) / *chưa đóng gói*.
3. **Đơn trả hàng (7 ngày)** — phiếu trả theo trạng thái (đã loại `canceled` = kháng nghị thành công).

---

## Cài đặt

```powershell
pip install -r requirements.txt
```

## Chạy

```powershell
streamlit run app.py
```

Mở trình duyệt tại địa chỉ Streamlit in ra (mặc định http://localhost:8501).

### Ba nguồn dữ liệu (chọn ở sidebar)

| Nguồn | Khi nào dùng | Cách cập nhật |
|-------|--------------|---------------|
| 🟢 **LIVE** | Có cookie/API trong `secrets.toml` | Tự gọi API mỗi 5 phút |
| 📸 **Snapshot** | Dữ liệu **thật** đã chụp sẵn (`snapshot.json`) | Chạy lại `capture_snapshot.js` |
| 🔵 **DEMO** | Chỉ xem giao diện, không cần đăng nhập | (số liệu mẫu cố định) |

App tự chọn nguồn tốt nhất đang có (LIVE > Snapshot > DEMO).

### Cập nhật Snapshot (không cần cookie/API)

1. Mở & đăng nhập `https://vitranboutiquehcm.mysapo.net/admin/orders`.
2. F12 → **Console** → dán toàn bộ nội dung [`capture_snapshot.js`](capture_snapshot.js) → Enter.
3. Đợi ~30 giây → trình duyệt tự tải **`sapo_snapshot.json`** về thư mục Downloads.
4. Chép file đó vào thư mục dự án, đổi tên thành **`snapshot.json`** (đè file cũ) → bấm **🔄** trên dashboard.

> Header dashboard hiển thị "Dữ liệu chụp lúc …" để biết độ mới của snapshot.

---

## Chuyển sang dữ liệu thật tự động (LIVE)

Chọn **một** trong hai cách, khai báo trong `.streamlit/secrets.toml`
(copy từ `.streamlit/secrets.toml.example`):

### Cách A — Cookie phiên (nhanh)
1. Đăng nhập `https://vitranboutiquehcm.mysapo.net/admin` trên Chrome.
2. F12 → **Network** → mở một request tới `/admin/...` → copy header **Cookie**.
3. Dán vào `SAPO_COOKIE` trong `secrets.toml`.
> Nhược: cookie hết hạn phải lấy lại. Khi API báo lỗi 401/403 → lấy cookie mới.

### Cách B — Sapo Open API (ổn định)
1. Tạo **Private App** trong Sapo, lấy `API key` + `secret`.
2. Điền `SAPO_API_KEY` và `SAPO_API_SECRET` trong `secrets.toml`.

> Cũng có thể đặt qua **biến môi trường** cùng tên thay cho `secrets.toml`.

Sau khi cấu hình: tắt DEMO ở sidebar → nhấn **🔄 Làm mới**.

---

## 🔒 Đăng nhập & tài khoản nhân viên

Dashboard yêu cầu đăng nhập (chia sẻ 1 link, mỗi người 1 tài khoản). Khai báo trong `.streamlit/secrets.toml`, mục `[auth.users.*]`.

**Tài khoản test hiện tại** — ⚠️ đổi ngay khi dùng thật:
- `admin` / `vitran@2026` (quản trị)
- `nv01` / `nv01@2026` (nhân viên)

**Thêm/sửa nhân viên:** mở `.streamlit/secrets.toml` thêm khối, lưu rồi reload:
```toml
[auth.users.nv02]
name = "Nguyễn Văn A"
password = "matkhau_tu_dat"
role = "viewer"          # admin hoặc viewer
```
Gửi tên đăng nhập + mật khẩu cho nhân viên qua Zalo. Đăng nhập có nhớ 30 ngày (không phải nhập lại mỗi lần).

## Cấu trúc

| File | Vai trò |
|------|---------|
| `app.py` | Giao diện dashboard (Streamlit + Plotly) |
| `sapo_client.py` | Xác thực + gọi API Sapo (LIVE) |
| `sapo_logic.py` | Logic nghiệp vụ (3 phần) + DEMO + đọc Snapshot |
| `capture_snapshot.js` | Script chụp dữ liệu thật từ Console (tạo `snapshot.json`) |
| `snapshot.json` | Dữ liệu thật đã chụp (nguồn 📸 Snapshot) |
| `.streamlit/secrets.toml` | Credential LIVE (tự tạo, không commit) |

## Quy tắc nghiệp vụ (giữ đúng)
- Múi giờ VN = UTC+7; "hôm nay" tính từ 00:00 VN (= 17:00 UTC hôm trước).
- Chờ xác nhận = `status=open` & `issue_status=pending`.
- Đơn hủy = `status=cancelled` & có `fulfillments` & `cancelled_on` trong 7 ngày.
- Loại trừ kháng nghị thành công: order có phiếu trả `status=canceled` → bỏ khỏi danh sách.
- `packed_status=packed` = đã đóng gói (kho cần lấy lại hàng).

## Tùy chọn nâng cao
- Xuất biểu đồ ra PNG để gửi Zalo: `pip install kaleido` rồi dùng `fig.write_image(...)`.
- Thêm bộ lọc ngày / sàn ở sidebar bằng `st.date_input`, `st.multiselect`.
