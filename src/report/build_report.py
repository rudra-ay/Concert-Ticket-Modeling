"""Build the final report (task 10): reports/findings.md -> reports/findings.html, charts embedded.

Usage: .venv/bin/python src/report/build_report.py [--md reports/findings.md]

Checks before writing (exit 1 on any failure, nothing written):
- every image referenced in the markdown exists under reports/;
- the 7 sections the brief requires are present, in order;
- every finding the report marks as confirmed ("[L3]", "[P2]", ...) appears as APPROVED in reviews/approved.json,
  which the skeptic's review process maintains: {"L3": "reviews/review3_task7.md", ...}.
The HTML is self-contained (charts as data URIs) so it can be opened or shared as one file.
"""
from __future__ import annotations

import argparse
import base64
import json
import re
import sys
from pathlib import Path

import markdown

ROOT = Path(__file__).resolve().parents[2]
SECTIONS = ["Data inventory", "Confirmed patterns", "Surprising findings", "Hypotheses that didn't matter",
            "LEVEL prediction error", "PATH", "Next steps"]
CSS = """
:root{--bg:#fff;--fg:#1d1d1f;--muted:#5f6368;--line:#e3e3e3;--accent:#0b57d0;--code:#f5f5f7}
@media (prefers-color-scheme:dark){:root{--bg:#121212;--fg:#e8e8e8;--muted:#a0a0a0;--line:#333;--accent:#8ab4f8;--code:#1e1e1e}}
body{background:var(--bg);color:var(--fg);font:16px/1.6 -apple-system,system-ui,Segoe UI,Roboto,sans-serif;
max-width:920px;margin:0 auto;padding:24px 16px}
h1,h2,h3{line-height:1.25}h2{border-bottom:1px solid var(--line);padding-bottom:4px;margin-top:2em}
a{color:var(--accent)}img{max-width:100%;height:auto;border:1px solid var(--line);border-radius:6px}
table{border-collapse:collapse;display:block;overflow-x:auto;margin:1em 0}
th,td{border:1px solid var(--line);padding:4px 8px;text-align:left;font-size:14px}
code{background:var(--code);padding:1px 4px;border-radius:4px}small,.muted{color:var(--muted)}
"""


def check(md: str, md_path: Path) -> list[str]:
    errors = []
    for ref in re.findall(r"!\[[^\]]*\]\(([^)\s]+)", md):
        if not (md_path.parent / ref).exists():
            errors.append(f"missing image: {ref}")
    heads = [h.strip() for h in re.findall(r"^## (.+)$", md, re.M)]
    pos = []
    for s in SECTIONS:
        hit = next((i for i, h in enumerate(heads) if h.lower().startswith(s.lower())), None)
        if hit is None:
            errors.append(f"missing section: '## {s}...'")
        pos.append(hit)
    found = [p for p in pos if p is not None]
    if found != sorted(found):
        errors.append("required sections are out of order")
    approved_path = ROOT / "reviews" / "approved.json"
    approved = json.loads(approved_path.read_text()) if approved_path.exists() else {}
    for fid in sorted(set(re.findall(r"\[([LP]\d+[a-z]?)\]", md))):
        if fid not in approved:
            errors.append(f"finding [{fid}] is cited but not in reviews/approved.json")
    return errors


def embed(html: str, base: Path) -> str:
    def sub(m: re.Match) -> str:
        p = base / m.group(2)
        mime = "image/svg+xml" if p.suffix == ".svg" else f"image/{p.suffix.lstrip('.').replace('jpg', 'jpeg')}"
        return f'{m.group(1)}data:{mime};base64,{base64.b64encode(p.read_bytes()).decode()}"'
    return re.sub(r'(<img[^>]*?src=")([^"]+)"', sub, html)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--md", default=str(ROOT / "reports" / "findings.md"))
    md_path = Path(ap.parse_args().md)
    md = md_path.read_text()
    errors = check(md, md_path)
    if errors:
        print("NOT BUILT:\n  " + "\n  ".join(errors))
        return 1
    body = markdown.markdown(md, extensions=["tables", "fenced_code", "toc", "sane_lists"])
    title = (re.search(r"^# (.+)$", md, re.M) or [None, "Concert ticket price findings"])[1]
    html = (f'<!doctype html><html lang="en"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width,initial-scale=1"><title>{title}</title>'
            f"<style>{CSS}</style></head><body>{embed(body, md_path.parent)}</body></html>")
    out = md_path.with_suffix(".html")
    out.write_text(html)
    print(f"wrote {out.relative_to(ROOT)} ({len(html) / 1e6:.1f} MB, {html.count('<img')} charts)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
