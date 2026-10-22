"""Run every analysis: uv run python -m evallab.analysis"""
from evallab.analysis import exp005, exp006, exp007

for mod in (exp005, exp006, exp007):
    mod.main()
    print("\n" + "=" * 100 + "\n")
