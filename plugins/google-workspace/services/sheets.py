"""Google Sheets service."""

from googleapiclient.errors import HttpError

from .base import BaseGoogleService


class SheetsService(BaseGoogleService):
    """Service for Google Sheets operations."""

    def __init__(self, sheets_service):
        """Initialize Sheets service.

        Args:
            sheets_service: Google Sheets API service
        """
        self.sheets = sheets_service

    def create(self, title: str) -> dict:
        """Create a new Google Sheet.

        Args:
            title: Spreadsheet title

        Returns:
            Response with spreadsheet ID and URL
        """
        try:
            spreadsheet = (
                self.sheets.spreadsheets()
                .create(body={"properties": {"title": title}})
                .execute()
            )
            return self._format_response(
                data={
                    "spreadsheetId": spreadsheet.get("spreadsheetId"),
                    "title": spreadsheet.get("properties", {}).get("title"),
                    "url": spreadsheet.get("spreadsheetUrl"),
                }
            )
        except HttpError as e:
            return self._format_error(self._handle_api_error(e))

    def read(self, spreadsheet_id: str, range: str = "Sheet1") -> dict:
        """Read cells from spreadsheet.

        Args:
            spreadsheet_id: Google Sheet ID
            range: A1 notation range (e.g., "Sheet1!A1:C10")

        Returns:
            Response with cell values
        """
        try:
            result = (
                self.sheets.spreadsheets()
                .values()
                .get(spreadsheetId=spreadsheet_id, range=range)
                .execute()
            )
            return self._format_response(
                data={
                    "spreadsheetId": spreadsheet_id,
                    "range": result.get("range"),
                    "values": result.get("values", []),
                    "url": f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}/edit",
                }
            )
        except HttpError as e:
            return self._format_error(self._handle_api_error(e))

    def write(self, spreadsheet_id: str, range: str, values: list) -> dict:
        """Write values to cells.

        Args:
            spreadsheet_id: Google Sheet ID
            range: A1 notation range (e.g., "Sheet1!A1")
            values: 2D array of values

        Returns:
            Response with updated cell count
        """
        try:
            result = (
                self.sheets.spreadsheets()
                .values()
                .update(
                    spreadsheetId=spreadsheet_id,
                    range=range,
                    valueInputOption="USER_ENTERED",
                    body={"values": values},
                )
                .execute()
            )
            return self._format_response(
                data={
                    "spreadsheetId": spreadsheet_id,
                    "updatedRange": result.get("updatedRange"),
                    "updatedRows": result.get("updatedRows"),
                    "updatedColumns": result.get("updatedColumns"),
                    "updatedCells": result.get("updatedCells"),
                    "url": f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}/edit",
                }
            )
        except HttpError as e:
            return self._format_error(self._handle_api_error(e))

    def append(self, spreadsheet_id: str, range: str, values: list) -> dict:
        """Append rows to spreadsheet.

        Args:
            spreadsheet_id: Google Sheet ID
            range: A1 notation range (e.g., "Sheet1!A:A")
            values: 2D array of values to append

        Returns:
            Response with appended range info
        """
        try:
            result = (
                self.sheets.spreadsheets()
                .values()
                .append(
                    spreadsheetId=spreadsheet_id,
                    range=range,
                    valueInputOption="USER_ENTERED",
                    insertDataOption="INSERT_ROWS",
                    body={"values": values},
                )
                .execute()
            )
            updates = result.get("updates", {})
            return self._format_response(
                data={
                    "spreadsheetId": spreadsheet_id,
                    "updatedRange": updates.get("updatedRange"),
                    "updatedRows": updates.get("updatedRows"),
                    "updatedCells": updates.get("updatedCells"),
                    "url": f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}/edit",
                }
            )
        except HttpError as e:
            return self._format_error(self._handle_api_error(e))

    def clear(self, spreadsheet_id: str, range: str) -> dict:
        """Clear values from cells (keeps formatting).

        Args:
            spreadsheet_id: Google Sheet ID
            range: A1 notation range to clear (e.g., "Sheet1!A1:C10")

        Returns:
            Response with cleared range info
        """
        try:
            result = (
                self.sheets.spreadsheets()
                .values()
                .clear(spreadsheetId=spreadsheet_id, range=range)
                .execute()
            )
            return self._format_response(
                data={
                    "spreadsheetId": spreadsheet_id,
                    "clearedRange": result.get("clearedRange"),
                    "url": f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}/edit",
                }
            )
        except HttpError as e:
            return self._format_error(self._handle_api_error(e))

    def add_sheet(self, spreadsheet_id: str, title: str) -> dict:
        """Add a new sheet to an existing spreadsheet.

        Args:
            spreadsheet_id: Google Sheet ID
            title: Name for the new sheet

        Returns:
            Response with new sheet info
        """
        try:
            request = {
                "requests": [
                    {
                        "addSheet": {
                            "properties": {
                                "title": title,
                            }
                        }
                    }
                ]
            }
            result = (
                self.sheets.spreadsheets()
                .batchUpdate(spreadsheetId=spreadsheet_id, body=request)
                .execute()
            )
            replies = result.get("replies", [{}])
            sheet_props = replies[0].get("addSheet", {}).get("properties", {})
            return self._format_response(
                data={
                    "spreadsheetId": spreadsheet_id,
                    "sheetId": sheet_props.get("sheetId"),
                    "sheetTitle": sheet_props.get("title"),
                    "url": f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}/edit",
                }
            )
        except HttpError as e:
            return self._format_error(self._handle_api_error(e))
