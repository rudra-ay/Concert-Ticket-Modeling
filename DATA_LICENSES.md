# Data licenses and attribution

The data files in this repository were derived from the sources below. They are shared for **non-commercial
research only**, because some inputs (MusicBrainz tags, Open-Meteo) allow nothing else. The full source notes,
including robots.txt and terms verdicts, are in [SOURCES.md](SOURCES.md).

| Source | Used for | License | Attribution |
|---|---|---|---|
| Wikipedia tour articles (A1) | Show list, grosses and attendance (the facts come from Billboard Boxscore and Pollstar) | CC BY-SA 4.0 (text) | "Contains information from English Wikipedia articles, CC BY-SA 4.0" |
| Wikidata (A2) | Venue capacity, type and coordinates; artist genre and career start | CC0 1.0 | none required |
| Wikimedia Pageviews (A3) | Artist attention (pageviews) | CC0 1.0 | none required |
| MusicBrainz core data (A4) | Artist IDs, type, country, career start | CC0 1.0 | none required |
| MusicBrainz tags (A4, supplementary) | `mb_genre_tags`, `mb_genre_coarse`, and `genre_coarse_final` where it falls back to them | **CC BY-NC-SA 3.0** | "Genre tags from MusicBrainz (musicbrainz.org), CC BY-NC-SA 3.0" |
| ListenBrainz (A5) | Popularity snapshot (2026) | CC0 1.0 | none required |
| Open-Meteo (A7) | Show-day weather (`wx_*`) | CC BY 4.0, free tier non-commercial | "Weather data by Open-Meteo.com" (https://open-meteo.com) |
| US Census ACS (A8), BLS CPI-U (A9) | Metro income and population; inflation deflator | Public domain (US government) | Sources cited in data/DATA_DICTIONARY.md |
| Federal Reserve G.5/H.10 (A12), ECB (A13) | FX checks | Public data; ECB requires citing the source and stating modifications | "Source: ECB, modified (monthly means)" |

**Not redistributed:** Ticketmaster Discovery API data. Snapshots stay in the gitignored `data/forward/`,
and the repo holds only aggregate statistics in `reports/path_tables/tm_*`. Attribution for those:
"Data from Ticketmaster Discovery API".

**Share-alike note:** the MusicBrainz genre columns are CC BY-NC-SA. Anyone reusing `data/shows.parquet`
with those columns must keep it non-commercial and share it under the same terms. To get a release without
the NC restriction, drop `mb_genre_tags`, `mb_genre_coarse` and `genre_coarse_final`, and rebuild genre from
Wikidata alone.

**Known data limitation:** 53 priced shows (0.2%) flagged `link_ambiguous` (venue coordinates more than 50 km from
the city) were kept in the frozen LEVEL model. See the final report's limitations section.
