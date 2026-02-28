"""Baseline serialization benchmarks for FastAPI response optimization.

Compares raw dict→json.dumps (current approach) vs Pydantic model→.model_dump()
(target approach) on three representative payload shapes.

Run::

    pytest tests/benchmarks/test_serialization.py -v
"""

import json
from datetime import datetime

import pytest
from pydantic import BaseModel

from core.api_schemas import ApiResponse

# -- Payload models (representative of real endpoints) -----------------------


class ToolInfo(BaseModel):
    name: str
    description: str
    server: str


class ConversationSummary(BaseModel):
    id: str
    agent_name: str
    title: str
    message_count: int
    created_at: str
    updated_at: str


class ModelField(BaseModel):
    name: str
    type: str
    required: bool
    description: str


class ModelInfo(BaseModel):
    schema_name: str
    model_name: str
    fields: list[ModelField]
    record_count: int


# -- Fixture data ------------------------------------------------------------


def _small_payload() -> dict:
    """Single item response (e.g. GET /api/v1/model/1)."""
    return {
        "ok": True,
        "data": {
            "id": 42,
            "name": "Test Record",
            "active": True,
            "created_at": datetime.now().isoformat(),
        },
    }


def _list_payload(n: int = 50) -> dict:
    """List response (e.g. GET /api/v1/model with 50 records)."""
    return {
        "ok": True,
        "data": [
            {
                "id": i,
                "name": f"tool_{i}",
                "description": f"Description for tool {i} with some extra text",
                "server": f"server-{i % 5}",
            }
            for i in range(n)
        ],
        "count": n,
    }


def _nested_payload() -> dict:
    """Nested response (e.g. model schema with field metadata)."""
    return {
        "ok": True,
        "data": [
            {
                "schema_name": "app",
                "model_name": f"model_{m}",
                "fields": [
                    {
                        "name": f"field_{f}",
                        "type": "varchar",
                        "required": f % 3 == 0,
                        "description": f"Field {f} of model {m}",
                    }
                    for f in range(10)
                ],
                "record_count": m * 100,
            }
            for m in range(5)
        ],
        "count": 5,
    }


# -- Pydantic equivalents ---------------------------------------------------


def _small_pydantic() -> ApiResponse:
    return ApiResponse(
        data={
            "id": 42,
            "name": "Test Record",
            "active": True,
            "created_at": datetime.now().isoformat(),
        },
    )


def _list_pydantic(n: int = 50) -> ApiResponse[list[ToolInfo]]:
    tools = [
        ToolInfo(
            name=f"tool_{i}",
            description=f"Description for tool {i} with some extra text",
            server=f"server-{i % 5}",
        )
        for i in range(n)
    ]
    return ApiResponse(data=tools, count=n)


def _nested_pydantic() -> ApiResponse[list[ModelInfo]]:
    models = [
        ModelInfo(
            schema_name="app",
            model_name=f"model_{m}",
            fields=[
                ModelField(
                    name=f"field_{f}",
                    type="varchar",
                    required=f % 3 == 0,
                    description=f"Field {f} of model {m}",
                )
                for f in range(10)
            ],
            record_count=m * 100,
        )
        for m in range(5)
    ]
    return ApiResponse(data=models, count=5)


# -- Benchmarks: json.dumps (current) ---------------------------------------


def test_json_dumps_small(benchmark):
    """Baseline: small payload via json.dumps."""
    payload = _small_payload()
    benchmark(json.dumps, payload)


def test_json_dumps_list(benchmark):
    """Baseline: list payload (50 items) via json.dumps."""
    payload = _list_payload()
    benchmark(json.dumps, payload)


def test_json_dumps_nested(benchmark):
    """Baseline: nested payload via json.dumps."""
    payload = _nested_payload()
    benchmark(json.dumps, payload)


# -- Benchmarks: Pydantic model_dump + json (current hybrid) ----------------


def test_pydantic_model_dump_json_small(benchmark):
    """Pydantic model_dump() then json.dumps."""
    model = _small_pydantic()
    benchmark(lambda: json.dumps(model.model_dump()))


def test_pydantic_model_dump_json_list(benchmark):
    """Pydantic model_dump() then json.dumps (list)."""
    model = _list_pydantic()
    benchmark(lambda: json.dumps(model.model_dump()))


def test_pydantic_model_dump_json_nested(benchmark):
    """Pydantic model_dump() then json.dumps (nested)."""
    model = _nested_pydantic()
    benchmark(lambda: json.dumps(model.model_dump()))


# -- Benchmarks: Pydantic model_dump_json (Rust path) -----------------------


def test_pydantic_rust_small(benchmark):
    """Target: small payload via Pydantic Rust serialization."""
    model = _small_pydantic()
    benchmark(model.model_dump_json)


def test_pydantic_rust_list(benchmark):
    """Target: list payload via Pydantic Rust serialization."""
    model = _list_pydantic()
    benchmark(model.model_dump_json)


def test_pydantic_rust_nested(benchmark):
    """Target: nested payload via Pydantic Rust serialization."""
    model = _nested_pydantic()
    benchmark(model.model_dump_json)


# -- Sanity check: verify outputs are equivalent ----------------------------


def test_output_equivalence_small():
    """Verify dict and Pydantic produce equivalent JSON structure."""
    dict_json = json.loads(json.dumps(_small_payload()))
    pydantic_json = json.loads(_small_pydantic().model_dump_json(exclude_none=True))
    assert dict_json["ok"] == pydantic_json["ok"]
    # Compare structure, skip timestamps (non-deterministic)
    for key in ("id", "name", "active"):
        assert dict_json["data"][key] == pydantic_json["data"][key]


def test_output_equivalence_list():
    """Verify list payloads are equivalent."""
    dict_data = _list_payload()
    pydantic_data = json.loads(_list_pydantic().model_dump_json(exclude_none=True))
    assert dict_data["count"] == pydantic_data["count"]
    assert len(dict_data["data"]) == len(pydantic_data["data"])


@pytest.mark.parametrize("n", [10, 50, 100, 500])
def test_scaling_json_dumps(benchmark, n):
    """How json.dumps scales with list size."""
    payload = _list_payload(n)
    benchmark(json.dumps, payload)


@pytest.mark.parametrize("n", [10, 50, 100, 500])
def test_scaling_pydantic_rust(benchmark, n):
    """How Pydantic Rust scales with list size."""
    model = _list_pydantic(n)
    benchmark(model.model_dump_json)
