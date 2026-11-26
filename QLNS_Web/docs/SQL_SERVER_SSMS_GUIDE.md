# Kết nối QLNS Web với SQL Server bằng SSMS

## Kết luận về công nghệ hiện tại

QLNS_Web(6) **đã dùng Microsoft SQL Server**, không dùng SQLite/MySQL/PostgreSQL. Backend truy cập SQL Server bằng `pyodbc`; schema và nâng cấp database được quản lý bởi `setup_db.py`, `schema_setup.py` và `migrate_db.py`. SSMS là công cụ để tạo, xem và quản trị database; không thay thế backend Flask.

## A. Chuẩn bị trên Windows

1. Cài SQL Server Express hoặc SQL Server Developer và khởi động đúng instance.
2. Cài SQL Server Management Studio (SSMS).
3. Cài Microsoft ODBC Driver 17 hoặc 18 for SQL Server.
4. Mở SSMS, kết nối bằng Windows Authentication tới instance đang chạy, ví dụ `localhost\\SQLEXPRESS03`.

## B. Tạo database trong SSMS

1. Mở file `database/migrations/00_create_database.sql`.
2. Chọn đúng instance trong SSMS và nhấn Execute (F5).
3. Refresh Databases; phải thấy `NHANSU_PY`.

Script chỉ tạo database khi chưa tồn tại. Nếu database đã có thì không drop, không tạo lại và không xóa dữ liệu. Không chạy trên database có dữ liệu quan trọng trước khi backup.

## C. Cấu hình ứng dụng Flask

Mở PowerShell tại thư mục gốc `QLNS_Web` và chạy:

```powershell
python -m venv .venv
& .\.venv\Scripts\python.exe -m pip install --upgrade pip
& .\.venv\Scripts\python.exe -m pip install -r requirements.txt
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
# C? th? b? qua l?nh t?o venv n?u .venv ?? t?n t?i; s?a c?u h?nh trong .env tr??c khi ch?y.

$env:DB_SERVER = 'localhost\SQLEXPRESS03'
$env:DB_NAME = 'NHANSU_PY'
$env:DB_DRIVER = 'ODBC Driver 18 for SQL Server'
$env:DB_WINDOWS_AUTH = 'true'
$env:DB_ENCRYPT = 'yes'
$env:DB_TRUST_SERVER_CERTIFICATE = 'yes'
```

Nếu máy đã cài ODBC Driver 17, đổi `DB_DRIVER` thành `ODBC Driver 17 for SQL Server`. `DB_SERVER` phải khớp tên server trong cửa sổ Connect của SSMS. Nếu instance của bạn khác, sửa giá trị này.

Với Windows Authentication, Python phải chạy bằng tài khoản Windows có quyền trên database. Khi phát triển cục bộ, có thể cấp `db_owner` cho tài khoản Windows phát triển; không dùng quyền này cho tài khoản ứng dụng production. Nếu dùng SQL Server Authentication, đặt `DB_WINDOWS_AUTH=false`, `DB_USER` và `DB_PASSWORD` trong phiên PowerShell, không ghi mật khẩu vào source code.

## D. Tạo bảng lần đầu

Sau khi đã tạo database và cấu hình kết nối, chạy:

```powershell
& .\.venv\Scripts\python.exe -m database.setup_db
```

Lệnh này tạo các bảng còn thiếu, bổ sung schema và tạo tài khoản quản trị ban đầu nếu chưa có. Mật khẩu admin được in ra đúng một lần; hãy lưu lại. Không chạy `setup_db.py` trên dữ liệu thật trước khi backup và xác nhận đúng `DB_SERVER`/`DB_NAME`.

Nếu database đã có dữ liệu và chỉ cần nâng cấp schema, hãy dừng Flask trước, backup database, rồi chạy quy trình migration theo `README.md` và `BACKUP_RESTORE.md`. Không dùng `setup_db.py` để thay thế quy trình nâng cấp có kiểm soát trên dữ liệu thật.

## E. Kiểm tra trong SSMS

1. Mở `database/migrations/01_inspect_database.sql`.
2. Chạy toàn bộ bằng F5.
3. Kiểm tra danh sách bảng, khóa ngoại, các bảng lõi và trạng thái `QlnsSchemaVersion`.
4. Nếu `IsComplete=0`, không khởi động ứng dụng như thể migration đã hoàn tất; cần xem lỗi migration và xử lý trên bản backup/staging.

## F. Chạy web

```powershell
& .\.venv\Scripts\python.exe app.py
```

Mở `http://127.0.0.1:5000`. Đăng nhập bằng tài khoản admin được tạo ở bước D.

## Lưu ý quan trọng

- SSMS không tự động chuyển database sang SQL Server: dự án đã kết nối SQL Server từ trước.
- Không xóa database hoặc bảng để “làm sạch” nếu muốn giữ dữ liệu.
- Luôn backup `.bak` và kiểm tra khả năng restore trước migration.
- Bản rà soát hiện tại chưa được kiểm thử với SQL Server thật trong môi trường ChatGPT; cần thực hiện trên máy Windows/instance của bạn.
