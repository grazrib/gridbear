#!/usr/bin/env python3

import asyncio
import json
import os
import sys
from typing import Any

import httpx


def _parse_csv_set(raw: str) -> set[str]:
    raw = (raw or "").strip()
    if not raw:
        return set()
    return {part.strip() for part in raw.split(",") if part.strip()}


def _parse_int(raw: str, default: int) -> int:
    try:
        return int(raw)
    except Exception:
        return default


def _parse_domain(domain: Any) -> list[Any]:
    if domain is None or domain == "":
        return []
    if isinstance(domain, list):
        return domain
    if isinstance(domain, str):
        parsed = json.loads(domain)
        return _parse_domain(parsed)
    if isinstance(domain, dict):
        conditions = domain.get("conditions")
        if isinstance(conditions, list):
            normalized = []
            for c in conditions:
                if not isinstance(c, dict):
                    continue
                field = c.get("field")
                operator = c.get("operator")
                value = c.get("value")
                if field and operator is not None:
                    normalized.append([field, operator, value])
            return normalized
    raise ValueError("Invalid domain format")


class OdooJsonRpcClient:
    def __init__(
        self,
        base_url: str,
        db: str,
        username: str,
        api_key: str,
        timeout_seconds: int = 30,
    ):
        self.base_url = base_url.rstrip("/")
        self.db = db
        self.username = username
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds
        self._uid: int | None = None
        self._client = httpx.Client(timeout=self.timeout_seconds)

    def close(self) -> None:
        self._client.close()

    def _call(self, service: str, method: str, args: list[Any]) -> Any:
        payload = {
            "jsonrpc": "2.0",
            "method": "call",
            "params": {"service": service, "method": method, "args": args},
            "id": 1,
        }
        r = self._client.post(f"{self.base_url}/jsonrpc", json=payload)
        r.raise_for_status()
        data = r.json()
        if "error" in data and data["error"]:
            raise RuntimeError(
                data["error"].get("data", {}).get("message")
                or data["error"].get("message")
                or "Odoo JSON-RPC error"
            )
        return data.get("result")

    def authenticate(self) -> int:
        if self._uid is not None:
            return self._uid
        uid = self._call(
            "common", "authenticate", [self.db, self.username, self.api_key, {}]
        )
        if not uid:
            raise RuntimeError("Authentication failed")
        self._uid = int(uid)
        return self._uid

    def execute_kw(
        self,
        model: str,
        method: str,
        args: list[Any] | None = None,
        kwargs: dict[str, Any] | None = None,
    ) -> Any:
        uid = self.authenticate()
        args = args or []
        kwargs = kwargs or {}
        return self._call(
            "object",
            "execute_kw",
            [self.db, uid, self.api_key, model, method, args, kwargs],
        )

    def common_version(self) -> Any:
        return self._call("common", "version", [])


class OdooMCPServer:
    def __init__(self, client: OdooJsonRpcClient, instance_name: str):
        self.client = client
        self.instance_name = instance_name
        self.allowed_models = _parse_csv_set(os.environ.get("ODOO_ALLOWED_MODELS", ""))
        self.allow_unsafe_execute_kw = os.environ.get(
            "ODOO_ALLOW_UNSAFE_EXECUTE_KW", "0"
        ) in ("1", "true", "True", "on")
        self.allowed_methods = _parse_csv_set(
            os.environ.get("ODOO_ALLOWED_METHODS", "")
        )
        self.max_smart_fields = _parse_int(
            os.environ.get("ODOO_MAX_SMART_FIELDS", ""), 20
        )
        self.validate_fields = os.environ.get("ODOO_VALIDATE_FIELDS", "1") in (
            "1",
            "true",
            "True",
            "on",
        )
        self.tools = [
            {
                "name": "odoo_execute_kw",
                "description": f"Execute Odoo model method on {instance_name}.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "model": {"type": "string"},
                        "method": {"type": "string"},
                        "args": {"type": "array"},
                        "kwargs": {"type": "object"},
                    },
                    "required": ["model", "method"],
                },
            },
            {
                "name": "odoo_version",
                "description": f"Get Odoo server version for {instance_name}.",
                "inputSchema": {"type": "object", "properties": {}},
            },
            {
                "name": "odoo_whoami",
                "description": f"Return authenticated user info for {instance_name}.",
                "inputSchema": {"type": "object", "properties": {}},
            },
            {
                "name": "odoo_search_read",
                "description": f"Search and read records from {instance_name}.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "model": {"type": "string"},
                        "domain": {
                            "anyOf": [
                                {"type": "array"},
                                {"type": "string"},
                                {"type": "object"},
                            ]
                        },
                        "fields": {"type": "array"},
                        "limit": {"type": "integer"},
                        "offset": {"type": "integer"},
                        "order": {"type": "string"},
                        "context": {"type": "object"},
                    },
                    "required": ["model"],
                },
            },
            {
                "name": "odoo_search",
                "description": f"Search records and return ids from {instance_name}.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "model": {"type": "string"},
                        "domain": {
                            "anyOf": [
                                {"type": "array"},
                                {"type": "string"},
                                {"type": "object"},
                            ]
                        },
                        "limit": {"type": "integer"},
                        "offset": {"type": "integer"},
                        "order": {"type": "string"},
                        "context": {"type": "object"},
                    },
                    "required": ["model"],
                },
            },
            {
                "name": "odoo_count",
                "description": f"Count records matching a domain on {instance_name}.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "model": {"type": "string"},
                        "domain": {
                            "anyOf": [
                                {"type": "array"},
                                {"type": "string"},
                                {"type": "object"},
                            ]
                        },
                        "context": {"type": "object"},
                    },
                    "required": ["model"],
                },
            },
            {
                "name": "odoo_read",
                "description": f"Read records by ids from {instance_name}.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "model": {"type": "string"},
                        "ids": {"type": "array"},
                        "fields": {"type": "array"},
                        "context": {"type": "object"},
                    },
                    "required": ["model", "ids"],
                },
            },
            {
                "name": "odoo_fields_get",
                "description": f"Inspect model fields on {instance_name}.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "model": {"type": "string"},
                        "attributes": {"type": "array"},
                        "context": {"type": "object"},
                    },
                    "required": ["model"],
                },
            },
            {
                "name": "odoo_list_models",
                "description": f"List available models (requires ir.model access) on {instance_name}.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "limit": {"type": "integer"},
                        "context": {"type": "object"},
                    },
                },
            },
            {
                "name": "odoo_check_access_rights",
                "description": f"Check model access rights (read/write/create/unlink) on {instance_name}.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "model": {"type": "string"},
                        "operation": {"type": "string"},
                        "raise_exception": {"type": "boolean"},
                        "context": {"type": "object"},
                    },
                    "required": ["model", "operation"],
                },
            },
            {
                "name": "odoo_check_access_rule",
                "description": f"Check record rules for ids on {instance_name}.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "model": {"type": "string"},
                        "ids": {"type": "array"},
                        "operation": {"type": "string"},
                        "raise_exception": {"type": "boolean"},
                        "context": {"type": "object"},
                    },
                    "required": ["model", "ids", "operation"],
                },
            },
            {
                "name": "odoo_create",
                "description": f"Create a record on {instance_name}.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "model": {"type": "string"},
                        "values": {"type": "object"},
                        "context": {"type": "object"},
                    },
                    "required": ["model", "values"],
                },
            },
            {
                "name": "odoo_write",
                "description": f"Write fields on records on {instance_name}.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "model": {"type": "string"},
                        "ids": {"type": "array"},
                        "values": {"type": "object"},
                        "context": {"type": "object"},
                    },
                    "required": ["model", "ids", "values"],
                },
            },
            {
                "name": "odoo_unlink",
                "description": f"Delete records on {instance_name}.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "model": {"type": "string"},
                        "ids": {"type": "array"},
                        "context": {"type": "object"},
                    },
                    "required": ["model", "ids"],
                },
            },
            {
                "name": "search_records",
                "description": f"Alias for odoo_search_read on {instance_name}.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "model": {"type": "string"},
                        "domain": {
                            "anyOf": [
                                {"type": "array"},
                                {"type": "string"},
                                {"type": "object"},
                            ]
                        },
                        "fields": {"type": "array"},
                        "limit": {"type": "integer"},
                        "offset": {"type": "integer"},
                        "order": {"type": "string"},
                        "context": {"type": "object"},
                    },
                    "required": ["model"],
                },
            },
            {
                "name": "get_record",
                "description": f"Alias for odoo_read (single id) on {instance_name}.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "model": {"type": "string"},
                        "record_id": {"type": "integer"},
                        "fields": {"type": "array"},
                        "context": {"type": "object"},
                    },
                    "required": ["model", "record_id"],
                },
            },
            {
                "name": "create_record",
                "description": f"Alias for odoo_create on {instance_name}.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "model": {"type": "string"},
                        "values": {"type": "object"},
                        "context": {"type": "object"},
                    },
                    "required": ["model", "values"],
                },
            },
            {
                "name": "update_record",
                "description": f"Alias for odoo_write on {instance_name}.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "model": {"type": "string"},
                        "ids": {"type": "array"},
                        "values": {"type": "object"},
                        "context": {"type": "object"},
                    },
                    "required": ["model", "ids", "values"],
                },
            },
            {
                "name": "delete_record",
                "description": f"Alias for odoo_unlink on {instance_name}.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "model": {"type": "string"},
                        "ids": {"type": "array"},
                        "context": {"type": "object"},
                    },
                    "required": ["model", "ids"],
                },
            },
            {
                "name": "count_records",
                "description": f"Alias for odoo_count on {instance_name}.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "model": {"type": "string"},
                        "domain": {
                            "anyOf": [
                                {"type": "array"},
                                {"type": "string"},
                                {"type": "object"},
                            ]
                        },
                        "context": {"type": "object"},
                    },
                    "required": ["model"],
                },
            },
            {
                "name": "list_models",
                "description": f"Alias for odoo_list_models on {instance_name}.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "limit": {"type": "integer"},
                        "context": {"type": "object"},
                    },
                },
            },
            {
                "name": "get_fields",
                "description": f"Alias for odoo_fields_get on {instance_name}.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "model": {"type": "string"},
                        "attributes": {"type": "array"},
                        "context": {"type": "object"},
                    },
                    "required": ["model"],
                },
            },
        ]

    def _assert_model_allowed(self, model: str) -> None:
        model = (model or "").strip()
        if not model:
            raise ValueError("Missing model")
        if self.allowed_models and model not in self.allowed_models:
            raise PermissionError(f"Model not allowed: {model}")

    def _assert_method_allowed(self, method: str) -> None:
        method = (method or "").strip()
        if not method:
            raise ValueError("Missing method")
        if self.allowed_methods and method not in self.allowed_methods:
            raise PermissionError(f"Method not allowed: {method}")

    def _fields_get(
        self,
        model: str,
        attributes: list[str] | None = None,
        context: dict | None = None,
    ) -> dict:
        self._assert_model_allowed(model)
        context = context or {}
        attributes = attributes or [
            "string",
            "type",
            "required",
            "readonly",
            "relation",
            "store",
            "compute",
            "searchable",
        ]
        return self.client.execute_kw(
            model,
            "fields_get",
            [],
            {"attributes": attributes, "context": context},
        )

    def _score_field_importance(self, field_name: str, field_info: dict) -> int:
        if field_name in {"id", "name", "display_name", "active"}:
            return 1000
        if field_name.startswith(("_", "message_", "activity_", "website_message_")):
            return 0
        if field_name in {
            "write_date",
            "create_date",
            "write_uid",
            "create_uid",
            "__last_update",
            "access_token",
            "access_warning",
            "access_url",
        }:
            return 0

        field_type = (field_info or {}).get("type", "")
        if field_type in ("binary", "image", "html"):
            return 0
        if field_type in ("one2many", "many2many"):
            return 0

        score = 0
        if (field_info or {}).get("required"):
            score += 500

        type_scores = {
            "char": 200,
            "boolean": 180,
            "selection": 170,
            "integer": 160,
            "float": 160,
            "monetary": 140,
            "date": 150,
            "datetime": 150,
            "many2one": 120,
            "text": 80,
        }
        score += type_scores.get(field_type, 50)

        if (field_info or {}).get("store", True):
            score += 80
        if (field_info or {}).get("searchable", True):
            score += 40

        name_lower = field_name.lower()
        if any(
            pattern in name_lower
            for pattern in (
                "state",
                "status",
                "stage",
                "priority",
                "company",
                "currency",
                "amount",
                "total",
                "date",
                "user",
                "partner",
                "email",
                "phone",
                "address",
                "street",
                "city",
                "country",
                "code",
                "ref",
                "number",
            )
        ):
            score += 60

        if (field_info or {}).get("compute") and not (
            field_info or {}
        ).get("store", True):
            score = min(score, 30)

        return max(int(score), 0)

    def _smart_fields(
        self, model: str, max_fields: int = 20, context: dict | None = None
    ) -> list[str]:
        fields_get = self._fields_get(model, context=context)
        scored: list[tuple[str, int]] = []
        for field_name, field_info in (fields_get or {}).items():
            if not isinstance(field_name, str):
                continue
            if not isinstance(field_info, dict):
                field_info = {}
            score = self._score_field_importance(field_name, field_info)
            if score > 0:
                scored.append((field_name, score))
        scored.sort(key=lambda x: x[1], reverse=True)

        selected = [name for name, _ in scored[: max(1, int(max_fields))]]
        for essential in ("id", "name", "display_name", "active"):
            if essential in fields_get and essential not in selected:
                selected.append(essential)

        final: list[str] = []
        seen: set[str] = set()
        for field_name in selected:
            if field_name in seen:
                continue
            final.append(field_name)
            seen.add(field_name)
        return final[: max(1, int(max_fields))]

    def _validate_values(
        self, model: str, values: dict, context: dict | None = None
    ) -> None:
        if not self.validate_fields:
            return
        if not isinstance(values, dict):
            raise ValueError("values must be an object")
        fields_get = self._fields_get(model, context=context)
        unknown = [k for k in values.keys() if k not in fields_get]
        if unknown:
            raise ValueError(f"Unknown fields: {', '.join(sorted(unknown))}")
        readonly = [k for k in values.keys() if fields_get.get(k, {}).get("readonly")]
        if readonly:
            raise ValueError(f"Readonly fields: {', '.join(sorted(readonly))}")

    def _call_tool(self, name: str, args: dict) -> Any:
        if name == "odoo_version":
            return self.client.common_version()
        if name == "odoo_whoami":
            uid = self.client.authenticate()
            data = self.client.execute_kw(
                "res.users",
                "read",
                [[uid]],
                {
                    "fields": ["id", "name", "login", "email", "company_id"],
                    "context": {},
                },
            )
            return {"uid": uid, "user": (data or [None])[0]}
        if name == "odoo_execute_kw":
            if not self.allow_unsafe_execute_kw:
                raise PermissionError("odoo_execute_kw is disabled by configuration")
            model = (args.get("model") or "").strip()
            method = (args.get("method") or "").strip()
            self._assert_model_allowed(model)
            self._assert_method_allowed(method)
            return self.client.execute_kw(
                model,
                method,
                args.get("args") or [],
                args.get("kwargs") or {},
            )
        if name in ("odoo_search_read", "search_records"):
            model = (args.get("model") or "").strip()
            self._assert_model_allowed(model)
            domain = _parse_domain(args.get("domain"))
            fields = args.get("fields") or []
            limit = args.get("limit")
            offset = args.get("offset")
            order = args.get("order")
            context = args.get("context") or {}
            search_read_kwargs: dict[str, Any] = {"context": context}
            if not fields:
                search_read_kwargs["fields"] = self._smart_fields(
                    model, self.max_smart_fields, context=context
                )
            else:
                search_read_kwargs["fields"] = fields
            if limit is not None:
                search_read_kwargs["limit"] = limit
            if offset is not None:
                search_read_kwargs["offset"] = offset
            if order:
                search_read_kwargs["order"] = order
            records = self.client.execute_kw(
                model, "search_read", [domain], search_read_kwargs
            )
            return {"model": model, "count": len(records or []), "records": records}
        if name == "odoo_search":
            model = (args.get("model") or "").strip()
            self._assert_model_allowed(model)
            domain = _parse_domain(args.get("domain"))
            limit = args.get("limit")
            offset = args.get("offset")
            order = args.get("order")
            context = args.get("context") or {}
            search_kwargs: dict[str, Any] = {"context": context}
            if limit is not None:
                search_kwargs["limit"] = limit
            if offset is not None:
                search_kwargs["offset"] = offset
            if order:
                search_kwargs["order"] = order
            ids = self.client.execute_kw(model, "search", [domain], search_kwargs)
            return {"model": model, "ids": ids or []}
        if name in ("odoo_count", "count_records"):
            model = (args.get("model") or "").strip()
            self._assert_model_allowed(model)
            domain = _parse_domain(args.get("domain"))
            context = args.get("context") or {}
            count = self.client.execute_kw(
                model, "search_count", [domain], {"context": context}
            )
            return {"model": model, "count": int(count or 0)}
        if name in ("odoo_read",):
            model = (args.get("model") or "").strip()
            self._assert_model_allowed(model)
            ids = args.get("ids") or []
            fields = args.get("fields") or []
            context = args.get("context") or {}
            read_kwargs: dict[str, Any] = {"context": context}
            if not fields:
                read_kwargs["fields"] = self._smart_fields(
                    model, self.max_smart_fields, context=context
                )
            else:
                read_kwargs["fields"] = fields
            return self.client.execute_kw(model, "read", [ids], read_kwargs)
        if name == "get_record":
            model = (args.get("model") or "").strip()
            self._assert_model_allowed(model)
            record_id = int(args.get("record_id"))
            fields = args.get("fields") or []
            context = args.get("context") or {}
            get_record_kwargs: dict[str, Any] = {"context": context}
            if not fields:
                get_record_kwargs["fields"] = self._smart_fields(
                    model, self.max_smart_fields, context=context
                )
            else:
                get_record_kwargs["fields"] = fields
            rows = self.client.execute_kw(
                model, "read", [[record_id]], get_record_kwargs
            )
            return {"model": model, "record": (rows or [None])[0]}
        if name in ("odoo_fields_get", "get_fields"):
            model = (args.get("model") or "").strip()
            attributes = args.get("attributes") or [
                "string",
                "type",
                "required",
                "readonly",
                "relation",
            ]
            context = args.get("context") or {}
            return {
                "model": model,
                "fields": self._fields_get(model, attributes, context),
            }
        if name in ("odoo_list_models", "list_models"):
            limit = args.get("limit")
            context = args.get("context") or {}
            list_models_kwargs: dict[str, Any] = {
                "context": context,
                "fields": ["model", "name"],
            }
            if limit is not None:
                list_models_kwargs["limit"] = limit
            models = self.client.execute_kw(
                "ir.model", "search_read", [[]], list_models_kwargs
            )
            return {"count": len(models or []), "models": models}
        if name == "odoo_check_access_rights":
            model = (args.get("model") or "").strip()
            self._assert_model_allowed(model)
            operation = (args.get("operation") or "").strip()
            raise_exception = bool(args.get("raise_exception", False))
            context = args.get("context") or {}
            ok = self.client.execute_kw(
                model,
                "check_access_rights",
                [operation],
                {"raise_exception": raise_exception, "context": context},
            )
            return {"model": model, "operation": operation, "ok": bool(ok)}
        if name == "odoo_check_access_rule":
            model = (args.get("model") or "").strip()
            self._assert_model_allowed(model)
            ids = args.get("ids") or []
            operation = (args.get("operation") or "").strip()
            raise_exception = bool(args.get("raise_exception", False))
            context = args.get("context") or {}
            ok = self.client.execute_kw(
                model,
                "check_access_rule",
                [ids, operation],
                {"raise_exception": raise_exception, "context": context},
            )
            return {"model": model, "operation": operation, "ok": bool(ok)}
        if name in ("odoo_create", "create_record"):
            model = (args.get("model") or "").strip()
            self._assert_model_allowed(model)
            values = args.get("values") or {}
            context = args.get("context") or {}
            self._validate_values(model, values, context=context)
            new_id = self.client.execute_kw(
                model, "create", [values], {"context": context}
            )
            return {"model": model, "id": int(new_id)}
        if name in ("odoo_write", "update_record"):
            model = (args.get("model") or "").strip()
            self._assert_model_allowed(model)
            ids = args.get("ids") or []
            values = args.get("values") or {}
            context = args.get("context") or {}
            self._validate_values(model, values, context=context)
            ok = self.client.execute_kw(
                model, "write", [ids, values], {"context": context}
            )
            return {"model": model, "ids": ids, "ok": bool(ok)}
        if name in ("odoo_unlink", "delete_record"):
            model = (args.get("model") or "").strip()
            self._assert_model_allowed(model)
            ids = args.get("ids") or []
            context = args.get("context") or {}
            ok = self.client.execute_kw(model, "unlink", [ids], {"context": context})
            return {"model": model, "ids": ids, "ok": bool(ok)}
        raise ValueError(f"Unknown tool: {name}")

    async def handle_request(self, request: dict) -> dict | None:
        method = request.get("method", "")
        req_id = request.get("id")
        params = request.get("params", {})

        if method == "initialize":
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {"tools": {}},
                    "serverInfo": {
                        "name": f"odoo-{self.instance_name}",
                        "version": "0.0.1",
                    },
                },
            }
        if method == "tools/list":
            return {"jsonrpc": "2.0", "id": req_id, "result": {"tools": self.tools}}
        if method == "tools/call":
            tool_name = params.get("name", "")
            args = params.get("arguments", {}) or {}
            try:
                result = {"ok": True, "result": self._call_tool(tool_name, args)}
            except Exception as exc:
                result = {"ok": False, "error": str(exc)}
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps(result, indent=2, default=str),
                        }
                    ]
                },
            }
        if method == "notifications/initialized":
            return None
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "error": {"code": -32601, "message": f"Method not found: {method}"},
        }

    async def run(self):
        loop = asyncio.get_event_loop()
        reader = asyncio.StreamReader()
        protocol = asyncio.StreamReaderProtocol(reader)
        await loop.connect_read_pipe(lambda: protocol, sys.stdin)

        while True:
            line = await reader.readline()
            if not line:
                break
            try:
                req = json.loads(line.decode("utf-8"))
            except json.JSONDecodeError:
                continue

            try:
                resp = await self.handle_request(req)
            except Exception as exc:
                resp = {
                    "jsonrpc": "2.0",
                    "id": req.get("id"),
                    "error": {"code": -32000, "message": str(exc)},
                }

            if resp:
                sys.stdout.write(json.dumps(resp) + "\n")
                sys.stdout.flush()


def main():
    instance_name = os.environ.get("ODOO_INSTANCE_NAME", "odoo")
    url = os.environ.get("ODOO_URL", "").strip()
    db = os.environ.get("ODOO_DB", "").strip()
    username = os.environ.get("ODOO_USERNAME", "").strip()
    api_key = os.environ.get("ODOO_API_KEY", "").strip()
    timeout_s = int(os.environ.get("ODOO_TIMEOUT_SECONDS", "30"))

    if not url or not db or not username or not api_key:
        sys.stderr.write("Missing Odoo configuration in environment\n")
        sys.exit(1)

    client = OdooJsonRpcClient(url, db, username, api_key, timeout_s)
    server = OdooMCPServer(client, instance_name)
    try:
        asyncio.run(server.run())
    finally:
        client.close()


if __name__ == "__main__":
    main()
