# Rà soát bảo mật trước triển khai

Ngày rà soát mã nguồn: 24/11/2026  
Phạm vi: kiểm tra tĩnh mã nguồn Flask, route/API, phân quyền, truy vấn SQL, schema/migration, cấu hình, tài liệu backup/restore và bộ kiểm thử có trong repository `QLNS_Web(6)`.

## Kết luận

Dự án đã có nhiều lớp bảo vệ tốt hơn so với một ứng dụng CRUD cơ bản: đăng nhập, CSRF, kiểm tra quyền phía máy chủ, thu hồi phiên qua `SecurityVersion`, schema migration tách khỏi request web, mã hóa tài liệu và một phần audit dữ liệu nhạy cảm. Tuy nhiên, **chưa đủ bằng chứng để xác nhận hệ thống sẵn sàng triển khai production** vì chưa chạy ứng dụng với đầy đủ dependencies, chưa kết nối database SQL Server staging và chưa diễn tập backup/restore.

Không chạy `setup_db.py` hoặc `migrate_db.py` trên database đang có dữ liệu thật trong giai đoạn rà soát này. Mọi kiểm thử migration phải dùng bản restore staging, có đối chiếu số dòng trước/sau.

## Kiểm soát đã thấy trong mã nguồn

- `app.py` kiểm tra phiên bản schema đã hoàn tất trước khi phục vụ request; migration được thực hiện riêng bằng `migrate_db.py`, không tự sửa schema trong request web.
- `app.py` có CSRF middleware cho POST/PUT/PATCH/DELETE; `static/app.js` bổ sung token cho form POST và fetch; API khuôn mặt dùng cơ chế token riêng.
- `permissions.py` định nghĩa sáu vai trò: `QuanTri`, `QuanTriHeThong`, `HR`, `KeToan`, `QuanLy`, `NhanVien`. Các route nghiệp vụ gọi kiểm tra quyền phía máy chủ; quyền chi tiết vẫn cần xác minh động bằng ma trận endpoint.
- `SecurityVersion` được kiểm tra lại từ database trên request đã đăng nhập, giúp thu hồi phiên khi tài khoản/role thay đổi hoặc nhân viên nghỉ việc.
- Mật khẩu được hash; truy vấn SQL chủ yếu truyền tham số qua PyODBC.
- Tài liệu hồ sơ và vector khuôn mặt được mã hóa bằng khóa lấy từ biến môi trường. Mất khóa có thể làm dữ liệu đã mã hóa không thể đọc lại.
- `README.md`, `BACKUP_RESTORE.md` và `scripts/backup_sqlserver.ps1` đã mô tả quy trình backup/restore. Script có `CHECKSUM` và `RESTORE VERIFYONLY`; đây chưa phải bằng chứng đã restore thành công.
- Các test hiện có tập trung vào hợp đồng chấm công khuôn mặt, ánh xạ quyền và một số hành vi migration.

## Rủi ro còn lại và mức ưu tiên

### Cao — Chưa kiểm thử tích hợp với SQL Server

Chưa xác minh cài mới, nâng cấp từ database cũ, quyền SQL runtime, transaction, race condition chấm công, thu hồi phiên đa worker hoặc dữ liệu sau migration. Unit test không thay thế kiểm thử SQL Server thật.

**Cần làm:** chạy checklist trong `INTEGRATION_TEST_PLAN.md` trên database staging được restore từ backup; ghi nhận số dòng và kết quả từng vai trò.

### Cao — Chưa diễn tập restore

Repository có hướng dẫn và script backup, nhưng chưa có bằng chứng backup/restore thực tế, `DBCC CHECKDB`, kiểm tra dữ liệu nghiệp vụ hoặc khôi phục khóa mã hóa.

**Cần làm:** chạy backup vào vị trí được bảo vệ, sao chép bản backup ra nơi độc lập, restore sang database mới, kiểm tra toàn vẹn và mở ứng dụng staging. Không ghi đè database nguồn.

### Cao — Chấm công khuôn mặt chưa phải bằng chứng chống giả mạo độc lập

Video được xử lý trên thiết bị; server nhận vector, nonce và kết quả/điểm thử thách do client gửi. Client có thể bị can thiệp và ngưỡng chưa được hiệu chuẩn đại diện. Không dùng kết quả khuôn mặt làm căn cứ duy nhất cho lương/kỷ luật nếu chưa có đánh giá FAR/FRR và quy trình dự phòng.

**Cần làm:** kiểm thử thiết bị/ánh sáng thực tế, quy trình khiếu nại và cân nhắc nhà cung cấp liveness xác minh phía máy chủ cho môi trường rủi ro cao.

### Cao — Quyền theo vai trò và dữ liệu nhạy cảm cần kiểm thử sâu

Mã nguồn có sáu vai trò, nhưng cần xác minh từng endpoint/API và từng ID tài nguyên; không chỉ kiểm tra việc ẩn nút trên giao diện. Phạm vi audit truy cập CCCD, liên hệ, lương, hợp đồng và xuất file chưa bao phủ toàn bộ đường đọc.

**Cần làm:** thực hiện ma trận 401/403/200 theo vai trò, thử đổi ID để phát hiện IDOR, rà soát dữ liệu trả về trong HTML/API/CSV/XLSX/PDF và hoàn thiện audit cho các đường xuất/đọc còn thiếu.

### Trung bình — Giới hạn đăng nhập sai nằm trong bộ nhớ tiến trình

`services/auth_service.py` lưu `_login_fails` trong dict toàn cục. Bộ đếm mất khi khởi động lại và không chia sẻ giữa nhiều worker/máy chủ.

**Cần làm:** trước khi scale, chuyển bộ đếm sang Redis hoặc kho dùng chung; giới hạn theo tài khoản và nguồn mạng, có thời gian chờ tăng dần và giám sát đăng nhập bất thường.

### Trung bình — Chưa khóa phiên bản dependencies

`requirements.txt` dùng các ràng buộc phiên bản tối thiểu, chưa có lockfile và chưa có kết quả audit dependency gắn với môi trường triển khai.

**Cần làm:** tạo môi trường build sạch, khóa phiên bản đã kiểm thử, rà lỗ hổng dependency và cập nhật có kiểm soát.

### Trung bình — Chính sách lương chưa đủ để sử dụng trả lương pháp lý

`PAYROLL_POLICY_GUIDE.md` và README nêu rõ tỷ lệ thuế/bảo hiểm phải được doanh nghiệp cấu hình, duyệt; hiện chính sách còn đơn giản, chưa tách đầy đủ nhóm vùng/hợp đồng và các loại OT ngày thường/ngày nghỉ/ngày lễ/ban đêm.

**Cần làm:** xác nhận chính sách với nhân sự/kế toán/pháp chế, tạo bộ dữ liệu kiểm thử chuẩn và đối soát kết quả trước khi dùng cho trả lương thật.

### Trung bình — AI soạn hợp đồng và chữ ký

Nội dung AI chỉ là bản nháp và cần người có thẩm quyền rà soát. Ảnh chữ ký vẽ hoặc việc tải lên tài liệu không thay thế xác minh chữ ký số/chứng thư.

**Cần làm:** không gửi dữ liệu cá nhân không cần thiết tới nhà cung cấp AI; cấu hình secret qua kho bí mật; nếu cần ký số có giá trị xác minh, tích hợp nhà cung cấp chữ ký số và kiểm tra chứng thư/trạng thái.

### Thấp — Cấu hình TLS SQL Server

`config.py` mặc định `TrustServerCertificate=yes` cho môi trường phát triển; trong `APP_ENV=production`, mặc định chuyển thành `no`. Cần xác minh chứng thư máy chủ và cấu hình reverse proxy/TLS ở môi trường thật, không chỉ dựa vào giá trị mặc định.

## Giới hạn của lượt rà soát này

- Đã chạy `python -m compileall -q .`: thành công.
- Đã chạy `python -m unittest discover -s tests -v`: 11/11 test thành công.
- Chưa import/khởi chạy được Flask app trong môi trường rà soát vì package `flask` chưa được cài; do đó chưa có route map runtime hoặc kiểm thử HTTP.
- Chưa kết nối SQL Server staging; không xác nhận được schema thực tế, migration, quyền database hoặc nghiệp vụ lưu/đọc dữ liệu.
- Không có repository `.git` trong gói nên không thể rà lịch sử commit/secret trong Git history.
- Chưa thực hiện penetration test, dependency audit, backup hoặc restore thực tế.

## Tài liệu kiểm thử tiếp theo

Thực hiện theo `INTEGRATION_TEST_PLAN.md` và `BACKUP_RESTORE.md`. Mọi thao tác migration/restore phải dùng database staging riêng; lưu biên bản kết quả, số dòng trước/sau và log lỗi đã loại bỏ bí mật/PII.
