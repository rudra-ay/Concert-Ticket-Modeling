# Resale vs face, 2023–24 US shows (end of sales window)

Data: 258 shows (17 acts, 19 tours) matched out of 23,062 in Landers'
SeatGeek file (arXiv 2507.23767, CC BY-NC 4.0) to face prices from Wikipedia tour tables (gross ÷ tickets, no fees).
Resale = SeatGeek listing prices **averaged over each show's last 14 days**. One number per show, so this says how
far resale ends from face, not **when** in the sales window prices move. Listings are asking prices, and whether
SeatGeek's figures include fees isn't stated. Treat ratios as approximate.

| Measure (resale ÷ average face) | Median |
|---|---|
| Median listing | 2.36 (middle half 1.81–3.17) |
| Cheapest listing | 0.70 (middle half 0.45–1.01) |

- The median listing was above face on 98% of shows.
- The cheapest listing was **below** the average face price on 74% of shows. In the last two
  weeks, a get-in seat usually cost less than the average ticket sold at face (the average includes premium seats).
- Sold-out shows (≥99% sold): median ratio 2.41 (n=200) vs
  2.18 (n=58).
- Friday/Saturday: 2.58 (n=100) vs other days 2.26
  (n=158).

By act (≥4 matched shows; medians):

| Act | Shows | Face avg | Resale low | Resale median | Low ÷ face | Median ÷ face |
|---|---|---|---|---|---|---|
| Olivia Rodrigo | 6.0 | $167 | $346 | $810 | 2.11 | 4.88 |
| Luis Miguel | 20.0 | $193 | $166 | $680 | 0.88 | 3.53 |
| Beyonce | 22.0 | $234 | $227 | $836 | 0.92 | 3.45 |
| Metallica | 11.0 | $108 | $113 | $350 | 0.97 | 3.17 |
| Pink | 17.0 | $174 | $126 | $527 | 0.78 | 3.08 |
| Depeche Mode | 23.0 | $163 | $96 | $404 | 0.57 | 2.50 |
| Shania Twain | 25.0 | $114 | $85 | $266 | 0.69 | 2.43 |
| Rod Wave | 17.0 | $123 | $155 | $296 | 1.26 | 2.40 |
| Ed Sheeran | 16.0 | $100 | $78 | $211 | 0.83 | 2.28 |
| RBD | 20.0 | $266 | $217 | $601 | 0.81 | 2.16 |
| Doja Cat | 22.0 | $135 | $85 | $285 | 0.63 | 2.11 |
| Madonna | 13.0 | $207 | $103 | $409 | 0.49 | 1.97 |
| Sam Smith | 10.0 | $84 | $30 | $138 | 0.36 | 1.59 |
| Travis Scott | 31.0 | $136 | $52 | $189 | 0.39 | 1.55 |

Limits: 17 big acts only, one season, so this isn't a market-wide estimate and has no time path. The daily
series behind it is in the request to Landers (price-timeline `docs/DATA_REQUESTS.md` 4d).
