"""Tests for gridbear i18n CLI commands."""

from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from cli.app import app

runner = CliRunner()


class TestI18nExtract:
    def test_extract_all(self):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            result = runner.invoke(app, ["i18n", "extract"])
            assert result.exit_code == 0

    def test_extract_domain(self):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            result = runner.invoke(app, ["i18n", "extract", "--domain", "ui"])
            assert result.exit_code == 0

    def test_extract_failure(self):
        """Should report failure when extraction script exits non-zero."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1)
            result = runner.invoke(app, ["i18n", "extract"])
            assert result.exit_code == 1


class TestI18nStatus:
    def test_status_shows_table(self):
        """Status command should show translation statistics."""
        result = runner.invoke(app, ["i18n", "status"])
        assert result.exit_code == 0
        # Should contain our ui/it domain
        assert "ui" in result.output
        assert "it" in result.output

    def test_status_filter_by_lang(self):
        """Filtering by language should work."""
        result = runner.invoke(app, ["i18n", "status", "--lang", "it"])
        assert result.exit_code == 0
        assert "it" in result.output

    def test_status_unknown_lang(self):
        """Filtering by non-existent language shows no files."""
        result = runner.invoke(app, ["i18n", "status", "--lang", "zz"])
        assert result.exit_code == 0
        assert "No .po files found" in result.output


class TestI18nUpdate:
    def test_update_missing_pot(self):
        """Should fail when .pot file doesn't exist."""
        result = runner.invoke(app, ["i18n", "update", "--lang", "fr"])
        assert result.exit_code == 1
        assert "not found" in result.output.lower() or "Template" in result.output
