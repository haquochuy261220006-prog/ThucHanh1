# Chính sách tính lương có phiên bản

## Cách vận hành

1. Tạo bản nháp chính sách trên trang **Quản lý tiền lương**. Nhập căn cứ, ngày hiệu lực và JSON theo biểu mẫu.
2. Nhập hồ sơ thuế/bảo hiểm cho từng nhân viên, có ngày hiệu lực. Tỷ lệ cư trú, người phụ thuộc, đối tượng tham gia và căn cứ đóng không được suy đoán.
3. Thêm phụ cấp, thưởng, khoản giảm thu nhập hoặc khấu trừ sau thuế. Phân loại chịu thuế/căn cứ bảo hiểm phải có căn cứ đã được HR/kế toán rà soát.
4. Một người có quyền `payroll.approve` duyệt chính sách bằng lý do; bản nháp không được dùng để tính.
5. Tính lại kỳ nháp. Một chính sách được chọn theo ngày đầu kỳ; lương cơ bản được lấy từ `LichSuCongTac` theo hiệu lực và phân bổ theo ngày lịch trong tháng.
6. Mỗi dòng lương có snapshot JSON của chính sách, hồ sơ nhân viên, dữ liệu công/phép/tăng ca và chi tiết phép tính. Sửa nguồn thì phải tính lại trước khi duyệt kỳ.
7. Duyệt rồi khóa kỳ như luồng hiện có. Phiếu lương hiển thị thu nhập, thuế, phần đóng của hai bên và thực lĩnh.

## Cấu trúc `QuyTacJson`

Tỷ lệ là số thập phân (5% nhập `0.05`), số tiền là VND. Cần thay tất cả số 0 mang tính ví dụ bằng cấu hình đã được kiểm chứng. JSON tối thiểu có dạng:

```json
{
  "base_salary_taxable": true,
  "base_salary_insurable": true,
  "salary_proration_basis": "calendar_days",
  "standard_workdays_per_month": 0,
  "hours_per_workday": 0,
  "attendance_bonus_min_days": 0,
  "attendance_bonus_rate": 0,
  "overtime_factor": 0,
  "components": {
    "attendance_bonus": {"taxable": false, "insurable": false},
    "overtime": {"taxable": false, "insurable": false},
    "extra_bonus": {"taxable": false, "insurable": false},
    "payroll_deductions": {"taxable": false, "insurable": false}
  },
  "tax": {
    "personal_deduction": 0,
    "dependent_deduction": 0,
    "employee_contributions_reduce_taxable_base": false,
    "allow_other_tax_deductions": false,
    "brackets": [{"up_to": null, "rate": 0}],
    "nonresident_flat_rate": 0
  },
  "insurance": {
    "limits": {
      "bhxh": {"minimum_base": null, "maximum_base": null},
      "bhyt": {"minimum_base": null, "maximum_base": null},
      "bhtn": {"minimum_base": null, "maximum_base": null},
      "tnld_bnn": {"minimum_base": null, "maximum_base": null}
    },
    "employee_rates": {"bhxh": 0, "bhyt": 0, "bhtn": 0},
    "employer_rates": {"bhxh": 0, "bhyt": 0, "bhtn": 0, "tnld_bnn": 0}
  }
}
```

Mỗi bậc thuế có `up_to` (VND/tháng) và `rate`; bậc cuối phải có `up_to: null`. Các loại thuế/đóng góp được lưu trong JSON đầu ra. Hệ thống tính lũy tiến từng phần theo các bậc đã khai báo.

## Giới hạn hiện tại

- Bản triển khai hiện có một chính sách toàn doanh nghiệp cho mỗi thời điểm hiệu lực; hồ sơ theo nhân viên cho phép thiết lập tình trạng cư trú, người phụ thuộc, tham gia bảo hiểm và căn cứ bảo hiểm riêng. Muốn tách chính sách theo nhóm hợp đồng/địa bàn cần thêm khóa nhóm vào chính sách và hồ sơ trước khi dùng nhiều nhóm.
- Lương công tác được phân bổ theo ngày lịch, không theo lịch làm việc. Tiền tăng ca tính theo giờ đã được yêu cầu, duyệt và xác nhận; tổng giờ từ sự kiện chấm công lưu riêng để đối soát, không tự xem toàn bộ giờ làm là giờ tăng ca.
- `overtime_factor` hiện là một hệ số cho toàn bộ giờ tăng ca. Dữ liệu nguồn chưa phân loại giờ ngày thường/ngày nghỉ/ngày lễ/ban đêm, nên không thể tự áp dụng đầy đủ nhiều mức tăng ca hoặc phụ cấp ban đêm. Không khóa kỳ nếu yêu cầu phân loại này bắt buộc.
- Không có chính sách hợp lệ hoặc hồ sơ nhân viên còn thiếu thì các cột thuế/bảo hiểm không được coi là kết quả tuân thủ. Dòng chưa có snapshot hiển thị “Chưa” và phiếu lương nêu rõ đang dùng công thức cũ.

## Nguồn quy định cần đối chiếu khi tạo phiên bản

- Luật Thuế thu nhập cá nhân số 109/2025/QH15, hiệu lực 01/07/2026: https://vanban.chinhphu.vn/?classid=1&docid=216495&pageid=27160
- Luật sửa đổi một số luật thuế số 09/2026/QH16: https://vanban.chinhphu.vn/?classid=1&docid=218095&pageid=27160
- Luật Bảo hiểm xã hội số 41/2024/QH15, hiệu lực 01/07/2025: https://vanban.chinhphu.vn/?classid=1&docid=211199&pageid=27160
- Luật Việc làm số 74/2025/QH15, hiệu lực 01/01/2026: https://vanban.chinhphu.vn/?classid=1&docid=214560&pageid=27160
- Nghị định lương tối thiểu vùng số 293/2025/NĐ-CP, hiệu lực 01/01/2026: https://vanban.chinhphu.vn/?classid=1&docid=215832&pageid=27160
- Bộ luật Lao động hợp nhất 18/VBHN-VPQH năm 2026: https://vanban.chinhphu.vn/?classid=0&docid=217002&pageid=27160

Đây là danh sách điểm bắt đầu tra cứu, không thay cho rà soát văn bản hướng dẫn, đối tượng áp dụng, vùng, loại hợp đồng, thỏa ước và quyết định lương của doanh nghiệp. Không sao chép tỷ lệ từ ví dụ hoặc hồ sơ của nhân viên khác để tạo chính sách.

Nghị quyết 43/2026/QH16 có chính sách giảm thuế TNCN cho thu nhập từ hoạt động kinh doanh trong phạm vi, điều kiện nêu tại nghị quyết; không tự áp dụng khoản giảm đó cho thu nhập tiền lương. Xem https://vanban.chinhphu.vn/?docid=219330&orggroupid=1&pageid=27160.


## Lưu ý về khoản giảm tiền lương

Không dùng khoản giảm để phạt kỷ luật hoặc tự ý cắt lương. Chỉ ghi nhận khoản giảm có căn cứ, được HR/kế toán duyệt và rà soát theo Bộ luật Lao động hiện hành; trách nhiệm vật chất và khấu trừ bồi thường cần quy trình, chứng từ và giới hạn pháp luật riêng. Ứng dụng chưa tự kiểm tra các điều kiện đó.
