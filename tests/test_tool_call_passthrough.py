"""Provider-specific fields on tool calls must survive the round trip unchanged."""
from types import SimpleNamespace

from openai.types.chat import ChatCompletionMessageToolCall
from openai.types.chat.chat_completion_message_tool_call import Function

from evallab.adapter import _tool_calls


def test_gemini_thought_signature_is_kept_in_raw():
    tc = ChatCompletionMessageToolCall(
        id="call_1", type="function", function=Function(name="get_ticket", arguments='{"ticket_id": "INC1"}'),
        extra_content={"google": {"thought_signature": "sig-abc"}})
    out = _tool_calls(SimpleNamespace(tool_calls=[tc]))
    assert out[0]["name"] == "get_ticket" and out[0]["id"] == "call_1"
    assert out[0]["raw"]["extra_content"]["google"]["thought_signature"] == "sig-abc"
    assert out[0]["raw"]["function"]["arguments"] == '{"ticket_id": "INC1"}'


def test_plain_tool_call_raw_is_well_formed():
    tc = ChatCompletionMessageToolCall(id="c2", type="function", function=Function(name="find_user", arguments="{}"))
    raw = _tool_calls(SimpleNamespace(tool_calls=[tc]))[0]["raw"]
    assert raw == {"id": "c2", "type": "function", "function": {"name": "find_user", "arguments": "{}"}}


def test_missing_id_gets_a_stable_one():
    fn = SimpleNamespace(name="get_user", arguments=None)
    out = _tool_calls(SimpleNamespace(tool_calls=[SimpleNamespace(function=fn)]))
    assert out[0]["id"] == "call_0" and out[0]["raw"]["id"] == "call_0" and out[0]["arguments"] == "{}"
