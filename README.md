# QLNS Web — Flask + SQL Server

Bản giao diện web chuyển từ ứng dụng Python/Tkinter sang Flask, tiếp tục sử dụng SQL Server và các bảng hiện có. Giao diện responsive cho máy tính và điện thoại.

## 1. Yêu cầu
- Windows 10/11
- Python 3.10 trở lên
- Microsoft ODBC Driver 17 hoặc 18 for SQL Server
- SQL Server Express/SQL Server đã chạy và có database `NHANSU_PY` cùng các bảng của dự án

## 2. Cấu hình kết nối
Mở `config.py` và chỉnh `SERVER` đúng với tên instance trên máy. Ví dụ:
- `localhost\\SQLEXPRESS`
- `localhost\\SQLEXPRESS03`
- `localhost` (nếu dùng default instance)

`DATABASE` mặc định là `NHANSU_PY`. Windows Authentication đang bật (`WINDOWS_AUTH = True`), nên tài khoản Windows chạy Flask cần quyền truy cập database. Không đưa ứng dụng ra Internet khi đang dùng cấu hình thử nghiệm.

## 3. Cài đặt và chạy
Mở terminal VS Code tại thư mục này:
```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python app.py
```
Mở trình duyệt: http://127.0.0.1:5000

Tài khoản mẫu nếu database được tạo bằng `setup_db.py`: `admin` / `admin123`. Chỉ chạy `python setup_db.py` nếu bạn muốn tạo database/bảng mẫu và đã xác nhận cấu hình `config.py` đúng. Sao lưu database trước khi chạy trên dữ liệu thật.

## 4. Tính năng trong bản web
- Đăng nhập/đăng xuất và đổi mật khẩu
- Tổng quan nhân sự
- Quản lý nhân viên, phòng ban, chức vụ, hợp đồng (thêm/sửa/xóa/tìm kiếm/xuất CSV)
- Chấm công vào/ra
- Gửi và duyệt đơn nghỉ phép
- Xem bảng lương, báo cáo tổng hợp
- **Soạn hợp đồng bằng AI và xuất file Word (.docx)** (menu Quản trị dữ liệu → Soạn HĐ bằng AI, hoặc nút "Soạn Word" ở từng dòng trong trang Hợp đồng)

Lưu ý: bản web chưa triển khai tạo tài khoản qua giao diện và chưa thay thế đầy đủ tính năng tính lương nâng cao của ứng dụng desktop. Hãy thử trên bản sao database trước.

## 5. Soạn hợp đồng bằng AI (Word)
1. Cài thư viện mới: `python -m pip install -r requirements.txt` (thêm `python-docx`, `anthropic`).
2. Lấy API key tại https://console.anthropic.com rồi đặt biến môi trường (PowerShell):
   ```powershell
   setx ANTHROPIC_API_KEY "sk-ant-..."
   ```
   Mở lại terminal. Không có key vẫn dùng được, hệ thống sẽ xuất theo mẫu điều khoản chuẩn.
3. Mở `config.py`, sửa mục `COMPANY` (tên, địa chỉ, MST, người đại diện). Nút **Kiểm tra kết nối AI** trên trang soạn hợp đồng cho biết kết nối đã thông chưa.
   - Tick **Cho AI tra cứu web** để Claude tra quy định mới nhất (lương tối thiểu vùng, thử việc, báo trước...) và cảnh báo "LƯU Ý HR" nếu lương thấp hơn mức tối thiểu.
   - Muốn dùng AI khác: đặt `AI_PROVIDER = "openai"`, điền `OPENAI_API_KEY`, `OPENAI_BASE_URL`, `OPENAI_MODEL` (không có tra cứu web).
4. Quy trình: chọn hợp đồng → nhập yêu cầu bổ sung → AI soạn điều khoản → chỉnh sửa trực tiếp hoặc nhờ AI sửa → tải `.docx`.

Bảo mật: thông tin nhân viên (họ tên, CCCD, SĐT, địa chỉ, email) được ghép vào file Word ngay trên máy chủ của bạn, **không gửi cho AI**. AI chỉ nhận chức danh, phòng ban, loại HĐ, ngày, mức lương và yêu cầu bạn nhập. Nội dung AI soạn chỉ là bản nháp, cần nhân sự/pháp chế rà soát trước khi ký.

### Các loại hợp đồng hỗ trợ
Thử việc · Có thời hạn · Không thời hạn · Thời vụ · Bán thời gian · Học việc · Cộng tác viên (hợp đồng dịch vụ, theo Bộ luật Dân sự) · Đào tạo (cam kết làm việc và hoàn trả chi phí). Mỗi loại có tiêu đề, căn cứ pháp lý, cách gọi hai bên và mẫu điều khoản riêng.
Muốn thêm loại mới: thêm một dòng vào `TYPES` trong `contracts.py` và thêm tên loại vào danh sách `choice:` của mục `hopdong` trong `app.py`.

### Cách chọn dữ liệu khi soạn
- **Soạn mới** (mặc định): chọn nhân viên + loại hợp đồng + ngày + lương (tự điền theo lương cơ bản). Có thể tick "Đồng thời lưu hợp đồng vào danh sách Hợp đồng" khi tải file.
- **Dùng hợp đồng đã có**: chọn từ danh sách các hợp đồng đã nhập trong hệ thống.

## 6. Dữ liệu mẫu để dùng thử
Sau khi chạy `setup_db.py`, chạy thêm:
```
python seed_sample.py
```
Lệnh này thêm 10 nhân viên mẫu (đủ 5 phòng ban) và 9 hợp đồng mẫu đủ các loại (Không thời hạn, Có thời hạn, Thử việc, Thời vụ, Bán thời gian, Học việc, Cộng tác viên). Chạy lại nhiều lần không bị trùng. Họ tên, CCCD, SĐT trong dữ liệu mẫu đều là dữ liệu giả.
