# Layer 1 slice plan: the business interview (planned, not built)

Status: written before the build, kept as the plan. Layer 1 has since been built and run once in
Snowflake (ADR-015); the README describes what runs. Tasks and acceptance tests below are the
original plan, not a record of what passed. The closed-loop figure of 794 below was the value on the
day of the original runs; it moves with the date (ADR-004).

## Goal

A business user with no data knowledge opens a Streamlit in Snowflake app, is interviewed in their own
words about one term, confirms a plain-language read-back, and the result lands in the `GLOSSARY` table
the mapper already reads. One term, end to end, then the mapper runs on it.

## Why this slice

Layers 2 and 3 take their meaning from `glossary/terms.yaml`, which a person wrote by hand (ADR-011).
Until an interview produces that file, the tool cannot be used by the people it is for. The Requirements
Accelerator already proved the interview pattern; this slice reuses it and aims it at a different
output: a glossary entry, not a requirements spec.

## Scope

In:
1. One Streamlit in Snowflake app, one term per session.
2. A Cortex-driven interview that collects the fields a glossary entry holds: term, owner, definition,
   exclusions, synonyms, the unit counted, breakdowns, systems mentioned in the user's words, why it
   matters, and the questions people ask.
3. A plain-language read-back the user confirms or corrects before anything is saved.
4. Save to `INTERVIEW.TERM_DRAFTS`, then a promotion step that copies a confirmed draft into `GLOSSARY`.
5. A closed-loop test: run `MAP_TERM` on a term that came out of the interview.

Out (later slices): engineer review screen, semantic view generation, Cortex Analyst validation,
multi-term sessions, user authentication beyond Snowflake's own, voice input.

## Design decisions to make and record as ADRs

- **Business language only (ADR-001, enforced).** The app role has no access to the estate, so it
  cannot leak names. The interview prompt forbids schema words, and an output check rejects any reply
  containing an identifier from a denylist built once by the engineer from the profile. Decide whether
  the denylist is worth its complexity or the missing grants are enough.
- **Isolation (ADR-007, ADR-012).** A new role, `SVC_INTERVIEWER`, owns schema `SVC_APP.INTERVIEW`,
  has Cortex access and nothing on the estate or `EVAL`. Promotion into `GLOSSARY` is a procedure the
  mapper side owns, so the interviewer never writes to the mapper's schema directly.
- **What the user confirms.** The read-back is the entry rendered as sentences ("You count someone as
  engaged if they redeemed points or opened a programme email in the last 60 days. Not just if their
  card is still active. Right?"). Corrections loop back to the interview; they never edit JSON.
- **Shape.** The saved draft uses the same fields as a `terms.yaml` entry, so the mapper needs no change.
- **Conversation state.** Kept in a table keyed by session, not in browser storage, so a user can
  resume and an engineer can audit what was asked.

## Tasks, in order

1. Create `SVC_INTERVIEWER`, the `INTERVIEW` schema and `TERM_DRAFTS` / `INTERVIEW_TURNS` tables
   (`sql/09_interview_setup.sql`).
2. Write the interview prompt and the field-completeness check as plain Python with offline unit tests,
   using the same fake-session pattern as the mapper tests.
3. Build the Streamlit app: chat panel, field checklist, read-back and confirm screen.
4. Write `PROMOTE_TERM(draft_id)`: validates the draft has every required field, then inserts into
   `GLOSSARY`.
5. Closed-loop test with a simulated business user (see below), then run `MAP_TERM` on the result.
6. Write the ADRs, update the README, record a short demo.

## Acceptance tests

- **Completeness:** an interview cannot be confirmed with a required field missing.
- **Language:** across a scripted set of interviews, no reply shown to the user contains a table or
  column name. Run offline first, then in Snowflake.
- **Closed loop:** an interview that reproduces T3's glossary entry produces a draft whose `MAP_TERM`
  run chooses the same sources as the hand-written entry and returns 794.
- **Isolation:** `SVC_INTERVIEWER` fails on any query against the estate and on `EVAL`.

## Test-honesty note

The first interviews will be played by a simulated business user, an LLM given each term's answers from
`terms.yaml`. That tests the app's mechanics, not whether real people give usable answers. Any claim
must say so. A real interview with a colleague playing the business owner is the proper test and
should follow before the project is described as validated.

## Risks

- **Trial ends 12 October.** Streamlit in Snowflake and Cortex need the account. The app can be
  developed and unit tested offline, but the closed-loop test needs the trial. If the trial lapses
  first, the app is built to Snowflake-native patterns and is re-hosted when an account is available.
- **Cortex flakiness (ADR-013).** The interview needs shorter prompts than the mapper, but the same
  retry and clear-failure handling applies.
- **Interviews that drift.** A free-form chat can skip fields. The field checklist, not the model,
  decides when the interview is complete.

## Time estimate

About five to six focused sessions of an hour or two, in the task order above. The first three tasks
are doable before the trial ends; the closed-loop test (task 5) is the one that needs the account.
