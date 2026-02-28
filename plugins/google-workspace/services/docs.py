"""Google Docs service."""

from pathlib import Path

import fitz
from googleapiclient.errors import HttpError

from .base import BaseGoogleService


class DocsService(BaseGoogleService):
    """Service for Google Docs operations."""

    def __init__(self, docs_service, drive_service, export_dir: Path):
        """Initialize Docs service.

        Args:
            docs_service: Google Docs API service
            drive_service: Google Drive API service (for export)
            export_dir: Directory for exported files
        """
        self.docs = docs_service
        self.drive = drive_service
        self.export_dir = export_dir
        self.export_dir.mkdir(parents=True, exist_ok=True)

    def create(self, title: str) -> dict:
        """Create a new Google Doc.

        Args:
            title: Document title

        Returns:
            Response with document ID and URL
        """
        try:
            doc = self.docs.documents().create(body={"title": title}).execute()
            return self._format_response(
                data={
                    "documentId": doc.get("documentId"),
                    "title": doc.get("title"),
                    "url": f"https://docs.google.com/document/d/{doc.get('documentId')}/edit",
                }
            )
        except HttpError as e:
            return self._format_error(self._handle_api_error(e))

    def read(self, document_id: str) -> dict:
        """Read document content.

        Args:
            document_id: Google Doc ID

        Returns:
            Response with document content
        """
        try:
            doc = self.docs.documents().get(documentId=document_id).execute()

            content = []
            for element in doc.get("body", {}).get("content", []):
                if "paragraph" in element:
                    for elem in element["paragraph"].get("elements", []):
                        if "textRun" in elem:
                            content.append(elem["textRun"].get("content", ""))

            return self._format_response(
                data={
                    "documentId": doc.get("documentId"),
                    "title": doc.get("title"),
                    "content": "".join(content),
                    "url": f"https://docs.google.com/document/d/{document_id}/edit",
                }
            )
        except HttpError as e:
            return self._format_error(self._handle_api_error(e))

    def update(self, document_id: str, content: str, position: int = None) -> dict:
        """Insert text into document.

        Args:
            document_id: Google Doc ID
            content: Text to insert
            position: Index position (default: end of document)

        Returns:
            Response with updated document info
        """
        try:
            if position is None:
                doc = self.docs.documents().get(documentId=document_id).execute()
                body_content = doc.get("body", {}).get("content", [])
                if body_content:
                    last_element = body_content[-1]
                    position = last_element.get("endIndex", 1) - 1
                else:
                    position = 1

            requests = [
                {
                    "insertText": {
                        "location": {"index": position},
                        "text": content,
                    }
                }
            ]

            self.docs.documents().batchUpdate(
                documentId=document_id, body={"requests": requests}
            ).execute()

            return self._format_response(
                data={
                    "documentId": document_id,
                    "inserted": len(content),
                    "position": position,
                    "url": f"https://docs.google.com/document/d/{document_id}/edit",
                }
            )
        except HttpError as e:
            return self._format_error(self._handle_api_error(e))

    def append(self, document_id: str, content: str) -> dict:
        """Append text to the end of document.

        Args:
            document_id: Google Doc ID
            content: Text to append

        Returns:
            Response with updated document info
        """
        try:
            doc = self.docs.documents().get(documentId=document_id).execute()
            body_content = doc.get("body", {}).get("content", [])

            # Find end position
            if body_content:
                last_element = body_content[-1]
                position = last_element.get("endIndex", 1) - 1
            else:
                position = 1

            requests = [
                {
                    "insertText": {
                        "location": {"index": position},
                        "text": content,
                    }
                }
            ]

            self.docs.documents().batchUpdate(
                documentId=document_id, body={"requests": requests}
            ).execute()

            return self._format_response(
                data={
                    "documentId": document_id,
                    "appended": len(content),
                    "url": f"https://docs.google.com/document/d/{document_id}/edit",
                }
            )
        except HttpError as e:
            return self._format_error(self._handle_api_error(e))

    def replace(self, document_id: str, find_text: str, replace_text: str) -> dict:
        """Find and replace text in document.

        Args:
            document_id: Google Doc ID
            find_text: Text to find
            replace_text: Text to replace with

        Returns:
            Response with replacement count
        """
        try:
            requests = [
                {
                    "replaceAllText": {
                        "containsText": {
                            "text": find_text,
                            "matchCase": True,
                        },
                        "replaceText": replace_text,
                    }
                }
            ]

            result = (
                self.docs.documents()
                .batchUpdate(documentId=document_id, body={"requests": requests})
                .execute()
            )

            # Get replacement count from response
            replies = result.get("replies", [{}])
            occurrences = (
                replies[0].get("replaceAllText", {}).get("occurrencesChanged", 0)
            )

            return self._format_response(
                data={
                    "documentId": document_id,
                    "find": find_text,
                    "replace": replace_text,
                    "occurrencesChanged": occurrences,
                    "url": f"https://docs.google.com/document/d/{document_id}/edit",
                }
            )
        except HttpError as e:
            return self._format_error(self._handle_api_error(e))

    def clear(self, document_id: str) -> dict:
        """Clear all content from document (keeps title).

        Args:
            document_id: Google Doc ID

        Returns:
            Response with cleared document info
        """
        try:
            # Get document to find content range
            doc = self.docs.documents().get(documentId=document_id).execute()
            body_content = doc.get("body", {}).get("content", [])

            if len(body_content) <= 1:
                # Document is already empty
                return self._format_response(
                    data={
                        "documentId": document_id,
                        "title": doc.get("title"),
                        "cleared": True,
                        "url": f"https://docs.google.com/document/d/{document_id}/edit",
                    }
                )

            # Find start and end of content (skip structural elements)
            start_index = 1
            end_index = body_content[-1].get("endIndex", 1) - 1

            if end_index > start_index:
                requests = [
                    {
                        "deleteContentRange": {
                            "range": {
                                "startIndex": start_index,
                                "endIndex": end_index,
                            }
                        }
                    }
                ]

                self.docs.documents().batchUpdate(
                    documentId=document_id, body={"requests": requests}
                ).execute()

            return self._format_response(
                data={
                    "documentId": document_id,
                    "title": doc.get("title"),
                    "cleared": True,
                    "url": f"https://docs.google.com/document/d/{document_id}/edit",
                }
            )
        except HttpError as e:
            return self._format_error(self._handle_api_error(e))

    def read_tables(self, document_id: str) -> dict:
        """Read all tables from document with their structure.

        Args:
            document_id: Google Doc ID

        Returns:
            Response with list of tables, each containing rows and cells
        """
        try:
            doc = self.docs.documents().get(documentId=document_id).execute()
            tables = []
            table_index = 0

            for element in doc.get("body", {}).get("content", []):
                if "table" in element:
                    table_data = self._extract_table(element, table_index)
                    tables.append(table_data)
                    table_index += 1

            return self._format_response(
                data={
                    "documentId": document_id,
                    "title": doc.get("title"),
                    "tables": tables,
                    "tableCount": len(tables),
                    "url": f"https://docs.google.com/document/d/{document_id}/edit",
                }
            )
        except HttpError as e:
            return self._format_error(self._handle_api_error(e))

    def _extract_table(self, table_element: dict, table_index: int) -> dict:
        """Extract table structure and content from a table element.

        Args:
            table_element: The table element from document body
            table_index: Index of the table in the document

        Returns:
            Dict with table structure including rows and cells
        """
        table = table_element.get("table", {})
        start_index = table_element.get("startIndex")
        end_index = table_element.get("endIndex")

        rows = []
        for row_idx, row in enumerate(table.get("tableRows", [])):
            cells = []
            for col_idx, cell in enumerate(row.get("tableCells", [])):
                cell_content = self._extract_cell_content(cell)
                cells.append(
                    {
                        "row": row_idx,
                        "column": col_idx,
                        "content": cell_content["text"],
                        "startIndex": cell_content["startIndex"],
                        "endIndex": cell_content["endIndex"],
                    }
                )
            rows.append(cells)

        return {
            "tableIndex": table_index,
            "startIndex": start_index,
            "endIndex": end_index,
            "rows": len(rows),
            "columns": len(rows[0]) if rows else 0,
            "data": rows,
        }

    def _extract_cell_content(self, cell: dict) -> dict:
        """Extract text content and indices from a table cell.

        Args:
            cell: Table cell element

        Returns:
            Dict with text content and position indices
        """
        text_parts = []
        start_index = None
        end_index = None

        for content_elem in cell.get("content", []):
            if "paragraph" in content_elem:
                para = content_elem["paragraph"]
                for elem in para.get("elements", []):
                    if start_index is None:
                        start_index = elem.get("startIndex")
                    end_index = elem.get("endIndex")
                    if "textRun" in elem:
                        text_parts.append(elem["textRun"].get("content", ""))

        return {
            "text": "".join(text_parts).strip(),
            "startIndex": start_index,
            "endIndex": end_index,
        }

    def update_table_cell(
        self, document_id: str, table_index: int, row: int, column: int, content: str
    ) -> dict:
        """Update content of a specific table cell.

        Args:
            document_id: Google Doc ID
            table_index: Index of the table (0-based)
            row: Row index (0-based)
            column: Column index (0-based)
            content: New text content for the cell

        Returns:
            Response with update confirmation
        """
        try:
            doc = self.docs.documents().get(documentId=document_id).execute()

            current_table = 0
            target_cell = None

            for element in doc.get("body", {}).get("content", []):
                if "table" in element:
                    if current_table == table_index:
                        table = element.get("table", {})
                        table_rows = table.get("tableRows", [])
                        if row < len(table_rows):
                            cells = table_rows[row].get("tableCells", [])
                            if column < len(cells):
                                target_cell = self._extract_cell_content(cells[column])
                        break
                    current_table += 1

            if target_cell is None:
                return self._format_error(
                    f"Cell not found: table {table_index}, row {row}, column {column}"
                )

            requests = []

            if target_cell["startIndex"] and target_cell["endIndex"]:
                if target_cell["endIndex"] > target_cell["startIndex"]:
                    requests.append(
                        {
                            "deleteContentRange": {
                                "range": {
                                    "startIndex": target_cell["startIndex"],
                                    "endIndex": target_cell["endIndex"] - 1,
                                }
                            }
                        }
                    )

            if content:
                insert_index = target_cell["startIndex"] or 1
                requests.append(
                    {
                        "insertText": {
                            "location": {"index": insert_index},
                            "text": content,
                        }
                    }
                )

            if requests:
                self.docs.documents().batchUpdate(
                    documentId=document_id, body={"requests": requests}
                ).execute()

            return self._format_response(
                data={
                    "documentId": document_id,
                    "tableIndex": table_index,
                    "row": row,
                    "column": column,
                    "newContent": content,
                    "url": f"https://docs.google.com/document/d/{document_id}/edit",
                }
            )
        except HttpError as e:
            return self._format_error(self._handle_api_error(e))

    def find_table_by_text(self, document_id: str, search_text: str) -> dict:
        """Find a table that appears after a specific text/heading.

        Args:
            document_id: Google Doc ID
            search_text: Text to search for (table should be after this text)

        Returns:
            Response with table data if found
        """
        try:
            doc = self.docs.documents().get(documentId=document_id).execute()

            search_text_lower = search_text.lower()
            found_text = False
            table_index = 0

            for element in doc.get("body", {}).get("content", []):
                if "paragraph" in element:
                    para_text = ""
                    for elem in element["paragraph"].get("elements", []):
                        if "textRun" in elem:
                            para_text += elem["textRun"].get("content", "")

                    if search_text_lower in para_text.lower():
                        found_text = True

                elif "table" in element:
                    if found_text:
                        table_data = self._extract_table(element, table_index)
                        return self._format_response(
                            data={
                                "documentId": document_id,
                                "searchText": search_text,
                                "table": table_data,
                                "url": f"https://docs.google.com/document/d/{document_id}/edit",
                            }
                        )
                    table_index += 1

            if not found_text:
                return self._format_error(f"Text '{search_text}' not found in document")

            return self._format_error(f"No table found after '{search_text}'")
        except HttpError as e:
            return self._format_error(self._handle_api_error(e))

    def update_table_row(
        self, document_id: str, table_index: int, row: int, values: list
    ) -> dict:
        """Update an entire row in a table.

        Args:
            document_id: Google Doc ID
            table_index: Index of the table (0-based)
            row: Row index (0-based)
            values: List of values for each cell in the row

        Returns:
            Response with update confirmation
        """
        try:
            doc = self.docs.documents().get(documentId=document_id).execute()

            current_table = 0
            target_row_cells = None

            for element in doc.get("body", {}).get("content", []):
                if "table" in element:
                    if current_table == table_index:
                        table = element.get("table", {})
                        table_rows = table.get("tableRows", [])
                        if row < len(table_rows):
                            cells = table_rows[row].get("tableCells", [])
                            target_row_cells = [
                                self._extract_cell_content(cell) for cell in cells
                            ]
                        break
                    current_table += 1

            if target_row_cells is None:
                return self._format_error(
                    f"Row not found: table {table_index}, row {row}"
                )

            requests = []
            for col_idx in range(min(len(values), len(target_row_cells)) - 1, -1, -1):
                cell = target_row_cells[col_idx]
                new_value = str(values[col_idx]) if values[col_idx] is not None else ""

                if cell["startIndex"] and cell["endIndex"]:
                    if cell["endIndex"] > cell["startIndex"]:
                        requests.append(
                            {
                                "deleteContentRange": {
                                    "range": {
                                        "startIndex": cell["startIndex"],
                                        "endIndex": cell["endIndex"] - 1,
                                    }
                                }
                            }
                        )

                if new_value:
                    requests.append(
                        {
                            "insertText": {
                                "location": {"index": cell["startIndex"]},
                                "text": new_value,
                            }
                        }
                    )

            if requests:
                self.docs.documents().batchUpdate(
                    documentId=document_id, body={"requests": requests}
                ).execute()

            return self._format_response(
                data={
                    "documentId": document_id,
                    "tableIndex": table_index,
                    "row": row,
                    "updatedCells": min(len(values), len(target_row_cells)),
                    "url": f"https://docs.google.com/document/d/{document_id}/edit",
                }
            )
        except HttpError as e:
            return self._format_error(self._handle_api_error(e))

    def export(self, document_id: str, format: str = "pdf") -> dict:
        """Export document to file.

        Args:
            document_id: Google Doc ID
            format: Export format (pdf, docx)

        Returns:
            Response with exported file path
        """
        mime_types = {
            "pdf": "application/pdf",
            "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        }

        if format.lower() not in mime_types:
            return self._format_response(
                success=False,
                error=f"Unsupported format: {format}. Use 'pdf' or 'docx'.",
            )

        try:
            doc = self.docs.documents().get(documentId=document_id).execute()
            title = doc.get("title", document_id)

            content = (
                self.drive.files()
                .export(fileId=document_id, mimeType=mime_types[format.lower()])
                .execute()
            )

            safe_title = "".join(c for c in title if c.isalnum() or c in " -_")[:50]
            filename = f"{safe_title}.{format.lower()}"
            filepath = self.export_dir / filename

            filepath.write_bytes(content)

            return self._format_response(
                data={
                    "documentId": document_id,
                    "title": title,
                    "path": str(filepath),
                    "format": format.lower(),
                    "size": len(content),
                }
            )
        except HttpError as e:
            return self._format_error(self._handle_api_error(e))

    def export_as_image(
        self, document_id: str, page: int = None, dpi: int = 150
    ) -> dict:
        """Export document as PNG image(s).

        Args:
            document_id: Google Doc ID
            page: Specific page to export (1-based), None for all pages
            dpi: Image resolution (default 150)

        Returns:
            Response with image file path(s)
        """
        try:
            doc = self.docs.documents().get(documentId=document_id).execute()
            title = doc.get("title", document_id)

            pdf_content = (
                self.drive.files()
                .export(fileId=document_id, mimeType="application/pdf")
                .execute()
            )

            safe_title = "".join(c for c in title if c.isalnum() or c in " -_")[:50]

            pdf_doc = fitz.open(stream=pdf_content, filetype="pdf")
            zoom = dpi / 72
            matrix = fitz.Matrix(zoom, zoom)

            image_paths = []

            if page is not None:
                page_idx = page - 1
                if page_idx < 0 or page_idx >= len(pdf_doc):
                    return self._format_error(
                        f"Page {page} not found. Document has {len(pdf_doc)} pages."
                    )
                pages_to_export = [page_idx]
            else:
                pages_to_export = range(len(pdf_doc))

            for page_idx in pages_to_export:
                pix = pdf_doc[page_idx].get_pixmap(matrix=matrix)

                if len(pdf_doc) == 1 and page is None:
                    filename = f"{safe_title}.png"
                else:
                    filename = f"{safe_title}_page{page_idx + 1}.png"

                filepath = self.export_dir / filename
                pix.save(str(filepath))
                image_paths.append(str(filepath))

            pdf_doc.close()

            return self._format_response(
                data={
                    "documentId": document_id,
                    "title": title,
                    "images": image_paths,
                    "pageCount": len(image_paths),
                    "dpi": dpi,
                    "url": f"https://docs.google.com/document/d/{document_id}/edit",
                }
            )
        except HttpError as e:
            return self._format_error(self._handle_api_error(e))
        except Exception as e:
            return self._format_error(f"Image conversion failed: {str(e)}")

    def _parse_color(self, color_str: str) -> dict | None:
        """Parse color string to Google Docs API format.

        Supports:
            - Hex: "#FF5733" or "FF5733"
            - RGB: "rgb(255, 87, 51)"
            - Named colors: "red", "blue", "black", "orange", etc.

        Returns:
            Color dict for Google Docs API or None if invalid
        """
        if not color_str:
            return None

        color_str = color_str.strip().lower()

        # Named colors
        named_colors = {
            "black": (0, 0, 0),
            "white": (255, 255, 255),
            "red": (255, 0, 0),
            "green": (0, 128, 0),
            "blue": (0, 0, 255),
            "yellow": (255, 255, 0),
            "orange": (255, 165, 0),
            "purple": (128, 0, 128),
            "pink": (255, 192, 203),
            "gray": (128, 128, 128),
            "grey": (128, 128, 128),
            "brown": (165, 42, 42),
            "cyan": (0, 255, 255),
            "magenta": (255, 0, 255),
        }

        if color_str in named_colors:
            r, g, b = named_colors[color_str]
            return {
                "color": {
                    "rgbColor": {
                        "red": r / 255.0,
                        "green": g / 255.0,
                        "blue": b / 255.0,
                    }
                }
            }

        # Hex format
        if color_str.startswith("#"):
            color_str = color_str[1:]
        if len(color_str) == 6:
            try:
                r = int(color_str[0:2], 16)
                g = int(color_str[2:4], 16)
                b = int(color_str[4:6], 16)
                return {
                    "color": {
                        "rgbColor": {
                            "red": r / 255.0,
                            "green": g / 255.0,
                            "blue": b / 255.0,
                        }
                    }
                }
            except ValueError:
                pass

        # RGB format: rgb(255, 87, 51)
        if color_str.startswith("rgb(") and color_str.endswith(")"):
            try:
                values = color_str[4:-1].split(",")
                r, g, b = [int(v.strip()) for v in values]
                return {
                    "color": {
                        "rgbColor": {
                            "red": r / 255.0,
                            "green": g / 255.0,
                            "blue": b / 255.0,
                        }
                    }
                }
            except (ValueError, IndexError):
                pass

        return None

    def update_text_style(
        self,
        document_id: str,
        start_index: int,
        end_index: int,
        bold: bool = None,
        italic: bool = None,
        underline: bool = None,
        strikethrough: bool = None,
        font_size: int = None,
        foreground_color: str = None,
        background_color: str = None,
    ) -> dict:
        """Update text formatting style in a range.

        Args:
            document_id: Google Doc ID
            start_index: Start character index
            end_index: End character index
            bold: Set bold (True/False/None to not change)
            italic: Set italic (True/False/None to not change)
            underline: Set underline (True/False/None to not change)
            strikethrough: Set strikethrough (True/False/None to not change)
            font_size: Font size in points (None to not change)
            foreground_color: Text color (hex "#FF5733", rgb "rgb(255,87,51)", or name "red")
            background_color: Text background/highlight color (same formats)

        Returns:
            Response with update confirmation
        """
        try:
            text_style = {}
            fields = []

            if bold is not None:
                text_style["bold"] = bold
                fields.append("bold")
            if italic is not None:
                text_style["italic"] = italic
                fields.append("italic")
            if underline is not None:
                text_style["underline"] = underline
                fields.append("underline")
            if strikethrough is not None:
                text_style["strikethrough"] = strikethrough
                fields.append("strikethrough")
            if font_size is not None:
                text_style["fontSize"] = {"magnitude": font_size, "unit": "PT"}
                fields.append("fontSize")
            if foreground_color is not None:
                color = self._parse_color(foreground_color)
                if color:
                    text_style["foregroundColor"] = color
                    fields.append("foregroundColor")
                else:
                    return self._format_error(
                        f"Invalid foreground_color format: {foreground_color}. "
                        "Use hex (#FF5733), rgb(255,87,51), or name (red, blue, black, etc.)"
                    )
            if background_color is not None:
                color = self._parse_color(background_color)
                if color:
                    text_style["backgroundColor"] = color
                    fields.append("backgroundColor")
                else:
                    return self._format_error(
                        f"Invalid background_color format: {background_color}. "
                        "Use hex (#FF5733), rgb(255,87,51), or name (red, blue, black, etc.)"
                    )

            if not fields:
                return self._format_error("No style properties specified")

            requests = [
                {
                    "updateTextStyle": {
                        "range": {
                            "startIndex": start_index,
                            "endIndex": end_index,
                        },
                        "textStyle": text_style,
                        "fields": ",".join(fields),
                    }
                }
            ]

            self.docs.documents().batchUpdate(
                documentId=document_id, body={"requests": requests}
            ).execute()

            return self._format_response(
                data={
                    "documentId": document_id,
                    "startIndex": start_index,
                    "endIndex": end_index,
                    "updatedStyles": fields,
                    "url": f"https://docs.google.com/document/d/{document_id}/edit",
                }
            )
        except HttpError as e:
            return self._format_error(self._handle_api_error(e))

    def delete_table(self, document_id: str, table_index: int) -> dict:
        """Delete an entire table from the document.

        Args:
            document_id: Google Doc ID
            table_index: Index of the table to delete (0-based)

        Returns:
            Response with deletion confirmation
        """
        try:
            table_index = int(table_index)
            doc = self.docs.documents().get(documentId=document_id).execute()

            tables_found = []
            target_table = None

            for element in doc.get("body", {}).get("content", []):
                if "table" in element:
                    tables_found.append(element)

            total_tables = len(tables_found)

            if table_index < 0 or table_index >= total_tables:
                return self._format_error(
                    f"Table index {table_index} out of range. "
                    f"Document has {total_tables} table(s) (valid indices: 0-{total_tables - 1}). "
                    f"Note: indices shift after each deletion."
                )

            target_table = tables_found[table_index]

            start_index = target_table.get("startIndex")
            end_index = target_table.get("endIndex")

            if start_index is None or end_index is None:
                return self._format_error("Could not determine table boundaries")

            requests = [
                {
                    "deleteContentRange": {
                        "range": {
                            "startIndex": start_index,
                            "endIndex": end_index,
                        }
                    }
                }
            ]

            self.docs.documents().batchUpdate(
                documentId=document_id, body={"requests": requests}
            ).execute()

            return self._format_response(
                data={
                    "documentId": document_id,
                    "deletedTableIndex": table_index,
                    "deletedRange": {"start": start_index, "end": end_index},
                    "url": f"https://docs.google.com/document/d/{document_id}/edit",
                }
            )
        except HttpError as e:
            return self._format_error(self._handle_api_error(e))
        except Exception as e:
            return self._format_error(f"Unexpected error: {str(e)}")

    def update_table_cell_style(
        self,
        document_id: str,
        table_index: int,
        row: int,
        column: int,
        bold: bool = None,
        italic: bool = None,
        underline: bool = None,
        strikethrough: bool = None,
        font_size: int = None,
    ) -> dict:
        """Update text formatting in a table cell.

        Args:
            document_id: Google Doc ID
            table_index: Index of the table (0-based)
            row: Row index (0-based)
            column: Column index (0-based)
            bold: Set bold (True/False/None to not change)
            italic: Set italic (True/False/None to not change)
            underline: Set underline (True/False/None to not change)
            strikethrough: Set strikethrough (True/False/None to not change)
            font_size: Font size in points (None to not change)

        Returns:
            Response with update confirmation
        """
        try:
            doc = self.docs.documents().get(documentId=document_id).execute()

            current_table = 0
            target_cell = None

            for element in doc.get("body", {}).get("content", []):
                if "table" in element:
                    if current_table == table_index:
                        table = element.get("table", {})
                        table_rows = table.get("tableRows", [])
                        if row < len(table_rows):
                            cells = table_rows[row].get("tableCells", [])
                            if column < len(cells):
                                target_cell = self._extract_cell_content(cells[column])
                        break
                    current_table += 1

            if target_cell is None:
                return self._format_error(
                    f"Cell not found: table {table_index}, row {row}, column {column}"
                )

            if not target_cell["startIndex"] or not target_cell["endIndex"]:
                return self._format_error("Cell has no content to style")

            return self.update_text_style(
                document_id,
                target_cell["startIndex"],
                target_cell["endIndex"] - 1,
                bold=bold,
                italic=italic,
                underline=underline,
                strikethrough=strikethrough,
                font_size=font_size,
            )
        except HttpError as e:
            return self._format_error(self._handle_api_error(e))

    def insert_table_of_contents(self, document_id: str, position: int = None) -> dict:
        """Insert a table of contents based on document headings.

        Args:
            document_id: Google Doc ID
            position: Index position (default: beginning of document)

        Returns:
            Response with insertion confirmation
        """
        try:
            if position is None:
                position = 1

            requests = [
                {
                    "insertTableOfContents": {
                        "location": {"index": position},
                    }
                }
            ]

            self.docs.documents().batchUpdate(
                documentId=document_id, body={"requests": requests}
            ).execute()

            return self._format_response(
                data={
                    "documentId": document_id,
                    "position": position,
                    "note": "TOC created based on document headings (H1-H6)",
                    "url": f"https://docs.google.com/document/d/{document_id}/edit",
                }
            )
        except HttpError as e:
            return self._format_error(self._handle_api_error(e))

    def insert_table(
        self, document_id: str, rows: int, columns: int, position: int = None
    ) -> dict:
        """Insert a new table into the document.

        Args:
            document_id: Google Doc ID
            rows: Number of rows
            columns: Number of columns
            position: Index position (default: end of document)

        Returns:
            Response with table info
        """
        try:
            if position is None:
                doc = self.docs.documents().get(documentId=document_id).execute()
                body_content = doc.get("body", {}).get("content", [])
                if body_content:
                    position = body_content[-1].get("endIndex", 1) - 1
                else:
                    position = 1

            requests = [
                {
                    "insertTable": {
                        "rows": rows,
                        "columns": columns,
                        "location": {"index": position},
                    }
                }
            ]

            self.docs.documents().batchUpdate(
                documentId=document_id, body={"requests": requests}
            ).execute()

            return self._format_response(
                data={
                    "documentId": document_id,
                    "rows": rows,
                    "columns": columns,
                    "position": position,
                    "url": f"https://docs.google.com/document/d/{document_id}/edit",
                }
            )
        except HttpError as e:
            return self._format_error(self._handle_api_error(e))

    def insert_table_row(
        self,
        document_id: str,
        table_index: int,
        row_index: int,
        insert_below: bool = True,
    ) -> dict:
        """Insert a new row in a table.

        Args:
            document_id: Google Doc ID
            table_index: Index of the table (0-based)
            row_index: Row index to insert at (0-based)
            insert_below: If True, insert below row_index; if False, insert above

        Returns:
            Response with confirmation
        """
        try:
            doc = self.docs.documents().get(documentId=document_id).execute()

            current_table = 0
            target_table = None
            table_start = None

            for element in doc.get("body", {}).get("content", []):
                if "table" in element:
                    if current_table == table_index:
                        target_table = element.get("table", {})
                        table_start = element.get("startIndex")
                        break
                    current_table += 1

            if target_table is None:
                return self._format_error(f"Table {table_index} not found")

            requests = [
                {
                    "insertTableRow": {
                        "tableCellLocation": {
                            "tableStartLocation": {"index": table_start},
                            "rowIndex": row_index,
                            "columnIndex": 0,
                        },
                        "insertBelow": insert_below,
                    }
                }
            ]

            self.docs.documents().batchUpdate(
                documentId=document_id, body={"requests": requests}
            ).execute()

            return self._format_response(
                data={
                    "documentId": document_id,
                    "tableIndex": table_index,
                    "rowIndex": row_index,
                    "insertedBelow": insert_below,
                    "url": f"https://docs.google.com/document/d/{document_id}/edit",
                }
            )
        except HttpError as e:
            return self._format_error(self._handle_api_error(e))

    def insert_table_column(
        self,
        document_id: str,
        table_index: int,
        column_index: int,
        insert_right: bool = True,
    ) -> dict:
        """Insert a new column in a table.

        Args:
            document_id: Google Doc ID
            table_index: Index of the table (0-based)
            column_index: Column index to insert at (0-based)
            insert_right: If True, insert to the right; if False, insert to the left

        Returns:
            Response with confirmation
        """
        try:
            doc = self.docs.documents().get(documentId=document_id).execute()

            current_table = 0
            table_start = None

            for element in doc.get("body", {}).get("content", []):
                if "table" in element:
                    if current_table == table_index:
                        table_start = element.get("startIndex")
                        break
                    current_table += 1

            if table_start is None:
                return self._format_error(f"Table {table_index} not found")

            requests = [
                {
                    "insertTableColumn": {
                        "tableCellLocation": {
                            "tableStartLocation": {"index": table_start},
                            "rowIndex": 0,
                            "columnIndex": column_index,
                        },
                        "insertRight": insert_right,
                    }
                }
            ]

            self.docs.documents().batchUpdate(
                documentId=document_id, body={"requests": requests}
            ).execute()

            return self._format_response(
                data={
                    "documentId": document_id,
                    "tableIndex": table_index,
                    "columnIndex": column_index,
                    "insertedRight": insert_right,
                    "url": f"https://docs.google.com/document/d/{document_id}/edit",
                }
            )
        except HttpError as e:
            return self._format_error(self._handle_api_error(e))

    def delete_table_row(
        self, document_id: str, table_index: int, row_index: int
    ) -> dict:
        """Delete a row from a table.

        Args:
            document_id: Google Doc ID
            table_index: Index of the table (0-based)
            row_index: Row index to delete (0-based)

        Returns:
            Response with confirmation
        """
        try:
            doc = self.docs.documents().get(documentId=document_id).execute()

            current_table = 0
            table_start = None

            for element in doc.get("body", {}).get("content", []):
                if "table" in element:
                    if current_table == table_index:
                        table_start = element.get("startIndex")
                        break
                    current_table += 1

            if table_start is None:
                return self._format_error(f"Table {table_index} not found")

            requests = [
                {
                    "deleteTableRow": {
                        "tableCellLocation": {
                            "tableStartLocation": {"index": table_start},
                            "rowIndex": row_index,
                            "columnIndex": 0,
                        },
                    }
                }
            ]

            self.docs.documents().batchUpdate(
                documentId=document_id, body={"requests": requests}
            ).execute()

            return self._format_response(
                data={
                    "documentId": document_id,
                    "tableIndex": table_index,
                    "deletedRowIndex": row_index,
                    "url": f"https://docs.google.com/document/d/{document_id}/edit",
                }
            )
        except HttpError as e:
            return self._format_error(self._handle_api_error(e))

    def delete_table_column(
        self, document_id: str, table_index: int, column_index: int
    ) -> dict:
        """Delete a column from a table.

        Args:
            document_id: Google Doc ID
            table_index: Index of the table (0-based)
            column_index: Column index to delete (0-based)

        Returns:
            Response with confirmation
        """
        try:
            doc = self.docs.documents().get(documentId=document_id).execute()

            current_table = 0
            table_start = None

            for element in doc.get("body", {}).get("content", []):
                if "table" in element:
                    if current_table == table_index:
                        table_start = element.get("startIndex")
                        break
                    current_table += 1

            if table_start is None:
                return self._format_error(f"Table {table_index} not found")

            requests = [
                {
                    "deleteTableColumn": {
                        "tableCellLocation": {
                            "tableStartLocation": {"index": table_start},
                            "rowIndex": 0,
                            "columnIndex": column_index,
                        },
                    }
                }
            ]

            self.docs.documents().batchUpdate(
                documentId=document_id, body={"requests": requests}
            ).execute()

            return self._format_response(
                data={
                    "documentId": document_id,
                    "tableIndex": table_index,
                    "deletedColumnIndex": column_index,
                    "url": f"https://docs.google.com/document/d/{document_id}/edit",
                }
            )
        except HttpError as e:
            return self._format_error(self._handle_api_error(e))

    def insert_image(
        self,
        document_id: str,
        image_url: str,
        position: int = None,
        width: float = None,
        height: float = None,
    ) -> dict:
        """Insert an image from URL into the document.

        Args:
            document_id: Google Doc ID
            image_url: Public URL of the image
            position: Index position (default: end of document)
            width: Image width in points (optional)
            height: Image height in points (optional)

        Returns:
            Response with confirmation
        """
        try:
            if position is None:
                doc = self.docs.documents().get(documentId=document_id).execute()
                body_content = doc.get("body", {}).get("content", [])
                if body_content:
                    position = body_content[-1].get("endIndex", 1) - 1
                else:
                    position = 1

            inline_object = {
                "location": {"index": position},
                "uri": image_url,
            }

            if width and height:
                inline_object["objectSize"] = {
                    "width": {"magnitude": width, "unit": "PT"},
                    "height": {"magnitude": height, "unit": "PT"},
                }

            requests = [{"insertInlineImage": inline_object}]

            self.docs.documents().batchUpdate(
                documentId=document_id, body={"requests": requests}
            ).execute()

            return self._format_response(
                data={
                    "documentId": document_id,
                    "imageUrl": image_url,
                    "position": position,
                    "url": f"https://docs.google.com/document/d/{document_id}/edit",
                }
            )
        except HttpError as e:
            return self._format_error(self._handle_api_error(e))

    def update_paragraph_style(
        self,
        document_id: str,
        start_index: int,
        end_index: int,
        heading: str = None,
        alignment: str = None,
        line_spacing: float = None,
        space_above: float = None,
        space_below: float = None,
    ) -> dict:
        """Update paragraph formatting.

        Args:
            document_id: Google Doc ID
            start_index: Start character index
            end_index: End character index
            heading: Heading style (NORMAL, HEADING_1 to HEADING_6, TITLE, SUBTITLE)
            alignment: Text alignment (START, CENTER, END, JUSTIFIED)
            line_spacing: Line spacing multiplier (e.g., 1.5 for 1.5x)
            space_above: Space above paragraph in points
            space_below: Space below paragraph in points

        Returns:
            Response with confirmation
        """
        try:
            paragraph_style = {}
            fields = []

            if heading is not None:
                paragraph_style["namedStyleType"] = heading.upper()
                fields.append("namedStyleType")
            if alignment is not None:
                paragraph_style["alignment"] = alignment.upper()
                fields.append("alignment")
            if line_spacing is not None:
                paragraph_style["lineSpacing"] = line_spacing * 100
                fields.append("lineSpacing")
            if space_above is not None:
                paragraph_style["spaceAbove"] = {"magnitude": space_above, "unit": "PT"}
                fields.append("spaceAbove")
            if space_below is not None:
                paragraph_style["spaceBelow"] = {"magnitude": space_below, "unit": "PT"}
                fields.append("spaceBelow")

            if not fields:
                return self._format_error("No paragraph style properties specified")

            requests = [
                {
                    "updateParagraphStyle": {
                        "range": {
                            "startIndex": start_index,
                            "endIndex": end_index,
                        },
                        "paragraphStyle": paragraph_style,
                        "fields": ",".join(fields),
                    }
                }
            ]

            self.docs.documents().batchUpdate(
                documentId=document_id, body={"requests": requests}
            ).execute()

            return self._format_response(
                data={
                    "documentId": document_id,
                    "startIndex": start_index,
                    "endIndex": end_index,
                    "updatedStyles": fields,
                    "url": f"https://docs.google.com/document/d/{document_id}/edit",
                }
            )
        except HttpError as e:
            return self._format_error(self._handle_api_error(e))

    def create_bullets(
        self,
        document_id: str,
        start_index: int,
        end_index: int,
        bullet_type: str = "BULLET_DISC_CIRCLE_SQUARE",
    ) -> dict:
        """Create a bulleted or numbered list.

        Args:
            document_id: Google Doc ID
            start_index: Start character index
            end_index: End character index
            bullet_type: Bullet preset (BULLET_DISC_CIRCLE_SQUARE, NUMBERED_DECIMAL_NESTED,
                        NUMBERED_DECIMAL_ALPHA_ROMAN, etc.)

        Returns:
            Response with confirmation
        """
        try:
            requests = [
                {
                    "createParagraphBullets": {
                        "range": {
                            "startIndex": start_index,
                            "endIndex": end_index,
                        },
                        "bulletPreset": bullet_type,
                    }
                }
            ]

            self.docs.documents().batchUpdate(
                documentId=document_id, body={"requests": requests}
            ).execute()

            return self._format_response(
                data={
                    "documentId": document_id,
                    "startIndex": start_index,
                    "endIndex": end_index,
                    "bulletType": bullet_type,
                    "url": f"https://docs.google.com/document/d/{document_id}/edit",
                }
            )
        except HttpError as e:
            return self._format_error(self._handle_api_error(e))

    def delete_bullets(
        self, document_id: str, start_index: int, end_index: int
    ) -> dict:
        """Remove bullets from a list.

        Args:
            document_id: Google Doc ID
            start_index: Start character index
            end_index: End character index

        Returns:
            Response with confirmation
        """
        try:
            requests = [
                {
                    "deleteParagraphBullets": {
                        "range": {
                            "startIndex": start_index,
                            "endIndex": end_index,
                        },
                    }
                }
            ]

            self.docs.documents().batchUpdate(
                documentId=document_id, body={"requests": requests}
            ).execute()

            return self._format_response(
                data={
                    "documentId": document_id,
                    "startIndex": start_index,
                    "endIndex": end_index,
                    "url": f"https://docs.google.com/document/d/{document_id}/edit",
                }
            )
        except HttpError as e:
            return self._format_error(self._handle_api_error(e))

    def insert_page_break(self, document_id: str, position: int = None) -> dict:
        """Insert a page break.

        Args:
            document_id: Google Doc ID
            position: Index position (default: end of document)

        Returns:
            Response with confirmation
        """
        try:
            if position is None:
                doc = self.docs.documents().get(documentId=document_id).execute()
                body_content = doc.get("body", {}).get("content", [])
                if body_content:
                    position = body_content[-1].get("endIndex", 1) - 1
                else:
                    position = 1

            requests = [
                {
                    "insertPageBreak": {
                        "location": {"index": position},
                    }
                }
            ]

            self.docs.documents().batchUpdate(
                documentId=document_id, body={"requests": requests}
            ).execute()

            return self._format_response(
                data={
                    "documentId": document_id,
                    "position": position,
                    "url": f"https://docs.google.com/document/d/{document_id}/edit",
                }
            )
        except HttpError as e:
            return self._format_error(self._handle_api_error(e))

    def create_header(self, document_id: str, content: str = "") -> dict:
        """Create or update document header.

        Args:
            document_id: Google Doc ID
            content: Text content for the header

        Returns:
            Response with header info
        """
        try:
            requests = [
                {
                    "createHeader": {
                        "type": "DEFAULT",
                        "sectionBreakLocation": {"index": 0},
                    }
                }
            ]

            result = (
                self.docs.documents()
                .batchUpdate(documentId=document_id, body={"requests": requests})
                .execute()
            )

            header_id = (
                result.get("replies", [{}])[0].get("createHeader", {}).get("headerId")
            )

            if content and header_id:
                requests = [
                    {
                        "insertText": {
                            "location": {"segmentId": header_id, "index": 0},
                            "text": content,
                        }
                    }
                ]
                self.docs.documents().batchUpdate(
                    documentId=document_id, body={"requests": requests}
                ).execute()

            return self._format_response(
                data={
                    "documentId": document_id,
                    "headerId": header_id,
                    "content": content,
                    "url": f"https://docs.google.com/document/d/{document_id}/edit",
                }
            )
        except HttpError as e:
            return self._format_error(self._handle_api_error(e))

    def create_footer(self, document_id: str, content: str = "") -> dict:
        """Create or update document footer.

        Args:
            document_id: Google Doc ID
            content: Text content for the footer

        Returns:
            Response with footer info
        """
        try:
            requests = [
                {
                    "createFooter": {
                        "type": "DEFAULT",
                        "sectionBreakLocation": {"index": 0},
                    }
                }
            ]

            result = (
                self.docs.documents()
                .batchUpdate(documentId=document_id, body={"requests": requests})
                .execute()
            )

            footer_id = (
                result.get("replies", [{}])[0].get("createFooter", {}).get("footerId")
            )

            if content and footer_id:
                requests = [
                    {
                        "insertText": {
                            "location": {"segmentId": footer_id, "index": 0},
                            "text": content,
                        }
                    }
                ]
                self.docs.documents().batchUpdate(
                    documentId=document_id, body={"requests": requests}
                ).execute()

            return self._format_response(
                data={
                    "documentId": document_id,
                    "footerId": footer_id,
                    "content": content,
                    "url": f"https://docs.google.com/document/d/{document_id}/edit",
                }
            )
        except HttpError as e:
            return self._format_error(self._handle_api_error(e))

    def insert_link(
        self, document_id: str, start_index: int, end_index: int, url: str
    ) -> dict:
        """Add a hyperlink to existing text.

        Args:
            document_id: Google Doc ID
            start_index: Start character index of text to link
            end_index: End character index of text to link
            url: URL for the hyperlink

        Returns:
            Response with confirmation
        """
        try:
            requests = [
                {
                    "updateTextStyle": {
                        "range": {
                            "startIndex": start_index,
                            "endIndex": end_index,
                        },
                        "textStyle": {"link": {"url": url}},
                        "fields": "link",
                    }
                }
            ]

            self.docs.documents().batchUpdate(
                documentId=document_id, body={"requests": requests}
            ).execute()

            return self._format_response(
                data={
                    "documentId": document_id,
                    "startIndex": start_index,
                    "endIndex": end_index,
                    "linkedUrl": url,
                    "url": f"https://docs.google.com/document/d/{document_id}/edit",
                }
            )
        except HttpError as e:
            return self._format_error(self._handle_api_error(e))

    def remove_link(self, document_id: str, start_index: int, end_index: int) -> dict:
        """Remove hyperlink from text (keep text, remove link).

        Args:
            document_id: Google Doc ID
            start_index: Start character index
            end_index: End character index

        Returns:
            Response with confirmation
        """
        try:
            requests = [
                {
                    "updateTextStyle": {
                        "range": {
                            "startIndex": start_index,
                            "endIndex": end_index,
                        },
                        "textStyle": {},
                        "fields": "link",
                    }
                }
            ]

            self.docs.documents().batchUpdate(
                documentId=document_id, body={"requests": requests}
            ).execute()

            return self._format_response(
                data={
                    "documentId": document_id,
                    "startIndex": start_index,
                    "endIndex": end_index,
                    "linkRemoved": True,
                    "url": f"https://docs.google.com/document/d/{document_id}/edit",
                }
            )
        except HttpError as e:
            return self._format_error(self._handle_api_error(e))
