from app.tools.definitions import TOOL_DEFINITIONS


def test_every_tool_is_described() -> None:
    names = [tool.name for tool in TOOL_DEFINITIONS]

    assert names == ["rechercher_creneaux_entretien", "reserver_entretien", "mettre_a_jour_statut_candidat"]


def test_descriptions_come_from_spec_docstrings(spec_namespace: dict[str, object]) -> None:
    descriptions = {tool.name: tool.description for tool in TOOL_DEFINITIONS}

    for name in ("rechercher_creneaux_entretien", "reserver_entretien"):
        assert descriptions[name] == spec_namespace[name].__doc__


def test_parameters_are_all_required_strings() -> None:
    for tool in TOOL_DEFINITIONS:
        properties = tool.parameters["properties"]
        assert tool.parameters["type"] == "object"
        assert tool.parameters["required"] == list(properties)
        assert all(prop["type"] == "string" for prop in properties.values())


def test_book_interview_parameters_match_the_spec() -> None:
    book = next(tool for tool in TOOL_DEFINITIONS if tool.name == "reserver_entretien")

    # Paramètres du cahier des charges, section 6
    assert list(book.parameters["properties"]) == ["candidat_nom", "date", "heure", "email"]
