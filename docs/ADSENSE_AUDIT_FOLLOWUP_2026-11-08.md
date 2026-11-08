# PoliticsHub AdSense audit follow-up — 8 November 2026

This document distinguishes audited code improvements from AdSense account actions and unverified external metrics. A third-party report's **86% approval odds** and manually checked **44/100 readiness score** are not Google approval decisions.

## Implemented in this change
- Reopen a first-party site-preference choice from the homepage footer and ordinary static pages. First-party preference choices control optional local browser storage; they are **not** an advertising consent-management platform.
- Require explicit ad-suitability review before ads can appear on certain sensitive public-interest news, even when original-source and copy-review checks pass. Do not suppress legitimate factual news solely for its subject.
- Regression tests for consent reopening and selective ad gating.

## AdSense-account action (not performed by repository changes)
The AdSense account owner or their eligible adult account holder needs to:
1. Open **Privacy & messaging → European regulations**.
2. Select PoliticsHub and provide `https://www.politicshub.in/privacy.html`.
3. Choose the appropriate consent and refusal options and **Publish** the Google-certified message.
4. Verify the message in EEA/UK/Switzerland browsing conditions and confirm consent changes and revocation controls.
5. Review **Sites** status and Google’s actual reason for any rejection.

Official guidance: https://support.google.com/adsense/answer/10960768

## Evidence still needed
- Verify Google-certified TCF consent in relevant regions (cannot infer from cookie/banner HTML).
- Individually review articles for original value, source permissions, accurate claims, and image licensing. Automated fingerprints and word counts **do not prove originality**.
- Verify indexed URL totals in Search Console and crawl performance and live link status via real measurements; the third-party report explicitly labels several checks simulated.
- Avoid invented authors, citations, blanket removals of public-interest reporting, purchased backlinks and artificial 600-word padding.
- AdSense registration/payment eligibility requires an adult account holder where applicable.

The site uses a meta tag for AdSense ownership verification; this is a Google-supported alternative to running ad code on the homepage. Do not enable homepage Auto ads merely to satisfy an external scanner. Reference: https://support.google.com/adsense/answer/7584263
