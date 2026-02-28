#!/usr/bin/env python3
"""Google Workspace MCP Server - Python implementation.

Provides Docs, Sheets, Slides, and Drive tools via MCP protocol.
Runs as subprocess, communicates via stdio.
Receives OAuth token via environment variable (never stored on disk).
"""

import asyncio
import json
import os
import sys
from pathlib import Path

# Add plugin directory to path for relative imports when run as script
_plugin_dir = Path(__file__).parent
if str(_plugin_dir) not in sys.path:
    sys.path.insert(0, str(_plugin_dir))

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from services.docs import DocsService
from services.drive import DriveService
from services.sheets import SheetsService
from services.slides import SlidesService


class GoogleWorkspaceMCPServer:
    """MCP Server for Google Workspace."""

    def __init__(self, token_data: dict, export_dir: str):
        self.export_dir = Path(export_dir)
        self.export_dir.mkdir(parents=True, exist_ok=True)

        self.credentials = Credentials(
            token=token_data.get("token"),
            refresh_token=token_data.get("refresh_token"),
            token_uri=token_data.get(
                "token_uri", "https://oauth2.googleapis.com/token"
            ),
            client_id=token_data.get("client_id"),
            client_secret=token_data.get("client_secret"),
            scopes=token_data.get("scopes", []),
        )

        self.docs_api = build("docs", "v1", credentials=self.credentials)
        self.sheets_api = build("sheets", "v4", credentials=self.credentials)
        self.slides_api = build("slides", "v1", credentials=self.credentials)
        self.drive_api = build("drive", "v3", credentials=self.credentials)

        self.docs = DocsService(self.docs_api, self.drive_api, self.export_dir)
        self.sheets = SheetsService(self.sheets_api)
        self.slides = SlidesService(self.slides_api)
        self.drive = DriveService(self.drive_api)

        self.user_email = self._get_user_email(token_data)
        self.tools = self._build_tools()

    def _get_user_email(self, token_data: dict) -> str:
        """Extract user email from token scopes or fetch from userinfo."""
        try:
            from googleapiclient.discovery import build

            oauth2 = build("oauth2", "v2", credentials=self.credentials)
            user_info = oauth2.userinfo().get().execute()
            return user_info.get("email", "unknown")
        except Exception:
            return "unknown"

    def _build_tools(self) -> list:
        """Build tool definitions."""
        email = self.user_email
        return [
            {
                "name": "docs_create",
                "description": f"Create a new Google Doc ({email}).",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "title": {
                            "type": "string",
                            "description": "Document title",
                        }
                    },
                    "required": ["title"],
                },
            },
            {
                "name": "docs_read",
                "description": f"Read content from a Google Doc ({email}).",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "document_id": {
                            "type": "string",
                            "description": "Google Doc ID",
                        }
                    },
                    "required": ["document_id"],
                },
            },
            {
                "name": "docs_update",
                "description": f"Insert text into a Google Doc ({email}).",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "document_id": {
                            "type": "string",
                            "description": "Google Doc ID",
                        },
                        "content": {
                            "type": "string",
                            "description": "Text to insert",
                        },
                        "position": {
                            "type": "number",
                            "description": "Character index position (default: end)",
                        },
                    },
                    "required": ["document_id", "content"],
                },
            },
            {
                "name": "docs_export",
                "description": f"Export a Google Doc to PDF or DOCX ({email}).",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "document_id": {
                            "type": "string",
                            "description": "Google Doc ID",
                        },
                        "format": {
                            "type": "string",
                            "description": "Export format: pdf or docx",
                            "enum": ["pdf", "docx"],
                        },
                    },
                    "required": ["document_id", "format"],
                },
            },
            {
                "name": "docs_replace",
                "description": f"Find and replace text in a Google Doc ({email}).",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "document_id": {
                            "type": "string",
                            "description": "Google Doc ID",
                        },
                        "find_text": {
                            "type": "string",
                            "description": "Text to find",
                        },
                        "replace_text": {
                            "type": "string",
                            "description": "Text to replace with",
                        },
                    },
                    "required": ["document_id", "find_text", "replace_text"],
                },
            },
            {
                "name": "docs_clear",
                "description": f"Clear all content from a Google Doc ({email}).",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "document_id": {
                            "type": "string",
                            "description": "Google Doc ID",
                        },
                    },
                    "required": ["document_id"],
                },
            },
            {
                "name": "docs_append",
                "description": f"Append text to the end of a Google Doc ({email}).",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "document_id": {
                            "type": "string",
                            "description": "Google Doc ID",
                        },
                        "content": {
                            "type": "string",
                            "description": "Text to append",
                        },
                    },
                    "required": ["document_id", "content"],
                },
            },
            {
                "name": "docs_read_tables",
                "description": f"Read all tables from a Google Doc with their structure and content ({email}). Returns table data organized by rows and cells with their indices.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "document_id": {
                            "type": "string",
                            "description": "Google Doc ID",
                        },
                    },
                    "required": ["document_id"],
                },
            },
            {
                "name": "docs_update_table_cell",
                "description": f"Update content of a specific cell in a Google Doc table ({email}). Use docs_read_tables first to get table structure.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "document_id": {
                            "type": "string",
                            "description": "Google Doc ID",
                        },
                        "table_index": {
                            "type": "integer",
                            "description": "Index of the table (0-based, first table is 0)",
                        },
                        "row": {
                            "type": "integer",
                            "description": "Row index (0-based)",
                        },
                        "column": {
                            "type": "integer",
                            "description": "Column index (0-based)",
                        },
                        "content": {
                            "type": "string",
                            "description": "New text content for the cell",
                        },
                    },
                    "required": [
                        "document_id",
                        "table_index",
                        "row",
                        "column",
                        "content",
                    ],
                },
            },
            {
                "name": "docs_find_table_by_text",
                "description": f"Find a table that appears after a specific text/heading in a Google Doc ({email}). Useful to locate tables in specific sections like 'Corrispettivi'.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "document_id": {
                            "type": "string",
                            "description": "Google Doc ID",
                        },
                        "search_text": {
                            "type": "string",
                            "description": "Text/heading to search for (table should be after this text)",
                        },
                    },
                    "required": ["document_id", "search_text"],
                },
            },
            {
                "name": "docs_update_table_row",
                "description": f"Update an entire row in a Google Doc table ({email}). Provide values for each cell in the row.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "document_id": {
                            "type": "string",
                            "description": "Google Doc ID",
                        },
                        "table_index": {
                            "type": "integer",
                            "description": "Index of the table (0-based)",
                        },
                        "row": {
                            "type": "integer",
                            "description": "Row index (0-based)",
                        },
                        "values": {
                            "type": "array",
                            "description": "List of values for each cell in the row",
                            "items": {"type": "string"},
                        },
                    },
                    "required": ["document_id", "table_index", "row", "values"],
                },
            },
            {
                "name": "docs_export_image",
                "description": f"Export a Google Doc as PNG image(s) ({email}). Converts document pages to images for visual preview.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "document_id": {
                            "type": "string",
                            "description": "Google Doc ID",
                        },
                        "page": {
                            "type": "integer",
                            "description": "Specific page to export (1-based). Omit for all pages.",
                        },
                        "dpi": {
                            "type": "integer",
                            "description": "Image resolution (default 150). Higher = better quality but larger file.",
                        },
                    },
                    "required": ["document_id"],
                },
            },
            {
                "name": "docs_delete_table",
                "description": f"Delete an entire table from a Google Doc ({email}). Use docs_read_tables first to identify the table index.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "document_id": {
                            "type": "string",
                            "description": "Google Doc ID",
                        },
                        "table_index": {
                            "type": "integer",
                            "description": "Index of the table to delete (0-based, first table is 0)",
                        },
                    },
                    "required": ["document_id", "table_index"],
                },
            },
            {
                "name": "docs_update_text_style",
                "description": f"Update text formatting (bold, italic, underline, strikethrough, font_size, colors) in a Google Doc ({email}). Use to apply or remove text formatting.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "document_id": {
                            "type": "string",
                            "description": "Google Doc ID",
                        },
                        "start_index": {
                            "type": "integer",
                            "description": "Start character index",
                        },
                        "end_index": {
                            "type": "integer",
                            "description": "End character index",
                        },
                        "bold": {
                            "type": "boolean",
                            "description": "Set bold (true/false). Omit to not change.",
                        },
                        "italic": {
                            "type": "boolean",
                            "description": "Set italic (true/false). Omit to not change.",
                        },
                        "underline": {
                            "type": "boolean",
                            "description": "Set underline (true/false). Omit to not change.",
                        },
                        "strikethrough": {
                            "type": "boolean",
                            "description": "Set strikethrough (true/false). Omit to not change.",
                        },
                        "font_size": {
                            "type": "integer",
                            "description": "Font size in points. Omit to not change.",
                        },
                        "foreground_color": {
                            "type": "string",
                            "description": "Text color. Formats: hex '#FF5733', rgb 'rgb(255,87,51)', or name (black, white, red, green, blue, yellow, orange, purple, pink, gray, brown, cyan, magenta). Omit to not change.",
                        },
                        "background_color": {
                            "type": "string",
                            "description": "Text background/highlight color. Same formats as foreground_color. Omit to not change.",
                        },
                    },
                    "required": ["document_id", "start_index", "end_index"],
                },
            },
            {
                "name": "docs_update_table_cell_style",
                "description": f"Update text formatting in a table cell ({email}). Use to remove strikethrough or apply bold/italic/etc to cell content.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "document_id": {
                            "type": "string",
                            "description": "Google Doc ID",
                        },
                        "table_index": {
                            "type": "integer",
                            "description": "Index of the table (0-based)",
                        },
                        "row": {
                            "type": "integer",
                            "description": "Row index (0-based)",
                        },
                        "column": {
                            "type": "integer",
                            "description": "Column index (0-based)",
                        },
                        "bold": {
                            "type": "boolean",
                            "description": "Set bold (true/false). Omit to not change.",
                        },
                        "italic": {
                            "type": "boolean",
                            "description": "Set italic (true/false). Omit to not change.",
                        },
                        "underline": {
                            "type": "boolean",
                            "description": "Set underline (true/false). Omit to not change.",
                        },
                        "strikethrough": {
                            "type": "boolean",
                            "description": "Set strikethrough (true/false). Use false to remove strikethrough.",
                        },
                        "font_size": {
                            "type": "integer",
                            "description": "Font size in points. Omit to not change.",
                        },
                    },
                    "required": ["document_id", "table_index", "row", "column"],
                },
            },
            {
                "name": "docs_insert_toc",
                "description": f"Insert a table of contents based on document headings ({email}). Requires headings (H1-H6) in the document.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "document_id": {
                            "type": "string",
                            "description": "Google Doc ID",
                        },
                        "position": {
                            "type": "integer",
                            "description": "Index position (default: beginning of document)",
                        },
                    },
                    "required": ["document_id"],
                },
            },
            {
                "name": "docs_insert_table",
                "description": f"Insert a new table into a Google Doc ({email}).",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "document_id": {
                            "type": "string",
                            "description": "Google Doc ID",
                        },
                        "rows": {
                            "type": "integer",
                            "description": "Number of rows",
                        },
                        "columns": {
                            "type": "integer",
                            "description": "Number of columns",
                        },
                        "position": {
                            "type": "integer",
                            "description": "Index position (default: end of document)",
                        },
                    },
                    "required": ["document_id", "rows", "columns"],
                },
            },
            {
                "name": "docs_insert_table_row",
                "description": f"Insert a new row in a Google Doc table ({email}).",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "document_id": {
                            "type": "string",
                            "description": "Google Doc ID",
                        },
                        "table_index": {
                            "type": "integer",
                            "description": "Index of the table (0-based)",
                        },
                        "row_index": {
                            "type": "integer",
                            "description": "Row index to insert at (0-based)",
                        },
                        "insert_below": {
                            "type": "boolean",
                            "description": "If true, insert below row_index; if false, insert above (default: true)",
                        },
                    },
                    "required": ["document_id", "table_index", "row_index"],
                },
            },
            {
                "name": "docs_insert_table_column",
                "description": f"Insert a new column in a Google Doc table ({email}).",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "document_id": {
                            "type": "string",
                            "description": "Google Doc ID",
                        },
                        "table_index": {
                            "type": "integer",
                            "description": "Index of the table (0-based)",
                        },
                        "column_index": {
                            "type": "integer",
                            "description": "Column index to insert at (0-based)",
                        },
                        "insert_right": {
                            "type": "boolean",
                            "description": "If true, insert to the right; if false, insert to the left (default: true)",
                        },
                    },
                    "required": ["document_id", "table_index", "column_index"],
                },
            },
            {
                "name": "docs_delete_table_row",
                "description": f"Delete a row from a Google Doc table ({email}).",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "document_id": {
                            "type": "string",
                            "description": "Google Doc ID",
                        },
                        "table_index": {
                            "type": "integer",
                            "description": "Index of the table (0-based)",
                        },
                        "row_index": {
                            "type": "integer",
                            "description": "Row index to delete (0-based)",
                        },
                    },
                    "required": ["document_id", "table_index", "row_index"],
                },
            },
            {
                "name": "docs_delete_table_column",
                "description": f"Delete a column from a Google Doc table ({email}).",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "document_id": {
                            "type": "string",
                            "description": "Google Doc ID",
                        },
                        "table_index": {
                            "type": "integer",
                            "description": "Index of the table (0-based)",
                        },
                        "column_index": {
                            "type": "integer",
                            "description": "Column index to delete (0-based)",
                        },
                    },
                    "required": ["document_id", "table_index", "column_index"],
                },
            },
            {
                "name": "docs_insert_image",
                "description": f"Insert an image from URL into a Google Doc ({email}).",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "document_id": {
                            "type": "string",
                            "description": "Google Doc ID",
                        },
                        "image_url": {
                            "type": "string",
                            "description": "Public URL of the image",
                        },
                        "position": {
                            "type": "integer",
                            "description": "Index position (default: end of document)",
                        },
                        "width": {
                            "type": "number",
                            "description": "Image width in points (optional)",
                        },
                        "height": {
                            "type": "number",
                            "description": "Image height in points (optional)",
                        },
                    },
                    "required": ["document_id", "image_url"],
                },
            },
            {
                "name": "docs_update_paragraph_style",
                "description": f"Update paragraph formatting in a Google Doc ({email}). Set headings (H1-H6), alignment, spacing.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "document_id": {
                            "type": "string",
                            "description": "Google Doc ID",
                        },
                        "start_index": {
                            "type": "integer",
                            "description": "Start character index",
                        },
                        "end_index": {
                            "type": "integer",
                            "description": "End character index",
                        },
                        "heading": {
                            "type": "string",
                            "description": "Heading style: NORMAL, HEADING_1 to HEADING_6, TITLE, SUBTITLE",
                        },
                        "alignment": {
                            "type": "string",
                            "description": "Text alignment: START, CENTER, END, JUSTIFIED",
                        },
                        "line_spacing": {
                            "type": "number",
                            "description": "Line spacing multiplier (e.g., 1.5 for 1.5x)",
                        },
                        "space_above": {
                            "type": "number",
                            "description": "Space above paragraph in points",
                        },
                        "space_below": {
                            "type": "number",
                            "description": "Space below paragraph in points",
                        },
                    },
                    "required": ["document_id", "start_index", "end_index"],
                },
            },
            {
                "name": "docs_create_bullets",
                "description": f"Create a bulleted or numbered list in a Google Doc ({email}).",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "document_id": {
                            "type": "string",
                            "description": "Google Doc ID",
                        },
                        "start_index": {
                            "type": "integer",
                            "description": "Start character index",
                        },
                        "end_index": {
                            "type": "integer",
                            "description": "End character index",
                        },
                        "bullet_type": {
                            "type": "string",
                            "description": "Bullet preset: BULLET_DISC_CIRCLE_SQUARE (bullets), NUMBERED_DECIMAL_NESTED (numbers), NUMBERED_DECIMAL_ALPHA_ROMAN",
                        },
                    },
                    "required": ["document_id", "start_index", "end_index"],
                },
            },
            {
                "name": "docs_delete_bullets",
                "description": f"Remove bullets from a list in a Google Doc ({email}).",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "document_id": {
                            "type": "string",
                            "description": "Google Doc ID",
                        },
                        "start_index": {
                            "type": "integer",
                            "description": "Start character index",
                        },
                        "end_index": {
                            "type": "integer",
                            "description": "End character index",
                        },
                    },
                    "required": ["document_id", "start_index", "end_index"],
                },
            },
            {
                "name": "docs_insert_page_break",
                "description": f"Insert a page break in a Google Doc ({email}).",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "document_id": {
                            "type": "string",
                            "description": "Google Doc ID",
                        },
                        "position": {
                            "type": "integer",
                            "description": "Index position (default: end of document)",
                        },
                    },
                    "required": ["document_id"],
                },
            },
            {
                "name": "docs_create_header",
                "description": f"Create or update document header in a Google Doc ({email}).",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "document_id": {
                            "type": "string",
                            "description": "Google Doc ID",
                        },
                        "content": {
                            "type": "string",
                            "description": "Text content for the header",
                        },
                    },
                    "required": ["document_id"],
                },
            },
            {
                "name": "docs_create_footer",
                "description": f"Create or update document footer in a Google Doc ({email}).",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "document_id": {
                            "type": "string",
                            "description": "Google Doc ID",
                        },
                        "content": {
                            "type": "string",
                            "description": "Text content for the footer",
                        },
                    },
                    "required": ["document_id"],
                },
            },
            {
                "name": "docs_insert_link",
                "description": f"Add a hyperlink to existing text in a Google Doc ({email}).",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "document_id": {
                            "type": "string",
                            "description": "Google Doc ID",
                        },
                        "start_index": {
                            "type": "integer",
                            "description": "Start character index of text to link",
                        },
                        "end_index": {
                            "type": "integer",
                            "description": "End character index of text to link",
                        },
                        "url": {
                            "type": "string",
                            "description": "URL for the hyperlink",
                        },
                    },
                    "required": ["document_id", "start_index", "end_index", "url"],
                },
            },
            {
                "name": "docs_remove_link",
                "description": f"Remove hyperlink from text (keep text, remove link) in a Google Doc ({email}).",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "document_id": {
                            "type": "string",
                            "description": "Google Doc ID",
                        },
                        "start_index": {
                            "type": "integer",
                            "description": "Start character index",
                        },
                        "end_index": {
                            "type": "integer",
                            "description": "End character index",
                        },
                    },
                    "required": ["document_id", "start_index", "end_index"],
                },
            },
            {
                "name": "sheets_create",
                "description": f"Create a new Google Sheet ({email}).",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "title": {
                            "type": "string",
                            "description": "Spreadsheet title",
                        }
                    },
                    "required": ["title"],
                },
            },
            {
                "name": "sheets_read",
                "description": f"Read cells from a Google Sheet ({email}).",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "spreadsheet_id": {
                            "type": "string",
                            "description": "Google Sheet ID",
                        },
                        "range": {
                            "type": "string",
                            "description": "A1 notation range (e.g., 'Sheet1!A1:C10')",
                        },
                    },
                    "required": ["spreadsheet_id", "range"],
                },
            },
            {
                "name": "sheets_write",
                "description": f"Write values to a Google Sheet ({email}).",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "spreadsheet_id": {
                            "type": "string",
                            "description": "Google Sheet ID",
                        },
                        "range": {
                            "type": "string",
                            "description": "A1 notation range (e.g., 'Sheet1!A1')",
                        },
                        "values": {
                            "type": "array",
                            "description": '2D array of values. Each inner array is a row. Example: [["A1", "B1"], ["A2", "B2"]]',
                            "items": {"type": "array", "items": {}},
                        },
                    },
                    "required": ["spreadsheet_id", "range", "values"],
                },
            },
            {
                "name": "sheets_append",
                "description": f"Append rows to a Google Sheet ({email}).",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "spreadsheet_id": {
                            "type": "string",
                            "description": "Google Sheet ID",
                        },
                        "range": {
                            "type": "string",
                            "description": "A1 notation range (e.g., 'Sheet1!A:A')",
                        },
                        "values": {
                            "type": "array",
                            "description": '2D array of values to append. Each inner array is a row. Example: [["Col1", "Col2"], ["Val1", "Val2"]]',
                            "items": {"type": "array", "items": {}},
                        },
                    },
                    "required": ["spreadsheet_id", "range", "values"],
                },
            },
            {
                "name": "sheets_clear",
                "description": f"Clear values from cells in a Google Sheet ({email}).",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "spreadsheet_id": {
                            "type": "string",
                            "description": "Google Sheet ID",
                        },
                        "range": {
                            "type": "string",
                            "description": "A1 notation range to clear (e.g., 'Sheet1!A1:C10')",
                        },
                    },
                    "required": ["spreadsheet_id", "range"],
                },
            },
            {
                "name": "sheets_add_sheet",
                "description": f"Add a new sheet to a Google Spreadsheet ({email}).",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "spreadsheet_id": {
                            "type": "string",
                            "description": "Google Sheet ID",
                        },
                        "title": {
                            "type": "string",
                            "description": "Name for the new sheet",
                        },
                    },
                    "required": ["spreadsheet_id", "title"],
                },
            },
            {
                "name": "slides_create",
                "description": f"Create a new Google Slides presentation ({email}).",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "title": {
                            "type": "string",
                            "description": "Presentation title",
                        }
                    },
                    "required": ["title"],
                },
            },
            {
                "name": "slides_read",
                "description": f"Read content from a Google Slides presentation ({email}).",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "presentation_id": {
                            "type": "string",
                            "description": "Google Slides presentation ID",
                        }
                    },
                    "required": ["presentation_id"],
                },
            },
            {
                "name": "slides_add_slide",
                "description": f"Add a new slide to a presentation ({email}).",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "presentation_id": {
                            "type": "string",
                            "description": "Google Slides presentation ID",
                        },
                        "layout": {
                            "type": "string",
                            "description": "Slide layout: BLANK, TITLE, TITLE_AND_BODY, etc.",
                        },
                    },
                    "required": ["presentation_id"],
                },
            },
            {
                "name": "slides_update",
                "description": f"Add text content to a slide ({email}).",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "presentation_id": {
                            "type": "string",
                            "description": "Google Slides presentation ID",
                        },
                        "slide_id": {
                            "type": "string",
                            "description": "Slide object ID",
                        },
                        "content": {
                            "type": "string",
                            "description": "Text content to add",
                        },
                    },
                    "required": ["presentation_id", "slide_id", "content"],
                },
            },
            {
                "name": "drive_copy",
                "description": f"Copy/duplicate a Google Drive file ({email}).",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "file_id": {
                            "type": "string",
                            "description": "Google Drive file ID to copy",
                        },
                        "new_title": {
                            "type": "string",
                            "description": "Title for the copy (default: Copy of <original>)",
                        },
                        "folder_id": {
                            "type": "string",
                            "description": "Destination folder ID (optional)",
                        },
                    },
                    "required": ["file_id"],
                },
            },
            {
                "name": "drive_delete",
                "description": f"Delete a file from Google Drive ({email}).",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "file_id": {
                            "type": "string",
                            "description": "Google Drive file ID to delete",
                        },
                    },
                    "required": ["file_id"],
                },
            },
            {
                "name": "drive_move",
                "description": f"Move a file to a different folder ({email}).",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "file_id": {
                            "type": "string",
                            "description": "Google Drive file ID to move",
                        },
                        "folder_id": {
                            "type": "string",
                            "description": "Destination folder ID",
                        },
                    },
                    "required": ["file_id", "folder_id"],
                },
            },
            {
                "name": "drive_rename",
                "description": f"Rename a file in Google Drive ({email}).",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "file_id": {
                            "type": "string",
                            "description": "Google Drive file ID",
                        },
                        "new_name": {
                            "type": "string",
                            "description": "New name for the file",
                        },
                    },
                    "required": ["file_id", "new_name"],
                },
            },
            {
                "name": "drive_create_folder",
                "description": f"Create a new folder in Google Drive ({email}).",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "name": {
                            "type": "string",
                            "description": "Folder name",
                        },
                        "parent_id": {
                            "type": "string",
                            "description": "Parent folder ID (optional, default: root)",
                        },
                    },
                    "required": ["name"],
                },
            },
            {
                "name": "drive_share",
                "description": f"Share a Google Drive file with a user ({email}).",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "file_id": {
                            "type": "string",
                            "description": "Google Drive file ID",
                        },
                        "email": {
                            "type": "string",
                            "description": "Email address to share with",
                        },
                        "role": {
                            "type": "string",
                            "description": "Permission role: reader, writer, commenter",
                            "enum": ["reader", "writer", "commenter"],
                        },
                    },
                    "required": ["file_id", "email", "role"],
                },
            },
            {
                "name": "drive_list",
                "description": f"List Google Workspace files ({email}).",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Search query (Google Drive syntax)",
                        },
                        "max_results": {
                            "type": "number",
                            "description": "Maximum results (default: 20)",
                        },
                    },
                },
            },
            {
                "name": "drive_upload",
                "description": f"Upload a local file to Google Drive ({email}). "
                "Supports any file type. Use share=true to get a public link.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "file_path": {
                            "type": "string",
                            "description": "Absolute path to the local file",
                        },
                        "name": {
                            "type": "string",
                            "description": "Filename on Drive (default: original filename)",
                        },
                        "folder_id": {
                            "type": "string",
                            "description": "Destination folder ID (default: root)",
                        },
                        "share": {
                            "type": "boolean",
                            "description": "Make accessible via link (anyone with link = viewer)",
                        },
                    },
                    "required": ["file_path"],
                },
            },
        ]

    def _track_operation(self, name: str, args: dict, result: dict) -> None:
        """Track operation for context persistence."""
        try:
            state_file = Path(self.export_dir) / "gworkspace_context.json"

            # Load existing state
            state = {}
            if state_file.exists():
                try:
                    with open(state_file, "r") as f:
                        state = json.load(f)
                except (json.JSONDecodeError, IOError):
                    state = {}

            # Use email as user_id (simplified - in production would use unified_id)
            user_id = self.user_email
            if user_id not in state:
                state[user_id] = {"operations": [], "working_document": None}

            from datetime import datetime, timezone

            timestamp = datetime.now(timezone.utc).isoformat()

            # Extract document info from args
            doc_id = (
                args.get("document_id")
                or args.get("spreadsheet_id")
                or args.get("presentation_id")
                or args.get("file_id", "")
            )
            doc_title = (
                result.get("data", {}).get("title", "")
                if isinstance(result.get("data"), dict)
                else ""
            )

            # Determine document type
            doc_type = "doc"
            if "sheets" in name:
                doc_type = "sheet"
            elif "slides" in name:
                doc_type = "slide"
            elif "drive" in name:
                doc_type = "drive"

            # Extract content summary for read operations
            content_summary = ""
            if name in ("docs_read", "sheets_read", "slides_read"):
                data = result.get("data", {})
                if isinstance(data, dict):
                    # Handle docs/slides content (string)
                    content = data.get("content", "")
                    if isinstance(content, str) and content:
                        content_summary = content[:1000]
                    elif isinstance(content, list):
                        # For structured content, extract text
                        texts = []
                        for item in content[:10]:
                            if isinstance(item, dict) and "text" in item:
                                texts.append(item["text"])
                        content_summary = "\n".join(texts)[:1000]

                    # Handle sheets values (2D array)
                    values = data.get("values", [])
                    if values and isinstance(values, list):
                        # Convert 2D array to readable text (first 10 rows)
                        rows = []
                        for row in values[:10]:
                            if isinstance(row, list):
                                rows.append(" | ".join(str(cell) for cell in row[:10]))
                        content_summary = "\n".join(rows)[:1000]

                        # Use first row as "title" hint if headers present
                        if values[0] and not doc_title:
                            doc_title = f"Foglio con colonne: {', '.join(str(c) for c in values[0][:5])}"

            # Record operation
            op_record = {
                "timestamp": timestamp,
                "operation": name.replace("docs_", "")
                .replace("sheets_", "")
                .replace("slides_", "")
                .replace("drive_", ""),
                "tool_name": name,
                "document_id": doc_id,
                "document_title": doc_title,
                "document_type": doc_type,
                "content_summary": content_summary,
            }

            state[user_id]["operations"].insert(0, op_record)
            state[user_id]["operations"] = state[user_id]["operations"][:10]

            # Update working document for read/create operations
            if name in (
                "docs_read",
                "docs_create",
                "sheets_read",
                "sheets_create",
                "slides_read",
                "slides_create",
            ):
                state[user_id]["working_document"] = {
                    "document_id": doc_id,
                    "document_title": doc_title,
                    "document_type": doc_type,
                    "content_summary": content_summary,
                    "timestamp": timestamp,
                }

            # Save state
            with open(state_file, "w") as f:
                json.dump(state, f, indent=2)

        except Exception:
            # Don't fail tool calls due to tracking errors
            pass

    def _call_tool(self, name: str, args: dict) -> dict:
        """Route tool call to appropriate service method."""
        import sys

        try:
            result = self._call_tool_impl(name, args)
        except Exception as e:
            sys.stderr.write(
                f"GWS _call_tool error for {name}: {type(e).__name__}: {e}\n"
            )
            sys.stderr.flush()
            raise

        # Track successful operations
        if result.get("success"):
            self._track_operation(name, args, result)

        return result

    def _call_tool_impl(self, name: str, args: dict) -> dict:
        """Implementation of tool routing."""
        if name == "docs_create":
            return self.docs.create(args["title"])
        elif name == "docs_read":
            return self.docs.read(args["document_id"])
        elif name == "docs_update":
            return self.docs.update(
                args["document_id"], args["content"], args.get("position")
            )
        elif name == "docs_export":
            return self.docs.export(args["document_id"], args["format"])
        elif name == "docs_replace":
            return self.docs.replace(
                args["document_id"], args["find_text"], args["replace_text"]
            )
        elif name == "docs_clear":
            return self.docs.clear(args["document_id"])
        elif name == "docs_append":
            return self.docs.append(args["document_id"], args["content"])
        elif name == "docs_read_tables":
            return self.docs.read_tables(args["document_id"])
        elif name == "docs_update_table_cell":
            return self.docs.update_table_cell(
                args["document_id"],
                args["table_index"],
                args["row"],
                args["column"],
                args["content"],
            )
        elif name == "docs_find_table_by_text":
            return self.docs.find_table_by_text(
                args["document_id"], args["search_text"]
            )
        elif name == "docs_update_table_row":
            return self.docs.update_table_row(
                args["document_id"],
                args["table_index"],
                args["row"],
                args["values"],
            )
        elif name == "docs_export_image":
            return self.docs.export_as_image(
                args["document_id"],
                args.get("page"),
                args.get("dpi", 150),
            )
        elif name == "docs_delete_table":
            return self.docs.delete_table(
                args["document_id"],
                args["table_index"],
            )
        elif name == "docs_update_text_style":
            return self.docs.update_text_style(
                args["document_id"],
                args["start_index"],
                args["end_index"],
                bold=args.get("bold"),
                italic=args.get("italic"),
                underline=args.get("underline"),
                strikethrough=args.get("strikethrough"),
                font_size=args.get("font_size"),
                foreground_color=args.get("foreground_color"),
                background_color=args.get("background_color"),
            )
        elif name == "docs_update_table_cell_style":
            return self.docs.update_table_cell_style(
                args["document_id"],
                args["table_index"],
                args["row"],
                args["column"],
                bold=args.get("bold"),
                italic=args.get("italic"),
                underline=args.get("underline"),
                strikethrough=args.get("strikethrough"),
                font_size=args.get("font_size"),
            )
        elif name == "docs_insert_toc":
            return self.docs.insert_table_of_contents(
                args["document_id"],
                args.get("position"),
            )
        elif name == "docs_insert_table":
            return self.docs.insert_table(
                args["document_id"],
                args["rows"],
                args["columns"],
                args.get("position"),
            )
        elif name == "docs_insert_table_row":
            return self.docs.insert_table_row(
                args["document_id"],
                args["table_index"],
                args["row_index"],
                args.get("insert_below", True),
            )
        elif name == "docs_insert_table_column":
            return self.docs.insert_table_column(
                args["document_id"],
                args["table_index"],
                args["column_index"],
                args.get("insert_right", True),
            )
        elif name == "docs_delete_table_row":
            return self.docs.delete_table_row(
                args["document_id"],
                args["table_index"],
                args["row_index"],
            )
        elif name == "docs_delete_table_column":
            return self.docs.delete_table_column(
                args["document_id"],
                args["table_index"],
                args["column_index"],
            )
        elif name == "docs_insert_image":
            return self.docs.insert_image(
                args["document_id"],
                args["image_url"],
                args.get("position"),
                args.get("width"),
                args.get("height"),
            )
        elif name == "docs_update_paragraph_style":
            return self.docs.update_paragraph_style(
                args["document_id"],
                args["start_index"],
                args["end_index"],
                heading=args.get("heading"),
                alignment=args.get("alignment"),
                line_spacing=args.get("line_spacing"),
                space_above=args.get("space_above"),
                space_below=args.get("space_below"),
            )
        elif name == "docs_create_bullets":
            return self.docs.create_bullets(
                args["document_id"],
                args["start_index"],
                args["end_index"],
                args.get("bullet_type", "BULLET_DISC_CIRCLE_SQUARE"),
            )
        elif name == "docs_delete_bullets":
            return self.docs.delete_bullets(
                args["document_id"],
                args["start_index"],
                args["end_index"],
            )
        elif name == "docs_insert_page_break":
            return self.docs.insert_page_break(
                args["document_id"],
                args.get("position"),
            )
        elif name == "docs_create_header":
            return self.docs.create_header(
                args["document_id"],
                args.get("content", ""),
            )
        elif name == "docs_create_footer":
            return self.docs.create_footer(
                args["document_id"],
                args.get("content", ""),
            )
        elif name == "docs_insert_link":
            return self.docs.insert_link(
                args["document_id"],
                args["start_index"],
                args["end_index"],
                args["url"],
            )
        elif name == "docs_remove_link":
            return self.docs.remove_link(
                args["document_id"],
                args["start_index"],
                args["end_index"],
            )
        elif name == "sheets_create":
            return self.sheets.create(args["title"])
        elif name == "sheets_read":
            return self.sheets.read(args["spreadsheet_id"], args["range"])
        elif name == "sheets_write":
            return self.sheets.write(
                args["spreadsheet_id"], args["range"], args["values"]
            )
        elif name == "sheets_append":
            return self.sheets.append(
                args["spreadsheet_id"], args["range"], args["values"]
            )
        elif name == "sheets_clear":
            return self.sheets.clear(args["spreadsheet_id"], args["range"])
        elif name == "sheets_add_sheet":
            return self.sheets.add_sheet(args["spreadsheet_id"], args["title"])
        elif name == "slides_create":
            return self.slides.create(args["title"])
        elif name == "slides_read":
            return self.slides.read(args["presentation_id"])
        elif name == "slides_add_slide":
            return self.slides.add_slide(
                args["presentation_id"], args.get("layout", "BLANK")
            )
        elif name == "slides_update":
            return self.slides.update(
                args["presentation_id"], args["slide_id"], args["content"]
            )
        elif name == "drive_copy":
            return self.drive.copy(
                args["file_id"], args.get("new_title"), args.get("folder_id")
            )
        elif name == "drive_delete":
            return self.drive.delete(args["file_id"])
        elif name == "drive_move":
            return self.drive.move(args["file_id"], args["folder_id"])
        elif name == "drive_rename":
            return self.drive.rename(args["file_id"], args["new_name"])
        elif name == "drive_create_folder":
            return self.drive.create_folder(args["name"], args.get("parent_id"))
        elif name == "drive_share":
            return self.drive.share(args["file_id"], args["email"], args["role"])
        elif name == "drive_list":
            return self.drive.list(args.get("query"), args.get("max_results", 20))
        elif name == "drive_upload":
            return self.drive.upload(
                args["file_path"],
                args.get("name"),
                args.get("folder_id"),
                args.get("share", False),
            )
        else:
            return {
                "success": False,
                "error": f"Unknown tool: {name}",
                "data": None,
                "recoverable": False,
                "retry_after": None,
            }

    async def handle_request(self, request: dict) -> dict:
        """Handle MCP JSON-RPC request."""
        method = request.get("method", "")
        req_id = request.get("id")
        params = request.get("params", {})

        try:
            if method == "initialize":
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {"tools": {}},
                        "serverInfo": {
                            "name": f"gws-{self.user_email}",
                            "version": "1.0.0",
                        },
                    },
                }

            elif method == "tools/list":
                return {"jsonrpc": "2.0", "id": req_id, "result": {"tools": self.tools}}

            elif method == "tools/call":
                tool_name = params.get("name", "")
                args = params.get("arguments", {})
                result = self._call_tool(tool_name, args)
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "content": [
                            {"type": "text", "text": json.dumps(result, indent=2)}
                        ]
                    },
                }

            elif method == "notifications/initialized":
                return None

            else:
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {"code": -32601, "message": f"Method not found: {method}"},
                }

        except Exception as e:
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32000, "message": str(e)},
            }

    async def run(self):
        """Run the MCP server on stdio."""
        loop = asyncio.get_event_loop()
        reader = asyncio.StreamReader()
        protocol = asyncio.StreamReaderProtocol(reader)
        await loop.connect_read_pipe(lambda: protocol, sys.stdin)

        while True:
            try:
                line = await reader.readline()
                if not line:
                    break

                request = json.loads(line.decode("utf-8"))
                response = await self.handle_request(request)

                if response:
                    sys.stdout.write(json.dumps(response) + "\n")
                    sys.stdout.flush()

            except json.JSONDecodeError:
                continue
            except Exception as e:
                error_response = {
                    "jsonrpc": "2.0",
                    "id": None,
                    "error": {"code": -32700, "message": f"Parse error: {e}"},
                }
                sys.stdout.write(json.dumps(error_response) + "\n")
                sys.stdout.flush()


def main():
    token_json = os.environ.get("GWORKSPACE_TOKEN_DATA", "")
    export_dir = os.environ.get("GWORKSPACE_EXPORT_DIR", "/app/data/exports")

    if not token_json:
        sys.stderr.write("Error: GWORKSPACE_TOKEN_DATA environment variable not set\n")
        sys.exit(1)

    try:
        token_data = json.loads(token_json)
    except json.JSONDecodeError as e:
        sys.stderr.write(f"Error: Invalid GWORKSPACE_TOKEN_DATA JSON: {e}\n")
        sys.exit(1)

    server = GoogleWorkspaceMCPServer(token_data, export_dir)
    asyncio.run(server.run())


if __name__ == "__main__":
    main()
