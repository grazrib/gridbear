"""Admin routes for secrets API (used by Settings page)."""

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse, RedirectResponse

from config.logging_config import logger
from ui.routes.auth import require_login
from ui.secrets_manager import secrets_manager

router = APIRouter(prefix="/secrets", tags=["secrets"])


@router.get("/export")
async def export_secrets(
    request: Request,
    _=Depends(require_login),
):
    """Export all secrets as JSON (for backup/migration)."""
    if not secrets_manager.is_available():
        raise HTTPException(400, "Encryption not available")

    data = secrets_manager.export_all()
    return JSONResponse(
        content=data,
        headers={"Content-Disposition": "attachment; filename=gridbear_secrets.json"},
    )


@router.post("/import")
async def import_secrets(
    request: Request,
    file: UploadFile = File(...),
    _=Depends(require_login),
):
    """Import secrets from JSON file."""
    if not secrets_manager.is_available():
        raise HTTPException(400, "Encryption not available")

    try:
        content = await file.read()
        json_str = content.decode("utf-8")
        results = secrets_manager.import_from_json(json_str, overwrite=True)
        imported = sum(1 for v in results.values() if v)
        return RedirectResponse(f"/settings?imported={imported}", status_code=303)
    except Exception as e:
        logger.warning("Secrets import failed: %s", e)
        raise HTTPException(400, "Invalid or corrupted JSON file")


@router.post("/generate-key")
async def generate_key(
    request: Request,
    _=Depends(require_login),
):
    """Generate a new encryption key file."""
    from ui.secrets_manager import SecretsManager

    try:
        SecretsManager.generate_key_file()
        return RedirectResponse("/settings?key_generated=1", status_code=303)
    except Exception as e:
        logger.error("Key generation failed: %s", e)
        raise HTTPException(400, "Failed to generate encryption key")
