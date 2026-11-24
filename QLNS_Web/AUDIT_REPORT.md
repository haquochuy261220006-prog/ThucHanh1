# Báo cáo rà soát QLNS_Web(6)

Ngày rà soát: 24/11/2026

## 1. Phạm vi và kết quả xác minh

- Giải nén và rà soát mã nguồn trong `QLNS_Web(6).zip` (121 tệp trong archive).
- Kiến trúc hiện tại: Flask + PyODBC + SQL Server; không chuyển sang SQLAlchemy.
- Có 8 blueprint nghiệp vụ trong `routes/` và blueprint hợp đồng riêng trong `contracts.py`.
- Schema khởi tạo gồm 8 bảng lõi trong `setup_db.py` và 37 câu lệnh tạo bảng bổ sung trong `schema_setup.py`; một số bảng liên kết được tạo theo nhu cầu ở route.
- `NhanVien.MaNV` là khóa nhân viên trung tâm; các nghiệp vụ công, phép, lương, hợp đồng và tài khoản dùng mã này để liên kết.
- Python syntax check: `python -m compileall -q -f .` — đạt.
- Unit tests hiện có sau khi bổ sung kiểm tra an toàn migration: `python -m pytest -q` — 11 passed, 4 subtests passed.

## 2. Thay đổi đã thực hiện trong lượt rà soát

1. Bỏ lời gọi migration xóa ba bảng `TruongMoRongNhanVien`, `GiaTriMoRongNhanVien`, `NhatKyTruongNhanVien`. Nếu các bảng này tồn tại trong database cũ, migration mới sẽ không xóa chúng.
2. Bổ sung unit test ngăn việc đưa lại lệnh xóa ba bảng trên vào luồng migration.
3. Chuẩn hóa tài liệu thành đúng tám chức năng đã thống nhất:
   - Tài khoản và phân quyền
   - Quản lý phòng ban
   - Quản lý nhân viên
   - Quản lý hợp đồng
   - Quản lý chấm công
   - Quản lý nghỉ phép
   - Quản lý tiền lương
   - Thống kê và báo cáo
4. Ghi rõ Dashboard chỉ là trang tổng quan dùng chung, không tính là chức năng thứ 9.
5. Bổ sung cảnh báo phải sao lưu và xác nhận khả năng khôi phục trước mỗi migration.

## 3. Các điểm cần xử lý ở giai đoạn tiếp theo

### Ưu tiên cao — Kiểm thử tích hợp SQL Server

Chưa có SQL Server/database staging trong môi trường rà soát. Cần kiểm tra migration trên bản sao database trước khi chạy với dữ liệu thật, đặc biệt các bảng lõi, ràng buộc khóa ngoại, dữ liệu công cũ, dữ liệu nghỉ phép và kỳ lương.

### Ưu tiên cao — Xác minh chạy ứng dụng

Môi trường thực hiện có Python 3.13.5 nhưng thiếu Flask và các thư viện runtime; không có mạng để cài dependency. Vì vậy chưa thể import Flask app, dựng route map hoặc kiểm thử giao diện/API trong lượt này. Cần cài `requirements.txt` trên máy Windows/VS Code của dự án và chạy smoke test.

### Ưu tiên cao — Kiểm tra phân quyền theo vai trò

Mã nguồn có các vai trò `QuanTri`, `QuanTriHeThong`, `HR`, `KeToan`, `QuanLy`, `NhanVien`. Cần chạy ma trận 401/403 cho từng route, bao gồm thử truy cập ID của nhân viên khác ở ảnh, hồ sơ, hợp đồng, chấm công, nghỉ phép và phiếu lương.

### Ưu tiên trung bình — Đồng bộ dữ liệu và quy tắc nghiệp vụ

Cần kiểm thử các luồng liên kết đầu-cuối: tạo nhân viên → tài khoản → hợp đồng → chấm công → nghỉ phép → tính lương → phiếu lương → báo cáo. Kiểm tra thay đổi nguồn dữ liệu có làm mất hiệu lực kỳ lương nháp đúng quy tắc hay không.

### Ưu tiên trung bình — Phân định xóa và ngừng hoạt động

Một số route có thao tác xóa. Với nhân viên/hợp đồng đã có lịch sử, mã hiện tại đã có chặn xóa trong nhiều trường hợp; cần test cả các trường hợp còn lại. Nên ưu tiên chuyển trạng thái/ngừng sử dụng thay vì xóa vật lý dữ liệu đã tham gia nghiệp vụ.

### Ưu tiên trung bình — Phụ thuộc ngoài

`requirements.txt` chưa khóa phiên bản chính xác. AI soạn hợp đồng, SMTP/Twilio, nhận diện khuôn mặt và xuất tài liệu cần được kiểm thử riêng; đây không phải điều kiện để xác nhận các luồng CRUD và database cơ bản.

## 4. Giới hạn xác nhận

Kết quả 11 tests hiện có chủ yếu là unit/static-contract tests; không chứng minh ứng dụng đã chạy với SQL Server thật. Không tuyên bố tám chức năng đã hoàn thiện toàn bộ cho đến khi hoàn tất kiểm thử tích hợp và kiểm thử người dùng trên database staging.

## 5. Bổ sung hướng dẫn SQL Server/SSMS (24/11/2026)

- Xác nhận lại: dự án vốn đã kết nối SQL Server qua `pyodbc`; không có chuyển đổi từ SQLite/MySQL/PostgreSQL cần thực hiện.
- Bổ sung `SQL_SERVER_SSMS_GUIDE.md` hướng dẫn cài ODBC, tạo database trong SSMS, cấu hình Windows Authentication, tạo schema bằng `setup_db.py`, nâng cấp schema và chạy ứng dụng.
- Bổ sung `sqlserver/00_create_database.sql`: chỉ tạo `NHANSU_PY` nếu chưa tồn tại; không drop/recreate database và không xóa dữ liệu.
- Bổ sung `sqlserver/01_inspect_database.sql`: xem bảng, số dòng ước lượng, khóa ngoại, trạng thái migration và các bảng lõi.
- Bổ sung ba kiểm thử tĩnh cho script SSMS. Tổng unit/static tests hiện chạy được: 14 passed, 4 subtests passed.
- Chưa thể kết nối SSMS/SQL Server thật từ môi trường thực hiện; chưa chạy DDL/migration trên database của người dùng.
