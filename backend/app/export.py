"""
Builds the downloadable lead list as a styled .xlsx workbook. The one detail
that matters most here: the phone column MUST be written as text, or Excel
silently reinterprets a leading-'+' E.164 number as a number and mangles it
into scientific notation on open.
"""
from __future__ import annotations

import io
from datetime import datetime, timezone

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.table import Table, TableStyleInfo

from app.models import Lead

_HEADERS = [
    ("First Name", "first_name", 16),
    ("Last Name", "last_name", 16),
    ("Position / Job Title", "job_title", 24),
    ("Company", "company", 26),
    ("Location", "location", 24),
    ("Phone Number", "phone", 18),
    ("Email Address", "email", 28),
    ("Additional Phones", "_additional_phones", 22),
    ("Website", "website", 24),
    ("Confidence", "_confidence_pct", 12),
    ("Warnings", "_warnings_str", 24),
    ("Source File", "source_file", 24),
]

_HEADER_FILL = PatternFill(start_color="1F2937", end_color="1F2937", fill_type="solid")
_HEADER_FONT = Font(color="FFFFFF", bold=True)


def build_leads_workbook(leads: list[Lead]) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "Leads"

    ws.append([h for h, _, _ in _HEADERS])
    for col_idx, (_, _, width) in enumerate(_HEADERS, start=1):
        cell = ws.cell(row=1, column=col_idx)
        cell.fill = _HEADER_FILL
        cell.font = _HEADER_FONT
        cell.alignment = Alignment(vertical="center")
        ws.column_dimensions[get_column_letter(col_idx)].width = width
    ws.freeze_panes = "A2"

    only_done = [l for l in leads if l.status == "done"]

    for lead in only_done:
        row_values = []
        for _, field, _ in _HEADERS:
            row_values.append(_field_value(lead, field))
        ws.append(row_values)

        row_idx = ws.max_row
        phone_col = next(i for i, (_, f, _) in enumerate(_HEADERS, start=1) if f == "phone")
        ws.cell(row=row_idx, column=phone_col).number_format = "@"  # force text format

        email_col = next(i for i, (_, f, _) in enumerate(_HEADERS, start=1) if f == "email")
        if lead.email:
            ws.cell(row=row_idx, column=email_col).hyperlink = f"mailto:{lead.email}"
            ws.cell(row=row_idx, column=email_col).font = Font(color="1D4ED8", underline="single")

    last_row = max(ws.max_row, 1)
    last_col = len(_HEADERS)
    if last_row > 1:
        table_ref = f"A1:{get_column_letter(last_col)}{last_row}"
        table = Table(displayName="Leads", ref=table_ref)
        table.tableStyleInfo = TableStyleInfo(
            name="TableStyleMedium2", showRowStripes=True, showFirstColumn=False
        )
        ws.add_table(table)

    meta_ws = wb.create_sheet("Summary")
    meta_ws.append(["Generated at (UTC)", datetime.now(timezone.utc).isoformat(timespec="seconds")])
    meta_ws.append(["Total leads exported", len(only_done)])
    meta_ws.append(["Total cards uploaded", len(leads)])
    failed = sum(1 for l in leads if l.status == "failed")
    meta_ws.append(["Cards that failed extraction", failed])
    meta_ws.column_dimensions["A"].width = 30
    meta_ws.column_dimensions["B"].width = 30

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _field_value(lead: Lead, field: str) -> str:
    if field == "_additional_phones":
        return "; ".join(lead.additional_phones)
    if field == "_confidence_pct":
        return round(lead.confidence * 100, 1)
    if field == "_warnings_str":
        return "; ".join(lead.warnings)
    return getattr(lead, field, None) or ""
