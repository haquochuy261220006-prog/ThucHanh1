# Rà soát bảo mật trước triển khai

Ngày rà soát: 28/10/2026  
Phạm vi: rà soát tĩnh mã nguồn Flask, route/API, truy vấn quyền, cấu hình, nhật ký nghiệp vụ, dữ liệu mẫu và cơ chế vận hành có trong thư mục dự án.

## Kết luận

Chưa nên đưa hệ thống lên môi trường nhiều người dùng trước khi hoàn tất kiểm thử tích hợp, backup/restore và tách quyền migration khỏi tài khoản chạy web. Mã nguồn có kiểm tra vai trò và quyền sở hữu ở nhiều route. Trong lượt rà soát tiếp theo đã thêm cookie/session policy, header bảo vệ cơ bản, logout POST có CSRF, xác thực mật khẩu hiện tại, thu hồi phiên cũ và thông báo lỗi chung cho các nhánh đã rà.

Đây là kết quả rà soát tĩnh. Chưa kết nối SQL Server, chạy ứng dụng, chạy kiểm thử xâm nhập hay khôi phục bản sao lưu; do đó các thay đổi chưa được xác minh tích hợp và cấu hình triển khai thực tế chưa được chứng nhận.

## Phát hiện

### Đã xử lý ở các nhánh rà soát — Chi tiết ngoại lệ nội bộ có thể trả về cho người dùng

Các luồng phổ biến ở `app.py` và `contracts.py` hiện giữ thông báo lỗi nghiệp vụ đã biết, còn ngoại lệ khác được log phía máy chủ và trả thông báo chung. API kiểm tra kết nối AI cũng không còn đưa thông tin ngoại lệ ra giao diện. Cần rà tiếp và xác nhận response thực tế trong staging.

**Còn lại:** kiểm thử phản hồi lỗi và đảm bảo log máy chủ không chứa thông tin bí mật/PII.

### Đã xử lý trong mã — Đổi mật khẩu không yêu cầu mật khẩu hiện tại và không thu hồi phiên cũ

Đã thêm yêu cầu mật khẩu hiện tại, cột `SecurityVersion`, và kiểm tra phiên đăng nhập trên request. Đổi mật khẩu làm tăng phiên bản và yêu cầu đăng nhập lại; phiên bị từ chối sau khi tài khoản bị xóa, đổi vai trò hoặc nhân viên chuyển sang nghỉ việc.

**Còn lại:** kiểm thử migration và xác nhận thu hồi phiên giữa nhiều worker trên database staging.

### Cao — Chưa có cơ chế sao lưu và diễn tập khôi phục trong dự án

Không tìm thấy script hoặc hướng dẫn vận hành cho sao lưu SQL Server, lưu bản sao ngoài máy chủ, kiểm tra tính hợp lệ, thời hạn giữ bản sao và khôi phục thử. Việc tạo backup file thành công không thay thế cho một lần restore thử.

**Khuyến nghị:** cấu hình lịch backup full/differential/log phù hợp RPO/RTO; mã hóa và giới hạn ACL của bản backup; giữ bản sao ở vị trí độc lập; lập runbook khôi phục sang database tách biệt và ghi nhận kết quả diễn tập định kỳ.

### Cao — Ứng dụng tự chạy DDL khi phục vụ request

`_auto_schema()` gọi `ensure_schema()` trong tiến trình web; hàm này tạo/sửa bảng và cột. Tài khoản Windows/SQL của ứng dụng vì vậy có thể cần quyền DDL trên database trong runtime.

**Khuyến nghị:** chạy migration bằng tài khoản triển khai riêng; tài khoản runtime chỉ có quyền cần thiết trên bảng/view và không có quyền tạo/sửa schema. Trước khi tách migration, xác định và kiểm thử toàn bộ schema upgrade hiện có.

### Đã xử lý một phần — Chính sách cookie phiên và security headers chưa được cấu hình tường minh

Đã cấu hình `HttpOnly`, `SameSite=Lax`, `Secure` theo `APP_ENV`/`SESSION_COOKIE_SECURE`, và header chống MIME sniffing, framing, referrer, cùng quyền trình duyệt. HSTS được trả khi Flask nhận diện request HTTPS. Chưa thêm CSP do giao diện có inline script/style.

**Còn lại:** kiểm tra reverse proxy/TLS thực tế; `request.is_secure` chỉ đúng khi proxy chuyển tiếp thông tin HTTPS an toàn.

### Trung bình — Giới hạn đăng nhập sai chỉ nằm trong bộ nhớ tiến trình

`_login_fails` là dict toàn cục. Bộ đếm mất khi ứng dụng khởi động lại và không được chia sẻ giữa nhiều worker/máy chủ, nên giới hạn có thể bị vượt qua khi scale hoặc đổi worker.

**Khuyến nghị:** dùng rate limiter lưu trong Redis/SQL dùng chung, giới hạn theo tài khoản và nguồn mạng, thêm thời gian chờ tăng dần và theo dõi sự kiện đăng nhập bất thường. Tránh khóa vĩnh viễn tài khoản theo cách cho phép kẻ khác gây từ chối dịch vụ.

### Đã xử lý một phần — Nhật ký kiểm toán cho hồ sơ nhân viên

Luồng tạo/sửa/xóa hồ sơ nhân viên hiện ghi hành động, tên trường thay đổi, người thực hiện và thời điểm vào `NhatKyHoSoNhanVien`. Nhật ký không chứa giá trị cũ/mới của các trường PII hoặc lương và có thể tra cứu bởi quản trị viên hoặc chính nhân viên.

**Còn lại:** audit truy cập đã được bổ sung một phần cho danh sách/xem nhân viên, dữ liệu lương ở một số màn hình, hồ sơ điện tử và danh sách/tải hợp đồng. Chưa bao phủ đầy đủ mọi route đọc, các luồng xuất CSV/Excel/PDF, truy cập trường CCCD ngoài form sửa; cần tiếp tục rà soát. Cũng cần hạn chế quyền sửa/xóa nhật ký ở SQL Server và phê duyệt thời hạn lưu.

Sổ tài sản nhân viên mới ghi nhật ký riêng cho thao tác cấp/thu hồi (tài sản, người thực hiện, ghi chú và thời điểm); phạm vi audit các truy cập nhạy cảm khác vẫn như trên.

### Trung bình — Phân quyền nhạy cảm mới chủ yếu theo hai vai trò

Các route lương, báo cáo, quản lý nhân viên/hợp đồng và tài khoản được giới hạn cho `QuanTri`; phiếu lương cá nhân, ảnh hồ sơ và tài liệu hợp đồng có kiểm tra quyền sở hữu. Tuy nhiên mô hình vai trò chỉ gồm `QuanTri` và `NhanVien`, chưa có quyền riêng cho HR, kế toán, quản lý trực tiếp hoặc trường dữ liệu. Quản trị viên có thể truy cập toàn bộ CCCD, liên hệ, lương và hồ sơ hợp đồng.

**Khuyến nghị:** trước khi triển khai nhiều bộ phận, xác định ma trận quyền theo chức năng và trường dữ liệu; mặc định ẩn CCCD/embedding; ghi audit việc xem/tải dữ liệu nhạy cảm; kiểm tra quyền ở server-side trên từng route/API và từng ID tài nguyên.

### Trung bình — Xác thực chứng thư kết nối SQL Server bị bỏ qua

`config.py` thêm `TrustServerCertificate=yes` vào chuỗi kết nối. Khi kết nối qua mạng, TLS có thể mã hóa kênh nhưng client không xác minh chứng thư máy chủ, làm giảm khả năng chống giả mạo endpoint.

**Khuyến nghị:** môi trường triển khai dùng chứng thư SQL Server hợp lệ và bật xác minh chứng thư (`TrustServerCertificate=no`); giữ kết nối cục bộ chỉ cho phát triển nếu cần, không dùng cấu hình local làm mặc định production.

### Thấp — Cấu hình vận hành database gắn trong mã nguồn

`config.py` có tên instance, tên database, `USER="sa"`, mật khẩu trống và `WINDOWS_AUTH=True`. Đây không phải bằng chứng có mật khẩu thật bị commit, và hiện cấu hình đang dùng Windows Authentication; tuy vậy cấu hình triển khai cần được đưa ra environment/secret store và tài khoản `sa` không nên là danh tính runtime.

**Khuyến nghị:** dùng tài khoản SQL/Windows riêng với quyền tối thiểu, cấu hình theo môi trường và không cấp `sysadmin` cho web app.

## Kiểm soát đã xác nhận trong mã nguồn

- Hầu hết route nghiệp vụ có `login_required`; route quản trị và blueprint hợp đồng có kiểm tra role phía máy chủ.
- Phiếu lương cá nhân kiểm tra mã nhân viên sở hữu; báo cáo, payroll và xuất dữ liệu nhạy cảm giới hạn cho quản trị viên; xuất lương yêu cầu kỳ lương đã khóa.
- Có CSRF token cho form và token riêng cho API nhận diện khuôn mặt; endpoint ảnh hồ sơ và tệp hợp đồng kiểm tra quyền sở hữu.
- Luồng chấm công thủ công/face hiện tuần tự hóa theo nhân viên/ngày bằng `sp_getapplock` và ghi sự kiện cùng bản tổng hợp trong một transaction; vẫn cần kiểm thử cạnh tranh và migration trên staging SQL Server.
- Mật khẩu được hash bằng PBKDF2-HMAC-SHA256 với salt ngẫu nhiên; API câu lệnh SQL chủ yếu truyền tham số.
- Vector khuôn mặt được mã hóa Fernet với khóa lấy từ environment; có đồng ý, thời hạn lưu và nút xóa mẫu. Chất lượng chống giả mạo vẫn chưa phải yếu tố bảo đảm chấm công.
- Dữ liệu trong `seed_sample.py` được ghi rõ là giả, email dùng miền `example.com`; không thấy tệp `.env` trong thư mục được rà soát.

## Giới hạn phạm vi và việc cần kiểm tra trước triển khai

- Thư mục dự án không có `.git`, nên không thể rà lịch sử commit hoặc xác nhận nội dung nào đã từng được đưa lên remote. Cần chạy secret scanner trên repository và lịch sử Git thực tế.
- Không có lockfile trong danh sách dự án; chưa chạy audit dependency theo lockfile. Cần cố định phiên bản phụ thuộc và audit trước phát hành.
- Chưa xác minh SQL Server TLS, quyền thực tế của service account, reverse proxy/HTTPS, cấu hình backup, phân quyền thư mục, nơi lưu log, hay secret store của môi trường đích.
- Chưa chạy kiểm thử động vì chưa có môi trường SQL Server cô lập và dữ liệu kiểm thử được cung cấp trong lượt rà soát.
- Đã thử kiểm tra cú pháp bằng `py -m compileall`, nhưng Windows không cho chạy `py.exe` trong môi trường hiện tại; kết quả compile/runtime vì thế chưa xác minh được.

## Bộ kiểm thử cần chạy ở môi trường staging

1. Ma trận 401/403 cho mọi route/API với khách, nhân viên, quản trị viên; thử đổi ID để kiểm tra IDOR ở ảnh, hợp đồng, phiếu lương, chấm công và nghỉ phép.
2. Kiểm tra CSRF cho mọi thao tác thay đổi trạng thái; kiểm tra logout không bị kích hoạt bởi GET hoặc trang bên ngoài.
3. Đổi mật khẩu, xóa/khóa tài khoản và đổi vai trò khi có phiên ở trình duyệt khác; phiên cũ phải bị từ chối.
4. Gây lỗi SQL có chủ ý trong staging và xác nhận người dùng chỉ nhận thông báo chung, log máy chủ giữ trace có mã tương quan nhưng không ghi bí mật/PII.
5. Xác nhận cookie có `HttpOnly`, `Secure`, `SameSite`; kiểm tra HTTPS, HSTS, CSP, framing và MIME headers qua reverse proxy thực tế.
6. Kiểm tra mọi dữ liệu nhạy cảm trong HTML, API, CSV/XLSX/PDF, log, exception, database backup và bản ghi mẫu.
7. Chạy thử backup và restore vào database tách biệt; xác minh số lượng bảng/bản ghi và khả năng đăng nhập/chạy nghiệp vụ sau khôi phục.
8. Kiểm tra quyền SQL của tài khoản runtime: không tạo/sửa schema, không có `sysadmin`; thử truy cập ngoài ma trận quyền đã phê duyệt.

## Tham chiếu mã nguồn chính

- `app.py`: cấu hình Flask/CSRF/đăng nhập, module CRUD, chấm công, payroll, export, đổi mật khẩu và `ensure_schema()`.
- `auth.py`: hash, đăng nhập và đổi mật khẩu.
- `config.py`: kết nối SQL Server, khóa AI/khuôn mặt và cấu hình môi trường.
- `contracts.py`: phân quyền route và tải tài liệu hợp đồng.
- `setup_db.py`, `seed_sample.py`: schema khởi tạo, tài khoản admin và dữ liệu mẫu.


### Cập nhật nhật ký truy cập dữ liệu nhạy cảm

Ứng dụng ghi loại dữ liệu, thao tác, mã nhân viên, người thực hiện và thời điểm vào NhatKyTruyCapNhanSu; không sao chép giá trị lương/CCCD/liên hệ vào nhật ký. Quản trị viên xem tối đa 500 lượt gần nhất tại **Nhật ký truy cập**. Hiện đã nối một số đường đọc hồ sơ nhân viên, lương, hồ sơ điện tử và hợp đồng. Đây chưa phải kiểm toán đầy đủ: đã ghi nhận xuất danh sách nhân viên, hợp đồng và bảng lương; các luồng xuất/đọc nhạy cảm khác, mọi route/API và vai trò HR/kế toán/quản lý chưa được bao phủ, và quyền truy cập quản trị vẫn rộng.
