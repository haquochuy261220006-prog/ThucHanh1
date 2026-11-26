# Bản đồ 9 phân hệ HR đang giữ lại

## Phạm vi

Ứng dụng tập trung vào đúng chín chức năng: Tài khoản và phân quyền, Quản lý phòng ban, Quản lý nhân viên, Quản lý hợp đồng, Quản lý chấm công, Quản lý nghỉ phép, Quản lý tiền lương, KPI & thưởng hiệu suất, Thống kê và báo cáo. Dashboard là trang tổng quan dùng chung, không tính là chức năng thứ 10. Audit, xuất tệp và cơ sở dữ liệu là năng lực nền.

## Bản đồ năng lực

| Chức năng | Năng lực đang giữ |
|---|---|
| Tài khoản và phân quyền | Đăng nhập, đổi mật khẩu, quản lý tài khoản, gán vai trò, kiểm soát quyền |
| Quản lý phòng ban | Đơn vị, phòng ban, chức danh, vị trí công việc, sơ đồ tổ chức, điều chuyển |
| Quản lý nhân viên | Hồ sơ chuẩn theo MaNV, CRUD, tìm kiếm/lọc, lịch sử công tác, tài liệu điện tử |
| Quản lý hợp đồng | Danh sách, mẫu, tệp/phiên bản, soạn nháp AI, vòng đời hợp đồng |
| Quản lý chấm công | Sự kiện vào/ra, đối soát, ca làm việc, tăng ca và phương thức ghi nhận dự phòng |
| Quản lý nghỉ phép | Đơn nghỉ, duyệt, kiểm tra trùng lịch, lịch làm việc và quỹ phép |
| Quản lý tiền lương | Tính lương, điều chỉnh, chính sách, phê duyệt, khóa kỳ, phiếu lương |
| KPI & thưởng hiệu suất | Thiết lập chỉ tiêu, gán theo phòng ban/cá nhân, nhập kết quả, chấm điểm, xác nhận và chuyển thưởng sang lương |
| Thống kê và báo cáo | Tổng hợp nhân sự/công/phép/lương, biểu đồ và xuất CSV/Excel/PDF |

**Dashboard:** chỉ hiển thị chỉ số tổng quan và liên kết nhanh tới các chức năng; không được tính là chức năng độc lập trong tổng số tám.

## Quy tắc dữ liệu

- NhanVien.MaNV là khóa nhân viên dùng chung; các bảng nghiệp vụ tham chiếu mã này.
- Các lần chấm công được lưu trong nguồn sự kiện và tổng hợp vào bảng công ngày để tương thích.
- Phiếu lương và bảng lương dùng chung dữ liệu kỳ; quyền xem phụ thuộc vai trò.
- Nhật ký quan trọng và dữ liệu nhạy cảm tiếp tục được giới hạn theo quyền.

## Ngoài phạm vi ứng dụng hiện tại

Các màn hình riêng về tuyển dụng, onboarding/offboarding, tài sản, đào tạo/kỹ năng, phúc lợi và hoạch định nhân lực đã được gỡ khỏi giao diện và route. Bảng dữ liệu cũ trong SQL Server được giữ lại, không bị xóa trong đợt thu gọn này. Migration không được tự ý xóa bảng hoặc dữ liệu cũ.
