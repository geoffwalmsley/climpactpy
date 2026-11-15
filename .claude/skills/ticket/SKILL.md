---
name: ticket
description: Use when adding, planning or breaking down work into tickets, when picking the next thing to work on, and when starting, opening a PR for, or finishing a ticket in climpactpy. Tickets are GitHub issues on the climpactpy Kanban project board. Covers the issue template (including parity coverage), board fields, epics and moving cards through the workflow.
---

# Tickets on the climpactpy Kanban

All planned work lives on the **[climpactpy Kanban](https://github.com/users/geoffwalmsley/projects/2)**, a GitHub Project (user project #2, owner `geoffwalmsley`). Each card is a GitHub **issue** in `geoffwalmsley/climpactpy`. Don't keep tickets as markdown files in the repo.

`gh` needs the `project` scope (`gh auth status` should list it). If it's missing, ask the user to run `gh auth refresh -h github.com -s project` in their own terminal, since it needs a browser login.

## Board reference

```
Project node ID: PVT_kwHOAFbo984BraA5
Status   field PVTSSF_lAHOAFbo984BraA5zhps4so  Backlog f75ad846 | Ready 61e4505c | In progress 47fc9ee4 | In review df73e18b | Done 98236657
Priority field PVTSSF_lAHOAFbo984BraA5zhps4zo  P0 79628723 | P1 0a877460 | P2 da944a9c
Size     field PVTSSF_lAHOAFbo984BraA5zhps4zs  XS 6c6483d2 | S f784b110 | M 7515a9f1 | L 817d0097 | XL db339eb2
```
If an edit fails with an unknown ID, re-read the fields: `gh project field-list 2 --owner geoffwalmsley --format json`.

- **Status:** Backlog (not ready or blocked) → Ready (can start now) → In progress → In review (PR open) → Done.
- **Priority:** P0 (needed for R parity on stations, which is how WMO judges the port), P1 (in the WMO scope but not on the parity critical path), P2 (nice to have).
- **Size:** XS (< 1 hour), S (half a day), M (1–2 days), L (3–5 days), XL (too big, so split it; only epics are XL).

**Built-in board automations (already on, don't duplicate them):** new repo issues and sub-issues are auto-added to the board; a linked PR merging closes its issue and moves the card to Done; a card moved to Done closes its issue. The "item added" automation sets a default status, so always set Status explicitly after adding a card and **verify it stuck**.

**Epics** (label `epic`). Make every ticket a sub-issue of the right one:

| # | Epic | Covers |
|---|------|--------|
| #8 | Station index parity with Climpact R | indices, thresholds, trends, CSV writer, batch, performance |
| #9 | Quality control port | QC CSV outputs, QC module |
| #10 | Gridded (netCDF) data | gridded thresholds and indices |
| #11 | Web front end | split into children before starting |
| #12 | Containers, deployment and handover | split into children before starting |

Cross-cutting tickets (for example the plugin interfaces, #28) and decision tickets sit outside the epics.

**Labels:** `enhancement`, `bug`, `documentation`, `question`, `epic`, `parity` (changes which R reference files pass), `qc`, `gridded`, `web`, `infra`, `performance`, `wmo-decision` (a scope or acceptance decision WMO would normally make. WMO cannot be consulted, so bring the options and a recommendation to the user, record their decision in the issue and in `TECHNICAL.md`, then close it).

## Adding a ticket

1. **Check for duplicates first:** `gh issue list --repo geoffwalmsley/climpactpy --state all --search "<keywords>"`.
2. **Read the code**, both the Python (`packages/climpact/src/climpact/...`) and the R it ports (`../climpact/server/climpact.etsci-functions.r`, `../climpact/services/...`, climdex.pcic), so the paths, functions and line numbers in the ticket are real. Read `TECHNICAL.md` and `CLAUDE.md`. Don't reopen decisions the user has already made.
3. **Plan the parity coverage.** Every ticket gets a **Parity coverage** section: list the reference files (`packages/climpact/tests/parity` ids such as `indices/gsl_ANN`) that should go from xfail to pass, for which runs (`lat0`, `sydney`), and at which tier. If no reference output exists yet (gridded, northern hemisphere), say how one will be produced with the Docker image in `reference/r`. If behaviour shouldn't change, write "No change: everything that passes now still passes".
4. **Write the body** using the template below, saved to a temp file.
5. **Create, add to the board and set fields.** Run these one ticket at a time, and record each issue number before moving on. A failed batch retry creates duplicate issues.
   ```bash
   R=geoffwalmsley/climpactpy; P=PVT_kwHOAFbo984BraA5
   url=$(gh issue create --repo $R --title "<Title>" --body-file /tmp/body.md --label enhancement,parity)
   # The board auto-adds the issue, so item-add may report "already exists", and the item may take
   # a few seconds to show up in item-list. Retry the lookup until it returns an id:
   item=$(gh project item-add 2 --owner geoffwalmsley --url "$url" --format json --jq .id 2>/dev/null)
   for i in 1 2 3 4 5; do [ -n "$item" ] && break; sleep 3
     item=$(gh project item-list 2 --owner geoffwalmsley --format json --limit 300 --jq ".items[] | select(.content.url==\"$url\") | .id"); done
   gh project item-edit --id "$item" --project-id $P --field-id PVTSSF_lAHOAFbo984BraA5zhps4so --single-select-option-id <status-option>
   gh project item-edit --id "$item" --project-id $P --field-id PVTSSF_lAHOAFbo984BraA5zhps4zo --single-select-option-id <priority-option>
   gh project item-edit --id "$item" --project-id $P --field-id PVTSSF_lAHOAFbo984BraA5zhps4zs --single-select-option-id <size-option>
   ```
6. **Make it a sub-issue of its epic** (this takes the issue's database `id`, not its number):
   ```bash
   gh api -X POST repos/geoffwalmsley/climpactpy/issues/<epic>/sub_issues -F sub_issue_id=$(gh api repos/geoffwalmsley/climpactpy/issues/<N> --jq .id)
   ```
7. **Verify:** `gh project item-list 2 --owner geoffwalmsley --format json --limit 300 --jq '.items[] | "#\(.content.number) \(.status) \(.priority) \(.size)"'`. Fix any card whose fields are `null`.
8. **Report the issue link(s)** to the user, with the Status, Priority and Size you set.

### Issue template
```markdown
## Context
Why this exists and where it fits. 2–5 sentences. Name the R code being ported (file:line or the
climdex.pcic function). Link related issues/PRs (#N). State dependencies as "Depends on #N".

## Scope
Concrete bullets naming real files (`packages/climpact/src/climpact/...`) and the outputs produced.
Include non-obvious design decisions and their reasoning (for example, xclim vs a direct port).

## Out of Scope            (optional)

## Implementation Notes    (optional: R quirks to reproduce, tie/rounding risks, hemisphere rules, edge cases)

## Parity coverage
Reference files expected to pass (ids, runs, tier), how a missing reference will be produced,
or "No change: everything that passes now still passes".

## Acceptance Criteria
- [ ] Observable, testable outcomes (named reference files pass at the stated tier)
- [ ] Unit tests for new algorithms, including R quirks that no reference run exercises
- [ ] `ruff check`, `ruff format --check`, `pytest` pass
- [ ] `TECHNICAL.md` updated (see the `update-technical-docs` skill)
```

**Sizing:** one ticket should be one reviewable PR (S–L). If it's XL, split it into sub-issues. Say what and why, plus enough how to remove ambiguity, but don't write the implementation. Call out risk explicitly (bootstrap or tie sensitivity, fitted distributions that may need the FITTED tier, anything that needs a user decision or a new R reference run). Put open questions in the issue and bring them up with the user instead of guessing.

## Working a ticket

1. **Pick:** take the highest-priority **Ready** card, or the one the user names. Check its "Depends on" issues are Done. If a Backlog card's blockers are cleared, move it to Ready.
   ```bash
   gh project item-list 2 --owner geoffwalmsley --format json --limit 300 \
     --jq '.items[] | select(.status=="Ready") | "#\(.content.number) \(.priority) \(.size) \(.title)"'
   ```
2. **Start:** move the card to **In progress**, create a branch from up-to-date `main` named `<issue-number>-<short-slug>` (for example `17-gsl`), and re-read the issue body. Comments may have changed the scope. If the issue has no "Parity coverage" section, add one now and edit the issue body.
3. **Build:** follow `CLAUDE.md` (`uv run` only). Run `uv run pytest` once and read the full parity summary from `.parity-summary.txt` (see `CLAUDE.md`; don't re-run the suite to see it). Check that the files named under Parity coverage moved from xfail to pass, and that nothing that passed before now fails. Save a copy of the summary from `main` before changing code if the PR needs a before → after comparison. If you find extra work, or a Python/R difference you can't resolve, file a new ticket rather than growing the scope. Tick acceptance criteria in the issue body as you meet them (`gh issue edit <N> --body-file`).
4. **Docs:** update `TECHNICAL.md` in the same branch using the `update-technical-docs` skill.
5. **PR:** commit and push only when the user asks. Open the PR against `main` with **`Closes #N`** in the body, the parity summary from the test run (before → after), and the Documentation note. That's what lets the automations close the issue and move the card to Done on merge. Then move the card to **In review**. Link the PR in T3 (`link_pull_request`).
   - **Stacked PRs:** if the base isn't `main`, the `Closes` link won't fire. After the user merges, check the issue closed, and that the commits actually reached `main`, since a stacked PR can merge into its parent branch after the parent has already merged.
6. **Done:** never merge the PR yourself; only the user merges (with a merge commit, see `CLAUDE.md`). Once CI is green, say the PR is ready to merge. After the user merges, confirm the issue is closed and the card is in Done. Move any Backlog cards it unblocked to Ready. Leave a short comment listing anything left over, and file follow-ups as new tickets.

Report honestly: if an acceptance criterion wasn't verified (for example, a file passes only at a looser tier than planned), leave it unticked and say why in the issue.
