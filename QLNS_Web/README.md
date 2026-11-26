# QLNS Web — Flask + SQL Server

Bản giao diện web chuyển từ ứng dụng Python/Tkinter sang Flask, tiếp tục sử dụng SQL Server và các bảng hiện có. Giao diện responsive cho máy tính và điện thoại.

## 1. Yêu cầu
- Windows 10/11
- Python 3.12 trở lên (mã nguồn dùng f-string lồng dấu nháy, chỉ hợp lệ từ Python 3.12)
- Microsoft ODBC Driver 17 hoặc 18 for SQL Server
- SQL Server Express/SQL Server đã chạy và có database `NHANSU_PY` cùng các bảng của dự án

## 2. Cấu hình kết nối

Hướng dẫn thao tác đầy đủ bằng SQL Server Management Studio (SSMS) nằm tại [docs/SQL_SERVER_SSMS_GUIDE.md](docs/SQL_SERVER_SSMS_GUIDE.md). Các script SSMS ở thư mục `database/migrations/` chỉ tạo database nếu chưa tồn tại và kiểm tra bảng/khóa ngoại; việc tạo/nâng cấp toàn bộ schema vẫn do mã Python hiện có quản lý để giữ logic migration.

Có thể đặt cấu hình trong `.env` (sao chép `.env.example`) hoặc bằng biến môi trường; file `.env` được nạp tự động nếu đã cài `python-dotenv`. Không commit `.env` hay khóa thật. Ví dụ PowerShell:
```powershell
$env:DB_SERVER = 'localhost\SQLEXPRESS03'
$env:DB_NAME = 'NHANSU_PY'
$env:DB_DRIVER = 'ODBC Driver 17 for SQL Server'
$env:DB_WINDOWS_AUTH = 'true'
```

`DB_SERVER` có thể là:
- `localhost\\SQLEXPRESS`
- `localhost\\SQLEXPRESS03`
- `localhost` (nếu dùng default instance)

`DB_WINDOWS_AUTH=true` dùng Windows Authentication; đặt `false` để dùng `DB_USER`/`DB_PASSWORD`. Môi trường production bắt buộc khai báo `DB_SERVER`, `DB_NAME` và thông tin xác thực phù hợp; ứng dụng không dùng cấu hình SQL Server cục bộ mặc định. Không đưa ứng dụng ra Internet khi đang dùng cấu hình thử nghiệm. Đặt `FLASK_SECRET_KEY` để giữ phiên đăng nhập ổn định giữa các lần khởi động; nếu chưa đặt trong môi trường phát triển, ứng dụng tạo khóa ngẫu nhiên và người dùng cần đăng nhập lại sau khi khởi động lại.

Hồ sơ nhân viên được tạo qua employee_profiles.create_employee() với mã gửi lại an toàn để một yêu cầu không tạo trùng hồ sơ.

## 3. Cài đặt và chạy trên Windows
Mở PowerShell tại thư mục dự án:
```powershell
Set-Location 'C:\Users\MANH\Downloads\QLNS_Web'
python -m venv .venv
& .\.venv\Scripts\python.exe -m pip install -r requirements.txt
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
# Sửa .env để khớp SQL Server và thông tin kết nối của máy bạn.
```
Nếu `.venv` đã tồn tại, bỏ qua lệnh tạo môi trường. Có thể dùng `& .\.venv\Scripts\python.exe ...` mà không cần bật `Activate.ps1`.

### Khởi tạo hoặc nâng cấp database

- Database hoàn toàn mới: cấu hình `.env`, sau đó chạy `& .\.venv\Scripts\python.exe -m database.setup_db`. Lệnh này tạo schema và tài khoản admin ban đầu.
- Database đã có dữ liệu: dừng ứng dụng, cấu hình migration account rồi chạy `& .\.venv\Scripts\python.exe -m database.migrate_db`. Với Windows Authentication:

```powershell
$env:DB_MIGRATION_WINDOWS_AUTH = 'true'
& .\.venv\Scripts\python.exe -m database.migrate_db
```

Chỉ khởi động ứng dụng sau khi khởi tạo/nâng cấp kết thúc thành công. Không chạy `setup_db` thay cho migration trên database đang sử dụng:

```powershell
& .\.venv\Scripts\python.exe app.py
```

Mở trình duyệt tại http://127.0.0.1:5000. Giữ cửa sổ PowerShell đang chạy; nhấn `Ctrl+C` để dừng server.

Sau khi tạo hoặc nâng cấp schema, ứng dụng chỉ nhận request khi `QlnsSchemaVersion` đã được đánh dấu hoàn tất. Với database hiện có, dừng web workers, đặt cấu hình kết nối và chạy `& .\.venv\Scripts\python.exe -m database.migrate_db` bằng migration account, sau đó khởi động lại ứng dụng. Web account không cần quyền thay đổi schema. Lệnh cũ `& .\.venv\Scripts\python.exe migrate_db.py` vẫn được giữ để tương thích.

Schema đăng nhập dùng bảng `VaiTro` và khóa ngoại `TaiKhoan.MaVaiTro` với ba vai trò `ADMIN`, `HR_ACCOUNTANT`, `EMPLOYEE`. Bảng `TaiKhoan` dùng `TenDangNhap`, `MatKhau`, `MaVaiTro`, `MaNV`, `TrangThai`, `NgayTao`; `TrangThai=1` là hoạt động, `0` là bị khóa. Khi cập nhật mã nguồn, dừng web workers và chạy migration trước khi bật lại. Trang Tài khoản cho quản trị viên khóa/mở khóa; khóa tài khoản sẽ thu hồi phiên đang đăng nhập. Mật khẩu được băm PBKDF2-HMAC-SHA256. Đây là tài khoản ứng dụng lưu trong SQL Server, không phải SQL Server login dùng để kết nối database.

Migration chuyển `QuanTri` cũ sang `ADMIN`; `QuanTriHeThong`, HR và kế toán cũ sang `HR_ACCOUNTANT`; nhân viên/quản lý cũ sang `EMPLOYEE`. Các bước nghỉ phép đang chờ quản lý được chuyển sang hàng chờ Nhân sự/Kế toán để phù hợp ma trận mới.

**An toàn dữ liệu:** sao lưu database và xác nhận có thể khôi phục trước mỗi lần migration. Migration hiện tại không xóa các bảng dữ liệu mở rộng hồ sơ cũ; không chạy script DDL thủ công hoặc xóa bảng nếu chưa đối chiếu dữ liệu và có bản backup đã kiểm tra.

Khi chạy `setup_db.py`, mật khẩu `admin` lấy từ biến môi trường `ADMIN_PASSWORD` (10–256 ký tự) hoặc được tự sinh ngẫu nhiên và in ra một lần; hãy lưu lại. Chỉ chạy `& .\.venv\Scripts\python.exe -m database.setup_db` nếu bạn muốn tạo database/bảng mẫu và đã xác nhận cấu hình `config.py` đúng. Sao lưu database trước khi chạy trên dữ liệu thật.

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
& .\.venv\Scripts\python.exe app.py
```
Với SMTP dùng SSL trực tiếp, đặt `SMTP_PORT` là `465`. Mỗi nhân viên cần có email hợp lệ trong hồ sơ trước khi quản trị viên gửi mã.

Gửi SMS qua Twilio, cấu hình thêm các biến môi trường dưới đây. Số điện thoại Việt Nam trong hồ sơ có thể nhập dạng `0912345678` hoặc `+84912345678`.
```powershell
$env:TWILIO_ACCOUNT_SID = "AC..."
$env:TWILIO_AUTH_TOKEN = "your-auth-token"
# Chọn một trong hai:
$env:TWILIO_FROM = "+1..."
# hoặc $env:TWILIO_MESSAGING_SERVICE_SID = "MG..."
& .\.venv\Scripts\python.exe app.py
```

## 4. Tám chức năng chính

1. **Tài khoản và phân quyền** — đăng nhập, đổi mật khẩu, tạo/quản lý tài khoản, gán vai trò và kiểm soát quyền truy cập.
2. **Quản lý phòng ban** — đơn vị, phòng ban, chức vụ, vị trí công việc, sơ đồ tổ chức và điều chuyển.
3. **Quản lý nhân viên** — hồ sơ chuẩn theo MaNV, thêm/sửa/tìm kiếm/lọc, lịch sử công tác và tài liệu hồ sơ.
4. **Quản lý hợp đồng** — danh sách hợp đồng, mẫu, tệp/phiên bản, vòng đời và công cụ soạn nháp.
5. **Quản lý chấm công** — ghi nhận vào/ra, đối soát, ca làm việc và yêu cầu tăng ca.
6. **Quản lý nghỉ phép** — gửi/duyệt đơn, kiểm tra trùng lịch, lịch làm việc và theo dõi quỹ phép.
7. **Quản lý tiền lương** — tính lương từ nhân viên, công, nghỉ và tăng ca; điều chỉnh, duyệt, khóa kỳ và phiếu lương.
8. **Thống kê và báo cáo** — tổng hợp theo kỳ, biểu đồ và xuất CSV/Excel/PDF theo quyền.

**Dashboard** là trang tổng quan dùng chung, không tính là chức năng thứ 9. Nhật ký kiểm toán, xuất tệp và các tiện ích dùng chung phục vụ tám chức năng trên. Hồ sơ nhân viên vẫn là nguồn dữ liệu chuẩn liên kết bằng MaNV.

### Employee Master Profile — mã nhân viên dùng chung

`NhanVien.MaNV` là mã nội bộ chuẩn và được tạo bởi SQL Server; mã này không đổi khi sửa hồ sơ, đổi công việc hoặc nghỉ việc. `MaNVHT` là mã hiển thị, không dùng làm khóa liên kết. Tài khoản, chấm công, nghỉ phép, lương và hợp đồng hiện liên kết với cùng `MaNV`; module mới phải lưu khóa ngoại tới `NhanVien.MaNV`, không tạo bản hồ sơ nhân viên riêng.

Hồ sơ nhân viên được tạo qua employee_profiles.create_employee() với mã gửi lại an toàn để một yêu cầu không tạo trùng hồ sơ.

### Cấu trúc tổ chức và hồ sơ điện tử

Quản trị viên quản lý Đơn vị, Phòng ban, Chức vụ (chức danh) và Vị trí công việc riêng; trang **Sơ đồ tổ chức** hiển thị cây đơn vị/phòng ban/nhân viên. Hồ sơ nhân viên có thể gắn vị trí công việc. Hệ thống thêm các bảng và khóa ngoại theo cách tương thích, không tự gán các phòng ban hiện hữu vào đơn vị mới.

Thay đổi phòng ban, chức danh, vị trí, lương cơ bản và quản lý trực tiếp được ghi thành các giai đoạn trong `LichSuCongTac`; quản trị viên và chính nhân viên có thể xem lịch sử tương ứng. Khi nâng cấp, trạng thái hiện tại cũ được ghi thành mốc bắt đầu từ ngày nâng cấp, không suy diễn ngược thay đổi trong quá khứ.

Nhật ký hồ sơ tại trang hồ sơ điện tử ghi nhận thao tác tạo/sửa/xóa, tên trường thay đổi, người thực hiện và thời điểm. Nhật ký không lưu giá trị CCCD, thông tin liên hệ hoặc lương; quyền xem giới hạn cho quản trị viên và chính nhân viên.

Tài liệu hồ sơ được mã hóa bằng Fernet trước khi lưu trong SQL Server; quyền xem/tải được kiểm tra theo tài khoản quản trị hoặc chính nhân viên và lượt xem/tải được ghi nhật ký. Trước khi dùng chức năng này, tạo khóa riêng và giữ ổn định qua các lần chạy:
```powershell
& .\.venv\Scripts\python.exe -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
$env:HR_DOCUMENT_ENCRYPTION_KEY = "<khóa-vừa-tạo>"
```
Lưu khóa ở nơi quản lý bí mật an toàn và sao lưu tách biệt với database; mất khóa sẽ không giải mã được các tệp. Chỉ nhận PDF, DOCX, JPEG, PNG tối đa 8 MB. Hạn lưu là ngày nhắc rà soát, hệ thống không tự xóa tài liệu; chính sách lưu trữ và xóa cần do doanh nghiệp phê duyệt.


### Chấm công theo sự kiện (giai đoạn chuyển tiếp)

`ChamCongSuKien` lưu từng giờ vào/ra, nguồn ghi nhận, kết quả và người thực hiện. Dữ liệu giờ vào/ra từ `ChamCong` cũ được nhập idempotent vào bảng sự kiện; mọi lần chấm mới được ghi thành chuỗi `vào → ra → vào`, với cập nhật sự kiện và dòng tổng hợp `ChamCong` trong cùng transaction SQL Server. `ChamCong` tiếp tục lưu giờ vào đầu và giờ ra gần nhất để tương thích module cũ; payroll vẫn tính tối đa một ngày công cho mỗi ngày. Ca qua đêm gắn giờ ra sau nửa đêm về ngày bắt đầu ca. Nhân viên và quản trị viên xem nhật ký sự kiện theo phạm vi quyền.

Quản trị viên có thể tạo ca sáng/chiều/đêm, phân ca theo ngày và cấu hình ngày lễ/nghỉ. Khi một nhân viên có ca được phân trong kỳ, chỉ các ngày đã phân ca được xem là ngày làm dự kiến; hệ thống không tự suy đoán ca cho ngày chưa phân. Ngưỡng đi muộn dùng giờ bắt đầu và phút ân hạn của ca. Nếu kỳ chưa có phân ca, hệ thống dùng lịch tuần riêng của nhân viên hoặc cấu hình mặc định. Ngày lễ được loại khỏi ngày nghỉ không phép. Nhân viên gửi yêu cầu tăng ca, quản trị viên phê duyệt và xác nhận giờ thực tế; chỉ giờ đã xác nhận mới vào payroll khi tính lại kỳ lương nháp. Mỗi lần tính payroll lưu snapshot tổng giờ từ các cặp sự kiện vào/ra hoàn tất để đối soát; giờ này chưa tự làm thay đổi lương. Phần tiền tăng ca chỉ dùng giờ trong yêu cầu đã được xác nhận. Phụ cấp ngày lễ chưa được tính.

### Chấm công bằng khuôn mặt
Ở trang **Chấm công**, mỗi nhân viên đăng nhập tài khoản cá nhân, xác nhận đồng ý rồi đăng ký mẫu từ ảnh hồ sơ đã lưu. Khi chấm công, nhân viên dùng camera trên chính thiết bị của mình, hoàn thành thử thách chuyển động và được đối chiếu với mẫu đã đăng ký; hệ thống chỉ ghi công sau khi nhận diện thành công. API chấm công khuôn mặt chỉ phục vụ tài khoản nhân viên tự chấm công, không cung cấp kiosk để quản trị viên chấm thay. Video được xử lý trên thiết bị, không gửi lên máy chủ; vector đặc trưng được gửi để đối chiếu và lưu trong database dưới dạng mã hóa. Người dùng có thể xóa mẫu đã đăng ký.


Trình duyệt cần truy cập Internet để tải Human 3.3.6 cùng mô hình từ jsDelivr và cần được cấp quyền camera. Luồng có kiểm tra liveness/chống giả mạo chạy trên thiết bị, nhưng điểm do trình duyệt gửi không phải bằng chứng chống giả mạo có thể xác minh độc lập. Ngưỡng nhận diện ban đầu chưa được hiệu chuẩn theo thiết bị và nhân viên thực tế; hãy giữ phương thức chấm công dự phòng và kiểm tra/hiệu chuẩn trước khi dùng kết quả khuôn mặt làm căn cứ tính lương.

### Bảo vệ dữ liệu và đánh giá độ tin cậy của chấm công khuôn mặt

Ứng dụng mã hóa vector khuôn mặt bằng Fernet trước khi ghi vào SQL Server. Cài thư viện từ `requirements.txt`, sau đó tạo khóa một lần và đặt trong biến môi trường của tiến trình chạy Flask (không commit khóa, không gửi khóa qua chat):
```powershell
& .\.venv\Scripts\python.exe -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
$env:FACE_ENCRYPTION_KEY = "<khóa vừa tạo>"
$env:FACE_RETENTION_DAYS = "365"
$env:FACE_MATCH_THRESHOLD = "0.82"
$env:FACE_ANTISPOOF_THRESHOLD = "0.70"
$env:FACE_LIVENESS_THRESHOLD = "0.70"
& .\.venv\Scripts\python.exe app.py
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
4. Trong mục **Hợp đồng**, kéo thả hoặc chọn mẫu `.doc`, `.docx` hoặc `.pdf`. DOC cũ được chuyển bằng Microsoft Word cài trên máy chạy ứng dụng; DOCX có văn bản được đọc trực tiếp; DOCX chứa ảnh scan và PDF scan cần Tesseract OCR (tối đa 5 ảnh trong DOCX hoặc 5 trang PDF; cài thêm gói ngôn ngữ `vie`, và đặt biến môi trường `TESSERACT_CMD` nếu `tesseract` không nằm trong PATH). Hệ thống trích xuất văn bản để xem lại và làm tài liệu tham khảo cho AI. Khi soạn, chọn mẫu, chọn nhân viên rồi tải hợp đồng dạng Word `.docx` hoặc PDF. Tệp đầu ra dùng định dạng chuẩn của hệ thống, không giữ nguyên bố cục đồ họa của tệp mẫu.

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
& .\.venv\Scripts\python.exe -m scripts.seed_data
```
Lệnh này thêm 10 nhân viên mẫu (đủ 5 phòng ban) và 9 hợp đồng mẫu đủ các loại (Không thời hạn, Có thời hạn, Thử việc, Thời vụ, Bán thời gian, Học việc, Cộng tác viên). Chạy lại nhiều lần không bị trùng. Họ tên, CCCD, SĐT trong dữ liệu mẫu đều là dữ liệu giả.

### Quy trình bảng lương

Bảng lương có trạng thái **Nháp → Đã duyệt → Đã khóa**. Quản trị viên có thể tính lại và chỉnh mức chung khi kỳ còn nháp; thao tác phê duyệt và khóa yêu cầu lý do và được ghi vào lịch sử. Chỉ kỳ đã khóa mới cho phép xuất bảng lương và xem phiếu lương cá nhân. Tăng ca chỉ tính vào payroll sau khi quản trị viên duyệt trước và xác nhận số giờ thực tế sau ca; cần tính lại kỳ lương còn nháp để áp dụng. Đi muộn được ghi nhận riêng; cấu hình mặc định không tự khấu trừ tiền lương.

Trang lương hỗ trợ tạo/duyệt chính sách thuế và bảo hiểm có phiên bản, hồ sơ cư trú/người phụ thuộc/đối tượng đóng theo ngày hiệu lực, khoản phụ cấp/thưởng/phạt/khấu trừ và snapshot đầu vào/kết quả cho từng dòng lương. Chính sách không có sẵn tỷ lệ pháp lý; phải được HR/kế toán điền căn cứ, cấu hình và duyệt. Khi thiếu chính sách hoặc hồ sơ cá nhân, hệ thống đánh dấu chưa có snapshot và không coi các số 0 là kết quả đã đối soát. Nguồn công/phép/tăng ca được lưu cùng snapshot; chỉnh nguồn làm kỳ nháp cần tính lại.

Lương cơ bản dùng lịch sử công tác có ngày hiệu lực và phân bổ theo ngày lịch. Tiền tăng ca tính theo giờ đã được yêu cầu, duyệt và xác nhận; tổng giờ sự kiện chấm công giữ làm dữ liệu đối chiếu, không tự coi toàn bộ giờ làm là giờ tăng ca. Bản hiện tại dùng một chính sách toàn doanh nghiệp cho mỗi ngày hiệu lực, một hệ số OT chung và chưa tách nhóm chính sách theo vùng/hợp đồng hoặc OT ngày thường/ngày nghỉ/ngày lễ/ban đêm. Vì vậy cần hoàn tất các nhóm và phân loại đó trước khi dùng để trả lương chính thức. Xem [docs/PAYROLL_POLICY_GUIDE.md](docs/PAYROLL_POLICY_GUIDE.md) để biết cấu trúc và giới hạn.

Hệ thống hiện có sáu vai trò được kiểm tra phía máy chủ: `QuanTri`, `QuanTriHeThong`, `HR`, `KeToan`, `QuanLy` và `NhanVien`. Quyền được khai báo tập trung trong `permissions.py`: HR quản lý hồ sơ/tổ chức/hợp đồng/nghỉ phép theo quyền được cấp; kế toán thao tác bảng lương; quản lý xem và duyệt phạm vi đội được gán; nhân viên dùng các chức năng tự phục vụ. `QuanTri` là vai trò tương thích cũ có quyền toàn hệ thống, còn `QuanTriHeThong` tập trung vào quản trị tài khoản/cấu hình. Việc giới hạn theo từng trường dữ liệu, từng phòng ban và audit toàn bộ đường đọc/xuất dữ liệu nhạy cảm vẫn cần kiểm thử bổ sung; không mặc định rằng ẩn nút giao diện đồng nghĩa với đã bảo vệ route/API.

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

## Việc xác minh còn lại trên SQL Server

- [ ] Chạy cài đặt schema trên database thử nghiệm mới và mở ứng dụng.
- [ ] Xác minh nâng cấp database hiện có không làm mất MaNV, chấm công, đơn nghỉ, hợp đồng, lương hoặc tài khoản.
- [ ] Kiểm tra chuyển nhân viên sang Đã nghỉ việc: đăng nhập mới bị chặn, phiên cũ bị thu hồi và mẫu khuôn mặt bị xóa.
- [ ] Kiểm tra quyền xem/sửa/xuất theo từng vai trò cho tám phân hệ.

## KPI & thưởng hiệu suất

Sau khi cập nhật mã nguồn, dừng web workers và chạy `& .\.venv\Scripts\python.exe migrate_db.py` bằng migration account để áp dụng các bảng và cập nhật schema `KPI_Chitieu`, `KPI_Danhgia`, `KPI_Chitiet`, `KPI_Thuong` (schema hiện tại `2026.11.26.4`), rồi khởi động lại ứng dụng.

Quản trị viên và Nhân sự/Kế toán có thể thiết lập chỉ tiêu theo phòng ban hoặc cá nhân, lập kỳ đánh giá tháng (`YYYY-MM`), quý (`YYYY-Q1`…`YYYY-Q4`) hoặc năm (`YYYY`), nhập kết quả, chấm và xác nhận. Trọng số các chỉ tiêu áp dụng cho mỗi nhân viên phải bằng 100%. Điểm hoàn thành từng chỉ tiêu bằng kết quả thực tế chia mục tiêu; tỷ lệ mỗi chỉ tiêu và tổng điểm KPI được giới hạn tối đa 120. Mức thưởng mặc định: dưới 50 điểm 0%, 50–dưới 70 là 2%, 70–dưới 85 là 5%, 85–dưới 100 là 8%, từ 100 điểm là 10%; HR có thể điều chỉnh tỷ lệ trong mục KPI. Thưởng được tính trên lương cơ bản lưu tại lúc lập đánh giá và thêm thành khoản thu nhập chịu thuế vào tháng kết thúc kỳ (quý/năm vào tháng cuối kỳ); kỳ lương đã duyệt/khóa sẽ không nhận khoản mới. Nhân viên chỉ xem và cập nhật kết quả KPI của chính mình; HR/Admin quản lý toàn bộ. Mỗi chỉ tiêu chọn chiều càng cao hoặc càng thấp càng tốt; HR có thể trả phiếu kèm phản hồi để nhân viên cập nhật lại trước khi xác nhận. Thưởng KPI dùng mã đánh giá duy nhất trong `PayrollItem.KPIReviewId` để tránh chuyển trùng và hiển thị trạng thái đã/chưa chuyển sang bảng lương. Báo cáo có xếp hạng nhân viên, so sánh phòng ban, điểm trung bình và tổng thưởng theo tháng.

## Chấm công cá nhân và tổng hợp tháng

Bản tổng hợp chấm công cá nhân hiển thị giờ Việt Nam UTC+7, giờ vào/ra, giờ làm từ các cặp sự kiện, số phút muộn và số phút về sớm. Admin/Nhân sự-Kế toán xem tổng hợp toàn nhân viên; nhân viên chỉ xem kỳ của mình. Giờ muộn và về sớm được lưu ở `ChamCong.SoPhutMuon` và `ChamCong.SoPhutVeSom`; chỉ ghi nhận để đối soát, không tự phát sinh khấu trừ riêng. Việc tính lương vẫn theo chính sách lương đã cấu hình. Tăng ca chỉ vào bảng lương sau khi đã duyệt, kết thúc và được Nhân sự/Admin xác nhận; chấm công hoặc xác nhận tăng ca sẽ đánh dấu kỳ lương nháp cần tính lại.

Sau cập nhật này, nâng schema lên `2026.11.26.4`: dừng web workers, chạy `& .\.venv\Scripts\python.exe migrate_db.py` bằng migration account, rồi khởi động lại ứng dụng.

### Giờ chấm công và nghỉ trưa

Mặc định giờ làm chuẩn là 08:00–12:00 và 13:00–17:00. Khoảng 12:00–13:00 được loại khỏi tổng phút làm việc và thời gian tăng ca quan sát được. Có thể cấu hình bằng `ATTENDANCE_START_TIME`, `ATTENDANCE_LUNCH_START`, `ATTENDANCE_LUNCH_END`, `ATTENDANCE_END_TIME` (định dạng `HH:MM`). Đi muộn/về sớm được ghi nhận để đối soát; ứng dụng không tự khấu trừ tiền chỉ vì đi muộn. Mỗi ngày, số phút làm thực tế được lưu ở `ChamCong.SoPhutLamViec`.

Sau cập nhật này, dừng web workers và chạy `& .\.venv\Scripts\python.exe migrate_db.py` bằng migration account để nâng schema lên `2026.11.26.4`, sau đó khởi động lại ứng dụng.

## Báo cáo nhân sự

Admin và Nhân sự/Kế toán xem dashboard và báo cáo toàn hệ thống: quỹ lương theo phòng ban/cơ cấu, xu hướng 6 kỳ lương đã khóa, biến động nhân sự và tỷ lệ nghỉ việc, chuyên cần, KPI theo phòng ban/nhân viên. Có thể lọc tháng/năm và xuất theo định dạng được cấu hình trong ứng dụng. Báo cáo lương chỉ lấy kỳ đã khóa; tổng chi phí gồm tổng lương và phần bảo hiểm doanh nghiệp đóng. Tỷ lệ nghỉ việc = nhân viên có ngày nghỉ việc trong kỳ / bình quân đầu kỳ và cuối kỳ.

Báo cáo chuyên cần tính ngày dự kiến theo lịch cá nhân (mặc định thứ Hai–thứ Bảy), loại ngày lễ và phép đã duyệt khỏi mẫu số. Nhân viên chỉ được mở/xuất báo cáo chấm công, nghỉ phép và lương của chính mình; lương cá nhân chỉ hiện khi kỳ đã khóa. Những ngày nghỉ việc xảy ra trước khi trường `NhanVien.NgayNghiViec` được bổ sung không có ngày hiệu lực lịch sử, nên không thể khôi phục chính xác tỷ lệ nghỉ việc cũ nếu chưa nhập bù ngày nghỉ.

## Hỗ trợ AI cho hợp đồng, quy tắc lương và chấm công

- **Soạn hợp đồng:** chức năng hiện có tạo bản nháp để HR/pháp chế rà soát. AI không tự ký, duyệt hoặc phát hành hợp đồng.
- **Diễn giải quy tắc lương:** tại **Lương → AI diễn giải quy tắc lương**, nhập quy chế dạng văn bản. AI trả JSON theo đúng cấu trúc chính sách hiện tại; hệ thống kiểm tra schema và giới hạn trước khi đưa vào ô sửa. HR phải đọc, sửa, lưu thành bản nháp và người có quyền duyệt xác nhận. JSON do AI tạo không tự tính hay cập nhật lương. Không nhập tên, CCCD, số điện thoại hoặc dữ liệu riêng của nhân viên vào phần mô tả.
- **Bất thường chấm công:** tại **Chấm công → Mở cảnh báo bất thường**, hệ thống đánh dấu đi muộn/về sớm lặp lại (từ 3 lần), thiếu giờ vào/ra ở ngày đã qua, giờ vào/ra lệch ca đã phân công, thời lượng trên 16 giờ/ngày, bản ghi trùng và tăng ca đã xác nhận trên 40 giờ/tháng. Các ngưỡng là tín hiệu để HR kiểm tra, không phải kết luận sai phạm. Nút giải thích AI chỉ gửi tháng và số lượng cảnh báo theo nhóm, không gửi tên/mã nhân viên hay dữ liệu lương.

Các tác vụ AI yêu cầu `payroll.edit` hoặc quyền quản lý chấm công, dùng provider/key đã cấu hình tại `config.py`/biến môi trường. Mỗi tài khoản giới hạn 10 yêu cầu/giờ. `AI_RequestLog` lưu người gọi, chức năng, model, mã băm prompt, trạng thái và thời điểm; không lưu nội dung prompt/đầu ra và bản ghi quá 180 ngày được dọn khi có yêu cầu AI mới. Sau thay đổi này, dừng web workers và chạy `& .\.venv\Scripts\python.exe migrate_db.py` bằng migration account để nâng schema lên `2026.11.26.4`, rồi khởi động lại ứng dụng.




