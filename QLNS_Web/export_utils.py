import csv
import io
import os
from decimal import Decimal

from flask import make_response, send_file


def _spreadsheet_safe(value):
    """Chặn công thức (CSV/Excel injection) bằng dấu nháy ở đầu ô văn bản."""
    if isinstance(value, str) and value[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + value
    return value


def _export_csv(filename, cols, rows):
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(cols)
    for row in rows:
        writer.writerow([_spreadsheet_safe(value) for value in row])
    response = make_response("\ufeff" + out.getvalue())
    response.headers["Content-Disposition"] = f'attachment; filename="{filename}.csv"'
    response.headers["Content-Type"] = "text/csv; charset=utf-8"
    return response


def _export_xlsx(filename, cols, rows):
    from openpyxl import Workbook

    workbook = Workbook(write_only=True)
    sheet = workbook.create_sheet("Danh sách")
    sheet.append([str(value) for value in cols])
    for row in rows:
        sheet.append(
            [
                float(value) if isinstance(value, Decimal) else _spreadsheet_safe(value)
                for value in row
            ]
        )
    output = io.BytesIO()
    workbook.save(output)
    output.seek(0)
    return send_file(
        output,
        as_attachment=True,
        download_name=f"{filename}.xlsx",
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


_PDF_FONT_CANDIDATES = (
    (r"C:\Windows\Fonts\arial.ttf", r"C:\Windows\Fonts\arialbd.ttf"),
    (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    ),
)


def _export_pdf(filename, cols, rows):
    from html import escape

    from reportlab.lib import colors
    from reportlab.lib.enums import TA_LEFT
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.platypus import LongTable, Paragraph, SimpleDocTemplate, TableStyle

    font_pair = next(
        (
            (regular, bold)
            for regular, bold in _PDF_FONT_CANDIDATES
            if os.path.isfile(regular) and os.path.isfile(bold)
        ),
        None,
    )
    if not font_pair:
        raise ValueError("Không tìm thấy phông chữ Unicode để xuất PDF tiếng Việt.")
    if "ExportUnicode" not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont("ExportUnicode", font_pair[0]))
        pdfmetrics.registerFont(TTFont("ExportUnicode-Bold", font_pair[1]))
    style = ParagraphStyle(
        "ExportCell",
        fontName="ExportUnicode",
        fontSize=6.5,
        leading=8,
        alignment=TA_LEFT,
        wordWrap="CJK",
    )
    header = ParagraphStyle(
        "ExportHeader", parent=style, fontName="ExportUnicode-Bold", textColor=colors.white
    )
    table_data = [[Paragraph(escape(str(value)), header) for value in cols]]
    table_data.extend(
        [
            Paragraph(escape("" if value is None else str(value)).replace("\n", "<br/>"), style)
            for value in row
        ]
        for row in rows
    )
    output = io.BytesIO()
    document = SimpleDocTemplate(
        output,
        pagesize=landscape(A4),
        rightMargin=20,
        leftMargin=20,
        topMargin=24,
        bottomMargin=24,
    )
    table = LongTable(table_data, repeatRows=1, hAlign="LEFT")
    table_styles = [
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#243b61")),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#ccd4df")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]
    if rows:
        table_styles.append(
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f3f6fa")])
        )
    table.setStyle(TableStyle(table_styles))
    document.build([table])
    output.seek(0)
    return send_file(
        output, as_attachment=True, download_name=f"{filename}.pdf", mimetype="application/pdf"
    )


_EXPORTERS = {"csv": _export_csv, "xlsx": _export_xlsx, "pdf": _export_pdf}


def _export_response(filename, cols, rows, file_format):
    exporter = _EXPORTERS.get(file_format)
    if exporter is None:
        raise ValueError("Vui lòng chọn CSV, Excel hoặc PDF.")
    return exporter(filename, cols, rows)

