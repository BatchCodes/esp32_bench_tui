---
name: mdbd-plan
description: Draft a markdown plan from a prompt or brief for review. Refine the plan against open questions. Convert approved steps into bd (beads) issues and start the work. Use this skill for "plan this out", "write a plan for X", "/mdbd-plan", "continue the plan", or "implement steps N-M of the plan". Plans are markdown files for humans. Beads issues track execution for agents. Do not use TodoWrite or separate TODO files for these implementation steps.
---

# mdbd-plan

This skill runs in two phases. The first phase drafts and refines a markdown
plan until no open questions remain. The second phase implements the plan.
It turns approved steps into bd issues. It does the work. The invocation
command selects the phase and mode.

## Where plans live

Each body of work has one file at `.claude/plans/<SLUG>.md`. `<SLUG>` is a
SHOUT_CASE name for the work's subject, for example
`BUTTON_DEBOUNCE_SETTINGS.md`. Keep the slug short enough to read as a
filename. Use 3 to 6 words.

## Plan file format

The frontmatter has a fixed format. The skill reads and writes the
frontmatter as its state. The content below the frontmatter is a normal
markdown document. This content can grow to match the size of the work. A
one-paragraph fix and a multi-week feature should not have the same length.

```markdown
---
slug: BUTTON_DEBOUNCE_SETTINGS
status: draft   # draft -> questions_open -> ready -> implementing -> done
created: 2026-09-18
epic: null      # bd id of the parent epic issue, filled in on first --implement
---

# Button Debounce Settings

## Current State
Add as much research and context as the work needs. Include existing
behaviour, relevant code (link it with `file.py#L12` references), and
constraints found during investigation. Skip this section for small,
self-contained work. Do not pad it.

## Goal
State what "done" looks like, in one or two sentences.

## Open Questions
- [ ] Q1: <question needing a user decision>
- [ ] Q2: <question needing a user decision>

## Decisions
- <answered question> -> <the decision, and why, once settled>

## Implementation Steps
1. [ ] (bd: none) Step description
2. [ ] (bd: none) Step description
3. [ ] (bd: none) Step description

## Findings
(Added during `--implement`. See Mode: implement below.)
```

| `status` value | Meaning |
|---|---|
| `draft` | The plan is a first draft. No one has reviewed it. |
| `questions_open` | The plan has one or more unchecked items under Open Questions. |
| `ready` | All questions have answers. The steps are stable. No step has a bd issue yet. |
| `implementing` | At least one step has a bd issue. |
| `done` | All step issues are closed. |

A bd issue signals approval for its step. See Mode: implement below. Do not
create a bd issue for a step until an `--implement` call names it.

### Phases

Some work splits naturally into stages. Each stage gets approval and
implementation at a different time. Examples: an MVP now, an extension
later, or a "future work" tail with no commitment yet.

For staged work, use `## Phase N: <name>` headings instead of one flat step
list. Each phase has its own `Implementation Steps` list. Number the steps
within a phase, for example `3.1` and `3.2` for phase 3. If a phase's
decisions differ from the plan's overall decisions, give the phase its own
`### Decisions` subsection.

A phase can start as a placeholder, with a "not started" note and no steps.
A later `--continue` call can add real steps and questions to that phase,
when the user is ready to plan it. This does not disturb phases already
implemented.

Each `--implement` call covers steps in one phase only, for example
"implement phase 1 steps 1-3". An `--implement` call never reaches into a
phase with no plan yet.

## Mode: new plan

The user starts this mode with `/mdbd-plan <topic text>` or
`/mdbd-plan <path/to/brief.md>`. Use this mode only when no plan file exists
yet for the subject.

1. If the user gives a path, read that file as the brief. If not, treat the
   prompt text as the brief.
2. Derive the SHOUT_CASE slug. Confirm that `.claude/plans/<SLUG>.md` does
   not already exist. If it exists, switch to the continue mode instead.
3. Draft the Goal section and the Implementation Steps section from the
   brief. Add a Current State section if the brief needs real investigation.
   Read the relevant code for that section and link it.
   Make each step concrete, ordered, and scoped to one bd issue. Do not
   write a step so small that it is trivial. Do not write a step so broad
   that it hides sub-decisions.
   If the work has natural stages for separate approval, split the steps
   into `## Phase N` sections. See Phases above.
4. Write each real ambiguity, each missing input, and each judgment call for
   the user as a checkbox under Open Questions. Do not invent questions to
   fill the section. An unambiguous brief can have zero open questions.
5. Set `status` to `questions_open` if the plan has open questions.
   Otherwise set `status` to `ready`. Write the plan file and stop.
   Show the user the open questions. If there are none, tell the user the
   plan is ready to implement. Do not create bd issues yet.

## Mode: continue

The user starts this mode with `/mdbd-plan --continue [SLUG]`. The slug is
optional when only one plan has `status: questions_open` or `status: draft`.

1. Read the plan file. The user's answers can arrive in two ways. The
   answers can appear inline in the chat message. The answers can already be
   in the file, for example as checked boxes, an edited Decisions section,
   or edited steps.
2. For each answered question, check its box. Add a line under Decisions
   that states the decision and the reason for it. Use the phase's own
   `### Decisions` subsection if the question belongs to one phase.
   Otherwise use the top-level Decisions section.
   Update the Current State section, the Goal section, or the affected
   steps to match the decision.
3. Check the plan for new ambiguity that the answers exposed. A decision
   often opens a follow-up question. Add only genuinely new questions. Do
   not ask again about a question the user already answered.
4. If unresolved or new questions remain, set `status` to `questions_open`.
   Show the questions to the user and stop.
5. If no questions remain, set `status` to `ready`. Tell the user the plan
   is ready. Name the `--implement` command to run next.

## Mode: implement

The user starts this mode with `/mdbd-plan --implement <SLUG> [range]`.
`range` is a step number, a comma list, or a hyphen range, for example `3`,
`2,4`, or `1-3`. If the user omits `range`, it means all steps that do not
yet have a bd issue.

1. Refuse this request if `status` is `draft` or `questions_open`. Tell the
   user which questions are still open and stop.
   The user can explicitly override this refusal. If the user does, note
   the skipped questions in the epic issue's description.
2. Set `status` to `implementing` immediately, before creating or touching
   any bd issue. Write the plan file with this status right away. This
   keeps the plan file honest about being mid-implementation even if issue
   creation, linking, or the work itself gets interrupted partway through.
3. If `epic` is `null` in the frontmatter, first check for a stray epic
   from an earlier, interrupted `--implement` call: run
   `bd search "<plan title>"` or `bd list` and scan for an epic with a
   matching title. If one already exists, use its id instead of creating a
   new one, and record it in the frontmatter now.
   Otherwise create the epic issue: run
   `bd create --type=epic --title="<plan title>" --description="<Goal section>. Plan: .claude/plans/<SLUG>.md"`.
   Capture its id safely: redirect the command's output to a file (or a
   variable) and extract the id from that saved output with a pattern that
   matches the full id, dot-suffix included (bd ids look like
   `<epic-slug>.<N>`, for example `myproj-abcd.3` — a pattern that stops at
   the first non-word character truncates this and silently captures the
   epic id instead). Record the id in the frontmatter.
4. Before creating any step issues, run `bd children <epic-id>` and check
   whether issues with matching titles already exist there (from an earlier
   interrupted run of this same `--implement` call). If they do, reuse
   their ids instead of creating duplicates.
   For each step in the range that still shows `(bd: none)` and has no
   existing match, do the following.
   - Run `bd create --type=task --parent=<epic-id> --title="<step text>" --description="<step detail>. Link: .claude/plans/<SLUG>.md"`,
     capturing its id with the same safe extraction as step 3 above.
   - Link the step to whichever earlier step or steps it actually reads or
     depends on, not merely "the step before it" in the list — two steps
     that both build on an earlier step, but not on each other, should
     both link to that earlier step and not to each other. Skip linking
     entirely for a step with no real dependency on another step in the
     range. Run `bd link <this-step-id> <depended-on-step-id>` once per
     real dependency.
   - Replace `(bd: none)` in the plan file with `(bd: <id>)` for that step,
     writing the file immediately rather than batching this update until
     the whole loop finishes.
   After the loop, run `bd children <epic-id>` again and confirm the
   number of children matches the number of steps now carrying a `(bd:
   <id>)` in this plan (accounting for any steps outside the range, which
   still show `(bd: none)`). A mismatch means a duplicate got created;
   find and close the duplicate with a reason before continuing.
5. Run `bd ready`. Claim exactly one ready step from this plan's epic at a
   time, with `bd update <id> --claim`, immediately before starting that
   step's work. Do not claim a second step until the first is closed.
   Implement the step directly. Write the code yourself. Do not hand the
   step off to another process.
   Close the step with `bd close <id>` as soon as it is done, before
   claiming the next one. Do this even when one piece of work naturally
   satisfies several planned steps at once (for example, one file that
   covers what were written up as three separate steps): claim, close,
   claim, close, in immediate succession, rather than claiming several
   steps up front and closing them all together at the end. `bd list`
   and `bd ready`, checked mid-run, should always show at most one step
   from this epic `in_progress`, matching whichever step is actually being
   worked on right now, not the first step in the range regardless of
   which step's work is actually happening.
   If a planned step turns out to be unnecessary once you reach it (a
   decision made it moot, or an earlier step already covered it), do not
   leave it open and do not silently drop it. Claim it, then close it
   immediately with a reason explaining why it was not needed. Do not
   open a new issue for this case; the existing step issue already covers
   it.
   Repeat this claim-work-close cycle until the requested range is
   finished, or until something blocks progress.
6. After closing steps, run `bd children <epic-id>`. If it shows no open
   children, set `status` to `done` in the plan file.

Steps outside the requested range stay as `(bd: none)`. A step with no bd
issue has no permission for implementation yet. A later `--implement` call
with a new range grants that permission.

### Unplanned work found mid-implementation

Real implementation work often finds things the plan did not anticipate.
Examples: a hidden second registration list, a config file that also needs
an entry, or a pre-existing bug next to the change. Handle each finding by
its size.

- **Small** finding, for example a missed field mapping or a one-line guard:
  fix it directly. Add one line under `## Findings` in the plan file. State
  what was wrong, how you found it, and what fixed it. This line is a record
  for humans. It is not a tracked task.
- **Real, separate work**, for example a bug worth its own fix, or a
  follow-up with no commitment yet: create a bd issue for it. Run
  `bd create --deps discovered-from:<step-id> ...` to link the new issue to
  the step that found it. Note this issue under `## Findings` too. Do not
  add unrelated scope to the current step's issue.

Do not let either case block the step in progress. The exception: if the
finding invalidates the step itself, stop. Explain why, and treat the
finding as a new open question. Do not push through.

## Notes

- This skill creates the bd issues. It does not replace the session-close
  protocol from `bd prime`. Close the work you finished. Leave the rest in
  the ready state.
- Do not use TodoWrite or TaskCreate for these steps. This repo's convention
  makes bd the tracker.
