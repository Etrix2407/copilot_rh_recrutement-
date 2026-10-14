from app.tools.definitions import TOOL_DEFINITIONS


def test_every_tool_is_described() -> None:
    names = [tool.name for tool in TOOL_DEFINITIONS]

    assert names == ["rechercher_creneaux_entretien", "reserver_entretien", "mettre_a_jour_statut_candidat"]


def test_descriptions_come_from_spec_docstrings() -> None:
    descriptions = {tool.name: tool.description for tool in TOOL_DEFINITIONS}

    assert descriptions["rechercher_creneaux_entretien"] == (
        "Retourne la liste des heures disponibles pour un entretien à une date donnée (format YYYY-MM-DD)."
    )
    assert descriptions["reserver_entretien"] == "Réserve un créneau d'entretien pour un candidat et confirme la réservation."


def test_parameters_are_all_required_strings() -> None:
    for tool in TOOL_DEFINITIONS:
        properties = tool.parameters["properties"]
        assert tool.parameters["type"] == "object"
        assert tool.parameters["required"] == list(properties)
        assert all(prop["type"] == "string" for prop in properties.values())


def test_book_interview_parameters_match_the_spec() -> None:
    book = next(tool for tool in TOOL_DEFINITIONS if tool.name == "reserver_entretien")

    assert list(book.parameters["properties"]) == ["candidat_nom", "date", "heure", "email"]  # cahier des charges, section 6
