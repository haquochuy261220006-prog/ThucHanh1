# Cấu hình kết nối SQL Server
SERVER = r"localhost\SQLEXPRESS03"      # đổi theo máy của bạn
DATABASE = "NHANSU_PY"                  # database mới cho bản Python (tránh đụng schema cũ)
DRIVER = "ODBC Driver 17 for SQL Server"  # hoặc "ODBC Driver 18 for SQL Server"
WINDOWS_AUTH = True                     # False -> dùng USER/PASSWORD bên dưới
USER = "sa"
PASSWORD = ""

CONG_CHUAN = 25          # số ngày công chuẩn/tháng -> lương ngày = lương cơ bản / CONG_CHUAN
GIO_VAO_CHUAN = "08:30"  # vào sau giờ này tính là đi muộn

# ---- Quy tắc tính lương (xem payroll.py) ----
NGAY_NGHI_TUAN = (6,)     # ngày nghỉ cố định trong tuần: 0=Thứ 2 ... 5=Thứ 7, 6=Chủ nhật
CHUYEN_CAN_SO_NGAY = 25   # đi làm từ số ngày này trở lên trong tháng thì được thưởng chuyên cần
CHUYEN_CAN_TY_LE = 0.25   # thưởng chuyên cần = 25% lương cơ bản
MUON_TRU_NGAY = 0.5       # mỗi lần vào muộn trừ nửa ngày lương
NGHI_KP_TRU_NGAY = 1      # mỗi ngày nghỉ không phép trừ 1 ngày lương
GIO_RA_CHUAN = "17:30"    # ra về sau giờ này tính là tăng ca
GIO_LAM_NGAY = 8          # số giờ của 1 ngày công (để đổi ngày lương -> lương giờ)
HE_SO_TANG_CA = 1.5       # tiền tăng ca = số giờ x lương giờ x hệ số này


def conn_str(database=None):
    db = database or DATABASE
    s = f"DRIVER={{{DRIVER}}};SERVER={SERVER};DATABASE={db};TrustServerCertificate=yes;"
    s += "Trusted_Connection=yes;" if WINDOWS_AUTH else f"UID={USER};PWD={PASSWORD};"
    return s


# ---- Soạn hợp đồng bằng AI ----
import os
# Chọn AI: "anthropic" (Claude, có tra cứu web) hoặc "openai" (OpenAI hoặc dịch vụ tương thích: Gemini, DeepSeek, Ollama...)
AI_PROVIDER = os.environ.get("AI_PROVIDER", "anthropic")

# --- Claude (khuyên dùng): lấy khóa tại console.anthropic.com
#     PowerShell:  setx ANTHROPIC_API_KEY "sk-ant-..."   (rồi mở lại terminal)
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
ANTHROPIC_MODEL = "claude-sonnet-5-5"

# --- OpenAI hoặc dịch vụ tương thích OpenAI
AI_PROVIDER = "openai"

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
OPENAI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"
OPENAI_MODEL = "gemini-3.6-flash"

# Cho AI tra cứu web để kiểm tra quy định mới nhất (lương tối thiểu vùng, BHXH...). Chỉ áp dụng với Claude.
AI_WEB_SEARCH = True

# Thông tin Bên A (công ty) in trên hợp đồng - sửa theo công ty của bạn
COMPANY = {
    "ten": "CÔNG TY TNHH ........",
    "dia_chi": "........",
    "mst": "........",
    "dien_thoai": "........",
    "dai_dien": "........",
    "chuc_vu": "Giám đốc",
    "dia_diem_ky": "",   # ví dụ "Hà Nội"
}
