"""ORM model registry entry point for core models.

Discovered by Registry._scan_directory() via rglob("models.py").
Importing this module triggers ModelMeta registration for all core models.
"""

from core.config_models import User  # noqa: F401 — forces User registration
from core.models.company import Company  # noqa: F401
from core.models.company_user import CompanyUser  # noqa: F401
