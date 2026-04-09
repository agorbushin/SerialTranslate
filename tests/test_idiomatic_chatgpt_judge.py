"""
Integration: full idiomatic pipeline + ChatGPT judge on three fixed series.

Requires OPENAI_API_KEY and Subtitle/*.srt files. Run explicitly:

    pytest tests/test_idiomatic_chatgpt_judge.py -m integration --run-integration

Or use the CLI harness (recommended for two-run comparison):

    python3 run_idiomatic_e2e_judge.py --run run1
    python3 run_idiomatic_e2e_judge.py --run run2
    python3 run_idiomatic_e2e_judge.py --compare run1 run2
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]


@pytest.mark.integration
def test_idiomatic_e2e_judge_three_series_smoke():
    if os.environ.get("RUN_IDIOMATIC_INTEGRATION", "").strip() != "1":
        pytest.skip("Set RUN_IDIOMATIC_INTEGRATION=1 to run ChatGPT judge e2e (slow, costs tokens).")
    if not os.environ.get("OPENAI_API_KEY", "").strip():
        pytest.skip("OPENAI_API_KEY not set")

    script = _REPO / "run_idiomatic_e2e_judge.py"
    label = "pytest_idiomatic_integration"
    proc = subprocess.run(
        [sys.executable, str(script), "--run", label],
        cwd=str(_REPO),
        capture_output=True,
        text=True,
        timeout=900,
    )
    assert proc.returncode == 0, proc.stderr + proc.stdout

    summary_path = _REPO / "reports" / "idiomatic_e2e" / label / "summary.json"
    assert summary_path.is_file(), f"expected {summary_path}"

    import json

    data = json.loads(summary_path.read_text(encoding="utf-8"))
    assert data.get("mean_overall_score") is not None
    for ep in data.get("episodes", []):
        assert ep.get("extract_ok") is True, ep
        j = ep.get("judge") or {}
        assert not j.get("error"), j.get("error")
        assert isinstance(j.get("overall_score"), (int, float))
