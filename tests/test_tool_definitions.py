from app.tools.definitions import TOOL_DEFINITIONS


def test_every_tool_is_described() -> None:
    names = [tool.name for tool in TOOL_DEFINITIONS]

    assert names == ["search_interview_slots", "book_interview", "update_candidate_status"]


def test_descriptions_come_from_spec_docstrings() -> None:
    descriptions = {tool.name: tool.description for tool in TOOL_DEFINITIONS}

    assert descriptions["search_interview_slots"] == (
        "Retourne la liste des heures disponibles pour un entretien à une date donnée (format YYYY-MM-DD)."
    )
    assert descriptions["book_interview"] == "Réserve un créneau d'entretien pour un candidat et confirme la réservation."


def test_parameters_are_all_required_strings() -> None:
    for tool in TOOL_DEFINITIONS:
        properties = tool.parameters["properties"]
        assert tool.parameters["type"] == "object"
        assert tool.parameters["required"] == list(properties)
        assert all(prop["type"] == "string" for prop in properties.values())


def test_book_interview_parameters_match_function_signature() -> None:
    book = next(tool for tool in TOOL_DEFINITIONS if tool.name == "book_interview")

    assert list(book.parameters["properties"]) == ["candidate_name", "date", "time", "email"]
