"""Protections HTTP communes à toute l'application, sous forme de middleware ASGI.

- hôtes autorisés (contre le « DNS rebinding » : un site piégé qui se fait passer pour localhost) ;
- requêtes venant d'un autre site refusées (CSRF) ;
- taille des corps de requête bornée ;
- en-têtes de sécurité sur les réponses.

Un middleware ASGI « pur » (et non BaseHTTPMiddleware) laisse passer le flux SSE
du chat sans le mettre en mémoire tampon.
"""

from starlette.datastructures import Headers, MutableHeaders
from starlette.exceptions import HTTPException
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})

# Corps de requête maximal : un CV de 2 Mo plus l'enveloppe multipart pour l'envoi de fichiers ; bien moins ailleurs
MAX_BODY_BYTES = 3_000_000
MAX_JSON_BODY_BYTES = 64_000
# Seules routes qui reçoivent des fichiers : toutes les autres reçoivent du JSON (ou rien)
UPLOAD_PATHS = frozenset({"/api/candidates/parse"})
TOO_LARGE = "Requête trop volumineuse."

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
    def __init__(self, app: ASGIApp, *, allowed_hosts: list[str], allowed_origins: list[str]) -> None:
        self.app = app
        self.allowed_hosts = frozenset(host.lower() for host in allowed_hosts)
        self.allowed_origins = frozenset(allowed_origins)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = Headers(scope=scope)
        with_csp = not scope["path"].startswith(DOCS_PATHS)
        body_limit = _body_limit(scope["path"])
        received = 0

        async def limited_receive() -> Message:
            # Compte les octets réellement reçus : Content-Length peut être absent (envoi « chunked »)
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > body_limit:
                    # HTTPException : FastAPI la laisse passer pendant la lecture du corps (au lieu d'un 400)
                    raise HTTPException(413, TOO_LARGE)
            return message

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                response_headers = MutableHeaders(scope=message)
                for name, value in SECURITY_HEADERS.items():
                    response_headers.setdefault(name, value)
                if with_csp:
                    response_headers.setdefault("Content-Security-Policy", CONTENT_SECURITY_POLICY)
            await send(message)

        if refusal := self._refusal(scope, headers, body_limit):
            status_code, detail = refusal
            # Les refus reçoivent aussi les en-têtes de sécurité
            await JSONResponse({"detail": detail}, status_code=status_code)(scope, receive, send_with_headers)
            return
        await self.app(scope, limited_receive, send_with_headers)

    def _refusal(self, scope: Scope, headers: Headers, body_limit: int) -> tuple[int, str] | None:
        """Renvoie (code HTTP, message) si la requête doit être refusée, sinon None."""
        host = headers.get("host", "").rsplit(":", 1)[0].lower()
        if host not in self.allowed_hosts:
            return 400, "Hôte non autorisé."
        if scope["method"] not in SAFE_METHODS and not self._comes_from_this_site(scope, headers):
            # CSRF : un autre site ouvert dans le navigateur ne peut pas déclencher d'action (analyse, chat…)
            return 403, "Requête provenant d'un autre site refusée."
        # Refus immédiat si la taille est annoncée ; sinon, les octets sont comptés à la réception
        if (length := _content_length(headers)) is not None and length > body_limit:
            return 413, TOO_LARGE
        return None

    def _comes_from_this_site(self, scope: Scope, headers: Headers) -> bool:
        # Le navigateur signale lui-même une requête lancée depuis un autre site, même sans Origin
        if headers.get("sec-fetch-site") == "cross-site":
            return False
        origin = headers.get("origin")
        # Sans en-tête Origin, la requête ne vient pas d'un navigateur sur un autre site (curl, tests…)
        if origin is None:
            return True
        # Host est sûr ici : il a été vérifié contre la liste des hôtes autorisés
        own_origin = f"{scope['scheme']}://{headers['host']}"
        return origin == own_origin or origin in self.allowed_origins


def _body_limit(path: str) -> int:
    """Limite choisie selon la route, pas selon le Content-Type annoncé (que le client peut falsifier)."""
    return MAX_BODY_BYTES if path in UPLOAD_PATHS else MAX_JSON_BODY_BYTES


def _content_length(headers: Headers) -> int | None:
    try:
        return int(headers["content-length"])
    except (KeyError, ValueError):
        return None
