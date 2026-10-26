# PROGRESS

Live status. One fact, one home: rules live in `CLAUDE.md`, the challenge in the
hackathon's Official Rules (a local copy, see `CLAUDE.md`).

## Deadlines (Bratislava time)
- Registered: confirmation e-mail Sun 18 Oct 22:33 CEST. Innovation Studio profile created
  Mon 19 Oct.
- Internal: **Tue 27 Oct 2026, 20:00 CET**
- Submission closes: **Wed 28 Oct 2026, 07:59 CET** (= Tue 27 Oct 23:59 PDT)
- Clocks change in Bratislava on Sun 25 Oct (CEST → CET); in the US on Sun 1 Nov.

## Now (Mon 26 Oct, 21:00 CET)
The current state only: each milestone's record is in Backlog by milestone below, the owner's
other decisions in the next section, the history in the git log of the private repository.
- **Done:** M0–M6. M5 item 7 (player focus) was conditional and is not done. **M7** (the
  submission) runs in `m7-submission` (`.claude/worktrees/m7-submission`, session
  `18-plhack-ec` since 26 Oct ~20:30 CET): the denylist hashes, the README, this public PROGRESS,
  the project page's texts and the video script (`docs/submission.md`) are done, Microsoft's
  texts out of the repo, the load limits on `/live` (issue #2); the owner's steps remain, in the
  order M7 gives them.
- **M8 (the showcase): no-go**, the owner's decision 26 Oct 19:48 CET, ahead of its Tue 12:00
  date: `m7-submission` is what is submitted, and the public repository and the video follow
  the re-deploy at once. M8's work stays on `m8-showcase` and in its worktrees for after the
  judging; its state is in the GitHub issues.
- **Branches:** `main` = `f2b50b9` (M2–M6, fast-forwarded and pushed by the owner 25 Oct
  22:18 CET; GitHub CI green, run 40234895445). `m5-personalize` = `0b130a6` (the demo runs of
  M5 and the startup probe's window), pushed by the owner 26 Oct. `m7-submission` builds on it.
  Only the owner pushes and merges into `main`.
- **Live app:** https://ca-matchlens.niceglacier-670016e8.swedencentral.azurecontainerapps.io/
  runs `ca-matchlens--23d81ab` (M7 with issues #2 and #7) since 26 Oct 23:30 CET, deployed by
  the owner (Metrics: Deploy, issues #2 and #7; the auto-mode classifier refuses a deploy to
  Claude). Frozen from the
  submission's close, Wed 28 Oct 07:59 CET, to the end of judging, Wed 11 Nov 08:59 CET: no
  re-deploy, not even a bug fix; a restart if unhealthy; a change only if the Sponsor permits it
  (owner, 24 Oct; `docs/deploy.md`).
- **Models and cost:** Claude Sonnet 5.5 and Haiku 5.5 on Foundry (`aif-matchlens`, both
  `NoAutoUpgrade`); the demo replays Sonnet 5.5 runs (owner, 23 Oct). October to 25 Oct: €3.73,
  of it €3.43 for all model calls (Metrics: Cost, October to 25 Oct).
- **Name:** the product is **Footnote** (23 Oct, chosen by Claude at the owner's word): every
  line on screen has a footnote with its evidence. The package and CLI stay `matchlens`.
- **Against the rules** (the hackathon's Official Rules): the five stages of 4.1(i), the metrics
  of 4.1(ii), recaps (iii), explainability (iv), the synthetic data (v), a second language (vi)
  and the category's points (distinct roles, shared state, handoffs, recovery) are covered; a
  deployment runs. Open: the M7 artifacts (video, public repo, project page).
- **Edge to show** (23 Oct, from the other entries visible to entrants): verified facts alone do
  not set an entry apart; ours is a deterministic Guard (no model judges) with machine-readable
  reasons, retries, fallbacks and a breaker, the engine's readings for judgement words, and
  measured numbers. The target stays Best Multi-Agent System.
- `docs/agent-graf/` (the owner's notes) stays local: gitignored, which also keeps it out of
  ruff. So do the hackathon's Official Rules and its resource page (`docs/RULES.md`,
  `docs/resource-playlists.md`, Microsoft's texts; `CLAUDE.md` says how to restore them).

## Owner decisions outside the milestone plans
Bratislava time. Each milestone's own approvals stand in its section of the backlog.
- 19 Oct: the private GitHub repository `radozaprazny/18_plhack`, `main` first pushed by the owner
  at 17:43 CEST (`m1-ingest` at `ebc2bb9`; its first GitHub CI run passed), the default branch set
  to `main` (owner OK); public only at M7. The Innovation Studio hackathon page answers 404 without
  a login, so the owner reads the other entries there.
- 20 Oct: no Claude session pushes to GitHub; the owner pushes from a terminal. The stop point of M2
  item 3 lifted.
- 21 Oct: the stop point of M3 item 2 lifted; 2 more Foundry calls that day (8 instead of 6); the
  Sonnet deployment set to `NoAutoUpgrade`.
- 22 Oct: M3 item 7 before item 6; item 6 at most 340 model calls, 170 per model: seeds 0, 1 and 3
  over MCP, 28 moments a model, at worst 3 attempts × 2 requests each = 168 a model.
- 23 Oct: the stop point of M3 item 7 lifted with "SDK retries 0" (it had stopped at a review
  finding: the SDK's 2 HTTP retries of a timed-out request may be billed and were counted nowhere);
  the demo replays the Sonnet 5.5 runs; M5's scope: Slovak required, since the strongest entries
  seen speak several languages, and player focus moved to the conditional item 7; M6 starts at 0.25
  vCPU and steps up only on a problem; the product is named **Footnote**, since the working name was
  taken by another entry and no football product of that name was found on the web or GitHub.
- 24 Oct: the page's reopen budget stays as it is (after a measured revision restart); the app is
  frozen during judging (Now).
- 25 Oct: M5 item 4 closed without a further round; M5 item 6's third stop point lifted for the one
  word it named; its Slovak run on Sonnet; M5 item 5's open follow-up left to Claude ("item 5, you
  decide", translated from Slovak); at 23:10 "I agree, go on" (translated from Slovak) to the
  audit's steps: the re-deploy of the M5 demo runs and M7.
- 26 Oct, "yes, as you recommend" (translated from Slovak): the stop point of M7's publication
  item lifted; the repository goes public as a new one from a squashed commit of `main`; three
  sentences for the Lessons of CLAUDE.md (approved by owner, 26 Oct).
- 26 Oct, about 16:25 CET, answered in chat: the new public repository is `radozaprazny/footnote`;
  its one commit carries the owner's GitHub noreply e-mail; the two Claude workflows are disabled
  there and it gets no secret (CI needs none); the hackathon's Official Rules and its resource
  page, Microsoft's texts, leave the repository and stay local.
- M5's Foundry budget as of 25 Oct: Sonnet 230 of 300 calls, Haiku 15 of 170.
- The Lessons of CLAUDE.md were each approved by the owner when added, among them: 19 Oct (the `&&`
  pipe, with the format hook's order); 21 Oct (a verifier mutates only a copy); 23 Oct (Commands get
  the Playwright install; Lessons get the surviving mutant, an option's `dest`, `pgrep -f`, denylist
  exceptions, the anchor splice, pipefail and scratch-copy mutants); 24 Oct (a loud lookup under
  `set -e`, `!` in double quotes); 25 Oct (readable colours, second-language word lists); 26 Oct
  21:00 CET (`git rm --cached` and a local copy, from the review of Microsoft's texts).

## Schedule: walking skeleton first (agreed by owner, 19 Oct)
A thin end-to-end slice through all five stages before any stage is deepened. Judges may score
from the video and text alone (rules 4.8), so deploy and video keep a 1.5-day reserve.

| Day | Goal |
|---|---|
| Mon 19 | M1 items 2–3: event schema, seeded generator |
| Tue 20 – Wed 21 | M1 items 4–5 (SSE, CLI); M2 thin: 4 stats, exposed as an MCP server |
| Thu 22 – Fri 23 | M3 thin: Moment Detector → Analyst → Guard on Agent Framework, 2 Foundry deployments (stop point); M4 thin: JSON cues + 2D pitch page |
| Sat 24 – Sun 25 | M5: 2 personas, EN + SK, Recap; M6: ACA deploy (stop point). Clocks change Sun |
| Mon 26 | M7 prep: video, README, testing instructions, denylist hashes, repo public (stop point) |
| Tue 27, by 20:00 CET | Submit; 12 h reserve |

Deepening (more stats, personas, languages) only after the slice runs end to end. Each milestone
still gets its own plan and owner approval before `/ship`.

## Stop points (the loop pauses and asks)
billed Azure resource · anything published (push, public repo, video, submission) · scope change · 3× red in a row

Quality bar for walking-skeleton items (owner decision, 21 Oct): a red round opens only for
`scripts/ci.sh` red, a property named in the approved plan missing or failing, the real run
failing, or a SERIOUS review finding. MINOR findings, the mutation score and extra long
Hypothesis runs never open a round: fix the cheap ones, the rest go to Follow-ups. The Guard's
mutation score is a number in Metrics, not a gate.

## Metrics (measured, not estimated)
| Metric | Method | Value |
|---|---|---|
| Guard pass rate | from a run's `summary.json` (built from `handoffs.jsonl`, every chain checked): first attempt = moments whose attempt 1 passes / moments; final = moments ending with a narrative / moments; real Foundry runs only, the Analyst over MCP, seeds 0, 1, 3 (owner, 22 Oct), per model, 23 Oct 10:00–10:35 CEST, `--pace 35` | Haiku 5.5: 28 of 28 first attempt, 28 of 28 final; Sonnet 5.5: 28 of 28, 28 of 28. 0 skipped, 0 crashed. A pass may hold no number: 1 Haiku narrative cites no fact (it did not call the tool; 1 of 28 attempts) |
| Readings in narratives (M5 item 1) | Sonnet 5.5 runs with the readings (`b18b545`), the Analyst over MCP, `--pace 35`, seeds 0, 1, 3, 23 Oct 18:43–18:58 CEST (`runs/m{0,1,3}/20261023T16…Z` in the `m5-personalize` worktree, gitignored), counted from `handoffs.jsonl`: the Guard → render handoffs, the fact ids of each passed draft's claims; latency = a moment's summed attempt wall time incl. the tool call, nearest rank; smoke runs on m7's first goal before them, one per model; cost at list price from `summary.json` | Guard: 28 of 28 first attempt, 28 of 28 final, 0 skipped. Narratives citing a reading: 28 of 28 (1 reading: 16, 2 readings: 12; M3's runs of 23 Oct: 0, as no reading existed); readings cited: score 19, momentum 14, goal 7 (e.g. "Malik Sennabe scores at 5'. Vellbridge Town take the lead, 1–0. Vellbridge Town are on top."). Requests 56, tokens 422 392 in / 10 783 out, $0.953; latency p50 4.85 s, p95 5.66 s, max 5.77 s. Smoke: Haiku 2 requests, 13 434 / 2 140 tokens, $0.0024, 12.6 s; Sonnet 2 requests, 13 434 / 404, $0.0309, 5.2 s; both pass. M5 calls so far: Haiku 2, Sonnet 58 of 170 each |
| Fan renditions (M5 item 2) | Sonnet 5.5, the Analyst over MCP plus the Persona Editor (`--persona fan`, role of `605a31e`), `--pace 35`, seeds 0, 1, 3, 23 Oct 20:58–21:25 CEST; counted from `handoffs.jsonl` (the Guard → render lines: the passed narrative and the fan rendition's last draft); numbers = numerals in the text (a score, a clock, a percentage each count 1); latency per rendition = its attempts' wall time, nearest rank; cost at list price from `summary.json` | Narratives 28 of 28 first attempt; fan renditions 28 of 28 passed at the first attempt, 0 fallback; differ from their narrative: 27 of 28; numbers per text: narrative 2 (20) or 3 (8), fan 0 (3), 1 (22) or 2 (3), never above the role's 2; length mean 112 → 84 characters; readings cited 40 → 32 (e.g. A: "Darnell Fenwright shoots and Cian Mulvarra saves at 03:21. Vellbridge Town are on top with momentum at 85%." F: "Darnell Fenwright shoots and Cian Mulvarra saves. Vellbridge Town are on top."). Requests: Analyst 56, fan 28; tokens 422 392 / 10 771 (Analyst), 108 684 / 7 395 (fan); cost $0.952 + $0.291 = $1.244; fan latency p50 2.5–2.8 s, p95 4.6–6.3 s per match. Smoke runs before (m7's first goal): Haiku 3 requests $0.0031, Sonnet 2 × 3 requests $0.041 each; the first Sonnet rendition was a copy of its caption, the second (revised role) was not |
| Persona switch (M5 item 3) | `matchlens cues --seed 0 --run runs/m0/20261023T185842002Z` (item 2's Sonnet run, `m5-personalize` worktree), 23 Oct, final code: the replay's stderr; cues whose fan lines differ from the analyst's; numerals on all cards = digit groups (`1–0`, `05:00`, `23.8` count 1 each); page: `matchlens serve` with that run, headless Chromium | 12 of 12 narratives and 12 of 12 fan renditions re-pass the Guard at replay; fan lines differ in 44 of 44 cues (chance 11, goal 1, moment 12, period end 2, window 18); numerals 179 → 50; one SSE stream across the switches, 0 console errors; screenshots `runs/screens/m5-item3-{analyst,fan}.png` (gitignored). m7 without a run: 35 of 50 cues differ (the 15 stats-only moments read the same) |
| Recap Writer (M5 item 4) | `matchlens recap m<s> --run DIR --persona fan` on Sonnet 5.5, seeds 0, 1, 3, 24 Oct 15:42 CEST (round 3, in item 2's run dirs of the `m5-personalize` worktree, gitignored), summed from each run's `recap.json`; latency = the attempt's wall time; cost at list price; length in characters from `recap.jsonl`. Replay 25 Oct after S1: `matchlens cues --seed <s> --run DIR` over every stored run (the 22 run dirs of `m3-explain`, `m5-personalize` and `m6-deploy/demo`), its stderr counts | Recaps 3 of 3 and fan recaps 3 of 3 passed at the first attempt, 0 fallback; requests 6 (writer 3, fan 3); tokens writer 13 743 in / 1 354 out, fan 12 771 / 571; cost $0.041 + $0.031 = $0.072; latency writer 3.74–4.30 s, fan 2.19–2.39 s (one recap per match, so no percentiles); length 202–248 characters (fan 66–77) of 600 (e.g. "Vellbridge Town 1–0 Quarrendale Rovers. Malik Sennabe scores at 5', and Vellbridge Town take the lead. Vellbridge Town have 52% of the ball, an even share of the ball, and Quarrendale Rovers are chasing the game." F: "Vellbridge Town 1–0 Quarrendale Rovers. Vellbridge Town are in the lead."). Earlier rounds 24 Oct, from the item's record (their files were replaced by round 3): Haiku smoke 2 requests $0.0029; Sonnet round 1 (13:08 CEST) 7 requests $0.090, round 2 (13:13) 6 $0.073, redone for prompt and Guard fixes (round 1 wrote "beat", "lose 0–1 to"). Replay: 147 narratives, 31 fan renditions, 3 recaps and 3 fan recaps (184 texts of 25 logs) re-pass, 0 refused |
| Favourite club (M5 item 5) | `matchlens serve --seed 0 --seed 7 --run runs/m0/20261023T185842002Z` (item 2's Sonnet run, `m5-personalize` worktree), headless Chromium, 25 Oct 10:11 CET, `?match=m0&team=vel&speed=1000&hz=1` to the end: cards in the rail by class; contrast of the accent text = WCAG 2.x ratio of the computed text colour on what is under it (chip: its 15% tint over the card), lowest over the not-dimmed cards, measured by the round-2 verifier with its own code in the browser, and the same from the test's oracle per club | 45 cards: 14 of VEL (chance, goal, moment) on top, 10 of QRD dimmed, 21 of no team; accent `#cb9aa9` (VEL's `#8B1E3F` 11 steps toward white); lowest accent-text contrast VEL 4.656, COR 4.855, SLT 4.529, QRD 9.062 (both methods agree; the primaries themselves 1.60, 1.57, 3.97, 9.06); dimmed cards' accent text 2.2–2.65 by design; 0 console errors; screenshots `runs/screens/m5-item5-{picker,vel-analyst,vel-fan}.png` (gitignored); `tests/test_web.py` 12 tests in 75 s |
| Slovak translations (M5 item 6) | `matchlens translate m<s> --run DIR --lang sk --deployment claude-sonnet-5-5 --max-calls 52/32/40 --pace 15` over item 2's run dirs of seeds 0, 1, 3 (`m5-personalize` worktree, gitignored; their narratives, fan renditions, recaps and fan recaps), 25 Oct 15:56–16:12 CET; counted from each run's `translate.sk.jsonl` (the Guard → render lines) and `translate.sk.json`; latency per translation = its attempts' wall time, nearest rank; cost at list price; length in characters of the passed Slovak text vs its English source. Replay: `matchlens cues --seed <s> --run DIR`, its stderr. Haiku smoke before it (`--deployment claude-haiku-5-5`, a copy of m0's run cut to 3 moments and the recap, 25 Oct ~11:35 CET). Page cost: `matchlens cues --seed 7` wall time, 2 runs each, base `m5-personalize` vs this branch | 62 of 62 passed (analyst 31, fan 31; moments 56, recaps 6), 61 at the first attempt, 0 fallback; the one retry was m1's recap, whose first draft wrote "Saltreach FC má 59% navrch" without the momentum reading (`phrase_not_cited`), the second "momentum Saltreach FC je 59%". Requests 63; tokens 182 209 in / 17 250 out; cost $0.537 (estimate said $0.8–1.0 ±50 %, from Haiku's longer outputs); latency p50 2.68 s, p95 3.31 s, max 6.55 s; length mean 100.7 vs 102.7 characters (ratio 0.98), max 232. E.g. "Malik Sennabe skóruje v 5'. Vellbridge Town ide do vedenia, 1–0. Vellbridge Town má navrch." Replay: 24 + 14 + 18 translations of moments and 2 on each recap shown, 0 refused, also under the Guard's final Slovak lists. Haiku smoke: 8 of 8 at the first attempt, 8 requests, $0.0053. Page cost: 6.0–6.1 s → 6.8–6.9 s a match (every cue built again in Slovak words) |
| Analyst on Foundry over MCP, measured | the same runs, summed per model from `summary.json`: requests / tokens in / out / cost at list price / a moment's latency (its attempt incl. the tool call), p50; p95 (nearest rank, 28 moments) | Haiku 5.5: 55 / 348 568 / 37 682 / $0.054 / 7.96 s; 9.30 s · Sonnet 5.5: 56 / 355 739 / 9 623 / $0.808 / 4.58 s; 5.09 s. With the smoke runs: Haiku 57, Sonnet 58 of 170 calls each, $0.89 in all |
| Event → overlay latency | `scripts/measure_latency.py`, local, 22 Oct 01:31 CEST: app (uvicorn) and headless Chromium 156 on one machine (same wall clock), seeds 0–4 one after the other, speed 20, 5 Hz, cues precomputed; the page stamps each cue at the start of the next `requestAnimationFrame`, before that frame's layout and paint (`performance.timeOrigin + performance.now()`); latency = stamp minus the `emitted_at_ms` of the cue's latest event (shot, goal or period end; the cue's own message for windows), delivery = stamp minus the cue message's; nearest-rank percentiles / cue timeline compute time per match (`match_facts` + `cue_timeline`), not in the above | latency p50 24.4 / p95 71.9 / max 91.5 ms, delivery p50 15.2 / p95 48.5 / max 70.3 ms, n 155 (all cues, 0 console errors); a chance cue is due at the ball's arrival, up to 76 ms after its shot at speed 20 / 4.57–4.85 s. Again 23 Oct 13:53 CEST with the stats-only moment cues (same method, `match_cues`): latency p50 18.7 / p95 68.0 / max 95.1 ms, delivery p50 14.7 / p95 48.0 / max 59.2 ms, n 209 (all cues, 0 console errors); latency p50 / p95 per kind: chance 55.2 / 85.3 (n 44), moment 13.7 / 56.0 (54), window 16.5 / 50.2 (91), goal 8.0 / 23.4 (10), period end 11.9 / 34.7 (10) / timeline 4.73–5.13 s |
| Demo recording | `scripts/record_demo.py`, 22 Oct: m7 at 30×, 60 s of replay, then a card's evidence and its place; Playwright video 1920×1080, length from the file header (Playwright's ffmpeg) | 65.7 s (65.0 s recorded), 28.28 MB, VP9 25 fps, `runs/` (not in git); 23 Oct with moments: m0 with its Sonnet 5.5 run (`--run`, 12 of 12 narratives), 30×, 45 s, then the newest moment card's evidence: 50.9 s (50.0 s recorded), 22.71 MB |
| Match generation | `generate_match(seed)` incl. `validate_match`, mean over seeds 0–49, 19 Oct | 0.42 s per match (50 seeds in 21.2 s) |
| Tracking render | `list(match.frames())` for seed 7, 56 768 frames at 10 Hz, 19 Oct (verifier) | 4.9 s |
| Calibration (means over seeds 0–49, 19 Oct) | passes / accuracy / shots / goals / fouls / throw-ins / corners | 1156 / 0.84 / 22.2 / 2.14 / 22.3 / 31.4 / 3.7 |
| SSE schedule error | `emitted_at_ms` minus planned time, match 7 at speed 20 over 5 s, local uvicorn, 19 Oct (verifier) | 0 to 2.35 ms |
| SSE speed-0 replay | one full match (1 589 messages, 0.59 MB) through `replay` without sending, 5 runs, 19 Oct | 11.8–12.5 ms |
| Possession | `stats.possession` over seeds 0–49, 20 Oct: `spells()` time per match (mean; max, 6 runs) / spells per match, team-less ones included / share of playing time without a team / share of playing time with a loose ball (part of the former) / home share from `possession()` | 2.1–2.3 ms; 6.2–9.5 ms / 480–584 / 16.4 % (13.2–20.6) / 2.3 % (1.8–3.0) / 44–55 %, mean 50.1 |
| Pass quality | `stats.passing` over seeds 0–49, 20 Oct: `pass_ratings()` time per match (mean, 2 runs; max) / difficulty of complete passes: mean, p10–p50–p90, range / progressive passes per team and match / average length per team and match | 19.7–23.3 ms; 26.0 ms / 37.4, 24–37–52, 5–71 / 87–137, mean 111.3 / 20.7–21.8 m |
| Speed and distance | `stats.speed` over seeds 0–49, 20 Oct: player speed between frames, to 0.05 m/s, p50 / p90 / p99 / p99.9 / max / distance per match, outfield and keepers / shot speed p50 / p80 / max, shots below 15 m/s / tags per match: hard shot (28 m/s), sprint (7.0 m/s) / `movement(m.frames())` per match incl. frame generation | 1.20 / 5.95 / 6.05 / 6.50 / 7.20 m/s / 10.45–14.61 km (median 12.71), 4.21–5.01 km / 23.1 / 27.9 / 32.0 m/s, 104 of 1 110 / 4.16 (1–10), 1 in 50 matches / 4.2 s |
| Analyst on Foundry over MCP, smoke | `matchlens explain m7 --until 05:00 --mcp … --max-calls 2` per model (m7's first goal, the facts read with `facts_at`), 23 Oct 09:35 CEST; tokens and requests from `summary.json`, latency = the attempt's wall time incl. the tool call; one attempt per model, so no spread | Haiku 5.5: 2 requests, 11 467 in / 845 out, 11.9 s, $0.0016, Guard pass · Sonnet 5.5: 2 requests, 11 467 in / 328 out, 5.2 s, $0.0262, Guard pass. 2 of the 170 calls per model |
| Explain over MCP, `--fake` | `matchlens mcp --http --seed 7` + `matchlens explain m7 --fake --mcp …` (the `echo` Analyst calls `facts_at`), 22 Oct: requests per attempt / a moment's latency incl. the MCP call, p50; p95 / wall time incl. process start / no server; a server without the match | 2 (30 for 15 attempts) / 38–50 ms; 54–67 ms / 3.2–3.6 s / exit 1 before any request |
| Explain workflow, `--fake` | `matchlens explain m<s> --fake` (the `echo` Analyst, no model), seeds 0–4, 22 Oct 00:45 CEST: moments per match / wall time per match incl. process start, generation and the AF import (`/usr/bin/time`) / `handoffs.jsonl` size | 12, 7, 15, 9, 11 (54), all narratives on attempt 1 / 1.93–2.31 s / 312–676 kB |
| Moment Detector | `explain.detector.detect` on whole matches, seeds 0–49, 22 Oct (`time.perf_counter` around `detect`, match generated before): moments per match, mean (range) / goals, saves, woodwork per match / time per match, mean; max / one case as JSON, p50; max / facts per case | 11.04 (2–17) / 2.14, 8.26, 0.64 / 0.205 s; 0.368 s / 15.4 kB; 15.4 kB / 42–57 |
| Guard | `explain.guard` on all 50 goals and saves of seeds 0–4, 21 Oct: `moment_evidence` + `check` of the stats-only cue per moment (p50; max) | 8.6 ms; 24.8 ms |
| Foundry smoke test | scratch script outside the repo, 21 Oct 16:30 CEST: `AnthropicFoundryClient` (`agent-framework-anthropic==1.0.0b261015`), `AzureCliCredential` token, one structured-output `Draft` call per model on m7's first goal (45 facts, 2 triggers, 3 467 prompt characters), effort low, SDK retries off; tokens and stop reason from the response's `usage`, latency = wall time of `get_response` (token fetched before), cost = tokens × list price; then `guard.check` on the draft. One call per model, so no spread | Haiku 5.5: 2 112 in / 236 out, 4.1 s, $0.00033, `end_turn`, Guard pass · Sonnet 5.5: 2 112 in / 296 out, 3.4 s, $0.0072, `end_turn`, Guard pass. 2 of the 6 allowed calls |
| Analyst on Foundry | `foundry_client` + `Analyst.attempt` on m7's first goal (45 facts), scratch script outside the repo, SDK retries off, 21 Oct; tokens from `usage`, latency = wall time of `attempt` (17:35: incl. the async Entra token fetch), cost = tokens × list price; then `guard.check`. One call per row, so no spread | 16:44 prompt v1: Haiku 3 363 in / 1 238 out, 7.7 s, $0.00096, pass · Sonnet 3 363 / 236, 3.5 s, $0.0091, pass · 17:35 prompt v2 (round-1 fixes): Haiku 3 604 / 923, 6.0 s, $0.00082, pass · 22:55 final prompt (approved by owner, 21 Oct; latency as 17:35): Haiku 4 071 / 925, 6.2 s, $0.00087, pass (2 claims: scorer with shirt number; score and clock) · Sonnet 4 071 / 321, 3.4 s, $0.0114, pass (3 claims: scorer and clock; score; possession 66%) |
| Guard mutation score | scratch mutator (AST + regex mutants of `guard.py`), each mutant against `tests/test_explain_guard.py` under the `ci` profile, final code of item 2, 21 Oct; survivors not classified by hand | 782 of 958 killed (81.6 %); round 3 code: 624 of 812 (76.8 %) |
| Facts + MCP | `matchlens.facts` / `matchlens.mcp` on m7, 20 Oct: `match_facts` (facts; time, mostly the tracking pass) / `facts_at` (facts; time) / MCP over stdio: client initialize, first `player_facts` (computes the match), cached `match_facts` / over streamable HTTP: `facts_at` | 244 (274 after item 4, 21 Oct); 4.1 s / 37 (15 + 22 shirt numbers; 57 after item 4) at 67:23; 15 ms (median of 20) / 0.8 s, 4.1 s, 80 ms / 11–43 ms |
| Flow | `stats.flow` over seeds 0–49, 21 Oct: whole match possession changes per minute p0 / p10 / p50 / p90 / p100 / average possession length, range (p50) / changes per match, range (p50) / A → nobody → A merged per match (mean) / pressing per team and minute, range (mean) / chaos, whole match / 5-minute windows (902, clock 0–5, 5–10 … min of each period): chaos p0–p10–p50–p90–p100, home momentum p10–p90, action weight p50 / time per match: `control`, `pressing`, `momentum` (mean; max) / `facts_at` on m7 at 67:23 over MCP stdio | 2.67 / 2.85 / 3.03 / 3.22 / 3.32 / 15.1–18.2 s (16.4) / 256–322 (292) / 64.7 / 0.23–0.66 (0.47) / 47–52, p50 50 / 32–43–51–57–65, 16–83 %, 24 / 2.9 ms (6.9), 0.6 ms (0.9), 2.4 ms (3.4) / 57 facts in 32 ms |
| Cue timeline | `cue_timeline` over seeds 0–4, 21 Oct: cues per match / time per match given `match_facts` / `match_facts` itself; seeds 0–12 (verifier) | 32, 28, 35, 29, 31 / 0.46–0.57 s / 4.13–4.32 s; 28–35 cues |
| Moment cues | `moment_cues(generate_match(seed))` without a run, seeds 0–4, 23 Oct (one run each): moments per match / time per match (Detector + evidence + stats-only text) | 12, 7, 15, 9, 11 / 0.19–0.43 s |
| Live stream | `matchlens serve --seed 7 --seed 8`, curl `/matches/m7/live?speed=0`, local, 21 Oct: MB per match at hz 1 / 5 / 10 (messages at 5 Hz: frames, events, cues) / schedule error = `emitted_at_ms` minus planned time from the first message, speed 20, hz 5, 12 s (1 264 messages); verifier: client arrival minus plan, speed 100, whole match (30 094 messages) / `live_timeline` build at hz 1 / 5 / 10 | 4.69 / 20.92 / 41.20 MB (28 384, 1 675, 35) / −0.35 to 6.0 ms, p50 1.0, p95 3.0; p50 0.49, p95 1.18, p99 3.19, max 11.4 ms / 12 / 60 / 114 ms |
| Live limits | Issue #2, 26 Oct ~13:30 CET, devbox (8 cores, load 4.7): m0 through `/live?speed=0` at hz 1, 5 and 10, two runs each, the app and its client in one process (`create_app` + Starlette `TestClient`, the overlay computed first; scratch script `/tmp/plhack-m7-measure/cpu.py`), `time.process_time` and `time.perf_counter` around reading the whole stream; µs a frame = process CPU / frames, so an upper bound for the server alone. Then `matchlens serve` with `LiveLimits` and the page in headless Chromium at 60×, 10× and 30×. 26 Oct 21:03 CET: `matchlens serve --seed 0 --run demo/runs/m0` (scratch script `/tmp/m2-measure/rss.py`), streams of 30× at 5 Hz opened with httpx one after the other and held (their line iterators kept: httpx closes a dropped one's connection, which frees its share; the 13:30 run had dropped them), `VmRSS` of the server (kB = KiB) before, with them and after | hz 1: 5 855 frames, 4.9 MB, 2.37–2.74 s CPU (404–468 µs a frame); hz 5: 29 271 frames, 21.7 MB, 10.08–10.10 s (344–345 µs); hz 10: 58 540 frames, 42.6 MB, 16.73–18.27 s (286–312 µs). The page played at every speed, 0 console errors. 21:03: 4 streams admitted, the 5th a 503 with `Retry-After: 5`; `VmRSS` 79 000 kB with 0 streams, 85 524 kB with 4 open, 86 120 kB after; the video's link (300× at 1 Hz) a 503 while full and a 200 after; 422 with the reason for 1000× at 5 Hz, 0.5× and 60× at 10 Hz. The limits (`LiveLimits`) are design choices on these numbers: a stream at most 300 frames a second, all of a replica's together at most 600 (0.21 s of CPU a second at 5 Hz, up to 0.28 s at 1 Hz), speed at least 1 |
| MCP response size | m7, 20 Oct, in-memory client: text blocks plus structured content; facts without id lists (`event_count`, `frame_count`) against the same facts with them | `match_facts` 0.143 MB (0.837 with ids); `facts_at` at the final whistle 21 kB (221); `fact_evidence` of the match possession fact 49 kB. After item 4, 21 Oct, same client: `match_facts` 0.161 MB, `facts_at` at the final whistle 33 kB, `fact_evidence` of the match chaos fact 49 kB (with ids not re-measured) |
| Container | `scripts/container.sh` (M6 item 1), 23 Oct 16:09–16:54 CEST, docker 29.6.1 on the devbox (8 cores, load average 1.1–2.1, other sessions running), `linux/amd64`, `--memory 512m`, `CPUS` 0.25 (3 runs) / 0.5 (1) / 1 (2); the three `/live` requests one after the other, so each also waits for the queued cue timelines (one match after the other in the app's worker); size: `docker image inspect` `.Size` (compressed content under Docker 29's containerd store; the verifier's `docker save \| gzip`: 69.6 MB) and `docker image ls` on disk; memory: `VmHWM` of PID 1 after the three `/live` heads (kB = KiB) | image 70.1 MB, 318 MB on disk (first build with uv copied in: 95.7 / 406 MB; with the stdlib compiled: 76.0 / 342 MB and no faster, so left out). Cold start to `/healthz`: 28.2–29.9 s / 9.0 s / 4.1–4.4 s. First `/live` message of m0, m1, m3 after start: 86.6–93.1, 144.6–153.9, 201.2–215.7 s / 24.9, 40.2, 53.2 s / 10.2–10.6, 16.6–16.8, 22.9–23.0 s. Memory 108.3–109.1 MiB in all runs. `docker stop` with a stream open: 20.7–21.8 s, exit code 0 in all runs (graceful timeout 20 s, ACA kills at 30 s). PID 1 is Python as uid 10001; 12, 7, 9 of 12, 7, 9 narratives at replay |
| Container, M5 demo runs | `scripts/container.sh` in `m6-demo-m5` (M5's demo runs), 25 Oct, docker 29.6.1 on the devbox (load average 1.3–1.6, other sessions running), `linux/amd64`, `--cpus 0.25 --memory 512m`: before the startup fix (ended 23:24 CET), `main` with M3's runs (`f2b50b9`, ended 23:28) and after the fix (ended 23:37); `matchlens serve` with the container's arguments at full CPU, no limit (23:14) | image 70.5 MB content, 324 MB on disk; cold start to `/healthz` 206.03 s (before the fix 211.82 s, `main` 202.39 s; full CPU 19.1 s), `/readyz` 200 at 206.06 s, at once; first `/live` message 0.39–0.90 s after its request; server memory VmHWM 137 412 kB (134 MiB); `docker stop` with a stream open 21.93 s, during the cold start (86.1 s in) 0.88 s, at `/healthz` (205.1 s in) 1.49 s, exit code 143 each; replay: 12 + 7 + 9 narratives, as many fan renditions, 24 + 14 + 18 Slovak translations and every recap and fan recap shown, 0 refused |
| Readiness and stop | M6 item 2, 23 Oct. Local: `matchlens serve` of m0, m1, m3 with the demo runs on the devbox, `/healthz` and `/readyz` polled every 0.1 s from the start (scratch script), then one `/live?speed=0&hz=5` of m3 and SIGTERM; `tests/test_container.py`'s stop script timed 5 times per phase. Container: `PORT=8767 scripts/container.sh` at 0.25 vCPU / 512m, ended 17:36 CEST (load average 1.1–1.8), `/readyz` polled each second; early stops after the first run's replay check is logged (cold start, `/healthz` not yet answering) and at `/healthz` (warm-up). Unhandled window: `python -c "import matchlens.cli"` timed 5 times with `/usr/bin/time` | Local: `/healthz` 200 at 2.7 s; `/readyz` 503 pending m0, m1, m3 → m1, m3 at 7.9 s → m3 at 12.9 s → 200 at 17.9 s; m3's stream after it 200, 20.9 MB; SIGTERM when ready: exit 143 in 0.26 s. Stop script: cold start 0.064 s (all 5), warm-up 0.21–0.27 s, exit 143. Container at 0.25 vCPU: `/healthz` 28.9 s, `/readyz` 503 at that moment, 200 at 211.2 s (first `/live` message of m0, m1, m3 at 91.5, 151.8, 211.4 s); memory 108.9 MiB (VmHWM); `docker stop` with a stream open 21.7 s, exit 143; during the cold start (22.4 s after the start) 0.88 s, exit 143; during the warm-up (27.8 s) 1.44 s, exit 143 (item 1's verifier: 30.3 s, exit 137). Second run after the review fixes, ended 18:17 CEST (load average 1.2–3.0): `/healthz` 14.5 s, `/readyz` 200 at 189.7 s (first `/live` of m0, m1, m3 at 65.7, 126.6, 189.6 s), 147 `/readyz` probes during the warm-up: median 0.178 s, **max 1.586 s** (`curl` `time_total`); stops 21.8 s / 0.90 s (cold start, 22.5 s) / 1.43 s (warm-up, 29.1 s), all exit 143. Unhandled SIGTERM window (interpreter start + `matchlens.cli` imports): 0.07–0.11 s locally, at 0.25 vCPU ≈ 0.3–0.5 s (estimate, ×4 for the CPU quota, ±50 %) |
| Stream resilience | M6 item 4, 23 Oct 19:51–19:52 CEST, devbox: `matchlens serve` with the container's arguments (seeds 0, 1, 3, their demo runs, graceful 20 s), the page `?match=m0&speed=30` in headless Chromium (Playwright 1.64), scratch script `/tmp/m6probe/realrun.py`: SIGTERM at clock 03:01, restart on the same port once it exited; then every `/live` answered 503 by `page.route`, SIGTERM, restart 8.5 s after the cut with the 503s off. Page states timed by `performance.now()` in the page, requests by Playwright's events. Rerun by the verifier: the same behaviour | Restart: the stream ran on until the graceful 20 s were over (exit 143); the browser retried 1.0 s apart (refused); the 4th retry reached the new server and resumed with `Last-Event-ID: m0-f007872` (= the clock shown, 13:07); live 8.2 s after the cut, before `/readyz` 200 (m0's timeline is computed first). 503: the browser's own retry 1.0 s after the cut, then the page's reopens at +1.0, +2.0, +4.0, +8.0 s, each with `last_event_id=m0-f018064`; the 4th reached the restarted server, live 16.7 s after the cut. Whole run: 9 079 clock values 00:00 → 30:15, steps of 0 or 1 s only (none back, none skipped); 16 cards, all distinct; 8 console errors, only `ERR_INCOMPLETE_CHUNKED_ENCODING`, `ERR_CONNECTION_REFUSED` and 503 |
| Deploy | M6 item 3, 23 Oct 23:41 – 24 Oct 00:01 CEST, revision `ca-matchlens--5b18038` at 0.25 vCPU / 0.5 GiB: `scripts/deploy.sh` twice for the same commit; ACA's system and console logs (`az containerapp logs show`, timestamps converted from UTC); `az monitor metrics list` per-minute maxima. From the devbox: `curl -sv --http2`; `/live?speed=1` read with httpx (51 messages); `/events?speed=1` resumed at `Last-Event-ID: m0-e00096`, so the 37 s pause after m0's first goal comes first; scratch script `/tmp/m6deploy/urlrun.py`: the page `?match=m0&speed=10` in headless Chromium (Playwright 1.64) for 300 s with a raw `/live?speed=10` beside it, then the page `?match=m1&speed=10` with `az containerapp revision restart` 20 s after it went live and `/healthz` polled every 0.5 s | First run 4 min 49 s (23:41:05–23:45:54): LA 34 s, ACR 16 s, build + push 13 s (layers cached), env 1 min 52 s, app 40 s. Revision created 23:45:01, image pulled in 3.75 s (69.2 MB), container started 23:45:12, `/healthz` bound 23:45:16, `/readyz` 200 at 23:45:42: **30 s after the container's start** (devbox `--cpus 0.25`: 190–211 s; at 1 CPU the last match streamed after 23 s). Second run 16.5 s, nothing created; the script as revised after the review, 24 Oct 13:00, same commit: 24 s, every step "already" (`deploy-rerun2.log`). TLS 1.3, HTTP/2 by ALPN, port 80 → 301 to https. `/live` 1×: headers and first `data:` together at 0.91 s, then 50 gaps median 0.200 s, max 0.201 s (no buffering). `/events` 1× across the pause: heartbeats at 15.12 and 30.12 s, the next event at 37.12 s. Rerun 24 Oct 13:07–13:10 with saved output (`tls.log`, `basics.log`, `heartbeat.log`): TLS 1.3, h2 accepted, 301; first `data:` at 0.52 s, gaps median 0.200 s, max 0.203 s; heartbeats at 15.13 and 30.13 s, the event at 37.12 s. Keep-alive (`keepalive.py`, 24 Oct 13:00–13:06): one client, 70 `/healthz` requests 4.9–5.5 s apart (around uvicorn's 5 s idle close), all 200. 10× past 240 s: **no cut**: the page made one `/live` request in 301 s, clock 00:00 → 46:21 in steps of 0 or 1 s, 0 console errors; the raw stream had 15 938 messages in 300 s and was ended by the client. `revision restart` (23:57:04): **rolling, no 503**: a new replica was scheduled 1 s after the call, started after 23 s and was ready about 48 s after the call; the old one kept the page's stream until 80 s after the call (then SIGTERM's graceful 20 s); the page showed "Reconnecting…" for 1.4 s and resumed with `Last-Event-ID: m1-f010220`, clock in steps of 0 or 1 s, 1 console error (`ERR_HTTP2_PROTOCOL_ERROR`, the cut); all 208 `/healthz` polls 200. Console log of the old replica: SIGTERM 61 s after the call (about 12 s after the new one was ready), the stream cancelled 19.4 s later when the graceful timeout ran out. A first try (23:54:49) ended its watch 62 s after the call, 8 s after the old replica's SIGTERM and before the cut (117 polls, all 200). `WorkingSetBytes` per-minute maxima 136.7–189.0 MiB (189 with two 10× streams and the restart); CPU at most 0.261 cores in a minute. Re-deploy of a new commit (`9de1094`, owner's OK, 24 Oct 17:22:12–17:23:56 CEST, `redeploy.log`, the page `?match=m1&speed=10` open throughout, `redeploy-watch.log`): 1 min 44 s (build 8 s from the layer cache, push, `update --yaml`); the new revision polled `Provisioned Activating None true` 5 times, then `Provisioned Running Healthy true` after 57 s (a fresh revision is active while it warms up and never showed `Failed`); the page kept its stream on the old revision until 43 s after the new one was healthy, then "Reconnecting…" for 1.5 s and resumed with `Last-Event-ID: m1-f017398`, clock in steps of 0 or 1 s, 1 console error (`ERR_HTTP2_PROTOCOL_ERROR`, the cut); all 792 `/healthz` polls 200. Saved in `/tmp/m6deploy/`: `deploy.log`, `stream10.log`, `restart.log`, `restart2.log`, `system-logs.json` and `console-logs.json` (Log Analytics, 23 Oct 23:40 – 24 Oct 00:05 CEST; the files' timestamps are UTC and up to 1 s off `az containerapp logs show`'s), `metrics.json` |
| Deploy, issues #2 and #7 | `23d81ab`, the owner 26 Oct; as the next row, 23:30 CET | revision `ca-matchlens--23d81ab` healthy 45 s after the script created it; container started 23:29:35 CET, 9 startup probe failures, 100 % of the traffic at 23:30:08, `1d5c025` deactivated; `/matches`, `/matches/m0/recap` 200 in 0.10–0.12 s, the recap's sources as below; `/live` of m3 first data after 0.61 s; 1000× a 422 with its reason. Two Playwright takes of the page at 1920×1080 (the shots 0:00–0:52 and the full time at 300× and 1 Hz, full time 20 s after opening), 0 console errors; the full-time card has no top speed |
| Deploy, issue #2 | `scripts/deploy.sh` of `1d5c025` (`m7-submission`) run by the owner 26 Oct; ACA's system log and `az containerapp show` (`/tmp/m6demo-scripts/post_deploy.sh`, UTC converted), curl from the devbox, 22:44 CET | revision `ca-matchlens--1d5c025` healthy 57 s after the script created it; image pulled in 3.59 s (70.3 MB), container started 22:42:21 CET, 10 startup probe failures 22:42:22–22:42:49 (every 3 s, the warm-up before the bind), 100 % of the traffic at 22:42:59, `0b130a6` deactivated. `/healthz`, `/readyz`, `/`, `/matches`, `/matches/m0/recap` 200 in 0.11–0.13 s (the recap by the Recap Writer, its fan recap by the Persona Editor, both in Slovak by the Translator); the page has the persona and language switches; `/live` of m3 sent its first data after 0.61 s. The limits live: m0 at 1000× (5 Hz), 0.5× and 60× at 10 Hz each a 422 with its reason; the video's 300× at 1 Hz a 200 with its `meta` |
| Deploy, M5 demo runs | `scripts/deploy.sh` of `0b130a6` run by the owner 26 Oct (the auto-mode classifier refused it to Claude); ACA's system and console logs from Log Analytics (REST query of `docs/deploy.md`, UTC converted), `az containerapp show`, curl, 08:33–08:36 CET | revision `ca-matchlens--0b130a6` created 08:08:41 CET, image pulled in 3.50 s (70.3 MB), container started 08:09:07.6, bound 08:09:29.7: **22.1 s** after its start (the replay check computes every overlay first; 4 s on 23 Oct with the timelines after the bind), 8 startup probe failures of the 240 allowed, then ready at once; no readiness or liveness failure and no restart since; `9de1094` stopped 08:10:08. Applied probes as the template (startup 1 + 240 × 3 s). Replay: 12 + 7 + 9 narratives, as many fan renditions, 24 + 14 + 18 Slovak translations and every recap shown, 0 refused. `/healthz`, `/readyz`, `/`, `/matches`, `/matches/m0/recap` 200 (the recap by the Recap Writer, its fan recap by the Persona Editor, both in Slovak by the Translator); the page has the persona and language switches; `/live` of m3 sent its first data after 0.54 s |
| Cost | M6 item 5, 24 Oct about 18:10 CEST: Consumption `usageDetails` (REST GET, api-version 2023-05-01, current billing period), rows of `rg-matchlens` without the `SaaS` ones (Claude on Foundry, billed per call); `az consumption usage list` for comparison | ACR Basic: 0.096 registry-days on 23 Oct (€0.0141) and 0.125 on 24 Oct (€0.0183), so far €0.032 (the 24 Oct row covers 3 h: rows lag by hours). Log Analytics ingestion 0.0011 GB and 0.0008 GB, €0 (inside the free 5 GB). No Container Apps row yet. `az consumption usage list` returned the same 10 rows with quantity and cost `None`. Saved: `/tmp/m6deploy/usage-rest-24.json`; the runbook's October range (`startDate`/`endDate`, 19:42) returned the same 10 rows with the same values (`usage-rest-oct.json`) |
| Cost, October to 25 Oct | Consumption `usageDetails` (REST GET, api-version 2023-05-01, `startDate=2026-10-01`, `endDate=2026-10-31`, as `docs/deploy.md`), rows of `rg-matchlens`, 26 Oct 07:34 CET (rows lag by hours: the latest is dated 25 Oct), summed by meter | 16 rows: €3.73 in all; Claude on Foundry (`claude-consumption-units`, every model call of M3–M5) €3.43, Container Registry €0.30, Log Analytics €0.00, no Container Apps row (presumably inside the monthly free grant, or not billed yet). Cross-check: the list-price sums of the runs in these Metrics come to about $4.0 (M3 $0.89, M5 items 1, 2, 4 and 6 $0.99, $1.33, $0.24, $0.54), €3.43 at about 0.85 €/$ |
| GitHub CI on `main` | `gh run list` / the run's job, 25 Oct: the CI workflow on `main` at `f2b50b9` (run 40234895445) | 2 408 passed; job 22 min 24 s, of it `scripts/ci.sh` 21 min 41 s (the step's timestamps); locally on the devbox `scripts/ci.sh` 17–18 min (2 414–2 450 tests, 26 Oct) |

## Follow-ups
- Issue #2, load limits (review and verifier 26 Oct, MINOR): after the first meta a 422 (e.g.
  `?hz=10` and a click on 60×) is retried on the backoff and ends as "Connection lost", its
  reason unshown; a first-time visitor at a full replica gives up after 31 s with "Connection
  lost", ignoring `Retry-After`; the limits are per replica, not per client (two tabs at 60×
  take the budget, 30 streams at 1× every slot for a match's length); the second replica never
  starts for stream load (the HTTP scale rule needs 10 concurrent requests, the budget refuses
  the 5th viewer at 30×; owner's call); whether Azure's ingress ejects a replica on a burst of
  503s is unverified (a 429 would avoid the question); a speed of 0.05 gets the API's own
  "at least 0.1" before the limit's "at least 1"; `Held(...)` is built outside the `try`; the
  endpoint repeats `admits` without a property tying them; the `console.error` condition, `int`
  for `round` in the thousandths and `BaseException` for `Exception` are not pinned
- M7, Microsoft's texts (review 26 Oct, MINOR): in a copy without `.git` (GitHub's "Download ZIP")
  `test_public_repo.py` fails as `test_deploy.py` already does; the README does not say a git
  clone is needed. `git check-ignore` also honours `.git/info/exclude`, so a devbox that lists the
  two paths there passes the ignore test without the `.gitignore` entries
- Tests (26 Oct): `test_web.py::test_a_closed_stream_is_reopened_with_backoff_until_it_gives_up`
  failed once in a pre-commit CI at a load average of 11 on 8 cores (five CI runs of other
  sessions at once) and passed 3 of 3 alone (26 s each): its timing gives way under load.
- M6 demo runs (25 Oct): since M5 item 4 the whole warm-up runs before the bind (`_replay`
  computes `match_overlay` for its replay lines and the recap check), so readiness gates nothing
  in the image and a restarted replica binds only after its every overlay; a cheap check before
  the bind (moment cues only, as `m6-deploy` had) with the overlays computed in the worker would
  bring the bind back to seconds. `scripts/container.sh` still waits at most 240 s for
  `/healthz`, 28 s above the devbox's 211.8 s at 0.25 vCPU.
- Demo texts (25 Oct, seen in the M5 demo runs): at full time the fan recap says "Vellbridge
  Town are in the lead" and the recap "Quarrendale Rovers are chasing the game": the readings
  have no full-time phrase for a result, and the Guard refuses `win`, `beat`; m0's recap pairs
  "52% of the ball" with "an even share of the ball" (Slovak: "52% lopty, rovnaký podiel
  lopty"); m3's fan recap: "Quarrendale Rovers 1–4 Saltreach FC. Quarrendale Rovers are chasing
  the game." The page shows them to the judges; a fix belongs in the engine (a reading of the
  result at full time). For the video, pick the cards and recaps that read well.
- M7 denylist hashes, review MINOR (26 Oct): a Slovak declension that changes the stem's last
  consonant or drops its "e", and a city's Slovak name instead of its own, are not caught (the
  English drafts are checked too); a false hit of the Slovak forms shows only digests and the
  text, not which word of it hit.
- M6 demo runs, review MINOR (25 Oct): `deploy.sh` waits 600 s for a healthy revision,
  less than the startup probe's 721 s; the probe timeouts' bound (`PROBE_MAX_S` 1.59 s) was
  measured during the warm-up after the bind, which since M5 no longer exists.
- M5 item 6 Slovak renditions (reviews 25 Oct, MINOR or left by the owner): the Slovak Guard
  judges with Slovak lists only, so English words left in a Slovak text pass ("They lead."); no
  Unicode normalization (a decomposed "druhy" + U+0301 matches no list); the club named last
  before a phrase counts, which Slovak word order meets less often ("Navrch má Corrowmere" is a
  retry, "Proti Corrowmere má navrch Vellbridge Town" citing Corrowmere's reading passes); the
  lists are lists (round 3, not fixed by the owner's call): `nezvíťazili`, `nezdolali`, "je
  pozadu", "je o gól vzadu", "zostáva vzadu", `bod` in the singular ("získal bod"), "prevzal
  kontrolu", "vzal hru pod kontrolu", ordinals 11–99 in their forms ("jedenásty", "v
  deväťdesiatej minúte"; a numeral of the source turned into words fails `NUMERAL_CHANGED`
  anyway), "z prvej" with three adjectives or an adverb before the noun, the phrases' synonyms
  ("zatlačený", "ovláda hru", "hrajú otvorene", "korigoval", "trpezlivé budovanie"), "vedúce"
  and "vedie k 3–1" pass; false rejections that cost a retry: "vyhrá druhú loptu", "dal z prvej
  gól", "zdolal brankára", "porazí brankára", "stoper vyhráva hlavičku", "po rýchlom obrate",
  "pod veľkým tlakom"; the test pair ("took control", "kontroloval hru") pins "controlled the
  game"; numerals inside English fixed phrases ("18-yard box") count, so "pokutové územie" fails
  `NUMERAL_CHANGED`; the page's own labels stay English, and the `lang="en"` of an English text
  standing in for a refused translation has no browser test (the page test runs without a run);
  translations run over a finished run only (`matchlens translate`, after `matchlens recap`; a
  recap written later stays English), not inside `matchlens explain`; every cue is built again
  in Slovak words (+0.8 s a match, Metrics)
- M5 item 5 favourite club (verifiers and reviews 25 Oct, all MINOR): the newest cues of no team
  (full time, the recap) sit below all of the favourite's cues, as the spec
  says (the heading says "VEL first"); a page loading a match shows the page's teal until `meta`
  (the accent waits to know whether the club plays); `rgb()` reads `--bg`, `--panel`, `--moment`
  as `#rrggbb` only; a pressed club button differs by colour only, as the persona and speed
  buttons; the picker offers clubs that play no listed match (the page takes the colour, no
  link carries it); the speed switch's test checks the URL, not the classes after reconnecting;
  dimmed cards' accent text in the rail is 2.2–2.65:1 (QRD 3.9–4.8) until hovered or focused; `>=` against
  `>` at 4.5 is not pinnable with 8-bit colours
- M5 item 4 Recap Writer (verifiers and review 3, 24–25 Oct; closed by the owner 25 Oct without a
  further round), in the guard.py docstring: S2, a recap's time rule is per claim and its window
  words are a list, so a whole-match reading passes in its own claim of the sentence that gives a
  goal's minute ("Adrien Pellacourt scores at 5' and Corrowmere Athletic are chasing the game" as
  two claims) and beside words outside the list that place it at a time ("after Adrien
  Pellacourt's goal", "at the break", "early on"; a fix: time words as a list, or the rule per
  sentence). Review 3 MINOR: a number after an on-ball exception counts only after a space ("won
  possession, 48%" passes); `edge of the` before a blanked phrase is a place, also before a window
  blanked in a claim of the last 5 minutes ("on the edge of the last 5 minutes"); `see … off` with
  4 words between passes ("saw the brave young visiting side off"); false refusals, a retry: "the
  edge of their box", "sees his shot deflect off the post"; `shot_speed` facts (scope: the shot's
  event id) are of no time, so any reading may stand beside them. Not the Guard's, so not in its
  docstring: item 4's additions to `_RECENT` are pinned on the refused side only, and only
  `second half` and `after the break` of them (no near miss passes in a test); in `matchlens
  recap`, `summarize` and the write of `recap.json` run after the try that sets the log aside, so
  an error there leaves `recap.jsonl` in place for the next try. All probed 25 Oct on m7's recap
  and m7's 25th shot
- M5 Persona Editor (verifier and review 23 Oct, MINOR): an attempt of one agent that started
  before the breaker opened still ends (the cap holds: requests are reserved before any await);
  a `FatalCallError` of one agent cancels the other's attempt in flight, whose request may have
  left and is then counted nowhere (at most 1, 2 with `--mcp`; the run stops anyway); the editor
  is offered clock, minute and score besides the caption's facts and the readings (in the
  Guard's evidence, so safe; a fan's line may add when and the score); one persona (fan), so
  "per persona" is tested with one; a v2 log reads with no renditions, a v3 line must carry them
- M5 readings (verifier and review 23 Oct, MINOR): the team of a phrase is the club or player
  named last before it in the claim, not the sentence's subject ("Quarrendale Rovers, against
  Vellbridge Town, are on top" passes with VEL's reading; a city used as a place counts as its
  club); words the prompt bans but the Guard does not check: `draw`, `tie(d)`, `under
  pressure`, `on top` beside another verb, `reply`, scores in words ("two-one"); false
  rejections that cost a retry: `led by`, `push to equalise`, `stays calm`, `level with the
  defender`, `on top of` anything but the ball; momentum and possession readings have mirror
  and boundary properties but no monotonicity property; the phrase list is English only (M5
  item 6 adds Slovak); the Guard judges per claim, so a phrase split from its window into two
  claims ("Vellbridge Town are on top" citing the match-long reading, "in the last 5 minutes"
  citing a last-5 fact) or a claim nested in another passes, as numbers do (0 of 58 M3 drafts
  split or nested claims; the prompt asks for whole clauses); tests do not pin every word of
  the blacklist on its own; the window check knows "last 5 minutes" and a few vague forms
  ("recently", "in this spell"), not every way to say a window, and it checks readings only: a
  match-long number in a claim that says "in this spell" passes (the numeric twin, an M3 known
  limit); judgements still passing: "adrift", "in the driving seat", "have the edge",
  "controlling the game", "under pressure"; false rejections still costing a retry: "leaves
  his marker behind", "a dominant header", "caught on the back foot", "in command of his area";
  "behind/ahead of" pass only before a place word (`_PLACE`: defence, line, ball, marker …),
  so a rarer place word is a false rejection
- M4 live (review 21 Oct, MINOR): one worker computes cue timelines in order, so a first
  `/live` of the last match waits for all before it (N × 5 s of silence, no `meta` yet) and an
  invalid id gets its 400 only after that wait; `live_timeline` (60–114 ms at 5–10 Hz) runs on the
  event loop; a frame id of another hz (or a cue id after a cue change) gives 400 instead of
  resuming at the nearest moment; a cue's `frame_ids` are 10 Hz ids that may not be in a lower-hz
  stream; `speed=0&hz=10` costs a few seconds of CPU per anonymous request (41 MB); frames repeat
  the player ids (about 700 B a frame, positions in lineup order would halve it); no concurrency
  test for two first requests (sequential only); a deterministic `cue_timeline` failure is
  recomputed on every request
- M4 web (review 22 Oct, MINOR): the kit-clash rule (`similar` < 120) has no test (seed 7 does
  not clash; pin both sides of the threshold); the scoreboard counts goal events instead of the
  engine's score fact; GitHub CI has no cache for `~/.cache/ms-playwright`; a fresh clone needs
  `uv run playwright install chromium` before the pre-commit hook passes (in Commands since 23 Oct); untested: pitch line geometry, the 4 s spotlight timeout, a card's clock text, speed
  clicks after the end; goalkeepers wear the outfield kit
- M4 moments (23 Oct): `serve --run` computes each run's moment cues twice, once to check the
  run before serving and once in the app's worker (deterministic, 0.2–0.4 s a match); the
  stats-only text is M3's wording, with lower-case club ids
  ("possession cor 58%"); at 30× a moment card leaves the lower third with the next cue (the
  05:00 window follows m7's first goal by 1.4 s)
- M4 cues (review 21 Oct, MINOR): the numeral property strips every cited display from every
  line, so a wrong minute passes if the digit appears in another cited display (lines are pinned
  by oracle tests per kind); no real-match test has a penalty or a stoppage-time goal; the window
  at exactly 45:00 reads "Recent play to 45+0:00" (`display_clock`, an engine change); a saved
  chance could cite its save event (due = arrival); `facts_at` runs once per cue (0.5 s a match),
  so items 2–3 build the timeline once per match, not per client
- guard denies reading git config too: any command naming the hooks-path key matches the deny
  rule, even a plain `git config --get`; allow read-only `git config --get` / `--list`
- verifier depth by item risk: mutation testing and full Hypothesis runs only for the stats engine
  and the Guard; lighter checks elsewhere
- league, before item 3 (generator): lookups `League.club(id)` / `player(id)` / `club_of(player_id)`;
  formation roles (LB/CB/RB, wingers) owned by the generator, deterministic by player id, or a
  `role` field in the data; `position` as `Literal`/`StrEnum`
- league: rules live only in `parse_league`, not in `__post_init__`, so a hand-built `Club` in
  generator tests skips them; malformed JSON raises KeyError/TypeError, not ValueError; empty
  strings for ids and names pass
- before M7: check "Meridian League" and the club codes (COR, VEL) against real names once more
- match ids are `m{seed}`, or `m{seed}{home}{away}` when clubs are chosen by hand; unambiguous
  only because the packaged league has 3-letter club ids. The API keeps a registry keyed by id
  and never parses an id back into seed and clubs
- M4 latency (review 23 Oct, MINOR): the chance cues' p95 is mostly the ball's flight (due at
  arrival, up to 76 ms after the shot at 20×, seconds at 1×; per kind in Metrics since 23 Oct:
  chance p50 55.2 against delivery 13.2 ms), so the headline mixes design delay and delivery; the browser clock (`timeOrigin + now()`, monotonic from page load) and the server's
  `time.time_ns()` can drift apart on an NTP step, so `0 <= delivery_ms` in the e2e test is the
  first suspect if it flakes (`Date.now()` is the alternative); `measure_latency.py` writes no
  JSON if no match got a stamp (`summarize([])` raises after the run)
- M4 latency metric (local value measured 22 Oct, see Metrics; deployed is open): `emitted_at_ms`
  is the server's wall clock when the message leaves the generator; overlay time minus it mixes
  two machines' clocks once deployed. Measure with
  browser and server on one machine (local Playwright), or estimate the offset NTP-style through
  a `/time` endpoint (uncertainty RTT/2); in the browser use `performance.timeOrigin +
  performance.now()`. Write the method into the Metrics table
- M4: a resumed stream sends its first event at once, so the rest of a gap is lost on every
  reconnect (e.g. the 30–50 s before a kick-off after a goal). Fine for now; documented in
  `replay`; revisit if the ACA ingress cuts long streams regularly
- M4 CORS: serve the overlay from the same FastAPI app (StaticFiles): same origin, no CORS, one
  container. Only if it lives elsewhere: `CORSMiddleware` with explicit origins, GET only
- M6 ingress: watch for 502/503 from uvicorn's 5 s keep-alive vs Envoy's idle reuse: none in 70
  requests 4.9–5.5 s apart from one client (24 Oct, Metrics: Deploy; the 325 polls 0.5 s apart
  kept the connections busy, so they could not show it); many clients at once stay unmeasured.
  The container part of this note (exec form, cold start, memory) closed with M6 item 1
- M6 readiness: on ACA at 0.25 vCPU `/readyz` turned 200 30 s after the container's start (first
  deploy) and about 25 s after it (the restart's replica), far inside the 48 × 5 s window
  (Metrics, Deploy); the devbox's 190–211 s at `--cpus 0.25` does not carry over, so no step up
  to 0.5 vCPU. Still unchecked: what ACA does with a replica whose readiness fails past
  threshold × period (never reached)
- M6 (review of item 2, MINOR, older than it): one client leaving while a cue timeline is
  queued cancels the shared future, so other clients waiting on the same timeline get a 500;
  `asyncio.shield` would keep the computation alive (at the cost of the freed queue slot). Moot
  once `/readyz` gates traffic, as every timeline is computed before the first client
- M6 (review of item 2, MINOR): a failed cue timeline is logged (`matchlens.api`, with its
  traceback) and computed again on every probe for as long as it fails, a minute of CPU each at
  0.25 vCPU; by design the revision stays unready, but nothing counts the failures
- M6 SIGTERM: a stop in the first ≈ 0.3–0.5 s of a container (interpreter start and
  `matchlens.cli` imports, before `_serve` installs its handler) is still ignored by PID 1 and
  waits for SIGKILL; only an init (`tini`) closes it. Harmless: ACA does not stop a replica
  that young on purpose
- M6 `test_deploy` vs the pre-commit hook: its test
  `test_a_first_run_creates_everything_in_order_and_a_second_nothing` asserts that
  `git ls-tree HEAD` holds the `Dockerfile`, and in the hook git sees the parent
  commit, so the commit that brings the `Dockerfile` into a branch cannot pass it (simulated 25
  Oct: fails in 1.5 s). The merge of `m6-deploy` into `m5-personalize` (`f2b50b9`) was therefore
  committed by the owner with `--no-verify`, after `scripts/ci.sh` was green on its exact tree
  (`a4dfe40`, 2 408 passed, with the merge as `HEAD`). It bites again only if a branch without
  the `Dockerfile` merges M6
- M6 in-place restart: the reopen budget stays at about 32 s (owner, 24 Oct, after item 3's
  `revision restart` measurement: rolling, no 503, the page back in 1.4 s; Metrics, Deploy).
  Unmeasured: a replica restarting in place (OOM, crash), whose warm-up on ACA (about 25–30 s
  after its container starts, plus the start) is about as long as the page's 32 s; a speed click
  buys 31 s more
- M6 shutdown log (item 3): a stream still open when the graceful 20 s run out is cancelled
  with `ERROR: Exception in ASGI application` and a `CancelledError` traceback in the console
  log (seen at the restart, 23 Oct 23:58:24 CEST): expected behaviour, but every restart with a
  viewer logs it as an error
- M6 template and env (item 3 review, MINOR): `az containerapp update --yaml` replaces the
  containers list whole, so a variable set on the app by hand (`--set-env-vars`, e.g. M5's
  `MATCHLENS_FOUNDRY_RESOURCE`) disappears on the next new-commit deploy: put M5's variables
  into the template's `env:`. Also: the template is the working tree's (deploy.sh notes when it
  differs from the commit's); `test_deploy.py` imports `yaml`, which the lock has only through
  `agent-framework-core`
- M6 deploy.sh (item 3 verifier, MINOR): the fake `docker` checks the build context's file
  names, not their content
- M6 cost (item 3): the resources run since 23 Oct 23:44 CEST, two days before the plan's 25 Oct.
  One 0.25 / 0.5 replica from then to the end of October (8.09 days, UTC) uses about 174 800 of
  the month's free 180 000 vCPU-s and 349 700 of 360 000 GiB-s (the plan's method; estimate,
  every rollover or restart adds a second replica for about 2 minutes, ≈ 30 vCPU-s each): a
  margin of about 5 200 vCPU-s, 5.8 h of a second replica. The default HTTP rule counts each open
  SSE stream as a concurrent request, so an 11th viewer at once starts a second replica. ACR
  Basic $0.33 more. Checked 24 Oct (Metrics, Cost): €0.032 so far, no Container Apps row yet;
  check again after 1 Nov with the runbook's October range (`docs/deploy.md`, Cost) whether
  October's Container Apps use stayed inside the free grant
- M6 first connect (item 4, MINOR, accepted by the owner 23 Oct): a page opened during a 503
  says "This match could not be loaded" for good (no reopen before the first `meta`, and
  `/league` fails the page earlier anyway); a reload helps
- M6 tests (item 4 review, MINOR): `Server` in `tests/test_web.py` repeats `scripts/serving.py`'s
  start and stop; its restart binds the same ephemeral port again, which another process could
  take meanwhile (loud EADDRINUSE, never silent; retry the bind if it ever shows)
- M6 container (review 23 Oct, MINOR): the build backend (hatchling) is unpinned and comes from
  PyPI both in the image build and in `test_container`'s `uv build`, so CI fails offline or in a
  PyPI outage; GitHub CI installs the latest uv, the image pins 0.11.25; the image's wheel is
  built without `.gitignore` in the context, so an untracked file under `src/matchlens` that
  passes `.dockerignore` lands in the image (`container.sh` only: `deploy.sh` builds from `git
  archive HEAD` since item 3); the digest pins freeze the base image's security
  updates (refresh by hand before the deploy; whether `-bookworm` is still rebuilt since Debian
  12 went LTS is unchecked)
- tests: no test pins client-disconnect handling (Starlette cancels the stream through
  `listen_for_disconnect` under uvicorn's ASGI spec 2.3; checked by reading and by the verifier's
  cut streams); a direct ASGI test with a `http.disconnect` receive would pin it
- M3: a possession fact cites one flat tuple of both teams' spells (1 583–1 799 ids for a whole
  match, seeds 0–49), and an event that changes possession at the very moment a spell ends (a
  save parried out for a corner, the latest event of a live prefix) is in no spell, so no
  possession fact cites it. A zero count (e.g. 0 progressive passes, 0 pressing actions and its
  0.0 per minute in `facts_at`) is a fact without event ids
- M2: a save has no outcome, so possession cannot tell a held save from one parried out; a
  corner restart backdates the switch, but when the period ends before the corner is taken the
  keeper's team gets the 1–3 s to `period_end` (rare: the step that crosses the time limit must
  end in a save that goes out). A `save` outcome (held / out) would fix both this and the save
  that is in no spell
- deepening (owner decided 20 Oct, in session `18-plhack-06`: after the walking skeleton runs
  end to end): an `intended` field on failed passes. Until then a failed pass has no difficulty,
  because the event records where it ended, not whom it was meant for; rated at its end, an
  interception reads as the most pressure (seeds 0–19, in a draft that rated failed passes: 803
  of the 952 passes rated 60–79 were intercepted, and short loose balls looked easy)
- deepening (owner decided 20 Oct, in this session: sprint line 7.0 m/s now, the generator
  later): no outfield
  player runs faster than 6.5 m/s (`APPROACH_SPEED`; seeds 0–49: top speeds 6.10–6.63 m/s with
  frame rounding), so top speed hardly tells players apart and `sprint_tags` stay all but silent
  (seeds 0–49: 1 tag, a keeper diving for a save in match 45; `KEEPER_REACH` allows 8.55 m/s);
  per-player pace and sprints on runs for through balls and loose balls would give them
  meaning; re-measure the tag thresholds after, and decide then whether a sprint tag needs
  hysteresis or several frames above the line (centimetre rounding alone moves a 100 ms step by
  up to 0.14 m/s, so a steady run at the line would tag again and again)
- generator: a shot that lands within 0.3 s of its drawn speed (up to 9.6 m) gets the 300 ms
  minimum flight and reads slower, so the p80 behind `HARD_SHOT_MS` is a little low too:
  re-measure it after a fix. Seeds 0–49: 104 of 1 110 shots below 15 m/s (0.1–14.9 m/s, all
  ending within 4.5 m; 82 blocked, 12 saved, 6 goals, 4 off target)
- M3: `facts_at(clock)` has no tracking facts yet: distance and top speed up to a
  clock need one pass over the frames that writes cumulative checkpoints (say every second);
  `match_facts` spends about 4 s a match on its tracking pass (the MCP server computes a match's
  facts once). Sprint tags are no facts while the generator keeps them silent. `stats.speed`
  reads the 10 Hz `TrackingFrame`s; `pass_ratings` keeps the `Snapshot`s for arrival instants
  off the 100 ms grid; the match JSON and the API carry meta and events only, so the MCP server
  generates its matches from seeds. Ball speed and passing measure length on the centimetre grid
  in two ways (metres in `Event.ball_speed`, whole centimetres in `passing`); they agree on it (a
  test pins it), off-grid coordinates would differ by up to about 1.4 cm
- M3: a fact's `display` is the numeral as written (`52%`, `12.7`, `67:23`, `68'`, `3–2`, a shirt
  number `19`); the minute fact shows `68'` only, so `68th minute` needs the Guard's form rule.
  The score shows home first with an en dash (`3–2`): a model may write `3-2` or the winner first
- deepening (Analyst over MCP): `match_facts` still sends 0.143 MB for m7, as FastMCP repeats
  every fact as an indented text block next to the structured content; one object as the result
  would halve it. A first `match_facts` call computes for about 4 s in a thread, under a lock
- M4: the 0–100 difficulty is compressed (seeds 0–49: p90 52, max 71) and is no probability;
  show bands or a percentile, never a %. No "fastest player" ranking while outfield top speeds
  are the maximum of noise under one cap (6.10–6.63 m/s; the full-time card's ranking went with
  issue #7), and no ball speed for blocked or very
  short shots (300 ms minimum flight)
- generator: the busiest passers are forwards (m7: `slt-p18` 165 passes, `cor-p15` 156, both
  FW, and 0 progressive, as the most advanced player has nobody ahead), and 87–137 progressive
  passes per team and match look high (no reference measured); check the pass weights before
  M5 personas talk about playmakers or team totals go on screen
- M4: the chaos index of a 5-minute window stays within 32–65 (p10 43, p90 57; seeds 0–49) and
  a whole match within 47–52, so show bands from these percentiles, not the number; a window's
  momentum swings 0–100 % (p10 16, p90 83) on action weights of 7–54, so the overlay needs a
  minimum weight before it calls a team on top
- deepening: the momentum weights (shot 3, final-third pass 1, ball won high 1) and the chaos
  references are design choices, fitted to nothing but the medians; momentum counts a completed
  pass when it is played (the event carries its outcome), `facts_at`'s passing waits for its
  arrival; a momentum fact cites the counted actions of both teams
- generator: duels happen only where a defender reaches the holder (its odds: 68 % pressure,
  24 % tackle, the rest a foul or, in the box the holder attacks, mostly a lost tackle), so
  pressing (0.23–0.66 actions per team and minute, seeds 0–49) shows where the duels were, not a
  pressing plan; fouls do not count as pressing
- M3: in a last-five-minutes window `average_possession_length` and `chaos` span their counted
  spells whole (as possession does), so the span may start before the window while the value
  uses only the time inside it; `chaos` also uses the changes per minute of the window. Use the
  window span for `chaos` if the Guard needs it (review 21 Oct)
- tests (review 21 Oct, kept): in `test_flow.py` the mirror property's `control` check holds
  trivially (control reads no coordinates) and the empty-window property's control branch runs
  only when nobody had the ball; neither counts as coverage of those properties for `control`
- tests: possession's meaning is pinned by one hand-built example and structural properties;
  the verifier's independent owner-at-time model (all prefixes of 20 seeds) is not committed
- M4: the rolling possession window is a clock range of one period; early in period 2 it cannot
  reach back into period 1
- M2: the blocker of a shot and the interceptor of a pass are the nearest opponents, not checked
  to be on the ball's path, so a blocked shot can travel sideways; shot maps and directions must
  tolerate it, or the generator picks opponents on the line
- M4: during a restart pause the ball glides linearly to the restart spot in the tracking (after a
  goal, 30–50 s from the net to the centre); the overlay needs a dead-ball flag or the frames need a
  "ball out of play" marker. `stats.possession.spells` shows it only afterwards (a team-less spell
  that a restart ends); live, the overlay must read it from the latest event (out, off-target
  shot, goal, foul)
- tests: event ↔ frame agreement is asserted only at events on a 100 ms multiple (~1 %); for the
  rest the preceding frame's ball is 6 cm from the event start in the median, 45 cm at p95, 3 m
  max (verifier, seed 7). The CI suite took 191 s on 21 Oct after M2 item 4 (`scripts/ci.sh`, 607 tests; 159 s and 549 before); on
  19 Oct the 50-match fixture took 21 s and the tracking test 5 s
- harness, owner decided 20 Oct: `git push` is DENY in every Claude session (on 19 Oct the ASK
  did not stop `git push origin m1-ingest m0-harness` in an auto-mode session); the owner pushes
  from a terminal outside Claude. Not checked: whether the guard also runs in GitHub Actions; if
  it does, `@claude` cannot push a branch either. A string "git push" anywhere in a command is
  denied too (e.g. in a commit message or a grep pattern)
- harness: an ASK inside a subagent waits silently for the owner. On 20 Oct verifier round 1 of
  M2 item 2 waited 5 h 21 min (02:05–07:26 CEST, transcript gap) on a false positive: `cp` with
  `pyproject.toml` as the source. Fixed 20 Oct with the owner's OK: the guard checks only the
  destination of `cp`. Owner decided 20 Oct: no Notification hook for waiting prompts
- rung 8 (night loop) and Lean (rung 11): after the submission
- attest (owner's ship-gate kit): install at the start of M7 prep, at the latest Mon 26 Oct, with
  BUSINESS.md (purpose and non-goals, reusable in the pitch) and `/gate` before the first public
  push
- `claude-code-action` has a `use_foundry` input (Microsoft Foundry via OIDC): the GitHub Claude
  could run on our Foundry deployment, a point for "Best Use of Foundry"; needs an Azure OK (M3)
- M3 item 3, open (reviews and verifiers 21 Oct): the conftest guard blocks only
  `analyst.AnthropicFoundryClient`, not the network or the credential; a timed-out call records 0
  tokens though it may be billed; `anthropic` is imported directly but comes in through the pinned
  `agent-framework-anthropic` (not in `pyproject.toml`); INSTRUCTIONS are pinned by a sample of
  phrases; the outcome's `_` → space in a trigger line is unpinned (item 4's woodwork exercises
  it); Haiku at effort low wrote 923–1 238 output tokens (thinking) against Sonnet's 236
- M3 Guard, known limits (the Analyst prompt of item 3 must forbid what they let through): the
  Guard checks that a number is a cited display, not what the sentence says it counts
  (`Corrowmere have 1 shot` citing their 1 goal passes, as do two goal counts written `2, 1`);
  words that imply a number without being one pass (`the only goal`, "a minute
  later", "half an hour in"); `one`, `first` and `second` pass unless a counted noun follows
  (one word like `more`, `clear`, `league` may come between); `once` passes unless a counting word
  comes before it ("shot once", "missed once" pass); `the back four` reads as a line before any
  noun outside a fixed list ("their back four clearances" passes); `first half of his shots`
  passes; a name that starts a sentence is
  checked only against the league's other clubs and players, a lower-case one only against the
  league's, so an invented or real name there passes (a test pins it); words without a numeral
  that compare or judge numbers pass ("more of the ball", "up from", "on top", "despite only",
  "clean sheet", "take the lead"; the item 3 prompt bans them by quoted lists); a score is accepted only
  in display order (home–away); number words and fixed phrases are English only, M5's other
  languages need their own lists. Real false rejections a prompt should avoid: "after 13
  minutes", "79 percent", formations ("4-4-2"), "11 v 11", capitalized words after a colon
  and the word `Mr`, "scored once Wierlo crossed", "a third man in the box", "the 2nd half", "a
  one-on-one chance", "half of the stadium", a possessive line ("Corrowmere's back four") or one
  with an adjective ("a deep back four", "the Corrowmere back four"), a
  line before a verb of the noun list ("the back four passes it out")
- M3 Guard, minor (review round 3, verifier round 4): a reason deduplicated by (code, token)
  names only the first claim with it; the stats-only label shows the team id ("possession cor
  52%"); a dash or quote that differs between claim and narrative gives `claim_not_in_text`;
  `quadruple save`, `scored a double`, `half the shots`, `a couple more` pass
- M3 item 7, open (verifiers and reviews 22–23 Oct): a tool that answered with an error (the
  model's wrong arguments, an unknown match) counts as transport like a dead server and feeds the
  breaker; tell the two apart if item 6 shows it. A `FatalCallError` on the second request
  drops the billed first one from the summary, and the budget's fail-closed `RuntimeError`
  leaves no `summary.json`: count such a stopped run by hand. `max_iterations` 2 is a second
  guard behind `max_function_calls` 1 (no test tells them apart). The `--fake` default of 40
  is pinned by the help text only. The real Foundry client with a tool, structured output and
  `tool_choice: none` on the second request is unverified until item 6's smoke run. AF logs
  "Could not cleanly close MCP exit stack" when the server is gone
- M3 item 6 (from item 5's review, 22 Oct): a run counts only with `skipped == 0` in its
  summary (an open breaker or a spent `--max-calls` makes the rest stats-only, and those moments
  lower both pass rates; the CLI warns on stderr). Estimate, not measured: back-to-back calls
  run near 50 000 TPM (Sonnet ~77 500 tokens/min from one call), so 429s are plausible; the
  breaker counts timeout, 429 and transport alike and stays open for the run. The SDK retries
  nothing since 23 Oct, so a 429 is a failed attempt at once. A 17-moment match can need 51 calls, more than the default
  40: set `--max-calls` per run (required since item 7 for a run that calls a model). It counts
  model requests, two per attempt with `--mcp`. Check that the run closes the aio Entra credential and the SDK client
  (no unclosed-session warnings)
- M3 item 5, open (verifiers and review 22 Oct): the Guard → Analyst edge condition is
  redundant (the Guard sends only open cases); the summary's arithmetic has examples, no
  property; `MAX_ATTEMPTS` = 3 is pinned through the tests' scripts of length 3 only; `echo`
  parses `moment_prompt`'s text (a format change fails loudly with `ScriptExhausted`); a
  pipeline bug (facts not the engine's) ends in a traceback without `summary.json`
- M3 item 4, open (verifiers and review 22 Oct): `detect` recomputes `facts_at` for every moment
  ended by `until` on each call, so a live loop that re-detects on every event (M4) does
  quadratic work: cache cases by `moment_id` or add a `since` cut. Generated moments never
  overlap (seeds 0–19: at least 5 242 ms from one moment's end to the next shot), so the order by
  end, its tie-break and the prefix filter of the events are pinned by no test; a hand-built
  match with a goal inside a woodwork's flight would pin them. No test pins the facts' order
  across processes (a digest of m7's cases would). `facts.brief` has examples, no property
- M5 item 3, open (verifier and review 23 Oct, all MINOR): the three cue invariants and the
  phrase test run over cues without a run, so a run's fan moment renditions pass them only
  through the Guard's re-check at replay (the fake's fan draft cites no reading); the e2e test
  serves no run and switches only after the end (one card in the lower third), so a re-render of
  only the first shared card or a "Fan view" card in the browser is pinned by no test (checked by
  hand mid-stream); a switch closes open "verified" chips; `?persona=xyz` reads as analyst but
  stays in the URL until a click; `aria-live` on the lower third re-announces its cards on a
  switch

## Backlog by milestone
Each milestone gets a plan the owner approves; then items run through `/ship` one by one.

### M0 Harness + Azure inventory: approved by owner, 18 Oct (the brief) · branch `m0-harness` · done
Done items keep one line and their commits; the details are in the commit messages.
- [x] Rungs 0–4, 6, 9 (18 Oct): CLAUDE.md `1cd51cb`; Stop hook `3449c22`, since 21 Oct only the
  tests of the changed files, owner OK `5e771c7` (measured 173 s → 0.7–45 s); guard, format hook,
  verifier, code-reviewer, simplifier, `/ship`, local CI judge `287595e`, `8cc5577`; Hypothesis
  `ci` profile `e6a0d2d`, `1a3c811`; GitHub CI `f653e05`
- [x] Rungs 5 (worktrees) and 7 (Claude on GitHub), 19 Oct, owner OK: `b4cf9fa`, `11348d3`.
  `claude-review.yml` is untested until the first PR
- [x] Azure (inventory 18 Oct, resources 19 Oct with the owner's OK): Pay-As-You-Go, billing in EUR,
  a subscription budget with a forecast alert; the subscription's other resource groups untouched.
  Ours, swedencentral, tags `project=matchlens owner=radoz expires=2026-11-30`: RG `rg-matchlens`,
  Foundry `aif-matchlens` (AIServices S0, system identity) with project `matchlens`
  (`https://aif-matchlens.services.ai.azure.com/api/projects/matchlens`), a quarterly budget for the
  project (alerts at 50, 80 and 100 %). `Microsoft.SaaS` registered 21 Oct 16:03 CEST (M3 session,
  owner OK). Model deployments: see M3. Approved for M6, each with its own OK: Log Analytics, ACA
  Consumption (0.25 vCPU / 0.5 GiB), managed identity to Foundry, ACR Basic

### M1 Ingest: approved by owner, 19 Oct · branch `m1-ingest` · done
Dependencies `fastapi`, `uvicorn`; dev `httpx2` instead of `httpx` (owner OK 19 Oct).
- [x] League: Meridian League, 4 fictional clubs × 18 players, real-name denylist test `9827e55`
- [x] Event schema: `Event`, `TrackingFrame` (10 Hz), `MatchMeta`, ids `m7-e00042` and
  `m7-f048346`, `display_clock` `fa8d188`
- [x] Seeded generator, `Match` with lazy frames, `validate_match`; no cards, substitutions, own
  goals or offside `6107da4`
- [x] SSE stream `GET /matches/{id}/events`: speed, `Last-Event-ID` resume, emit timestamps,
  heartbeat, 204 after the end `d8ae0da`
- [x] CLI `matchlens generate` and `matchlens serve` `dcd819f`

### M2 Interpret: approved by owner, 19 Oct · branch `m2-interpret` · thin done 21 Oct
Owner in chat 19 Oct 22:33: "I agree with M2" (translated from Slovak). Pure functions in
`matchlens.stats`: no I/O, never an LLM; every computation works on any prefix of the event stream
and has at least one Hypothesis property; every value carries its event ids, a tracking value its
frame ids (owner decided 20 Oct). Dependency `mcp` (item 5).
- [x] Possession: spells (new event type `recovery`), shares per match, period and window `49a805f`
- [x] Pass quality: rating and difficulty 0–100 per pass, stats per player and team `ca58736`
- [x] Speed and distance: ball and shot speed, distance, top speed, sprint tags (7.0 m/s, owner
  decided) and hard-shot tags (28 m/s) `71921c1`
- [x] Facts with provenance + MCP server: `Fact` (`fact_id`, `display`, `source`),
  `match_facts`, `player_facts`, `facts_at`, `fact_evidence`, stdio and streamable HTTP `a6cd3d4`
- [x] Pressing, momentum, control vs chaos (`stats.flow`; "possession changes"; a typical match
  has chaos 50) and their facts `b54a1d0`
Not in M2: expected threat, formations, set-piece analysis.

### M3 Explain: approved by owner, 20 Oct · branch `m3-explain`
Owner in chat 20 Oct, shortly before 21:27: "I agree, as you recommend" (translated from Slovak)
(the plan drafted in session `18-plhack-06`, every recommended option; item list below written from
it). Thin first: Moment Detector → Analyst → Guard as a Microsoft Agent Framework workflow
(`WorkflowBuilder`, three `Executor`s, conditional edges). Only the Analyst calls a model; Detector
and Guard are deterministic. Agents never compute numbers: every number in a narrative is the
`display` of a Fact, and every claim cites fact ids and event ids (frame ids for a tracking value).
- Moment Detector (no LLM): reads the event prefix and the stats engine's facts; returns a
  `MomentCase` (trigger ids, clock range, display minute, the moment's facts). Thin triggers: goal,
  saved shot, woodwork; seeds 0–19 give 11.25 per match (2.4 + 8.3 + 0.55, counted 20 Oct)
- Analyst (LLM): reads the `MomentCase` (fact ids and displays) and the reasons a previous attempt
  was rejected; returns a `Draft` (text and claims `{text, fact_ids, event_ids}`) as structured
  output. Claude Sonnet 5.5 for measured runs and the demo, Haiku 5.5 for development (env
  `MATCHLENS_ANALYST_DEPLOYMENT`), effort low
- Guard (no LLM): looks the cited fact ids up in the stats engine itself (never trusts the
  Analyst's copies); returns pass or reject with machine-readable reasons (code, token, claim).
  Every numeral (integer, decimal, %, `67:23`, `45+2`, `68'`, `68th`, a score `2–1`) equals the
  `display` of a fact its claim cites; number words (`two`, `twice`) are rejected; cited fact ids
  exist; event and frame ids exist in the match and belong to a cited fact or to the moment's
  triggers; every claim cites an event id; no number outside a claim; player and club names come
  only from the match's lineups
- Shared state: `MomentCase` (frozen, JSON): run, match and moment ids, triggers, period and clock
  range, display clock, facts, attempts `{n, draft, verdict, reasons, model, tokens, latency_ms}`,
  outcome `narrative | stats_only`. Every handoff (Detector → Analyst, Analyst → Guard, Guard →
  Analyst, Guard → output) appends `{ts, from, to, moment_id, attempt, state}` with the whole state
  to `runs/<match>/<run_id>/handoffs.jsonl` (gitignored)
- Failure recovery: a rejected draft goes back to the Analyst with the reasons, at most 2 times,
  then a stats-only cue built from facts only (it passes the Guard by construction). A timeout, a
  429 after the SDK's retries, a refusal or invalid JSON counts as a failed attempt with a reason;
  after 3 transport errors in a row the run skips the Analyst (circuit breaker). `--max-calls`
  caps model calls per run (default 40), as Azure budgets only alert
- Tests: CI never calls a model. A `FakeChatClient(BaseChatClient)` replays scripted replies; the
  real client comes only from a factory that reads `MATCHLENS_FOUNDRY_RESOURCE`, and an autouse
  fixture makes that factory raise in tests. Mutation testing for the Guard
- Owner decisions 20 Oct: rung 10 (TLA+) no: the invariant "nothing leaves without a verified
  source" is a Hypothesis property over the workflow (revisit only with 2–3 h to spare after M4
  thin). Shirt numbers (source: the league) and the display minute (from `events.display_clock`;
  football counts upwards, 67:23 is the 68th minute; forms `67:23`, `68'`, `68th minute`) are
  Facts of M2 item 5, so the Guard has one source. Agreed with `18-plhack-84` 20 Oct for item 5:
  a `Fact` carries `fact_id` (stable, citable), `display` (one rounded string) and `source`
  (engine, league or clock); item 5 adds `Match.frame_at(period, clock_ms)`, so the Guard can
  check a tracking fact's frames; `mcp>=1.24,<2`, which fits AF's pin. Entra ID only (`AzureCliCredential` locally, managed identity in M6), no API
  keys. Only the Analyst is an LLM agent in the thin slice; M5 adds LLM agents (persona,
  translation, Recap) behind the Guard
- Branch: `m3-explain` from `m2-interpret`, in its own milestone worktree
  `.claude/worktrees/m3-explain` while M2 holds the main tree; `/ship` merges where `<base>` is
  checked out (harness change, owner OK 20 Oct). `m2-interpret` is merged into `m3-explain` when
  item 5 lands
- New dependencies (PyPI checked 20 Oct): `agent-framework-core==1.22.0`,
  `agent-framework-anthropic==1.0.0b261015` (beta, pinned exactly: `AnthropicFoundryClient`, pulls
  `anthropic` 1.x on `httpx2`), `azure-identity==1.26.0`. Not `agent-framework` (meta package, 30+
  packages incl. `mcp<2`), `agent-framework-azure-ai` (stale rc6), `agent-framework-foundry`,
  `azure-ai-projects`. If the beta breaks: an own thin chat client over
  `anthropic.AsyncAnthropicFoundry` inside AF core. AF's `all` extra pins `mcp>=1.24,<2`
- Foundry deployments, **stop point (separate OK)**: `claude-sonnet-5-5` v2 and `claude-haiku-5-5`
  v2, Global Standard, capacity 50 each (1 unit = 1 RPM + 1 000 TPM; quota 80 each, 0 used, 20 Oct).
  Foundry bills Claude through the Marketplace at Anthropic's list prices: Sonnet 5.5 $2 / $10,
  Haiku 5.5 $0.10 / $0.50 per million tokens in / out. Estimate, not measured (3 000 tokens in and
  500–2 000 out per call ±100 %, 1–3 attempts per moment): $0.10–1.10 per match on Sonnet,
  $0.01–0.06 on Haiku, $3–23 for all of M3. The first run's logged tokens replace it. Created 21 Oct
  (owner OK 21 Oct): Haiku 16:24:42 CEST by session `18-plhack-5f` with `NoAutoUpgrade`, then PUT
  again by the M3 session (setting kept); Sonnet 16:29:44 by the M3 session with the default
  `OnceNewDefaultVersionAvailable` (ARM `systemData`), set to `NoAutoUpgrade` 21 Oct 22:56:47 CEST
  by `az rest` PUT with the creation body plus `versionUpgradeOption` (approved by owner, 21 Oct);
  `deployment show` confirms it, sku, capacity and model version unchanged. 50 RPM and 50 000 TPM
  each. `Microsoft.SaaS` registered first. An Anthropic deployment needs
  `properties.modelProviderData` (`organizationName`, `countryCode`, `industry`; the owner's
  organization, country and industry; the RP signs the Marketplace offer with them), for which az
  CLI 2.91.0 has no flag: created with `az rest` PUT on
  `.../accounts/aif-matchlens/deployments/<name>`, api-version `2025-10-01-preview`. Client:
  `resource="aif-matchlens"` (the SDK builds
  `https://aif-matchlens.services.ai.azure.com/anthropic/`), token scope
  `https://ai.azure.com/.default`; the owner's subscription-wide Foundry User role sufficed; no
  client errors. AF sends `response_format` as `output_config.format` and passes an `output_config`
  option (`effort`) through; usage arrives in `usage_details`
- [x] Spike + contracts: the dependencies above; `matchlens.explain.state` (`MomentCase`, `Draft`,
  `Claim`, `Verdict`); the JSONL handoff log; `FakeChatClient`. An AF workflow of three executors
  runs on the fake; AF's MCP client against the `mcp` version of M2 item 5. Properties:
  `MomentCase` JSON round trip; one log line per handoff.
  Done 20 Oct: the three pins locked (22 new packages, no locked version changed). `explain.state`
  also has `Reason`, `Attempt`, `CallFailure` (`CallError`: timeout, rate_limited, transport,
  refusal, invalid_reply, skipped = no call made), `MomentOutcome` and `MAX_ATTEMPTS` (3). A
  `Claim` cites `fact_ids`, `event_ids` and `frame_ids`. Construction refuses a narrative whose
  last attempt did not pass, an attempt on a closed case, a failed attempt that passes, a reason
  pointing at a claim the draft lacks, triggers that are not events of the match, a display clock
  that is not `events.display_clock` at `end_ms`, facts without a unique `fact_id` and a `display`
  or not strict JSON (stored as normalized copies), and wrong types (sequences become tuples, a
  bool is no int); `MomentCase.narrative` is the passed draft or None, so Render never takes a
  rejected text. `explain.log`: `HandoffLog` and `read_handoffs` check the route and the case's
  phase on writing and on reading (fresh → Analyst, drafted → Guard, rejected with a retry left →
  Analyst, closed → Render); one ASCII, strict-JSON line per handoff with schema version `v` 1, UTC;
  a reading error names its line. `FakeChatClient` has the function-invocation and chat-middleware
  layers of the real client, counts characters as tokens and raises `ScriptExhausted` (an
  `AssertionError`) when the script runs out. A real AF `WorkflowBuilder` with stand-in executors
  and a Guard → Analyst edge runs a pass, retries with the reasons and stats-only on the fake,
  catching `ChatClientException` as the real client raises it (`tests/test_explain_af.py`). MCP,
  scratch only: AF's `MCPStdioTool` listed and called the one tool of a FastMCP stdio server, with
  `uv run --isolated --no-project --python 3.12 --with mcp==1.30.0 --with
  agent-framework-core==1.22.0` (item 5's range); item 5's real MCP client run supersedes it
- [x] Guard: the rules above. Properties: a narrative made of cited displays passes; changing any
  number to a value no cited fact displays is rejected and the reason names it; a foreign fact,
  event or frame id is rejected; claim order and repeated runs do not change the verdict; never
  raises on arbitrary text; a stats-only cue always passes. Mutation testing.
  Done 21 Oct: `explain.guard`: `check(draft, case, evidence)` and `judge(case, evidence)` (the
  last attempt; a failed one gets `no_draft`), `moment_evidence(match, case)` (the engine's
  `facts_at` the moment's end, its events up to then, frames through `Match.frame_at`, the name
  words of the two lineups and clubs, the league's other names; a case whose facts are not the
  engine's raises: a pipeline bug, no draft to judge), `stats_only_draft(case, evidence)` (minute,
  score and possession so far from the engine, each a claim with the triggers), `numerals` and
  `ordinal`. `Reason.code` is a `ReasonCode` (15 codes). A numeral counts as inside a claim only
  when its whole span lies within an occurrence of the claim's text; a unit word must follow its
  number, a shirt number needs `No.`/`number`/`#`/`shirt` before it, a last-5 fact needs "last 5
  minutes" in its claim; two numbers joined by a dash, slash, colon or "to" read as one score;
  numbers in words (incl. `nil`, `brace`, `only once`, `half of` but not `first half of`, `first
  goal`, `one more shot`, `dozens`), numeric characters other than 0-9, other numeral forms and
  drafts over 1 000 characters or 12 claims are refused; fixed phrases (`six-yard box`,
  `one-two`, `50-50`/`50/50 ball`, `final third`, `triple save`, `the back four` and `the front
  three` after a determiner and before no counted noun, `a third-man run`) are no claims. A retry
  hint says what a fact showing the number counts and allows citing it only if the sentence
  states exactly that. Red rounds 3 of 3: review round 1 (6 SERIOUS: claims blanked by `str.replace` let numbers pass and
  made the verdict order-dependent, a real player name in a test, number words, names after
  `No.`, the last-5 window, shirt numbers) and round 2 (2 SERIOUS: `50-50` blanked anywhere, a
  hint that coached citing any fact with the same number), all fixed; round 3 (1 SERIOUS, N3):
  the stop point, lifted by the owner 21 Oct; round 4 fixed N3 and the minors, verifier PASS
  twice, review without SERIOUS. Mutation testing
  (verifier, round 2 code): 664 mutants of `guard.py`, 426 killed; of the 238 survivors 57
  equivalent, 38 message-only, 143 untested behaviour, which the round 3 tests target (13 of
  them rerun: all killed); round 3 code: 812 mutants, 624 killed (76.8 %), of the 188 survivors
  43 equivalent, 45 message-only, 100 untested behaviour; final code: 958 mutants, 782 killed
  (81.6 %), survivors not classified (Metrics). Every display of the engine reads as itself
  (seeds 0–4, 6 303 facts of `match_facts` and of `facts_at` at goals, saves and every 100th
  event). Properties also ran with 3 000 examples each (459 Guard tests). Real run, seeds 0–4:
  all 50 goals and saves get a stats-only cue that
  passes, and the same cue with the score off by one is refused (`number_not_cited`, 50 of 50)
- [x] Analyst: an AF `Agent` over `AnthropicFoundryClient` (Entra token provider), structured
  output `Draft`, prompt with fact ids and displays and the previous attempt's reasons. Tests on
  the fake client only.
  Done 21 Oct: `explain.analyst`: `Analyst(client, match).attempt(case)` returns the next
  `Attempt` (draft, or a `CallFailure`; model, tokens, latency) and refuses before the call a
  closed case, one with `MAX_ATTEMPTS` attempts or an unjudged last attempt. `moment_prompt`:
  clubs, lineups, trigger events with the shot outcome, every fact as `id | write as | what it
  counts | window` (`No. 19`, `68' or 68th minute`, `15.1 s`; "last 5 minutes"), earlier
  attempts with their claims and reasons tagged `[claim i]`; no period number. INSTRUCTIONS state
  the Guard's rules and limits (1 000 characters, 12 claims) and ban by quoted lists what its
  known limits let through: number and ordinal words, count-implying words, the score or a
  comparison of numbers in words, time words without the clock, details the triggers do not give.
  Structured output `DRAFT_SCHEMA` (pinned against `Draft`), effort low, `max_tokens` 4 000.
  Failures: refusal (`content_filter`) → `refusal`; cut off (`length`), bad JSON or no `Draft` →
  `invalid_reply`; `asyncio.timeout` 240 s or SDK `APITimeoutError` → `timeout`;
  `RateLimitError` after the SDK's 2 retries (none since 23 Oct, item 7) → `rate_limited`; every other client error →
  `transport` (the SDK error is found through `__cause__`). `foundry_client(deployment)`:
  `MATCHLENS_FOUNDRY_RESOURCE`, deployment from the argument, `MATCHLENS_ANALYST_DEPLOYMENT` or
  Haiku, `AsyncAnthropicFoundry` with request timeout 60 s and 2 retries, Entra token from
  `azure.identity.aio` (scope `https://ai.azure.com/.default`); a session autouse fixture makes it
  raise in tests. `FakeChatClient` replays whole `ChatResponse`s too. Tests: 35 collected (23
  functions), 3 Hypothesis properties (any draft round-trips; any reply gives a draft or the reason; the prompt
  carries every fact line, trigger, name and earlier reason), the real Foundry client over a mock
  transport (URL, bearer token, `output_config`, every error code, a 429 retried twice), every
  "write as" form passing the Guard on all goals and saves of seeds 0 and 7. Red rounds 2 of 3
  (review: the prompt let through score words, bare ordinals and "period 1", then comparisons in
  words); verifier PASS three times. Real runs in Metrics (before the last prompt changes)
- [x] Moment Detector: goal, saved shot and woodwork on any event prefix; the moment's facts incl.
  display minute and shirt numbers. Properties: deterministic; triggers lie in the prefix; a
  prefix yields the full stream's moments that end inside it.
  Done 22 Oct: `explain.detector.detect(match, run_id, until=None)`: a goal or a save with its
  shot (`related`) → triggers (shot, goal | save); a shot with outcome woodwork → (shot,). A
  moment runs from the shot's clock to the ball's arrival (the goal or save event, which the
  generator puts at shot clock + `duration_ms`, 0 exceptions in seeds 0–19; for woodwork shot
  clock + `duration_ms`), is returned once it has ended by `until` (period, clock_ms; default the
  latest event; a list is accepted), in the order the moments end. `moment_id` names the shot
  (`m7-k00072` for `m7-e00072`), so ids hold across prefixes. Facts: `facts_at` the end, stored as
  `facts.brief` (no id lists, `event_count` / `frame_count`; moved from `mcp._brief`, which now
  calls it): a case is about 15 kB of JSON instead of up to 150 kB with the lists, and the log
  writes the whole case at every handoff. A goal or save whose shot is missing raises ValueError.
  Tests: 22 collected (18 functions), 4 Hypothesis properties (prefix = the full match's moments
  ending inside it; reads only the prefix; triggers lie in the prefix; deterministic + JSON round
  trip), `until` drawn anywhere or on a moment's start or end ±1 ms, `facts_at` memoized for
  speed (one example runs the real one on a cut match); boundaries of a goal and a woodwork both sides, counts by kind
  against the events, m7 pinned, facts = the engine's incl. minute and 22 shirt numbers. Red
  rounds 0: verifier PASS twice (CI 1 276 passed; 40 targeted mutants, 35 killed, 5
  equivalent; an own oracle over seeds 0–19: 225 moments, 1 650 prefix instants, every case
  accepted by `moment_evidence` and its stats-only cue passes); review without SERIOUS, its cheap
  MINOR fixed, the rest in Follow-ups. Real run in Metrics
- [x] Workflow + recovery: Detector → Analyst → Guard; reject → retry with reasons (max 2) →
  stats-only cue; transport errors, refusals and invalid JSON count as attempts; circuit breaker;
  `--max-calls`. CLI `matchlens explain <match> [--until 45:00] [--fake]` writes the log and a run
  summary (pass rates, attempts, tokens, cost, p50 / p95 latency per moment). Properties: at most 3
  attempts; the outcome is a passed narrative or stats-only; a log line for every transition.
  Done 22 Oct: `explain.workflow.explain(match, client, log, run_id, until, max_calls)`: AF
  `WorkflowBuilder`, executors Detector / Analyst / Guard, Guard → Analyst edge on `is_open`.
  AF delivers one sender's messages in order, so calls come in rounds (every first attempt, then
  the retries), each in moment order. The Detector checks every case against the engine
  (`moment_evidence`) before the first call and hands the evidence to the Guard; only the Guard
  calls `with_verdict` (an AST test). `CallBudget`: no call after 3 calls in a row without an
  answer (timeout, 429, transport; an answer resets it) or once `max_calls` (default 40) are
  spent; such an attempt is `skipped` and its moment stats-only at once. The stats-only cue is
  checked by the Guard (a failing one stops the run). Fatal (`analyst.FatalCallError`): an Entra
  `ClientAuthenticationError` or a 4xx other than 408/409/429 anywhere in the cause chain stops
  the run; two expectations of an existing test (400 and 401 → `transport`) moved into the fatal
  test (the owner's Follow-up). `FakeChatClient` takes a function of the request text;
  `fake.by_moment` keys replies by moment and attempt, `fake.echo` is the `--fake` Analyst (the
  score fact and the first trigger). `explain.summary`: `check_chain` (the Detector sends first,
  each receiver sends next, identity fixed, the Analyst adds one attempt, the Guard only its
  verdict, nothing after Render; a broken chain raises, a chain without Render is `crashed`),
  `summarize` → moments, narratives, stats-only, crashed, first-attempt and final pass rate,
  attempts, model calls, skipped, errors and reasons by code, tokens, cost at list price, p50 /
  p95 nearest rank of a moment's summed attempt latencies. CLI: `matchlens explain m7 [--until
  45:00] [--fake | --deployment …] [--max-calls N] [--runs runs]` → `runs/<match>/<run_id>/`
  (`run_id` UTC to the ms) `handoffs.jsonl` and `summary.json`; `--until` is the exact inverse
  of `display_clock` (`45:00` = the second half's kick-off); exit 1 on a fatal stop or a moment
  left without a cue. Tests: 30 in `test_explain_workflow.py` and `test_explain_summary.py` (27
  functions), 18 new functions in `test_cli.py`, `test_explain_fake.py`,
  `test_explain_analyst.py`; properties: the workflow against an independent simulation of the
  recovery policy over random reply scripts × `max_calls` 0–10 (≤ 3 attempts, the outcome a
  passed narrative or a stats-only cue that passes, one log line per transition, every chain
  valid, the summary's counts), the budget over any call sequence, `clock` round trip. Red
  rounds 0: verifier PASS twice (CI 1 362 and 1 365 passed; 56 and 72 targeted mutants, 49 and
  65 killed, the rest equivalent or gaps since pinned; independent recounts of real `--fake`
  logs); review without SERIOUS, its cheap MINOR fixed, the rest in Follow-ups. Real runs in
  Metrics
- [x] Foundry run (stop point): the 2 deployments after the owner's OK; seeds 0–4 per model; Guard
  pass rate, tokens, cost and latency into Metrics. Owner OK 22 Oct: at most 340 model calls, 170
  per model, after item 7 (approved by owner, 22 Oct); plan of 22 Oct: a smoke run of 1 moment per
  model, then seeds 0, 1, 3 over MCP, `--max-calls` per run at its worst case (Metrics: Analyst on
  Foundry over MCP, measured). A run that must be repeated gets `--max-calls` = 170 minus the
  requests that model has spent (summaries, a stopped run counted from its `handoffs.jsonl`); if
  that is below its worst case, ask the owner. Smoke run done 23 Oct 09:35 (Metrics). From it: about
  11.8k tokens per attempt, so back to back Sonnet would run about 136k and Haiku 57k tokens a
  minute against the 50 000 TPM of each deployment, and with no SDK retries a 429 is a failed
  attempt: `--pace` (seconds between attempt starts) added for the measured runs, which use `--pace
  35` (review: at 25 s three starts fit into one minute, about 58k tokens if the limiter also
  reserves `max_tokens`; an estimate, the limiter's window is not known). `summary.json` records the
  run's settings. Done 23 Oct 10:00–10:35 CEST: 6 runs (Haiku, then Sonnet; m0, m1, m3 with
  `--max-calls` 72, 42, 54), every moment a narrative on attempt 1, no 429, no skip; logs in `runs/`
  (gitignored). Results in Metrics
- [x] Analyst reads facts over MCP (required, not a deepening item: owner decided 21 Oct, for the
  multi-agent category): `MCPStreamableHTTPTool` against `matchlens mcp --http`; the Guard still
  looks every cited fact up in the engine itself. Done 23 Oct: `explain(..., facts_url)` /
  `matchlens explain … --mcp URL` opens `MCPStreamableHTTPTool(allowed_tools=["facts_at"],
  request_timeout=10 s)` and checks with `list_matches` that the server serves the match (else
  `FactsUnavailable`, exit 1, no call). `Analyst(facts_tool=…)`: the prompt lists no facts, says to
  call `facts_at` once with the moment's match_id, period and clock_ms, gives the write-as, window
  and what-it-counts rules for tool facts and the ids of clubs and players; the tool loop is capped
  at 1 call and `MAX_REQUESTS` 2 model requests (`max_function_calls` 1, `max_iterations` 2;
  measured: a model that keeps calling gets 2 requests and an invalid reply); a chat middleware
  counts each request and sums the tokens of each answered one (`Attempt.requests`, log schema v2);
  the draft is the last message's text; a failed tool (a raised `ToolException` or an error result)
  is a transport failure. `CallBudget(max_calls, per_attempt)`: an attempt starts only when its
  worst case fits, and one that made more requests stops the run; a run that calls a model needs
  `--max-calls`; the SDK retries nothing (`MAX_RETRIES` 0, request timeout 120 s, attempt 300 s;
  owner 23 Oct). `summary.model_requests`; `fake.echo` calls the tool first when told to. Tests: 18
  in `test_explain_mcp.py` against a real FastMCP streamable HTTP server in a thread (one tool, the
  moment's facts reach request 2, the cap, lost tokens kept, a dying server: 3 transport failures,
  breaker, the run finishes), `requests` in the round-trip strategy, the budget property over
  requests per attempt, `model_requests` in the workflow property. Red rounds 3 of 3, the stop
  point, lifted by the owner 23 Oct (Owner decisions outside the milestone plans); simplifier once,
  before the review fixes; verifiers PASS after each fix (CI 1 393 passed). Real runs in Metrics
Not in M3 thin: personas, languages and Recap (M5), overlay and live SSE (M4).

### M4 Render: approved by owner, 21 Oct · branch `m4-render`
Owner in chat 21 Oct, 16:01 CEST: "approved" (the plan drafted in session `18-plhack-dc [32e982]`).
Thin first: one web page served by our app, a 2D pitch replaying a match from a live SSE stream
with timed overlay cues. Cues come from the stats engine's facts (items 1–4) and from M3's moments
(item 5: stats-only cues after M3 item 4, Guard-passed narratives after M3 item 5), so M4 does not
wait for the Analyst. Not a stub: judges score "a balanced blend of frontend and backend" (20 %).
- Stack: plain HTML/JS/SVG in `src/matchlens/web/`, served by FastAPI `StaticFiles` (Starlette,
  already installed). No build step, no npm, no CDN, no external fonts (no third-party marks in
  the video). Kit colours from `league.json`
- Gap found while planning: `/matches/{id}/events` carries events only, no tracking; the pitch
  needs positions, so item 2 adds frames to a new stream
- Branch: `m4-render` from `m2-interpret` (`b54a1d0`, M2 thin complete) in its own worktree
  `.claude/worktrees/m4-render`. `m3-explain` is merged into `m4-render` (one way only, for item
  5); `m4-render` is never merged into `m3-explain`. Expected conflicts: `PROGRESS.md`, `uv.lock`
  (regenerate with `uv lock`). Into `main`: `m2-interpret`, then `m3-explain`, then `m4-render`
  (owner merges)
- New dependencies (PyPI checked 21 Oct): dev `playwright==1.64.0` (pulls `pyee`, `greenlet`), no
  `pytest-playwright` (an own fixture); Chromium via `playwright install chromium` (download
  outside PyPI). GitHub CI needs a browser install step in `.github/workflows/ci.yml` (harness
  change, announced; the e2e test is not skipped)
- Hours per item are estimates (±50 %). Measured calibration: M2/M3 items took 2.4–15.6 h wall
  clock between commits (median 7.4 h, nights and red rounds included). Target: items 1–4 (M4
  thin) done Fri 23 Oct evening; item 5 when M3 item 4 lands, at the latest Sat 24 morning
- [x] Cue timeline (3–4 h), done 21 Oct. Deviations: no sprint cue (no sprint fact exists), no
  distance at full time (its `frame_ids` span the whole match), window header "Recent play to
  05:00" ("Last 5 minutes" carried a numeral that is no fact): `matchlens.render.cues`, `Cue` (frozen, JSON: `cue_id`, `due`
  (period, clock_ms), `kind`, `lines`, `fact_ids`, `event_ids`, `frame_ids`, `ttl_ms`, `anchor`);
  `cue_timeline(match)` picks deterministically from facts: goal (score, shot speed), shot on
  target and woodwork, end of a 5-minute window (momentum, chaos, pressing), half time and full
  time (possession, pass accuracy, distance), hard shot and sprint tags. Text is templates plus
  cited facts' `display` only. Properties: no numeral outside a cited fact's display; no future
  leak: every cited fact ends at or before `due` and equals the one `facts_at(due)` returns (pinned
  exactly on the boundary and 1 ms off); deterministic and sorted; every id exists. Real run:
  `matchlens cues --seed 7`, cues per match measured
- [x] Live stream (3 h), done 21 Oct: `/matches/{id}/live?speed&hz&last_event_id`, hz 1/2/5/10
  (default 5), merges `meta` (lineups, `hz`, `first_half_ms`), `frame` (`frame_id`, period,
  clock, `display_clock`, ball `[x, y]`, players `[[id, x, y]]` to the centimetre),
  `match_event` (as `/events`), `cue` (`Cue.to_dict()`, placed at its `due`, after the frames
  and events of that moment) and `end`; every message has an id (frame, event, cue id), resume
  after any (header or query), 204 after `end`. `stream.live_timeline`, `stream.live`, a shared
  `paced` (also under `/events`, whose tests are unchanged); `Match.frames(every_ms, start)`.
  Cue timelines once per match: queued in one worker thread at server start (lifespan), or on a
  `/live` request of a match not ready yet; a failed or cancelled one is computed again
- [x] Web page (5–7 h), done 22 Oct: `src/matchlens/web/` (`index.html`, `app.css`, `app.js`)
  under `/static`, `/` serves the page, new `/league` (clubs, kit colours, shirt numbers).
  `/?match=m7&speed=30` (optional `hz`); a speed switch reconnects with `last_event_id`; the away
  team wears its secondary colour when the primaries are close; only cards with a place (goal,
  chance) are clickable; an unknown match or a lost connection shows an error. The scoreboard
  tallies goal events (no own goals exist). Tests: TestClient (page, assets, no external URL,
  `/league`); e2e in headless Chromium against uvicorn on a free port, cold server, seed 7: 22
  players with numbers and kit colours, final positions = last frame, all 35 cards in order in
  rail and lower third, score, chip, highlight, interpolation, a 10→30→60 switch with a clock that
  never goes back, picker, unknown match; no console errors. Real run: `matchlens serve --seed 7
  --seed 8`, screenshots of m7 and m8 (verifier: 3–2 at 90+3:22, 35 cards). Plan was: `/` match picker; watch view with SVG pitch 105×68, players with shirt
  numbers (interpolated), ball, score, `display_clock`, speed 10× / 30× / 60×; cue cards (lower
  third + side rail) with a "verified" chip that expands to fact and event ids, a click highlights
  the event's location. Tests: TestClient (page, assets); one playwright e2e (uvicorn on a free
  port, seed 7: 22 players, at least N cards whose fact ids match `cue_timeline`, no console
  errors). Real run: a screenshot
- [x] Latency + recording (3 h), done 23 Oct: `app.js` stamps each cue into
  `window.matchlensLatency` (cue id, kind, trigger, `latency_ms`, `delivery_ms`); `matchlens.latency`
  (nearest-rank `percentile`, `summarize`; Hypothesis properties and boundaries both sides);
  `scripts/measure_latency.py`, `scripts/record_demo.py`, `scripts/serving.py` (uvicorn on a free
  port); `runs/` gitignored. The e2e test pins one stamp per cue in order and its trigger (the
  last cited event, else the cue). Numbers in Metrics. Red rounds 0 (verifier PASS).
  Plan was: the page stamps each cue: render time after the next
  `requestAnimationFrame` minus its trigger event's `emitted_at_ms`. `scripts/measure_latency.py`
  (headless, local, seeds 0–4, speed 20) → p50 / p95 / max / n into Metrics; a property for the
  percentile helper. `scripts/record_demo.py` → webm 1920×1080 in `runs/` (Playwright's own
  ffmpeg); length and size measured. Same machine's clock on both sides, so measured locally only;
  with precomputed cues it measures delivery and render, the timeline's compute time is measured
  apart
- [x] Moment cues from M3 (2–3 h, conditional, not part of "M4 thin done"), done 23 Oct:
  `matchlens.render.moments`: a `moment` cue (after the goal or chance it explains, 8 s) for every
  moment the Detector finds, with "Analyst · <club>" and the narrative of a run's Guard → render
  handoff if the Guard passes it again at replay, else "Key moment · <club>" and the stats-only
  text; `match_cues` (facts' cues + moments) in the app and `matchlens cues`; `--run DIR` on
  `serve` (repeatable) and `cues`, checked before serving (a run that does not fit the match
  exits 2; stderr says how many narratives show and how many the Guard refuses now); cues due
  together share the lower third. Property: random scripted Analyst replies through the real
  workflow → each cue's text is exactly what the workflow let out, no rejected text shows; the
  three cue invariants of `test_cues` now run over the moment cues too. Real runs: `matchlens
  serve --seed 7 --run` with M3's smoke run (Foundry, 23 Oct 09:36 CEST): the narrative shows next
  to the goal card; `matchlens cues --run` over M3's Foundry runs of m0, m1, m3 (Haiku 5.5 and
  Sonnet 5.5 each): 56 of 56 narratives pass the Guard again at replay. Red rounds 1 of 3 (review
  SERIOUS: a run that did not fit the match gave a traceback in `cues` and a 500 on every `/live`
  in `serve`; fixed by the check before serving, tested for both commands).
  Plan was: after M3 item 4 a `moment` cue from the stats-only draft; after M3 item 5 a Guard-passed narrative replayed from a
  finished run's `handoffs.jsonl` (live Analyst during replay is deepening). Property: the cue text
  equals the passed draft or the stats-only text exactly; rejected text never shows
Not in M4 thin: live Analyst calls during a replay, persona switch (M5), deployed latency (M6).

### M5 Personalize: approved by owner, 23 Oct · branch `m5-personalize`
The same verified intelligence reaches a data-hungry analyst and a casual fan as two different
experiences (rules 4.1(e)), with an automated recap (4.1(iii)); everything personalised passes the
Guard. Owner 23 Oct ~15:45 in chat: M5 thin as recommended in session `18-plhack-59`, item 1 first,
M6 in parallel. Owner 23 Oct ~16:05 in chat: "I approve M5" (translated from Slovak) for the plan
and the two points listed with it: the CLAUDE.md rule (numbers and judgement words come from the
engine; changed with this approval) and a cap of 170 model calls per model for all of M5's Foundry
runs together, as in M3 (approved by owner, 23 Oct). Runs within the cap need no further OK; each
run's size is said in chat before it starts. Owner 23 Oct ~20:15: the Sonnet 5.5 cap raised to 300
calls for all of M5 (approved by owner, 23 Oct; Claude's recommendation, so the demo runs both
languages on Sonnet; estimate +$2–3 ±50 %); Haiku stays at 170. Proposal of 21 Oct (Persona Editor
behind the Guard) kept; the Foundry deployments it waited for exist since 21 Oct.
- Why item 1 comes first: the narratives of 23 Oct report, they do not explain (rules 4.1(c):
  "explain why a moment matters rather than only reporting that it happened"), because the
  Analyst prompt bans every judgement word ("lead", "on top", "more of the ball") the Guard
  cannot verify. Readings fix that at the source: the stats engine decides the judgement,
  deterministically, from thresholds, and its `display` is the phrase; the Guard allows a phrase
  only inside a claim that cites a reading displaying it, exactly as it treats a numeral. The rule
  "every number comes from the engine" becomes "every number and every judgement word comes from
  the engine" (CLAUDE.md Rules, with the approval of this plan). Agents still compute nothing
- Readings (`stats/readings.py`, pure functions over the facts the engine already computes;
  emitted by `facts_at` and `match_facts` as facts whose `value` is the code, `display` the
  phrase, `unit` empty, `source` engine, with the ids of the facts they read; the thresholds are
  design choices, each pinned exactly on it and one unit off):
  `score_reading` per team at any clock from the goal difference: `in the lead` (> 0), `on
  level terms` (0), `chasing the game` (< 0); `goal_reading` for the scorer's team when a goal is at the clock exactly (a
  goal moment ends at its goal event: `detector.detect`, checked 23 Oct), from the difference
  before the goal: 0 → `take the lead`, −1 → `equalise`, ≥ 1 → `extend the lead`, ≤ −2 → `pull
  one back`; `momentum_reading` per team and scope (`to`, `last5`) when the scope's action weight
  is at least `MIN_WEIGHT` 10 (Follow-ups: weights 7–54, so a window of 2 shots calls nobody on
  top): ≥ 70 % `on top`, ≤ 30 % `pinned back`, else `evenly matched`, no reading below the
  weight; `chaos_reading` per scope from the windows' measured p90 and p10 (Metrics, Flow): ≥ 57
  `end-to-end`, ≤ 43 `patient build-up`, else `a steady tempo`; `possession_reading` per
  team and scope: ≥ 55 % `more of the ball`, ≤ 45 % `less of the ball`, else `an even share of
  the ball`. 16 phrases, chosen so that none is an ordinary word elsewhere in a caption;
  `VOCABULARY` (code → phrase) is the one list the engine, the Guard and the prompts share
- Guard: a vocabulary phrase in the text (word-bounded, case-insensitive) must lie inside a claim
  that cites a reading whose display is that phrase, else `PHRASE_OUTSIDE_CLAIM` or
  `PHRASE_NOT_CITED`; cited phrases are blanked before the numeral check (as `_PHRASES` are, so
  `pull one back` is no number word); a judgement word outside the vocabulary (`JUDGEMENT_WORD`:
  the prompt's lists of score states and flow judgements: `ahead`, `in front`, bare `lead`,
  `equaliser`, `opener`, `winner`, `comeback`, `all square`, `goalless`, `winning`, `losing`,
  `advantage`, `dominate`, `in control`, `on the front foot`, `chaotic`, `calm`, `outshoot`, and
  `more` / `fewer` / `less` / `most` within three words of `ball`, `possession`, `shots`, `passes`
  or `chances`) is rejected and the reason names it. The numeral rules are unchanged
- Personas: `analyst` is the Analyst's draft as it is (no call); `fan` is the Persona Editor's
  rendition; favourite club and player focus are render-side modes (item 5, no model); a club's
  voice ("we") and more personas are deepening
- Persona Editor (LLM, a 4th executor): reads the draft that passed, the facts it cites and the
  moment's readings (ids and "write as"), writes a `Draft` for the persona as structured output
  (1–2 short sentences, plain words, phrases over percentages, at most 2 numbers, the names as
  given, nothing the draft and the readings do not say), claims as the Analyst's. One request per
  attempt, no tool call. The Guard judges it with the same `check`; a rejection goes back once
  with the reasons (2 attempts per persona), then the rendition falls back to the Analyst's
  narrative, which passed (checked anyway). Workflow: Detector → Analyst → Guard →(open: retry)
  Analyst; Guard →(closed, a persona pending) Persona Editor → Guard; Guard →(nothing pending)
  output. The Guard dispatches on the case's stage and never trusts the Persona Editor's copies
- Recap Writer (LLM): after the last moment a `RecapCase` (run and match ids, `match_facts` with
  the readings at full time, the moments' ids and their passed narratives) → 3–5 sentences, at
  most 600 characters, claims citing match facts and the goals' event ids → the same Guard with
  the match's whole facts as evidence → 2 retries → fallback: a deterministic recap (score,
  scorers with minutes, possession, pass accuracy, chaos reading). Personas apply to the recap
  through the same Persona Editor. Out: a `recap` cue at full time, `GET /matches/{id}/recap`
  (the studio output: text, claims, fact and event ids per persona) and `matchlens recap`
- Shared state: `MomentCase.renditions` (persona, attempts, outcome, text), `RecapCase`; new
  log roles `persona_editor` and `recap_writer`; every handoff logged as today;
  `summary.json` per persona and for the recap (pass rates, attempts, tokens, cost, latency).
  `moment_cues` replays each rendition from the Guard → render handoff and judges it again
- Models and budget: one `--deployment` for every LLM agent of a run; Haiku 5.5 for development
  and smoke runs, Sonnet 5.5 for the measured runs and the demo (owner, 23 Oct); SDK retries 0;
  `--max-calls` counts every agent's requests, `--pace` spaces every model attempt. Estimate
  from M3's measurements (±100 %): item 1's re-run of seeds 0, 1, 3 on Sonnet 56–84 requests,
  $0.8–1.2; item 2's fan renditions 28–56 requests, $0.3–0.9 (a shorter prompt, no tool call);
  item 4 3–9 requests, $0.1. Every Foundry run is a stop point with the owner's cap, as in M3
- Dependencies: none new. Branch `m5-personalize` from `main` (`31f8699`) in
  `.claude/worktrees/m5-personalize`; `m6-deploy` runs in parallel in its own worktree and
  session; conflicts expected in PROGRESS.md only. Into `main`: `m5-personalize`, then
  `m6-deploy` (owner merges). The video (M7) replays the Sonnet runs of item 2
- Hours are estimates (±50 %; calibration: median 7.4 h wall clock per item in M2–M4). Targets:
  item 1 Fri 23 night; items 2–3 Sat 24; items 4–6 Sun 25; item 7 only if items 1–6 are done
  by Sun 25 evening; Mon 26 is M7. Scope change 23 Oct ~16:30 (approved by owner, 23 Oct):
  Slovak (item 6) is required, as the strongest entries seen on Innovation Studio speak several
  languages (23 Oct); item 5 is the favourite club only, player focus moved to item 7
- [x] Readings + Guard vocabulary, done 23 Oct (red rounds 2 of 3: review SERIOUS twice in
  round 1, a match-long reading's phrase passed in a claim about the last 5 minutes, and
  exceptions for false rejections opened "extend their lead to 3–1", "draw level with", "come
  from behind"; review SERIOUS in round 2, the exception "in behind" also let "remain behind"
  through; all fixed and verified). `stats/readings.py` (`VOCABULARY`, 16 phrases, thresholds pinned on
  both sides, mirror and monotonicity properties); readings in `facts_at`, `match_facts` and
  over MCP, checked by the facts oracles; the Guard's phrase rule (claim, cited reading, the
  club named last before the phrase, the claim's window), `JUDGEMENT_WORD` for judgements
  without a reading and the vocabulary in other forms; the Analyst prompt's Readings section.
  M3's 56 Foundry narratives still pass at replay. Commit `b18b545`. Foundry run 23 Oct
  18:43–18:58 CEST: Sonnet 5.5 28 of 28 first attempt, every narrative cites 1–2 readings
  (Metrics).
  Plan was:
  `stats/readings.py` with `VOCABULARY`; the readings
  in `facts_at` and `match_facts` (also over MCP); the Guard rules above; the Analyst prompt
  lists the readings with "write as" and keeps its other bans; `write_as` for a phrase. Properties:
  every threshold pinned on both sides (goal difference −2, −1, 0, 1; momentum 69/70 and 30/31;
  weight 9/10; chaos 43/44 and 56/57; possession 45/46 and 54/55); a reading exists iff its
  input fact does; deterministic over any prefix; a caption made of cited phrases and displays
  passes; an uncited vocabulary phrase, a phrase whose cited reading displays another, and every
  blacklisted word are rejected and the reason names the token; claim order and repeated runs do
  not change the verdict; never raises on arbitrary text; the stats-only cue still passes;
  mutation testing of the new Guard code. Real run (stop point, owner's cap): Haiku smoke of
  m7's first goal, then seeds 0, 1, 3 on Sonnet 5.5 with `--mcp`; into Metrics: Guard pass
  rates, readings cited per narrative, tokens, cost, latency
- [x] Persona Editor agent, done 23 Oct (red rounds 1 of 3: review SERIOUS, the Analyst's
  retries and the editor's attempts run side by side in one AF superstep, and a check-then-count
  budget let them pass `--max-calls` by one attempt (5 requests at a cap of 4, reproduced);
  fixed by reserving an attempt's requests before any await, tested side by side and by a
  property over any script and cap). `explain/persona.py` (fan role + the Analyst's `RULES`,
  one request an attempt, no tool), `Rendition` on `MomentCase` (`PERSONA_ATTEMPTS` 2), the
  Guard → Persona Editor → Guard edges, a shared `Pace` and budget, log schema v3 (v2 still
  reads), per-persona summary and `total_*`, `explain --persona fan`. Foundry run 23 Oct
  20:57–21:25 CEST: the first Sonnet smoke rendition copied its caption, so the fan role now
  asks for a plainly different line (`605a31e`); then 28 of 28 pass, 27 of 28 differ (Metrics).
  Plan was: `explain/persona.py` (prompt, `PersonaExecutor`),
  `renditions` on `MomentCase` and in the log, the workflow edges above, `fake.py` scripted
  persona replies, `explain --persona fan` (repeatable), the summary per persona. Properties:
  nothing leaves the workflow without passing the Guard (the invariant property extends to
  renditions); a rendition is the passed persona draft or the Analyst's narrative, never
  rejected text; at most 2 attempts per persona; a log line per transition; JSON round trip of
  a case with renditions; the budget counts persona requests. Real run (stop point): Haiku smoke,
  then seeds 0, 1, 3 on Sonnet with `--persona fan`; Metrics as for item 1 per persona
- [x] Persona switch + fan cue templates, done 23 Oct (red rounds 0: verifier PASS, 22 of 22
  mutants killed; review no SERIOUS, its cheap MINOR fixed: no fan draft of a narrative the Guard
  refuses at replay, a fan draft the log calls rejected never shows, the chance's club kept in
  the fan header, the spotlight cleared on a switch; the rest in Follow-ups). `CueRendition` and
  `Cue.renditions` (JSON `renditions` by persona), fan lines from readings ("GOAL · Malik Sennabe
  #11 · VEL take the lead · VEL 1–0 QRD", "VEL on top · end-to-end", "VEL have more of the ball ·
  a steady tempo"; possession when a window has no momentum reading; without a reading the
  analyst's window lines), the run's fan draft at replay ("Fan view", judged again, else the
  analyst's lines), rendition event ids checked by the stream, `cues`/`serve` report fan
  renditions shown and refused, the stats-only label with short names ("possession COR 66%"),
  the page's Analyst | Fan toggle (`?persona=`, re-render from stored cues, one stream), the name
  "Footnote". Real run on item 2's Sonnet run of m0 (Metrics).
  Plan was: `Cue.renditions` (persona → lines, fact ids,
  event ids; `lines` and `fact_ids` stay the analyst rendition, so every cue test holds); fan
  lines for the facts' cues from readings ("VEL on top · end-to-end", "GOAL · Malik Sennabe #11
  · VEL take the lead · VEL 1–0 QRD"); the moment cues' fan rendition from the run (judged again
  at replay, fallback as today); the page's persona toggle (Analyst | Fan, `?persona=`), the rail
  and lower third re-render from the stored cues without reconnecting; the stats-only label with
  club short names, not lower-case ids; the page's product name "Footnote" (title, brand).
  Properties: the three cue invariants of `test_cues` over
  every rendition, the phrase rule included; e2e: switching changes the texts and the chips' ids,
  no console errors. Real run: `matchlens serve --seed 0 --run <item 2's Sonnet run>`, screenshots
  of both personas
- [x] Recap Writer agent, done 25 Oct (red rounds: stopped three times at "3 red rounds", each
  time lifted by the owner, 24 Oct ~21:35 and 23:57 CEST, 25 Oct ~07:10 CET; 9 verifier and 3
  review rounds). The result rule is a denylist, so each round found new forms of its words
  ("tied in", "tying", "edging past", "a point", "stalemating", "saw the hosts off", "beat the
  keeper 3–2"), all pinned in `RESULT_PAIRS`; synonyms outside it pass by design (owner 24 Oct: a
  known limit, not a result reading at full time). Reviews 2 and 3, SERIOUS: a reading beside a
  fact of another time in one claim; fixed both ways (a whole-match reading never beside a goal's
  minute or score, a goal's reading never beside a whole-match fact) and, 25 Oct, S1: a goal's
  reading only beside the minute and the score of that same goal, compared by the instant in the
  fact id rather than `end` (a flow fact so far ends at its last spell, before the instant, in 4
  of the 43 live moments of seeds 0, 1, 3, 7, measured), pinned both sides incl. 1 ms off, 3
  self-run mutants killed. S2 and review 3's MINOR are known limits (guard.py docstring,
  Follow-ups); the owner waived a further verifier and review round for that last change.
  `explain/fulltime.py` (recap case, offered facts, deterministic recap), `explain/recap.py`
  (Recap Writer, workflow reusing the moments' executors), Guard `recap_evidence` (no halves),
  `RECAP_MAX_TEXT` 600, `NO_FINAL_SCORE`, result words, `matchlens recap m<s> --run DIR`
  (`recap.jsonl`, `recap.json`), the `recap` cue at full time, `GET /matches/{id}/recap`, `serve`
  with precomputed overlays. Foundry 24 Oct (Metrics): round 3, seeds 0, 1, 3 with `--persona
  fan`, 3 of 3 recaps and 3 of 3 fan recaps passed at the first attempt; after S1 the 184 stored
  texts of 25 logs re-pass at replay. CLAUDE.md lesson on word-list rules (approved by owner,
  25 Oct) in this commit.
  Plan was: Recap Writer agent (4–6 h): `explain/recap.py` (`RecapCase`, prompt, `RecapExecutor`,
  the deterministic fallback), the Guard with whole-match evidence, the `recap` cue kind and its
  place at full time, `GET /matches/{id}/recap`, `matchlens recap <match> --run DIR`, `--fake`
  script. Properties: every numeral and phrase of a recap is a cited display; a recap cites only
  facts of the whole match and events that exist; the fallback always passes; at most 3
  attempts; JSON round trip. Real run (stop point): the recaps of seeds 0, 1, 3 on Sonnet with
  `--persona fan`; Metrics: pass rate, tokens, cost, latency
- [x] Favourite club, done 25 Oct (red rounds 1 of 3: review SERIOUS ×2, the cards of no team drew
  their stripe in the favourite's accent, and the accent was made readable only on `--bg` though it
  colours text on cards and on the verified chip (COR's chip about 3.1:1); fixed with `--neutral`
  and a contrast check on every surface and chip, measured in the browser by the test; then verifier
  PASS, review 2 without SERIOUS, its minors fixed). `?team=<club>` counts where the club plays the
  match: its cues (chance, goal, moment) lead the rail, newest first, then every other cue, newest
  first, on arrival and after a persona switch ("Cues · VEL first"); the other club's cards at
  opacity 0.5 in the rail (1 on hover or focus), at full strength over the pitch, so a live moment,
  the other club's goal too, stays readable (until 25 Oct dimmed there too; left to Claude by the
  owner, 25 Oct: "item 5, you decide" (translated from Slovak)); cues of no team keep their place,
  stripe and opacity. The accent is the club's primary mixed toward white in 5% steps until its WCAG
  contrast is at least 4.5 on `--bg`, `--panel`, `--moment` and the chip over each (VEL and COR 11
  steps, SLT 3, QRD's white as it is). Picker: a button per club, the URL's `team`, the accent,
  `&team=` on the links of the club's matches; the brand link keeps it. No server change: the
  no-future-leak property and `test_cues.py` untouched. Real run in Metrics. Plan was: `?team=vel`
  keeps that club's cues on top and the others dimmed, the club's colour as the page accent; in the
  picker. Tests: e2e for order and accent; the no-future-leak property unchanged
- [x] Slovak renditions, done 25 Oct (red rounds 3 of 3, all review SERIOUS on the Slovak word
  lists: round 1 number-word forms (`jednu`, `dvaja`), a reading's phrase in other forms ("je
  navrchu") and the Slovak of English judgement words ("otvoril skóre"); round 2 the result
  words with "ne-" and other spellings ("zvíťazil", "remizovali"); round 3 "zremizovali", fixed
  after the owner lifted the stop point for that word; verifier PASS in all 4 rounds; the stop
  hook failed twice on a test count and a replay line, and three times on a docstring's line
  length). `VOCABULARY_SK` (a phrase per code, `PHRASES` by language); the Guard per language
  (`Language`: phrases, number words in their forms, judgement words, "posledných 5 minút", other
  window words, `č.` before a shirt number) and, against a translation's source,
  `NUMERAL_CHANGED` (every numeral byte for byte, as often) and `NAME_CHANGED`, in 1.25 times
  the source's limit; `Translation` on a closed case (the narrative and each persona's own passed
  draft, 2 attempts, fallback = the English text), log v4 with the `translator` role, its chains
  and `translations` in the summary; the Translator (one request an attempt) and
  `matchlens translate m<s> --run DIR --lang sk`; the Slovak stats-only cue, deterministic recap
  and fact-cue templates; the replay judges each translation again (and only while its English
  source passes); `?lang=sk` and an EN | SK switch. Properties: one caption broken 8 ways gets
  the same reasons in both languages; any changed, dropped or added numeral of a translation is
  refused. Real run in Metrics.
  Plan was: a
  Translator executor behind the Guard that renders a passed rendition in Slovak keeping every
  numeral, name and `display` byte for byte (`57%`, `1–0`, `67:23`, `5'` stay as they are;
  `37,4` and `68. minúta` are not attempted); `VOCABULARY` gets the Slovak phrase of each code
  and the Guard judges Slovak text with the Slovak phrases and a Slovak number-word list
  (`jeden`, `dva`, `dvakrát`, `prvý`, `druhý`, `polovica`, `nula`); Slovak fact-cue templates;
  `?lang=sk` and a toggle. Properties: the Guard's rules hold in both languages on the same
  facts; no numeral differs between a rendition and its translation. Real run (stop point):
  seeds 0, 1, 3 on Sonnet. The Translator takes a target language; another language costs its
  phrases, its number-word list and a run
- [ ] Player focus (2 h, conditional: only if items 1–6 are done by Sun 25 evening, no model):
  `?player=vel-p11` rings the player on the pitch, the rail shows the cues citing that player's
  events first and a player card at full time from `player_facts` (new `GET
  /matches/{id}/players/{player}/facts`; the tracking facts are whole-match only, so nothing of
  the future shows before full time); in the picker. Tests: TestClient for the endpoint (unknown
  player 404); e2e for ring, order and card
Not in M5 thin: a club's voice, live persona calls during a replay, per-player live facts, more
languages, speech.

### M6 Deploy: approved by owner, 23 Oct (plan and the six stop points below) · branch `m6-deploy`
Thin: the app of `main` (M2–M4, M5 when merged) as one container on Azure Container Apps with a
public HTTPS URL that replays seeds 0, 1 and 3 with their Sonnet 5.5 runs; judges get a link, the
README (M7) the same link. No model calls from the container in M6 thin (replay only); the
identity for live calls is granted so M5's agents can use it. Read-only checks 23 Oct 15:50 CEST:
the owner's subscription enabled; `rg-matchlens` swedencentral, tagged; providers
Microsoft.App, OperationalInsights, ContainerRegistry, ManagedIdentity all `Registered`; the RG
holds only `aif-matchlens` and its project (no env, app or registry yet); `docker` 29.6.1 runs on
the devbox (owner in the `docker` group); `az` has no extensions (`containerapp` needed, latest
1.3.0b5 is preview, free).
- Design: single container, single revision mode (ACA default; traffic moves only when the new
  revision's probes pass, so a re-deploy never shows judges a cold app). Consumption plan
  0.25 vCPU / 0.5 GiB (the smallest allowed pair). **min replicas 1, max 2**: a scaled-to-zero
  app would make the first judge wait (container start + 2.8 s match generation + 14.6 s cue
  timelines measured locally today with the venv script; at 0.25 vCPU an estimate of 45–90 s
  ±50 %), while an idle replica costs cents (below). Stateless: any replica rebuilds the same
  deterministic matches and timelines, so a reconnect with `last_event_id` resumes on either
  replica; no session affinity
- Memory, measured 23 Oct (`/proc/<pid>/status`, seeds 0, 1, 3 with runs): RSS 89 MB at bind,
  97 MB after the 3 cue timelines, 108 MB after streaming all three at `speed=0&hz=5` (20.0–20.6
  MB each on the wire), 119 MB after one `hz=10` stream (40.6 MB). All four hz caches for 3
  matches ≈ 160 MB (estimate from those deltas, ±30 %): 0.5 GiB holds. SIGTERM → exit in 0.22 s
  with no open stream; open streams get `--graceful-timeout` 20 s, under ACA's 30 s to SIGKILL
  (docs: "If your application doesn't respond within 30 seconds to the SIGTERM message, then
  SIGKILL terminates your container")
- Ingress facts (ACA docs, 9 Oct 2026 version): TLS 1.2/1.3 terminated at ingress, HTTP/1.1 and
  HTTP/2, WebSocket, port 80 redirected to 443, default FQDN `<app>.<random>.swedencentral.
  azurecontainerapps.io`, "Request time out is 240 seconds". Our `/live` lasts about 95 s at 60×,
  190 s at 30×, 570 s at 10× and 5 700 s at 1×: 10× and 1× depend on resume (item 4). Heartbeat
  every 15 s (`HEARTBEAT_S`) is well under any idle cut. Not on the page: whether 240 s cuts an
  active stream or only an idle one, and response buffering → measured after the deploy (item
  3). No redirects or absolute URLs in the app (checked `api.py`, `app.js` 23 Oct), so
  `FORWARDED_ALLOW_IPS` is not needed; the Follow-ups note closes
- Health: `/healthz` exists (liveness). Readiness today would say ok while the cue timelines
  still compute (a first `/live` waits up to 14.6 s locally); item 2 adds `/readyz` (503 until
  the lifespan's queue is done) so a new revision takes traffic only when warm. ACA defaults if
  none set: TCP probes on the target port, startup failure threshold 240 × 1 s
- Identity → Foundry: the owner's calls work with **Foundry User** (sub scope; checked with
  `az role assignment list`: Owner + Foundry User, nothing else; Owner carries no data actions),
  and the Foundry RBAC doc says "To call a deployment at inference time, assign the Foundry User
  role on the Foundry account scope" (role id `53ca6127-db72-4b80-b1b0-d745d6d5456d`; the Claude
  how-to's troubleshooting names Cognitive Services User for a 403: second try only). Scope
  `https://ai.azure.com/.default`, base URL `https://aif-matchlens.services.ai.azure.com/
  anthropic` (as today). The app's system-assigned identity gets Foundry User on `aif-matchlens`
  (free); `foundry_client` moves from `AzureCliCredential` to `DefaultAzureCredential` (item 2
  took `foundry_credential` instead, not DAC: see there)
  (managed identity in ACA, CLI locally; the test fixture still makes the factory raise). M5's
  live persona or recap calls need only `MATCHLENS_FOUNDRY_RESOURCE` set on the app plus
  `--max-calls`
- Demo runs: the three Sonnet runs are 541 kB, 313 kB and 407 kB (`handoffs.jsonl` + 582 B
  `summary.json`; 1.26 MB in all). Commit them as `demo/runs/m0`, `m1`, `m3` (`.gitignore`
  excludes `/runs/` only): one source for the container, the README's local run and the video;
  no secrets in them (fictional data, model names). Chromium and Playwright stay out of the image
- Cost (retail prices API, swedencentral, 23 Oct, USD): ACA Standard vCPU active $0.000024/s, idle
  $0.000003/s; memory active and idle $0.000003/GiB-s; requests $0.40/M after 2 M free; free per
  subscription and calendar month 180 000 vCPU-s and 360 000 GiB-s (= 8.3 days of one 0.25/0.5
  replica). ACR Basic $0.1666/day, 10 GB included; ACR Task build $0.0001/s (not needed, docker
  builds locally). Log Analytics $2.99/GB after 5 GB/month free. Method: one replica always on
  from Sun 25 Oct to the judging end (10 Nov 23:59 PST = 11 Nov 08:59 CET, 17 days): October
  fully inside the free grant, November 10.4 days → 44 640 vCPU-s and 89 280 GiB-s billable:
  **$0.40 idle, $1.34 if active throughout** (an open stream counts as active). ACR $2.83. Logs
  under 0.1 GB (estimate) → $0. Total ≈ **$3.2–4.2 to 11 Nov**, ≈ $10–20 kept to 30 Nov (tag
  `expires`); within the project's quarterly budget. The env's management meter ($0.13/h) applies
  only with private endpoints or planned maintenance: enable neither
- Names, all tagged `project=matchlens owner=radoz expires=2026-11-30`, swedencentral:
  `log-matchlens` (Log Analytics, PerGB2018, 30-day retention), `acrmatchlens` (ACR Basic, admin
  user off, pull by managed identity `AcrPull`), `cae-matchlens` (environment, Consumption,
  logs → `log-matchlens`), `ca-matchlens` (app, system-assigned identity, external ingress,
  target port 8000, image tag = short git sha, revision suffix = the same)
- Branch: `m6-deploy` from `main` (`31f8699`) in `.claude/worktrees/m6-deploy`; `/ship` merges
  there; the owner merges into `main`. No new Python dependencies (`azure-identity` is in);
  `uv.lock` unchanged. Expected conflicts with `m5-personalize`: `PROGRESS.md`, `CLAUDE.md`
  Commands, and `app.js` if M5's persona switch touches `open()`/`onerror` (M6's item 4 edits
  only those two; tell the M5 session). Also `tests/test_explain_analyst.py` (checked 23 Oct
  18:39 CEST): M6 item 2 and `m5-readings`' uncommitted work both add tests at its end; keep
  both. Their `analyst.py` edits do not overlap (M5: prompt text; M6: imports and
  `foundry_credential`). The README's testing instructions (M7) take the URL and
  `demo/runs` from here
- Stop points: LA, ACR, environment, app (billed), the Foundry User grant and the public URL
  itself (published). One batched OK for all six at approval, so item 3 runs in one sitting
  (approved by owner: M6 resources, 23 Oct)
- Hours are estimates ±50 %, calibration M2–M4 median 7.4 h per item; M6 items are smaller
  (no stats engine) but wait on cloud steps (RBAC propagation up to minutes, pushes)
- [x] Container (3 h), done 23 Oct: `Dockerfile` (python 3.12 slim and uv 0.11.25, both pinned by
  digest; uv mounted for the two `uv sync --locked --no-editable` layers only; uid 10001;
  exec-form `CMD` serving seeds 0, 1, 3 with `demo/runs/m0`, `m1`, `m3`: the Sonnet
  5.5 runs, 1.26 MB), `.dockerignore`, `scripts/container.sh` (build, run at `CPUS`/`MEMORY`,
  default 0.25/512m, smoke and timings; exits 1 on a failed check, incl. a match not streaming
  within 240 s of the start). Tests (`test_container.py`): the wheel carries every file of `web`
  and `data`; each demo run is a Sonnet run of its folder's match and shows all its narratives
  at replay; the `CMD` parses with the real CLI and serves exactly the demo runs. Real runs:
  Metrics (Container). Finding: at 0.25 vCPU the last match streams close to the readiness
  window planned in item 3 (48 × 5 s = 240 s; check ACA's allowed probe ranges there; devbox
  CPU, not ACA's). Owner decision, 23 Oct: item 3 starts at 0.25 vCPU / 0.5 GiB; on a problem or
  if it is very slow, 0.5 / 1 GiB, and if that is not good either, 1 / 2 GiB. Cost to 11 Nov
  with the method above, idle / active throughout, excluding ACR ($2.83), estimate: 0.25: $0.40 /
  $1.34; 0.5: $3.53 / $11.75; 1: $10.29 / $34.30 (at 0.5 and 1 October already exceeds the free
  grant)
- [x] Readiness + identity (2 h), done 23 Oct: `/readyz` 503 `{"status": "warming", "pending":
  [...]}` until every served match's cue timeline is computed, then 200; the probe queues again
  a timeline that failed or that a leaving client cancelled while queued (else the revision
  would never be ready); `/healthz` unchanged. The cue worker is one daemon thread
  (`_DaemonWorker` in `api.py`) instead of the `ThreadPoolExecutor`: its shutdown cancels the
  queued jobs and the interpreter no longer joins a running one. `_serve` installs a SIGTERM
  handler (`SystemExit(143)`) before its imports; uvicorn puts it back and raises the signal
  again after the graceful shutdown, so `serve` stopped by SIGTERM exits 143 (CLI docstring).
  Identity: **not** `DefaultAzureCredential` (deviation from the plan, measured 23 Oct): its
  async managed identity needs aiohttp (not in the lock: `ImportError` with ACA's variables set),
  and on the devbox its IMDS probe cost 24.45 s before the CLI token (0.59 s): something answers
  169.254.169.254 with 404 and is retried with backoff. `foundry_credential()` takes
  `ManagedIdentityCredential` with azure-core's `AsyncioRequestsTransport` when
  `IDENTITY_ENDPOINT` is set (ACA sets it), else `AzureCliCredential`; no new dependency.
  `GRACEFUL_TIMEOUT_S` comment: 20 s for open streams, the rest of ACA's 30 s for an exit that
  no longer waits. Tests: readiness 2 → 1 → 0 matches warming (only 0 is ready), given cues
  ready at once, a failed and a cancelled timeline queued again by the probe; the worker's order,
  shutdown and daemon thread; `matchlens serve` in a subprocess with SIG_IGN standing in for PID
  1, held in the cold start and in the warm-up: SIGTERM → exit 143 under 2 s (each fails on the
  old code: 10 s timeout, checked by reverting each fix); the credential off Azure (unset, empty,
  blank) and with ACA's variables against a fake identity endpoint on loopback (token over the
  requests transport). The cold-phase stop test holds at `_serve`'s `import uvicorn`, so it
  also pins the handler before the imports; a failed timeline is logged with its traceback
  before the retry (no client reaches an unready replica to see a 500). `scripts/container.sh`
  checks `/readyz` 503 at `/healthz`, prints the flip and each probe's time (median, max),
  expects exit 143 and stops two more containers early (cold start, warm-up), each under 5 s.
  Real runs: Metrics (Readiness and stop). At 0.25 vCPU `/readyz` turns 200 at 190–211 s, inside
  item 3's planned 48 × 5 s window by 29–50 s. Found by item 1's
  verifier: a SIGTERM during warm-up at 0.25 vCPU ends in SIGKILL (`docker stop -t 30` right
  after `/healthz`: 30.3 s, exit 137) because `worker.shutdown(wait=False, cancel_futures=True)`
  leaves the running cue job, which the interpreter joins at exit (~60 s a match at 0.25);
  `scripts/container.sh` stops only after the warm-up. Found by item 1's review, another cause:
  before uvicorn installs its handlers (match generation and the runs' replay check, the whole
  cold start to `/healthz`), Python as PID 1 ignores SIGTERM, so a stop then waits for SIGKILL
  (fix: a SIGTERM handler at the start of `_serve`, or an init; ACA's
  `terminationGracePeriodSeconds` is the other knob, item 3). Both fixed above
- [x] Resources + first deploy (4 h, stop points), done 24 Oct (deployed 23 Oct):
  `deploy/containerapp.yaml` is the revision template (image, 0.25 / 0.5Gi, scale 1–2 with ACA's
  default HTTP rule, SIGKILL 30 s after SIGTERM, suffix = the commit's short sha, tags) with
  three probes: startup `/healthz` (1 + 40 × 3 s), liveness `/healthz` (every 10 s, 3
  failures), readiness `/readyz` (5 s × 48); timeouts 3, 5 and 5 s; `/readyz` on neither startup
  nor liveness; the placeholders quoted (a sha of digits is a number in YAML, one with a leading
  0 an octal one). `scripts/deploy.sh`: each step looks with a `list` query as a plain
  assignment before it creates (LA → ACR → image → env → app → `AcrPull` and Foundry User for
  the app's identity → revision), so a failed lookup stops the run instead of creating again
  over a live resource (`az containerapp create` is a PUT: on the live app it would put the
  placeholder image back); the image is built from `git archive` of the commit read once, so its
  tag names exactly what is in it; the revision goes on with `az containerapp update --yaml` (a
  PATCH of the template: ingress on 8000 and the registry pulled by the system identity stay as
  `az containerapp create` set them; a note when the template differs from the commit's, and
  whether it was applied); then it waits for the revision active and healthy, printing each
  polled state (a failed provisioning or container ends it at once with the restart command, an
  inactive revision with the activate command, 600 s at most) and prints the URL (none without
  an FQDN). A registry created in the same run is not asked for its images. Deviations: no `az extension add` (core CLI 2.91.0 has every command
  used; the preview extension would replace them); the CLI's create leaves two extra, inactive
  revisions (its placeholder image, then the image with ACA's default probes) before the
  template's; it granted `AcrPull` itself (the script's grant found it). Tests
  (`test_deploy.py`): probe paths and ports against the Dockerfile's `EXPOSE` and the script's
  `--target-port`, timeouts ≥ 2 s, the startup window ≥ 3 × the measured cold start, the
  readiness window ≥ `container.sh`'s 240 s, the replica, placeholders and tags shared with the
  script, shas `5b18038`, `1234567`, `0123456`, `0000000` staying the suffix; against fake `az`,
  `docker`, `sleep` and `date`: a first run creates everything in order (the image from exactly
  the commit's files, the env on the workspace by id without its key, the app with its own
  identity, Foundry User for it, the template filled in; a fresh registry not looked into; the
  revision looked up with `--all`), a second run of the same commit changes nothing, a new
  commit only builds, pushes and deploys its revision, each of the 8 lookups failing ends a run
  with no change, a failed scope lookup
  stops it before any grant, a warming revision is waited for (20 s), 600 s from both sides
  (healthy on the poll at 600 s passes, one poll later fails), a failed or crashing revision
  stops it at once with the restart command, an inactive one with the activate command, a failed
  or empty FQDN gives no URL. Red rounds 1 of 3 (review SERIOUS: the unquoted suffix, `show ||
  create`; both fixed; second verifier PASS, CI 1568 passed, 95 mutants; re-review no SERIOUS,
  its cheap MINOR fixed, the rest in Follow-ups). Real runs: Metrics (Deploy). URL
  (LA and ACR up since 23 Oct 23:41 CEST, env and app since 23:44):
  https://ca-matchlens.niceglacier-670016e8.swedencentral.azurecontainerapps.io/
- [x] Stream resilience (3 h), done 23 Oct (the public-URL run waits for item 3): the SSE
  `retry` hint on `meta` existed (2000 ms) and is now 1000 (`RETRY_MS`): after a network cut the
  browser retries each second and resumes by `Last-Event-ID`. Any answer but 200 (a 503 while a
  replica restarts) closes the source for good: the page reopens it after the last handled id
  (`last_event_id`), waiting 1, 2, 4, 8, 16 s (`REOPEN_MS`, `reopenDelay` in `app.js`), then
  "Connection lost: pick a speed to try again" in the status and on the overlay; the waits start
  afresh on each `meta` and on a speed click, and a click while a reopen waits connects at once.
  The last frame stays on screen (nothing is cleared). Deviations: before the first `meta` a
  closed source still says "This match could not be loaded" at once (an unknown match's 404
  should not wait 31 s; a rollover then also fails `/league`, so a reopen would not help); the
  restartable server is `Server` in `tests/test_web.py`, not `scripts/serving.py`. Tests
  (`test_web.py`): the schedule for attempts 0–6 (1 … 16 s, then null: both sides of the cap); a
  server stopped mid-stream and started on the same port (the browser's reconnect by header, the
  last frame held, at 1 Hz the clock shows each second once from 00:00, the cards are the
  timeline's prefix, cards on both sides of the cut); 503s through `page.route` with a paused
  Playwright clock: each wait pinned 1 ms early and on the dot, the last frame's positions after
  each wait, a `meta` resets, give-up after 5, a click resets, a click while a reopen waits drops
  it; the whole-match test checks that nothing reopens after `end`. Mutants of `app.js` and
  `RETRY_MS` (implementer 11, verifier 17) each fail them (the verifier's one survivor, a wiped
  frame, since the review fixes). Red rounds 0 of 3 (verifier PASS,
  review no SERIOUS; its cheap MINOR fixed, the rest in Follow-ups). Real run: Metrics (Stream
  resilience); through the public URL (10× past 240 s, `revision restart` with the page open):
  Metrics (Deploy), run with item 3
- [x] Ops + docs (1.5 h), done 24 Oct: `docs/deploy.md`, the runbook: who runs what (read-only
  commands anyone; deploy, restart and teardown only with the owner's OK), what runs where (the
  four resources, the identity's two roles, the template), the **freeze** during judging, deploy
  and re-deploy (commit, then `scripts/deploy.sh` from the branch the owner names; settings into
  the template's `env:`), roll back (`git revert`, deploy), restart (`latestReadyRevisionName`:
  the revision that serves, not a failed newer one), health, logs (console stream, system
  events, a Log Analytics query by REST GET, since `az monitor log-analytics query` needs a
  preview extension), metrics, cost (Consumption `usageDetails` by REST GET for a month's range:
  `az consumption usage list` gives rows without quantities or costs here; the Claude rows are
  the deployment's own once the app calls models) and the **teardown** after judging: the
  identity's role assignments first (they outlive the app), app, env, ACR, LA with `--force
  true` (else soft-deleted 14 days); never the RG or Foundry; never recreate the env while the
  URL is published (its domain is in the URL). Freeze (review SERIOUS: nothing stopped a
  re-deploy after the submission closed, against Rules 4.8 and 5): `scripts/deploy.sh` refuses
  from 28 Oct 07:59 CET to 11 Nov 08:59 CET, before any call, unless run as
  `DEPLOY_DURING_JUDGING=yes` (the owner's decision); it also prints the branch and the commit,
  and for an inactive revision points to the revert instead of an unmeasured `revision
  activate`. Every read-only line of the runbook was run for real on 24 Oct, pasted into an
  interactive bash (history expansion on; the deletes only checked with `-h`; `--follow` buffers
  when redirected, fine in a terminal). CLAUDE.md Commands gets `scripts/container.sh` (the plan)
  and `scripts/deploy.sh` (beyond the plan, kept by the owner 24 Oct; its line says: only with
  the owner's OK), announced.
  Tests (`test_deploy.py`): the freeze from both sides at both ends (refused before any call,
  with the override let through); the teardown deletes the app identity's role assignments
  first (its principal looked up, the filter on it), then exactly deploy.sh's app, env, ACR and
  LA in that order, all in its resource group, never the group or the Foundry account; the
  runbook's table names the script's resources; the URL is one URL in the runbook and PROGRESS;
  no `!` inside double quotes in a command; every script, template and doc the runbook names
  exists; the freeze's epochs derived from the rules' Pacific times, the runbook's dates from
  them, only `yes` lets a deploy through, the commit line, the restart on the serving revision,
  the teardown's `--all`, `--yes` and `--force true`. Red rounds 1 of 3 (review SERIOUS: the
  freeze; fixed; second verifier PASS, CI 1579 passed; re-review no SERIOUS, its cheap MINOR
  fixed). The planned Follow-ups were closed earlier: the container note by item 1, the SSE
  note by item 3, `FORWARDED_ALLOW_IPS` by the plan. Real run: Metrics (Cost)
- [x] Demo runs of M5 (re-deploy approved by owner, 25 Oct, 23:10 CET: "I agree, go on" (translated
  from Slovak) to the audit's steps), done 25 Oct in `m6-demo-m5`, from `m5-personalize` (the runs
  cite reading ids only M5's engine knows; `m6-deploy` lacks it): `demo/runs/m0`, `m1`, `m3` are M5
  item 2's Sonnet runs (`runs/m0/20261023T185842002Z`, `runs/m1/20261023T191212840Z`,
  `runs/m3/20261023T191953049Z` of the `m5-personalize` worktree), copied byte for byte with the
  recap (item 4) and the Slovak translations (item 6) added to them later: six files a run, 5.76 MB
  in all (M3's: 1.26 MB). No local path, host, e-mail or key in them (the one URL is the local MCP
  server's, `127.0.0.1:8001`). Tests (`test_container.py`): read as `matchlens serve --run` reads it
  (`cli._runs`), each demo run has exactly its six files and shows a fan rendition of every moment,
  the Recap Writer's recap and its fan recap, and a Slovak translation of every narrative, rendition
  and recap, with no fallback to the engine's or the English text; no text of the runs, refused
  drafts included, names a real club or a famous player (the lists of `test_league.py`). Mutants in
  a scratch copy (M3's runs back, m1 without its translations, a real club's name in a recap draft)
  each failed its test. Finding of the real run (`scripts/ container.sh`): since M5 item 4
  (`722eee3`) `serve`'s replay check computes every match's overlay, the whole warm-up, before the
  bind, so at 0.25 vCPU on the devbox `/healthz` answered after 211.8 s (`main` with M3's runs:
  202.4 s; 29.9 s on 23 Oct, with the cue timelines computed after the bind), beyond the startup
  probe's 1 + 40 × 3 s, and `/readyz` answers 200 as soon as the server listens (container.sh failed
  its 503 check). Fixed in the deployment, not in the code: the startup probe gets ACA's own default
  threshold, 1 + 240 × 3 s, three times the cold start as `test_deploy.py` asks (`COLD_START_S`
  211.8), and container.sh expects 200 at `/healthz`. Red rounds 2 of 3 (verifier FAIL twice: this
  entry and a follow-up spelled out real club names, one as a mutant's, two in Slovak declensions;
  replaced by descriptions). Review: no SERIOUS; its cheap MINOR fixed (every attempt's model, a run
  of every moment, the claims' texts, stale comments, a unit), the rest in Follow-ups. Real runs:
  Metrics (Container, M5 demo runs); the re-deploy: Metrics (Deploy)
- Day plan alongside M5: Sat 24 morning items 1–2 (no owner needed), afternoon item 3 with the
  batched OKs (owner online ~1 h for the first deploy), evening the URL measurements; Sun 25
  (CET from 03:00) items 4–5 and a re-deploy with M5's state if merged; Mon 26 re-deploys only
  (M7 needs the URL before the Innovation Studio page is saved). Total 13.5 h (7–20 h)
- Risks: the 240 s ingress cut on active streams (mitigated by resume; measured in item 3); an
  open stream keeps the replica at the active rate (≤ $1.34 in all); `AcrPull` or Foundry User
  propagation delay → first revision "Activation failed", restart it after a few minutes;
  `az containerapp` preview flags shifting → pin the extension version in `deploy.sh`;
  anonymous `speed=0&hz=10` costs seconds of CPU per request at 0.25 vCPU → max replicas 2 and
  the budget alert, a cap on hz for speed 0 only if abused (not thin); judges from the US see
  ~150 ms RTT to swedencentral, harmless for SSE; the devbox's guard blocks `docker`/`rm -rf`
  chains, so item 1's measurement and item 3's push may need the owner's terminal
Not in M6 thin: CI/CD to ACA (GitHub Actions OIDC), custom domain, Application Insights or
OpenTelemetry, auth or IP restrictions, CORS, Bicep/azd templates, the MCP server as a second
app, live Analyst calls during replay (M5/deepening), `claude-code-action` on Foundry.

### M7 Submission: approved by owner, 25 Oct (23:10 CET, "I agree, go on" (translated from Slovak) to the audit's steps: README with the name, a diagram and testing instructions, denylist hashes, the video with a Guard refusal; the public repo, the video's upload and the Innovation Studio page stay stop points) · branch `m7-submission`
README, pitch, demo video (< 2 min, no third-party marks or music), public repo, testing
instructions. All in English. The rules name the category two ways, "Best Multi-Agent System"
(4.2) and "Best Multi-Agent Orchestration" (prize table): use both in the pitch.
Branch `m7-submission` from `m5-personalize` (after the demo runs of M5 and their re-deploy) in
`.claude/worktrees/m7-submission`, run by session `18-plhack-ba`, from 26 Oct afternoon
`18-plhack-37`; `/ship` merges there; the owner merges into `main`. No new dependencies. Hours are
estimates ±50 %.
Items, in this order (the first three before the repo goes public):
- [x] Denylist hashes (1 h), done 26 Oct in `m7-denylist`: the three lists of
  `tests/test_league.py` (98 club names, 23 club codes, 30 surnames) are the first 16 hex digits
  of the SHA-256 of each lower-cased name, so the repo spells none out. The detector (`hits`)
  hashes every run of up to `MAX_WORDS` (3) words of a text, the last word also in its Slovak
  case forms (an ending of `SK_ENDINGS` dropped, or replaced by an "a" or an "o", the stem at
  least 3 letters): the demo's translations decline names. `test_container.py`'s check of the
  demo texts uses it. Tests: the sizes and a fingerprint of each list; a digest's known answer
  and that it ignores case; each check reads its own list (made-up names put into the three
  lists); the detector with made-up names from both sides (any case, accents, names of one, two
  and three words and a part of one, a sentence; a longer word or a bare stem not), every
  Slovak ending (written out in the test) and the 3-letter stem from both sides. Checked once outside the repo against the
  plain lists (scratch scripts, not committed): every plain name hits, alone and in a sentence;
  714 Slovak case forms of the 122 one-word names hit; the league's and the demo runs' 2 439
  texts give the same hits as with the plain lists (0). Mutants in scratch copies, each killed:
  the stem at 4 or 2 letters, an ending dropped, no "a" or no "o" added, `MAX_WORDS` 1 or 2, a
  digest changed, dropped or swapped between lists, the digest truncated, of another hash or
  encoding, no lower-casing, each check emptied or reading another list, the code check
  without the digest; two survive as harmless (a form "+e" more, which only adds hits; the
  last word's case, which the digest lowers anyway). Red rounds 2 of 3: the review (SERIOUS
  twice: the stem boundary pinned from one side, fixed; the git history, the next item; its
  cheap MINOR fixed: a fingerprint per list, every ending, `MAX_WORDS` 3, docstrings, a
  two-word name and its part, no real place's name) and the verifier (FAIL: no test tied the
  real lists to their checks nor pinned the digest, so emptying a check passed, where the old
  test of real names failed; fixed with the known answer and the wiring test); the third
  verifier PASS (74 mutants of its own, 64 killed, the 10 survivors harmless or as in the
  plain version; every listed name put into the league in memory fails a test, 0 lost),
  its MINOR fixed (an ending tried after an earlier one fits: "-mu" and "-u")
- [ ] Owner, before the repo goes public (review of the denylist hashes, SERIOUS): the plain lists
  stay in the history, in `tests/test_league.py` of 91 of `main`'s 101 commits and of every pushed
  branch (method: the plain lists over every file of every commit of `main`, the engine's word
  "reading" left out; no other file and no commit message names one). The history also holds the old
  "Now" of PROGRESS.md (M7 cut it on 26 Oct): from `f603a71` (23 Oct) it names other entries of the
  hackathon and one entrant's public GitHub account, with our notes on them, and earlier versions
  quote the owner in Slovak, as does the message of `58723ac`. Making `radozaprazny/18_plhack`
  public shows all of it. Recommended: a new public repository from one squashed commit of `main`
  after M7 (GitHub keeps a force-pushed repo's old commits reachable by their SHA). A rewrite in
  place (`git filter-repo --replace-text` plus rewritten messages, then a force-push) would have to
  catch all of the above and would still leave the old commits reachable. Decided by the owner, 26
  Oct: a new public repository from one squashed commit of `main` after M7; `radozaprazny/18_plhack`
  stays private
- [x] README for judges (2 h), done 26 Oct in `m7-readme`: the problem (a model on air can
  invent a number or a judgement), the name Footnote and its line, the five stages, a Mermaid
  architecture diagram (three Agent Framework workflows, the Guard's retry edge, the MCP tool
  call, the handoff log), the agents (role, model or code, what happens when one fails), the
  shared state (`MomentCase`: an unverified narrative cannot be represented), what the Guard
  checks and where its known limits are, recovery (the one real refusal of the demo runs),
  measured results from Metrics (the cost of October measured for it: Metrics, Cost, October to
  25 Oct), the Microsoft technologies and the open protocol used and only those, testing
  instructions (the live demo; a demo run served locally; the whole agent chain without a model;
  on Foundry over MCP; the tests) and the layout. Tests (`test_readme.py`): the one app URL is
  the runbook's; every `uv run matchlens` of its code blocks is collected and parses with the
  CLI, placeholders filled; the commands a judge runs are there; a command that calls a model
  caps its requests, and the agents on Foundry reach the facts server the README starts (its
  `mcp` command run with a stand-in server); every number in the tables of "Measured results"
  stands in Metrics as a whole number; every path it names exists (links, backticks, commands; a run directory named by a
  placeholder excepted). `docs/deploy.md` says Footnote too. Real run: every
  command of the testing instructions but the billed Foundry one, as written, from the worktree:
  `serve` of `demo/runs/m0` ready in about 7 s with all of M5 replayed, 0 refused; the `--fake`
  chain explain, recap, translate wrote a run directory with all six files. Red rounds 2 of 3 (review 1, SERIOUS ×5: a cost with no source in the repo, the Guard promised
  more than it checks, a command the test skipped, the live demo still M3's, "one budget" for
  all agents across runs; review 2, SERIOUS ×1: the budget is one per command, not per run
  directory; all fixed, its cheap MINOR too, the live demo by the owner's re-deploy of `0b130a6`, 26 Oct 08:08 CET:
  Metrics, Deploy, M5 demo runs); the verifier PASS, its MINOR fixed (the Ingest list as the
  events are, every link checked, the budget and the pace explained, the latency dated). The
  diagram is checked by its syntax only, not seen rendered (no renderer on the devbox, and the
  auto-mode classifier refused a downloaded one): look at it on GitHub after a push
- [x] Issue #9 (Footnote naming, stale docstrings), done 26 Oct in `m7-naming`: `/docs`, `/redoc`
  and `/openapi.json` say Footnote, as do the `Dockerfile` and the package docstring; stale
  docstrings fixed (Analyst, Detector, the Guard's known limits: `a goal ahead` is refused, now
  pinned). Red rounds 0: verifier PASS (full CI, 2 451 passed), review OK, its minor fixed. The
  live app shows it after the next deploy (the owner's)
- [x] PROGRESS for a public repo (1 h), done 26 Oct in `m7-publication` with the next two items (one
  change, one review): "Now" cut from about 190 lines to the current state; the owner's decisions
  that lived only there now stand in "Owner decisions outside the milestone plans"; the competition
  notes kept as their conclusion, without other entries' names; the owner's Slovak quotes in
  English, marked as translated; GitHub CI's duration a Metrics row; internal account details made
  generic (the subscription's budget, another resource group, the project's budget, the owner's
  Marketplace values; GitHub issue #12); and four README sentences the code does not fully back,
  rephrased (issue #3: the shared state, numbers in words, no sprints; the budget per command was
  already fixed)
- [x] Video (1.5 h; the owner records the voice and uploads), done 26 Oct: the script in
  `docs/submission.md`, eight shots ending at 1:50 (the rules ask for less than 2:00), 210 words of
  voice-over, at most 2.5 a second in any shot; the Guard's refusal is the Translator's (m1's Slovak
  recap, `phrase_not_cited`, then passed: the one refusal of the demo runs, real), shown by a
  terminal command the doc gives. Changed from the plan: no Playwright tour; the owner records the
  live page by hand, following the script; still frames of the live page for a cover were taken 26
  Oct, outside the repo. The voice-over and the pitch say that the page replays runs the agents
  wrote beforehand, not live calls
- [x] Innovation Studio texts (0.5 h), done 26 Oct in `docs/submission.md`, each text to paste in a
  code block: title (48 of 140 characters), tagline (273 of 300), keywords, challenge, the form's
  two answers, and the description (the pitch: the problem, what was built with which Microsoft
  technologies, the shared state, what the judges see and that it replays logged runs, the live URL,
  measured numbers), the category named both ways. Tests (`test_submission.py`): the page's limits
  and the stated counts, on the limit and one over; the category in the pitch, tagline and keywords,
  and the runbook's URL in the pitch; each measured claim in its own Metrics row and no other
  number; the video's eight shots contiguous from 0:00, ending by 1:55, at most 2.5 words a second
  (on the limit and one word over), the stated word count; the terminal shot's command, pasted into
  bash, prints the refusal and the retry. Red rounds 3 of 3, the stop point (counted strictly):
  review 1 (SERIOUS ×3: the pitch and video promised live agent calls and a check of every
  judgement, the video ended at 2:00, one Slovak quote left), the verifier on the same version
  (FAIL: the same points, the word count, facts lost from the old Now, thresholds pinned from one
  side), review 2 (SERIOUS: the history item must name the old Now's other entries, an entrant's
  GitHub account and the Slovak quotes, and recommend a new squashed repository); all fixed with the
  cheap MINOR, and the third verifier PASS on the version before review 2's fixes. Stop point lifted
  by the owner, 26 Oct ("yes, as you recommend", translated from Slovak); the commit also adds the
  three lessons to CLAUDE.md the owner approved
- [x] Microsoft's texts out of the repository (0.5 h; owner, 26 Oct, Owner decisions), done 26 Oct
  in `m7-mstexts`: `docs/RULES.md` (the hackathon's Official Rules) and `docs/resource-playlists.md`
  untracked and gitignored; a tree keeps its copies until a merge or checkout of this commit removes
  them, so `CLAUDE.md` gives the restore command (the private repository's `5eb247e` has both) and
  the Hackathon Website; `docs/deploy.md` and two comments name the Official Rules instead.
  `.claude/` stays: `test_guard.py` and `test_select_tests.py` test its hooks. Tests
  (`test_public_repo.py`, over the index): no tracked file holds a verbatim sentence of either text
  (the Rules' opening paragraph, challenge and our category's prize; the playlists' opening
  paragraph); only `.gitignore`, `CLAUDE.md`, PROGRESS and the test name the two paths; both are
  ignored, the other docs and a new one are not; each sentence is in its text (the local copy, else
  `5eb247e`; skipped where neither exists: CI, the public repository). Real run, the owner's step
  (3) rehearsed in `/tmp` on this item's tree: `git archive` into an empty directory, `git init -b
  main`, `git add -A`, one commit with the noreply e-mail; its tree hash equals the item's, 134
  files, neither text; the repo's real-name detectors over every file of it hit only the engine's
  word "reading" (37 files). Red rounds 2 of 3: the verifier (FAIL: a comment of `test_deploy.py`
  over ruff's 100 characters; fixed with its cheap minor, `check-ignore --no-index` so the tracked
  docs count, and no tree hash quoted here, as this line is in the tree); the second verifier PASS
  (`scripts/ci.sh` 2 469 passed, the mutants of the new tests killed); the review (SERIOUS: the
  local copies vanish at this item's merge and worktree removal, so `CLAUDE.md` claimed copies that
  were gone and the sentence test skipped everywhere; fixed with the restore command and the
  fallback to `5eb247e`), its cheap minor fixed (the index searched with `git grep --cached`, two
  more sentences, the files that may name the paths, the Hackathon Website, Now, M7's session, the
  subscription's name made generic); the third verifier PASS (`scripts/ci.sh` 2 477 passed; in
  scratch copies the fallback to `5eb247e`, the squashed copy's skips, the index, the allowlist and
  the pre-commit hook's environment, each with its mutant; the restore command gives byte-identical
  files); the second review OK, its cheap minor fixed (the fallback skips only where its commit, now
  a full SHA, is missing, and fails otherwise; the restore command for both files; a test's name;
  "opening paragraph"); left as they are: no test tells the index from the working tree (the hook
  tests a checkout of the index), and a 12-word phrase of the challenge in a docstring
- [x] Load limits on `/live` (issue #2, the live demo protected during the judging), done 26 Oct
  in `m7-loadlimits`: `LiveLimits` in `matchlens.api`, on in `matchlens serve`: a stream's speed at
  least 1×, its frames a second (speed × hz) at most 300, the open streams of a replica together at
  most 600 frames a second (in integer thousandths) and 30 streams; a link past a stream's own
  bounds gets a 422 with the reason, a full replica a 503 with `Retry-After: 5`; the share is
  taken with the check before any await and given back on a 400, a failed overlay or the
  stream's end. `LiveLimits.admits(speed, hz)` is a stream's own bounds. The page asks a refused
  first stream's link why: 404 and 422 say so at once with the server's reason, a 503 is tried
  again on the reopen backoff (an ask answered 200, a slot freed meanwhile, is cut at once and
  reopened), and an answer for a stream a click has replaced changes nothing; only a string
  reason is shown (FastAPI's own 422s carry a list).
  `live()` reads the timeline in place (no copy per open stream). The video's full-time shot
  opens `?match=m0&team=vel&speed=300&hz=1` (1000× at 5 Hz is refused now). Tests:
  `tests/test_live_limits.py` (the public limits; `admits` from both sides; the slot and the
  budget each pinned on their bound and one unit past it; a request refused with a 400, a
  finished resume, a failed overlay, a stream that fails midway: each gives back its slot and
  its share, by each bound alone; the reasons and the 503's body word for word; `/events` while
  full; requests at once), four page tests in `tests/test_web.py` (503 tried again until a slot
  frees; a 200 ask cut and reopened; 422 says why in the status and on the pitch, a list reason
  not shown, no reopen; a late answer for a replaced stream ignored), and every page link of the
  shots admitted (`tests/test_submission.py`). Real run: Metrics, Live limits (21:03). Red
  rounds: past the stop point three times, each time the owner went on (26 Oct, session
  `18-plhack-b9`; 20:33 and 21:43 CET in session `18-plhack-ec`). The FAIL at the handover was
  only unpinned code (the share given back, the stale-answer guard; a `clearTimeout` in
  `reopen()` that no path reaches, removed: `connect()` clears the timer and a stale answer
  returns first; the verifier's own probe found no double reopen). The next round: `scripts/ci.sh`
  2 512 passed and the real run as designed, but the verifier FAIL on five survivors (a stream
  failing midway, the 200 ask's cut and its signal, the reason on the pitch, the minimum's
  reason, the 503's body) and one assertion of `test_submission.py` moved into the new test (put
  back); the review SERIOUS: the Metrics row's "10 open streams" were never open (re-measured:
  4). All fixed, the cheap minor too (the CPU figures per hz, a list reason, the shot opened
  20 s early, `/live`'s docstring, a stale comment). The owner chose to commit without another
  full verifier round: each survivor and the list reason re-run as a mutant, 7 of 7 killed, and
  the pre-commit hook's `scripts/ci.sh`
- [x] No player top speed on the full-time card (issue #7), ported 26 Oct ~23:10 CET from
  `m8-showcase` (`70db3b4`, done there in M8 with verifier PASS and review OK) by the owner's
  decision 26 Oct 22:53 CET: the safe line's footage showed "Top speed Jakub Vesnar #18 23.8
  km/h", and top speeds in the Premier League are about 32–36 km/h. The card keeps the score,
  possession and pass completion, English and Slovak; the engine keeps the fact. Tests:
  `test_no_card_names_a_players_top_speed` (every cue, persona and language, both period ends)
  replaces the test that pinned the line (owner OK with the issue). Follow-up: `recap_evidence`
  still offers `top_speed`, so a live Recap Writer could cite it if it guessed its id; filtering
  it is a Guard change (issue #19)
- [ ] Owner, in this order, before the submission closes (Wed 28 Oct 07:59 CET): (1) re-deploy the
  final `m7-submission` with `scripts/deploy.sh` (issues #2 and #9 change the app; done 26 Oct
  22:42 CET, `1d5c025`, and 23:30 CET, `23d81ab` with #7; Metrics: Deploy), then merge it
  into `main` and push both; (2) the history is decided (the item "Owner, before the repo goes
  public" above); (3) create the new public repository `radozaprazny/footnote` from one squashed
  commit of the final `main` (the GitHub noreply e-mail), push it there and disable its two Claude
  workflows; (4) look at the README's diagram on GitHub; (5) record the video by
  `docs/submission.md` and upload it, public (YouTube, Vimeo, Facebook Video or Youku); (6) pick a
  cover image (footage and stills of `23d81ab`, 26 Oct 23:31 CET: two Playwright takes at
  1920×1080 and seven stills in `~/footnote-media` on the devbox, outside the repo; its
  `tour.py` takes them again); (7) search
  "Footnote" among the Innovation Studio projects; (8) save the project page with the texts of
  `docs/submission.md` (pass 1: title, tagline, keywords, challenge, "open for others to join" No,
  "writing code" Yes, description with the live URL), then add the repository, the video and the
  cover (pass 2); (9) submit
- [x] LICENSE: MIT, added 19 Oct (rules 4.8 free use by judges; 4.11 allows open source)
- [x] Product name "Footnote" (decided 23 Oct, Owner decisions outside the milestone plans) in
  the README, pitch and video script (M7) and on the page (M5 item 3); the package and CLI stay
  `matchlens`. The project page and the search for "Footnote" among the Innovation Studio projects
  are in the owner's steps below
- [x] An architecture diagram in the README (Mermaid; M7 item 2)
- [ ] Own cover image for the project page (the default banner reads as a placeholder next to
  the strongest entries): the owner's step (6) below
- [x] The video shows the Guard rejecting a draft and an agent fixing it (done with the Translator's
  real refusal, see Video above; the Analyst's first drafts all passed) (a scripted `--fake` reply
  or a run that has one): "recover from failures" is a category point, and the real runs of 23 Oct
  passed 28 of 28 at the first attempt, so no recovery shows by itself
- [x] Real-name denylist in `tests/test_league.py` → SHA-256 of lower-cased names before the repo
  goes public (owner decision 19 Oct): item "Denylist hashes" above
- [ ] Innovation Studio project page (saved with the required fields = the Submission, rules 4;
  visible to all entrants). Form seen 19 Oct, not saved. Two passes, because media and the code
  repository can be added only after the first Save. Pass 1: Title* (≤ 140 chars), Tagline*
  (≤ 300), Keywords* (tags), Description (Markdown, optional, but the rules ask for a pitch),
  Challenge* (one option: "The Synthetic Match Insights Engine for Premier League Studio"),
  "open for others to join" = No, "writing code" = Yes. Pass 2: repo URL, media (the demo video
  URL presumably goes here). The form has no prize-category field: name the target category in
  the Tagline, Description and Keywords. Create it Mon 26 Oct.

Out of scope: auto-eventing from video.
