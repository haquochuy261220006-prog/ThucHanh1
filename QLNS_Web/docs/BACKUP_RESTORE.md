# Quy trình sao lưu và khôi phục QLNS Web

Tài liệu này áp dụng cho database SQL Server `NHANSU_PY` của dự án. Hãy chọn đúng một trong hai quy trình theo nơi đặt database: SQL Server tự quản lý (máy Windows/VM) hoặc Azure SQL Database. Script `scripts/backup_sqlserver.ps1` chỉ dùng cho SQL Server tự quản lý; Azure SQL có backup tích hợp và phải khôi phục bằng Azure.

## Mục tiêu vận hành mặc định

Cho đến khi doanh nghiệp phê duyệt RPO/RTO khác, dùng mục tiêu ban đầu sau:

- Sao lưu SQL Server tự quản lý mỗi ngày; giữ ít nhất 30 ngày.
- RPO mục tiêu: tối đa 24 giờ dữ liệu có thể mất khi sự cố.
- RTO mục tiêu: khôi phục dịch vụ trong 4 giờ. Đây là mục tiêu cần đo trong diễn tập, không phải cam kết sẵn có.
- Mỗi quý diễn tập khôi phục vào database/môi trường tách biệt. Không diễn tập ghi đè database thật.
- Lưu ít nhất một bản sao mã hóa ngoài máy chủ/database nguồn. Giới hạn quyền truy cập và thử quyền đọc bản sao.

Nếu nghiệp vụ cần mất dữ liệu ít hơn 24 giờ, phải cấu hình chiến lược log backup/PITR phù hợp, dung lượng lưu trữ, cảnh báo và người trực; chỉ chạy full backup mỗi ngày không đáp ứng mục tiêu đó.

## A. SQL Server tự quản lý (SQL Server Express/Standard)

### Chuẩn bị một lần

1. Cài Microsoft `sqlcmd` trên máy chạy tác vụ và bảo đảm `sqlcmd` có trong `PATH`.
2. Tạo thư mục backup trên ổ đĩa được bảo vệ. Tài khoản **dịch vụ SQL Server** cần quyền ghi vào thư mục này; quyền của người chạy PowerShell không thay thế quyền dịch vụ SQL Server.
3. Tách tài khoản backup khỏi tài khoản ứng dụng web. Cấp tối thiểu quyền backup database cần thiết; không cấp `sysadmin` cho ứng dụng Flask. Nếu backup ra mạng, dùng UNC path và cấu hình quyền cho tài khoản dịch vụ SQL Server trên cả share lẫn NTFS.
4. Đặt thư mục đích trên ổ đĩa/thiết bị khác nguồn dữ liệu nếu có thể. Sau đó sao chép bản backup thành công sang nơi lưu tách biệt, có kiểm soát truy cập và mã hóa.

### Chạy backup thủ công

Mở PowerShell bằng tài khoản vận hành được cấp quyền backup. Với Windows Authentication (mặc định dev của dự án):

```powershell
$env:DB_SERVER = 'localhost\SQLEXPRESS03'
$env:DB_NAME = 'NHANSU_PY'
$env:DB_WINDOWS_AUTH = 'true'
& .\scripts\backup_sqlserver.ps1 -BackupDirectory 'D:\QLNS-Backups' -RetainDays 30
```

Với SQL Authentication, dùng tài khoản backup riêng (không dùng tài khoản web nếu không cần) và cung cấp `DB_USER`, `DB_PASSWORD`, `DB_WINDOWS_AUTH=false` qua secret store/credential injection của máy chạy tác vụ. Script chuyển mật khẩu sang `SQLCMDPASSWORD` trong thời gian chạy và xóa biến sau đó; không ghi mật khẩu dạng rõ trong file `.ps1`, lịch sử lệnh hoặc task arguments.

Script tạo file `.bak` có ngày giờ trong tên, dùng `CHECKSUM`, gọi `RESTORE VERIFYONLY`, xác nhận file tồn tại/không rỗng rồi mới xóa file cũ hơn thời hạn giữ. SQL Server service phải nhìn thấy đường dẫn backup. `VERIFYONLY` giúp phát hiện một số lỗi media, nhưng **không thay thế diễn tập restore thật**. Task Scheduler nên chạy hằng ngày với tài khoản riêng; bật lịch sử tác vụ, lưu output/exit code và cảnh báo khi tác vụ lỗi. Bảo vệ thư mục backup khỏi người dùng ứng dụng và ransomware.

### Diễn tập restore an toàn

Chọn một file backup đã được sao chép tới máy/đích diễn tập. Thay đường dẫn file, instance SQL và tên database nếu cần. Đích phải là database mới `NHANSU_PY_RESTORE_DRILL`, không phải database đang phục vụ ứng dụng.

1. Xem logical file name trong backup:

```powershell
sqlcmd -S 'localhost\SQLEXPRESS03' -d master -E -b -Q "RESTORE FILELISTONLY FROM DISK = N'D:\QLNS-Backups\NHANSU_PY-YYYYMMDD-HHMMSS.bak';"
```

2. Dùng tất cả logical data/log file name kết quả ở bước trên để khôi phục vào **đường dẫn vật lý mới**. Ví dụ dưới đây giả sử backup chứa một data file và một log file; sửa logical name và đường dẫn theo kết quả thật. Nếu backup chứa nhiều data file, thêm một cặp `MOVE` cho mỗi file:

```powershell
sqlcmd -S 'localhost\SQLEXPRESS03' -d master -E -b -Q "RESTORE DATABASE [NHANSU_PY_RESTORE_DRILL] FROM DISK = N'D:\QLNS-Backups\NHANSU_PY-YYYYMMDD-HHMMSS.bak' WITH MOVE N'NHANSU_PY' TO N'D:\SQLData\NHANSU_PY_RESTORE_DRILL.mdf', MOVE N'NHANSU_PY_log' TO N'D:\SQLData\NHANSU_PY_RESTORE_DRILL_log.ldf', RECOVERY, CHECKSUM, STATS = 10;"
```

3. Kiểm tra toàn vẹn và đối chiếu dữ liệu nghiệp vụ cơ bản:

```powershell
sqlcmd -S 'localhost\SQLEXPRESS03' -d master -E -b -Q "DBCC CHECKDB ([NHANSU_PY_RESTORE_DRILL]) WITH NO_INFOMSGS, ALL_ERRORMSGS;"
sqlcmd -S 'localhost\SQLEXPRESS03' -d NHANSU_PY_RESTORE_DRILL -E -b -Q "SELECT DB_NAME() AS DatabaseName; SELECT COUNT_BIG(*) AS EmployeeCount FROM dbo.NhanVien;"
```

Ghi lại ngày/giờ, mã backup, người thực hiện, thời gian khôi phục, kết quả `CHECKDB`, số lượng nhân viên/bảng quan trọng và lỗi. Kiểm tra thêm bảng chấm công, nghỉ phép, lương và hợp đồng trong SSMS; thử đăng nhập ứng dụng staging trỏ vào database diễn tập nếu schema tương thích. Không dùng dữ liệu diễn tập làm database sản xuất. Sau khi lưu biên bản, xóa database diễn tập theo quy trình nội bộ và xác minh đúng tên đích trước khi xóa.

### Khôi phục sau sự cố

1. Dừng ghi dữ liệu vào ứng dụng hoặc chuyển sang chế độ bảo trì; giữ nguyên database lỗi để điều tra.
2. Chọn bản backup gần nhất đã xác minh. Nếu đã thiết lập transaction log backup, khôi phục full/differential/log theo chuỗi tới thời điểm mục tiêu; nếu chưa có, chỉ có thể quay về thời điểm của full backup.
3. Khôi phục trước vào database/instance mới. Chạy `DBCC CHECKDB`, kiểm tra dữ liệu nghiệp vụ và cấu hình ứng dụng trỏ vào bản khôi phục.
4. Đổi kết nối sau khi người chịu trách nhiệm nghiệp vụ xác nhận; kiểm tra đăng nhập, ghi thử có kiểm soát, báo cáo và các tệp hồ sơ.
5. Lưu biên bản sự cố, thời điểm dữ liệu thực tế được phục hồi (RPO) và tổng thời gian (RTO); giữ bản lỗi và bản backup theo chính sách điều tra/lưu trữ.

## B. Azure SQL Database

Azure SQL Database tự quản lý full/differential/log backup; không chạy script SQL Server ở trên và không dùng `BACKUP DATABASE`/`RESTORE DATABASE` T-SQL cho PITR Azure SQL. Trong Azure Portal, vào SQL database → **Backups / Data management** để xác nhận thời hạn point-in-time restore (PITR), backup storage redundancy và chính sách long-term retention (LTR) phù hợp yêu cầu doanh nghiệp. PITR thường tạo **database mới**, không ghi đè nguồn. LTR chỉ bật nếu cần giữ bản hàng tuần/tháng/năm dài hơn thời hạn PITR.

Diễn tập mỗi quý bằng **Restore** từ một thời điểm đã chọn tới tên database staging mới; đợi thao tác hoàn tất, xác minh database, chạy kiểm tra nghiệp vụ và đo thời gian. Ghi lại điểm phục hồi thực tế và RTO. Không đổi App Service production sang database diễn tập. Dùng quyền Azure RBAC giới hạn cho người thao tác khôi phục; cảnh báo khi thay đổi chính sách retention hoặc khi tài nguyên database bị xóa.

Tham khảo tài liệu chính thức: [Azure SQL automated backups](https://learn.microsoft.com/en-us/azure/azure-sql/database/automated-backups-overview?view=azuresql), [khôi phục database từ backup](https://learn.microsoft.com/en-us/azure/azure-sql/database/recovery-using-backups?tabs=azure-portal&view=azuresql), [cấu hình PITR và redundancy](https://learn.microsoft.com/en-us/azure/azure-sql/database/automated-backups-change-settings?view=azuresql), [cấu hình LTR](https://learn.microsoft.com/en-us/azure/azure-sql/database/long-term-backup-retention-configure?view=azuresql).

## C. Những bí mật và dữ liệu ngoài database

Backup database không đủ để phục hồi đầy đủ dịch vụ. Lưu trong kho bí mật riêng, có kiểm soát truy cập và quy trình khôi phục:

- `FLASK_SECRET_KEY`, `HR_DOCUMENT_ENCRYPTION_KEY`, `FACE_ENCRYPTION_KEY` và các khóa Fernet khác. Giữ nguyên khóa tương ứng với dữ liệu đã mã hóa; database không thể tự giải mã khi khóa bị mất.
- Cấu hình production/Key Vault, cấu hình SMTP/AI/Twilio và hướng dẫn cấp lại credential; không lưu mật khẩu thật trong backup script hoặc repository.
- Mã nguồn/phiên bản image/container đã triển khai và hướng dẫn cấu hình App Service. Tệp hợp đồng/hồ sơ đang nằm trong database; nếu sau này chuyển sang Blob Storage, phải thêm container vào chính sách backup/retention.

## D. Checklist diễn tập và vận hành

- [ ] Lịch backup chạy thành công và có cảnh báo khi lỗi.
- [ ] Backup được xác minh và có bản sao ngoài máy/database nguồn.
- [ ] Khóa mã hóa và bí mật production có bản sao an toàn, khôi phục được.
- [ ] Restore vào đích tách biệt; `DBCC CHECKDB` không báo lỗi.
- [ ] Đã mở ứng dụng staging và đối chiếu hồ sơ, công, nghỉ, lương, hợp đồng.
- [ ] Ghi nhận RPO/RTO thực tế, người thực hiện, kết quả và việc cần khắc phục.
- [ ] Lần diễn tập kế tiếp được lên lịch (khuyến nghị trong vòng 3 tháng).

**Trạng thái hiện tại:** repository có script và quy trình; chưa có kết nối SQL Server/Azure production để tạo backup hay thực hiện restore. Chỉ đánh dấu diễn tập thành công sau khi hoàn tất các bước trên trên staging và lưu biên bản.
