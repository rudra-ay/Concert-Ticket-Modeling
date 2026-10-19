"""Parse cached Wikipedia tour pages into per-show box office rows.

Input: data/raw/wikipedia_dumps/pages/<dump>/<page_id>__<revid>.json (from
collect_wikipedia_boxoffice.py). Output: data/interim/shows_base.parquet and
data/interim/shows_base_coverage.md. Parsing rules are documented in
data/interim/shows_base.md.
"""
from __future__ import annotations

import json
import re
import unicodedata
from datetime import date
from pathlib import Path

import mwparserfromhell as mwp
import pandas as pd
import pycountry

ROOT = Path(__file__).resolve().parents[1]
PAGES = ROOT / "data" / "raw" / "wikipedia_dumps" / "pages" / "20261001"
OUT = ROOT / "data" / "interim" / "shows_base.parquet"
COVERAGE = ROOT / "data" / "interim" / "shows_base_coverage.md"

MONTHS = {m.lower(): i for i, m in enumerate(
    ["January", "February", "March", "April", "May", "June", "July", "August",
     "September", "October", "November", "December"], 1)}
MONTHS.update({k[:3]: v for k, v in list(MONTHS.items())})
MONTHS["sept"] = 9

NOTE_WORDS = re.compile(r"\b(cancel+ed|postponed|rescheduled|festival|relocated|moved|"
                        r"private|charity|benefit|co-headline|matinee|livestream)\b", re.I)
DROP_TEMPLATES = re.compile(r"^(efn|refn|ref|note|sfn|cite|citation|notetag|r|nbsp|"
                            r"abbr|tooltip|clarify|citation needed|cn|dead link|update|"
                            r"when|which|by whom|failed verification|better source)", re.I)


# ------------------------------------------------------------------ helpers
def slug(s: str | None) -> str:
    if not isinstance(s, str) or not s:
        return ""
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")


def _strip_refs(text: str) -> str:
    text = re.sub(r"<!--.*?-->", "", text, flags=re.S)
    text = re.sub(r"<ref[^>]*/>", "", text, flags=re.I)
    text = re.sub(r"<ref[^>]*>.*?</ref>", "", text, flags=re.I | re.S)
    return text


LIST_SEP = "\ue000"  # private-use sentinel for <br>, bullets and list templates
LIST_TEMPLATES = ("flatlist", "plainlist", "hlist", "ubl", "unbulleted list", "bulleted list", "plain list")


def clean_cell(raw: str, list_sep: str = " ") -> tuple[str, list[str]]:
    """Return (plain text, wikilink targets) for a cell's wikitext.

    Line breaks (<br>), bullets and list templates become list_sep, so a cell
    listing several acts can be returned as "A | B | C"."""
    raw = re.sub(r"<br\s*/?\s*>", LIST_SEP, _strip_refs(raw), flags=re.I)
    raw = re.sub(r"(^|\n)\s*[*#]+", LIST_SEP, raw)
    code = mwp.parse(raw)
    links = [str(l.title).strip() for l in code.filter_wikilinks()
             if not str(l.title).lower().startswith(("file:", "image:", "category:"))]
    for t in code.filter_templates(recursive=False):
        name = str(t.name).strip().lower()
        try:
            if DROP_TEMPLATES.match(name):
                code.remove(t)
            elif name in LIST_TEMPLATES:
                code.replace(t, LIST_SEP.join(str(p.value) for p in t.params if not p.showkey))
            elif name in ("sort", "sortname", "nts", "dts", "flagu", "flagcountry", "flag",
                          "flagdeco", "nowrap", "small", "center", "date", "start date", "end date",
                          "us$", "usd", "hs", "sts", "abbrlink") or name.startswith(("flag", "sort")):
                code.replace(t, _template_text(t))
        except ValueError:
            pass
    text = code.strip_code(normalize=True, collapse=True).replace("\xa0", " ")
    parts = [re.sub(r"\s+", " ", x).strip() for x in text.split(LIST_SEP)]
    return list_sep.join(x for x in parts if x), links


def _template_text(t) -> str:
    name = str(t.name).strip().lower()
    params = [str(p.value).strip() for p in t.params if not p.showkey]
    if name in ("dts", "date", "start date", "end date", "start date and age", "birth date") and params:
        nums = [p for p in params if re.fullmatch(r"\d{1,4}", p)]
        if len(nums) >= 3:
            y, m, d = nums[:3]
            return f"{int(y):04d}-{int(m):02d}-{int(d):02d}"
        return " ".join(params)
    if name in ("sort", "sortname"):
        return params[-1] if params else ""
    if name in ("us$", "usd"):
        return "$" + (params[0] if params else "")
    if name.startswith("flag") and params:
        return params[0]
    return params[0] if params else ""


# ------------------------------------------------------------------ tables
def iter_tables(text: str):
    """Yield (table_wikitext, section_path) for every top-level wikitable."""
    heads: list[tuple[int, str]] = []
    pos = 0
    pat = re.compile(r"^(={2,6})\s*(.+?)\s*\1\s*$|^\{\||^\|\}", re.M)
    depth = 0
    start = None
    sec_at_start: list[str] = []
    for m in pat.finditer(text):
        tok = m.group(0)
        if m.group(1) and depth == 0:
            lvl = len(m.group(1))
            heads = [h for h in heads if h[0] < lvl] + [(lvl, clean_cell(m.group(2))[0])]
        elif tok.startswith("{|"):
            if depth == 0:
                start = m.start()
                sec_at_start = [h for _, h in heads]
            depth += 1
        elif tok.startswith("|}") and depth:
            depth -= 1
            if depth == 0 and start is not None:
                yield text[start:m.end()], sec_at_start
        pos = m.end()


def _split_cells(line: str, sep: str) -> list[str]:
    """Split a row line on || (or !!) outside of [[ ]] and {{ }}."""
    out, buf, i, d_sq, d_cu = [], [], 0, 0, 0
    while i < len(line):
        two = line[i:i + 2]
        if two == "[[":
            d_sq += 1; buf.append(two); i += 2; continue
        if two == "]]":
            d_sq = max(0, d_sq - 1); buf.append(two); i += 2; continue
        if two == "{{":
            d_cu += 1; buf.append(two); i += 2; continue
        if two == "}}":
            d_cu = max(0, d_cu - 1); buf.append(two); i += 2; continue
        if d_sq == 0 and d_cu == 0 and (two == sep or (sep == "!!" and two == "||")):
            out.append("".join(buf)); buf = []; i += 2; continue
        buf.append(line[i]); i += 1
    out.append("".join(buf))
    return out


def _attr_split(cell: str) -> tuple[str, str]:
    """Split 'attrs | content' on the first single | outside links/templates."""
    d_sq = d_cu = 0
    i = 0
    while i < len(cell):
        two = cell[i:i + 2]
        if two in ("[[", "{{"):
            d_sq += two == "[["; d_cu += two == "{{"; i += 2; continue
        if two in ("]]", "}}"):
            d_sq -= two == "]]"; d_cu -= two == "}}"; i += 2; continue
        if cell[i] == "|" and d_sq <= 0 and d_cu <= 0:
            attrs = cell[:i]
            if "=" in attrs or attrs.strip() == "" or re.fullmatch(r"\s*[a-z-]+\s*", attrs):
                return attrs, cell[i + 1:]
            break
        i += 1
    # malformed cells like '| rowspan="11" {{TBA}}' (attribute pipe missing)
    m = _BARE_ATTRS.match(cell)
    if m:
        return m.group(0), cell[m.end():]
    return "", cell


_BARE_ATTRS = re.compile(r'^\s*(?:(?:rowspan|colspan|style|scope|class|align|width|bgcolor|valign)'
                         r'\s*=\s*(?:"[^"]*"|\'[^\']*\'|[^\s|]+)\s*)+', re.I)


def _span(attrs: str, name: str) -> int:
    m = re.search(name + r'\s*=\s*"?\s*(\d+)', attrs, re.I)
    return max(1, min(int(m.group(1)), 400)) if m else 1


def parse_table(tw: str) -> tuple[str, list[list[dict]]]:
    """Return (caption, rows); each row is a list of cell dicts (with rowspans expanded)."""
    caption = ""
    raw_rows: list[list[dict]] = []
    cur: list[dict] | None = None
    lines = tw.split("\n")[1:]
    # join continuation lines (cell content spanning lines) onto previous cell
    for line in lines:
        s = line.strip()
        if s.startswith("|}"):
            break
        if s.startswith("|+"):
            caption = clean_cell(_attr_split(s[2:])[1])[0]
            continue
        if s.startswith("|-"):
            cur = []
            raw_rows.append(cur)
            continue
        if s.startswith(("!", "|")):
            if cur is None:
                cur = []
                raw_rows.append(cur)
            header = s.startswith("!")
            for c in _split_cells(s[1:], "!!" if header else "||"):
                attrs, content = _attr_split(c)
                cur.append({"raw": content, "header": header, "rs": _span(attrs, "rowspan"),
                            "cs": _span(attrs, "colspan"), "attrs": attrs})
        elif cur:
            cur[-1]["raw"] += "\n" + line
    # expand spans into a grid
    grid: list[list[dict]] = []
    pending: dict[int, list] = {}  # col -> [cell, remaining_rows, row_index_started]
    for r_i, row in enumerate(r for r in raw_rows if r):
        out: list[dict] = []
        col = 0
        cells = list(row)
        while cells or col in pending:
            if col in pending:
                cell, left, origin = pending[col]
                out.append(dict(cell, spanned=True, origin=origin))
                if left <= 1:
                    del pending[col]
                else:
                    pending[col][1] = left - 1
                col += 1
                continue
            if not cells:
                break
            c = cells.pop(0)
            for k in range(c["cs"]):
                out.append(dict(c, spanned=k > 0, origin=r_i))
                if c["rs"] > 1:
                    pending[col] = [c, c["rs"] - 1, r_i]
                col += 1
        grid.append(out)
    return caption, grid


# ------------------------------------------------------------------ values
NUM = r"\d[\d,\.\s]*"


def parse_attendance(t: str) -> tuple[int | None, int | None, str | None]:
    if not t:
        return None, None, None
    s = t.replace(" ", "").replace(" ", "")
    m = re.search(r"(\d[\d,\.]*)/(\d[\d,\.]*)", s)
    if m:
        return _int(m.group(1)), _int(m.group(2)), None
    m = re.search(r"(\d[\d,\.]*)", s)
    if m and _int(m.group(1)) and _int(m.group(1)) >= 50:
        return _int(m.group(1)), None, None
    low = t.lower()
    if "sold out" in low:
        return None, None, "sold out (no count)"
    return None, None, None


def _int(s: str) -> int | None:
    s = s.replace(",", "").replace(".", "")
    return int(s) if s.isdigit() else None


CURRENCIES = [("US$", "USD"), ("USD", "USD"), ("A$", "AUD"), ("AU$", "AUD"), ("AUD", "AUD"),
              ("CA$", "CAD"), ("C$", "CAD"), ("CAD", "CAD"), ("NZ$", "NZD"), ("R$", "BRL"),
              ("MX$", "MXN"), ("HK$", "HKD"), ("S$", "SGD"), ("NT$", "TWD"), ("€", "EUR"),
              ("EUR", "EUR"), ("£", "GBP"), ("GBP", "GBP"), ("¥", "JPY"), ("JP¥", "JPY"),
              ("₩", "KRW"), ("KRW", "KRW"), ("₱", "PHP"), ("₹", "INR"), ("CHF", "CHF"),
              ("kr", "SEK/NOK/DKK"), ("R ", "ZAR"), ("฿", "THB"), ("$", "USD")]


def parse_money(t: str, header_currency: str | None) -> tuple[float | None, str | None]:
    if not t:
        return None, None
    s = t.replace("\xa0", " ")
    m = re.search(r"(\d[\d,]*(?:\.\d+)?)\s*(million|billion)?", s, re.I)
    if not m:
        return None, None
    num = float(m.group(1).replace(",", ""))
    if m.group(2):
        num *= 1e6 if m.group(2).lower() == "million" else 1e9
    cur = None
    prefix = s[:m.start()] + " " + s[m.end():m.end() + 5]
    for sym, code in CURRENCIES:
        if sym in prefix:
            cur = code
            break
    cur = cur or header_currency
    return num, cur


def parse_day(t: str, default_year: int | None) -> tuple[date | None, int | None]:
    """Parse 'February 23', '23 February 2024', '2024-02-23', 'Feb 23–24'. Returns (date, explicit_year)."""
    if not t:
        return None, None
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", t)
    if m:
        return _mk(int(m.group(1)), int(m.group(2)), int(m.group(3))), int(m.group(1))
    yr_m = re.search(r"\b(19[5-9]\d|20[0-3]\d)\b", t)
    yr = int(yr_m.group(1)) if yr_m else None
    m = re.search(r"([A-Za-z]{3,9})\.?\s+(\d{1,2})\b", t)
    if m and m.group(1).lower() in MONTHS:
        return _mk(yr or default_year, MONTHS[m.group(1).lower()], int(m.group(2))), yr
    m = re.search(r"\b(\d{1,2})\s+([A-Za-z]{3,9})\b", t)
    if m and m.group(2).lower() in MONTHS:
        return _mk(yr or default_year, MONTHS[m.group(2).lower()], int(m.group(1))), yr
    return None, yr


def _mk(y, m, d):
    if y is None:
        return None
    try:
        return date(y, m, d)
    except ValueError:
        return None


_country_cache: dict[str, str | None] = {}
COUNTRY_ALIASES = {"united states": "US", "usa": "US", "u.s.": "US", "us": "US", "england": "GB",
                   "scotland": "GB", "wales": "GB", "northern ireland": "GB", "united kingdom": "GB",
                   "uk": "GB", "south korea": "KR", "korea": "KR", "russia": "RU", "taiwan": "TW",
                   "czech republic": "CZ", "czechia": "CZ", "turkey": "TR", "türkiye": "TR",
                   "vietnam": "VN", "the netherlands": "NL", "netherlands": "NL", "holland": "NL",
                   "ivory coast": "CI", "macau": "MO", "macao": "MO", "hong kong": "HK",
                   "puerto rico": "PR", "iran": "IR", "bolivia": "BO", "venezuela": "VE",
                   "uae": "AE", "united arab emirates": "AE", "west germany": "DE", "east germany": "DE",
                   "soviet union": "SU", "yugoslavia": "YU", "brasil": "BR", "méxico": "MX"}


def iso2(name: str | None) -> str | None:
    if not isinstance(name, str) or not name.strip():
        return None
    k = name.strip().lower()
    if k in _country_cache:
        return _country_cache[k]
    code = COUNTRY_ALIASES.get(k)
    if code is None:
        try:
            code = pycountry.countries.lookup(name.strip()).alpha_2
        except LookupError:
            try:
                code = pycountry.countries.search_fuzzy(name.strip())[0].alpha_2 if len(k) > 3 else None
            except LookupError:
                code = None
    _country_cache[k] = code
    return code


US_STATES = {s.name for s in pycountry.subdivisions.get(country_code="US")}
CA_PROV = {s.name for s in pycountry.subdivisions.get(country_code="CA")}


# ------------------------------------------------------------------ infobox
def parse_infobox(code) -> dict:
    out: dict = {}
    for t in code.filter_templates(recursive=False):
        name = str(t.name).strip().lower().replace("_", " ")
        if not name.startswith("infobox concert") and not name.startswith("infobox tour"):
            continue
        for p in t.params:
            key = str(p.name).strip().lower()
            val = str(p.value)
            if key == "artist":
                txt, links = clean_cell(val)
                out["artist_name"] = txt
                out["artist_wikilink"] = " | ".join(links) or None
            elif key in ("start date", "start_date", "end date", "end_date"):
                txt, _ = clean_cell(val)
                d, _y = parse_day(txt, None)
                if d is None:
                    m = re.search(r"\b(19|20)\d\d\b", txt)
                    d = date(int(m.group(0)), 1, 1) if m else None
                out["tour_" + key.replace(" ", "_")] = d
            elif key in ("announced", "announcement_date", "announced_date", "announcement"):
                txt, _ = clean_cell(val)
                out["tour_announced_date"] = parse_day(txt, None)[0]
            elif key in ("gross", "attendance", "number_of_shows", "number of shows", "type", "album",
                         "number_of_legs", "number of legs"):
                out["tour_infobox_" + key.replace(" ", "_")] = clean_cell(val)[0] or None
        break
    return out


# ------------------------------------------------------------------ main page parse
COLS = {
    "date": re.compile(r"^(date|dates)\b|\bdate\b", re.I),
    "city": re.compile(r"\bcity\b|location|town", re.I),
    "region": re.compile(r"state|province|region", re.I),
    "country": re.compile(r"country|nation", re.I),
    "venue": re.compile(r"venue|arena|stadium|location", re.I),
    "opening": re.compile(r"opening|support|special guest|supporting", re.I),
    "attendance": re.compile(r"attendance|tickets sold|sold", re.I),
    "revenue": re.compile(r"revenue|gross|box office|earnings", re.I),
    "notes": re.compile(r"^notes?$|reason|status|event", re.I),
}


def _map_header(hdr: list[str]) -> dict[str, int]:
    m: dict[str, int] = {}
    for i, h in enumerate(hdr):
        for key, rx in COLS.items():
            if key in m or not rx.search(h):
                continue
            if key == "venue" and "city" in m and m["city"] == i:
                continue
            if key == "city" and re.search(r"venue", h, re.I):
                continue
            m[key] = i
            break
    return m


def _acts(t: str) -> str | None:
    """Opening acts as 'A | B | C' (split on line breaks, list items and commas; not on 'and',
    which appears inside band names)."""
    parts = [x.strip() for x in re.split(r"\s*\|\s*|\s*,\s*|\s*;\s*", t or "")]
    parts = [x for x in parts if x and x not in ("—", "–", "-", "N/A", "TBA", "None")]
    return " | ".join(parts) or None


def _year_hint(*texts: str) -> int | None:
    for t in texts:
        if t:
            ys = re.findall(r"\b(19[5-9]\d|20[0-3]\d)\b", t)
            if ys:
                return int(ys[0])
    return None


def parse_page(p: dict) -> list[dict]:
    text = p["text"]
    code = mwp.parse(text)
    ib = parse_infobox(code)
    rows: list[dict] = []
    start_year = ib.get("tour_start_date").year if ib.get("tour_start_date") else None
    for t_i, (tw, secs) in enumerate(iter_tables(text)):
        try:
            caption, grid = parse_table(tw)
        except Exception:  # noqa: BLE001 - malformed tables are skipped and counted
            continue
        if not grid:
            continue
        # header row = first row with >= 3 header cells
        h_idx = next((i for i, r in enumerate(grid[:5])
                      if len({clean_cell(c["raw"])[0] for c in r if c["header"]}) >= 3), None)
        if h_idx is None:
            continue
        hdr = [clean_cell(c["raw"])[0] for c in grid[h_idx]]
        cmap = _map_header(hdr)
        if "date" not in cmap or not ({"attendance", "revenue"} & cmap.keys()):
            continue
        # some tables have a 2-row header (e.g. Attendance | Revenue split); skip extra header rows
        sec_txt = " / ".join(secs)
        is_cancel_table = bool(re.search(r"cancel|postpone", sec_txt + " " + caption, re.I))
        year = _year_hint(hdr[cmap["date"]], caption) or _year_hint(*reversed(secs)) or start_year
        rev_hdr = hdr[cmap["revenue"]] if "revenue" in cmap else ""
        hdr_cur = parse_money("1 " + rev_hdr, None)[1] if re.search(r"US\$|\$|€|£|¥|USD", rev_hdr) else None
        leg = None
        prev: date | None = None
        ncols = len(hdr)
        for r_i in range(h_idx + 1, len(grid)):
            row = grid[r_i]
            if not row:
                continue
            texts = [clean_cell(c["raw"], " | " if j == cmap.get("opening") else " ")
                     for j, c in enumerate(row)]
            first = texts[0][0] if texts else ""
            # separator / leg rows: a single cell spanning (almost) the table
            if len(row) and all(c is row[0] or c.get("spanned") for c in row) and row[0]["cs"] >= max(2, ncols - 1):
                if re.search(r"total", first, re.I):
                    continue
                leg = first or leg
                y = _year_hint(first)
                if y:
                    year = y
                continue
            if re.search(r"^total", first, re.I) or (row[0]["header"] and re.search(r"total", first, re.I)):
                continue
            if all(c["header"] for c in row) and r_i <= h_idx + 2:
                continue  # sub-header
            get = lambda k: texts[cmap[k]] if k in cmap and cmap[k] < len(texts) else ("", [])  # noqa: E731
            cell = lambda k: row[cmap[k]] if k in cmap and cmap[k] < len(row) else None  # noqa: E731
            d_txt = get("date")[0]
            d, explicit_y = parse_day(d_txt, year)
            if d is None:
                continue
            if explicit_y:
                year = explicit_y
            elif prev and d < prev and (prev - d).days > 150:  # year rollover in a yearless column
                d = _mk(d.year + 1, d.month, d.day) or d
                year = d.year
            prev = d
            att_c, rev_c = cell("attendance"), cell("revenue")
            sold, avail, att_note = parse_attendance(get("attendance")[0])
            gross, cur = parse_money(get("revenue")[0], hdr_cur)
            if gross is not None and gross < 1000:  # stray numbers like footnote marks
                gross, cur = None, None
            # aggregate detection: figure cell spans several rows (multi-night stand)
            agg_n = 1
            agg_first = True
            for c in (att_c, rev_c):
                if c is not None and c["rs"] > 1:
                    agg_n = max(agg_n, c["rs"])
                    agg_first = agg_first and not c.get("spanned")
            notes = " ; ".join(x for x in [get("notes")[0], att_note] if x)
            status = []
            if is_cancel_table:
                status.append("cancelled/postponed table")
            for src in (notes, d_txt, get("venue")[0], get("attendance")[0], get("revenue")[0]):
                status += [w.lower() for w in NOTE_WORDS.findall(src or "")]
            rows.append({
                "tour_title": p["title"], "tour_page_id": p["page_id"], "tour_revid": p["revid"],
                "rev_timestamp": p["timestamp"], "table_index": t_i, "table_caption": caption or None,
                "section": sec_txt or None, "leg": leg or (secs[-1] if secs else None),
                "show_date": d, "date_raw": d_txt,
                "city": get("city")[0] or None, "city_wikilink": " | ".join(get("city")[1]) or None,
                "region": get("region")[0] or None,
                "country": get("country")[0] or None,
                "venue": get("venue")[0] or None, "venue_wikilink": " | ".join(get("venue")[1]) or None,
                "opening_acts_raw": _acts(get("opening")[0]),
                "opening_acts_wikilinks": " | ".join(get("opening")[1]) or None,
                "attendance_raw": get("attendance")[0] or None, "revenue_raw": get("revenue")[0] or None,
                "tickets_sold": sold if agg_first else None,
                "tickets_available": avail if agg_first else None,
                "gross": gross if agg_first else None, "gross_currency": cur if agg_first else None,
                "aggregate_n_shows": agg_n, "aggregate_is_first": agg_first,
                "notes_raw": notes or None, "status_note": ",".join(sorted(set(status))) or None,
                **ib,
            })
    return rows


AMBIGUOUS_STATE_COUNTRY = {"Georgia"}  # US state and sovereign country
AU_STATES = {s.name for s in pycountry.subdivisions.get(country_code="AU")}
_LINK_REGION = re.compile(r"^[^,]+,\s*(.+)$")
# US/Canadian cities whose enwiki article title has no ", State" suffix (AP dateline style)
BARE_CITIES = {
    "Atlanta": "Georgia", "Baltimore": "Maryland", "Boston": "Massachusetts", "Chicago": "Illinois",
    "Cincinnati": "Ohio", "Cleveland": "Ohio", "Dallas": "Texas", "Denver": "Colorado",
    "Detroit": "Michigan", "Honolulu": "Hawaii", "Houston": "Texas", "Indianapolis": "Indiana",
    "Las Vegas": "Nevada", "Los Angeles": "California", "Miami": "Florida", "Milwaukee": "Wisconsin",
    "Minneapolis": "Minnesota", "New Orleans": "Louisiana", "New York City": "New York",
    "Oklahoma City": "Oklahoma", "Philadelphia": "Pennsylvania", "Phoenix, Arizona": "Arizona",
    "Pittsburgh": "Pennsylvania", "St. Louis": "Missouri", "Salt Lake City": "Utah",
    "San Antonio": "Texas", "San Diego": "California", "San Francisco": "California",
    "Seattle": "Washington", "Washington, D.C.": "Washington, D.C.", "Nashville, Tennessee": "Tennessee",
    "Tampa, Florida": "Florida", "Austin, Texas": "Texas", "Portland, Oregon": "Oregon",
    "Brooklyn": "New York", "Nashville": "Tennessee", "Tampa": "Florida", "Raleigh": "North Carolina",
    "El Paso": "Texas", "Sacramento": "California", "Charlotte": "North Carolina", "Orlando": "Florida",
    "Columbus": "Ohio", "Kansas City": "Missouri", "Louisville": "Kentucky", "Memphis": "Tennessee",
    "Jacksonville": "Florida", "Fort Worth": "Texas", "Tulsa": "Oklahoma", "Albuquerque": "New Mexico",
    "Miami Gardens": "Florida", "Temecula": "California", "Inglewood": "California",
    "Toronto": "Ontario", "Ottawa": "Ontario", "Hamilton, Ontario": "Ontario", "London, Ontario": "Ontario",
    "Montreal": "Quebec", "Quebec City": "Quebec", "Vancouver": "British Columbia",
    "Calgary": "Alberta", "Edmonton": "Alberta", "Winnipeg": "Manitoba", "Saskatoon": "Saskatchewan",
    "Regina, Saskatchewan": "Saskatchewan", "Halifax, Nova Scotia": "Nova Scotia",
    "Moncton": "New Brunswick", "St. John's, Newfoundland and Labrador": "Newfoundland and Labrador",
    "Tucson": "Arizona", "Fresno": "California", "Omaha": "Nebraska", "Buffalo": "New York", "Manhattan": "New York", "Queens": "New York", "Anchorage, Alaska": "Alaska",
}


def _region_from_link(link) -> str | None:
    """'Pasadena, California' -> 'California' (first city wikilink target only)."""
    if not isinstance(link, str):
        return None
    first = link.split(" | ")[0].strip()
    if first in BARE_CITIES:
        return BARE_CITIES[first]
    m = _LINK_REGION.match(first)
    if not m:
        return None
    r = m.group(1).replace("_", " ").strip()
    return r if r in US_STATES or r in CA_PROV or r in AU_STATES or r == "Washington, D.C." else None


def _city_region_fix(df: pd.DataFrame) -> pd.DataFrame:
    """Fill region (state/province) and fix tables that put the state in the country slot.

    region_source: 'table' (own column), 'country_slot', 'city_wikilink' ('City, State'
    link target), or null."""
    def fix(row):
        c, reg = row["country"], row["region"]
        src = "table" if isinstance(reg, str) and reg else None
        # "Georgia" in the country slot is the US state only if the city link says so
        state_in_slot = (c in US_STATES or c in CA_PROV) and not (
            c in AMBIGUOUS_STATE_COUNTRY and _region_from_link(row["city_wikilink"]) != c)
        if state_in_slot:
            return pd.Series({"region": reg if src else c, "region_source": src or "country_slot",
                              "country": "United States" if c in US_STATES else "Canada"})
        if not src:
            reg = _region_from_link(row["city_wikilink"])
            src = "city_wikilink" if reg else None
            if reg and not (isinstance(c, str) and c):
                c = ("United States" if reg in US_STATES or reg == "Washington, D.C." else
                     "Canada" if reg in CA_PROV else "Australia")
        return pd.Series({"region": reg, "region_source": src, "country": c})
    df[["region", "region_source", "country"]] = df.apply(fix, axis=1)
    return df


def build() -> pd.DataFrame:
    files = sorted(PAGES.glob("*.json"))
    latest: dict[int, Path] = {}
    for f in files:  # one revision per page
        pid = int(f.stem.split("__")[0])
        latest[pid] = f
    all_rows: list[dict] = []
    n_pages_with_rows = 0
    for f in latest.values():
        p = json.loads(f.read_text())
        try:
            r = parse_page(p)
        except Exception as exc:  # noqa: BLE001
            print("parse error", p["title"], exc)
            continue
        n_pages_with_rows += bool(r)
        all_rows.extend(r)
    df = pd.DataFrame(all_rows)
    if df.empty:
        print("no rows")
        return df
    # Wikipedia links a city only on first mention: carry the link to later rows of the same page
    first_link = (df.dropna(subset=["city_wikilink"]).groupby(["tour_page_id", "city"])["city_wikilink"]
                  .first())
    miss = df["city_wikilink"].isna() & df["city"].notna()
    df.loc[miss, "city_wikilink"] = [first_link.get((pid, c)) for pid, c in
                                     zip(df.loc[miss, "tour_page_id"], df.loc[miss, "city"])]
    # rows without a venue are not single shows (tour-summary rows on "List of ... live
    # performances" pages, TBA venues) and cannot form a show_id; drop them
    not_show = df["venue"].isna()
    print(f"dropping {int(not_show.sum())} venue-less rows")
    df = df[~not_show].copy()
    df = _city_region_fix(df)
    # remaining US/CA/AU gaps: city name -> region learned from other rows, only when unambiguous
    known = df[df["region"].notna() & df["city"].notna()]
    amb = known.groupby(["country", "city"])["region"].nunique()
    cmap = known.groupby(["country", "city"])["region"].first()[amb == 1]
    gap = df["region"].isna() & df["country"].isin(["United States", "Canada", "Australia"])
    fill = [cmap.get((c, ci)) for c, ci in zip(df.loc[gap, "country"], df.loc[gap, "city"])]
    df.loc[gap, "region"] = fill
    df.loc[gap & df["region"].notna(), "region_source"] = "city_name_map"
    df["country_iso2"] = df["country"].map(iso2)
    df["gross_usd"] = df["gross"].where(df["gross_currency"] == "USD")
    ok = (df["tickets_sold"] > 0) & df["gross_usd"].notna()
    df["avg_price_usd"] = (df["gross_usd"] / df["tickets_sold"]).where(ok)
    # implausible averages are kept but flagged
    df["avg_price_flag"] = None
    df.loc[ok & ((df["avg_price_usd"] < 5) | (df["avg_price_usd"] > 2000)), "avg_price_flag"] = "implausible"
    df["sellout_ratio"] = (df["tickets_sold"] / df["tickets_available"]).where(df["tickets_available"] > 0)
    # artist: infobox, else article title minus "Tour"
    fallback = df["tour_title"].str.replace(r"\s*\(.*\)$", "", regex=True)
    df["artist_name"] = df.get("artist_name", pd.Series(index=df.index, dtype=object)).fillna(fallback)
    df["artist_id"] = df["artist_name"].map(slug)
    df["venue_id"] = df["venue"].map(slug) + "__" + df["city"].map(slug)
    df["show_id"] = df["artist_id"] + "__" + df["show_date"].astype(str) + "__" + df["venue"].map(slug)
    # same show on two pages (main tour article + "List of ... concerts"): keep the row with more figures
    df["_score"] = df[["tickets_sold", "gross"]].notna().sum(axis=1)
    df = (df.sort_values(["_score", "tour_revid"], ascending=False)
            .drop_duplicates(["show_id", "tour_page_id", "table_index"]))
    dup = df.duplicated(["show_id", "attendance_raw", "revenue_raw"], keep="first")
    df = df[~dup].drop(columns="_score")
    df = df.sort_values(["artist_id", "show_date", "venue_id"]).reset_index(drop=True)
    k = df.groupby("show_id").cumcount()
    df.loc[k > 0, "show_id"] = df.loc[k > 0, "show_id"] + "__" + (k[k > 0] + 1).astype(str)
    df["capacity_bucket"] = pd.cut(df["tickets_available"].fillna(df["tickets_sold"]),
                                   [0, 3000, 8000, 25000, 1e7],
                                   labels=["<3k club/theater", "3k-8k theater/amph.", "8k-25k arena", "25k+ stadium"])
    df["show_date"] = pd.to_datetime(df["show_date"])
    for c in ("tour_start_date", "tour_end_date", "tour_announced_date"):
        if c in df:
            df[c] = pd.to_datetime(df[c])
    df["source"] = "enwiki-20261001 dump; CC BY-SA 4.0; attribute tour_title @ tour_revid"
    front = ["show_id", "artist_id", "venue_id", "show_date", "artist_name", "venue", "city", "region", "region_source",
             "country", "country_iso2", "tickets_sold", "tickets_available", "gross", "gross_currency",
             "gross_usd", "avg_price_usd", "sellout_ratio", "aggregate_n_shows", "aggregate_is_first",
             "status_note", "tour_title", "leg"]
    df = df[front + [c for c in df.columns if c not in front]]
    OUT.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(OUT, index=False)
    write_coverage(df, len(latest), n_pages_with_rows)
    print(f"{len(df)} rows from {n_pages_with_rows}/{len(latest)} pages; "
          f"{int(df['avg_price_usd'].notna().sum())} with avg price")
    return df


def write_coverage(df: pd.DataFrame, n_pages: int, n_used: int) -> None:
    priced = df[df["avg_price_usd"].notna()]
    lines = ["# shows_base coverage", "",
             f"Generated from {n_pages} cached tour pages ({n_used} yielded show rows).", "",
             f"- show rows: {len(df)}", f"- rows with avg price (USD gross and tickets sold): {len(priced)}",
             f"- artists (priced): {priced['artist_id'].nunique()}; tours (priced): {priced['tour_page_id'].nunique()}",
             f"- venues (priced): {priced['venue_id'].nunique()}; countries (priced): {priced['country_iso2'].nunique()}",
             f"- rows with gross in a non-USD currency: {int((df['gross'].notna() & (df['gross_currency'] != 'USD')).sum())}",
             f"- rows flagged implausible avg price: {int((df['avg_price_flag'] == 'implausible').sum())}",
             f"- rows that are part of a multi-show aggregate figure: {int((df['aggregate_n_shows'] > 1).sum())}", ""]

    def tbl(title, s):
        lines.extend([f"## {title}", "", "| value | priced shows |", "|---|---|"])
        lines.extend(f"| {k} | {v} |" for k, v in s.items())
        lines.append("")
    tbl("By year (priced)", priced["show_date"].dt.year.value_counts().sort_index())
    tbl("By country, top 25 (priced)", priced["country_iso2"].fillna("unknown").value_counts().head(25))
    tbl("By capacity bucket (priced; available, else sold)", priced["capacity_bucket"].value_counts(sort=False))
    tbl("Top 25 artists by priced shows", priced["artist_name"].value_counts().head(25))
    lines.append("Genre is not in the tour articles; collector-features joins it from Wikidata/MusicBrainz.")
    COVERAGE.write_text("\n".join(lines) + "\n")


if __name__ == "__main__":
    build()
