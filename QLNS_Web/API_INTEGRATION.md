# API và tích hợp

## API đang hoạt động

- GET /api/v1/reports/hr?year=2026&month=11
- Yêu cầu đăng nhập và quyền reports.hr.
- Chỉ trả số liệu tổng hợp; chi phí lương đã khóa chỉ có khi tài khoản có thêm payroll.view.
- Response gồm api_version, period và metrics; lỗi theo dạng error.code/error.message.
- API hiện dùng cookie phiên của ứng dụng, chưa cung cấp thông tin xác thực riêng cho hệ thống bên ngoài.

Các adapter gửi sự kiện từ máy chấm công, xuất sang phần mềm kế toán và gửi email chưa được triển khai. Khi cần tích hợp, phải xác định xác thực riêng, phạm vi quyền, idempotency, kiểm toán và giới hạn tốc độ trước khi mở endpoint.

## Chỉ số

- Headcount: số nhân viên đang làm.
- Chi phí lương: tổng lương và phần bảo hiểm doanh nghiệp của kỳ lương đã khóa.
- Tỷ lệ vắng mặt: dựa trên ngày nghỉ ghi trên bảng chấm công; hiện chưa hiệu chỉnh theo ca riêng và ngày lễ.
