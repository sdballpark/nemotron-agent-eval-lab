from types import SimpleNamespace

from evallab.adapter import split_reasoning


def msg(content=None, **fields):
    return SimpleNamespace(content=content, **fields)


def test_ollama_reasoning_field():
    assert split_reasoning(msg("PELICAN", reasoning="thinking")) == ("PELICAN", "thinking", "field")


def test_nvidia_reasoning_content_field():
    assert split_reasoning(msg("PELICAN", reasoning_content="thinking")) == ("PELICAN", "thinking", "field")


def test_inline_bare_closing_tag():
    content = "The marker is PELICAN.\n</think>\nPELICAN"
    assert split_reasoning(msg(content)) == ("PELICAN", "The marker is PELICAN.", "inline")


def test_inline_both_tags():
    content = "<think>The marker is PELICAN.</think>PELICAN"
    assert split_reasoning(msg(content)) == ("PELICAN", "The marker is PELICAN.", "inline")


def test_no_reasoning():
    assert split_reasoning(msg(" PELICAN \n")) == ("PELICAN", "", "none")


def test_none_content():
    assert split_reasoning(msg(None)) == ("", "", "none")


def test_empty_field_falls_through_to_inline():
    content = "thinking</think>PELICAN"
    assert split_reasoning(msg(content, reasoning="")) == ("PELICAN", "thinking", "inline")
