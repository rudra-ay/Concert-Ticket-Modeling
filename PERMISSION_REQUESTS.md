# PERMISSION_REQUESTS.md

These are sources whose terms prohibit automated access, or that blocked our scout requests, ranked by value to the project. Each draft email is written for the user to send from their own account. Fill in `[Your name]` and review every draft before sending. **Nothing here has been sent.**

Shared framing for every request: a personal, non-commercial research project on how concert ticket prices are set (LEVEL) and how resale prices move before a show (PATH). We will not resell data, build a competing product, or publish raw data; only aggregate findings. We're happy to sign a data-use agreement and to share results.

Contact addresses marked *(verified)* were seen on an official page or in an official press release during scouting. All others say how to find the right contact.

---

## 0. Ticketmaster Discovery API: storage clarification (optional; source is already ALLOWED)
- **Why:** the terms bar caching or storing "Event Content other than for reasonable periods in order to provide the service you are providing". A daily `priceRanges` panel kept for several months is a gray area.
- **Contact:** the developer support form at https://developer.ticketmaster.com/support/contact-us/ *(verified; no email published)*. The page says to use the separate "Partner with Us" form only for partnerships.
- **Ask:** confirmation that keeping daily Discovery snapshots of about 3–5k US music events privately for up to 12 months, for non-commercial analysis, is acceptable. Also whether a modestly higher quota is possible.

> Subject: Research use of Discovery API: data retention question
>
> Hello Ticketmaster Developer team,
>
> I'm running a small, non-commercial personal research project on how concert ticket prices change in the weeks before a show. I plan to use the Discovery API within the default quota (well under 5,000 calls/day, at 1 request/sec or slower) to take one daily snapshot of public event data (dates, status, and priceRanges) for a few thousand US music events.
>
> Your terms limit storing Event Content to "reasonable periods". Could you confirm whether keeping these snapshots privately for up to 12 months, purely for statistical analysis (no redistribution, no public dataset, no consumer product), is acceptable? If a different arrangement is needed, I'm happy to follow it.
>
> Thank you,
> [Your name], rudraayyagari@gmail.com

---

## 1. StubHub: resale listing histories (highest value for PATH)
- **Why it matters:** StubHub is the largest US resale marketplace. Listing-level price histories (all-in price, section, quantity, first and last seen) from about 60 days out to show time are exactly what PATH needs. The terms forbid any "robot, spider, scraper or other automated means ... without our express written permission".
- **Contact:** pr@stubhub.com *(verified as the media contact in StubHub press releases on Business Wire, Feb 2026)*. Ask them to forward the request to data partnerships or research. StubHub (NYSE: STUB) investor relations is a second route.
- **Ask:** a de-identified historical extract for a sample of US concerts from 2023–2026: daily lowest price, median listed price, and listing count by zone, from 90 days out to the event, plus sold prices if possible. Alternatively, written permission for low-rate collection of public event pages for a fixed list of events.

> Subject: Research data request: concert resale price dynamics
>
> Hello StubHub team,
>
> I'm conducting a non-commercial research project on how concert resale prices evolve between about 60 days before a show and show time, and what predicts those paths. Your terms (rightly) prohibit automated collection without written permission, so I'm writing to ask rather than collect anything.
>
> Would StubHub consider sharing a de-identified historical extract for a sample of US concerts? For example: daily lowest and median listed price and listing count by seating zone from 90 days out to the event, and, if possible, aggregated sale prices. I don't need any buyer or seller information. I will not redistribute the data or build a commercial product, I'm happy to sign a data-use agreement, and I'll share the findings with you before anything is published.
>
> If this isn't the right inbox, I'd be grateful if you could forward it to the appropriate data or research team.
>
> Many thanks,
> [Your name], rudraayyagari@gmail.com

---

## 2. TicketData.com: historical "get-in" price series (very high value for PATH)
- **Why it matters:** the site reportedly holds "over a decade" of per-event resale price histories (lowest all-in price, outliers removed), which is a ready-made PATH dataset. Its terms page returned **403** to our fetcher, so I stopped.
- **Contact:** not found. Find it by visiting ticketdata.com in a normal browser and looking for a Contact or About page, or via the founders named in press coverage (Digital Music News, 2025-10-21).
- **Ask:** daily get-in price series for US concerts with event metadata (artist, venue, date) for 2019–2026, or permission for limited, rate-limited access.

> Subject: Academic-style research request: historical concert get-in prices
>
> Hello TicketData team,
>
> I'm working on a non-commercial research project studying how concert resale prices move in the final two months before a show. TicketData's long history of get-in prices is the best resource I've found for this, and I'd much rather ask than collect anything automatically.
>
> Would you be open to sharing daily get-in price histories for a sample of US concerts (artist, venue, date, and daily price), for example 2019–2026? I'd use them only for statistical analysis, would credit TicketData in any write-up, wouldn't redistribute the raw data, and would share results with you first.
>
> Thank you for considering it,
> [Your name], rudraayyagari@gmail.com

---

## 3. SeatGeek: API access and event price stats (high value for PATH and LEVEL)
- **Why it matters:** the public API historically exposed event-level `stats` (lowest, average, median, and highest price, plus listing count). Daily snapshots would give a clean PATH proxy across many events. During scouting, `seatgeek.com` served a **DataDome CAPTCHA (403)** and `seatgeek.ca/api-terms` returned **403**, so I stopped. The developer portal (developer.seatgeek.com) is JS-only, and I couldn't confirm whether new developers can get a `client_id`.
- **Contact:** the developer portal at https://developer.seatgeek.com (login), or SeatGeek's partner program. No email verified.
- **Ask:** a `client_id` for non-commercial research, confirmation that daily polling of `/2/events` stats for about 3k concerts at 1 req/s or slower is acceptable, and whether historical `stats` snapshots exist.

> Subject: Non-commercial research use of the SeatGeek API
>
> Hello SeatGeek Platform team,
>
> I'm doing non-commercial research on concert ticket pricing: how prices differ across shows and how resale prices change as a show approaches. I'd like to use the SeatGeek API's event-level price statistics, polling a few thousand US concerts once per day at 1 request/sec or slower.
>
> Could you let me know whether new developers can still obtain a client_id for this kind of use, and whether daily snapshots kept privately for analysis would be within your API terms? If you keep any historical event-level price statistics, I'd also be very interested in a research extract. No redistribution, no commercial product, and I'll share findings.
>
> Thank you,
> [Your name], rudraayyagari@gmail.com

---

## 4. Pollstar: Data Cloud / Boxoffice (highest value for LEVEL)
- **Why it matters:** this is the standard academic source for per-show gross, tickets sold, capacity, and **price low/high**, covering about 319k artists since 1999. Pollstar is used by Krueger, Courty & Pagliero, and Bennett et al. It would replace the biased Wikipedia subset.
- **Contact:** the demo and sales form at https://pages.pollstar.com/request-a-free-demo. No email verified; Pollstar is part of Oak View Group.
- **Ask:** academic or individual research pricing for a one-time Boxoffice extract (US shows 2010–2026: date, artist, venue, city, capacity, tickets sold, gross, and price low/high).

> Subject: Research licensing inquiry: Boxoffice data extract
>
> Hello Pollstar team,
>
> I'm conducting non-commercial research on the determinants of concert ticket prices, building on published work that used Pollstar Boxoffice data (e.g. Krueger; Courty & Pagliero). I'd like to ask whether Pollstar offers research or academic licensing for a one-time extract of US box office reports for 2010–2026 (date, artist, venue, city, capacity, tickets sold, gross, and ticket price low/high).
>
> I'd use it only for statistical analysis, credit Pollstar, and not redistribute it. Could you let me know what options and pricing exist?
>
> Best regards,
> [Your name], rudraayyagari@gmail.com

---

## 5. Rebrowser: StubHub / SeatGeek / Gametime research grant (high value; provenance decision needed first)
- **Why it matters:** the StubHub listings span 2024-03-31 → 2026-10-11 (142M records) with all-in price, face value, and first and last seen dates. That's directly usable for PATH.
- **Caveat (decide before sending):** Rebrowser sells "undetectable" scraping browsers, and the data was very likely collected against the marketplaces' terms. **I recommend that the lead or user decide whether using it is acceptable before applying.** The cleaner path is item 1 (StubHub directly).
- **Contact:** the research-access checker and request flow at https://rebrowser.net/free-datasets-for-research (sign-in required), or the contact form at https://rebrowser.net/contact-us *(verified pages)*.
- **Ask:** a one-time historical CSV of StubHub concert listings (US, 2024–2026), with the price fields.

> Subject: Research access request: StubHub dataset (historical CSV)
>
> Hello Rebrowser team,
>
> I'm working on a non-commercial research project on concert resale price dynamics and would like to apply for free research access to a one-time historical CSV from your StubHub dataset (US concert events, 2024–2026, including price, face value, section, quantity, and first/last-seen timestamps). I won't redistribute the raw data or use it commercially.
>
> Could you also tell me how the data was collected and whether the marketplace has authorized its redistribution? I need to document provenance for my project.
>
> Thank you,
> [Your name], rudraayyagari@gmail.com

---

## 6. Vivid Seats: resale price histories (high value for PATH)
- **Why it matters:** the second-largest US resale marketplace. Terms §17.3.3 forbid crawling or scraping "other than as permitted under these Terms of Use".
- **Contact:** investor relations at https://investors.vividseats.com, or the media contact listed in Vivid Seats press releases (the name was found, but the email was redacted in search results). The affiliate program reportedly runs via the Impact network.
- **Ask:** the same as StubHub: daily zone-level lowest and median prices and listing counts for a sample of US concerts.

> Subject: Research data request: concert resale price dynamics
>
> Hello Vivid Seats team,
>
> I'm conducting non-commercial research on how concert resale prices change in the two months before a show. Since your Terms of Use don't permit automated collection, I'm writing to ask whether Vivid Seats would share a de-identified historical extract for a sample of US concerts (daily lowest and median price and listing count by zone, 90 days out to the event). No customer data needed, no redistribution, and I'd share findings with you first. Could you forward this to the right data or partnerships contact?
>
> Thank you,
> [Your name], rudraayyagari@gmail.com

---

## 7. Gametime: last-minute prices (medium-high value for the tail of PATH)
- **Why it matters:** Gametime specializes in the final hours, which other sources capture poorly. Terms §1.D prohibit automated or non-automated scraping.
- **Contact:** not verified. Look for a "Press" or "Partners" link in the gametime.co footer.
- **Ask:** hourly or daily lowest price per zone for concerts over the final 7 days, for a sample of US events.

> Subject: Research request: last-minute concert ticket prices
>
> Hello Gametime team,
>
> I'm doing non-commercial research on how concert ticket prices behave in the final days and hours before a show, where Gametime's marketplace is uniquely informative. Your terms prohibit scraping, so I'm asking directly: would you consider sharing a de-identified extract (for example, hourly lowest price by seating zone over the final 7 days) for a sample of US concerts? No redistribution or commercial use, and I'm glad to share findings.
>
> Many thanks,
> [Your name], rudraayyagari@gmail.com

---

## 8. Billboard Boxscore (medium value for LEVEL)
- **Why it matters:** this is the original source of most per-show gross and attendance figures. PMC terms forbid robots, crawlers, and AI tools ("whether automated or manual") for scraping or aggregation. Wikipedia (A1) already covers much of it.
- **Contact:** Billboard's contact page on billboard.com, or PMC's contact and permissions page at https://pmc.com. No email verified.
- **Ask:** permission to compile per-show figures from Boxscore reports for 2010–2026, or a licensed extract.

> Subject: Permission request: research use of Boxscore figures
>
> Hello Billboard team,
>
> I'm conducting non-commercial research on concert ticket pricing and would like permission to compile per-show gross and attendance figures from Billboard Boxscore reports (2010–2026) into a private dataset for statistical analysis, or to license an extract if one exists. I wouldn't republish Billboard content and would cite Boxscore as the source. Could you direct me to the right person?
>
> Thank you,
> [Your name], rudraayyagari@gmail.com

---

## 9. setlist.fm (medium value for features)
- **Why it matters:** tour membership and show counts per tour, and setlist length. Terms forbid retaining "any copies of the Setlist.fm data" except short-period caching.
- **Contact:** via the setlist.fm API forum or the contact page linked from https://api.setlist.fm/docs/1.0/index.html. No email verified.
- **Ask:** permission to retain API responses for about 2k tours privately for analysis.

> Subject: API data retention for non-commercial research
>
> Hello setlist.fm team,
>
> I'm doing non-commercial research on concert ticket pricing and would like to use the setlist.fm API to look up show dates, venues, and tour names for about 2,000 tours. Your API terms restrict retaining data beyond short-term caching. Would you permit me to keep these responses privately for statistical analysis (no redistribution, with attribution to setlist.fm in any write-up)?
>
> Thank you,
> [Your name], rudraayyagari@gmail.com

---

## 10. Last.fm (medium value for features)
- **Why it matters:** artist listeners, playcount, and tags, a popularity measure now that Spotify is unavailable. The API page says research use requires prior contact.
- **Contact:** **partners@last.fm** *(verified on https://www.last.fm/api)*.
- **Ask:** approval for non-commercial research use of `artist.getInfo` for about 3k artists, under the 100 MB usage cap.

> Subject: Research use of the Last.fm API
>
> Hello Last.fm partners team,
>
> Your API page asks researchers to get in touch before use. I'm running a non-commercial personal research project on concert ticket pricing and would like to call artist.getInfo (listeners, playcount, tags) once for about 3,000 artists, slowly, staying well within your usage cap, with Last.fm credited as required. May I go ahead?
>
> Thank you,
> [Your name], rudraayyagari@gmail.com

---

## 11. Google Trends API (alpha) (medium value for features)
- **Contact:** the application flow linked from https://developers.google.com/search/blog/2025/07/trends-api.
- **Ask:** alpha access for weekly or daily interest series for about 1–3k artist names. No email draft is needed; use their form and describe the non-commercial research purpose in two sentences.

## 12. openICPSR 161484 (Bhave & Budish) (medium value; user action, no email)
- The user signs in at https://www.openicpsr.org/openicpsr/project/161484/view, reads the license and terms, and if they're acceptable, downloads manually into `data/raw/openicpsr_161484/`. Record the license text alongside the files.

## 13. TickPick (low-medium value)
- The terms are unverified (the URL I tried returned 404). The user should read the Terms in a browser. If automated access is prohibited, send a request modeled on item 6 via the contact link in the site footer.

## 14. US Census Data API (low value; alternative exists)
- `api.census.gov` rejected our robots.txt request. If the API is wanted, the user gets a free key at https://api.census.gov/data/key_signup.html. Otherwise use the bulk files (SOURCES A8). No email needed.

## 15. Internet Archive Wayback Machine (low value)
- Verify the terms at https://archive.org/about/terms.php in a browser. For bulk or research use questions: info@archive.org (not verified this session). Expected yield of resale prices is low because pages are client-rendered.

## 16. Songkick (low value)
- The API status after the reported 2025 ownership change is unclear. Ask via the Songkick API Google Group (https://groups.google.com/g/songkick-api) only if the other event-calendar sources fail.

## 17. Deezer (low value)
- The terms limit use to "strictly private use within a family scope" and require prior approval for other uses. Ask via https://developers.deezer.com only if no other fan-count proxy works.

## 18. AXS / Live Nation (low value)
- Both terms pages returned 403. Ticketmaster's Discovery API (Live Nation's own official route) covers the same need.

## 19. Kaggle community datasets (lowest value; no email)
- Check each dataset's license on Kaggle in a browser if the lead wants one. They're Wikipedia-derived and redundant with SOURCES A1.
