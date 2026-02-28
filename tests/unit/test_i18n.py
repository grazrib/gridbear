"""Tests for core i18n module — ui domain and active languages cache."""

from unittest.mock import patch

from core.i18n import (
    _load_translations,
    clear_cache,
    get_active_languages,
    get_translation,
    invalidate_language_cache,
    resolve_language,
    set_language,
)


class TestUiDomain:
    """Test that the 'ui' domain resolves to ui/i18n/."""

    def setup_method(self):
        clear_cache()

    def test_ui_domain_returns_none_when_no_po_file(self):
        """ui domain with non-existent language returns None."""
        result = _load_translations("ui", "zz")
        assert result is None

    def test_ui_domain_loads_existing_po(self, tmp_path):
        """ui domain loads from ui/i18n/{lang}.po."""
        po_content = (
            'msgid ""\nmsgstr ""\n"Language: test\\n"\n\nmsgid "Hello"\nmsgstr "Ciao"\n'
        )
        with patch("core.i18n.BASE_DIR", tmp_path):
            i18n_dir = tmp_path / "ui" / "i18n"
            i18n_dir.mkdir(parents=True)
            (i18n_dir / "test.po").write_text(po_content)
            clear_cache()

            result = get_translation("ui", "Hello", "test")
            assert result == "Ciao"

    def test_english_returns_original(self):
        """English source language returns original string."""
        result = get_translation("ui", "Hello", "en")
        assert result == "Hello"


class TestActiveLanguagesCache:
    """Test get_active_languages() with DB caching."""

    def test_returns_cached_languages(self):
        """Should return cached dict after first call."""
        mock_rows = [
            {
                "code": "en",
                "name": "English",
                "active": True,
                "direction": "ltr",
                "is_default": True,
            },
            {
                "code": "it",
                "name": "Italiano",
                "active": True,
                "direction": "ltr",
                "is_default": False,
            },
        ]
        with patch("core.i18n._fetch_active_languages", return_value=mock_rows):
            invalidate_language_cache()
            langs = get_active_languages()
            assert "en" in langs
            assert "it" in langs
            assert langs["en"]["is_default"] is True

    def test_invalidate_clears_cache(self):
        """invalidate_language_cache() forces re-fetch."""
        with patch("core.i18n._fetch_active_languages") as mock_fetch:
            mock_fetch.return_value = [
                {
                    "code": "en",
                    "name": "English",
                    "active": True,
                    "direction": "ltr",
                    "is_default": True,
                },
            ]
            invalidate_language_cache()
            get_active_languages()
            get_active_languages()  # second call, should be cached
            assert mock_fetch.call_count == 1

            invalidate_language_cache()
            get_active_languages()
            assert mock_fetch.call_count == 2


class TestJinja2Integration:
    """Test _() global in Jinja2 templates."""

    def test_translate_function_registered(self):
        """templates.env.globals should have _() function."""
        from ui.jinja_env import templates

        assert "_" in templates.env.globals
        assert callable(templates.env.globals["_"])

    def test_translate_returns_english_by_default(self):
        """_() returns original string when language is English."""
        from ui.jinja_env import templates

        set_language("en")
        translate = templates.env.globals["_"]
        assert translate("Hello") == "Hello"


class TestI18nMiddleware:
    """Test language resolution logic."""

    def test_resolve_language_from_user_locale(self):
        """User with locale set should get that language."""
        with patch(
            "core.i18n.get_active_languages",
            return_value={
                "en": {"is_default": True},
                "it": {"is_default": False},
            },
        ):
            assert resolve_language(user={"locale": "it"}) == "it"

    def test_resolve_falls_back_to_default(self):
        """No user or unknown locale falls back to default language."""
        with patch(
            "core.i18n.get_active_languages",
            return_value={
                "en": {"is_default": True},
            },
        ):
            with patch("core.i18n.get_default_language", return_value="en"):
                assert resolve_language(user=None) == "en"

    def test_resolve_accept_language_header(self):
        """Accept-Language header used when no user locale."""
        with patch(
            "core.i18n.get_active_languages",
            return_value={
                "en": {"is_default": True},
                "it": {"is_default": False},
            },
        ):
            with patch("core.i18n.get_default_language", return_value="en"):
                result = resolve_language(
                    user={"locale": None},
                    accept_language="it-IT,it;q=0.9,en;q=0.8",
                )
                assert result == "it"
