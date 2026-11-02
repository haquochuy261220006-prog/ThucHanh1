import os

# Cấu hình kết nối SQL Server
SERVER = r"localhost\SQLEXPRESS03"  # đổi theo máy của bạn
DATABASE = "NHANSU_PY"  # database mới cho bản Python (tránh đụng schema cũ)
DRIVER = "ODBC Driver 17 for SQL Server"  # hoặc "ODBC Driver 18 for SQL Server"
WINDOWS_AUTH = True  # False -> dùng USER/PASSWORD bên dưới
USER = "sa"
PASSWORD = ""

CONG_CHUAN = 25  # số ngày công chuẩn/tháng -> lương ngày = lương cơ bản / CONG_CHUAN
GIO_VAO_CHUAN = "08:30"  # vào sau giờ này tính là đi muộn

# ---- Quy tắc tính lương (xem payroll.py) ----
NGAY_NGHI_TUAN = (6,)  # ngày nghỉ cố định trong tuần: 0=Thứ 2 ... 5=Thứ 7, 6=Chủ nhật
CHUYEN_CAN_SO_NGAY = (
    25  # đi làm từ số ngày này trở lên trong tháng thì được thưởng chuyên cần
)
CHUYEN_CAN_TY_LE = 0.25  # thưởng chuyên cần = 25% lương cơ bản
MUON_TRU_NGAY = 0  # chỉ ghi nhận vi phạm; không tự động khấu trừ tiền lương
NGHI_KP_TRU_NGAY = 1  # mỗi ngày nghỉ không phép trừ 1 ngày lương
GIO_RA_CHUAN = "17:30"  # ra về sau giờ này tính là tăng ca
GIO_LAM_NGAY = 8  # số giờ của 1 ngày công (để đổi ngày lương -> lương giờ)
HE_SO_TANG_CA = 1.5  # tiền tăng ca = số giờ x lương giờ x hệ số này


def conn_str(database=None):
    db = database or DATABASE
    s = f"DRIVER={{{DRIVER}}};SERVER={SERVER};DATABASE={db};TrustServerCertificate=yes;"
    s += "Trusted_Connection=yes;" if WINDOWS_AUTH else f"UID={USER};PWD={PASSWORD};"
    return s


# ---- Soạn hợp đồng bằng AI ----

# Chọn AI: "anthropic" (Claude, có tra cứu web) hoặc "openai" (OpenAI hoặc dịch vụ tương thích: Gemini, DeepSeek, Ollama...)
# Mọi khóa API CHỈ đọc từ biến môi trường, tuyệt đối không ghi khóa vào mã nguồn.
AI_PROVIDER = os.environ.get("AI_PROVIDER", "anthropic")

# --- Claude (khuyên dùng): lấy khóa tại console.anthropic.com
#     PowerShell:  setx ANTHROPIC_API_KEY "sk-ant-..."   (rồi mở lại terminal)
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
ANTHROPIC_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-5-5")

# --- OpenAI hoặc dịch vụ tương thích OpenAI (ví dụ Gemini)
#     PowerShell:  setx AI_PROVIDER "openai"  và  setx OPENAI_API_KEY "..."
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
OPENAI_BASE_URL = os.environ.get(
    "OPENAI_BASE_URL", "https://generativelanguage.googleapis.com/v1beta/openai/"
)
OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gemini-3.6-flash")

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
    "dia_diem_ky": "",  # ví dụ "Hà Nội"
}

# Nhận diện khuôn mặt chỉ hỗ trợ xác minh sơ bộ; cần hiệu chuẩn trên dữ liệu thực tế.
FACE_MATCH_THRESHOLD = float(os.environ.get("FACE_MATCH_THRESHOLD", "0.82"))
FACE_ANTISPOOF_THRESHOLD = float(os.environ.get("FACE_ANTISPOOF_THRESHOLD", "0.70"))
FACE_LIVENESS_THRESHOLD = float(os.environ.get("FACE_LIVENESS_THRESHOLD", "0.70"))
FACE_ENCRYPTION_KEY = os.environ.get("FACE_ENCRYPTION_KEY", "")
FACE_RETENTION_DAYS = int(os.environ.get("FACE_RETENTION_DAYS", "365"))
FACE_CONSENT_VERSION = "2026-11-v2"
FACE_CONSENT_PURPOSE = "Chấm công nhân viên; đối chiếu vector khuôn mặt và xác minh thử thách camera trực tiếp."
if not 0.0 <= FACE_MATCH_THRESHOLD <= 1.0:
    raise ValueError("FACE_MATCH_THRESHOLD must be between 0 and 1")
if not 0.0 <= FACE_ANTISPOOF_THRESHOLD <= 1.0 or not 0.0 <= FACE_LIVENESS_THRESHOLD <= 1.0:
    raise ValueError("Face liveness thresholds must be between 0 and 1")
if FACE_RETENTION_DAYS < 1:
    raise ValueError("FACE_RETENTION_DAYS must be a positive integer")
