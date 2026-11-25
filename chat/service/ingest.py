import csv
import os
import re
import tempfile

import pdfplumber
from django.core.files.base import ContentFile


class NoTableFound(Exception):
    pass


def _clean_cell(cell):
    return re.sub(r"\s+", " ", cell).strip() if cell else ""


def _merge_tables(tables):
    """Tables that repeat the same header row (a table split over pages) become one table;
    the largest resulting table wins."""
    merged = {}
    for rows in tables:
        header = tuple(rows[0])
        if header in merged:
            merged[header].extend(rows[1:])
        else:
            merged[header] = list(rows)
    return max(merged.values(), key=len)


def extract_pdf_table(pdf_path):
    """Largest table in the PDF as a list of rows (first row is the header).
    Returns (rows, table_count). Raises NoTableFound if the PDF has no table."""
    tables = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            for raw in page.extract_tables():
                rows = [[_clean_cell(c) for c in row] for row in raw]
                rows = [r for r in rows if any(r)]
                if len(rows) >= 2:
                    tables.append(rows)
    if not tables:
        raise NoTableFound("No table with a header and data rows was found in this PDF.")
    return _merge_tables(tables), len(tables)


def pdf_to_csv(pdf_path, csv_path):
    """Write the largest table of the PDF to csv_path. Returns (row_count, table_count)."""
    rows, table_count = extract_pdf_table(pdf_path)
    width = len(rows[0])
    os.makedirs(os.path.dirname(csv_path), exist_ok=True)
    with open(csv_path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        for row in rows:
            writer.writerow((row + [""] * width)[:width])
    return len(rows) - 1, table_count


def document_csv_path(document):
    """Where the CSV made from this document's PDF is cached (named after the PDF so the
    agent can refer to it by name)."""
    stem = os.path.splitext(os.path.basename(document.file.name))[0]
    stem = re.sub(r"_[A-Za-z0-9]{7}$", "", stem)
    return os.path.join(os.path.dirname(document.file.path), "derived", str(document.pk), f"{stem}.csv")


def ensure_document_csv(document):
    """CSV for the document's PDF, made on first use and cached. Returns (csv_path, note);
    note says which table was used when the PDF had several."""
    path = document_csv_path(document)
    if os.path.exists(path):
        return path, ""
    rows, table_count = pdf_to_csv(document.file.path, path)
    note = f" (the PDF had {table_count} tables; the largest was used)" if table_count > 1 else ""
    return path, f"{rows} rows{note}"


def pdf_upload_to_csv_file(uploaded):
    """Chat attachment: turn an uploaded PDF into a CSV file ready to store on a Message.
    Returns (ContentFile, note). Raises NoTableFound if the PDF has no table."""
    stem = os.path.splitext(os.path.basename(uploaded.name))[0]
    with tempfile.TemporaryDirectory() as tmp:
        pdf_path = os.path.join(tmp, "upload.pdf")
        with open(pdf_path, "wb") as handle:
            for chunk in uploaded.chunks():
                handle.write(chunk)
        csv_path = os.path.join(tmp, f"{stem}.csv")
        rows, table_count = pdf_to_csv(pdf_path, csv_path)
        with open(csv_path, "rb") as handle:
            content = ContentFile(handle.read(), name=f"{stem}.csv")
    note = f" (the PDF had {table_count} tables; the largest was used)" if table_count > 1 else ""
    return content, f"{rows} rows{note}"
