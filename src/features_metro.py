"""US metro (CBSA) context per venue (A8) -> data/interim/features_metro.parquet + venue_metro.parquet.

Sources (all cached under data/raw/census_acs/, downloaded from www2.census.gov, robots allows all):
- ACS 2024 5-year table-based summary file (2020-2024): B19013 (median household income),
  B01003 (total population), B14001 (school enrollment by level).
- OMB July 2023 CBSA delineation (list1_2023.xlsx): county -> CBSA. Matches the ACS 2024 CBSA codes.
- 2024 Gazetteer places: place name, state, internal-point lat/lon.

Venue -> place -> county (largest population piece, ACS summary level 155) -> CBSA.
"""
from __future__ import annotations

import re
import unicodedata
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd

from context_http import load_venue_coords, INTERIM, out_dir, RAW, fetch_cached, load_spine

ACS_VINTAGE = 2024
ACS_BASE = f"https://www2.census.gov/programs-surveys/acs/summary_file/{ACS_VINTAGE}/table-based-SF/data/5YRData/"
TABLES = ["b19013", "b01003", "b14001"]
DELINEATION_URL = ("https://www2.census.gov/programs-surveys/metro-micro/geographies/reference-files/2023/"
                   "delineation-files/list1_2023.xlsx")
GAZ_URL = "https://www2.census.gov/geo/docs/maps-data/data/gazetteer/2024_Gazetteer/2024_Gaz_place_national.zip"
# County subdivisions: New England towns (Mansfield MA, Foxborough MA) are not Census places.
COUSUB_URL = "https://www2.census.gov/geo/docs/maps-data/data/gazetteer/2024_Gazetteer/2024_Gaz_cousubs_national.zip"

CACHE = RAW / "census_acs"
COLLEGE_SHARE_THRESHOLD = 0.15  # enrolled college/grad students / total population
MAX_COORD_MATCH_KM = 15.0       # coordinate match to a place centroid must be at least this close
NAME_COORD_MAX_KM = 40.0        # a name match is accepted if its centroid is this close to the venue coords
# Census internal points that sit off the mainland (San Francisco's is in the Farallon Islands).
PLACE_COORD_OVERRIDES = {"0667000": (37.7793, -122.4193)}  # San Francisco City Hall

STATES = {
    "alabama": "AL", "alaska": "AK", "arizona": "AZ", "arkansas": "AR", "california": "CA", "colorado": "CO",
    "connecticut": "CT", "delaware": "DE", "district of columbia": "DC", "washington, d.c.": "DC",
    "washington dc": "DC", "d.c.": "DC", "florida": "FL", "georgia": "GA", "hawaii": "HI", "idaho": "ID",
    "illinois": "IL", "indiana": "IN", "iowa": "IA", "kansas": "KS", "kentucky": "KY", "louisiana": "LA",
    "maine": "ME", "maryland": "MD", "massachusetts": "MA", "michigan": "MI", "minnesota": "MN",
    "mississippi": "MS", "missouri": "MO", "montana": "MT", "nebraska": "NE", "nevada": "NV",
    "new hampshire": "NH", "new jersey": "NJ", "new mexico": "NM", "new york": "NY", "north carolina": "NC",
    "north dakota": "ND", "ohio": "OH", "oklahoma": "OK", "oregon": "OR", "pennsylvania": "PA",
    "rhode island": "RI", "south carolina": "SC", "south dakota": "SD", "tennessee": "TN", "texas": "TX",
    "utah": "UT", "vermont": "VT", "virginia": "VA", "washington": "WA", "west virginia": "WV",
    "wisconsin": "WI", "wyoming": "WY", "puerto rico": "PR",
}
# Common tour-table city spellings -> Gazetteer place base name.
CITY_ALIASES = {
    "new york city": "new york", "nyc": "new york", "brooklyn": "new york", "queens": "new york",
    "manhattan": "new york", "the bronx": "new york", "bronx": "new york", "staten island": "new york",
    "honolulu": "urban honolulu", "nashville": "nashville-davidson", "louisville": "louisville/jefferson county",
    "washington, d.c.": "washington", "washington d.c.": "washington", "washington dc": "washington",
    "st. louis": "st. louis", "saint louis": "st. louis", "st louis": "st. louis", "saint paul": "st. paul",
    "st paul": "st. paul", "hollywood": "los angeles", "indianapolis": "indianapolis",
    "lexington": "lexington-fayette", "augusta": "augusta-richmond county", "athens": "athens-clarke county",
    "boise": "boise city", "napa valley": "napa", "belmont park": "elmont", "san buenaventura": "san buenaventura (ventura)", "ventura": "san buenaventura (ventura)",
}
# Venue towns whose names are shared by a larger or similar-sized US place elsewhere. Used only when
# shows_base gives no state and no venue coordinates exist.
CITY_DEFAULT_STATE = {
    "pasadena": "CA", "morrison": "CO", "arlington": "TX", "glendale": "AZ", "inglewood": "CA",
    "east rutherford": "NJ", "foxborough": "MA", "foxboro": "MA", "paradise": "NV", "las vegas": "NV",
    "george": "WA", "santa clara": "CA", "mansfield": "MA", "uniondale": "NY", "elmont": "NY",
    "landover": "MD", "wantagh": "NY", "holmdel": "NJ", "camden": "NJ", "bristow": "VA",
    "noblesville": "IN", "tinley park": "IL", "clarkston": "MI", "burgettstown": "PA",
    "cuyahoga falls": "OH", "saratoga springs": "NY", "west palm beach": "FL", "irvine": "CA",
    "auburn": "WA", "rosemont": "IL", "independence": "MO", "highland park": "IL",
    "the woodlands": "TX", "belmont park": "NY", "woodlands": "TX", "uncasville": "CT", "atlantic city": "NJ",
}
# (state, city as written) -> Census place / county-subdivision base name, for venue towns that aren't
# Census places, or are spelled differently in tour tables.
STATE_CITY_ALIASES = {
    ("CT", "uncasville"): "montville", ("MI", "clarkston"): "independence", ("NY", "darien center"): "darien",
    ("VA", "bristow"): "gainesville", ("PA", "university park"): "state college", ("UT", "salt lake"): "salt lake city",
    ("OH", "cuyahoga"): "cuyahoga falls", ("NY", "hopwell"): "hopewell", ("GA", "cumberland"): "smyrna",
    ("NJ", "holmdel township"): "holmdel", ("FL", "lake buena vista"): "bay lake",
    ("CA", "angels camp"): "angels", ("MI", "mt. pleasant"): "mount pleasant", ("MI", "mt pleasant"): "mount pleasant",
    ("MA", "west springfield"): "west springfield town", ("CO", "snowmass"): "snowmass village",
    ("MO", "ridgedale"): "branson", ("CA", "paso robles"): "el paso de robles (paso robles)",
    ("GA", "macon"): "macon-bibb county", ("WI", "lacrosse"): "la crosse", ("MA", "allston"): "boston",
    ("OK", "oklahoma"): "oklahoma city", ("TX", "odessa city"): "odessa", ("NY", "belmont park"): "elmont", ("PA", "upper darby township"): "upper darby",
}
_US_SUFFIX = re.compile(r",\s*(united states( of america)?|usa|u\.s\.a?\.?|us)\s*$", re.IGNORECASE)
_DC = re.compile(r"^washington,?\s*d\.?\s*c\.?$", re.IGNORECASE)


def normalize_city(city, state) -> tuple[str, object]:
    """'New York City, United States' -> ('new york city', state); 'Austin, Texas' -> ('austin', 'TX')."""
    c = _US_SUFFIX.sub("", str(city or "")).strip()
    c = re.sub(r"^usa\s+", "", c, flags=re.IGNORECASE)  # "USA Commerce City, CO, United States"
    if _DC.match(c):
        return "washington", "DC"
    if "," in c:
        head, tail = (x.strip() for x in c.rsplit(",", 1))
        tail_state = tail.upper() if len(tail) == 2 and tail.isalpha() else STATES.get(tail.lower())
        if tail_state:
            c = head
            state = state if not pd.isna(state) else tail_state
    return c.lower(), state


AMBIGUITY_RATIO = 3.0  # name-only: top place must be >= 3x the population of the runner-up

# Government-form suffixes can stack ("Indianapolis city (balance)"); strip them repeatedly, then
# strip at most ONE place-type suffix so "Salt Lake City city" -> "salt lake city".
_GOV_SUFFIXES = [" consolidated government (balance)", " metropolitan government (balance)",
                 " metro government (balance)", " unified government (balance)", " (balance)", " urban county",
                 " zona urbana", " comunidad"]
_LSAD_SUFFIXES = [" charter township", " township", " city and borough", " municipality", " borough", " village", " city", " town", " cdp"]


def _download() -> dict[str, Path]:
    paths = {t: fetch_cached(ACS_BASE + f"acsdt5y{ACS_VINTAGE}-{t}.dat",
                             CACHE / str(ACS_VINTAGE) / f"acsdt5y{ACS_VINTAGE}-{t}.dat") for t in TABLES}
    paths["delineation"] = fetch_cached(DELINEATION_URL, CACHE / "delineation" / "list1_2023.xlsx")
    paths["gazetteer"] = fetch_cached(GAZ_URL, CACHE / "gazetteer" / "2024_Gaz_place_national.zip")
    paths["cousub"] = fetch_cached(COUSUB_URL, CACHE / "gazetteer" / "2024_Gaz_cousubs_national.zip")
    return paths


def _read_acs(path: Path, prefixes: tuple[str, ...]) -> pd.DataFrame:
    """Read only rows for the given GEO_ID prefixes (the files hold every geography)."""
    with open(path) as f:
        header = f.readline().rstrip("\n").split("|")
        rows = [ln.rstrip("\n").split("|") for ln in f if ln.startswith(prefixes)]
    df = pd.DataFrame(rows, columns=header)
    for c in header[1:]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
        df.loc[df[c] < -100_000_000, c] = np.nan  # ACS annotation codes (-666666666 etc.) -> missing
    return df


def _base_name(name: str) -> str:
    n = name.lower().strip()
    changed = True
    while changed:
        changed = False
        for suf in _GOV_SUFFIXES:
            if n.endswith(suf):
                n, changed = n[: -len(suf)].strip(), True
    for suf in _LSAD_SUFFIXES:
        if n.endswith(suf):
            return n[: -len(suf)].strip()
    return n


def _read_gazetteer(path: Path) -> pd.DataFrame:
    with zipfile.ZipFile(path) as z:
        g = pd.read_csv(z.open(z.namelist()[0]), sep="\t", dtype={"GEOID": str})
    g.columns = [c.strip() for c in g.columns]
    g["base"] = g.NAME.map(_base_name)
    return g


def _load_reference(paths: dict[str, Path]) -> dict[str, pd.DataFrame]:
    pref = ("310M700US", "1600000US", "1550000US", "0500000US")
    inc = _read_acs(paths["b19013"], pref)
    pop = _read_acs(paths["b01003"], pref)
    enr = _read_acs(paths["b14001"], pref)
    acs = (inc[["GEO_ID", "B19013_E001", "B19013_M001"]]
           .merge(pop[["GEO_ID", "B01003_E001"]], on="GEO_ID", how="outer")
           .merge(enr[["GEO_ID", "B14001_E001", "B14001_E008", "B14001_E009"]], on="GEO_ID", how="outer"))
    acs = acs.rename(columns={"B19013_E001": "median_hh_income", "B19013_M001": "median_hh_income_moe",
                              "B01003_E001": "population", "B14001_E001": "pop_3plus"})
    acs["college_enrolled"] = acs.B14001_E008 + acs.B14001_E009
    acs["college_share"] = acs.college_enrolled / acs.population

    d = pd.read_excel(paths["delineation"], header=2, dtype=str)
    d = d.dropna(subset=["FIPS State Code", "FIPS County Code"])
    d["county_fips"] = d["FIPS State Code"].str.zfill(2) + d["FIPS County Code"].str.zfill(3)
    county_cbsa = d[["county_fips", "CBSA Code", "CBSA Title", "Metropolitan/Micropolitan Statistical Area",
                     "CSA Code", "CSA Title"]].rename(columns={
        "CBSA Code": "cbsa_code", "CBSA Title": "cbsa_title",
        "Metropolitan/Micropolitan Statistical Area": "cbsa_type", "CSA Code": "csa_code", "CSA Title": "csa_title"})

    gaz = _read_gazetteer(paths["gazetteer"])
    for geoid, (la, lo) in PLACE_COORD_OVERRIDES.items():
        gaz.loc[gaz.GEOID == geoid, ["INTPTLAT", "INTPTLONG"]] = [la, lo]
    gaz = gaz.merge(acs[["GEO_ID", "population"]].assign(GEOID=lambda x: x.GEO_ID.str[9:])
                    [acs.GEO_ID.str.startswith("1600000US")][["GEOID", "population"]], on="GEOID", how="left")

    pc = acs[acs.GEO_ID.str.startswith("1550000US")][["GEO_ID", "population"]].copy()
    pc["place_geoid"] = pc.GEO_ID.str[9:16]
    pc["county_fips"] = pc.GEO_ID.str[9:11] + pc.GEO_ID.str[16:19]
    place_county = (pc.sort_values("population", ascending=False)
                    .drop_duplicates("place_geoid")[["place_geoid", "county_fips"]])
    cousub = _read_gazetteer(paths["cousub"])
    cousub = cousub[~cousub.NAME.str.contains("not defined", case=False)]
    return {"acs": acs, "county_cbsa": county_cbsa, "gaz": gaz, "place_county": place_county, "cousub": cousub}


def _venue_coords(spine: pd.DataFrame) -> pd.DataFrame | None:
    """Venue coordinates and US state from collector-features, with the shared guards applied."""
    v = load_venue_coords(spine)
    return None if v is None else v[["venue_id", "lat", "lon", "venue_us_state"]]


def _haversine_km(lat1, lon1, lat2, lon2):
    lat1, lon1, lat2, lon2 = map(np.radians, (lat1, lon1, lat2, lon2))
    a = np.sin((lat2 - lat1) / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin((lon2 - lon1) / 2) ** 2
    return 6371.0 * 2 * np.arcsin(np.sqrt(a))


def _name_variants(*names: str) -> list[str]:
    """Spelling variants seen in tour tables: accents, Saint/St., trailing 'township', New England 'X Town'."""
    out: list[str] = []
    for n in names:
        if not n:
            continue
        a = unicodedata.normalize("NFKD", n).encode("ascii", "ignore").decode()
        for x in (n, a):
            out.append(x)
            if x.startswith("saint "):
                out.append("st. " + x[6:])
            if x.startswith("st. "):
                out.append("saint " + x[4:])
            if x.endswith(" township"):
                out.append(x[: -len(" township")])
            out.append(x + " town")
    return list(dict.fromkeys(out))


def match_places(venues: pd.DataFrame, gaz: pd.DataFrame, cousub: pd.DataFrame | None = None) -> pd.DataFrame:
    """venues: venue_id, city, state_usps, lat, lon -> place_geoid | county_fips, match_method, match_note.

    Name first (city + state); venue coordinates, when present, verify the name match (<= NAME_COORD_MAX_KM)
    and otherwise pick the nearest place internal point (<= MAX_COORD_MATCH_KM).
    """
    out = []
    for v in venues.itertuples(index=False):
        rec = {"venue_id": v.venue_id, "place_geoid": None, "county_fips": None, "match_method": "unmatched",
               "match_note": None, "coord_conflict_km": None}
        raw_city, state = normalize_city(v.city, v.state_usps)
        city = STATE_CITY_ALIASES.get((state, raw_city)) or CITY_ALIASES.get(raw_city, raw_city)
        has_xy = not pd.isna(v.lat) and not pd.isna(v.lon)
        defaulted = False
        if pd.isna(state) and not has_xy and city in CITY_DEFAULT_STATE:
            state, defaulted = CITY_DEFAULT_STATE[city], True
        cand = gaz if pd.isna(state) else gaz[gaz.USPS == state]
        variants = _name_variants(city, raw_city, city.split(",")[0].strip() if "," in city else "")
        hits = cand[cand.base.isin(variants)]

        if has_xy and not hits.empty:
            d = _haversine_km(v.lat, v.lon, hits.INTPTLAT.values, hits.INTPTLONG.values)
            i = int(np.argmin(d))
            if d[i] <= NAME_COORD_MAX_KM:
                rec.update(place_geoid=hits.GEOID.iloc[i], match_method="name_coords_verified",
                           match_note=f"{hits.NAME.iloc[i]}, {hits.USPS.iloc[i]} ({d[i]:.1f} km)")
                out.append(rec)
                continue
            # The tour table's city exists in this state but far from the venue coordinates. Wikidata
            # resolution is the likelier error (chains like "Hard Rock Live"), so trust the name.
            rec["coord_conflict_km"] = round(float(d[i]), 1)
            has_xy = False
        if has_xy:
            d = _haversine_km(v.lat, v.lon, cand.INTPTLAT.values, cand.INTPTLONG.values)
            i = int(np.argmin(d))
            if d[i] <= MAX_COORD_MATCH_KM:
                rec.update(place_geoid=cand.GEOID.iloc[i], match_method="coords_nearest_place",
                           match_note=f"{cand.NAME.iloc[i]}, {cand.USPS.iloc[i]} ({d[i]:.1f} km)")
                out.append(rec)
                continue
        if not hits.empty:
            hits = hits.sort_values("population", ascending=False)
            best = hits.iloc[0]
            how = ("name_default_state" if defaulted else "name_state" if not pd.isna(state)
                   else "name_only_most_populous")
            note = f"{best.NAME}, {best.USPS}"
            if len(hits) > 1:
                pops = hits.population.fillna(0).tolist()
                if how == "name_only_most_populous" and pops[0] < AMBIGUITY_RATIO * pops[1]:
                    rec.update(match_method="ambiguous_name", match_note="; ".join(
                        f"{r.NAME}, {r.USPS} ({r.population:,.0f})" for r in hits.head(4).itertuples()))
                    out.append(rec)
                    continue
                note += f" (chosen from {len(hits)} same-name places)"
            rec.update(place_geoid=best.GEOID, match_method=how, match_note=note)
        elif cousub is not None and not pd.isna(state):
            cs = cousub[(cousub.USPS == state) & cousub.base.isin(variants)]
            if not cs.empty:
                best = cs.sort_values("ALAND", ascending=False).iloc[0]
                rec.update(county_fips=best.GEOID[:5], match_method="name_state_county_subdivision",
                           match_note=f"{best.NAME}, {best.USPS}" + (f" (chosen from {len(cs)})" if len(cs) > 1 else ""))
        out.append(rec)
    return pd.DataFrame(out)


def build(spine: pd.DataFrame, ref: dict[str, pd.DataFrame]) -> tuple[pd.DataFrame, pd.DataFrame]:
    def _mode(x: pd.Series):  # most common non-null value: one bad row shouldn't relabel a venue
        m = x.dropna().mode()
        return m.iloc[0] if len(m) else pd.NA

    venues = spine.groupby("venue_id", as_index=False).agg(
        city=("city", _mode), state=("state", _mode), country_iso2=("country_iso2", _mode))
    coords = _venue_coords(spine)
    venues = venues.merge(coords, on="venue_id", how="left") if coords is not None else venues.assign(lat=np.nan, lon=np.nan)
    st = venues.state.astype("string").str.strip()
    venues["state_usps"] = st.where(st.str.len() == 2).str.upper().fillna(st.str.lower().map(STATES))
    if "venue_us_state" in venues:
        venues["state_usps"] = venues.state_usps.fillna(venues.venue_us_state)

    us = venues[venues.country_iso2.isin(["US", "PR"])]
    m = match_places(us, ref["gaz"], ref["cousub"]) if len(us) else pd.DataFrame(
        columns=["venue_id", "place_geoid", "county_fips", "match_method", "match_note", "coord_conflict_km"])
    m = m.merge(ref["place_county"].rename(columns={"county_fips": "place_county_fips"}), on="place_geoid", how="left")
    m["county_fips"] = m.county_fips.fillna(m.place_county_fips)
    m = m.drop(columns="place_county_fips").merge(ref["county_cbsa"], on="county_fips", how="left")
    vm = venues[["venue_id", "city", "state_usps", "country_iso2"]].merge(m, on="venue_id", how="left")
    vm["match_method"] = vm.match_method.fillna("non_us")

    acs = ref["acs"]
    cbsa = acs[acs.GEO_ID.str.startswith("310M700US")].assign(cbsa_code=lambda x: x.GEO_ID.str[9:])
    county = acs[acs.GEO_ID.str.startswith("0500000US")].assign(county_fips=lambda x: x.GEO_ID.str[9:])
    place = acs[acs.GEO_ID.str.startswith("1600000US")].assign(place_geoid=lambda x: x.GEO_ID.str[9:])
    keep = ["median_hh_income", "median_hh_income_moe", "population", "college_share"]

    f = (vm.merge(cbsa[["cbsa_code", *keep]].add_prefix("metro_").rename(columns={"metro_cbsa_code": "cbsa_code"}),
                  on="cbsa_code", how="left")
           .merge(county[["county_fips", *keep]].add_prefix("county_").rename(columns={"county_county_fips": "county_fips"}),
                  on="county_fips", how="left")
           .merge(place[["place_geoid", "median_hh_income", "population"]]
                  .rename(columns={"median_hh_income": "place_median_hh_income", "population": "place_population"}),
                  on="place_geoid", how="left"))
    f["is_us"] = f.country_iso2.isin(["US", "PR"])
    f["metro_scope"] = np.select(
        [~f.is_us, f.county_fips.isna(), f.cbsa_code.isna(), f.cbsa_type.str.startswith("Metro", na=False)],
        ["non_us", "us_unmatched", "us_outside_cbsa", "metropolitan"], default="micropolitan")
    f["metro_log_population"] = np.log(f.metro_population)
    f["is_college_town"] = (f.metro_college_share >= COLLEGE_SHARE_THRESHOLD).astype("boolean").where(
        f.metro_college_share.notna())
    f["match_confidence"] = np.select(
        [f.match_method.isin(["coords_nearest_place", "name_coords_verified", "name_state", "name_default_state",
                              "name_state_county_subdivision"]),
         f.match_method.eq("name_only_most_populous")], ["high", "low"], default=None)
    f["acs_vintage"] = f"{ACS_VINTAGE} 5-year ({ACS_VINTAGE - 4}-{ACS_VINTAGE})"
    cols = ["venue_id", "is_us", "metro_scope", "cbsa_code", "cbsa_title", "cbsa_type", "csa_code", "csa_title",
            "metro_median_hh_income", "metro_median_hh_income_moe", "metro_population", "metro_log_population",
            "metro_college_share", "is_college_town",
            "county_fips", "county_median_hh_income", "county_population", "county_college_share",
            "place_geoid", "place_median_hh_income", "place_population",
            "match_method", "match_confidence", "match_note", "coord_conflict_km", "acs_vintage"]
    features = f[cols]
    venue_metro = f[["venue_id", "city", "state_usps", "country_iso2", "place_geoid", "county_fips", "cbsa_code",
                     "cbsa_title", "csa_code", "match_method", "match_note", "coord_conflict_km"]]
    return features, venue_metro


def main() -> None:
    ref = _load_reference(_download())
    features, venue_metro = build(load_spine(), ref)
    features.to_parquet(out_dir() / "features_metro.parquet", index=False)
    venue_metro.to_parquet(out_dir() / "venue_metro.parquet", index=False)
    print(f"wrote features_metro.parquet / venue_metro.parquet: {len(features)} venues")
    print(features.metro_scope.value_counts().to_string())
    print(features.match_method.value_counts().to_string())


if __name__ == "__main__":
    main()
