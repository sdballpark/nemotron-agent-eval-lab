"""Run headers store EndpointConfig.model_dump() and resume compares it after
a JSON round trip. Any non-JSON-native field (a tuple, a set) would make every
interrupted run refuse to resume."""
import json

from evallab.adapter import EndpointConfig


def test_endpoint_config_survives_json_round_trip():
    cfg = EndpointConfig(name="t", base_url="https://example.invalid/v1", model="m",
                         api_key_env="X", reasoning=True, max_tokens=8192, temperature=1.0, top_p=0.95)
    dumped = cfg.model_dump()
    assert json.loads(json.dumps(dumped)) == dumped
