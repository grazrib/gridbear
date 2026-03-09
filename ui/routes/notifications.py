"""Notification routes — REST endpoints, SSE stream, internal API."""

import asyncio
from datetime import datetime

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse

from core.api_schemas import ApiResponse, api_error, api_ok
from core.internal_api.auth import verify_internal_auth
from ui.routes.auth import require_user
from ui.services.notifications import NotificationService

router = APIRouter()


def _user_info(user: dict) -> tuple[str, bool]:
    """Extract user identifier and admin flag from the auth user dict."""
    uid = user.get("username") or str(user.get("id", ""))
    is_admin = user.get("is_superadmin", False)
    return uid, is_admin


# ------------------------------------------------------------------
# User-facing endpoints (require_user auth)
# ------------------------------------------------------------------


@router.get(
    "/unread-count",
    response_model=ApiResponse,
    response_model_exclude_none=True,
)
async def unread_count(user: dict = Depends(require_user)):
    uid, is_admin = _user_info(user)
    svc = NotificationService.get()
    count = await svc.get_unread_count(user_id=uid, is_admin=is_admin)
    return api_ok(count=count)


@router.get(
    "/list",
    response_model=ApiResponse[dict],
    response_model_exclude_none=True,
)
async def notification_list(
    unread_only: bool = Query(default=False),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    user: dict = Depends(require_user),
):
    uid, is_admin = _user_info(user)
    svc = NotificationService.get()
    rows = await svc.get_list(
        user_id=uid,
        is_admin=is_admin,
        unread_only=unread_only,
        limit=limit,
        offset=offset,
    )
    # Serialize datetime fields to ISO strings
    for row in rows:
        for key, val in row.items():
            if isinstance(val, datetime):
                row[key] = val.isoformat()
    return api_ok(data={"notifications": rows})


@router.post(
    "/{notification_id}/read",
    response_model=ApiResponse,
    response_model_exclude_none=True,
)
async def mark_read(
    notification_id: int,
    user: dict = Depends(require_user),
):
    uid, is_admin = _user_info(user)
    svc = NotificationService.get()
    await svc.mark_read(notification_id, user_id=uid, is_admin=is_admin)
    return api_ok()


@router.post(
    "/read-all",
    response_model=ApiResponse,
    response_model_exclude_none=True,
)
async def mark_all_read(user: dict = Depends(require_user)):
    uid, is_admin = _user_info(user)
    svc = NotificationService.get()
    count = await svc.mark_all_read(user_id=uid, is_admin=is_admin)
    return api_ok(count=count)


# ------------------------------------------------------------------
# SSE stream
# ------------------------------------------------------------------


@router.get("/stream")
async def notification_stream(
    request: Request,
    user: dict = Depends(require_user),
):
    uid, is_admin = _user_info(user)
    svc = NotificationService.get()

    async def event_generator():
        queue = svc.subscribe(user_id=uid, is_admin=is_admin)
        try:
            yield ": connected\n\n"
            while True:
                if await request.is_disconnected():
                    break
                try:
                    payload = await asyncio.wait_for(queue.get(), timeout=30)
                    if payload is None:
                        break  # evicted by newer connection
                    yield f"data: {payload}\n\n"
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        finally:
            svc.unsubscribe(user_id=uid, queue=queue, is_admin=is_admin)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )


# ------------------------------------------------------------------
# Internal API (bot -> UI)
# ------------------------------------------------------------------


@router.post(
    "/internal/create",
    response_model=ApiResponse[dict],
    response_model_exclude_none=True,
)
async def internal_create(
    request: Request,
    _auth: None = Depends(verify_internal_auth),
):
    body = await request.json()
    category = body.get("category")
    if not category:
        return api_error(400, "category is required", "validation_error")

    svc = NotificationService.get()
    result = await svc.create(
        category=category,
        severity=body.get("severity", "info"),
        title=body.get("title", category),
        message=body.get("message"),
        source=body.get("source"),
        user_id=body.get("user_id"),
        action_url=body.get("action_url"),
    )

    if result is None:
        return api_ok(data={"deduplicated": True})
    return api_ok(data={"id": result["id"]})
