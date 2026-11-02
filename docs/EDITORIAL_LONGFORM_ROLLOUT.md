# Long-form editorial review policy (draft rollout)

The `EDITORIAL_LONGFORM_ONLY` gate defaults to **true** in the proposed worker change.
Do **not** merge or deploy until an operator has verified the editorial review workflow:
otherwise nearly all automated RSS stories will be held and the public news feed
will stop receiving new items.

- Collected RSS headlines/excerpts are research leads, not independently authored reports.
- Automatic article scraping/extractive summarization does **not** create original reporting.
- Stories without 800 words of substantive text remain pending.
- Reports need a real human `reviewed` or `approved` status before publication.
- Multiple publishers repeating the same claim are not automatically independent verification.
- Keep source attribution and original links.
- Report length is only an internal preference, never an AdSense approval guarantee.
- No padding, generic filler, invented details or automatically fabricated citations.
- Existing published content is **not** silently rewritten or removed by this gate.
- An editor must check factual claims, rights/licensing, quotations, original added value,
  conflicts and corrections. The deterministic gate cannot prove any of these.
- Rollback: set `EDITORIAL_LONGFORM_ONLY=false` after explicit editorial approval;
  this re-enables the legacy short-summary fallback and should not be treated as
  AdSense-safe.

Before merging: run Python tests, exercise a representative pending queue with
realistic data in staging, verify admin review UX and approval persistence, measure
held/published counts, and confirm production database and deployment capacity.
