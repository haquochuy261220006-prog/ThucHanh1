"""OCR cục bộ cho hợp đồng scan (PDF hoặc ảnh) bằng Tesseract.

Cần cài chương trình Tesseract OCR (kèm gói ngôn ngữ ``vie`` và ``eng``). Nếu
``tesseract`` không nằm trong PATH, đặt biến môi trường ``TESSERACT_CMD`` là
đường dẫn tới tệp thực thi.
"""

import io
import os

MAX_OCR_PAGES = 5
_RENDER_DPI = 200
_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".webp"}


def _tesseract():
    import pytesseract

    command = os.environ.get("TESSERACT_CMD", "").strip()
    if command:
        pytesseract.pytesseract.tesseract_cmd = command
    available = set(pytesseract.get_languages(config=""))
    languages = [name for name in ("vie", "eng") if name in available]
    if not languages:
        raise RuntimeError("Tesseract chưa cài gói ngôn ngữ vie hoặc eng.")
    return pytesseract, "+".join(languages)


def _ocr_image(engine, languages, data):
    from PIL import Image, ImageOps

    with Image.open(io.BytesIO(data)) as image:
        prepared = ImageOps.exif_transpose(image).convert("L")
        return engine.image_to_string(prepared, lang=languages)


def _pdf_pages_as_png(data):
    import fitz

    with fitz.open(stream=data, filetype="pdf") as pdf:
        if pdf.page_count > MAX_OCR_PAGES:
            raise ValueError(f"OCR chỉ hỗ trợ tối đa {MAX_OCR_PAGES} trang.")
        for page in pdf:
            yield page.get_pixmap(dpi=_RENDER_DPI).tobytes("png")


def _ocr_pages(filename, data):
    """Nhận dạng văn bản từ ảnh hoặc PDF scan; trả về chuỗi văn bản (có thể rỗng)."""
    extension = os.path.splitext(filename)[1].lower()
    engine, languages = _tesseract()
    if extension == ".pdf":
        pages = _pdf_pages_as_png(data)
    elif extension in _IMAGE_EXTENSIONS:
        pages = (data,)
    else:
        raise ValueError("OCR chỉ hỗ trợ PDF hoặc ảnh.")
    texts = (_ocr_image(engine, languages, page).strip() for page in pages)
    return "\n".join(text for text in texts if text)
