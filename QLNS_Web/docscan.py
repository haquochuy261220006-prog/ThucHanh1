"""Local OCR and basic field extraction for employee documents."""

import io
import os
import re
import unicodedata

ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "tif", "tiff", "bmp", "pdf"}
MAX_FILE_SIZE = 10 * 1024 * 1024


def _plain(text):
    text = unicodedata.normalize("NFD", text or "")
    return (
        "".join(c for c in text if unicodedata.category(c) != "Mn")
        .lower()
        .replace("đ", "d")
    )


def _ocr_pages(filename, data):
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext not in ALLOWED_EXTENSIONS:
        raise ValueError("Chỉ nhận ảnh PNG/JPG/TIFF/BMP hoặc PDF.")
    if not data or len(data) > MAX_FILE_SIZE:
        raise ValueError("Tệp trống hoặc lớn hơn giới hạn 10 MB.")
    try:
        import pytesseract
        from PIL import Image

        if os.environ.get("TESSERACT_CMD"):
            pytesseract.pytesseract.tesseract_cmd = os.environ["TESSERACT_CMD"]
        if ext == "pdf":
            import fitz

            pdf = fitz.open(stream=data, filetype="pdf")
            if pdf.page_count > 5:
                raise ValueError("PDF tối đa 5 trang cho mỗi lần quét.")
            images = [
                Image.open(
                    io.BytesIO(
                        page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False).tobytes(
                            "png"
                        )
                    )
                ).convert("RGB")
                for page in pdf
            ]
        else:
            image = Image.open(io.BytesIO(data))
            image.thumbnail((3000, 3000))
            images = [image.convert("RGB")]
        return "\n".join(
            pytesseract.image_to_string(image, lang="vie+eng", config="--psm 6")
            for image in images
        )
    except ImportError as e:
        raise RuntimeError(
            "Thiếu thư viện OCR. Cài các gói trong requirements.txt rồi thử lại."
        ) from e
    except Exception as e:
        if isinstance(e, ValueError):
            raise
        if "tesseract" in str(e).lower() or "traineddata" in str(e).lower():
            raise RuntimeError(
                "Chưa cài Tesseract OCR hoặc thiếu dữ liệu tiếng Việt (vie)."
            ) from e
        raise RuntimeError(
            "Không đọc được tệp. Hãy dùng ảnh/PDF rõ nét, không đặt mật khẩu."
        ) from e


def _after_label(lines, labels):
    plain_lines = [_plain(line).strip() for line in lines]
    for i, line in enumerate(plain_lines):
        for label in labels:
            match = re.search(
                r"\b" + re.escape(label) + r"\b(?:\s*/\s*[^:]*)?\s*[:\-]?\s*(.*)$", line
            )
            if match:
                value = lines[i][len(lines[i]) - len(lines[i].lstrip()) :].strip()
                # Preserve the original accented text after the field label when it shares a line.
                colon = re.search(r"[:\-]", value)
                if colon and value[colon.end() :].strip():
                    return value[colon.end() :].strip()
                if i + 1 < len(lines):
                    return lines[i + 1].strip()
    return ""


def _extract(text):
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    flat = "\n".join(lines)
    plain = _plain(flat)
    cccd = re.search(r"(?<!\d)\d{12}(?!\d)", re.sub(r"[\s.-]", "", flat))
    email = re.search(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", flat, re.I)
    phone = re.search(r"(?<!\d)(?:\+?84|0)(?:[\s.-]?\d){8,10}(?!\d)", flat)
    dob = ""
    dob_line = _after_label(lines, ["ngay sinh", "date of birth", "dob"])
    date_match = re.search(r"\b(\d{1,2})[./-](\d{1,2})[./-](\d{4})\b", dob_line or flat)
    if date_match:
        day, month, year = map(int, date_match.groups())
        if 1 <= day <= 31 and 1 <= month <= 12:
            dob = f"{year:04d}-{month:02d}-{day:02d}"
    gender = _after_label(lines, ["gioi tinh", "sex", "gender"])
    gender_plain = _plain(gender)
    if "nu" in gender_plain or "female" in gender_plain:
        gender = "Nữ"
    elif "nam" in gender_plain or "male" in gender_plain:
        gender = "Nam"
    else:
        gender = ""
    name = _after_label(lines, ["ho va ten", "full name", "ho ten"])
    if (
        not name
        and lines
        and ("curriculum vitae" in plain or re.search(r"\b(cv|resume)\b", plain))
    ):
        name = next(
            (
                line
                for line in lines[:5]
                if not re.search(r"@|\d{7,}|curriculum|resume|\bcv\b", line, re.I)
            ),
            "",
        )
    address = _after_label(
        lines,
        [
            "noi thuong tru",
            "dia chi thuong tru",
            "cho o hien nay",
            "dia chi",
            "address",
            "place of residence",
        ],
    )
    fields = {
        "HoTen": name[:200],
        "NgaySinh": dob,
        "GioiTinh": gender,
        "DiaChi": address[:500],
        "SDT": re.sub(r"[\s.-]", "", phone.group()) if phone else "",
        "Email": email.group() if email else "",
        "CCCD": cccd.group() if cccd else "",
    }
    return fields


def scan_employee_document(filename, data):
    text = _ocr_pages(filename, data)
    plain = _plain(text)
    cccd_markers = (
        "can cuoc cong dan",
        "so dinh danh ca nhan",
        "personal identification",
        "citizen identity",
        "identity card",
    )
    cv_markers = ("so yeu ly lich", "ho so ung tuyen", "curriculum vitae", "resume")
    if any(marker in plain for marker in cccd_markers):
        document_type = "CCCD"
    elif any(marker in plain for marker in cv_markers) or (
        "@" in text and re.search(r"(?<!\d)0\d{9,10}(?!\d)", re.sub(r"\s", "", text))
    ):
        document_type = "CV / Sơ yếu lý lịch"
    else:
        raise ValueError(
            "Chưa nhận dạng được loại tài liệu. Bản đầu hỗ trợ CCCD và CV/sơ yếu lý lịch."
        )
    fields = _extract(text)
    if not fields["HoTen"] and document_type == "CCCD":
        # CCCD scans often place the name on the line immediately after its bilingual label.
        fields["HoTen"] = _after_label(
            text.splitlines(), ["ho va ten", "full name", "ho ten"]
        )[:200]
    return {"document_type": document_type, "fields": fields, "preview": text[:3000]}
