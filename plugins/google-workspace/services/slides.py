"""Google Slides service."""

from googleapiclient.errors import HttpError

from .base import BaseGoogleService


class SlidesService(BaseGoogleService):
    """Service for Google Slides operations."""

    def __init__(self, slides_service):
        """Initialize Slides service.

        Args:
            slides_service: Google Slides API service
        """
        self.slides = slides_service

    def create(self, title: str) -> dict:
        """Create a new Google Slides presentation.

        Args:
            title: Presentation title

        Returns:
            Response with presentation ID and URL
        """
        try:
            presentation = (
                self.slides.presentations().create(body={"title": title}).execute()
            )
            return self._format_response(
                data={
                    "presentationId": presentation.get("presentationId"),
                    "title": presentation.get("title"),
                    "url": f"https://docs.google.com/presentation/d/{presentation.get('presentationId')}/edit",
                }
            )
        except HttpError as e:
            return self._format_error(self._handle_api_error(e))

    def read(self, presentation_id: str) -> dict:
        """Read presentation content.

        Args:
            presentation_id: Google Slides presentation ID

        Returns:
            Response with presentation structure
        """
        try:
            presentation = (
                self.slides.presentations()
                .get(presentationId=presentation_id)
                .execute()
            )

            slides_info = []
            for slide in presentation.get("slides", []):
                slide_data = {
                    "objectId": slide.get("objectId"),
                    "elements": [],
                }

                for element in slide.get("pageElements", []):
                    if "shape" in element and "text" in element.get("shape", {}):
                        text_content = []
                        for text_elem in element["shape"]["text"].get(
                            "textElements", []
                        ):
                            if "textRun" in text_elem:
                                text_content.append(
                                    text_elem["textRun"].get("content", "")
                                )
                        if text_content:
                            slide_data["elements"].append(
                                {
                                    "objectId": element.get("objectId"),
                                    "type": "text",
                                    "content": "".join(text_content),
                                }
                            )

                slides_info.append(slide_data)

            return self._format_response(
                data={
                    "presentationId": presentation.get("presentationId"),
                    "title": presentation.get("title"),
                    "slideCount": len(slides_info),
                    "slides": slides_info,
                    "url": f"https://docs.google.com/presentation/d/{presentation_id}/edit",
                }
            )
        except HttpError as e:
            return self._format_error(self._handle_api_error(e))

    def add_slide(self, presentation_id: str, layout: str = "BLANK") -> dict:
        """Add a new slide to presentation.

        Args:
            presentation_id: Google Slides presentation ID
            layout: Predefined layout (BLANK, TITLE, TITLE_AND_BODY, etc.)

        Returns:
            Response with new slide info
        """
        try:
            import uuid

            slide_id = f"slide_{uuid.uuid4().hex[:8]}"

            requests = [
                {
                    "createSlide": {
                        "objectId": slide_id,
                        "slideLayoutReference": {"predefinedLayout": layout},
                    }
                }
            ]

            self.slides.presentations().batchUpdate(
                presentationId=presentation_id, body={"requests": requests}
            ).execute()

            return self._format_response(
                data={
                    "presentationId": presentation_id,
                    "slideId": slide_id,
                    "layout": layout,
                    "url": f"https://docs.google.com/presentation/d/{presentation_id}/edit",
                }
            )
        except HttpError as e:
            return self._format_error(self._handle_api_error(e))

    def update(self, presentation_id: str, slide_id: str, content: str) -> dict:
        """Update slide content by inserting a text box.

        Args:
            presentation_id: Google Slides presentation ID
            slide_id: Slide object ID
            content: Text content to add

        Returns:
            Response with updated slide info
        """
        try:
            import uuid

            textbox_id = f"textbox_{uuid.uuid4().hex[:8]}"

            requests = [
                {
                    "createShape": {
                        "objectId": textbox_id,
                        "shapeType": "TEXT_BOX",
                        "elementProperties": {
                            "pageObjectId": slide_id,
                            "size": {
                                "width": {"magnitude": 600, "unit": "PT"},
                                "height": {"magnitude": 400, "unit": "PT"},
                            },
                            "transform": {
                                "scaleX": 1,
                                "scaleY": 1,
                                "translateX": 50,
                                "translateY": 100,
                                "unit": "PT",
                            },
                        },
                    }
                },
                {
                    "insertText": {
                        "objectId": textbox_id,
                        "insertionIndex": 0,
                        "text": content,
                    }
                },
            ]

            self.slides.presentations().batchUpdate(
                presentationId=presentation_id, body={"requests": requests}
            ).execute()

            return self._format_response(
                data={
                    "presentationId": presentation_id,
                    "slideId": slide_id,
                    "textboxId": textbox_id,
                    "contentLength": len(content),
                    "url": f"https://docs.google.com/presentation/d/{presentation_id}/edit",
                }
            )
        except HttpError as e:
            return self._format_error(self._handle_api_error(e))
