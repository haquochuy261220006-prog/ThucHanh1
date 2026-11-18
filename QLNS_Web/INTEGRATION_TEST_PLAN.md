# Kiểm thử tích hợp trước khi triển khai

Chạy toàn bộ checklist trên **database staging riêng**, tốt nhất là bản sao mới nhất của production. Không chạy `setup_db.py`, `migrate_db.py`, thao tác thu hồi phiên hoặc stress test trên database đang phục vụ người dùng. Không đưa mật khẩu vào lệnh được lưu trong PowerShell history.

## 1. Cài mới

- [ ] Tạo database staging mới và cấu hình tài khoản migration có quyền tạo bảng/sửa dữ liệu.
- [ ] Chạy `python setup_db.py` theo đúng `DB_SERVER`/`DB_NAME` của database rỗng; kiểm tra bảng lõi `NhanVien`, `TaiKhoan`, `ChamCong`, `NghiPhep`, `HopDong`, `Luong` tồn tại.
- [ ] Xác nhận `dbo.QlnsSchemaVersion` có phiên bản hiện tại `2026.11.16.1`, `IsComplete=1`.
- [ ] Chạy web bằng tài khoản ứng dụng riêng; đăng nhập và mở dashboard, nhân viên, chấm công.
- [ ] Kết nối bằng tài khoản web và xác nhận đọc được dòng phiên bản schema, nhưng lệnh `CREATE TABLE`/`ALTER TABLE` bị từ chối.

## 2. Nâng cấp database hiện có

1. Restore bản backup production gần nhất vào staging. Ghi lại số dòng trước nâng cấp của `NhanVien`, `ChamCong`, `NghiPhep`, `HopDong`, `Luong`, `TaiKhoan`.
2. Dừng toàn bộ web worker trỏ vào staging và tạo thêm backup staging.
3. Chạy `python migrate_db.py` bằng migration identity; xác nhận lệnh kết thúc với mã 0 và `IsComplete=1`.
4. Chạy lại lệnh để xác nhận nâng cấp idempotent; xác nhận số dòng nghiệp vụ không mất hoặc nhân đôi ngoài thay đổi migration đã dự kiến.
5. Khởi động web, xác nhận route nghiệp vụ hoạt động. Thử kết nối bằng app identity và xác nhận DDL bị từ chối.
6. Nếu migration lỗi, giữ web dừng, kiểm tra log, restore backup staging hoặc sửa migration rồi chạy lại; không đánh dấu phiên bản hoàn tất thủ công.

## 3. Ma trận quyền

Dùng tài khoản staging riêng cho `QuanTri`, `QuanTriHeThong`, `HR`, `KeToan`, `QuanLy`, `NhanVien`. Với mỗi vai trò, thử trực tiếp request GET/POST (không chỉ ẩn nút giao diện):

- [ ] HR xem/sửa trường hồ sơ theo quyền trường, xem hợp đồng/hồ sơ và nhật ký; route không được cấp quyền trả 403.
- [ ] Kế toán thao tác/xuất lương theo trạng thái kỳ; không đọc hồ sơ nhân viên không được cấp.
- [ ] Quản lý xem đội được gán trực tiếp, duyệt đơn theo phạm vi; không đọc CCCD/lương/tài liệu hồ sơ.
- [ ] Nhân viên chỉ đọc/sửa phần tự phục vụ của chính mình.
- [ ] Quản trị hệ thống không thể gán vai trò `QuanTri`; quản trị cấp cao có thể thực hiện thao tác được phép.
- [ ] Xuất file qua POST/route trực tiếp cũng bị từ chối khi thiếu quyền; kiểm tra nhật ký truy cập cho thao tác hợp lệ.

Ghi lại vai trò, endpoint, mã HTTP và kết quả mong đợi/thực tế; không dùng dữ liệu nhân sự thật trong ảnh chụp/biên bản.

## 4. Thu hồi phiên đăng nhập

- [ ] Đăng nhập bằng tài khoản staging trong hai trình duyệt/phiên độc lập.
- [ ] Đổi mật khẩu, vô hiệu hóa hoặc đổi vai trò tài khoản từ phiên quản trị.
- [ ] Dùng cookie phiên cũ truy cập trang yêu cầu đăng nhập; phiên cũ phải bị xóa/chuyển về trang đăng nhập, phiên mới cũng phải đăng nhập lại khi `SecurityVersion` thay đổi.
- [ ] Xác nhận luồng OTP/tài khoản và tài khoản nghỉ việc cũng thu hồi phiên theo trạng thái dự kiến.

## 5. Chấm công đồng thời

- [ ] Tạo một nhân viên staging đang làm và chưa có sự kiện chấm công cho ngày thử.
- [ ] Gửi đồng thời hai request chấm vào hợp lệ cho cùng nhân viên/ngày từ hai phiên; không dùng face liveness giả lập để kết luận chất lượng nhận diện.
- [ ] Kết quả mong đợi: đúng một request tạo sự kiện `in`; request còn lại nhận lỗi nghiệp vụ có thể hiểu được; có đúng một dòng tổng hợp ngày trong `ChamCong`.
- [ ] Thử chu kỳ vào → ra → vào và chấm qua ca đêm; kiểm tra `ChamCongSuKien`, ngày công và dòng tổng hợp nhất quán.
- [ ] Xác nhận không có transaction treo hoặc hai sự kiện `in` liên tiếp do race.

## 6. Chữ ký hợp đồng và khuôn mặt

Chữ ký vẽ hiện tại chỉ là ảnh nét vẽ được nhúng vào tài liệu; tải lên bản hợp đồng đã ký là thao tác HR xác nhận, không phải xác minh chứng thư. Luồng liveness đang tin kết quả/điểm từ trình duyệt, nên kiểm thử staging không biến nó thành chống giả mạo được chứng nhận. Trước khi bật như bằng chứng ký hoặc căn cứ duy nhất cho lương/kỷ luật:

- [ ] Chọn nhà cung cấp chữ ký số, hoàn tất hợp đồng dịch vụ, sandbox, chứng thư và yêu cầu lưu trữ/xác minh.
- [ ] Chọn dịch vụ liveness/face match có đánh giá phù hợp, chạy thử thiết bị thật và quy trình dự phòng.
- [ ] Kiểm thử callback/webhook có xác thực, đối chiếu hash tài liệu đã ký, danh tính người ký, thời điểm và trạng thái thu hồi chứng thư.
- [ ] Ghi nhận tỷ lệ nhận sai/chấp nhận sai trên thiết bị và ánh sáng đại diện; duyệt quy trình khiếu nại thủ công.

## Kết quả lần rà soát hiện tại

- Cơ chế tự sửa schema theo request đã được thay bằng cổng chỉ đọc phiên bản schema; migration được chạy từ tiến trình riêng.
- Chưa chạy được kiểm thử SQL Server trong môi trường lập trình hiện tại: chưa có biến cấu hình staging/database; kết nối mặc định tới SQL Server cục bộ thất bại ở ODBC 17/TLS và không tới được instance. Chưa có bằng chứng cài mới/nâng cấp, quyền SQL thực tế, session revoke hoặc concurrency trên SQL Server.
- Chưa có nhà cung cấp/chứng thư cho chữ ký số hoặc liveness; các luồng này cần quyết định dịch vụ và cấu hình sandbox trước khi có thể triển khai/xác minh.
