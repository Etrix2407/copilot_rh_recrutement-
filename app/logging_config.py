import logging


def configure_logging(level: str) -> None:
    """Configure le format et le niveau des logs de l'application."""
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s : %(message)s",
    )
