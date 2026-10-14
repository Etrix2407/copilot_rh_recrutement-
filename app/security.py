"""En-têtes de sécurité et protection CSRF, sous forme de middleware ASGI.

Un middleware ASGI « pur » (et non BaseHTTPMiddleware) laisse passer le flux SSE
du chat sans le mettre en mémoire tampon.
"""

from starlette.datastructures import Headers, MutableHeaders
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})

SECURITY_HEADERS = {
    # Pas de contenu deviné par le navigateur (un .txt ne devient jamais un script)
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
}
# Scripts et styles uniquement servis par l'application, et pas d'affichage dans une iframe d'un autre site.
# /docs n'en reçoit pas : Swagger UI charge ses fichiers depuis un CDN.
CONTENT_SECURITY_POLICY = "default-src 'self'; frame-ancestors 'none'"
DOCS_PATHS = ("/docs", "/redoc")


class SecurityMiddleware:
    def __init__(self, app: ASGIApp, *, allowed_origins: list[str]) -> None:
        self.app = app
        self.allowed_origins = frozenset(allowed_origins)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = Headers(scope=scope)
        if scope["method"] not in SAFE_METHODS and not self._is_allowed_origin(scope, headers):
            # CSRF : un autre site ouvert dans le navigateur ne peut pas déclencher d'action (analyse, chat…)
            response = JSONResponse({"detail": "Requête provenant d'un autre site refusée."}, status_code=403)
            await response(scope, receive, send)
            return

        with_csp = not scope["path"].startswith(DOCS_PATHS)

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                response_headers = MutableHeaders(scope=message)
                for name, value in SECURITY_HEADERS.items():
                    response_headers.setdefault(name, value)
                if with_csp:
                    response_headers.setdefault("Content-Security-Policy", CONTENT_SECURITY_POLICY)
            await send(message)

        await self.app(scope, receive, send_with_headers)

    def _is_allowed_origin(self, scope: Scope, headers: Headers) -> bool:
        origin = headers.get("origin")
        # Sans en-tête Origin, la requête ne vient pas d'un navigateur sur un autre site (curl, tests…)
        if origin is None:
            return True
        own_origin = f"{scope['scheme']}://{headers.get('host', '')}"
        return origin == own_origin or origin in self.allowed_origins
