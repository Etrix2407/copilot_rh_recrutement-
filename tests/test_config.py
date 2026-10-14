import pytest
from pydantic import ValidationError

from app.config import Settings, describe_configuration_errors


def test_missing_configuration_names_the_variables_without_their_values(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in Settings.model_fields:
        monkeypatch.delenv(name.upper(), raising=False)

    with pytest.raises(ValidationError) as exc_info:
        Settings(llm_api_key="secret-key", log_level="BAVARD", _env_file=None)
    message = describe_configuration_errors(exc_info.value)

    assert "LLM_MODEL (manquante)" in message
    assert "LOG_LEVEL (invalide)" in message
    assert "BAVARD" not in message
    assert "secret-key" not in message
    assert ".env.example" in message
