import json

import pytest

from channels.web_protocol import (
    AssistantMessageEvent,
    decode_assistant_message,
    encode_assistant_message,
)


def test_v2_assistant_event_has_frozen_type_and_version():
    payload = json.loads(encode_assistant_message("hello"))
    assert payload == {
        "type": "assistant.message",
        "protocol_version": 2,
        "content": "hello",
    }


def test_legacy_plain_text_remains_compatible():
    assert decode_assistant_message("legacy reply") == "legacy reply"


def test_v2_assistant_event_round_trip():
    payload = encode_assistant_message("v2 reply")
    assert decode_assistant_message(payload) == "v2 reply"


def test_v2_contract_rejects_unknown_fields():
    with pytest.raises(ValueError):
        AssistantMessageEvent.model_validate(
            {"type": "assistant.message", "protocol_version": 2, "content": "ok", "secret": "no"}
        )
