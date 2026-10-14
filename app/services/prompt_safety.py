"""Protection des prompts contre l'injection : les textes externes sont délimités comme des données."""

import re


def as_data(tag: str, text: str) -> str:
    """Entoure un texte externe (CV, question…) de balises <tag>…</tag>.

    Le prompt système précise que ce qui est entre ces balises est une donnée,
    jamais une instruction. Les balises du même nom présentes dans le texte sont
    retirées : le texte ne peut pas fermer le bloc pour glisser ses propres consignes.
    """
    pattern = re.compile(rf"<\s*/?\s*{re.escape(tag)}\s*>", flags=re.IGNORECASE)
    # Répété jusqu'à stabilité : « <c<cv>v> » redonnerait « <cv> » après un seul passage
    cleaned = text
    while (stripped := pattern.sub("", cleaned)) != cleaned:
        cleaned = stripped
    return f"<{tag}>\n{cleaned.strip()}\n</{tag}>"
