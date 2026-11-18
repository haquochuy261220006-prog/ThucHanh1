# Employee Master Profile

## Phạm vi

Hồ sơ nhân viên chuẩn là nguồn dữ liệu nhân sự dùng chung cho tám phân hệ. Mã NhanVien.MaNV là khóa nội bộ chính; mã hiển thị NhanVien.MaNVHT chỉ để trình bày. Hồ sơ này bao gồm CRUD, tìm kiếm/lọc, ảnh, lịch sử công tác, tài liệu điện tử và trường tùy chỉnh.

## Quy tắc dữ liệu

- MaNV do SQL Server cấp, không thay đổi khi chỉnh hồ sơ và không tái sử dụng.
- Chấm công, nghỉ phép, hợp đồng, bảng lương và tài khoản tham chiếu cùng một MaNV.
- employee_profiles.create_employee() tạo hồ sơ từ biểu mẫu có khóa gửi lại an toàn để tránh tạo trùng.
- Dữ liệu lịch sử nghiệp vụ được giữ khi nhân viên chuyển trạng thái nghỉ việc.
- Không xóa MaNV, hồ sơ điện tử hoặc bảng lịch sử khỏi database khi thu gọn ứng dụng.

## Phân quyền và an toàn

- Quyền kiểm tra ở route; ẩn liên kết giao diện không thay thế kiểm tra phía máy chủ.
- Thay đổi hồ sơ, lịch sử công tác và truy cập trường nhạy cảm phải theo quyền hiện hành và có audit.
- Khi chuyển nhân viên từ đang làm sang đã nghỉ việc, ứng dụng vô hiệu phiên tài khoản, xóa mẫu khuôn mặt và ghi nhật ký trước khi hoàn tất cập nhật.
- Dữ liệu có trong các phân hệ đã bỏ khỏi ứng dụng vẫn được giữ trong database hiện hữu.

## Khởi tạo database

setup_db.py tạo các bảng nền cho tám phân hệ rồi gọi ensure_schema() để thêm schema nghiệp vụ cần thiết. Không dùng trình khởi tạo này thay cho migration production. Chỉ xác minh trên database thử nghiệm có thể khôi phục.
