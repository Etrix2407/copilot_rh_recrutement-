"""Limitation du nombre d'appels au LLM par adresse IP, pour protéger le quota du fournisseur."""

import math
import threading
import time
from collections import deque
from collections.abc import Callable

from fastapi import HTTPException, Request, status

WINDOW_SECONDS = 60.0


class RateLimiter:
    """Fenêtre glissante en mémoire : au plus max_requests requêtes par minute et par client."""

    def __init__(self, max_requests: int, *, clock: Callable[[], float] = time.monotonic) -> None:
        self._max_requests = max_requests
        self._clock = clock
        self._requests: dict[str, deque[float]] = {}
        # Lecture et ajout atomiques, même si un appel venait un jour d'un thread du pool (code synchrone)
        self._lock = threading.Lock()

    def retry_after(self, client: str) -> float:
        """Enregistre la requête si elle est permise et renvoie 0, sinon le délai d'attente en secondes."""
        with self._lock:
            now = self._clock()
            recent = self._requests.setdefault(client, deque())
            while recent and recent[0] <= now - WINDOW_SECONDS:
                recent.popleft()
            if len(recent) >= self._max_requests:
                return recent[0] + WINDOW_SECONDS - now
            recent.append(now)
            # Les clients sans requête récente sont oubliés : la mémoire ne grossit pas indéfiniment
            expired = [key for key, times in self._requests.items() if not times or times[-1] <= now - WINDOW_SECONDS]
            for key in expired:
                del self._requests[key]
            return 0.0

    def tracked_clients(self) -> int:
        """Nombre de clients actuellement suivis (ceux qui ont une requête récente en mémoire)."""
        return len(self._requests)


def enforce_llm_rate_limit(request: Request) -> None:
    """À appeler dans une route juste avant le LLM, une fois la demande validée : lève 429 au-delà de la limite.

    Une demande refusée (422, 404…) ne consomme donc pas le quota.
    """
    limiter: RateLimiter = request.state.rate_limiter
    # Adresse réelle du client à condition de lancer uvicorn avec --no-proxy-headers : sinon, un client local
    # peut changer d'adresse apparente à chaque requête avec un en-tête X-Forwarded-For et contourner la limite
    client = request.client.host if request.client else "inconnu"
    wait = limiter.retry_after(client)
    if wait > 0:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            f"Trop de demandes en peu de temps. Réessayez dans {math.ceil(wait)} secondes.",
            headers={"Retry-After": str(math.ceil(wait))},
        )
