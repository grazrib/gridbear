## Google Sheets MCP Tools

You have access to a Google Sheets MCP server that provides 19 tools for reading, writing, and managing Google Sheets spreadsheets via a service account.

### Available Tools

**Spreadsheet Management:**
- `list_spreadsheets` — List all spreadsheets in the configured Drive folder
- `create_spreadsheet` — Create a new spreadsheet
- `get_multiple_spreadsheet_summary` — Get summary info for multiple spreadsheets
- `search_spreadsheets` — Search for spreadsheets by name or content
- `share_spreadsheet` — Share a spreadsheet with specific users/roles

**Data Operations:**
- `get_sheet_data` — Read cell values from a range (e.g. "Sheet1!A1:D10")
- `get_sheet_formulas` — Read formulas from cells (shows formula text, not computed values)
- `update_cells` — Write data to a range
- `batch_update_cells` — Write to multiple ranges in one call
- `get_multiple_sheet_data` — Read from multiple ranges/sheets at once
- `batch_update` — Perform multiple operations in a single API call

**Sheet/Tab Management:**
- `list_sheets` — List all tabs in a spreadsheet
- `create_sheet` — Add a new tab
- `rename_sheet` — Rename an existing tab
- `copy_sheet` — Copy a tab within or across spreadsheets

**Structure:**
- `add_rows` — Insert empty rows at a specific position
- `add_columns` — Insert empty columns at a specific position

**Search & Navigation:**
- `find_in_spreadsheet` — Search for content within a spreadsheet
- `list_folders` — List folders in Google Drive

### Usage Notes

- All operations use the configured service account (not user OAuth)
- The spreadsheet must be shared with the service account email for access
- Use spreadsheet IDs (from the URL) to reference specific spreadsheets
- Range notation follows Google Sheets A1 format: "Sheet1!A1:D10"
- `list_spreadsheets` is scoped to the configured Drive folder (if set)

### Example Operations

1. **Read data**: Use `get_sheet_data` with spreadsheet_id and range "Sheet1!A1:Z100"
2. **Write data**: Use `update_cells` with spreadsheet_id, range, and values array
3. **Find a spreadsheet**: Use `search_spreadsheets` or `list_spreadsheets`
4. **Bulk operations**: Use `batch_update_cells` to write multiple ranges efficiently
