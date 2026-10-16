# Token recovery: continuous accounting and offline response gate

## Scope

This runner is an offline fixture harness, not a live model runner. It accepts response bytes, has no network client, reads no credentials, and executes no generated tool calls. Passing a fixture does not demonstrate a complete task, model quality, or the user's ≤1,000,000-token full-task target.

The historical source and experimental execution budget must be independent files. Contract creation and verification reject source paths inside the execution tree, symlink aliases, and hardlinks to mutable budget files. Sources are hash- and inode-bound. Contracts and per-request evidence directories are exclusively created; preexisting destinations are never overwritten. The runner consumes an existing child budget; it never initializes or resets permission or allowances.

## Accounting contract

`token_lineage.create_contract` binds the original cumulative report, original child budget, and an identical restored child-budget copy. The report must contain the exact child snapshot. Historical known usage already includes that child snapshot: only subsequent child deltas are added to the research total.

For the actual preserved baseline, cumulative known usage remains 2,746,096 tokens, 73 HTTP attempts, and 3 historical unknown usages. The latest narrow child allowance has 4 of 8 HTTP attempts and 180,208 of 1,000,000 known tokens consumed; known remaining is 819,792 tokens and 4 requests. Historical nonactual holds (219,060) are kept separately, not described as actual token usage. Unknown usage is not zero; the total is not exact. A new pending or unknown attempt blocks subsequent verification despite the historical unknown prefix. Reasoning is not counted twice.

`research_limit` is a bound checked by this offline contract, not evidence of permission. Frozen historical sources and current external authorization remain separate prerequisites for any future real run. Go or official fallback cannot inherit an OpenRouter-only authorization.

## Execution order

1. Rehash the contract and source files, check identities and isolation, verify unchanged historical attempts and limits, and reject new unknown usage.
2. Exclusively create a private evidence directory.
3. Use the real token adapter to prepare the final payload and reserve its conservative UTF-8-byte input estimate plus output cap, bound to the child budget ID.
4. Parse and scan fixture response bytes. Settle independently observed valid usage, including known failed responses. Missing or ambiguous usage remains unknown.
5. Require complete protocol and safe evidence before marking the fixture accepted. Recheck continuous accounting and write an explicitly offline result.

Payload bytes are an admission estimate, not actual tokens. The fixture's simulated attempts and usage never belong in the historical real-model ledger. The isolated restored-baseline demonstration consumed one simulated 12-token response only; actual new model HTTP remains zero.

## Response preservation

Chat SSE retains exact safe wire bytes separately from its derived semantic JSON. The wire cap is 32 MiB and semantic cap 4 MiB. Frames are decoded sequentially, so a valid complete usage frame survives a truncated or invalid-UTF8 tail, while the incomplete response remains ineligible for execution. Conflicting/repeated usage is not guessed.

Responses JSON retains the original JSON separately from the normalized Chat-like evidence envelope. Tool arguments use the strict parser: objects only, no NaN, no duplicate keys, and no duplicate call IDs. Credential-like content or unscannable raw content is never accepted as safe evidence. The offline sentinel is synthetic, not a credential.

## Review history and limits

Freeze 0631 exposed three defects in independent review: loss of prior usage on an invalid tail, overly permissive Responses arguments/IDs, and source/execution alias pollution. Original failing logs and independent tests were preserved. Freeze 0638 addresses these with protocol and pre-write isolation checks. Independent review passed 58 tests including nine independent counterexamples. Freeze 0640 only translates comments into Chinese, with no behavior changes. See `offline-validation/independent-offline-chain-audit-20261015.md`.

The earlier full suite had 625 passes and four environment-related failures. Those failures require forbidden browser/network facilities and were not removed or weakened. The final full run passed 630 tests with the same four failures (5840 warnings). Original-source hash checks also passed after a fresh, isolated 12-token synthetic fixture. No fixture result replaces the historical 15 `not_run` acceptance checks or establishes successful completion of the original model task.
