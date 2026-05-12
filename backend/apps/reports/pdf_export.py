"""
PDF export utility using ReportLab.

Two export modes:
1. Per-student result card (existing): groups results across subjects per student.
2. Bundle PDF (new): one PDF per bundle listing every student's roll number,
   anonymization token, and per-question/section mark breakdown.
"""
import io
from datetime import date
from django.http import HttpResponse
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch, mm
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.platypus import (
    SimpleDocTemplate, Table, TableStyle, Paragraph,
    Spacer, HRFlowable, PageBreak,
)


def _build_student_pdf_elements(student, styles):
    """Build ReportLab elements for a single student result card."""
    elements = []

    # ── College Header ───────────────────────────
    header_style = ParagraphStyle(
        'CollegeHeader', parent=styles['Title'],
        fontSize=16, leading=20, alignment=TA_CENTER,
        textColor=colors.HexColor('#1C1D22'),
    )
    sub_header = ParagraphStyle(
        'SubHeader', parent=styles['Normal'],
        fontSize=10, alignment=TA_CENTER,
        textColor=colors.HexColor('#64748B'),
    )
    elements.append(Paragraph('ExamFlow — Examination Management System', header_style))
    elements.append(Paragraph('Student Evaluation Report Card', sub_header))
    elements.append(Spacer(1, 0.25 * inch))
    elements.append(HRFlowable(
        width='100%', thickness=1, color=colors.HexColor('#E2E8F0'),
        spaceAfter=0.2 * inch,
    ))

    # ── Student Info ─────────────────────────────
    info_style = ParagraphStyle(
        'Info', parent=styles['Normal'], fontSize=10, leading=14,
    )
    bold_style = ParagraphStyle(
        'InfoBold', parent=styles['Normal'], fontSize=10, leading=14,
        textColor=colors.HexColor('#1C1D22'),
    )

    roll = student.get('roll_number', 'N/A')
    dept = student.get('department', 'N/A')
    sem = student.get('semester', 'N/A')
    acad = student.get('academic_year', 'N/A')

    info_data = [
        [Paragraph(f'<b>Roll Number:</b> {roll}', info_style),
         Paragraph(f'<b>Department:</b> {dept}', info_style)],
        [Paragraph(f'<b>Semester:</b> {sem}', info_style),
         Paragraph(f'<b>Academic Year:</b> {acad}', info_style)],
    ]
    info_table = Table(info_data, colWidths=['50%', '50%'])
    info_table.setStyle(TableStyle([
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
    ]))
    elements.append(info_table)
    elements.append(Spacer(1, 0.3 * inch))

    # ── Subjects Table ───────────────────────────
    table_header = ['Subject Code', 'Subject Name', 'Semester', 'Total Marks', 'Evaluated On']
    table_data = [table_header]

    for subj in student.get('subjects', []):
        table_data.append([
            subj.get('subject_code', ''),
            subj.get('subject_name', ''),
            str(subj.get('semester', '')),
            str(subj.get('total_marks', 0)),
            subj.get('evaluated_on', ''),
        ])

    col_widths = [1.2 * inch, 2.0 * inch, 0.9 * inch, 1.0 * inch, 1.2 * inch]
    subjects_table = Table(table_data, colWidths=col_widths, repeatRows=1)
    subjects_table.setStyle(TableStyle([
        # Header row
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1C1D22')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 9),
        # Data rows
        ('FONTSIZE', (0, 1), (-1, -1), 9),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#E2E8F0')),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#F7F8FA')]),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
    ]))
    elements.append(subjects_table)
    elements.append(Spacer(1, 0.2 * inch))

    # ── Grand Total ──────────────────────────────
    grand_total = student.get('grand_total', 0)
    total_style = ParagraphStyle(
        'GrandTotal', parent=styles['Normal'],
        fontSize=12, alignment=TA_RIGHT,
        textColor=colors.HexColor('#1C1D22'),
    )
    elements.append(Paragraph(f'<b>GRAND TOTAL:  {grand_total}</b>', total_style))
    elements.append(Spacer(1, 0.5 * inch))

    # ── Footer ───────────────────────────────────
    elements.append(HRFlowable(
        width='100%', thickness=0.5, color=colors.HexColor('#E2E8F0'),
        spaceAfter=0.1 * inch,
    ))
    footer_style = ParagraphStyle(
        'Footer', parent=styles['Normal'],
        fontSize=8, alignment=TA_CENTER,
        textColor=colors.HexColor('#94A3B8'),
    )
    elements.append(Paragraph(
        f'Generated on {date.today().strftime("%d %B %Y")} — ExamFlow Examination Management System',
        footer_style
    ))

    return elements


def generate_student_pdf_response(student):
    """Generate a downloadable PDF HttpResponse for a single student."""
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4,
        rightMargin=0.6 * inch, leftMargin=0.6 * inch,
        topMargin=0.6 * inch, bottomMargin=0.6 * inch,
    )
    styles = getSampleStyleSheet()
    elements = _build_student_pdf_elements(student, styles)
    doc.build(elements)

    roll = student.get('roll_number', 'student')
    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="result_{roll}.pdf"'
    response.write(buffer.getvalue())
    buffer.close()
    return response


def generate_student_pdf_bytes(student):
    """Generate PDF bytes (BytesIO) for a single student — used for ZIP bundling."""
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4,
        rightMargin=0.6 * inch, leftMargin=0.6 * inch,
        topMargin=0.6 * inch, bottomMargin=0.6 * inch,
    )
    styles = getSampleStyleSheet()
    elements = _build_student_pdf_elements(student, styles)
    doc.build(elements)
    buffer.seek(0)
    return buffer


# ── Bundle PDF ────────────────────────────────────────────────────────────────

def _build_bundle_pdf_elements(bundle_data, styles):
    """
    Build all ReportLab elements for a bundle-level result PDF.

    bundle_data structure:
    {
        'bundle_number': '001',
        'subject_code': 'CS601',
        'subject_name': 'Operating Systems',
        'department': 'Computer Science',
        'semester': 6,
        'academic_year': '2025-26',
        'total_sheets': 30,
        'generated_on': '21 April 2026',
        'sheets': [
            {
                'roll_number': '2022CS001',
                'token': 'TKN-XXXX',
                'status': 'completed',
                'total_marks': 42,
                'section_results': [
                    {
                        'section_name': 'A',
                        'questions': [
                            {'question_no': '1', 'max_marks': 5, 'marks_obtained': 4},
                            ...
                        ],
                        'section_total': 4
                    },
                    ...
                ]
            },
            ...
        ]
    }
    """
    elements = []

    # ── Shared styles ──────────────────────────────────────────────────────
    h_style = ParagraphStyle(
        'BundleHeader', parent=styles['Title'],
        fontSize=15, leading=20, alignment=TA_CENTER,
        textColor=colors.HexColor('#1C1D22'),
    )
    sub_h = ParagraphStyle(
        'BundleSubHeader', parent=styles['Normal'],
        fontSize=10, alignment=TA_CENTER,
        textColor=colors.HexColor('#64748B'),
    )
    section_title_style = ParagraphStyle(
        'SectionTitle', parent=styles['Normal'],
        fontSize=11, fontName='Helvetica-Bold',
        textColor=colors.HexColor('#1C1D22'),
        spaceAfter=4,
    )
    info_style = ParagraphStyle(
        'InfoSmall', parent=styles['Normal'],
        fontSize=9, leading=13,
    )
    footer_style = ParagraphStyle(
        'BundleFooter', parent=styles['Normal'],
        fontSize=8, alignment=TA_CENTER,
        textColor=colors.HexColor('#94A3B8'),
    )

    # ── Cover Page ─────────────────────────────────────────────────────────
    elements.append(Spacer(1, 0.5 * inch))
    elements.append(Paragraph('ExamFlow — Examination Management System', h_style))
    elements.append(Paragraph('Bundle Evaluation Report', sub_h))
    elements.append(Spacer(1, 0.3 * inch))
    elements.append(HRFlowable(width='100%', thickness=1.5, color=colors.HexColor('#1C1D22'), spaceAfter=0.3 * inch))

    cover_data = [
        ['Bundle Number', bundle_data.get('bundle_number') or '-'],
        ['Subject', f"{bundle_data.get('subject_code') or '-'} — {bundle_data.get('subject_name') or '-'}"] ,
        ['Department', bundle_data.get('department') or '-'],
        ['Semester', str(bundle_data.get('semester') if bundle_data.get('semester') is not None else '-')],
        ['Academic Year', bundle_data.get('academic_year') or '-'],
        ['Total Sheets', str(bundle_data.get('total_sheets') if bundle_data.get('total_sheets') is not None else 0)],
        ['Generated On', bundle_data.get('generated_on') or '-'],
    ]
    cover_table = Table(cover_data, colWidths=[2.0 * inch, 4.5 * inch])
    cover_table.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 10),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ('LEFTPADDING', (0, 0), (-1, -1), 8),
        ('ROWBACKGROUNDS', (0, 0), (-1, -1), [colors.HexColor('#F7F8FA'), colors.white]),
        ('GRID', (0, 0), (-1, -1), 0.4, colors.HexColor('#E2E8F0')),
    ]))
    elements.append(cover_table)
    elements.append(Spacer(1, 0.5 * inch))
    elements.append(HRFlowable(width='100%', thickness=0.5, color=colors.HexColor('#E2E8F0'), spaceAfter=0.2 * inch))
    elements.append(Paragraph(
        f'Generated on {bundle_data.get("generated_on", "")} — ExamFlow Examination Management System',
        footer_style,
    ))

    # ── Per-Student Sections ───────────────────────────────────────────────
    sheets = bundle_data.get('sheets', [])
    for idx, sheet in enumerate(sheets, start=1):
        elements.append(PageBreak())

        roll = sheet.get('roll_number', 'N/A')
        token = sheet.get('token', 'N/A')
        total_marks = sheet.get('total_marks', '-')
        sheet_status = sheet.get('status', 'pending')
        section_results = sheet.get('section_results', [])

        # Student header card
        elements.append(Paragraph(f'ExamFlow — Bundle #{bundle_data.get("bundle_number")}', sub_h))
        elements.append(Spacer(1, 0.15 * inch))
        elements.append(HRFlowable(width='100%', thickness=1, color=colors.HexColor('#1C1D22'), spaceAfter=0.15 * inch))

        student_info = [
            [
                Paragraph(f'<b>Student {idx} of {len(sheets)}</b>', info_style),
                Paragraph(f'<b>Subject:</b> {bundle_data.get("subject_code") or "-"} — {bundle_data.get("subject_name") or "-"}', info_style),
            ],
            [
                Paragraph(f'<b>Roll Number:</b> {roll}', info_style),
                Paragraph(f'<b>Department:</b> {bundle_data.get("department") or "-"} &nbsp; | &nbsp; '
                          f'<b>Sem:</b> {bundle_data.get("semester") if bundle_data.get("semester") is not None else "-"}', info_style),
            ],
            [
                Paragraph(f'<b>Token / Code:</b> {token}', info_style),
                Paragraph(f'<b>Academic Year:</b> {bundle_data.get("academic_year") or "-"}', info_style),
            ],
        ]
        info_tbl = Table(student_info, colWidths=['50%', '50%'])
        info_tbl.setStyle(TableStyle([
            ('TOPPADDING', (0, 0), (-1, -1), 4),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ]))
        elements.append(info_tbl)
        elements.append(Spacer(1, 0.25 * inch))

        if sheet_status != 'completed' or not section_results:
            # Not yet evaluated
            pending_style = ParagraphStyle(
                'Pending', parent=styles['Normal'],
                fontSize=11, alignment=TA_CENTER,
                textColor=colors.HexColor('#EF4444'),
            )
            elements.append(Paragraph('⚠ This answer sheet has not been evaluated yet.', pending_style))
        else:
            # Build marks breakdown table using real schema:
            # section_results = [{ name, sub_questions: [{ name, parts: [{ name, max_marks, marks_obtained }] }] }]
            col_widths = [1.5 * inch, 1.2 * inch, 1.2 * inch, 1.4 * inch, 1.4 * inch]
            marks_header = ['Question', 'Sub-Q', 'Part', 'Max Marks', 'Marks Obtained']
            marks_data = [marks_header]
            subtotal_rows = []
            row_cursor = 1  # 1-indexed, row 0 is header

            for q in section_results:
                q_name = q.get('name', '')
                q_obtained_total = q.get('obtained_total', 0)
                q_max_total = 0
                first_part_of_q = True

                for sq in q.get('sub_questions', []):
                    sq_name = sq.get('name', '')
                    sq_obtained = sq.get('obtained_total', 0)
                    sq_max = sum(p.get('max_marks', 0) for p in sq.get('parts', []))
                    first_part_of_sq = True

                    for part in sq.get('parts', []):
                        p_name = part.get('name', '')
                        max_m = part.get('max_marks', 0)
                        obtained = part.get('marks_obtained')
                        q_max_total += max_m

                        if obtained is None or str(obtained).strip().lower() in ['none', 'null', '']:
                            obtained_str = '—'
                        else:
                            obtained_str = str(obtained)

                        marks_data.append([
                            f'Q {q_name}' if first_part_of_q else '',
                            sq_name if first_part_of_sq else '',
                            p_name,
                            str(max_m),
                            obtained_str,
                        ])
                        first_part_of_q = False
                        first_part_of_sq = False
                        row_cursor += 1

                # Sub-question subtotal row
                # (skipped per-sq subtotal to keep PDF compact; only question subtotals shown)
                pass

                # Question subtotal row
                marks_data.append([
                    '',
                    Paragraph(f'<b>Q {q_name} Total</b>', info_style),
                    '',
                    Paragraph(f'<b>{q_max_total}</b>', info_style),
                    Paragraph(f'<b>{q_obtained_total}</b>', info_style),
                ])
                subtotal_rows.append(row_cursor)
                row_cursor += 1

            # Grand total row
            marks_data.append([
                '',
                Paragraph('<b>GRAND TOTAL</b>', ParagraphStyle('GT', parent=styles['Normal'], fontSize=10, fontName='Helvetica-Bold')),
                '',
                '',
                Paragraph(f'<b>{total_marks}</b>', ParagraphStyle('GTM', parent=styles['Normal'], fontSize=10, fontName='Helvetica-Bold', textColor=colors.HexColor('#10B981'))),
            ])
            grand_total_row = row_cursor

            style_cmds = [
                # Header
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1C1D22')),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, 0), 9),
                # Body
                ('FONTSIZE', (0, 1), (-1, -1), 9),
                ('ALIGN', (2, 0), (-1, -1), 'CENTER'),
                ('ALIGN', (0, 0), (1, -1), 'LEFT'),
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                ('GRID', (0, 0), (-1, -1), 0.4, colors.HexColor('#E2E8F0')),
                ('ROWBACKGROUNDS', (0, 1), (-1, grand_total_row - 1), [colors.white, colors.HexColor('#F7F8FA')]),
                ('TOPPADDING', (0, 0), (-1, -1), 5),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
                ('LEFTPADDING', (0, 0), (-1, -1), 6),
                # Grand total row
                ('BACKGROUND', (0, grand_total_row), (-1, grand_total_row), colors.HexColor('#ECFDF5')),
                ('LINEABOVE', (0, grand_total_row), (-1, grand_total_row), 1.5, colors.HexColor('#10B981')),
            ]
            # Subtotal rows
            for sr in subtotal_rows:
                style_cmds += [
                    ('BACKGROUND', (0, sr), (-1, sr), colors.HexColor('#F1F5F9')),
                    ('LINEABOVE', (0, sr), (-1, sr), 0.5, colors.HexColor('#CBD5E1')),
                ]
            marks_table = Table(marks_data, colWidths=col_widths, repeatRows=1)
            marks_table.setStyle(TableStyle(style_cmds))
            elements.append(marks_table)


        # Footer line
        elements.append(Spacer(1, 0.3 * inch))
        elements.append(HRFlowable(width='100%', thickness=0.5, color=colors.HexColor('#E2E8F0'), spaceAfter=0.1 * inch))
        elements.append(Paragraph(
            f'ExamFlow — Bundle #{bundle_data.get("bundle_number")} | Roll: {roll} | Token: {token}',
            footer_style,
        ))

    return elements


def generate_bundle_pdf_response(bundle_data):
    """Generate a downloadable PDF HttpResponse for a full bundle."""
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4,
        rightMargin=0.6 * inch, leftMargin=0.6 * inch,
        topMargin=0.6 * inch, bottomMargin=0.6 * inch,
    )
    styles = getSampleStyleSheet()
    elements = _build_bundle_pdf_elements(bundle_data, styles)
    doc.build(elements)

    bundle_num = bundle_data.get('bundle_number', 'bundle')
    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="bundle_{bundle_num}_report.pdf"'
    response.write(buffer.getvalue())
    buffer.close()
    return response

