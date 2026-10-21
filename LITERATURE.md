# LITERATURE.md: concert and event ticket pricing

Compiled 2026-10-18. **Verification markers:**
- **[V-text]**: I read the paper's text (the PDF or text is cached in `data/raw/_scout/papers/`).
- **[V-abstract]**: verified from the abstract or a bibliographic record (IDEAS/RePEc, NBER, or the publisher).
- **[V-secondary]**: findings verified only through secondary coverage (press, university news, citing papers).
- **[UNVERIFIED]**: from memory or a single uncorroborated source. Check before relying on it.

Hypotheses are tagged **(LEVEL)** or **(PATH)** and numbered globally (H1, H2, …) so the analysis plan can cite them.

---

## A. Resale markets and price paths (PATH)

### 1. Sweeting (2012), dynamic pricing in secondary markets for MLB tickets [V-text]
- **Citation:** Sweeting, A. (2012). "Dynamic Pricing Behavior in Perishable Goods Markets: Evidence from Secondary Markets for Major League Baseball Tickets." *Journal of Political Economy* 120(6): 1133–1172. doi:10.1086/669254. Author PDF: https://www.econ.umd.edu/sites/www.econ.umd.edu/files/pubs/SWEETING_PDECLINE_0112.pdf
- **Data:** 2007 MLB regular season. More than 178,000 fixed-price eBay listings (with transactions) and several million StubHub listings, collected Jan 6 – Sep 30, 2007 by automated script.
- **Findings:** prices fall "significantly as a game approaches, especially in the final month". Simple dynamic-pricing models explain why sellers cut prices "by 40% or more". Individual sellers cut by "around 90% of face value in the month before the game". Dynamic pricing raises the average seller's expected payoff by about 16%. Most sellers hold a single set of tickets, which drives the declines because their opportunity cost falls with time.
- **Hypotheses:**
  - **H1 (PATH):** median resale prices decline over the final 30 days, with the steepest decline in the final week.
  - **H2 (PATH):** the decline is larger for events with more listings relative to expected demand (lower sell-through or weaker demand).
  - **H3 (PATH):** the price paths of individual listings decline faster than the market minimum, because sellers reprice toward the floor.

### 2. Leslie & Sorensen (2014), resale and rent-seeking [V-abstract + V-text of the 2009 NBER WP]
- **Citation:** Leslie, P. & Sorensen, A. (2014). "Resale and Rent-Seeking: An Application to Ticket Markets." *Review of Economic Studies* 81(1): 266–300. doi:10.1093/restud/rdt033. Working paper: NBER w15476 (2009), "The Welfare Effects of Ticket Resale".
- **Data:** 56 major rock concerts in summer 2004 (12 artists). Ticketmaster primary data (seat-level) matched to 68,828 resold tickets from eBay and StubHub.
- **Findings (WP text):**
  - Resale prices average **41% above face value**, but losses are common. Brokers (non-brokers) lose money on **21% (31%)** of tickets sold.
  - Brokers account for 46% of resale transactions.
  - Only **5% of tickets are resold** on average; the most active event had **17%** resold, with resale revenue equal to 37% of primary revenue.
  - High-quality (front) seats are more likely to be resold. "Unpriced seat quality may be the most important driver of resale activity."
  - **50% of resales occur within 26 days of the event, and 25% within 7 days.**
  - **Unlike MLB, concert resale prices "tend to increase slightly in the two-week period just" before the event, after a gradual decline.**
  - 70% of primary sales happen in the first week of the on-sale, and over 75% of sample concerts sold out.
  - Welfare (abstract): resale raises allocative efficiency by about 5%, with about a third offset by rent-seeking and transaction costs.
- **Hypotheses:**
  - **H4 (PATH):** concert resale paths are U-shaped or flat-then-rising in the last 14 days for sold-out, high-demand shows, unlike the monotone decline in sports.
  - **H5 (PATH):** the late-path shape depends on whether the primary market sold out. Sold-out shows rise late; shows with unsold primary inventory decline.
  - **H6 (LEVEL/PATH):** the resale markup is concentrated in the best seats, because face prices are too flat across seat quality (underpricing of "unpriced quality").
  - **H7 (PATH):** resale volume is back-loaded. The median transaction is about 3–4 weeks out, so price observations far from the event are sparse and noisy.

### 3. Bhave & Budish (2023), primary-market auctions [V-text of NBER w23770 abstract and intro]
- **Citation:** Bhave, A. & Budish, E. (2023). "Primary-Market Auctions for Event Tickets: Eliminating the Rents of 'Bob the Broker'?" *AEJ: Microeconomics* 15(1): 142–170. NBER w23770 (2017). Replication: openICPSR 161484.
- **Data:** Ticketmaster primary-market auction data (2007; confidential, anonymized in the replication package) matched to eBay resale values.
- **Findings:** auctions "eliminated the arbitrage profits associated with underpriced tickets" on average. Price discovery "improved dramatically" and artist revenues "roughly doubled" relative to the fixed-price counterfactual. The auctions still failed to take off.
- **Hypotheses:**
  - **H8 (LEVEL):** fixed face prices are systematically below market-clearing for high-demand shows, so the resale premium is a measure of underpricing.
  - **H9 (PATH):** events with dynamic or auction-style primary pricing (e.g. "platinum" or tiered releases) show smaller resale premiums and flatter resale paths.

### 4. Courty (2003), "Some Economics of Ticket Resale" [V-abstract]
- **Citation:** Courty, P. (2003). *Journal of Economic Perspectives* 17(2): 85–97. doi:10.1257/089533003765888449.
- **Argument:** borrowing from airline pricing, promoters can't capture resale profits because demand from late-arriving, high-value buyers can't be separated at the time of the primary sale. Brokers do the intertemporal price discrimination.
- **Hypotheses:**
  - **H10 (PATH):** the late-path price level rises with the share of late-deciding, high-value demand. Proxy it by tourist-heavy cities, weekend shows, and big metros.

### 5. Shapiro & Drayer (2014), and later StubHub MLB timing studies [V-abstract for the citation; findings V-secondary]
- **Citation:** Shapiro, S. L. & Drayer, J. (2014). "An examination of dynamic ticket pricing and secondary market price determinants in Major League Baseball." *Sport Management Review* 17(2): 145–159. Related: a 2023 study (Lee, Morse, Hyun, Shapiro & Drayer?) in *Sport, Business and Management*, doi:10.1108/SBM-05-2022-0042. The authorship of the later paper is [UNVERIFIED].
- **Data:** 2014: Giants (AT&T Park) dynamic prices vs. StubHub, 12 games, 1,316 prices. 2023: StubHub MLB, 4 observations per game from T-3 days to game day, 19,155 observations.
- **Findings (secondary):** days-to-event negatively affects price, with a sharp drop on game day and no significant effect at T-2. Star players, league, weather forecast changes, and starting pitcher quality matter.
- **Hypotheses:**
  - **H11 (PATH):** show-day prices drop discretely relative to T-1, beyond the trend.
  - **H12 (PATH):** forecast bad weather (rain, cold) lowers late resale prices for outdoor venues but not indoor ones.

### 6. Tompkins (2019), review of primary and secondary concert pricing [V-text]
- **Citation:** Tompkins, T. (2019). "An analysis of ticket pricing in the primary and secondary concert marketplace." *International Journal of Music Business Research* 8(1): 39–56(?). Page range [UNVERIFIED]. PDF cached.
- **Content:** a literature review. It cites Pollstar-based averages: $40.74 (2000) → $78.93 (2016–17); $42.00 → $78.93 for 2005–2017 (+88%). It cites Krueger's survey of 1,068 concerts (about 10% of tickets bought on the secondary market; average face value $81, average markup 36%, average secondary price $122). It cites Chan, Mathew & Ruggie (2009), who say sellers "start with a high price, peak about nine to ten days prior to the concert and drop the price below face value", with some of the lowest prices "within one hour". The Chan et al. primary source is [UNVERIFIED].
- **Hypotheses:**
  - **H13 (PATH):** resale prices peak about 7–14 days before the show and then fall. This competes with H4, and the data should discriminate between them.
  - **H14 (PATH):** the price minimum often occurs in the final hours. Test the T-1h vs. T-24h difference when hourly data exist.

### 7. Bennett, Seamans & Zhu (2015), secondary markets and concert pricing [V-secondary]
- **Citation:** Bennett, V. M., Seamans, R. & Zhu, F. (2015). "Cannibalization and option value effects of secondary markets: Evidence from the US concert industry." *Strategic Management Journal* 36(11): 1599–1614. The page range is [UNVERIFIED].
- **Data:** Pollstar, more than 73,000 US concerts in 2003–2008 (headliners with at least 25 shows). Craigslist's city-by-city entry is the shock.
- **Findings:** after Craigslist entered a city, primary prices **rose for shows likely to sell out and fell for shows that weren't**, with similar patterns for StubHub entry. Promoters responded by booking artists into venues they were more likely to sell out.
- **Hypotheses:**
  - **H15 (LEVEL):** a thicker resale market raises primary prices for high-demand acts and lowers them for low-demand acts, an interaction of demand × resale access.
  - **H16 (LEVEL):** expected sell-out probability (capacity relative to artist popularity) is a key driver of price level.

### 8. Cui, Duenyas & Sahin (2014), "Should event organizers prevent resale of tickets?" [V-secondary]
- **Citation:** *Management Science* 60(9): 2160–2179. Volume and pages are [UNVERIFIED].
- **Argument:** a theory paper. Resale can benefit organizers. It proposes ticket options.
- **Hypothesis:**
  - **H17 (PATH):** when aggregate demand uncertainty is resolved late (e.g. by new album news), resale price variance increases near the event.

### 9. Waisman (working paper), selling mechanisms for perishable goods in an online resale market [UNVERIFIED beyond the title]
- **Status:** title confirmed from a Kellogg seminar listing (2017-11-02, Caio Waisman, Stanford). I could not verify the venue or findings.
- **Hypothesis:**
  - **H18 (PATH):** fixed-price listings dominate auctions late in the horizon. Test only if listing-format data exist.

### 10. GAO (2018), Event Ticket Sales: Market Characteristics and Consumer Protection Issues (GAO-18-347) [V-secondary: highlights]
- **Link:** https://www.gao.gov/products/GAO-18-347
- **Findings:** tickets are "often resold on the secondary market at prices above face value". In a nongeneralizable sample, total fees averaged **27% (primary) and 31% (secondary)** of the ticket price. Claims elsewhere that GAO reported a 41% or 124% average markup are [UNVERIFIED].
- **Hypothesis:**
  - **H19 (LEVEL):** fee share varies by venue and ticketer, so gross-based average prices are not comparable to face prices without a fee adjustment.

### 11. UK CMA (2025), Ticketmaster and Oasis: tiered vs. dynamic pricing [V-secondary]
- **Sources:** Music Week, Music Business Worldwide, and Pollstar (2025-09-25/29) coverage of the CMA outcome.
- **Findings:** the CMA found no evidence of real-time algorithmic ("dynamic") pricing. Standing tickets were released in **tiers at two prices** without telling fans in the queue. "Platinum" seats sold for about 2.5× equivalent standard tickets. Ticketmaster committed to giving 24 hours' notice of tiered pricing.
- **Hypotheses:**
  - **H20 (LEVEL/PATH):** primary "dynamic pricing" in practice is mostly pre-set tier releases. Expect step changes, not continuous drift, in Ticketmaster `priceRanges` snapshots.

### 12. Industry claims on timing (StubHub newsroom 2026; FinanceBuzz; NITO 2025) [V-secondary; promotional or advocacy]
- StubHub (2026-04-20): prices are "often highest right after on-sale" and "can drop further closer to the event". Some concert tickets fall below face value. "1 in 3" buyers purchase within 48 hours. No data or methods are given, and the source is promotional.
- FinanceBuzz: buyers on concert day paid 33% less than average, and 27% less the day before. The data basis is unclear.
- NITO (2025): 20 Maryland concerts (2021–2024) generated $6.2M in reseller profit above face value. StubHub had more than 24% of resales. NITO is an advocacy group.
- **Hypothesis:**
  - **H21 (PATH):** the typical concert's resale minimum is in the final 48 hours. Test it against H4 and H13 and expect heterogeneity by demand.

---

## B. Price levels and determinants (LEVEL)

### 13. Krueger (2005), "The Economics of Real Superstars" [V-abstract]
- **Citation:** Krueger, A. B. (2005). *Journal of Labor Economics* 23(1): 1–30. doi:10.1086/425431.
- **Data:** Pollstar box office data.
- **Findings:** average concert prices rose **82% from 1996 to 2003, vs. 17% for the CPI**. Krueger evaluates five explanations (less secondary-market activity, superstar effects, Baumol cost disease, promoter concentration, weaker concert–album complementarity) and tentatively favors the **erosion of the concert–album link** (file sharing) as the main driver.
- **Hypotheses:**
  - **H22 (LEVEL):** real prices trend up faster than the CPI. Include year fixed effects and deflate with CPI-U.
  - **H23 (LEVEL):** prices are higher for artists whose recorded-music income is lower relative to their live demand. Proxy live demand with pageviews and recorded-music strength with chart and streaming measures where available.

### 14. Connolly & Krueger (2006), "Rockonomics: The Economics of Popular Music" [V-abstract for the WP; Handbook details UNVERIFIED]
- **Citation:** Connolly, M. & Krueger, A. B. (2006). In Ginsburgh & Throsby (eds.), *Handbook of the Economics of Art and Culture*, Vol. 1, ch. 20, pp. 667–719 [UNVERIFIED]. NBER w11282 (2005).
- **Findings (secondary):** concert revenue is concentrated. The top 1% of artists' share of concert revenue rose from **26% (1982) to 56% (2003)**, and the top 5% from 62% to 84%. Ticket prices from Pollstar rose about 61% over five years vs. 13% CPI (2002 lecture coverage).
- **Hypotheses:**
  - **H24 (LEVEL):** the price distribution across artists is heavily right-skewed, and log price rises convexly in popularity (superstar effect; Rosen 1981).

### 15. Krueger (2019), *Rockonomics* (book) [V-secondary]
- **Citation:** Krueger, A. B. (2019). *Rockonomics: A Backstage Tour of What the Music Industry Can Teach Us About Economics and Life*. Currency/Crown.
- **Findings (secondary, from a talk):** concert ticket prices are up about 400% since the early 1980s vs. about 150% for overall inflation. The book's exact figures are [UNVERIFIED].
- **Hypotheses:** this reinforces H22 and H24.

### 16. Courty & Pagliero (2012), price discrimination and revenue in concerts [V-secondary: abstract via search]
- **Citation:** Courty, P. & Pagliero, M. (2012). "The Impact of Price Discrimination on Revenue: Evidence from the Concert Industry." *Review of Economics and Statistics* 94(1): 359–369.
- **Data:** Pollstar concerts with varying numbers of seat categories.
- **Findings:** offering multiple seating categories raises revenue by about **5%** vs. a single price. Returns are higher with **more heterogeneous demand, in smaller venues, and in more competitive markets**. Going from 3 to 4 categories yields about half the gain of going from 1 to 2. A companion paper (CEPR DP7143) finds price discrimination is more likely for **older artists and larger venues**.
- **Hypotheses:**
  - **H25 (LEVEL):** the price range (max/min) widens with venue size and artist career age.
  - **H26 (LEVEL):** average realized price (gross ÷ sold) rises with the number of price tiers, holding the artist constant. Test with the Ticketmaster `priceRanges` count.

### 17. Courty & Pagliero (2014), "The pricing of art and the art of pricing: pricing styles in the concert industry" [UNVERIFIED]
- **Citation:** *Handbook of the Economics of Art and Culture*, Vol. 2 [UNVERIFIED chapter and pages].
- **Expected relevance:** documents pricing "styles" (uniform vs. tiered, round-number prices) across artists.
- **Hypothesis:**
  - **H27 (LEVEL):** artists have persistent pricing styles, which is why prices relative to the artist's own median are the right second target. Artist fixed effects should explain a large share of variance.

### 18. Mortimer, Nosko & Sorensen (2012), digital distribution and live performance [V-secondary]
- **Citation:** *Information Economics and Policy* 24(1): 3–14. NBER w16507.
- **Data:** weekly CD sales and individual concert data for nearly 2,000 artists over ten years.
- **Findings:** file sharing reduced album sales but **increased concert demand, mainly for smaller artists**. Large artists saw negligible effects.
- **Hypothesis:**
  - **H28 (LEVEL):** online attention (pageviews) predicts price more strongly for mid-tier artists than for superstars, an interaction of attention × popularity tier.

### 19. Rosen (1981), "The Economics of Superstars" [UNVERIFIED in-session; canonical]
- **Citation:** Rosen, S. (1981). *American Economic Review* 71(5): 845–858.
- **Theory:** small talent differences produce large earnings differences when technology allows one performer to serve a large market.
- **Hypothesis:** the theoretical basis for H24.

### 20. Black, Fox & Kochanowski (2007), "Concert tour success in North America: An examination of the top 100 tours from 1997 to 2005" [UNVERIFIED]
- **Citation:** *Popular Music and Society* 30(2): 149–172 [UNVERIFIED].
- **Expected relevance:** tour-level determinants of gross (artist age, genre, number of shows, album releases).
- **Hypothesis:**
  - **H29 (LEVEL):** a new album released within 12 months before the tour raises the average price, holding popularity constant.

### 21. Pollstar year-end business analyses (2024–2025) [V-secondary via search; Pollstar headline]
- **Source:** Pollstar, "Year-End Business Analysis: A Return to Earth…" (2025-12-12). https://news.pollstar.com/2025/12/12/
- **Findings:** the Top 100 tours' average ticket price was **$135.92 (2024)** and **$132.62 (2025, −2.4%)**. The Top 100 gross was about $8.9B in 2025 (−6.1% vs. 2024). Average tickets sold per show hit a record 19,104.
- **Hypotheses:**
  - **H30 (LEVEL):** after the post-pandemic peak (2023–2024), real average prices for top tours flatten or decline in 2025–2026. Include year effects and don't extrapolate the trend.
  - **H31 (LEVEL):** stadium shows command higher average prices than arenas, holding the artist constant. Venue type is a key feature. A secondary claim that stadium prices averaged $216.13 is [UNVERIFIED].

### 22. Elfenbein (2005/2006), anti-scalping laws and NFL tickets online [V-secondary: cited in the Leslie & Sorensen WP]
- **Citation:** Elfenbein, D. W. (cited by L&S as 2005). "Do anti-ticket scalping laws make a difference online? Evidence from Internet sales of NFL tickets." Working paper [venue UNVERIFIED].
- **Finding (as summarized by L&S):** "stricter regulations result in fewer tickets being resold, higher ...". The rest of the sentence is on the next page and was not captured, so the direction of the price effect is [UNVERIFIED].
- **Hypothesis:**
  - **H32 (LEVEL/PATH):** state resale caps or restrictions (e.g. NY, CT, and others with markup limits) change resale paths. Add state-law indicators.

### 23. Rosen & Rosenfield (1997), "Ticket Pricing"; Courty (2003b), "Ticket pricing under demand uncertainty" [UNVERIFIED]
- **Citations:** *Journal of Law and Economics* 40(2): 351–376 [UNVERIFIED]; *Journal of Law and Economics* 46(2): 627–652 [UNVERIFIED].
- **Theory:** why sellers underprice and ration (quality-tier pricing and demand uncertainty).
- **Hypothesis:**
  - **H33 (LEVEL):** cheap seats are underpriced relative to premium seats more often than the reverse, so resale markups are larger at the top of the house (links to H6).

### 24. Courty (2019), "Ticket resale, bots, and the fair price ticketing curse" [UNVERIFIED]
- **Citation:** *Journal of Cultural Economics* 43: 345–363 [UNVERIFIED].
- **Expected relevance:** why artists keep "fair" (below-market) prices, and the role of bots.
- **Hypothesis:**
  - **H34 (LEVEL):** artists with strong "fan-friendly" positioning (e.g. Verified Fan or face-value exchange only) have lower primary prices relative to popularity and larger resale gaps.

### 25. Zou, "Integration of Primary and Resale Platforms" (working paper) [UNVERIFIED beyond the title]
- **Link:** https://www.depts.ttu.edu/rawlsbusiness/research/Integration-of-PrimaryandResalePlatforms.pdf (not read).
- **Hypothesis:**
  - **H35 (PATH):** events sold on platforms with integrated resale (e.g. Ticketmaster resale on the same event page) have smaller resale premiums. Test only if the platform can be identified.

---

## C. PATH, added for task 8: what predicts the shape of a price path

Added 2026-10-21 by collector-prices. Citations come from bibliographic records or publisher and author pages found by web search on that date; I did not read the full texts unless marked. Numbers appear only where the abstract states them.

### 26. Gallego & van Ryzin (1994), optimal dynamic pricing over a finite horizon [V-abstract]
- **Citation:** Gallego, G. & van Ryzin, G. (1994). "Optimal Dynamic Pricing of Inventories with Stochastic Demand over Finite Horizons." *Management Science* 40(8): 999–1020. doi:10.1287/mnsc.40.8.999. Author PDF: https://business.columbia.edu/sites/default/files-efs/pubfiles/3943/vanryzin_optimal_dynamic_pricing.pdf
- **Content:** a seller with fixed stock and a deadline facing price-sensitive stochastic demand. The paper proves monotonicity of the optimal price in stock level and time remaining, and shows fixed-price policies are asymptotically optimal as volume grows.
- **For PATH:** the theoretical anchor for "the path depends on remaining inventory relative to remaining time". A seller long on inventory late in the horizon cuts prices; scarce inventory holds prices up. This supports H2/H5 (sell-through as the moderator) and the face-value side of H20.

### 27. Board & Skrzypacz (2016), revenue management with forward-looking buyers [V-abstract]
- **Citation:** Board, S. & Skrzypacz, A. (2016). "Revenue Management with Forward-Looking Buyers." *Journal of Political Economy* 124(4): 1046–1087. doi:10.1086/686713.
- **Content:** units sold before a deadline to buyers who arrive over time and can time their purchases. The optimal allocation uses cutoffs that depend only on inventory and time remaining, implementable with posted prices. The 2011 working-paper version states that the cutoffs fall over time and with inventory [V-secondary for that detail].
- **For PATH:** declining paths are optimal even with strategic buyers, so a late rise needs something else: scarcity (sell-outs, H4/H5) or late high-value arrivals (H10).

### 28. Williams (2022), welfare effects of dynamic pricing in airlines [V-abstract]
- **Citation:** Williams, K. R. (2022). "The Welfare Effects of Dynamic Pricing: Evidence from Airline Markets." *Econometrica* 90(2): 831–858. doi:10.3982/ECTA16180.
- **Content:** separates fare changes caused by demand shocks from those caused by a shifting mix of buyers (willingness to pay rises as departure nears). Dynamic pricing benefits early leisure buyers and charges late business buyers more.
- **For PATH:** the closest empirical analog for a *rising* late path. If late concert demand is less price-elastic (Courty 2003, H10), late prices can rise. The path then depends on the timing mix of buyers as well as inventory.

### 29. Xu, Fader & Veeraraghavan (2019), dynamic pricing for MLB single-game tickets [V-abstract]
- **Citation:** Xu, J. J., Fader, P. S. & Veeraraghavan, S. (2019). "Designing and Evaluating Dynamic Pricing Policies for Major League Baseball Tickets." *Manufacturing & Service Operations Management* 21(1): 121–138. doi:10.1287/msom.2018.0760.
- **Content:** a demand model of quantity and seat-section choice for one franchise's primary tickets. The abstract reports that daily re-optimization would raise revenue by about 17.2%, close to a clairvoyant policy. Customer arrival timing is related to the seat chosen.
- **For PATH:** primary sellers *can* gain from daily repricing. Whether Ticketmaster concert face values actually move daily is an empirical question the forward panel answers (H20). Seat section and arrival timing interact, so paths should be studied by tier where tiers exist (H36).

### 30. Diehl, Maxcy & Drayer (2015), secondary-market price elasticity in the NFL [V-abstract]
- **Citation:** Diehl, M. A., Maxcy, J. G. & Drayer, J. (2015). "Price Elasticity of Demand in the Secondary Market: Evidence from the National Football League." *Journal of Sports Economics* 16(6): 557–575.
- **Content:** using secondary-market transactions with IV, demand is elastic (unlike most primary-market estimates), and elasticity differs by seat quality.
- **For PATH:** resale price paths should differ by seat tier (H36), and secondary sellers face elastic demand, which fits Sweeting's declining paths for most events.

### 31. Waisman (working paper, 2017 seminar version), auctions vs. posted prices for NFL tickets on eBay [V-abstract via seminar listings; publication venue UNVERIFIED]
- Updates item 9. The UCL (2017-10-24) and Kellogg (2017-11-02) seminar abstracts describe a structural model of forward-looking eBay sellers choosing auctions or posted prices for NFL tickets. In the counterfactuals, removing auctions cuts sellers' expected payoffs by 20% to 90%.
- **For PATH:** the selling mechanism and seller dynamics are part of the path; relevant to H18 only if listing-format data exist.

### 32. Kemper & Breuer (2016), dynamic pricing for Bayern Munich [V-abstract; findings UNVERIFIED]
- **Citation:** Kemper, C. & Breuer, C. (2016). "How Efficient is Dynamic Pricing for Sport Events? Designing a Dynamic Pricing Model for Bayern Munich." *International Journal of Sport Finance* 11(1): 4–15.
- **Content:** a Bernoulli-type dynamic pricing model with demand estimated from ebay.de ticket auctions (2013/14 season), evaluated by Monte Carlo simulation. I did not verify its efficiency conclusion.

### Synthesis: predictors of path shape named in the literature

| predictor | expected effect on the late path | sources | testable here? |
|---|---|---|---|
| Remaining inventory relative to time (primary sell-out, listings vs. demand) | long inventory → decline; scarcity → flat or rising | Sweeting 2012; Leslie & Sorensen 2014; Gallego & van Ryzin 1994; Board & Skrzypacz 2016 | resale data needed (H2, H5) |
| Timing mix of buyers (late, high-value demand) | more late high-value demand → late rise | Courty 2003; Williams 2022 | resale data needed (H10) |
| Seller type (brokers vs. individuals holding one set) | individual sellers cut harder as opportunity cost falls | Sweeting 2012; Leslie & Sorensen 2014 | resale listing data needed (H3) |
| Seat quality tier | elasticity and markups differ by tier | Diehl, Maxcy & Drayer 2015; Leslie & Sorensen 2014; Xu et al. 2019 | partly: primary tiers via price_min/price_max (H36 resale side excluded) |
| Primary pricing regime (tier releases, platinum, auctions) | smaller resale premiums and flatter resale paths; primary steps at release dates | Bhave & Budish 2023; CMA 2025; Xu et al. 2019 | primary side yes (H20, H9p, H37) |
| Late resolution of demand uncertainty | rising late variance | Cui, Duenyas & Sahin 2014 | resale data needed (H17) |
| Event-specific shocks (weather, line-up news) | discrete level shifts | Shapiro & Drayer 2014 | resale data needed (H12) |

- **Hypotheses:**
  - **H36 (PATH):** late resale paths differ by seat tier. Premium tiers decline less (or rise) for high-demand shows, and cheap tiers decline more. Needs resale data with section or tier.
  - **H37 (PATH, primary):** Ticketmaster primary face-value changes concentrate around scheduled sale-phase dates (public on-sale start and presale windows) rather than spreading evenly over days to show. Testable on the forward panel because the sale dates are recorded as-of in each snapshot.

## Consolidated hypothesis list (for the analysis plan)

**LEVEL:** H6, H8, H15, H16, H19, H22, H23, H24, H25, H26, H27, H28, H29, H30, H31, H32, H33, H34.
**PATH:** H1, H2, H3, H4, H5, H7, H9, H10, H11, H12, H13, H14, H17, H18, H20, H21, H35, H36, H37.

**Directly competing PATH predictions to test head-to-head:** monotone decline to the end (H1, H21; Sweeting/MLB, StubHub newsroom) vs. a late rise for sold-out concerts (H4/H5; Leslie & Sorensen) vs. a peak at T-9 to T-10 days then a fall (H13; Chan et al. via Tompkins). The moderator to test is primary sell-out status and demand relative to capacity.

## Unverified items to check before citing in any write-up
Connolly & Krueger Handbook pages; the Krueger 2019 book figures; Courty & Pagliero 2014; Black, Fox & Kochanowski 2007; Rosen & Rosenfield 1997; Courty 2003b; Courty 2019; Waisman (publication venue; the seminar abstract is verified, item 31); Zou; the Kemper & Breuer efficiency conclusion; Chan, Mathew & Ruggie 2009; the Bennett et al. pages; the Cui et al. volume and pages; the authorship of the 2023 SBM paper; and the GAO markup figures.
