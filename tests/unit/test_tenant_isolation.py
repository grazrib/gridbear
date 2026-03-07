"""Tests for multi-tenancy ORM isolation (Phase 1).

All tests are unit tests — no live DB required.
Mock _execute_one/_execute_all/_execute_rowcount where needed.
"""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from core.orm import fields
from core.orm.exceptions import (
    TenantAccessError,
    TenantContextError,
    TenantSafetyError,
)
from core.orm.model import Model, ModelMeta
from core.orm.query import domain_to_sql
from core.tenant import SUPERADMIN_BYPASS, clear_tenant, get_tenant, set_tenant

# ── Test fixtures: mock model classes ─────────────────────────────


class _SharedModel(Model):
    """Non-tenant model (default behavior)."""

    _schema = "test"
    _name = "shared_items"
    name = fields.Text(required=True)


class _TenantModel(Model):
    """Tenant-aware model."""

    _schema = "test"
    _name = "tenant_items"
    _tenant_field = "company_id"
    name = fields.Text(required=True)


@pytest.fixture(autouse=True)
def _clean_tenant():
    """Reset tenant context before/after each test."""
    clear_tenant()
    yield
    clear_tenant()


# ── 1. TenantContext ──────────────────────────────────────────────


class TestTenantContext:
    def test_default_is_none(self):
        assert get_tenant() is None

    def test_set_and_get(self):
        set_tenant(42)
        assert get_tenant() == 42

    def test_clear(self):
        set_tenant(42)
        clear_tenant()
        assert get_tenant() is None

    def test_superadmin_bypass(self):
        set_tenant(SUPERADMIN_BYPASS)
        assert get_tenant() == SUPERADMIN_BYPASS

    def test_concurrent_async_isolation(self):
        """Each asyncio Task gets its own tenant context."""
        results = {}

        async def _set_and_read(task_id, company_id):
            set_tenant(company_id)
            await asyncio.sleep(0.01)  # yield control
            results[task_id] = get_tenant()

        async def _run():
            await asyncio.gather(
                _set_and_read("a", 1),
                _set_and_read("b", 2),
                _set_and_read("c", 3),
            )

        asyncio.run(_run())
        assert results == {"a": 1, "b": 2, "c": 3}


# ── 2. DomainToSql ───────────────────────────────────────────────


class TestDomainToSqlTenant:
    def test_shared_model_no_filter(self):
        """Non-tenant model should not inject any filter."""
        sql, params = domain_to_sql([("name", "=", "x")], _SharedModel)
        assert '"company_id"' not in sql
        assert params == ["x"]

    def test_tenant_model_injection(self):
        """Tenant model should prepend company_id filter."""
        set_tenant(5)
        sql, params = domain_to_sql([("name", "=", "x")], _TenantModel)
        assert '"company_id" = %s' in sql
        assert 5 in params
        assert "x" in params

    def test_tenant_model_empty_domain(self):
        """Even with empty domain, tenant filter should be added."""
        set_tenant(5)
        sql, params = domain_to_sql([], _TenantModel)
        assert '"company_id" = %s' in sql
        assert params == [5]

    def test_fail_closed_no_context(self):
        """Should raise TenantContextError when no context is set."""
        with pytest.raises(TenantContextError, match="No tenant context"):
            domain_to_sql([], _TenantModel)

    def test_superadmin_bypass_no_filter(self):
        """SUPERADMIN_BYPASS should not inject any filter."""
        set_tenant(SUPERADMIN_BYPASS)
        sql, params = domain_to_sql([("name", "=", "x")], _TenantModel)
        assert '"company_id"' not in sql


# ── 3. Create enforcement ────────────────────────────────────────


class TestCreateTenantEnforcement:
    def test_create_raises_without_context(self):
        """create() should fail on tenant model without context."""
        with patch.object(_TenantModel, "_execute_one", new_callable=AsyncMock):
            with pytest.raises(TenantContextError, match="No tenant context"):
                asyncio.run(_TenantModel.create(name="x"))

    def test_create_injects_company_id(self):
        """create() should inject company_id from context."""
        mock_row = {"id": 1, "name": "x", "company_id": 5}
        set_tenant(5)
        with patch.object(
            _TenantModel, "_execute_one", new_callable=AsyncMock, return_value=mock_row
        ) as mock_exec:
            result = asyncio.run(_TenantModel.create(name="x"))
            assert result["company_id"] == 5
            # Verify company_id was in the INSERT
            call_query = mock_exec.call_args[0][0]
            assert '"company_id"' in call_query

    def test_create_superadmin_requires_explicit(self):
        """create() with SUPERADMIN_BYPASS should raise if company_id not provided."""
        set_tenant(SUPERADMIN_BYPASS)
        with patch.object(_TenantModel, "_execute_one", new_callable=AsyncMock):
            with pytest.raises(TenantContextError, match="SUPERADMIN_BYPASS"):
                asyncio.run(_TenantModel.create(name="x"))

    def test_create_superadmin_explicit_ok(self):
        """create() with SUPERADMIN_BYPASS and explicit company_id should work."""
        set_tenant(SUPERADMIN_BYPASS)
        mock_row = {"id": 1, "name": "x", "company_id": 99}
        with patch.object(
            _TenantModel, "_execute_one", new_callable=AsyncMock, return_value=mock_row
        ):
            result = asyncio.run(_TenantModel.create(name="x", company_id=99))
            assert result["company_id"] == 99

    def test_shared_model_create_no_tenant_needed(self):
        """create() on shared model should work without tenant context."""
        mock_row = {"id": 1, "name": "x"}
        with patch.object(
            _SharedModel, "_execute_one", new_callable=AsyncMock, return_value=mock_row
        ):
            result = asyncio.run(_SharedModel.create(name="x"))
            assert result["name"] == "x"


# ── 4. Write/Delete enforcement ──────────────────────────────────


class TestWriteDeleteTenantEnforcement:
    def test_write_cross_tenant_raises(self):
        """write() should raise TenantAccessError on cross-tenant record."""
        set_tenant(5)
        # write returns 0 (no match in tenant), then check finds the record exists
        with (
            patch.object(
                _TenantModel,
                "_execute_rowcount",
                new_callable=AsyncMock,
                return_value=0,
            ),
            patch.object(
                _TenantModel,
                "_execute_all",
                new_callable=AsyncMock,
                return_value=[{"1": 1}],  # record exists in another tenant
            ),
        ):
            with pytest.raises(TenantAccessError, match="belongs to another tenant"):
                asyncio.run(_TenantModel.write(42, name="y"))

    def test_write_own_tenant_ok(self):
        """write() should succeed on own tenant record."""
        set_tenant(5)
        with patch.object(
            _TenantModel,
            "_execute_rowcount",
            new_callable=AsyncMock,
            return_value=1,
        ):
            result = asyncio.run(_TenantModel.write(42, name="y"))
            assert result == 1

    def test_delete_cross_tenant_raises(self):
        """delete() should raise TenantAccessError on cross-tenant record."""
        set_tenant(5)
        with (
            patch.object(
                _TenantModel,
                "_execute_rowcount",
                new_callable=AsyncMock,
                return_value=0,
            ),
            patch.object(
                _TenantModel,
                "_execute_all",
                new_callable=AsyncMock,
                return_value=[{"1": 1}],
            ),
        ):
            with pytest.raises(TenantAccessError, match="belongs to another tenant"):
                asyncio.run(_TenantModel.delete(42))

    def test_delete_nonexistent_returns_zero(self):
        """delete() should return 0 for nonexistent record (not raise)."""
        set_tenant(5)
        with (
            patch.object(
                _TenantModel,
                "_execute_rowcount",
                new_callable=AsyncMock,
                return_value=0,
            ),
            patch.object(
                _TenantModel,
                "_execute_all",
                new_callable=AsyncMock,
                return_value=[],  # record doesn't exist at all
            ),
        ):
            result = asyncio.run(_TenantModel.delete(42))
            assert result == 0

    def test_shared_model_write_no_tenant_check(self):
        """write() on shared model should not add tenant clause."""
        with patch.object(
            _SharedModel,
            "_execute_rowcount",
            new_callable=AsyncMock,
            return_value=1,
        ) as mock_exec:
            result = asyncio.run(_SharedModel.write(1, name="y"))
            assert result == 1
            call_query = mock_exec.call_args[0][0]
            assert "company_id" not in call_query


# ── 5. Raw query safety ──────────────────────────────────────────


class TestRawQuerySafety:
    def test_raw_search_raises_without_company_id(self):
        """raw_search on tenant model should raise if query lacks company_id."""
        set_tenant(5)
        with pytest.raises(TenantSafetyError, match="must include"):
            asyncio.run(
                _TenantModel.raw_search("SELECT * FROM {table} WHERE name = %s")
            )

    def test_raw_search_ok_with_company_id_in_query(self):
        """raw_search should work if company_id appears in the query string."""
        set_tenant(5)
        with patch.object(
            _TenantModel,
            "_execute_all",
            new_callable=AsyncMock,
            return_value=[],
        ):
            result = asyncio.run(
                _TenantModel.raw_search(
                    "SELECT * FROM {table} WHERE company_id = %s", (5,)
                )
            )
            assert result == []

    def test_raw_search_bypass_with_warning(self):
        """raw_search with _bypass_tenant should log a warning but not raise."""
        set_tenant(5)
        with (
            patch.object(
                _TenantModel,
                "_execute_all",
                new_callable=AsyncMock,
                return_value=[],
            ),
            patch("core.orm.model._logger") as mock_logger,
        ):
            asyncio.run(
                _TenantModel.raw_search("SELECT * FROM {table}", _bypass_tenant=True)
            )
            mock_logger.warning.assert_called_once()

    def test_raw_execute_raises_without_company_id(self):
        """raw_execute on tenant model should raise if query lacks company_id."""
        set_tenant(5)
        with pytest.raises(TenantSafetyError):
            asyncio.run(_TenantModel.raw_execute("DELETE FROM {table} WHERE id = %s"))

    def test_shared_model_raw_no_check(self):
        """raw_search on shared model should not enforce tenant safety."""
        with patch.object(
            _SharedModel,
            "_execute_all",
            new_callable=AsyncMock,
            return_value=[],
        ):
            result = asyncio.run(_SharedModel.raw_search("SELECT * FROM {table}"))
            assert result == []


# ── 6. Upsert conflict fields ────────────────────────────────────


class TestUpsertConflictFields:
    def test_company_id_added_to_conflict_fields(self):
        """create_or_update should auto-add company_id to _conflict_fields."""
        set_tenant(5)
        mock_row = {"id": 1, "name": "x", "company_id": 5}
        with patch.object(
            _TenantModel, "_execute_one", new_callable=AsyncMock, return_value=mock_row
        ) as mock_exec:
            asyncio.run(
                _TenantModel.create_or_update(_conflict_fields=("name",), name="x")
            )
            call_query = mock_exec.call_args[0][0]
            # Should have company_id in ON CONFLICT
            assert "company_id" in call_query
            assert "ON CONFLICT" in call_query

    def test_conflict_fields_not_duplicated(self):
        """If company_id already in _conflict_fields, don't add it again."""
        set_tenant(5)
        mock_row = {"id": 1, "name": "x", "company_id": 5}
        with patch.object(
            _TenantModel, "_execute_one", new_callable=AsyncMock, return_value=mock_row
        ) as mock_exec:
            asyncio.run(
                _TenantModel.create_or_update(
                    _conflict_fields=("company_id", "name"), name="x"
                )
            )
            call_query = mock_exec.call_args[0][0]
            # Should not have company_id twice
            conflict_section = call_query.split("ON CONFLICT")[1].split(")")[0]
            assert conflict_section.count("company_id") == 1


# ── 7. ModelMeta auto-injection ───────────────────────────────────


class TestModelMetaAutoInjection:
    def test_tenant_field_auto_injects_fk(self):
        """_tenant_field should auto-inject a ForeignKey field."""
        assert "company_id" in _TenantModel._fields
        assert "company_id" in _TenantModel._field_names
        fk = _TenantModel._fields["company_id"]
        assert isinstance(fk, fields.ForeignKey)
        assert fk.required is True

    def test_shared_model_no_injection(self):
        """Shared model should not have company_id injected."""
        assert "company_id" not in _SharedModel._fields
        assert _SharedModel._tenant_field is None

    def test_tenant_field_inherited(self):
        """Subclass should inherit _tenant_field from parent."""

        class _ChildTenant(_TenantModel):
            _schema = "test"
            _name = "child_tenant_items"
            extra = fields.Text()

        assert _ChildTenant._tenant_field == "company_id"
        assert "company_id" in _ChildTenant._fields

        # Cleanup: remove from ModelMeta registry to avoid interference
        ModelMeta._all_models = [
            m for m in ModelMeta._all_models if m is not _ChildTenant
        ]
