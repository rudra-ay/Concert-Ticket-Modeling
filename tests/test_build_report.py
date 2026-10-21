import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from report import build_report as B  # noqa: E402

PNG = bytes.fromhex("89504e470d0a1a0a0000000d4948445200000001000000010806000000"
                    "1f15c4890000000d49444154789c6360000002000154a24f5d0000000049454e44ae426082")


def _md(extra: str = "") -> str:
    return "# T\n" + "".join(f"\n## {s}\ntext {extra}\n" for s in B.SECTIONS)


def test_complete_report_builds(tmp_path, monkeypatch):
    (tmp_path / "reviews").mkdir()
    (tmp_path / "reviews" / "approved.json").write_text(json.dumps({"L1": "r.md"}))
    (tmp_path / "c.png").write_bytes(PNG)
    md = tmp_path / "findings.md"
    md.write_text(_md("[L1] ![c](c.png)"))
    monkeypatch.setattr(B, "ROOT", tmp_path)
    monkeypatch.setattr(sys, "argv", ["x", "--md", str(md)])
    assert B.main() == 0
    html = md.with_suffix(".html").read_text()
    assert "data:image/png;base64," in html and 'src="c.png"' not in html


def test_blocks_unapproved_missing_image_and_missing_section(tmp_path, monkeypatch):
    monkeypatch.setattr(B, "ROOT", tmp_path)
    md = _md("[L9] ![c](nope.png)").replace("## Next steps", "## Something else")
    errors = B.check(md, tmp_path / "findings.md")
    assert any("nope.png" in e for e in errors)
    assert any("[L9]" in e for e in errors)
    assert any("Next steps" in e for e in errors)
