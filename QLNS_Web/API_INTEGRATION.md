# Báo cáo và hợp đồng tích hợp API

## Hiện có

- `GET /api/v1/reports/hr?year=2026&month=11`: trả JSON tổng hợp, yêu cầu đăng nhập và quyền `reports.hr`. Không trả dữ liệu định danh nhân viên. Chi phí payroll chỉ có trong response nếu tài khoản có thêm `payroll.view`, và chỉ tính kỳ đã khóa.
- Response thành công có `api_version`, `period`, `metrics`. Lỗi dùng cấu trúc `{ "error": { "code": "...", "message": "..." } }`.
- URL có phiên bản `/api/v1`; thay đổi phá vỡ tương thích cần tạo phiên bản API mới. Trình duyệt dùng cookie phiên hiện tại; endpoint chưa bật xác thực cho máy/đối tác.

## Hợp đồng cho các adapter tương lai

| Hệ thống | Hướng | Hợp đồng đề xuất | Quyền riêng |
| --- | --- | --- | --- |
| Máy chấm công | Gửi sự kiện vào | `POST /api/v1/attendance/events`; `Idempotency-Key`, mã nhân viên nội bộ, thời gian ISO-8601 có múi giờ, loại `in/out`, mã sự kiện ngoài và mã máy | `attendance.write` |
| Tuyển dụng/ATS | Đồng bộ ứng viên vào/ra | `POST /api/v1/recruiting/candidates`, `GET /api/v1/recruiting/jobs`; định danh ứng viên ngoài, mã yêu cầu tuyển dụng, trạng thái pipeline | `recruiting.read/write` |
| Kế toán | Xuất kỳ lương đã khóa | `GET /api/v1/payroll/periods/{year}/{month}/export`; chỉ dữ liệu cần hạch toán, kèm phiên bản chính sách và mã kỳ | `payroll.export` |
| Email | Gửi thông báo ra | Outbox nội bộ + webhook/email provider; sự kiện có mã duy nhất, mẫu, người nhận đã được phép và trạng thái gửi | `notifications.send` |

Các adapter trên là thiết kế đích, chưa phải route đã triển khai. Trước khi bật truy cập hệ thống ngoài, cần cấu hình OAuth2 client credentials hoặc API key riêng từng đối tác, scope theo quyền tối thiểu, xoay vòng/thu hồi khóa, giới hạn tốc độ, HTTPS, idempotency, kiểm toán, retry có backoff và bảo vệ chống replay. Không dùng chung token giữa máy chấm công, ATS và kế toán; không đưa bí mật vào repository.

## Ý nghĩa chỉ số dashboard

- Nghỉ việc: kết thúc offboarding trong năm / headcount trung bình đầu-cuối năm.
- Vắng mặt: ngày nghỉ đã ghi trên bảng chấm công / ngày làm dự kiến Thứ Hai–Thứ Sáu của headcount hiện tại. Chưa hiệu chỉnh ca linh hoạt, lịch riêng và ngày lễ.
- Chi phí nhân sự: tổng lương cộng phần bảo hiểm doanh nghiệp của kỳ payroll đã khóa.
- Thời gian tuyển dụng: trung bình ngày từ lúc tạo ứng viên đến ngày nhân viên bắt đầu làm, chỉ cho hồ sơ đã liên kết.
- KPI: tiến độ bình quân của kết quả KPI đã duyệt, chưa phải điểm có trọng số.
- Nhu cầu nhân lực: tổng kế hoạch định biên đã duyệt trừ số nhân viên hiện tại theo phòng ban; đây là kế hoạch, không phải mô hình dự báo thống kê.
