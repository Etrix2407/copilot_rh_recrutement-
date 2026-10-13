from fastapi import APIRouter

router = APIRouter()


@router.get("/health")
def health() -> dict[str, str]:
    """Indique que l'API est démarrée."""
    return {"status": "ok"}
