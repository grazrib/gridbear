"""Google Workspace services."""

from .base import BaseGoogleService
from .docs import DocsService
from .drive import DriveService
from .sheets import SheetsService
from .slides import SlidesService

__all__ = [
    "BaseGoogleService",
    "DocsService",
    "SheetsService",
    "SlidesService",
    "DriveService",
]
