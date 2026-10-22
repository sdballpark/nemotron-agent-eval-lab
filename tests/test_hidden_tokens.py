from types import SimpleNamespace as U

from evallab.adapter import hidden_tokens


def test_gemini_thinking_recovered_from_total():
    assert hidden_tokens(U(total_tokens=398, prompt_tokens=16, completion_tokens=23)) == 359


def test_zero_when_total_is_the_sum():
    assert hidden_tokens(U(total_tokens=39, prompt_tokens=16, completion_tokens=23)) == 0


def test_none_when_usage_incomplete():
    assert hidden_tokens(None) is None
    assert hidden_tokens(U(total_tokens=None, prompt_tokens=16, completion_tokens=23)) is None
