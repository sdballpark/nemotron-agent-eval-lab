from evallab.run import load_endpoint


def test_config_defaults_apply_without_overrides():
    cfg = load_endpoint("lightning-q4-local", reasoning=True)
    assert cfg.temperature == 0.0 and cfg.top_p is None and cfg.max_tokens == 1200


def test_sampling_overrides_change_the_identity():
    base = load_endpoint("lightning-q4-local", reasoning=True, max_tokens=8192)
    vendor = load_endpoint("lightning-q4-local", reasoning=True, max_tokens=8192, temperature=1.0, top_p=0.95)
    assert vendor.temperature == 1.0 and vendor.top_p == 0.95
    assert base.model_dump() != vendor.model_dump()
