# QLNS Web — Flask + SQL Server

Bản giao diện web chuyển từ ứng dụng Python/Tkinter sang Flask, tiếp tục sử dụng SQL Server và các bảng hiện có. Giao diện responsive cho máy tính và điện thoại.

## 1. Yêu cầu
- Windows 10/11
- Python 3.10 trở lên
- Microsoft ODBC Driver 17 hoặc 18 for SQL Server
- SQL Server Express/SQL Server đã chạy và có database `NHANSU_PY` cùng các bảng của dự án

## 2. Cấu hình kết nối
Mở `config.py` và chỉnh `SERVER` đúng với tên instance trên máy. Ví dụ:
- `localhost\\SQLEXPRESS`
- `localhost\\SQLEXPRESS03`
- `localhost` (nếu dùng default instance)

`DATABASE` mặc định là `NHANSU_PY`. Windows Authentication đang bật (`WINDOWS_AUTH = True`), nên tài khoản Windows chạy Flask cần quyền truy cập database. Không đưa ứng dụng ra Internet khi đang dùng cấu hình thử nghiệm. Đặt `FLASK_SECRET_KEY` để giữ phiên đăng nhập ổn định giữa các lần khởi động; nếu chưa đặt, ứng dụng tạo khóa ngẫu nhiên và người dùng cần đăng nhập lại sau khi khởi động lại.

Khi triển khai production, đặt `APP_ENV=production` và cung cấp `FLASK_SECRET_KEY` mạnh, ổn định; ứng dụng sẽ không khởi động nếu thiếu khóa này và sẽ bật cờ `Secure` cho cookie phiên. Hãy chạy sau HTTPS. `SESSION_COOKIE_SECURE=1` có thể bật cờ này rõ ràng trong các môi trường HTTPS chưa đặt `APP_ENV=production`.

## 3. Cài đặt và chạy
Mở terminal VS Code tại thư mục này:
```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python app.py
```
Mở trình duyệt: http://127.0.0.1:5000

Khi chạy `setup_db.py`, mật khẩu `admin` lấy từ biến môi trường `ADMIN_PASSWORD` (10–256 ký tự) hoặc được tự sinh ngẫu nhiên và in ra một lần; hãy lưu lại. Chỉ chạy `python setup_db.py` nếu bạn muốn tạo database/bảng mẫu và đã xác nhận cấu hình `config.py` đúng. Sao lưu database trước khi chạy trên dữ liệu thật.

## Gửi OTP khi tạo tài khoản
Trang **Tài khoản** cho quản trị viên chọn gửi OTP đến email hoặc số điện thoại đã lưu trong hồ sơ nhân viên. Mã có 6 chữ số, hết hạn sau 5 phút, giới hạn 5 lần nhập sai và mỗi lần gửi cách nhau ít nhất 30 giây cho mỗi nhân viên. Hash OTP và số lần thử được lưu trong bảng SQL Server `TaiKhoanOTP`; email cần cấu hình SMTP, SMS cần tài khoản Twilio cùng số gửi hoặc Messaging Service. Mật khẩu tài khoản mới cần từ 10 đến 256 ký tự. Không lưu thông tin xác thực trong mã nguồn.

Ví dụ PowerShell (Gmail cần bật xác minh 2 bước và dùng App Password):
```powershell
$env:SMTP_HOST = "smtp.gmail.com"
$env:SMTP_PORT = "587"
$env:SMTP_USER = "your-address@gmail.com"
$env:SMTP_PASSWORD = "your-app-password"
$env:SMTP_FROM = "your-address@gmail.com"
$env:FLASK_SECRET_KEY = "a-long-random-secret-value"
python app.py
```
Với SMTP dùng SSL trực tiếp, đặt `SMTP_PORT` là `465`. Mỗi nhân viên cần có email hợp lệ trong hồ sơ trước khi quản trị viên gửi mã.

Gửi SMS qua Twilio, cấu hình thêm các biến môi trường dưới đây. Số điện thoại Việt Nam trong hồ sơ có thể nhập dạng `0912345678` hoặc `+84912345678`.
```powershell
$env:TWILIO_ACCOUNT_SID = "AC..."
$env:TWILIO_AUTH_TOKEN = "your-auth-token"
# Chọn một trong hai:
$env:TWILIO_FROM = "+1..."
# hoặc $env:TWILIO_MESSAGING_SERVICE_SID = "MG..."
python app.py
```

## Quét giấy tờ nhân viên (OCR)
Trong trang **Nhân viên**, chọn **Quét giấy tờ nhân viên** để tải ảnh/PDF CCCD hoặc CV/sơ yếu lý lịch. OCR chạy cục bộ trên máy chủ; kết quả tự nhận dạng loại tài liệu và một số trường thông tin, sau đó mở form hồ sơ để người dùng kiểm tra và bổ sung trước khi lưu. Tệp tải lên không được lưu vào database.

Cài gói Python bằng `python -m pip install -r requirements.txt`, đồng thời cài **Tesseract OCR** trên máy chạy Flask và cài dữ liệu ngôn ngữ tiếng Việt (`vie`) cùng tiếng Anh (`eng`). Đảm bảo lệnh `tesseract` có trong `PATH`; nếu chưa có, đặt biến môi trường `TESSERACT_CMD` trỏ tới `tesseract.exe` và cấu hình chương trình dùng biến này. Tính năng nhận ảnh PNG/JPG/TIFF/BMP và PDF tối đa 5 trang, 10 MB. Cần kiểm tra thủ công mọi trường OCR trước khi lưu vì ảnh mờ, nghiêng hoặc chữ nhỏ có thể nhận sai.

## 4. Tính năng trong bản web
- Đăng nhập/đăng xuất và đổi mật khẩu
- Tổng quan nhân sự
- Quản lý nhân viên, phòng ban, chức vụ, hợp đồng (thêm/sửa/xóa/tìm kiếm/xuất CSV, Excel hoặc PDF)
- Chấm công vào/ra
- Quản trị viên lọc, sửa trạng thái và xuất chấm công theo ngày; nhân viên chỉ xem dữ liệu của mình
- Chấm công bằng nhận diện khuôn mặt (đăng ký có xác nhận đồng ý, xử lý ảnh trong trình duyệt, lưu mẫu đặc trưng trong SQL Server; cần Internet để tải thư viện và mô hình nhận diện từ jsDelivr)
- Gửi và duyệt đơn nghỉ phép
- Đơn nghỉ trùng khoảng ngày bị từ chối; số ngày nghỉ tính theo lịch làm việc cấu hình (hiện không tính Chủ nhật)
- Xem bảng lương, điều chỉnh mức thưởng chung theo tháng, lương cơ bản riêng và thưởng thêm; các thay đổi yêu cầu lý do và được ghi nhật ký; báo cáo tiến độ ngày công đếm sự kiện chấm vào hợp lệ, đồng thời hiển thị tổng giờ từ các cặp vào/ra hoàn tất để đối soát (không tự dùng giờ này để tính lương)
- Xuất danh sách chấm công, nghỉ phép, lương, báo cáo, điều chuyển và tài khoản theo định dạng CSV, Excel hoặc PDF
- **Quản lý hợp đồng mẫu, soạn hợp đồng bằng AI, xuất DOCX/PDF và lưu/tải lại các phiên bản đã tạo** (trong mục Hợp đồng)

Lưu ý: tạo tài khoản nhân viên qua giao diện (có OTP) đã được triển khai ở trang **Tài khoản**; bản web chưa thay thế đầy đủ tính năng tính lương nâng cao của ứng dụng desktop. Hãy thử trên bản sao database trước.

### Employee Master Profile — mã nhân viên dùng chung

`NhanVien.MaNV` là mã nội bộ chuẩn và được tạo bởi SQL Server; mã này không đổi khi sửa hồ sơ, đổi công việc hoặc nghỉ việc. `MaNVHT` là mã hiển thị, không dùng làm khóa liên kết. Tài khoản, chấm công, nghỉ phép, lương và hợp đồng hiện liên kết với cùng `MaNV`; module mới phải lưu khóa ngoại tới `NhanVien.MaNV`, không tạo bản hồ sơ nhân viên riêng.

Khi tạo hồ sơ thủ công, ứng dụng dùng `employee_profiles.create_employee()` và khóa nguồn để gửi lại cùng yêu cầu không tạo hồ sơ thứ hai. Module có hồ sơ nguồn bên ngoài có thể dùng `employee_profiles.link_source()` để liên kết khóa nguồn ổn định với một `MaNV` đã có. Ứng viên chỉ trở thành nhân viên sau khi chấp nhận offer; luồng tuyển dụng dùng khóa nguồn `recruitment` để liên kết idempotent với một `MaNV`.

### Tuyển dụng và vòng đời nhân viên

Quản trị viên quản lý yêu cầu tuyển dụng, pipeline ứng viên, lịch phỏng vấn, đánh giá và offer. Offer ở trạng thái bản nháp đến khi HR xác nhận đã gửi; chấp nhận offer sẽ tạo hồ sơ chuẩn một lần. Tài khoản quản trị được giới hạn trong phân hệ này.

Onboarding/offboarding tạo checklist liên phòng ban từ mẫu cấu hình. Chỉ hoàn tất offboarding sau khi xử lý checklist, thu hồi hết tài sản đang giao và đến ngày hiệu lực; khi hoàn tất, tài khoản bị thu hồi phiên, hồ sơ chuyển trạng thái nghỉ việc và mẫu khuôn mặt bị xóa. Quản trị viên theo dõi việc cấp/thu hồi thiết bị tại **Tài sản nhân viên**; lịch sử thao tác được giữ theo `MaNV` và có thể xuất CSV, Excel hoặc PDF. Việc tạo/khóa tài khoản và đồng bộ thiết bị ngoài vẫn cần bộ phận phụ trách xử lý thủ công.

### Hiệu suất và mục tiêu

HR tạo chu kỳ, khung năng lực và mục tiêu cá nhân/phòng ban; trọng số mục tiêu áp dụng cho từng nhân viên trong chu kỳ phải cộng đủ 100%. Nhân viên cập nhật kết quả, tự đánh giá năng lực và gửi bản tự đánh giá theo chu kỳ. Quản lý trực tiếp chấm năng lực và điểm quản lý (0–100), rồi chuyển HR phê duyệt. Điểm mục tiêu = tổng (min(thực tế/chỉ tiêu, 100%) × trọng số); điểm cuối = 70% điểm mục tiêu + 30% điểm quản lý. HR phê duyệt chốt kết quả mục tiêu; các lần cập nhật và bước duyệt được lưu theo chu kỳ. Nhân viên có thể đề xuất vai trò mục tiêu và kế hoạch phát triển; quản lý xem xét, HR phê duyệt. Đây là công thức khởi điểm của ứng dụng, cần được doanh nghiệp xác nhận trước khi dùng cho quyết định nhân sự.

### Đào tạo và phúc lợi

Đào tạo liên kết khóa học, đăng ký/duyệt, trạng thái hoàn thành, chứng chỉ/hạn chứng chỉ và hồ sơ kỹ năng cấp độ 1–5 cùng kế hoạch phát triển với `MaNV`. Cấp độ tự khai cần HR xác minh. Phúc lợi có danh mục, mô tả điều kiện, đăng ký nhân viên và duyệt/từ chối của HR; phần điều kiện hưởng hiện được HR xác minh thủ công, chưa tự động tính theo hợp đồng hoặc thời gian công tác.

### Hoạch định nhân lực

Quản trị viên lập kế hoạch headcount và chi phí theo năm/phòng ban/vị trí, đối chiếu với số nhân viên và tổng lương cơ bản hiện hành, và ghi nhận ứng viên kế nhiệm cùng độ sẵn sàng/khoảng trống kỹ năng. Đây là công cụ kế hoạch thủ công; không tự thay đổi định biên, tuyển dụng, lương hoặc điều chuyển.

### Phân tích nhân sự

Trang **Phân tích nhân sự** tổng hợp tuyển mới và offboarding được ghi nhận trong 12 tháng, nhân lực/lương cơ bản hiện tại theo phòng ban, độ phủ kỹ năng và đăng ký đào tạo. Số liệu nghỉ việc chỉ tính các quy trình offboarding đã hoàn tất trong hệ thống; chưa bao gồm lịch sử cũ, chưa có dự báo nghỉ việc/giữ chân hoặc phân tích xu hướng chuyên sâu.

### Cấu trúc tổ chức và hồ sơ điện tử

Quản trị viên quản lý Đơn vị, Phòng ban, Chức vụ (chức danh) và Vị trí công việc riêng; trang **Sơ đồ tổ chức** hiển thị cây đơn vị/phòng ban/nhân viên. Hồ sơ nhân viên có thể gắn vị trí công việc. Hệ thống thêm các bảng và khóa ngoại theo cách tương thích, không tự gán các phòng ban hiện hữu vào đơn vị mới.

Thay đổi phòng ban, chức danh, vị trí, lương cơ bản và quản lý trực tiếp được ghi thành các giai đoạn trong `LichSuCongTac`; quản trị viên và chính nhân viên có thể xem lịch sử tương ứng. Khi nâng cấp, trạng thái hiện tại cũ được ghi thành mốc bắt đầu từ ngày nâng cấp, không suy diễn ngược thay đổi trong quá khứ.

Nhật ký hồ sơ tại trang hồ sơ điện tử ghi nhận thao tác tạo/sửa/xóa, tên trường thay đổi, người thực hiện và thời điểm. Nhật ký không lưu giá trị CCCD, thông tin liên hệ hoặc lương; quyền xem giới hạn cho quản trị viên và chính nhân viên.

Tài liệu hồ sơ được mã hóa bằng Fernet trước khi lưu trong SQL Server; quyền xem/tải được kiểm tra theo tài khoản quản trị hoặc chính nhân viên và lượt xem/tải được ghi nhật ký. Trước khi dùng chức năng này, tạo khóa riêng và giữ ổn định qua các lần chạy:
```powershell
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
$env:HR_DOCUMENT_ENCRYPTION_KEY = "<khóa-vừa-tạo>"
```
Lưu khóa ở nơi quản lý bí mật an toàn và sao lưu tách biệt với database; mất khóa sẽ không giải mã được các tệp. Chỉ nhận PDF, DOCX, JPEG, PNG tối đa 8 MB. Hạn lưu là ngày nhắc rà soát, hệ thống không tự xóa tài liệu; chính sách lưu trữ và xóa cần do doanh nghiệp phê duyệt.

Quản trị viên có thể định nghĩa trường hồ sơ tùy chỉnh kiểu văn bản, số, ngày, có/không hoặc email. Trường được lưu trong bảng giá trị riêng theo `MaNV`, không tạo cột SQL theo tên do người dùng nhập. Có thể đánh dấu trường nhạy cảm để chỉ quản trị viên xem và sửa; trường đã có dữ liệu chỉ được ngừng sử dụng, không xóa.

### Chấm công theo sự kiện (giai đoạn chuyển tiếp)

`ChamCongSuKien` lưu từng giờ vào/ra, nguồn ghi nhận, kết quả và người thực hiện. Dữ liệu giờ vào/ra từ `ChamCong` cũ được nhập idempotent vào bảng sự kiện; mọi lần chấm mới được ghi thành chuỗi `vào → ra → vào`, với cập nhật sự kiện và dòng tổng hợp `ChamCong` trong cùng transaction SQL Server. `ChamCong` tiếp tục lưu giờ vào đầu và giờ ra gần nhất để tương thích module cũ; payroll vẫn tính tối đa một ngày công cho mỗi ngày. Ca qua đêm gắn giờ ra sau nửa đêm về ngày bắt đầu ca. Nhân viên và quản trị viên xem nhật ký sự kiện theo phạm vi quyền.

Quản trị viên có thể tạo ca sáng/chiều/đêm, phân ca theo ngày và cấu hình ngày lễ/nghỉ. Khi một nhân viên có ca được phân trong kỳ, chỉ các ngày đã phân ca được xem là ngày làm dự kiến; hệ thống không tự suy đoán ca cho ngày chưa phân. Ngưỡng đi muộn dùng giờ bắt đầu và phút ân hạn của ca. Nếu kỳ chưa có phân ca, hệ thống dùng lịch tuần riêng của nhân viên hoặc cấu hình mặc định. Ngày lễ được loại khỏi ngày nghỉ không phép. Nhân viên gửi yêu cầu tăng ca, quản trị viên phê duyệt và xác nhận giờ thực tế; chỉ giờ đã xác nhận mới vào payroll khi tính lại kỳ lương nháp. Mỗi lần tính payroll lưu snapshot tổng giờ từ các cặp sự kiện vào/ra hoàn tất để đối soát; giờ này chưa tự làm thay đổi lương. Phần tiền tăng ca chỉ dùng giờ trong yêu cầu đã được xác nhận. Phụ cấp ngày lễ chưa được tính.

### Chấm công bằng khuôn mặt
Ở trang **Chấm công**, nhân viên tự đăng ký khuôn mặt bằng tài khoản đã gắn với hồ sơ; quản trị viên không thực hiện chấm công khuôn mặt thay nhân viên. Quản trị viên tải ảnh hồ sơ lên, nhân viên xác nhận đồng ý rồi đăng ký mẫu từ ảnh hồ sơ. Khi chấm công, nhân viên chọn hoặc chụp một ảnh rõ mặt (ảnh tĩnh, không phải video trực tiếp) rồi bấm **Quét ảnh và chấm công**. Ảnh được xử lý trên thiết bị và không gửi lên máy chủ; vector đặc trưng được gửi tới máy chủ và lưu trong database dưới dạng mã hóa. Người dùng có thể xóa mẫu đã đăng ký.

Trình duyệt cần truy cập Internet để tải Human 3.3.6 cùng mô hình từ jsDelivr; thiết bị di động có thể yêu cầu quyền camera khi chọn chụp ảnh. Luồng hiện chưa có phát hiện người thật/chống giả mạo; ngưỡng nhận diện ban đầu chưa được hiệu chuẩn theo thiết bị và nhân viên thực tế. Giữ phương thức quản trị viên ghi nhận/điều chỉnh và kiểm tra/hiệu chuẩn trước khi dùng kết quả khuôn mặt làm căn cứ tính lương.

### Bảo vệ dữ liệu và đánh giá độ tin cậy của chấm công khuôn mặt

Ứng dụng mã hóa vector khuôn mặt bằng Fernet trước khi ghi vào SQL Server. Cài thư viện từ `requirements.txt`, sau đó tạo khóa một lần và đặt trong biến môi trường của tiến trình chạy Flask (không commit khóa, không gửi khóa qua chat):
```powershell
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
$env:FACE_ENCRYPTION_KEY = "<khóa vừa tạo>"
$env:FACE_RETENTION_DAYS = "365"
$env:FACE_MATCH_THRESHOLD = "0.82"
$env:FACE_ANTISPOOF_THRESHOLD = "0.70"
$env:FACE_LIVENESS_THRESHOLD = "0.70"
python app.py
```
Giữ nguyên cùng một `FACE_ENCRYPTION_KEY` qua các lần khởi động và lưu bản sao khóa ở nơi quản trị bí mật có kiểm soát. Mất khóa đồng nghĩa không thể giải mã các mẫu đã lưu. Khóa mã hóa vector mới không thể giải mã các mẫu cũ đang lưu dạng văn bản; sau khi triển khai cần cho nhân viên đăng ký lại mẫu, rồi xóa các mẫu cũ. Hệ thống xóa mẫu quá hạn trong lần đầu mở trang chấm công mỗi ngày; nếu ứng dụng không được mở trang này, việc dọn mẫu sẽ chạy khi trang được mở trở lại.

`FACE_MATCH_THRESHOLD` hiện mặc định `0.82` chỉ là giá trị khởi đầu, không phải ngưỡng đã được chứng nhận. Trước khi áp dụng, hãy thử trên bộ ảnh có sự đồng ý, gồm nhiều lần chụp thật của đúng nhân viên và ảnh của người khác trong điều kiện thiết bị/ánh sáng thực tế. Ghi số lần người khác được chấp nhận để tính FAR (tỷ lệ nhận nhầm) và số lần nhân viên hợp lệ bị từ chối để tính FRR (tỷ lệ từ chối nhầm); chọn ngưỡng theo mức rủi ro và lưu kết quả thử nghiệm. Không có bộ thử nghiệm thực tế đính kèm nên dự án chưa thể hiệu chuẩn ngưỡng.

Ảnh tĩnh không chứng minh người đang chấm công là người thật. Luồng yêu cầu camera trực tiếp, thử thách chuyển động và sàng lọc điểm anti-spoof/liveness bằng Human chạy trên thiết bị; video không gửi lên máy chủ. Tuy vậy, trình duyệt có thể bị sửa và các điểm gửi từ máy khách không phải bằng chứng chống giả mạo có thể xác minh độc lập. Không dùng kết quả này làm căn cứ duy nhất để tính lương hoặc xử lý kỷ luật; nếu cần độ tin cậy cao, hãy tích hợp dịch vụ liveness có xác minh phía máy chủ hoặc thiết bị chuyên dụng. Chấm công thường và quy trình ngoại lệ vẫn là phương án dự phòng.

Thông báo tại bước đăng ký nêu mục đích đối chiếu chấm công, thời hạn lưu cấu hình và quyền rút lại đồng ý/xóa mẫu. Cấu hình mặc định lưu tối đa 365 ngày tính từ lần đồng ý; đơn vị cần đặt `FACE_RETENTION_DAYS` theo chính sách được phê duyệt và quy định áp dụng, đồng thời thông báo cho nhân viên về quyền truy cập, chỉnh sửa, rút lại đồng ý và yêu cầu xóa. Luật Bảo vệ dữ liệu cá nhân số 91/2025/QH15 có hiệu lực từ 01/01/2026; việc triển khai thực tế cần được đơn vị rà soát theo luật và văn bản hướng dẫn hiện hành.

## Bảo mật (đã cập nhật)
- **Không ghi khóa API vào mã nguồn.** Mọi khóa (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`) chỉ đọc từ biến môi trường. Nếu trước đây khóa từng nằm trong `config.py`, hãy thu hồi khóa cũ và tạo khóa mới.
- Chọn nhà cung cấp AI bằng biến môi trường `AI_PROVIDER` (`anthropic` mặc định, hoặc `openai` cho Gemini/OpenAI; khi đó đặt thêm `OPENAI_API_KEY`, `OPENAI_BASE_URL`, `OPENAI_MODEL`). Tra cứu web chỉ có khi dùng Claude.
- Mọi form và lời gọi POST đều có token CSRF; đăng nhập sai 5 lần sẽ khóa 5 phút theo cặp IP và tên đăng nhập; mật khẩu tối thiểu 10 ký tự; OTP được lưu phía máy chủ trong SQL Server.
- Nhân viên đã có lịch sử lương, chấm công, nghỉ phép hoặc hợp đồng không bị xóa cứng; hãy chuyển trạng thái sang “Đã nghỉ việc”. Hợp đồng có tệp phiên bản lưu cũng không bị xóa cứng.

## 5. Soạn hợp đồng bằng AI (Word)
1. Cài thư viện mới: `python -m pip install -r requirements.txt` (gồm `python-docx`, `anthropic`, `PyMuPDF`, `reportlab`).
2. Lấy API key tại https://console.anthropic.com rồi đặt biến môi trường (PowerShell):
   ```powershell
   setx ANTHROPIC_API_KEY "sk-ant-..."
   ```
   Mở lại terminal. Không có key vẫn dùng được, hệ thống sẽ xuất theo mẫu điều khoản chuẩn.
3. Mở `config.py`, sửa mục `COMPANY` (tên, địa chỉ, MST, người đại diện). Nút **Kiểm tra kết nối AI** trên trang soạn hợp đồng cho biết kết nối đã thông chưa.
   - Tick **Cho AI tra cứu web** để Claude tra quy định mới nhất (lương tối thiểu vùng, thử việc, báo trước...) và cảnh báo "LƯU Ý HR" nếu lương thấp hơn mức tối thiểu.
   - Muốn dùng AI khác: đặt `AI_PROVIDER = "openai"`, điền `OPENAI_API_KEY`, `OPENAI_BASE_URL`, `OPENAI_MODEL` (không có tra cứu web).
4. Trong mục **Hợp đồng**, kéo thả hoặc chọn mẫu `.doc`, `.docx` hoặc `.pdf`. DOC cũ được chuyển bằng Microsoft Word cài trên máy chạy ứng dụng; DOCX có văn bản được đọc trực tiếp; DOCX chứa ảnh scan và PDF scan cần Tesseract OCR (tối đa 5 ảnh trong DOCX hoặc 5 trang PDF). Hệ thống trích xuất văn bản để xem lại và làm tài liệu tham khảo cho AI. Khi soạn, chọn mẫu, chọn nhân viên rồi tải hợp đồng dạng Word `.docx` hoặc PDF. Tệp đầu ra dùng định dạng chuẩn của hệ thống, không giữ nguyên bố cục đồ họa của tệp mẫu.

Bảo mật: thông tin nhân viên trong hồ sơ được ghép vào file Word ngay trên máy chủ của bạn, không gửi cho AI. Nếu chọn hợp đồng mẫu, phần văn bản trích từ mẫu và thông tin công việc/lương/ngày hợp đồng sẽ được gửi tới nhà cung cấp AI đã cấu hình; hãy xóa thông tin cá nhân khỏi mẫu trước khi tải lên. Nội dung AI soạn chỉ là bản nháp, cần nhân sự/pháp chế rà soát trước khi ký.

### Các loại hợp đồng hỗ trợ
Thử việc · Có thời hạn · Không thời hạn · Thời vụ · Bán thời gian · Học việc · Cộng tác viên (hợp đồng dịch vụ, theo Bộ luật Dân sự) · Đào tạo (cam kết làm việc và hoàn trả chi phí). Mỗi loại có tiêu đề, căn cứ pháp lý, cách gọi hai bên và mẫu điều khoản riêng.
Muốn thêm loại mới: thêm một dòng vào `TYPES` trong `contracts.py` và thêm tên loại vào danh sách `choice:` của mục `hopdong` trong `app.py`.

### Cách chọn dữ liệu khi soạn
- **Soạn mới** (mặc định): chọn nhân viên + loại hợp đồng + ngày + lương (tự điền theo lương cơ bản). Có thể tick "Đồng thời lưu hợp đồng vào danh sách Hợp đồng" khi tải file.
- **Dùng hợp đồng đã có**: chọn từ danh sách các hợp đồng đã nhập trong hệ thống.

### Vòng đời hợp đồng

Hợp đồng mới và nội dung do AI tạo được lưu là **Bản nháp**. Quản trị viên gửi HR/pháp chế duyệt, ghi nhận người duyệt, rồi tải lên bản PDF/DOCX đã ký cùng ngày ký để chuyển sang **Đã ký** hoặc **Còn hiệu lực**. Tải hoặc lưu bản AI không tự đổi trạng thái sang đã duyệt/đã ký. Hợp đồng được đồng bộ trạng thái hiệu lực theo ngày bắt đầu/kết thúc; trang Hợp đồng cảnh báo các mốc còn 30, 60 và 90 ngày.

  Trong **Vòng đời**, quản trị viên có thể trả bản chờ duyệt kèm lý do chỉnh sửa, tạo bản nháp gia hạn/tái ký liên kết với hợp đồng trước, ghi nhận chấm dứt và tải phụ lục, quyết định thay đổi lương/chức vụ hoặc tài liệu liên quan. Hợp đồng đang hiệu lực tiếp tục có hiệu lực trong lúc bản gia hạn được soạn và duyệt; hợp đồng cũ chỉ chuyển sang **Đã gia hạn** sau khi bản mới được ký. Mỗi tệp có loại, phiên bản, người lập, người duyệt/ngày duyệt, ngày ký và ghi chú; thao tác được lưu trong lịch sử. Quyết định/Phụ lục chỉ hiện với nhân viên khi quản trị viên xác nhận đã ký. Tệp chính thức tối đa 10 MB, định dạng PDF hoặc DOCX.

Quản trị viên xem và tải mọi tài liệu. Tài khoản nhân viên chỉ xem hợp đồng và tệp chính thức đã ký thuộc hồ sơ của chính mình; bản nháp AI và tài liệu chưa ký bị chặn. Các tệp cũ trước khi có phân loại được xếp thành bản nháp AI để an toàn; muốn nhân viên xem, quản trị viên cần tải lại bản gốc đã ký qua quy trình Vòng đời.

## 6. Dữ liệu mẫu để dùng thử
Sau khi chạy `setup_db.py`, chạy thêm:
```
python seed_sample.py
```
Lệnh này thêm 10 nhân viên mẫu (đủ 5 phòng ban) và 9 hợp đồng mẫu đủ các loại (Không thời hạn, Có thời hạn, Thử việc, Thời vụ, Bán thời gian, Học việc, Cộng tác viên). Chạy lại nhiều lần không bị trùng. Họ tên, CCCD, SĐT trong dữ liệu mẫu đều là dữ liệu giả.

### Quy trình bảng lương

Bảng lương có trạng thái **Nháp → Đã duyệt → Đã khóa**. Quản trị viên có thể tính lại và chỉnh mức chung khi kỳ còn nháp; thao tác phê duyệt và khóa yêu cầu lý do và được ghi vào lịch sử. Chỉ kỳ đã khóa mới cho phép xuất bảng lương và xem phiếu lương cá nhân. Tăng ca chỉ tính vào payroll sau khi quản trị viên duyệt trước và xác nhận số giờ thực tế sau ca; cần tính lại kỳ lương còn nháp để áp dụng. Đi muộn được ghi nhận riêng; cấu hình mặc định không tự khấu trừ tiền lương.

Trang lương hỗ trợ tạo/duyệt chính sách thuế và bảo hiểm có phiên bản, hồ sơ cư trú/người phụ thuộc/đối tượng đóng theo ngày hiệu lực, khoản phụ cấp/thưởng/phạt/khấu trừ và snapshot đầu vào/kết quả cho từng dòng lương. Chính sách không có sẵn tỷ lệ pháp lý; phải được HR/kế toán điền căn cứ, cấu hình và duyệt. Khi thiếu chính sách hoặc hồ sơ cá nhân, hệ thống đánh dấu chưa có snapshot và không coi các số 0 là kết quả đã đối soát. Nguồn công/phép/tăng ca được lưu cùng snapshot; chỉnh nguồn làm kỳ nháp cần tính lại.

Lương cơ bản dùng lịch sử công tác có ngày hiệu lực và phân bổ theo ngày lịch. Tiền tăng ca tính theo giờ đã được yêu cầu, duyệt và xác nhận; tổng giờ sự kiện chấm công giữ làm dữ liệu đối chiếu, không tự coi toàn bộ giờ làm là giờ tăng ca. Bản hiện tại dùng một chính sách toàn doanh nghiệp cho mỗi ngày hiệu lực, một hệ số OT chung và chưa tách nhóm chính sách theo vùng/hợp đồng hoặc OT ngày thường/ngày nghỉ/ngày lễ/ban đêm. Vì vậy cần hoàn tất các nhóm và phân loại đó trước khi dùng để trả lương chính thức. Xem [PAYROLL_POLICY_GUIDE.md](PAYROLL_POLICY_GUIDE.md) để biết cấu trúc và giới hạn.

Các module mới hiện được bảo vệ chủ yếu theo vai trò quản trị/nhân viên và quyền xem hồ sơ của chính nhân viên. Chưa có bộ vai trò chuyên biệt HR, kế toán, quản lý trực tiếp với phạm vi dữ liệu theo phòng ban; audit việc xem/tải toàn bộ trường nhạy cảm cũng chưa hoàn tất. Không xem đây là phân quyền đủ để triển khai nhiều đơn vị/người dùng.

### Quy trình nghỉ phép

Trang **Nghỉ phép** phân loại Phép năm, Không lương, Nghỉ ốm, Việc riêng có lương và Khác. Quản trị viên phải cấp quỹ phép năm theo từng nhân viên/năm và có thể nhập số ngày chuyển từ năm trước; nếu chưa cấp, số dư phép năm là 0 và đơn phép năm bị từ chối khi gửi. Nếu trong khoảng nghỉ có phân ca, số ngày phép được đếm theo các ngày đã phân ca; nếu không, dùng lịch tuần riêng của nhân viên hoặc `NGAY_NGHI_TUAN` trong `config.py`. Ngày đã cấu hình trong lịch lễ không bị tính là ngày phép.

Các đơn đã có từ trước được gán loại **Khác** khi nâng schema để tránh tự suy đoán đó là phép năm và trừ sai quỹ.

Quy trình mặc định yêu cầu nhân sự duyệt. Trong cấu hình trang nghỉ phép, quản trị viên có thể bật thêm bước quản lý trực tiếp. Khi bật bước này, hãy gán quản lý là nhân viên đang làm và đã có tài khoản; quản lý duyệt bằng tài khoản nhân viên, còn bước nhân sự do tài khoản quản trị viên xử lý. Đơn đã từ chối, rút hoặc hủy không chặn đơn mới cùng ngày; đơn đang chờ, đã duyệt hoặc có yêu cầu hủy/thay đổi vẫn giữ xung đột lịch. Khi sửa đơn phép năm, hệ thống chỉ giữ phần ngày tăng thêm so với số cũ; chuyển từ loại nghỉ khác sang phép năm thì giữ toàn bộ số ngày phép mới. Gửi/sửa đơn và cập nhật quỹ được khóa theo nhân viên trong transaction; hệ thống kiểm tra lại xung đột và số dư trước khi ghi để tránh các yêu cầu đồng thời cùng tiêu một phần quỹ. Quản trị viên không thể giảm quỹ dưới số ngày đã dùng/đang giữ.

Nhân viên có thể rút đơn đang chờ, yêu cầu hủy đơn đã duyệt, hoặc gửi thay đổi ngày/loại nghỉ; các thay đổi đều quay lại luồng duyệt. Thông báo trạng thái hiển thị trong trang Nghỉ phép. Loại nghỉ hiện được ghi nhận riêng cho nghiệp vụ và báo cáo; việc áp dụng các chính sách lương cụ thể cho từng loại nghỉ cần được cấu hình/đối chiếu trước khi dùng bảng lương chính thức.


### Nhật ký truy cập dữ liệu nhạy cảm

Quản trị viên có thể xem các lượt truy cập đã được ghi tại **Nhật ký truy cập**. Bảng NhatKyTruyCapNhanSu chỉ lưu loại dữ liệu, thao tác, mã nhân viên, người thực hiện và thời điểm; không lưu lại nội dung lương, liên hệ hoặc CCCD. Phạm vi hiện bao gồm một số màn hình nhân viên/lương, hồ sơ điện tử và hợp đồng. Đã ghi nhận xuất danh sách nhân viên, hợp đồng và bảng lương; các luồng xuất/đọc nhạy cảm khác vẫn cần nối audit trước khi coi đây là kiểm toán toàn diện.


### Rà soát hạn lưu hồ sơ điện tử

Quản trị viên mở **Hạn lưu hồ sơ** để xem tối đa 500 tài liệu đã quá hạn hoặc đến hạn trong 90 ngày, rồi mở hồ sơ nhân viên để rà soát. Ứng dụng không tự xóa tài liệu; mỗi lượt mở danh sách được ghi nhật ký truy cập. Các tệp vẫn được mã hóa theo cấu hình HR_DOCUMENT_ENCRYPTION_KEY.

### Cập nhật quy trình chấm công trực tiếp (2026-11)

- Quét ảnh tĩnh không còn được gửi để chấm công. Nhân viên phải cấp quyền camera, hoàn tất thử thách quay đầu ngẫu nhiên/chớp mắt và vượt các kiểm tra liveness/chống giả mạo chạy trên thiết bị. Video không gửi lên máy chủ; API nhận vector đối chiếu, điểm kiểm tra, nonce một lần và kết quả thử thách.
- Mẫu khuôn mặt cũ yêu cầu đăng ký lại và xác nhận thông báo mới `2026-11-v2`. Dùng `FACE_ANTISPOOF_THRESHOLD` và `FACE_LIVENESS_THRESHOLD` để hiệu chuẩn điểm mô hình (mặc định khởi đầu 0.70); không coi mặc định là mức chứng nhận.
- Thử thách phía trình duyệt làm tăng khó khăn cho ảnh tĩnh nhưng không phải xác minh chống giả mạo được chứng nhận: client có thể bị sửa và mô hình cục bộ có thể nhận sai. Dùng số liệu FAR/FRR trên thiết bị thật; triển khai rủi ro cao nên tích hợp nhà cung cấp liveness xác minh phía máy chủ. Chấm công dự phòng và khiếu nại vẫn là đường xử lý bắt buộc khi camera/model không đạt.

Quản lý ca hỗ trợ phân theo phòng ban cho một ngày, giờ bắt đầu/kết thúc tùy chỉnh theo từng lượt phân ca và đổi ca theo luồng nhân viên đề nghị → đồng nghiệp xác nhận → quản trị viên duyệt. Yêu cầu tăng ca hiển thị giờ đối soát từ cặp sự kiện vào/ra; chênh lệch với giờ đã duyệt cần lý do. Sự kiện sửa theo khiếu nại được ghi lại như lượt vào/ra thay thế để đối soát.

