"""The test split can only be evaluated against a frozen spec, once."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from analysis import level_model  # noqa: E402

pytestmark = pytest.mark.skipif(not (Path(__file__).resolve().parents[1] / "data/shows.parquet").exists(),
                                reason="data/shows.parquet not built")


def test_refuses_without_or_with_stale_spec(tmp_path, monkeypatch):
    monkeypatch.setattr(level_model, "FINAL_SPEC", tmp_path / "final_spec.json")
    with pytest.raises(SystemExit, match="no frozen spec"):
        level_model.check_final_allowed()
    (tmp_path / "final_spec.json").write_text(json.dumps({"sha256": "stale", "spec": {}}))
    with pytest.raises(SystemExit, match="!= frozen"):
        level_model.check_final_allowed()


def test_refuses_second_final_touch(tmp_path, monkeypatch):
    monkeypatch.setattr(level_model, "FINAL_SPEC", tmp_path / "final_spec.json")
    monkeypatch.setattr(level_model, "OUT_TABLES", tmp_path)
    spec = level_model.current_spec()
    (tmp_path / "final_spec.json").write_text(json.dumps({"sha256": level_model.spec_hash(spec), "spec": spec}, default=str))
    (tmp_path / "test_touch_log.jsonl").write_text(json.dumps({"kind": "final"}) + "\n")
    with pytest.raises(SystemExit, match="already logged"):
        level_model.check_final_allowed()
