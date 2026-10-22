"""The PATH confirmatory test runs only against a frozen spec, once (review 4, F5)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from analysis import path_hypotheses as ph  # noqa: E402

pytestmark = pytest.mark.skipif(not (ph.TABLES / "power.json").exists(), reason="power.json not built")


def test_refuses_without_or_with_stale_spec(tmp_path, monkeypatch):
    monkeypatch.setattr(ph, "FINAL_SPEC", tmp_path / "final_spec.json")
    with pytest.raises(SystemExit, match="no frozen spec"):
        ph.check_final_allowed()
    (tmp_path / "final_spec.json").write_text(json.dumps({"sha256": "stale", "spec": {}}))
    with pytest.raises(SystemExit, match="!= frozen"):
        ph.check_final_allowed()


def test_refuses_second_final_touch_and_refreeze(tmp_path, monkeypatch):
    monkeypatch.setattr(ph, "FINAL_SPEC", tmp_path / "final_spec.json")
    monkeypatch.setattr(ph, "TOUCH_LOG", tmp_path / "test_touch_log.jsonl")
    ph.freeze_spec()
    assert ph.check_final_allowed()
    with pytest.raises(SystemExit, match="already exists"):
        ph.freeze_spec()
    (tmp_path / "test_touch_log.jsonl").write_text(json.dumps({"kind": "final"}) + "\n")
    with pytest.raises(SystemExit, match="already logged"):
        ph.check_final_allowed()


def test_frozen_spec_matches_code():
    if not ph.FINAL_SPEC.exists():
        pytest.skip("final_spec.json not frozen")
    assert ph.spec_hash(ph.current_spec()) == json.loads(ph.FINAL_SPEC.read_text())["sha256"]


def test_estimator_recovers_bucket_effect():
    rng = np.random.default_rng(0)
    n_ev, days = 400, np.arange(29, -1, -1)
    d = pd.DataFrame({"event_id": np.repeat([f"e{i}" for i in range(n_ev)], 30), "days_before": np.tile(days, n_ev)})
    d["cluster"] = "a" + (d.event_id.str[1:].astype(int) // 2).astype(str)
    for i, (lo, hi) in enumerate(ph.PARAMS["pair_buckets"]):
        d[f"b{i}"] = d.days_before.between(lo, hi).astype(float)
    d["dow"] = d.days_before % 7
    d["y"] = (rng.random(len(d)) < 0.01 + 0.05 * d.b0).astype(float)
    r = ph.estimate("H20a", d)
    assert abs(r["coef"] - 0.05) < 0.02 and r["p"] < 0.01


def test_bh():
    q = ph.bh({"a": 0.01, "b": 0.04})
    assert q == {"a": 0.02, "b": 0.04}
