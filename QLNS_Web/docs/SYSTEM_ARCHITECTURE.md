# Cấu trúc dự án

Ứng dụng vẫn khởi chạy tại `app.py`; các package bên dưới tách trách nhiệm theo lớp. Những file ở thư mục gốc như `db.py`, `contracts.py`, `permissions.py`, `migrate_db.py`, `setup_db.py`, `payroll.py` và `seed_sample.py` là lớp tương thích cho hướng dẫn hoặc import cũ. Mã mới nên dùng đường dẫn package.

## Các lớp chính

- `database/`: kết nối SQL Server, thiết lập schema và lệnh migration. `database/migrations/` hiện chứa script hỗ trợ SSMS; schema ứng dụng vẫn được quản lý bằng migration Python.
- `routes/`: Flask Blueprint theo phân hệ; mỗi module xử lý HTTP và gọi service.
- `services/`: logic nghiệp vụ dùng chung; các dịch vụ chấm công, lương, báo cáo và AI được nhóm theo package.
- `utils/`: quyền, xác thực route, kiểm tra dữ liệu, export và tiện ích dùng chung.
- `templates/`: giao diện Jinja theo phân hệ; `static/css/` và `static/js/` chứa tài nguyên trình duyệt.
- `tests/`: kiểm thử tự động; `docs/`: hướng dẫn, thiết kế và tài liệu kiểm toán.
- `scripts/`: tác vụ quản trị và seed dữ liệu; `instance/`: dữ liệu cấu hình cục bộ không đưa lên Git.

Một số phần hiện chưa tách thành service riêng: luồng KPI vẫn nằm trong `routes/kpi_routes.py`, còn đăng ký tăng ca là một phần của `routes/attendance_routes.py`. Các script SQL hiện có chỉ hỗ trợ SSMS; migration schema thực tế chạy qua `database/schema_setup.py` và `database/schema_migrations.py`, nên chưa tạo các file SQL migration đánh số giả lập.

## Quy ước mở rộng

Khi thêm chức năng, đặt route trong `routes/*_routes.py`, logic nghiệp vụ trong `services/<module>/`, template trong `templates/<module>/`, và dùng `database/schema_setup.py` cùng `database/schema_migrations.py` khi thay đổi schema. Không tạo module rỗng để lấp đầy cây thư mục; chỉ tách service khi có logic nghiệp vụ thực sự cần được dùng lại hoặc kiểm tra độc lập.
