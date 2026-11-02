# Immediate public website publication

The old publication action committed the phone database row and then depended on a separate GitHub SSH identity/outbox push. Without that identity, the UI correctly reported a phone-only publication, but it did not meet the intended workflow. New manual articles also offered only Save draft.

The CMS now offers Save draft and Publish now · main news. Publish now checks both creation and publishing permissions and invokes the same direct approval transaction. A client request UUID and transactional reservation make retries after a lost response idempotent. Manual article URL hashes include their UUID explicitly: different original articles may cite the same evidence URL without hitting a uniqueness error.

The public website now reads approved-only phone publications through the existing signed HTTPS bridge. Separate service paths require the existing HMAC secret, fresh nonces and signed responses; they cannot be invoked through the public admin proxy. Positive export fields exclude drafts, rejected stories, credentials, moderation/evidence notes and internal identifiers. The public ID namespace is safe for JavaScript and avoids collisions with phone primary keys. Restored archive copies retain their canonical identity. Existing withheld sources remain withheld.

Every approval sets the current editorial lead without falsifying the original source publication date. The public API and homepage honor that placement. A lightweight version check and same-origin BroadcastChannel refresh open reader tabs after publication; stale shared HTML/API caches cannot mask a live publication. The gateway performs an actual anonymous public article API read and checks the precise revision before saving a signed website-visibility receipt and returning synced. A failed check remains verifying and can be retried without publishing another database row. Direct phone-admin status checks can perform the same visibility measurement.

GitHub remains an optional archive/fallback path. Its missing or failed SSH key no longer prevents immediate public delivery. Outbox/archive state is separate from a website visibility receipt. Public IDs and feature metadata survive optional Git backup; distinct manual articles using the same evidence URL remain distinct. Live serving still requires the phone and its existing HTTPS tunnel to be online. The existing backup-preserving Termux updater activates the new phone service; no new credentials or database provider are needed.

Validation:

- 427 Python tests with real PostgreSQL 18, including direct creation/publication, idempotent retry, signed public reads, receipts and role enforcement.
- 61 JavaScript tests; Python compile and public JavaScript syntax checks.
- 23 reader, 22 admin and 10 editorial browser regression checks.
- Four additional acceptance flows through two separate localhost processes and real HTTPS: browser login through the gateway; Publish now appearing immediately in an already-open homepage; Save draft then one-click Verify making it the main story; refreshed website receipts and private-field exclusion. These fixtures have no GitHub SSH key and never mutate production.
- A real local bare-Git integration verifies that two phone articles sharing one evidence URL retain separate complete copies in the feed/archive.

Deploy the web gateway/interface, then run the immutable phone updater and sign in again. Production news was not created or approved as a test.
