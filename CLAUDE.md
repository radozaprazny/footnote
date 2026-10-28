# Footnote (product name; package and CLI `matchlens`)

## What this is
Hackathon entry (Microsoft "Inside the Game", target category: Best Multi-Agent System). A pipeline
turns a synthetic, fictional football match into explainable, personalized on-screen intelligence:
Ingest → Interpret (deterministic stats engine) → Explain (agents) → Render (overlay cues) → Personalize.
Rules: the hackathon's Official Rules (Hackathon Website https://aka.ms/insidethegame), Microsoft's
text and so not in the repo: local copies in the gitignored `docs/RULES.md` and
`docs/resource-playlists.md`; where missing, restore them in the private repository with
`for f in RULES.md resource-playlists.md; do git show 5eb247e:docs/$f > docs/$f; done`.
Status, backlog and metrics: `PROGRESS.md`.

## Commands
- Tests: `uv run pytest -q`
- Lint and format: `uv run ruff check . && uv run ruff format .`
- Local CI (the independent judge): `scripts/ci.sh`, the whole suite, run by GitHub CI and before
  a merge into main or a deploy. The git pre-commit hook runs `scripts/ci.sh --changed`: the lint
  and the tests of the staged files, imports between the modules in `src/` followed (owner
  decision, 27 Oct)
- One-time setup after a clone (owner runs it; the guard blocks it for Claude):
  `git config core.hooksPath .githooks`
- Browser for the end-to-end tests and the scripts, once after a clone (the pre-commit hook needs
  it): `uv run playwright install chromium`
- Container smoke test (builds the image and runs it as Azure Container Apps does, at 0.25 vCPU and
  512 MB, with timings): `scripts/container.sh`
- Deploy to Azure Container Apps, only with the owner's OK (runbook: `docs/deploy.md`):
  `scripts/deploy.sh`

## Done means
- the pre-commit hook is green (the tests of the change); the whole `scripts/ci.sh` before a
  merge into main or a deploy
- new logic has its own test; every stats-engine computation has at least one Hypothesis property
- the changed part was run for real once (CLI, endpoint, stream)

## Rules
- Fictional clubs and players only. Never real club or player names, logos, crests or kits.
- The stats engine is deterministic and never calls an LLM. Agents do not compute numbers or
  judge them: every number and every judgement word (a reading's phrase, such as "take the lead"
  or "on top") in a narrative comes from the stats engine, and every claim carries an event ID (a
  tracking value carries frame IDs instead).
- Everything in the repo and every submission material is in English.
- Never push, publish, create or change a GitHub repo, or submit without the owner's explicit OK.
- Azure: read-only commands are fine. Creating or changing billed resources needs explicit OK.
- New dependencies only if the approved milestone plan in `PROGRESS.md` lists them; otherwise ask.
- A milestone is approved only when the owner says so in chat. Only then write
  "approved by owner, <date>" next to it in `PROGRESS.md`.
- Never delete or weaken tests without the owner's OK.
- Announce every change to the harness: `.claude/`, `.githooks/`, `scripts/ci.sh`, `.github/`.
- Times for the owner are in Bratislava local time (CEST until Sun 25 Oct 2026, CET after).

## Lessons
- One session = one working tree. Run a background `/ship` only in its own git worktree.
- In a `&&` chain never pipe a command whose failure must stop the chain: `| tail` hides its
  exit code (a failed merge once let the next command remove its worktree).
- Pin every threshold and boundary from both sides (exactly on it and one unit off), and add every
  field or optional parameter a change introduces to an existing Hypothesis property in the same
  change; random values and an example at period 1, clock 0 pin nothing.
- A test that takes a boundary from the module's own constant (`CIRCLE + MARGIN`) moves with it and
  pins nothing: write the rule's number once as a literal (9.15).
- For a float bound, put one input exactly on it (search for it, and assert the equality in the
  test): a millimetre on each side leaves `<` against `<=` alive.
- Create an item worktree with a path from the main tree (`git -C <main tree> worktree add
  .claude/worktrees/<name>`): a relative path run inside a milestone worktree nests the new tree
  in it, and moving it later breaks its venv's script paths.
- A verifier mutates only a copy of the worktree, never the live tree: the Stop hook runs the tests
  whenever the session pauses, and a mutant left in place fails it.
- A surviving mutant counts only after you have confirmed that it really changes behaviour
  (`1 || a ? b : c` is still `b`).
- A subcommand's option never takes the name of an attribute the CLI dispatches on (`run`,
  `error`): give it its own `dest`.
- `pgrep -f` or `pkill -f` with a pattern from your own command line matches your own shell: find
  a server by its port (`ss -ltnp`).
- Never name a helper module after a stdlib module: `scripts/site.py` loses to the `site` that
  Python has already imported.
- Before a billed run, measure the tokens per attempt in a smoke run and pace the run so it stays
  under the deployment's tokens per minute: with no SDK retries a 429 is a lost attempt.
- A denylist exception added to stop a false rejection is a new bypass until a test pins it from
  both sides: the ordinary phrase passes AND the judgement it resembles is still refused (`in
  behind` vs `remain behind`).
- For a rule built on a word list, a verifier's FAIL is the plan and the docstring's contract
  only: a new phrasing outside the list is a known limit to record, not a red round.
- A colour made readable must reach its contrast on every surface it colours text on (page,
  cards, chips), measured in the browser, not only on the page background.
- For a word-list rule in a second language, mirror the first language's list entry by entry and
  cover every form a translator writes (prefixes such as `ne-` and `z-`, declensions, aspect)
  before the first review: item 6 spent three red rounds on forms the Slovak lists lacked.
- When a script splices a file at an anchor string, assert the anchor occurs exactly once;
  `str.index` takes the first hit, and an anchor repeated in a just-written comment once cut
  `container.sh` from line 23.
- Under `set -o pipefail`, a reader that exits early (`grep -q`, `head`) SIGPIPEs the writer and
  flips the pipeline's status, so `if a | grep -q bad; then fail; fi` can miss a match: capture
  the output in a variable and count with `grep -c`.
- Run mutants in a scratch copy, never in the item's worktree: a killed mutant loop once left
  the old `app.js` in place.
- In a `set -e` script, decide whether to create with a lookup that fails loudly as a plain
  assignment (`n=$(az … list --query …)`), never `show 2>/dev/null || create`: any error then
  passes for "missing" and the create lands on the live resource.
- Commands the owner pastes never put `!` inside double quotes: an interactive bash expands it
  as history and prints "event not found" (use KQL `not(…)`, single-quoted JMESPath).
- Never spell out a real club or player name in committed text, not even as a mutant's
  description or an example of what a check misses: write "a real club's name". M6's demo runs
  lost two red rounds to PROGRESS.md.
- After a change to what the server does before it binds, run `scripts/container.sh` again: a
  measured constant in a test goes stale silently (`COLD_START_S` pinned 29.9 s while the real
  start had grown to 206 s, beyond the startup probe's window).
- When a test's literal data is hashed, keep a test that ties the hashed constants to their
  checks (a known digest, each check reading its own list): else an emptied check still passes.
- `git rm --cached` deletes the file from every tree that later merges or checks out the commit,
  so a "local copy" needs a restore command, and a test that reads it a fallback.
- While the pre-commit CI runs, run nothing heavy beside it: timing tests flake under CPU load.
- Before a verifier round, sweep the key invariants' mutants yourself in a scratch copy with the
  fast tests: five rounds each found the next gap, one at a time.
