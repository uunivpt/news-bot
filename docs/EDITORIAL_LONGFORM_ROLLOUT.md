# PoliticsHub automated long-form publication (staging proposal)

## Goal
No mandatory human prepublication approval for low-risk, evidence-supported stories.
The worker publishes directly **only when every automated check passes**. A
failed or inconclusive check holds the story. Automated screening cannot certify
truth, independence or copyright clearance.

## Pipeline
1. Collect attributed RSS/official-source material and cluster related headlines.
2. Assemble source URLs, snippets and permitted public article material as research evidence.
3. If enough evidence exists and Phi-4 is configured, draft an 800-1200 word report.
   Never pad, paraphrase entire copyrighted articles, or invent details.
4. Screen for two distinct publisher domains, >=500 source-material words,
   >=800 article words, substantial vocabulary overlap with evidence, no
   unsupported numerical claims, no recognized high-risk claims, and acceptable
   content quality. These are heuristics, not independently verified facts.
5. If every gate passes, publish without requiring an editor's review status.
   Otherwise retain the pending item. X posts still require separate review.

## Important limitations
- Multiple sources can republish the same press release; domain diversity alone
  does not verify a claim.
- Current risk checks are primarily English. Non-English fact-checking remains
  inadequate; those stories need language-specific checks before release.
- Automated writing must add genuine explanatory value, not merely inflate text.
- A generic 800-word threshold is an **internal preference**, not an AdSense rule.
- There is no guarantee of AdSense approval.
- The job currently requires a reachable model endpoint (PHI4_ENABLED);
  otherwise long-form publication is held rather than publishing thin summaries.
- Existing published archive content is not repaired by this change.

## Release gate
Do not merge this draft until CI, realistic database tests, model availability,
the production source/licensing constraints and staging smoke tests have passed.
Run editorial tests and ensure existing news publishing/feeds remain operational.
Rollback is reverting the PR or restoring previous deployment.
