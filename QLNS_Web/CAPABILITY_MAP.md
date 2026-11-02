# Bản đồ phân hệ HR cần bổ sung

## Mục tiêu

Mở rộng ứng dụng Flask + SQL Server hiện tại thành hệ thống quản lý nhân sự theo vòng đời nhân viên. Tái sử dụng hồ sơ nhân viên, chấm công, nghỉ phép, lương, hợp đồng, điều chuyển và báo cáo đang có; không tạo hồ sơ nhân viên thứ hai khi ứng viên được tuyển.

## Bản đồ năng lực

| ID | Phân hệ | Trách nhiệm | Phụ thuộc |
|---|---|---|---|
| `access-control` | Phân quyền và audit | Vai trò HR, kế toán, quản lý trực tiếp, nhân viên; quyền theo chức năng/trường dữ liệu; ghi nhận thao tác xem, tải, sửa và duyệt dữ liệu nhạy cảm | — |
| `recruitment` | Tuyển dụng và ứng viên | Định biên/yêu cầu tuyển, hồ sơ ứng viên, pipeline, phỏng vấn, đánh giá, offer, chuyển ứng viên trúng tuyển sang hồ sơ nhân viên | `access-control` |
| `employee-lifecycle` | Onboarding và offboarding | Checklist liên phòng ban, người phụ trách, hạn hoàn tất, bàn giao tài sản, yêu cầu cấp/thu hồi tài khoản; lưu kết quả xử lý | `access-control`, hồ sơ nhân viên |
| `workforce-time` | Định biên vận hành, ca và thời gian | Ca, lịch làm linh hoạt, địa điểm, phân ca, chấm công theo ca và quy tắc giờ làm thêm | `access-control`, hồ sơ nhân viên |
| `payroll-compliance` | Payroll theo chính sách | Nhiều nhóm/kỳ lương; cấu hình thuế, bảo hiểm, phụ cấp, khấu trừ theo ngày hiệu lực; tính toán, duyệt, khóa, phiếu lương và audit | `access-control`, `workforce-time`, nghỉ phép |
| `performance` | Hiệu suất và mục tiêu | Chu kỳ đánh giá, mục tiêu cá nhân/nhóm, tiến độ, phản hồi, tự đánh giá, đánh giá quản lý và kết quả đã duyệt | `access-control`, hồ sơ nhân viên |
| `learning-career` | Đào tạo, kỹ năng và nghề nghiệp | Khóa học, chứng chỉ, kỹ năng, mức năng lực, khoảng trống và kế hoạch phát triển | `access-control`, hồ sơ nhân viên, `performance` |
| `benefits` | Phúc lợi | Danh mục quyền lợi, điều kiện hưởng theo chính sách, đăng ký/thay đổi, thời hạn, người phụ thuộc và lịch sử lựa chọn | `access-control`, hồ sơ nhân viên, `payroll-compliance` |
| `workforce-planning` | Hoạch định và kế nhiệm | Headcount hiện tại/kế hoạch, dự báo chi phí, vị trí trọng yếu, ứng viên kế nhiệm và điều chuyển nội bộ theo kỹ năng | `access-control`, `learning-career`, `payroll-compliance` |
| `people-analytics` | Phân tích nhân sự | Dashboard xu hướng, tuyển dụng, nghỉ việc/giữ chân, headcount, hiệu suất, đào tạo và chi phí; quyền truy cập theo phạm vi | Các phân hệ dữ liệu được phép tổng hợp |

## Thứ tự xây dựng đề xuất

`access-control` → `recruitment` → `employee-lifecycle` → `workforce-time` → `payroll-compliance` → `performance` → `learning-career` → `benefits` → `workforce-planning` → `people-analytics`.

Nghỉ phép và hợp đồng hiện có sẽ được tích hợp vào phân quyền, vòng đời nhân viên và payroll; không xây dựng lại thành phân hệ thay thế. Phân tích nhân sự làm sau cùng để chỉ tổng hợp dữ liệu có nguồn và quyền truy cập rõ ràng.

## Giả định cần xác nhận khi viết đặc tả từng phân hệ

1. Tiếp tục dùng Flask server-rendered templates và SQL Server; không thêm dịch vụ ngoài hoặc thư viện mới nếu chưa cần.
2. Quy trình payroll áp dụng cho doanh nghiệp tại Việt Nam. Thuế, bảo hiểm và quy tắc có hiệu lực theo thời gian phải là cấu hình có nguồn/ngày hiệu lực; không để AI hoặc công thức cố định tự xác nhận tuân thủ pháp luật.
3. Checklist onboarding/offboarding ghi nhận nhiệm vụ và người xử lý trong hệ thống; cấp/thu hồi tài khoản hoặc tài sản bên ngoài chỉ tự động khi có tích hợp được cấu hình.
4. Offer chỉ chuyển thành hồ sơ nhân viên sau khi được chấp nhận; dữ liệu ứng viên thất bại có chính sách lưu/xóa riêng.
5. Chưa có bộ test tự động và môi trường SQL Server staging sẵn trong thư mục dự án; mỗi lát cần bổ sung cách kiểm chứng phù hợp trước khi phát hành.

## Tiêu chí chung

- Mỗi phân hệ có quyền kiểm tra ở server-side, audit thao tác trọng yếu, validate đầu vào và lịch sử thay đổi.
- Dữ liệu nhạy cảm chỉ trả về theo vai trò, quan hệ quản lý và quyền trường dữ liệu; export/download dùng cùng chính sách như giao diện.
- Mỗi thay đổi schema có migration tương thích database hiện tại và hướng dẫn rollback/backup.
- Các thay đổi payroll có thể tính lại có kiểm soát, không ghi đè kỳ đã khóa và phải truy nguyên được chính sách cùng phiên bản đầu vào.
- Mỗi lát có tiêu chí nghiệm thu, kiểm chứng và tài liệu cấu hình trước khi mở cho người dùng.
