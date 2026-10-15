# Restore the existing production providers

## Active database after 15 October cutover

The account owner created **politics 3**, project `shy-mountain-59394437`,
production branch `br-misty-block-b5rt7ujx`. New collection and website reads
use that project through `DATABASE_URL` in GitHub Actions and Vercel Production.
The collector validates the new endpoint:
`ep-bold-recipe-b5iqrmwg-pooler.c-7.us-east-2.aws.neon.tech`
(or its direct counterpart without `-pooler`).

Keep historical data in `soft-bread-75007292` and `ancient-king-18045040`.
Do not run the snapshot-restore script or copy historical tables into politics 3.
Changing only the Vercel variable is insufficient: the collector and publishing
workers also require the matching Actions secret. Changes to Vercel environment
variables require a new production deployment before they take effect.

The fresh database's article sequence starts at `1000000000000000` to keep
new article IDs separate from historical database and emergency snapshot IDs.

## Previous database quota diagnosis

The existing Neon project is `soft-bread-75007292`, endpoint
`ep-steep-rice-b5dvvhhb`. On 15 October 2026 the project reported
5,526,539,401 bytes of transfer and the Free plan. `SELECT 1` is rejected
with HTTP 402 (quota exceeded). This is a monthly transfer allowance, not
storage that can be freed by deleting articles.

1. Open [Neon Billing](https://console.neon.tech/app/billing#change_plan)
   for organization `org-falling-river-32824966` and review a Launch upgrade.
   This starts usage-based paid billing. Launch includes 500 GB of public
   transfer per project per month; compute and storage are charged separately.
2. After upgrading, restart the existing compute in the project console so it
   picks up the new limits. Keep the existing database and connection strings.
3. If staying on Free, the project reports its next quota reset as
   **1 November 2026, 00:00 UTC**. The public snapshot feed keeps news available
   during the outage.

Official references: [network-transfer limits](https://neon.com/docs/introduction/network-transfer),
[pricing](https://neon.com/docs/introduction/plans), and
[changing plans](https://neon.com/docs/introduction/manage-billing#change-your-plan).

## Instagram

The worker currently receives Meta OAuth error 190: the session was invalidated.
A revoked token cannot be repaired by calling the long-lived-token refresh API.

1. Open the **existing** app in [Meta App Dashboard](https://developers.facebook.com/apps/).
   Reauthorize the PoliticsHub Instagram account with that app's existing login
   method, and obtain a new token with the publishing permissions it requires.
2. Update `META_ACCESS_TOKEN` in
   [this repository's Actions secrets](https://github.com/uunivpt/news-bot/settings/secrets/actions).
   Keep the token inside the secret store. Never paste it in an issue, log or chat.
3. Confirm `META_API_BASE_URL`, `META_API_VERSION`, and
   `META_INSTAGRAM_ACCOUNT_ID` match the chosen login method/account. Use the
   official Instagram Graph endpoint for Instagram Login and the official
   Facebook Graph endpoint for Facebook Login. Do not switch accounts to
   work around an authorization error.

## Verify recovery

Run [Provider Recovery Check (Read Only)](https://github.com/uunivpt/news-bot/actions/workflows/provider-health.yml).
It reads `SELECT 1` and Meta `/me`, reports safe statuses, and never publishes.
After the checks pass, the existing collector, news processing and Instagram
workflows can run normally. A successful `/me` alone does not prove the token
has media-publishing permission; the publishing workflow must also complete.

Public news search, breaking/trending lists, clustering and duplicate detection
use small projections. Dashboard counts/coverage use SQL aggregates. These
changes reduce future transfer; they cannot refund already-consumed quota.
