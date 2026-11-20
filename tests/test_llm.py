from app.ai.llm import strict_json_schema
from app.ai.schemas import GroundedAnswer


def test_strict_json_schema_requires_every_object_property_and_removes_defaults() -> None:
    schema = strict_json_schema(GroundedAnswer)

    assert schema["required"] == list(schema["properties"])
    assert schema["additionalProperties"] is False
    assert "default" not in schema["properties"]["supporting_findings"]
    assert schema["$defs"]["Citation"]["required"] == ["post_id", "url"]
    assert schema["$defs"]["Citation"]["additionalProperties"] is False
