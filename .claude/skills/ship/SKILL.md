---
name: ship
description: Takes one backlog item from plan to a verified commit. Use only for an item of a milestone the owner approved in PROGRESS.md, or when the owner types /ship.
argument-hint: "[backlog item]"
---
Item: $ARGUMENTS

The steps fix the order and who does what. How you do each step is up to you.
`<base>` is the milestone branch that PROGRESS.md names for the item's milestone.
"The base tree" is the working tree where `<base>` is checked out (`git worktree list`): the main
tree, or a milestone worktree `.claude/worktrees/<base>` while two milestones run side by side.
"The diff" means `git add -N . && git diff <base>`: working tree against base, new files included.

1. Plan: a plan of 5 to 10 points. If PROGRESS.md marks the milestone approved by the owner (with
   a date) and the item stays inside its scope, go on. Otherwise show the plan and wait.
2. Worktree and branch: `git worktree add .claude/worktrees/<short-name> -b <short-name> <base>`,
   then do steps 3 to 6 inside that worktree (one task, one working tree; the owner's tree and
   anything they drop into it stay out of the diff). The first `uv run` there builds its own venv.
3. Implementation: the change including tests.
4. Verification and review, once each and at the same time (owner decision, 27 Oct): in one
   message, subagent `verifier`, told the base branch, the item's key invariants (the few whose
   mutants must die: what the item exists to guarantee) and its 15-minute budget, and subagent
   `code-reviewer`, given the diff.
5. Fixes: fix the verifier's FAIL and the review's serious findings, and the cheap advisory and
   minor findings; list the rest under Follow-ups in PROGRESS.md. Judge the fixes yourself, with
   no second round: the tests of the changed files green, and every surviving mutant the verifier
   reported, and a mutant of each fix, killed in a scratch copy. A second verifier round only
   when its FAIL was a failing test; if that round is red too, stop and write what blocks.
   Quality bar for a thin item, i.e. one of a milestone's walking-skeleton slice in PROGRESS.md
   (owner decision, 21 Oct): besides CLAUDE.md's "Done means", only the properties its plan
   names and serious findings block it. Minor findings and a mutation score never block; they
   go under Follow-ups. For any item (owner decision, 27 Oct): mutants outside the key invariants
   of step 4 never block.
6. Commit: one commit with what and why, PROGRESS.md updated in the same commit. The pre-commit
   hook runs `scripts/ci.sh`; never bypass it. Merge in the base tree. First
   `git -C <base tree> status --short`: the owner may have edited a file the item also changes;
   keep their edit (back it up, merge, carry it over, commit it as theirs) and never discard it.
   Then `git -C <base tree> merge --ff-only <short-name>`, then
   `git worktree remove .claude/worktrees/<short-name>` and
   `git -C <base tree> branch -d <short-name>` (`-d` checks the branch against the HEAD of the
   tree it runs in, so from another tree it refuses a branch that is merged). If `<base>` moved on
   meanwhile, rebase the item onto it and run `scripts/ci.sh` again (a rebase does not run the
   pre-commit hook).
   Only the owner merges a milestone branch into `main`.
7. Lesson: if you hit a mistake that can repeat, propose one sentence for Lessons in CLAUDE.md.
