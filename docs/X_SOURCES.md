# X (Twitter) source integration

The collector uses X API v2 only. It does not scrape X, copy screenshots,
download tweet-attached photos, or treat a tweet as an independently verified fact.

* Configure explicitly selected official account handles in `config/sources.json`
  under the `x` group. RahulGandhi, narendramodi and elonmusk are configured.
* Set the GitHub Actions repository secret `X_API_BEARER_TOKEN` for approved
  X API access. X may charge for API access; no free access is assumed.
* In Newsroom, review every X story and open its original source link.
  Approve the **source authenticity and context** before any site publish.
* The published website can show a 4:5 typographic source quote card.
  The Instagram worker publishes the original 4:5 card as an image and adds
  the original post URL to the caption.
* The card is NOT an X screenshot and must not be represented as one.
  A licence for source photographs/screenshots, if ever used, requires separate review.
* If a configured account is renamed, its lookup must match the configured handle;
  the collector fails with a visible warning instead of assigning the wrong author.
* A post may contain an unverified allegation: attribution remains mandatory.
* GitHub scheduled runs are not guaranteed to start on time. Current collector
  cron is every 30 minutes, regardless of per-source check_every_minutes.
* `CJP` is deliberately not configured until its precise account is identified.
