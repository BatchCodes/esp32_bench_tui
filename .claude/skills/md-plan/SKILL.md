---
name: md-plan
description: Draft a markdown plan from a prompt or brief for review. Refine the plan against open questions. Implement the approved steps directly, checking each one off in the plan file as it finishes. Use this skill for "plan this out", "write a plan for X", "/md-plan", "continue the plan", or "implement steps N-M of the plan" in a repository that does not have bd (beads) installed. If bd is installed, use the mdbd-plan skill instead — it tracks the same steps as bd issues.
---

# md-plan

This is the plain-markdown counterpart to `mdbd-plan`, for a repository with
no bd (beads) issue tracker. It runs the same two phases. The first phase
drafts and refines a markdown plan until no open questions remain. The
second phase implements the plan directly, checking off each step in the
plan file as it finishes. The plan file itself is the only tracker. The
invocation command selects the phase and mode.

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
1. [ ] Step description
2. [ ] Step description
3. [ ] Step description

## Findings
(Added during `--implement`. See Mode: implement below.)
```

| `status` value | Meaning |
|---|---|
| `draft` | The plan is a first draft. No one has reviewed it. |
| `questions_open` | The plan has one or more unchecked items under Open Questions. |
| `ready` | All questions have answers. The steps are stable. No step is checked off yet. |
| `implementing` | At least one step is checked off, and at least one is not. |
| `done` | Every step in every phase is checked off. |

A checked step (`[x]`) means it is finished, not merely approved. Unlike
`mdbd-plan`, there is no separate issue-creation event to mark permission —
naming a step in an `--implement` range is itself the permission to start
it, and checking the box is the record that it is done.

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

The user starts this mode with `/md-plan <topic text>` or
`/md-plan <path/to/brief.md>`. Use this mode only when no plan file exists
yet for the subject.

1. If the user gives a path, read that file as the brief. If not, treat the
   prompt text as the brief.
2. Derive the SHOUT_CASE slug. Confirm that `.claude/plans/<SLUG>.md` does
   not already exist. If it exists, switch to the continue mode instead.
3. Draft the Goal section and the Implementation Steps section from the
   brief. Add a Current State section if the brief needs real investigation.
   Read the relevant code for that section and link it.
   Make each step concrete and ordered, and scope it to one sitting of
   work — not so small that it is trivial, not so broad that it hides
   sub-decisions.
   If the work has natural stages for separate approval, split the steps
   into `## Phase N` sections. See Phases above.
4. Write each real ambiguity, each missing input, and each judgment call for
   the user as a checkbox under Open Questions. Do not invent questions to
   fill the section. An unambiguous brief can have zero open questions.
5. Set `status` to `questions_open` if the plan has open questions.
   Otherwise set `status` to `ready`. Write the plan file and stop.
   Show the user the open questions. If there are none, tell the user the
   plan is ready to implement. Do not start any step yet.

## Mode: continue

The user starts this mode with `/md-plan --continue [SLUG]`. The slug is
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

The user starts this mode with `/md-plan --implement <SLUG> [range]`.
`range` is a step number, a comma list, or a hyphen range, for example `3`,
`2,4`, or `1-3`. If the user omits `range`, it means all steps that are not
yet checked off.

1. Refuse this request if `status` is `draft` or `questions_open`. Tell the
   user which questions are still open and stop.
   The user can explicitly override this refusal. If the user does, note
   the skipped questions under `## Findings` before continuing.
2. Set `status` to `implementing` immediately, before starting any step.
   Write the plan file with this status right away. This keeps the plan
   file honest about being mid-implementation even if the work gets
   interrupted partway through.
3. Work through the steps in the requested range, in order. Skip any step
   already checked off — this is what makes a re-run after an interruption
   safe: the checkboxes are the only state, so resuming just continues from
   the first unchecked step in the range.
   For each unchecked step:
   - Implement it directly. Write the code yourself. Do not hand the step
     off to another process.
   - Check its box (`[x]`) as soon as it is done, and write the plan file
     immediately, before moving to the next step. Do not batch several
     steps' checkbox updates until the end.
   - If a planned step turns out to be unnecessary once you reach it (a
     decision made it moot, or an earlier step already covered it), still
     check its box. Add a one-line note under `## Findings` explaining why
     it was not needed, instead of leaving it open or deleting it.
4. After the requested range is finished, check every step in every phase
   of the plan. If all are checked off, set `status` to `done`. Otherwise
   leave `status` as `implementing`.

Steps outside the requested range stay unchecked. An unchecked step has not
been started. A later `--implement` call with a new range is how the user
authorizes it.

### Unplanned work found mid-implementation

Real implementation work often finds things the plan did not anticipate.
Examples: a hidden second registration list, a config file that also needs
an entry, or a pre-existing bug next to the change. Handle each finding by
its size.

- **Small** finding, for example a missed field mapping or a one-line guard:
  fix it directly. Add one line under `## Findings` in the plan file. State
  what was wrong, how you found it, and what fixed it.
- **Real, separate work**, for example a bug worth its own fix, or a
  follow-up with no commitment yet: do not fold it into the current step.
  Add a new unchecked step to the Implementation Steps list (in the current
  phase, or a new "Future work" phase if it does not belong to this change),
  so it is not lost, and add a line under `## Findings` describing it and
  pointing at that new step.

Do not let either case block the step in progress. The exception: if the
finding invalidates the step itself, stop. Explain why, and treat the
finding as a new open question. Do not push through.

## Notes

- The plan file's checkboxes are the durable record of progress across
  sessions. If you also use TodoWrite during a session for finer-grained
  scratch tracking, mirror the real state back onto the plan file's
  checkboxes before you stop working — the plan file, not TodoWrite, is
  what the next session or the next `--implement` call reads.
- This skill has no bd dependency. If the repository has bd (beads)
  installed, prefer the `mdbd-plan` skill instead, so implementation work
  is visible to `bd ready`/`bd list` alongside everything else being
  tracked there.
