"""Protection des prompts contre l'injection : les textes externes sont délimités comme des données."""

# Chevrons remplacés par leurs équivalents pleine chasse : lisibles par le LLM, mais incapables de former une balise
_NEUTRAL_BRACKETS = str.maketrans({"<": "＜", ">": "＞"})


def as_data(tag: str, text: str) -> str:
    """Entoure un texte externe (CV, question…) de balises <tag>…</tag>.

    Le prompt système précise que ce qui est entre ces balises est une donnée,
    jamais une instruction. Les chevrons du texte sont neutralisés : aucune balise
    (« </cv> », « </cv attr> », « <c<cv>v> »…) ne peut fermer le bloc pour glisser des
    consignes. Un seul passage, en temps linéaire, quelle que soit la forme du texte.
    """
    cleaned = text.translate(_NEUTRAL_BRACKETS)
    return f"<{tag}>\n{cleaned.strip()}\n</{tag}>"
