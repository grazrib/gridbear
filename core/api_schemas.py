"""Standard API response schemas for all JSON endpoints.

Provides a unified response envelope so that every JSON endpoint in
GridBear returns the same structure.  When used with ``response_model=``
on FastAPI routes, Pydantic handles serialisation on the Rust side
(FastAPI >= 0.131).

Usage::

    from core.api_schemas import ApiResponse, api_ok, api_error

    @router.get("/items", response_model=ApiResponse[list[ItemOut]])
    async def list_items():
        return api_ok(data=items, count=len(items))

    @router.get("/items/{id}", responses={404: {"model": ApiError}})
    async def get_item(id: int):
        item = ...
        if not item:
            return api_error(404, "Not found", "not_found")
        return api_ok(data=item)
"""

from typing import Generic, TypeVar

from fastapi.responses import JSONResponse
from pydantic import BaseModel

T = TypeVar("T")


class ApiResponse(BaseModel, Generic[T]):
    """Standard success response envelope.

    All JSON-returning endpoints should use this as their
    ``response_model``.  Fields that are ``None`` should be excluded
    from the wire format via ``response_model_exclude_none=True``
    (set per-route or on the router).
    """

    ok: bool = True
    data: T | None = None
    error: str | None = None
    code: str | None = None
    count: int | None = None


class ApiError(BaseModel):
    """Error response body.

    **Always** returned inside a :class:`JSONResponse` with the
    appropriate HTTP status code — never as a bare ``return`` (which
    would produce HTTP 200 with an error body).
    """

    ok: bool = False
    error: str
    code: str


# -- Helper functions --------------------------------------------------------


def api_ok(data=None, **extra) -> ApiResponse:
    """Build a success envelope.

    Extra keyword arguments are forwarded to :class:`ApiResponse`
    (e.g. ``count=42``).
    """
    return ApiResponse(data=data, **extra)


def api_error(status: int, message: str, code: str) -> JSONResponse:
    """Build an error :class:`JSONResponse` with the correct HTTP status.

    Using this helper (instead of ``return ApiError(...)``) ensures the
    HTTP status code is always set — a bare ``return`` of a Pydantic
    model would produce HTTP 200.
    """
    return JSONResponse(
        ApiError(error=message, code=code).model_dump(),
        status_code=status,
    )
