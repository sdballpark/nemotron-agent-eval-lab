from evallab.repeats import correct_counts, is_length_error, majority_correct


def row(ok):
    return {"status": "ok", "outcome": "correct" if ok else "false_positive"}


def test_counts_and_majority():
    runs = [{"a": row(True), "b": row(False)}, {"a": row(True), "b": row(True)}, {"a": row(False), "b": row(False)}]
    counts = correct_counts(runs, ["a", "b"])
    assert counts == {"a": 2, "b": 1}
    assert majority_correct(counts, 3) == {"a": True, "b": False}


def test_tie_is_not_a_majority():
    assert majority_correct({"a": 2}, 4) == {"a": False}


def test_length_error_detection():
    assert is_length_error({"status": "model_error", "attempt_log": [{"status": "length"}]})
    assert not is_length_error({"status": "model_error", "attempt_log": [{"status": "timeout"}]})
    assert not is_length_error({"status": "ok", "attempt_log": [{"status": "ok"}]})
