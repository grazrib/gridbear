"""Internationalization module for GridBear.

Odoo-style translation system using:
- _() function for translatable strings
- ContextVar for per-request language
- .po files for translations
"""

import gettext
from contextvars import ContextVar
from pathlib import Path
from typing import Callable

from config.logging_config import logger

# Current language context (per-request/per-user)
current_lang: ContextVar[str] = ContextVar("lang", default="en")

# Base directory for locale files
BASE_DIR = Path(__file__).resolve().parent.parent

# Cache for loaded translations
_translations: dict[str, dict[str, gettext.GNUTranslations | None]] = {}

# Default language
DEFAULT_LANG = "en"


def _load_translations(domain: str, lang: str) -> gettext.GNUTranslations | None:
    """Load translations for a specific domain and language.

    Args:
        domain: Translation domain (e.g., 'telegram', 'discord', 'core')
        lang: Language code (e.g., 'it', 'en', 'fr')

    Returns:
        GNUTranslations object or None if not found
    """
    cache_key = f"{domain}:{lang}"
    if cache_key in _translations.get(domain, {}):
        return _translations.get(domain, {}).get(cache_key)

    # Initialize domain cache
    if domain not in _translations:
        _translations[domain] = {}

    # Determine locale directory based on domain
    if domain == "core":
        locale_dir = BASE_DIR / "core" / "i18n"
    elif domain == "ui":
        locale_dir = BASE_DIR / "ui" / "i18n"
    else:
        # Check plugins directory via resolver
        from core.registry import get_plugin_path

        plugin_path = get_plugin_path(domain)
        if plugin_path is None:
            # Fallback
            locale_dir = BASE_DIR / "plugins" / domain / "i18n"
        else:
            locale_dir = plugin_path / "i18n"

    if not locale_dir.exists():
        _translations[domain][cache_key] = None
        return None

    try:
        # Try to load .mo file first (compiled), then fall back to .po
        mo_file = locale_dir / f"{lang}.mo"
        po_file = locale_dir / f"{lang}.po"

        if mo_file.exists():
            with open(mo_file, "rb") as f:
                trans = gettext.GNUTranslations(f)
                _translations[domain][cache_key] = trans
                logger.debug(f"Loaded translations: {domain}/{lang} (compiled)")
                return trans
        elif po_file.exists():
            # Parse .po file manually (simplified)
            trans = _load_po_file(po_file)
            _translations[domain][cache_key] = trans
            logger.debug(f"Loaded translations: {domain}/{lang} (source)")
            return trans
        else:
            _translations[domain][cache_key] = None
            return None
    except Exception as e:
        logger.warning(f"Failed to load translations for {domain}/{lang}: {e}")
        _translations[domain][cache_key] = None
        return None


class SimpleTranslations:
    """Simple translations class that mimics GNUTranslations interface."""

    def __init__(self, catalog: dict[str, str]):
        self._catalog = catalog

    def gettext(self, message: str) -> str:
        return self._catalog.get(message, message)

    def ngettext(self, singular: str, plural: str, n: int) -> str:
        if n == 1:
            return self._catalog.get(singular, singular)
        return self._catalog.get(plural, plural)


def _load_po_file(po_file: Path) -> SimpleTranslations:
    """Parse a .po file and return a SimpleTranslations object.

    This is a simplified parser that handles basic msgid/msgstr pairs.
    """
    catalog = {}
    current_msgid = None
    current_msgstr = []
    in_msgstr = False

    with open(po_file, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()

            if line.startswith("msgid "):
                # Save previous entry
                if current_msgid is not None and current_msgstr:
                    msgstr = "".join(current_msgstr)
                    if msgstr:  # Only store non-empty translations
                        catalog[current_msgid] = msgstr

                # Start new entry
                current_msgid = _parse_po_string(line[6:])
                current_msgstr = []
                in_msgstr = False

            elif line.startswith("msgstr "):
                in_msgstr = True
                current_msgstr.append(_parse_po_string(line[7:]))

            elif line.startswith('"') and line.endswith('"'):
                # Continuation line
                text = _parse_po_string(line)
                if in_msgstr:
                    current_msgstr.append(text)
                elif current_msgid is not None:
                    current_msgid += text

    # Don't forget the last entry
    if current_msgid is not None and current_msgstr:
        msgstr = "".join(current_msgstr)
        if msgstr:
            catalog[current_msgid] = msgstr

    return SimpleTranslations(catalog)


def _parse_po_string(s: str) -> str:
    """Parse a quoted string from .po file."""
    s = s.strip()
    if s.startswith('"') and s.endswith('"'):
        s = s[1:-1]
    # Handle escape sequences
    s = s.replace("\\n", "\n")
    s = s.replace("\\t", "\t")
    s = s.replace('\\"', '"')
    s = s.replace("\\\\", "\\")
    return s


def get_translation(domain: str, message: str, lang: str | None = None) -> str:
    """Get translation for a message.

    Args:
        domain: Translation domain
        message: Message to translate
        lang: Language code (uses current_lang if not specified)

    Returns:
        Translated message or original if not found
    """
    if lang is None:
        lang = current_lang.get()

    # English is the source language, no translation needed
    if lang == "en":
        return message

    trans = _load_translations(domain, lang)
    if trans is None:
        return message

    return trans.gettext(message)


def make_translator(domain: str) -> Callable[[str], str]:
    """Create a translator function for a specific domain.

    Usage:
        _ = make_translator("myplugin")
        message = _("Not authorized.")
    """

    def translate(message: str) -> str:
        return get_translation(domain, message)

    return translate


# Convenience function for core translations
def _(message: str) -> str:
    """Translate a core message."""
    return get_translation("core", message)


def set_language(lang: str) -> None:
    """Set the current language for this context."""
    current_lang.set(lang)


def get_language() -> str:
    """Get the current language."""
    return current_lang.get()


# ── Active languages cache ──────────────────────────────────────

_active_langs_cache: dict[str, dict] | None = None

_FALLBACK_LANGUAGES = [
    {
        "code": "en",
        "name": "English",
        "active": True,
        "direction": "ltr",
        "is_default": True,
    }
]


def _fetch_active_languages() -> list[dict]:
    """Fetch active languages from DB (sync)."""
    try:
        from core.registry import get_database

        db = get_database()
        if not db:
            return _FALLBACK_LANGUAGES
        with db.acquire_sync() as conn:
            cur = conn.execute(
                "SELECT code, name, active, direction, date_format, is_default "
                "FROM i18n.languages WHERE active = TRUE ORDER BY code"
            )
            rows = cur.fetchall()
            if not rows:
                return _FALLBACK_LANGUAGES
            return [dict(r) for r in rows]
    except Exception as e:
        logger.debug("Could not fetch languages from DB: %s", e)
        return _FALLBACK_LANGUAGES


def get_active_languages() -> dict[str, dict]:
    """Get active languages (cached). Returns {code: {name, direction, ...}}."""
    global _active_langs_cache
    if _active_langs_cache is not None:
        return _active_langs_cache
    rows = _fetch_active_languages()
    _active_langs_cache = {r["code"]: r for r in rows}
    return _active_langs_cache


def invalidate_language_cache() -> None:
    """Invalidate the active languages cache (call after admin changes)."""
    global _active_langs_cache
    _active_langs_cache = None


def get_default_language() -> str:
    """Get the default language code."""
    langs = get_active_languages()
    for code, info in langs.items():
        if info.get("is_default"):
            return code
    return DEFAULT_LANG


def resolve_language(user: dict | None = None, accept_language: str = "") -> str:
    """Resolve the best language for a request.

    Priority: 1) user.locale  2) Accept-Language header  3) default.
    """
    active = get_active_languages()

    # 1. User's saved locale
    if user and isinstance(user, dict):
        locale = user.get("locale")
        if locale and locale in active:
            return locale

    # 2. Accept-Language header
    for part in accept_language.split(","):
        lang = part.split(";")[0].strip().split("-")[0].lower()
        if lang in active:
            return lang

    # 3. Default language
    return get_default_language()


def clear_cache() -> None:
    """Clear the translation cache (useful for development)."""
    global _translations
    _translations = {}
