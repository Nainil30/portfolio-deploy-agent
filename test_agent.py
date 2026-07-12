# test_agent.py
"""
Test the full agent pipeline.
Run with: python test_agent.py
"""

from src.graph.workflow import run_agent

print("Running full agent pipeline...\n")
final_state = run_agent()

# Verify all state was populated
print("\n" + "=" * 60)
print("STATE VERIFICATION")
print("=" * 60)

checks = [
    ("Config loaded", bool(final_state.get("config"))),
    ("Portfolio tracked", final_state.get("portfolio") is not None),
    ("Tickers scored", len(final_state.get("ticker_scores", {})) > 0),
    ("Market mood set", bool(final_state.get("market_mood"))),
    ("Plan generated", final_state.get("deployment_plan") is not None),
    ("AI commentary", bool(final_state.get("analyst_commentary"))),
    ("Reflection ran", final_state.get("revision_count") is not None),
    ("Plan approved", final_state.get("plan_approved", False)),
    ("Notification sent", final_state.get("notification_sent", False)),
    ("No errors", final_state.get("error") is None),
]

all_passed = True
for label, passed in checks:
    icon = "✅" if passed else "❌"
    print(f"  {icon} {label}")
    if not passed:
        all_passed = False

print()
if all_passed:
    print("ALL CHECKS PASSED — Agent system is working!")
else:
    print("SOME CHECKS FAILED — Review the output above.")