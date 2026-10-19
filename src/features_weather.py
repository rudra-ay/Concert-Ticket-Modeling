"""Show-day weather per show from the Open-Meteo historical archive API (A7)
-> data/interim/features_weather.parquet.

Open-Meteo's archive API is the one robots.txt exception approved in DECISIONS.md (weather only).
Free tier, non-commercial use only; data CC BY 4.0, "Weather data by Open-Meteo.com".

Coordinates, in order of preference:
  1. data/interim/features_venue.parquet (collector-features, Wikidata venue coordinates);
  2. Census Gazetteer internal point of the venue's matched US place (venue_metro.parquet, features_metro.py).
Non-US venues without venue coordinates get no weather.

One request per (venue, cluster of show dates spanning <= 14 days); hours are venue-local (timezone=auto).
Responses are cached in data/raw/open_meteo/ and never refetched. A 403/429 stops the whole run.
"""
from __future__ import annotations

import datetime as dt
import json
import zipfile

import numpy as np
import pandas as pd
import requests

from context_http import venue_features_path, INTERIM, RAW, BlockedError, fetch_cached, load_spine, out_dir

API = "https://archive-api.open-meteo.com/v1/archive"
CACHE = RAW / "open_meteo"
CLUSTER_DAYS = 14   # Open-Meteo counts >2 weeks of data as more than one call
ARCHIVE_LAG_DAYS = 6  # the archive (ERA5 + forecast blend) lags real time by about 5 days
EVENING_HOURS = range(18, 24)  # 18:00-23:00 local, inclusive
DAILY = ["temperature_2m_max", "temperature_2m_min", "precipitation_sum", "rain_sum", "snowfall_sum",
         "precipitation_hours", "wind_speed_10m_max", "weather_code"]
HOURLY = ["temperature_2m", "apparent_temperature", "precipitation", "wind_speed_10m", "weather_code"]


def venue_coordinates(spine: pd.DataFrame) -> pd.DataFrame:
    venues = spine[["venue_id"]].drop_duplicates()
    parts = []
    fv = venue_features_path()
    if fv.exists():
        v = pd.read_parquet(fv)
        lat = next((c for c in ["lat", "latitude", "venue_lat"] if c in v), None)
        lon = next((c for c in ["lon", "lng", "longitude", "venue_lon"] if c in v), None)
        if lat and lon and "venue_id" in v:
            parts.append(v[["venue_id", lat, lon]].rename(columns={lat: "lat", lon: "lon"})
                         .dropna().drop_duplicates("venue_id").assign(coord_source="venue_wikidata"))
    vm_path = out_dir() / "venue_metro.parquet"
    gaz_path = RAW / "census_acs" / "gazetteer" / "2024_Gaz_place_national.zip"
    if vm_path.exists() and gaz_path.exists():
        vm = pd.read_parquet(vm_path)[["venue_id", "place_geoid"]].dropna()
        with zipfile.ZipFile(gaz_path) as z:
            gaz = pd.read_csv(z.open(z.namelist()[0]), sep="\t", dtype={"GEOID": str})
        gaz.columns = [c.strip() for c in gaz.columns]
        g = vm.merge(gaz[["GEOID", "INTPTLAT", "INTPTLONG"]], left_on="place_geoid", right_on="GEOID")
        parts.append(g.rename(columns={"INTPTLAT": "lat", "INTPTLONG": "lon"})[["venue_id", "lat", "lon"]]
                     .assign(coord_source="census_place_centroid"))
    if not parts:
        return venues.assign(lat=np.nan, lon=np.nan, coord_source=pd.NA)
    coords = pd.concat(parts).drop_duplicates("venue_id", keep="first")  # venue coords win
    return venues.merge(coords, on="venue_id", how="left")


def date_clusters(dates: list[dt.date]) -> list[tuple[dt.date, dt.date]]:
    out: list[tuple[dt.date, dt.date]] = []
    for d in sorted(set(dates)):
        if out and (d - out[-1][0]).days < CLUSTER_DAYS:
            out[-1] = (out[-1][0], d)
        else:
            out.append((d, d))
    return out


def fetch(venue_id: str, lat: float, lon: float, start: dt.date, end: dt.date) -> dict | None:
    path = CACHE / f"{venue_id}__{lat:.3f}_{lon:.3f}__{start}__{end}.json"
    params = {"latitude": round(lat, 4), "longitude": round(lon, 4), "start_date": str(start),
              "end_date": str(end), "daily": ",".join(DAILY), "hourly": ",".join(HOURLY),
              "timezone": "auto", "wind_speed_unit": "kmh"}
    try:
        fetch_cached(API, path, params=params)
    except BlockedError:
        raise
    except requests.HTTPError as e:
        print(f"  skip {venue_id} {start}..{end}: {e}")
        return None
    return json.loads(path.read_text())


def summarise(resp: dict, day: dt.date) -> dict:
    rec: dict = {"wx_grid_lat": resp.get("latitude"), "wx_grid_lon": resp.get("longitude"),
                 "wx_timezone": resp.get("timezone"), "wx_elevation_m": resp.get("elevation")}
    daily = pd.DataFrame(resp["daily"])
    row = daily[daily.time == str(day)]
    if row.empty:
        return rec
    r = row.iloc[0]
    rec.update(
        wx_temp_max_c=r.temperature_2m_max, wx_temp_min_c=r.temperature_2m_min,
        wx_precip_mm=r.precipitation_sum, wx_rain_mm=r.rain_sum, wx_snowfall_cm=r.snowfall_sum,
        wx_precip_hours=r.precipitation_hours, wx_wind_max_kmh=r.wind_speed_10m_max,
        wx_weather_code=r.weather_code,
    )
    hourly = pd.DataFrame(resp["hourly"])
    hourly["time"] = pd.to_datetime(hourly.time)
    ev = hourly[(hourly.time.dt.date == day) & hourly.time.dt.hour.isin(EVENING_HOURS)]
    if len(ev):
        rec.update(
            wx_eve_temp_mean_c=ev.temperature_2m.mean(),
            wx_eve_apparent_temp_min_c=ev.apparent_temperature.min(),
            wx_eve_precip_mm=ev.precipitation.sum(min_count=1),
            wx_eve_precip_hours=int((ev.precipitation >= 0.1).sum()),
            wx_eve_wind_max_kmh=ev.wind_speed_10m.max(),
            wx_eve_weather_code_max=ev.weather_code.max(),
            wx_eve_thunderstorm=bool((ev.weather_code >= 95).any()),
            wx_eve_hours_covered=len(ev),
        )
    return rec


def build(spine: pd.DataFrame, today: dt.date | None = None) -> pd.DataFrame:
    today = today or dt.date.today()
    last_available = today - dt.timedelta(days=ARCHIVE_LAG_DAYS)
    shows = spine[["show_id", "venue_id", "date"]].merge(venue_coordinates(spine), on="venue_id", how="left")
    shows["day"] = shows.date.dt.date
    todo = shows.dropna(subset=["lat", "lon", "day"])
    todo = todo[todo.day <= last_available]

    responses: dict[tuple[str, dt.date], dict] = {}
    groups = list(todo.groupby("venue_id"))
    n_req = sum(len(date_clusters(list(g.day))) for _, g in groups)
    print(f"{len(todo)} shows at {len(groups)} venues -> {n_req} requests (cached ones are free)")
    for venue_id, g in groups:
        lat, lon = float(g.lat.iloc[0]), float(g.lon.iloc[0])
        for start, end in date_clusters(list(g.day)):
            resp = fetch(venue_id, lat, lon, start, end)
            if resp is None:
                continue
            for d in g.day[(g.day >= start) & (g.day <= end)]:
                responses[(venue_id, d)] = resp

    rows = []
    for s in shows.itertuples(index=False):
        rec = {"show_id": s.show_id, "wx_coord_source": s.coord_source, "wx_query_lat": s.lat, "wx_query_lon": s.lon}
        if pd.isna(s.day):
            rec["wx_status"] = "no_date"
        elif pd.isna(s.lat):
            rec["wx_status"] = "no_coordinates"
        elif s.day > last_available:
            rec["wx_status"] = "not_yet_in_archive"
        elif (s.venue_id, s.day) not in responses:
            rec["wx_status"] = "request_failed"
        else:
            rec.update(summarise(responses[(s.venue_id, s.day)], s.day))
            rec["wx_status"] = "ok" if "wx_temp_max_c" in rec else "date_missing_in_response"
        rows.append(rec)
    out = pd.DataFrame(rows)
    out["wx_known_at_purchase"] = False  # show-day weather: context variable, not a purchase-time feature
    for c in ["wx_eve_precip_hours", "wx_eve_hours_covered"]:
        if c in out:
            out[c] = out[c].astype("Int16")
    if "wx_eve_thunderstorm" in out:
        out["wx_eve_thunderstorm"] = out.wx_eve_thunderstorm.astype("boolean")
    return out


def main() -> None:
    spine = load_spine()
    try:
        out = build(spine)
    except BlockedError as e:
        print(f"STOPPED: {e}")
        raise SystemExit(2)
    path = out_dir() / "features_weather.parquet"
    out.to_parquet(path, index=False)
    print(f"wrote {path}: {len(out)} rows")
    print(out.wx_status.value_counts().to_string())


if __name__ == "__main__":
    main()
