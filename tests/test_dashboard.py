"""Run the Streamlit dashboard headlessly (skipped unless the [dashboard] extra is installed)."""

import pytest

pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest  # noqa: E402


def test_dashboard_renders_example_plan(monkeypatch, tmp_path):
    # No personal plan -> the dashboard falls back to the example plan + demo prices.
    import pda.config as config

    monkeypatch.setattr(config, "DEFAULT_STRATEGY", tmp_path / "missing.yaml")
    at = AppTest.from_file("../dashboard/app.py", default_timeout=60).run()
    assert not at.exception, [e.value for e in at.exception]
    assert "Core + stock slot" in at.title[0].value
    labels = [m.label for m in at.metric]
    assert {"Value", "Goal progress", "Monthly", "Months to goal"} <= set(labels)
    assert at.dataframe, "plan table missing"
