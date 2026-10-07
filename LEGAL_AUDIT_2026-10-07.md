# PoliticsHub.in Legal / Compliance Audit

Audit date: 7 October 2026  
Scope: public website, newsletter, automated newsroom, Reel publisher, current direct dependencies and major external services.  
This is a product/compliance review, not legal advice.

## Executive result

The site now has baseline privacy/terms/cookie disclosures, explicit newsletter consent, a self-service unsubscribe path, data-rights request paths, safer media licensing rules, a third-party license notice, and advertising disabled pending compliant consent management.

The remaining issues that should be reviewed by a qualified lawyer are: copyright/fair-dealing limits for source-derived news summaries and headlines; jurisdiction/liability language in the Terms; privacy/child-data obligations as the Indian DPDP Act phases into force; Meta/Instagram developer obligations for the connected app; and any future paid product/refund terms.

## 20-point checklist

1. Privacy Policy — implemented at /privacy.html.
2. Terms & Conditions — implemented at /terms.html.
3. Cookie Policy — implemented at /cookies.html.
4. Cookie consent — optional local-storage preferences now require a user choice. Advertising is disabled. If Google ads are enabled for EEA/UK/Swiss traffic, use a Google-certified CMP integrated with IAB TCF where required.
5. Form consent — newsletter requires both explicit marketing/privacy consent and age confirmation.
6. Data collected — Privacy Policy itemizes newsletter email, consent choice, optional local preferences/cache, technical request logs and email enquiries.
7. Purpose — each item is paired with its purpose and typical retention.
8. Deletion — /data-rights.html provides a deletion request path and self-service newsletter removal.
9. Access/correction — /data-rights.html provides dedicated access and correction request links.
10. Third-party API terms — reviewed at a high level. NewsAPI disabled pending production-license confirmation; NewsData restricted to safer metadata fields; Openverse restricted to public-domain/CC0-style results; Meta, Cloudinary, Google, Vercel and GitHub obligations recorded in THIRD_PARTY_NOTICES.md.
11. AI-generated content/IP — disclosure added. AI rewriting can still create derivative-work, factual-error, defamation and source-rights questions; lawyer/editorial review remains advisable.
12. Open-source/source-available licenses — direct dependencies documented. Remotion is source-available, not OSI open source, and has organization-size/use-case conditions.
13. Copyrighted assets — unknown-license publisher images are blocked from the public site; Reel automation no longer treats a source image as reusable merely because it was fetched.
14. Attribution — Reel captions include recorded attribution for legacy attribution-bearing licensed images. New automated image selection is limited to low-risk public-domain/CC0-style results.
15. UI assets — logo/favicon are treated as PoliticsHub assets. The unused public/politicshub-header.webp file still needs provenance documentation before use.
16. Age restrictions — public reading remains open; newsletter personal-data collection is limited to users 18+.
17. High-risk advice disclaimer — expanded to cover legal, medical, financial, investment, tax, safety and emergency decisions.
18. Refund/cancellation policy — no paid consumer product currently exists, so Terms say no refund policy applies yet. Publish full pricing/renewal/refund terms before charging users.
19. Marketing claims — “Independent reporting. Clearly.” was changed to “Source-linked news. Clearly.” to match the actual product.
20. Final legal audit — this document records unresolved lawyer-review items below.

## Lawyer-review / manual-review flags

### High priority

- Source-derived text copyright: the deterministic fallback can select and republish source sentences. Attribution and linking do not automatically make copying lawful. Decide, with counsel, the permitted amount of quotation/fair dealing for India and other target markets, or require original paraphrasing for non-licensed publisher material.
- Defamation and election/public-figure risk: automated summaries can create legal exposure if inaccurate. Keep correction workflows, human review for sensitive claims, and source retention.
- India DPDP rollout: child-data and consent obligations are phased. The current newsletter 18+ rule is conservative, but counsel should confirm final operational requirements before the relevant provisions take effect.
- Meta/Instagram app terms: confirm the connected Meta app's permissions, Data Use Checkup/app-review status, token handling, privacy-policy URL and deletion path against current Meta Platform Terms/Developer Policies.
- Terms jurisdiction/liability: have Indian counsel tailor governing law, venue, limitation-of-liability, indemnity and dispute provisions to the actual operator/entity.

### Medium priority

- NewsData.io: confirm the subscribed plan and any account-specific terms. Continue using title/short description/source/date only; do not republish supplied images or full content.
- NewsAPI: if re-enabled, verify a production-authorized plan and the exact content rights allowed by the account.
- Openverse: even public-domain/CC0 metadata can be wrong; consider human verification for high-profile/commercial campaigns.
- Remotion: re-check license eligibility if the organization exceeds three people or the video product becomes a customer-facing rendering service.
- Google Fonts: consider self-hosting fonts to reduce third-party connection-data disclosure.
- Unused asset provenance: document ownership/source of public/politicshub-header.webp or delete it.

## Operational rules going forward

Before adding a new API, SDK, tracking tag, image source, paid plan, user account feature, ad network or form, update the privacy notice, cookie controls, third-party notices and this audit. Do not enable a new data-collection or advertising integration first and “fix the policy later”.
