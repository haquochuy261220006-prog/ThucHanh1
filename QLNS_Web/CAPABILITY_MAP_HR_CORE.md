# Capability Map: Employee Master Profile và hồ sơ nhân viên

## Mục tiêu

Xây dựng hồ sơ nhân viên chuẩn làm nguồn dữ liệu thống nhất. Mỗi nhân viên chỉ có một `MaNV` ổn định; mọi dữ liệu thuộc các module tuyển dụng sau khi nhận việc, onboarding, chấm công, nghỉ phép, lương, KPI, đào tạo, tài sản, hợp đồng và báo cáo đều tham chiếu mã này thay vì tạo bản hồ sơ nhân viên riêng.

## Hiện trạng liên quan

- `NhanVien.MaNV` hiện là khóa chính `IDENTITY`; các bảng lương, chấm công, nghỉ phép và hợp đồng đang tham chiếu mã này.
- Bảng `NhanVien` hiện lưu phòng ban, chức vụ, lương cơ bản, ngày vào làm và trạng thái hiện tại.
- `LichSuDieuChuyen` hiện chỉ ghi điều chuyển phòng ban; chưa lưu các giai đoạn chức vụ, lương hoặc quản lý.
- `ChamCong` hiện giới hạn một bản ghi mỗi nhân viên/ngày, chưa biểu diễn trực tiếp nhiều lần vào/ra, nhiều ca hoặc ca qua đêm.
- `PhongBan` và `ChucVu` là danh mục phẳng; chưa có cây đơn vị/phòng ban hoặc phân biệt vị trí công việc với chức danh.
- Tuyển dụng, onboarding, KPI và đào tạo đã có module; tài sản hiện có sổ cấp/thu hồi liên kết `MaNV`, chưa tích hợp hệ thống thiết bị ngoài.
- Tài liệu hiện nằm chủ yếu trong luồng hợp đồng; tệp quét hồ sơ từ OCR không được lưu thành hồ sơ điện tử tập trung.

## Tiến độ thực hiện

- `employee-master-profile`: đã có registry liên kết nguồn với `MaNV` và service tạo/liên kết hồ sơ; các checkpoint cần xác minh trên SQL Server còn mở.
- `organization-model`: đã bổ sung schema đơn vị/phòng ban dạng cây và vị trí công việc, trường vị trí trên hồ sơ nhân viên, cùng trang sơ đồ tổ chức. Cần kiểm tra migration trên database hiện có.
- `employment-history`: hồ sơ theo giai đoạn phòng ban/chức danh/vị trí/lương/quản lý; dữ liệu hiện trạng cũ được lấy ngày nâng cấp làm mốc đầu tiên. Cần kiểm tra migration.
- `profile-fields`: đã có định nghĩa kiểu dữ liệu allowlist, cờ bắt buộc/nhạy cảm, giá trị theo `MaNV` và nhật ký sửa; cần kiểm tra quyền và migration trên database.
- Nhật ký hồ sơ nhân viên: đã ghi tạo/sửa/xóa và tên trường thay đổi, chỉ hiển thị cho quản trị viên hoặc chính nhân viên; không lưu giá trị CCCD, liên hệ hay lương trong audit. Nhật ký giữ mã nhân viên dạng số và không có khóa ngoại để còn dấu vết sau khi xóa hồ sơ chưa phát sinh nghiệp vụ.
- `employee-records`: đã có tài liệu mã hóa, giới hạn xem/tải, nhật ký truy cập và trang quản trị rà tài liệu quá hạn/đến hạn 90 ngày (không tự xóa); yêu cầu cấu hình khóa `HR_DOCUMENT_ENCRYPTION_KEY`.
- `workforce-time`: đã có ca, phân ca theo ngày, chặn trùng giờ, ngày lễ/nghỉ, đơn tăng ca và phê duyệt. Luồng thủ công/face hỗ trợ nhiều chu kỳ `vào → ra` trong ngày, ghi sự kiện và cập nhật `ChamCong` trong cùng transaction; ca qua đêm ánh xạ giờ ra sau nửa đêm về ngày bắt đầu ca. `ChamCong` tiếp tục là tổng hợp tương thích với giờ vào đầu/ra cuối; payroll vẫn tối đa một ngày công/ngày; báo cáo tiến độ ngày công đếm sự kiện vào hợp lệ và hiển thị tổng giờ từ các cặp vào/ra hoàn tất để đối soát; snapshot giờ sự kiện được lưu khi tính kỳ lương để đối soát, nhưng chưa được dùng để thay đổi tiền lương tăng ca. Payroll dùng ngày đã phân làm ngày làm dự kiến, ân hạn ca để tính đi muộn và loại lễ khỏi ngày nghỉ không phép; không tự suy diễn ca ngày chưa phân. Tính phép theo ca, phụ cấp ngày lễ và tích hợp chấm công vật lý/GPS/liveness còn thiếu.
- Tuyển dụng: đã có yêu cầu, pipeline, phỏng vấn/đánh giá và offer; nhận offer tạo/liên kết một `MaNV` qua registry nguồn. Cần chính sách lưu/xóa ứng viên và kiểm tra trên SQL Server.
- Onboarding/offboarding: đã có checklist liên phòng ban, mẫu checklist cấu hình, điều kiện hoàn tất nghỉ việc, thu hồi phiên và xóa mẫu khuôn mặt. Cấp/thu hồi tài sản được ghi trong sổ tài sản theo `MaNV`; bước thu hồi trong checklist kiểm tra tài sản đang giao. Tạo/khóa tài khoản vẫn là checklist thủ công, chưa tích hợp hệ thống ngoài.
- Quản lý tài sản: đã có sổ cấp/thu hồi theo nhân viên, giữ lịch sử và nhật ký thao tác, xuất CSV/Excel/PDF; chưa có danh mục kho, kiểm kê, bảo trì hoặc đồng bộ MDM.
- KPI: đã có chu kỳ, mục tiêu cá nhân/phòng ban, tự báo cáo tiến độ, duyệt kết quả và phản hồi liên tục. Chưa có phân quyền theo quản lý trực tiếp, dashboard KPI chuyên sâu hoặc tự động đánh giá.
- Đào tạo/kỹ năng/nghề nghiệp: đã có khóa học, đăng ký/duyệt, hoàn thành/chứng chỉ, danh mục kỹ năng, cấp độ và kế hoạch phát triển cá nhân; cần kiểm tra DB và quy trình thực tế.
- Phúc lợi: đã có danh mục/điều kiện, nhân viên đăng ký và HR duyệt/từ chối; xác minh điều kiện đang do HR thực hiện thủ công.
- Hoạch định nhân lực: đã có kế hoạch headcount/chi phí, so sánh định biên với số lượng/lương cơ bản hiện tại và danh sách kế nhiệm theo kỹ năng hồ sơ. Chưa có dự báo xu hướng, phê duyệt ngân sách nhiều cấp hoặc đề xuất điều chuyển tự động theo kỹ năng.
- Phân tích nhân sự: đã có dashboard 12 tháng về tuyển mới và offboarding ghi nhận, headcount/lương cơ bản theo phòng ban, kỹ năng và trạng thái đào tạo. Số nghỉ việc chỉ bao gồm quy trình offboarding được ghi nhận; chưa phản ánh lịch sử cũ, chưa có dự báo nghỉ việc/giữ chân hoặc phân tích xu hướng chuyên sâu.
- Payroll thuế/bảo hiểm theo quy định và phân quyền HR/kế toán/quản lý chi tiết chưa có module hoàn chỉnh; cần xác minh chính sách pháp lý và phân quyền trước khi mở rộng.
- Phân quyền hiện vẫn chủ yếu theo vai trò quản trị/nhân viên; chưa có vai trò chuyên biệt HR, kế toán, quản lý trực tiếp, phạm vi theo phòng ban và audit việc xem/tải mọi trường nhạy cảm.

## Bản đồ năng lực

| Module id | Trách nhiệm | Phụ thuộc |
|---|---|---|
| `employee-master-profile` | Là nguồn nhân viên chuẩn; duy trì `MaNV` không tái sử dụng, thông tin nhân thân và trạng thái vòng đời; quy định các module lưu khóa ngoại `MaNV`, không tạo hồ sơ nhân viên trùng. | — |
| `organization-model` | Phân biệt đơn vị, phòng ban, vị trí công việc và chức danh; quản lý cây tổ chức và quan hệ cha-con. | `employee-master-profile` |
| `employment-history` | Lưu các giai đoạn công tác có ngày hiệu lực, gồm đơn vị/phòng ban, vị trí/chức danh, lương và quản lý; tra cứu lịch sử theo nhân viên. | `employee-master-profile`, `organization-model` |
| `profile-fields` | Cho quản trị viên định nghĩa trường tùy chỉnh và lưu giá trị theo từng nhân viên, có kiểu dữ liệu và kiểm tra đầu vào. | `employee-master-profile` |
| `employee-records` | Kho hồ sơ điện tử tập trung: phân loại tài liệu, tệp, ngày hiệu lực/hết hạn, quyền xem/tải, thời hạn lưu và xử lý hết hạn. Hiển thị/liên kết tài liệu hợp đồng đã có, tránh tạo bản sao. | `employee-master-profile` |
| `employee-assets` | Theo dõi cấp/thu hồi tài sản theo `MaNV`, giữ nhật ký thao tác và hỗ trợ bàn giao tài sản trong offboarding. | `employee-master-profile`, `employee_lifecycle` |
| `workforce-time` | Quản lý ca sáng/chiều/đêm, phân ca theo nhân viên, ca qua đêm, lịch lễ/ngày nghỉ, tăng ca đăng ký và phê duyệt; hỗ trợ đổi ca, thời gian linh hoạt, GPS/geofence, máy chấm công và chống giả mạo khuôn mặt theo chính sách triển khai. | `employee-master-profile`, `organization-model` |

## Quy tắc liên kết module

- `MaNV` là định danh nhân viên nội bộ dùng xuyên suốt; không đổi khi đổi tên, phòng ban, chức vụ hoặc trạng thái làm việc và không được cấp lại cho người khác.
- Mọi bảng nghiệp vụ có dữ liệu của nhân viên dùng `MaNV` làm khóa ngoại; chỉ lưu dữ liệu riêng của nghiệp vụ, không sao chép hồ sơ gốc.
- Ứng viên trước khi nhận offer vẫn là hồ sơ tuyển dụng riêng. Khi offer được chấp nhận và tạo nhân viên, hệ thống tạo đúng một `MaNV`, lưu liên kết ứng viên → nhân viên và dùng `MaNV` đó cho onboarding cùng các module sau.
- Offboarding cập nhật trạng thái/lịch sử nhân viên; không xóa hoặc cấp lại `MaNV` khi còn dữ liệu nghiệp vụ liên quan.

## Thứ tự xây dựng đề xuất

`employee-master-profile` → `organization-model` → (`employment-history`, `workforce-time`) → (`profile-fields`, `employee-records`, `employee-assets`).

Các module hiện có như chấm công, nghỉ phép, lương, hợp đồng và tài sản tiếp tục dùng `MaNV`; không thay thế dữ liệu lịch sử cũ trong cùng lần nâng cấp. Các module tuyển dụng, onboarding, KPI và đào tạo cũng phải tuân thủ quy tắc liên kết ở trên.

## Phạm vi quản lý ca và chấm công

**Ưu tiên bắt buộc:** ca sáng/chiều/đêm; phân ca theo nhân viên; ca qua đêm; lịch ngày lễ/ngày nghỉ; đăng ký và phê duyệt tăng ca.

**Ưu tiên theo cấu hình doanh nghiệp:** đổi ca; thời gian làm việc linh hoạt; GPS/geofence; tích hợp máy chấm công vật lý. GPS/geofence và nhận diện khuôn mặt chỉ bật khi doanh nghiệp chọn, có chính sách quyền riêng tư và cách xử lý ngoại lệ.

**Chống giả mạo khuôn mặt:** nếu tiếp tục dùng nhận diện, phải có cơ chế xác minh người thật phù hợp trước khi xem kết quả là bằng chứng chấm công. Nhận diện khuôn mặt hiện có không tự được coi là xác minh liveness.

**Tương thích dữ liệu:** `ChamCong` hiện có ràng buộc một dòng mỗi nhân viên/ngày. Không bỏ hoặc phá bảng này trong lần nâng cấp đầu. Bổ sung mô hình sự kiện chấm công riêng cho từng lần vào/ra và sự kiện nguồn khác; tổng hợp các sự kiện thành bản công ngày trong `ChamCong` hoặc lớp tương thích tương đương. Dữ liệu cũ phải được giữ và ánh xạ được; chỉ nới/bỏ ràng buộc cũ trong migration sau khi mọi route, báo cáo, lương và export đã chuyển sang mô hình mới.
## Giả định cần xác nhận khi viết đặc tả

1. Tiếp tục dùng Flask templates và SQL Server; không thêm dịch vụ hay thư viện mới nếu chưa cần.
2. Phân quyền chi tiết mới chưa được yêu cầu ở đây; dữ liệu hồ sơ/tài liệu phải tuân theo quyền hiện có và không được mở rộng quyền truy cập ngầm.
3. Thay đổi công tác có ngày hiệu lực; chỉnh sửa hồi tố phải lưu ai sửa, lúc nào và lý do.
4. Thời hạn lưu tài liệu là cấu hình theo loại; hệ thống không tự xóa tài liệu trước khi chính sách được duyệt.
5. Không xóa cột/lịch sử cũ trong lần migration đầu; cần ánh xạ và bảo toàn dữ liệu hiện hữu, kèm hướng dẫn backup/rollback.

## Tiêu chí chung

- Một nhân viên chỉ có một `MaNV`; tạo lại hoặc chuyển trạng thái không tạo nhân viên trùng.
- Không module nào tạo bản sao hồ sơ nhân viên gốc; mọi nghiệp vụ của nhân viên truy ngược được tới cùng `MaNV`.
- Mọi thao tác cập nhật hồ sơ và dữ liệu công tác ghi nhận người thực hiện, thời gian và giá trị thay đổi.
- Nhật ký hồ sơ chỉ ghi tên trường và hành động, không sao chép giá trị PII hoặc dữ liệu lương nhạy cảm.
- Định nghĩa trường tùy chỉnh không cho phép chèn tên cột hoặc SQL tùy ý.
- Tài liệu chỉ được xem, tải, chỉnh sửa hoặc xử lý hết hạn sau kiểm tra quyền phía máy chủ.
