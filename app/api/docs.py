"""Pages de documentation de l'API (/docs et /redoc), avec des versions figées de Swagger UI et ReDoc.

Par défaut, FastAPI charge la dernière version 5.x de Swagger UI depuis un CDN : un changement
non prévu de ce script tiers s'exécuterait sur l'origine de l'application. Les versions sont donc figées.
"""

from fastapi import APIRouter, Request
from fastapi.openapi.docs import get_redoc_html, get_swagger_ui_html
from fastapi.responses import HTMLResponse

SWAGGER_UI_VERSION = "5.17.14"
REDOC_VERSION = "2.1.5"
CDN = "https://cdn.jsdelivr.net/npm"

router = APIRouter(include_in_schema=False)


@router.get("/docs")
async def swagger_ui(request: Request) -> HTMLResponse:
    return get_swagger_ui_html(
        openapi_url=request.app.openapi_url,
        title=f"{request.app.title} — documentation",
        swagger_js_url=f"{CDN}/swagger-ui-dist@{SWAGGER_UI_VERSION}/swagger-ui-bundle.js",
        swagger_css_url=f"{CDN}/swagger-ui-dist@{SWAGGER_UI_VERSION}/swagger-ui.css",
    )


@router.get("/redoc")
async def redoc(request: Request) -> HTMLResponse:
    return get_redoc_html(
        openapi_url=request.app.openapi_url,
        title=f"{request.app.title} — documentation",
        redoc_js_url=f"{CDN}/redoc@{REDOC_VERSION}/bundles/redoc.standalone.js",
    )
