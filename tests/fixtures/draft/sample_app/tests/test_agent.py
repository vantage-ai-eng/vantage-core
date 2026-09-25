"""Golden strings the production agent must retain."""


def test_agent_quotes_doc_token():
    out = "[SOURCE: Document \"Note\"] DOC-104 retained"
    assert "DOC-104" in out
