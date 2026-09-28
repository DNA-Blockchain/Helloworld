import json
from pathlib import Path


def test_recovery_search_schema_offers_both_identities_without_private_keys():
    schema_path = Path(__file__).parents[1] / "schemas" / "recovery-search-v1.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))

    identity = schema["properties"]["identities"]["items"]
    assert identity["properties"]["mode"]["enum"] == [
        "user-recovery-key",
        "pinned-node-key",
    ]
    assert schema["properties"]["enabled"]["default"] is False
    assert schema["properties"]["networkEnabled"]["default"] is False
    assert schema["properties"]["includePrivateContent"]["const"] is False
    assert "privateKey" not in identity["properties"]
    assert "endpointIds" not in schema["required"]

    remote_search = schema["allOf"][0]
    assert remote_search["if"]["properties"]["networkEnabled"]["const"] is True
    assert remote_search["then"]["properties"]["endpointIds"]["minItems"] == 1
    assert (
        remote_search["then"]["properties"]["sources"]["contains"]["const"]
        == "configured-peer-index"
    )
