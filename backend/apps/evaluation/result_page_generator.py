"""
result_page_generator.py
------------------------
Generates a single-page PDF result summary to prepend to each marked answer sheet.
Runs entirely in memory — returns bytes, nothing written to disk.

Page layout (A4 portrait):
  ┌─────────────────────────────────────────────┐
  │  [ExamFlow header bar — teal #0F6E56]       │
  ├─────────────────────────────────────────────┤
  │  Student: 1 of N   Subject: ETH405 — Name  │
  │  Roll Number: 2023CS045                     │
  │  Token / Code: XK729FAB                     │
  │  Department: ENTC  |  Sem: 3               │
  │  Academic Year: 2025-26                     │
  ├─────────────────────────────────────────────┤
  │  TABLE:                                     │
  │  Question | Sub-Q | Part | Max | Obtained  │
  │  ─────────────────────────────────────────  │
  │  Q Q1     | Q1A   |  1   |  2  |    2      │
  │           | Q1B   |  1   |  2  |   1.5     │
  │           | ...                             │
  │           | Q Q1 Total  | 14  |   8.5      │
  │  Q Q2     | Q2A   |  1   |  4  |   3.5     │
  │           | ...                             │
  │           | Q Q2 Total  | 28  |   19.0     │
  │  ─────────────────────────────────────────  │
  │  GRAND TOTAL              | 42  |   27.5   │
  └─────────────────────────────────────────────┘
"""

import io
from reportlab.pdfgen import canvas as rl_canvas
from reportlab.lib.pagesizes import A4
from reportlab.lib.colors import HexColor, white, black
from reportlab.lib.units import mm
from reportlab.platypus import (
    SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT

# ── Color constants ──────────────────────────────────────────────────────────
COLOR_HEADER_BG      = white
COLOR_HEADER_TEXT    = black
COLOR_TABLE_HEADER   = HexColor('#1A202C')
COLOR_TABLE_HDR_TEXT = white
COLOR_SECTION_TOTAL  = HexColor('#F1F5F9')
COLOR_SECTION_TEXT   = black
COLOR_GRAND_BG       = HexColor('#ECFDF5')
COLOR_GRAND_TEXT     = HexColor('#10B981')
COLOR_ROW_ALT        = HexColor('#F9FAFB')
COLOR_ROW_WHITE      = white
COLOR_BORDER         = HexColor('#CBD5E0')
COLOR_BODY_TEXT      = black
COLOR_MUTED_TEXT     = HexColor('#4A5568')

PAGE_WIDTH, PAGE_HEIGHT = A4   # 595.27 x 841.89 points
MARGIN_LEFT   = 20 * mm
MARGIN_RIGHT  = 20 * mm
MARGIN_TOP    = 15 * mm
MARGIN_BOTTOM = 20 * mm
CONTENT_WIDTH = PAGE_WIDTH - MARGIN_LEFT - MARGIN_RIGHT


def generate_result_page(
    roll_number: str,
    token: str,
    subject_code: str,
    subject_name: str,
    department: str,
    semester: int,
    academic_year: str,
    section_results: list,
    total_marks: float,
    student_index: int = 1,
    total_students: int = 1,
) -> bytes:
    """
    Generates a single A4 result summary page.
    """
    buffer = io.BytesIO()

    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=MARGIN_LEFT,
        rightMargin=MARGIN_RIGHT,
        topMargin=MARGIN_TOP,
        bottomMargin=MARGIN_BOTTOM,
    )

    styles = getSampleStyleSheet()
    story  = []

    # ── Header bar ────────────────────────────────────────────────────────────
    header_style = ParagraphStyle(
        'HeaderLeft',
        fontName='Helvetica-Bold',
        fontSize=10,
        textColor=COLOR_HEADER_TEXT,
        backColor=COLOR_HEADER_BG,
        leading=14,
    )
    header_right_style = ParagraphStyle(
        'HeaderRight',
        fontName='Helvetica',
        fontSize=10,
        textColor=COLOR_HEADER_TEXT,
        backColor=COLOR_HEADER_BG,
        leading=14,
        alignment=TA_RIGHT,
    )

    header_table = Table(
        [[
            Paragraph(f"<b>Student {student_index} of {total_students}</b>", header_style),
            Paragraph(
                f"<b>Subject:</b> {subject_code} — {subject_name}",
                header_right_style
            ),
        ]],
        colWidths=[CONTENT_WIDTH * 0.35, CONTENT_WIDTH * 0.65],
    )
    header_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), COLOR_HEADER_BG),
        ('TOPPADDING',    (0, 0), (-1, -1), 2),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 10),
        ('LEFTPADDING',   (0, 0), (0, -1), 0),
        ('RIGHTPADDING',  (-1, 0), (-1, -1), 0),
    ]))
    story.append(header_table)
    story.append(Spacer(1, 4 * mm))

    # ── Student info block ────────────────────────────────────────────────────
    info_label_style = ParagraphStyle(
        'InfoLabel',
        fontName='Helvetica-Bold',
        fontSize=9,
        textColor=COLOR_BODY_TEXT,
        leading=14,
    )
    info_value_style = ParagraphStyle(
        'InfoValue',
        fontName='Helvetica',
        fontSize=9,
        textColor=COLOR_BODY_TEXT,
        leading=14,
    )

    def info_row(label, value):
        return [
            Paragraph(f"<b>{label}</b>", info_label_style),
            Paragraph(str(value), info_value_style),
        ]

    info_data = [
        info_row("Roll Number:", roll_number),
        info_row("Token / Code:", token),
        info_row("Department:", f"{department}   |   Sem: {semester}"),
        info_row("Academic Year:", academic_year),
    ]

    info_table = Table(info_data, colWidths=[CONTENT_WIDTH * 0.25, CONTENT_WIDTH * 0.75])
    info_table.setStyle(TableStyle([
        ('TOPPADDING',    (0, 0), (-1, -1), 2),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
        ('LEFTPADDING',   (0, 0), (-1, -1), 0),
    ]))
    story.append(info_table)
    story.append(Spacer(1, 5 * mm))

    # ── Marks table ───────────────────────────────────────────────────────────
    col_widths = [
        CONTENT_WIDTH * 0.20,   # Question
        CONTENT_WIDTH * 0.18,   # Sub-Q
        CONTENT_WIDTH * 0.12,   # Part
        CONTENT_WIDTH * 0.22,   # Max Marks
        CONTENT_WIDTH * 0.28,   # Marks Obtained
    ]

    tbl_header_style = ParagraphStyle(
        'TblHeader',
        fontName='Helvetica-Bold',
        fontSize=9,
        textColor=COLOR_TABLE_HDR_TEXT,
        alignment=TA_CENTER,
        leading=12,
    )
    tbl_cell_style = ParagraphStyle(
        'TblCell',
        fontName='Helvetica',
        fontSize=9,
        textColor=COLOR_BODY_TEXT,
        alignment=TA_CENTER,
        leading=12,
    )
    tbl_cell_left = ParagraphStyle(
        'TblCellLeft',
        fontName='Helvetica',
        fontSize=9,
        textColor=COLOR_BODY_TEXT,
        alignment=TA_LEFT,
        leading=12,
    )
    tbl_bold_center = ParagraphStyle(
        'TblBoldCenter',
        fontName='Helvetica-Bold',
        fontSize=9,
        textColor=COLOR_SECTION_TEXT,
        alignment=TA_CENTER,
        leading=12,
    )
    tbl_grand_style = ParagraphStyle(
        'TblGrand',
        fontName='Helvetica-Bold',
        fontSize=10,
        textColor=COLOR_GRAND_TEXT,
        alignment=TA_CENTER,
        leading=14,
    )

    # Build table rows
    table_data = []
    row_styles  = []   # list of TableStyle commands built per-row
    row_index   = 1    # 0 = header row

    # Header row
    table_data.append([
        Paragraph("Question",       tbl_header_style),
        Paragraph("Sub-Q",          tbl_header_style),
        Paragraph("Part",           tbl_header_style),
        Paragraph("Max Marks",      tbl_header_style),
        Paragraph("Marks Obtained", tbl_header_style),
    ])
    row_styles.append(('BACKGROUND', (0, 0), (-1, 0), COLOR_TABLE_HEADER))
    row_styles.append(('TOPPADDING',    (0, 0), (-1, 0), 6))
    row_styles.append(('BOTTOMPADDING', (0, 0), (-1, 0), 6))

    grand_max_total      = 0
    grand_obtained_total = 0

    for section in section_results:
        section_name     = section.get('name', '')
        sub_questions    = section.get('sub_questions', [])
        
        section_max      = 0
        for sq in sub_questions:
            for part in sq.get('parts', []):
                section_max += part.get('max_marks', 0)
                
        section_obtained = section.get('obtained_total', 0)

        grand_max_total      += section_max
        grand_obtained_total += section_obtained

        first_in_section = True

        for sq in sub_questions:
            sq_name = sq.get('name', '')
            parts   = sq.get('parts', [])

            for part in parts:
                part_name  = part.get('name', '1')
                max_m      = part.get('max_marks', 0)
                obtained   = part.get('marks_obtained')
                if obtained is None or str(obtained).strip().lower() in ['none', 'null', '']:
                    obtained_str = '—'
                else:
                    obtained_str = str(obtained)
                # Show section name only on first question of section
                question_cell = Paragraph(
                    section_name if first_in_section else '',
                    tbl_cell_left
                )
                first_in_section = False

                # Alternate row background
                bg = COLOR_ROW_WHITE if row_index % 2 == 0 else COLOR_ROW_ALT
                row_styles.append(('BACKGROUND', (0, row_index), (-1, row_index), bg))

                table_data.append([
                    question_cell,
                    Paragraph(sq_name,           tbl_cell_style),
                    Paragraph(str(part_name),    tbl_cell_style),
                    Paragraph(str(max_m),        tbl_cell_style),
                    Paragraph(obtained_str,      tbl_cell_style),
                ])
                row_styles.append(('TOPPADDING',    (0, row_index), (-1, row_index), 4))
                row_styles.append(('BOTTOMPADDING', (0, row_index), (-1, row_index), 4))
                row_index += 1

        # Section total row
        table_data.append([
            Paragraph('', tbl_cell_style),
            Paragraph(f"{section_name} Total", tbl_bold_center),
            Paragraph('', tbl_cell_style),
            Paragraph(str(section_max),           tbl_bold_center),
            Paragraph(str(section_obtained),      tbl_bold_center),
        ])
        row_styles.append(('BACKGROUND',    (0, row_index), (-1, row_index), COLOR_SECTION_TOTAL))
        row_styles.append(('TOPPADDING',    (0, row_index), (-1, row_index), 5))
        row_styles.append(('BOTTOMPADDING', (0, row_index), (-1, row_index), 5))
        row_styles.append(('SPAN', (1, row_index), (2, row_index)))
        row_index += 1

    # Grand total row
    tbl_grand_label = ParagraphStyle(
        'TblGrandLabel',
        fontName='Helvetica-Bold',
        fontSize=10,
        textColor=black,
        alignment=TA_CENTER,
        leading=14,
    )
    table_data.append([
        Paragraph('', tbl_grand_style),
        Paragraph('GRAND TOTAL', tbl_grand_label),
        Paragraph('', tbl_grand_style),
        Paragraph('', tbl_grand_style),
        Paragraph(str(total_marks), tbl_grand_style),
    ])
    row_styles.append(('BACKGROUND',    (0, row_index), (-1, row_index), COLOR_GRAND_BG))
    row_styles.append(('TOPPADDING',    (0, row_index), (-1, row_index), 7))
    row_styles.append(('BOTTOMPADDING', (0, row_index), (-1, row_index), 7))
    row_styles.append(('SPAN', (1, row_index), (2, row_index)))
    row_index += 1

    # Global table styles
    base_styles = [
        ('LEFTPADDING',  (0, 0), (-1, -1), 6),
        ('RIGHTPADDING', (0, 0), (-1, -1), 6),
        ('VALIGN',       (0, 0), (-1, -1), 'MIDDLE'),
        ('LINEBELOW',    (0, 0), (-1, 0), 1, white), # white line under header
    ]

    marks_table = Table(table_data, colWidths=col_widths, repeatRows=1)
    marks_table.setStyle(TableStyle(base_styles + row_styles))

    story.append(marks_table)

    # ── Footer ────────────────────────────────────────────────────────────────
    story.append(Spacer(1, 6 * mm))
    footer_style = ParagraphStyle(
        'Footer',
        fontName='Helvetica',
        fontSize=8,
        textColor=COLOR_MUTED_TEXT,
        alignment=TA_CENTER,
        leading=12,
    )
    story.append(Paragraph(
        f"Generated by ExamFlow  •  {subject_code} — {subject_name}  •  {academic_year}",
        footer_style
    ))

    doc.build(story)
    buffer.seek(0)
    return buffer.read()
