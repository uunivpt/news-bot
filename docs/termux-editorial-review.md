# PoliticsHub phone editorial review — Termux only

The PostgreSQL database remains **on the Android phone**. This tool never
connects to Neon, never makes the phone DB reachable from the internet, and
does not give publishing permissions to the hourly collection worker.

## 1. List substantial drafts (read-only)

```sh
cd "$HOME/politicshub-live-upload"
env -u DATABASE_URL -u DATABASE_3URL python scripts/mobile_editorial_approve.py --list
```

## 2. Inspect one story

```sh
env -u DATABASE_URL -u DATABASE_3URL python scripts/mobile_editorial_approve.py --id 455
```

Inspect original source links, dates, attribution, report text and originality.
Do **not** assume a generated draft has been fact-checked. Items shorter than
600 characters, already rejected, missing a public source, or older than five
days are blocked from this standard news path. Correct or retain these items
privately; never backdate or redate a stale report to evade the age policy.

## 3. Human approval of one verified story only

After comparing the claim against at least one **independent** official
record or reliable source (two distinct publisher domains for high-impact or
Telegram-sourced claims), run:

```sh
env -u DATABASE_URL -u DATABASE_3URL python scripts/mobile_editorial_approve.py --id 455 --approve
```

The tool shows the entire private draft, prompts for supporting URLs,
explanation of checked facts/context/originality, and exact
`APPROVE 455` confirmation. It then prompts for the **local PostgreSQL
admin password**, without saving it in a file or GitHub. It rechecks the
record under a database lock and atomically stores one approval and audit
entry. If the source record changed, it cancels.

After a successful approval, the tool invokes the existing approved-only
GitHub uploader. A GitHub workflow merges validated approved records into
the public website feed. If upload fails, the already configured 15-minute
sync scheduler can retry the export. **Approval never means guaranteed
instant website visibility**: upload, GitHub workflow, public feed policy
and Vercel availability must all succeed. Existing public stories stay
intact.

### Do not use this tool for

* Single-channel conflict or casualty claims that have not been independently
  confirmed;
* Drafts that copy protected reporting without original writing;
* Bulk approval of hundreds of pending reports;
* A story with a rejected/disputed fact-check state.

When in doubt, keep a story pending and investigate further.
