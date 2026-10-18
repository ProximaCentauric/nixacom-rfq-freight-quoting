"""
Document Parser Service for PDF and Excel Freight Attachments.
Supports raw text extraction, table parsing, and structured data extraction.
"""

from typing import Dict, Any, List, Optional
import io

try:
    import pdfplumber
except ImportError:
    pdfplumber = None

try:
    import pypdf
except ImportError:
    pypdf = None

try:
    import pandas as pd
except ImportError:
    pd = None


class DocumentParser:
    """Extracts text and tabular content from PDF and Excel files."""

    @staticmethod
    def extract_from_pdf_bytes(file_bytes: bytes, filename: str = "") -> Dict[str, Any]:
        """Extracts text and structured tables from a PDF document."""
        extracted_text = ""
        tables_data = []

        # 1. Primary Attempt: pdfplumber for high-precision text & table extraction
        if pdfplumber:
            try:
                with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
                    for page_num, page in enumerate(pdf.pages, start=1):
                        page_text = page.extract_text()
                        if page_text:
                            extracted_text += f"\n--- Page {page_num} ---\n" + page_text

                        # Extract tabular data (e.g., line items in Packing Lists)
                        page_tables = page.extract_tables()
                        for tbl in page_tables:
                            if tbl:
                                tables_data.append({
                                    "page": page_num,
                                    "rows": tbl
                                })
            except Exception as err:
                print(f"[DocumentParser Warning] pdfplumber failed for {filename}: {err}")

        # 2. Fallback: pypdf if pdfplumber is unavailable or returned empty text
        if not extracted_text.strip() and pypdf:
            try:
                reader = pypdf.PdfReader(io.BytesIO(file_bytes))
                for page_num, page in enumerate(reader.pages, start=1):
                    text = page.extract_text()
                    if text:
                        extracted_text += f"\n--- Page {page_num} ---\n" + text
            except Exception as err:
                print(f"[DocumentParser Warning] pypdf failed for {filename}: {err}")

        return {
            "filename": filename,
            "file_type": "pdf",
            "extracted_text": extracted_text.strip(),
            "tables": tables_data,
            "has_content": bool(extracted_text.strip() or tables_data)
        }

    @staticmethod
    def extract_from_excel_bytes(file_bytes: bytes, filename: str = "") -> Dict[str, Any]:
        """Extracts sheet tables and converted text from Excel workbooks."""
        sheets_data = {}
        combined_text = ""

        if pd:
            try:
                excel_file = pd.ExcelFile(io.BytesIO(file_bytes))
                for sheet_name in excel_file.sheet_names:
                    df = pd.read_excel(excel_file, sheet_name=sheet_name)
                    # Fill NaNs for clean string representation
                    cleaned_df = df.fillna("")
                    records = cleaned_df.to_dict(orient="records")
                    sheets_data[sheet_name] = records
                    
                    # Convert to text block for extraction engine
                    combined_text += f"\n--- Sheet: {sheet_name} ---\n"
                    combined_text += cleaned_df.to_string(index=False)
            except Exception as err:
                print(f"[DocumentParser Error] Failed to read Excel file {filename}: {err}")

        return {
            "filename": filename,
            "file_type": "excel",
            "extracted_text": combined_text.strip(),
            "sheets": sheets_data,
            "has_content": bool(combined_text.strip())
        }

    @classmethod
    def parse_attachment(cls, file_bytes: bytes, filename: str) -> Dict[str, Any]:
        """Routes file processing based on extension."""
        lower_name = filename.lower()
        if lower_name.endswith(".pdf"):
            return cls.extract_from_pdf_bytes(file_bytes, filename)
        elif lower_name.endswith((".xlsx", ".xls", ".csv")):
            return cls.extract_from_excel_bytes(file_bytes, filename)
        else:
            return {
                "filename": filename,
                "file_type": "unsupported",
                "extracted_text": "",
                "has_content": False
            }