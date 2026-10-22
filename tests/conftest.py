"""Test collection rules.

test_error_path.py and test_rendering.py call preflight() at import, which needs
the agentic-soc-triage checkout. Where that checkout is absent (CI), they are left
out of collection instead of failing it. Everything else runs everywhere; tests
needing the gateway or the corpus skip themselves.
"""
import os
from pathlib import Path

SOC_TRIAGE_ROOT = Path(os.environ.get("SOC_TRIAGE_ROOT", str(Path.home() / "ai/projects/agentic-soc-triage")))
NEEDS_SOC_TRIAGE = ["test_error_path.py", "test_rendering.py"]

collect_ignore = [] if (SOC_TRIAGE_ROOT / ".git").exists() else NEEDS_SOC_TRIAGE
