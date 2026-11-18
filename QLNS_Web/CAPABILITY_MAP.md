# Bản đồ 8 phân hệ HR đang giữ lại

## Phạm vi

Ứng dụng tập trung vào tám phân hệ người dùng: Dashboard, Nhân viên, Phòng ban/chức vụ, Chấm công, Nghỉ phép, Hợp đồng, Tiền lương và Báo cáo. Đăng nhập, phân quyền, audit, tài khoản, xuất tệp và cơ sở dữ liệu là năng lực nền dùng chung.

## Bản đồ năng lực

| Phân hệ | Năng lực đang giữ |
|---|---|
| Dashboard | Chỉ số tổng quan và danh sách nhân viên gần đây |
| Nhân viên | Hồ sơ chuẩn theo MaNV, CRUD, tìm kiếm/lọc, lịch sử công tác, tài liệu điện tử và trường hồ sơ tùy chỉnh |
| Phòng ban/chức vụ | Đơn vị, phòng ban, chức danh, vị trí công việc, sơ đồ tổ chức, điều chuyển |
| Chấm công | Sự kiện vào/ra, đối soát và sửa bản ghi, chấm công khuôn mặt, ca và tăng ca |
| Nghỉ phép | Đơn nghỉ, duyệt, kiểm tra trùng lịch, lịch làm việc và quỹ phép |
| Hợp đồng | Mẫu, nhập/trích xuất tệp, soạn thảo AI dạng nháp, vòng đời và phiên bản |
| Tiền lương | Tính lương, điều chỉnh, chính sách, phê duyệt, khóa kỳ, phiếu lương |
| Báo cáo | Lọc kỳ, tổng hợp nhân sự/công/phép/lương, biểu đồ và xuất CSV/Excel/PDF |

## Quy tắc dữ liệu

- NhanVien.MaNV là khóa nhân viên dùng chung; các bảng nghiệp vụ tham chiếu mã này.
- Các lần chấm công được lưu trong nguồn sự kiện và tổng hợp vào bảng công ngày để tương thích.
- Phiếu lương và bảng lương dùng chung dữ liệu kỳ; quyền xem phụ thuộc vai trò.
- Nhật ký quan trọng và dữ liệu nhạy cảm tiếp tục được giới hạn theo quyền.

## Ngoài phạm vi ứng dụng hiện tại

Các màn hình riêng về tuyển dụng, onboarding/offboarding, tài sản, KPI, đào tạo/kỹ năng, phúc lợi và hoạch định nhân lực đã được gỡ khỏi giao diện và route. Bảng dữ liệu cũ trong SQL Server được giữ lại, không bị xóa trong đợt thu gọn này.
