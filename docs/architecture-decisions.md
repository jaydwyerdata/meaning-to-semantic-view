# Architecture decisions

Running log of design decisions, findings and their reasoning. The README states current state;
this file holds how it got there.

## ADR-001: Business users supply meaning only (3 October 2026)

**Decision.** SMEs are never shown a table or column name. They describe concepts, measures,
time logic, exclusions and the questions they ask, in their own words. Translating that into
physical structure is the tool's job, confirmed by an engineer.

**Why.** The people who hold the meaning cannot judge grain, join keys or fan-out, and asking them
to is how bad semantic models get built. Validation with SMEs uses example rows rendered in plain
language ("these 10 customers count as active, right?"), never schema.

**Consequence.** Three layers: capture meaning (SME-facing), map meaning to structure
(engineer-facing, Cortex proposes, engineer confirms), generate and validate (semantic view DDL,
then Cortex Analyst asked the SMEs' own questions).

## ADR-002: Build order follows the trial, not the user journey (3 October 2026)

**Decision.** Build layers 2 and 3 first, against a hand-written glossary standing in for layer 1.
Build the layer 1 interview afterwards.

**Why.** Layers 2 and 3 need a live Snowflake account (catalog metadata, query history, Cortex,
semantic views, Cortex Analyst); layer 1 does not. The trial window is the scarce resource. The
interview pattern is also already proven in the Requirements Accelerator.

## ADR-003: A deliberately messy test estate, with a separate answer key (3 October 2026)

**Decision.** Build a synthetic legacy estate with cryptic names, no comments, no declared keys,
key format mismatches, stale and decoy columns, competing dates and fan-out. Keep the correct
mappings in `eval/`, outside anything the tool reads.

**Why.** Snowflake's sample datasets have clean, descriptive names; a mapping step would look good
on them for reasons that do not transfer to a real estate. Scoring needs ground truth, and ground
truth only means something if the tool cannot see it.

**Reused, not reinvented.** The business (Alderglen Outfitters) and the SME definitions come from
the Requirements Accelerator's synthetic interview dataset, including its two real conflicts
("active customer", "on-time delivery") and its conceptual overlap ("engaged member").

## ADR-004: Deterministic, date-relative generation (3 October 2026)

**Decision.** Every generated value is `MOD(ABS(HASH(key, 'salt')), n)`, not `RANDOM()`. Dates are
offsets from the load date.

**Why.** Hash-based values are reproducible and independent of execution order or parallelism, so
reference answers are stable for a given load. Relative dates keep "in the last 90 days" meaningful
whenever the estate is rebuilt, at the cost that exact reference values change day to day; the
reference queries are rerun after each load rather than hard-coded.

## ADR-005: Volumes tuned so the stockout definition is testable (3 October 2026)

**Finding.** The first draft generated 40,000 POS transactions spread across 120 stores and 200
fast-moving SKUs. That gives under 0.01 units per store-SKU per day, so "below what we'd sell before
the next delivery" collapses to "at zero", the exact definition the SME rejected. The trap would
have existed on paper and not in the data.

**Decision.** 150,000 POS transactions, 60% of lines concentrated on 10 hero SKUs, and hero SKUs
held lean in store inventory. The smoke test now asserts both distinguishing cases exist: SKUs at
risk without being at zero, and SKUs at zero without being at risk.

## ADR-006: Offline smoke test against an emulator (3 October 2026)

**Decision.** `tests/emulator_smoke.py` runs the full DDL, load and reference queries against
fakesnow (DuckDB-backed) and asserts row counts plus the existence of each designed trap.

**Limits, stated plainly.** The emulator rewrites the hash expressions (its HASH is unsigned) and
does not replicate Snowflake exactly, so emulator values differ from a real load. It catches syntax
and logic errors before trial credits are spent; it does not replace running in Snowflake.

## ADR-007: Build and eval sessions are tagged out of query history (3 October 2026)

**Decision.** `01_setup_and_ddl.sql` and `02_load_data.sql` set `QUERY_TAG = 'SVC_BUILD'`;
`eval/reference_queries.sql` sets `QUERY_TAG = 'SVC_EVAL'`. The mapping step must exclude both tags
when it reads query history.

**Why.** Layer 2 uses query history as evidence of how the estate is really used. Running the
reference queries in the same account would put the answer key into that history, and the load
script's INSERT statements reveal how every decoy was generated. Either would let the mapper score
well for the wrong reason, which breaks the evaluation isolation rule in ADR-003.

**Limit.** A tag is only a filter the tool has to honour; it is not access control. The scoring
harness should check that no excluded query was used as evidence.

**Finding, first Snowflake load.** The first build ran from an untagged copy of the scripts, so its
statements carry no query tag. The mapping step therefore also reads `SELECT` statements only. That
is the right rule anyway: analyst `SELECT`s are the evidence of how data is used, and every build
statement is DDL or DML (`INSERT ... SELECT` is recorded as `INSERT`). The tag remains essential for
the reference queries, which are `SELECT`s.

## ADR-008: Estate verified in Snowflake (3 October 2026)

**Finding.** The estate was built and loaded on a Snowflake trial account (SYSADMIN, XSMALL
warehouse). All 19 tables loaded, 1,094,354 rows in total, with no failed statements. Reference
query results for that load:

| Term | Value |
|---|---|
| T1 active customer (Marketing) | 2,932 |
| T2 active customer (Finance) | 1,469 |
| T3 engaged member | 846 |
| T4 on-time delivery % (Customer Experience) | 53.2 |
| T5 on-time delivery % (vendor) | 74.4 |
| T6 store-SKUs at stockout risk | 842 |
| T6 decoy: store-SKUs at zero on hand | 3,204 |
| T6 at risk but not at zero | 103 |
| T6 at zero but not at risk | 2,465 |
| Decoy: active per `ERP.CUSMST.LSTPURDT` | 0 |
| Decoy: `ERP.CUSMST.STSCD = 'A'` | 4,245 |
| Decoy: `LOY.MBR.CARD_STAT = 'ACT'` | 2,785 |

Values move with the load date (ADR-004); these are a record of one load, not fixed expectations.

**Every designed trap holds.** The two "active customer" definitions disagree by a factor of two.
The two "on-time delivery" definitions differ by 21 points. Card status overstates engagement more
than threefold, and ERP account status overstates activity. Both stockout distinguishing cases exist
(ADR-005). The stale `LSTPURDT` column returns zero recent customers by construction, since its batch
stopped 180 days before the load: a mapper that profiles freshness catches it, one that trusts
column names does not.

**Model availability is not stable.** A Cortex smoke test against `mistral-large2` failed because
the model had moved to legacy state. The mapping step will therefore take its model name as a
setting, checked at startup against `SHOW CORTEX BASE MODELS IN SCHEMA SNOWFLAKE.MODELS`, never
hard-coded. The schema qualifier matters: unqualified, the command is scoped to the current database
and returns no rows once the session has run `USE DATABASE`. The default will be
chosen on cost: start with a capable mid-tier model and move up only if scoring against the answer
key shows misses.

**Default model.** From the trial account's `SHOW CORTEX BASE MODELS` on 3 October 2026:

- Default: `CLAUDE-SONNET-5`. Generally available, not legacy, and a mid-tier cost.
- Cheaper comparison: `CLAUDE-HAIKU-4-5`. If it scores the same against the answer key, it
  becomes the default.
- Ceiling: `CLAUDE-OPUS-5`, used only if the default misses mappings.
- Excluded: preview models (`PUPR`, `PRPR`) and anything `LEGACY` or `EOL`. `CLAUDE-4-SONNET`, for
  example, was legacy with an end-of-life date of 14 October 2026, eleven days after this check.

The startup check accepts only models whose `lifecycle_status` is `GA`. Every Claude model on the
list has no in-region availability, so the account needs cross-region inference enabled; the trial
account already had it, since a test call to `CLAUDE-OPUS-4-5` succeeded.

## ADR-009: Simulated analyst query history (3 October 2026)

**Decision.** `sql/03_analyst_workload.sql` runs 34 ad hoc and report queries written as six analysts
(marketing, finance, loyalty, customer experience, supply chain, store operations) would write
them, tagged `SVC_WORKLOAD`. The mapping step reads them as ordinary query history.

**Why.** Layer 2 treats query history as evidence of how an estate is really used: which joins
work, which codes mean what. A fresh trial account has none, while a real legacy estate has years
of it. Without a simulated history, layer 2 would be built and tested against an input it will
never lack in practice.

**How it stays honest.** The workload was written fresh, not copied from the reference queries. No
query encodes a full SME definition. Wrong usages (decoy columns, wrong keys, fan-out, sign errors)
appear at least as often as correct ones, as they do in real history, and three queries use wrong
join keys and return nothing. Which query is which is recorded only in `eval/workload_design.md`,
outside anything the tool reads.

**Limits.** Each query runs once, so run frequency carries no signal. Everything runs as one user
and role. The offline smoke test now executes every workload query; that proves they run, not that
they are realistic.

**Verified.** Run on the Snowflake trial account on 3 October 2026: all 34 queries succeeded and
appear in query history as `SELECT` statements tagged `SVC_WORKLOAD`.

**Finding.** Adding the query tags in ADR-007 had broken the offline smoke test: the emulator does
not support `ALTER SESSION`. The harness now skips those statements.

## ADR-010: Query history is optional evidence, and its value is measured (3 October 2026)

**Context.** Two groups hold the knowledge this tool needs. Business users know what terms mean
and never write queries; layer 1 captures them in conversation (ADR-001). Analysts and engineers
know where data lives, and their queries are one source of layer 2 evidence (ADR-009). In the
low-maturity organisations this tool targets, that second group may be small: much query history
comes from BI service accounts or spreadsheet extracts, or barely exists.

**Decision.**

1. The mapping step must work from catalog metadata and sample values alone. Query history raises
   or lowers confidence in a proposal; it is never required to make one. Every proposal states
   which kinds of evidence it rests on.
2. The mapper is scored against the answer key twice, with and without the simulated workload.
   The difference is reported as the measured value of query history.

**Why.** A tool that only works where analysts already write good SQL is least useful where it is
most needed. Measuring the gap, rather than asserting it, keeps the claim defensible.

## ADR-011: A hand-written glossary stands in for layer 1 (3 October 2026)

**Decision.** `glossary/terms.yaml` holds the six terms as business users stated them: definition,
exclusions, synonyms, the unit counted, breakdowns, the systems they mentioned, why it matters, and
the questions they ask. It is the mapping step's only input about meaning.

**What it deliberately leaves out.** No table or column names, no mappings, no traps, no open
questions, and no note that two pairs of terms conflict. Those are things the tool has to work out,
or ask about, so including them would score the tool on information a real business user would
never give it.

**Sourcing.** Definitions, exclusions, synonyms and system mentions are quoted from the Requirements
Accelerator's synthetic interviews. The questions are composed from each interview's stated
measure and breakdowns; they are the test set for layer 3, where Cortex Analyst is asked them
against the generated semantic view.

**Realistic gaps kept on purpose.** Marketing names only the email platform, which is not in the
estate; Loyalty's "engaged member" and Marketing's "active customer" overlap with no shared words.
A real interview produces exactly this kind of incomplete, uneven input.

## ADR-012: The mapper runs inside Snowflake under its own isolated role (3 October 2026)

**Decision.** Layer 2 is two Python stored procedures in `SVC_APP.MAPPER`:

- `PROFILE_ESTATE` scans each estate table once and stores per-column statistics: row and distinct
  counts, nulls, value range, most common values, and for dates how many days ago the latest value
  is. That last figure is what exposes a stale column.
- `MAP_TERM(term, model, use_history)` sends one glossary term, the catalog with profiles and,
  optionally, analyst query history to `AI_COMPLETE` with a JSON schema. It gets back the entity
  being counted, every component (source, join, filter, time window, exclusion) with its evidence
  and confidence, the columns it rejected and why, a measure query, and questions for the business
  owner. It runs the measure query (single read-only `SELECT` only) and records everything, with
  token usage, in `PROPOSALS`.

**Isolation is enforced by Snowflake, not by convention.** `04_app_setup.sql` creates `SVC_MAPPER`
and `SVC_EVALUATOR`. Only the evaluator can see `SVC_APP.EVAL`, where the answer key will live.
Both procedures run with caller's rights and refuse to start unless the session is `SVC_MAPPER`
with secondary roles off. Without that check, Snowsight's default of activating all of a user's
roles as secondary roles would silently hand the mapper the evaluator's access. Query tags
(ADR-007) remain necessary on top, because account query history shows every role's queries.

**Why in Snowflake.** No credentials leave the account, nothing is hard-coded, and the same
procedures back the Streamlit in Snowflake review screen later. Python lives in `python/` as plain
modules; `tools/build_sql.py` inlines them into `sql/06_procedures.sql`, and `tests/test_mapper.py`
loads exactly that inlined code against a fake session, so what is tested is what is deployed.

**Limits.** The whole catalog goes into one prompt. That fits this estate (19 tables, 105 columns)
but not a real one; a retrieval step (Cortex Search over column profiles) would narrow candidates
first. Each proposal is one model call with no self-check, and the measure query is the model's own
SQL, executed only after a read-only guard.

## ADR-013: First Snowflake run of the mapper, and a history leak caught (7 October 2026)

**What ran.** `04` to `07` on the trial account. `PROFILE_ESTATE` returned 19 tables and 105 columns.
`MAP_TERM` for T3 (engaged member) ran three times on `CLAUDE-SONNET-5`: with history, without, and with
history restricted to the simulated workload.

**Result.** All three proposals chose `LOY.PTS_TXN` where `TXN_CD = 'RDM'` and `LOY.EML_EVT` where
`EVT_TYP = 'OPN'`, each in a 60-day window, counted per member, and rejected `LOY.MBR.CARD_STAT` as the
trap. All three measure queries returned 794. The reference query in `eval/reference_queries.sql`,
run as `SVC_EVALUATOR` with the `SVC_EVAL` tag on the same day, also returned 794, so the three runs
match the ground truth. The no-history
run reached the same mapping from catalog metadata and sample values alone (ADR-010, point 1).

**Finding 1: the first with-history run was contaminated.** Its evidence quoted queries labelled
`T3 engaged member` and `Decoy: LOY CARD_STAT = ACT`, which exist only in `eval/reference_queries.sql`.
It read 44 history queries against the 34 in the simulated workload. Account query history held nine
copies of the reference queries tagged `SVC_EVAL` (excluded, as designed) and nine identical untagged
copies from the same user and role, from a run where the session tag did not apply. The mapper cannot
tell an answer-key query from an analyst query without eval knowledge, which ADR-007 forbids. That
run's result is discarded.

**Decision.** `MAP_TERM` takes an optional `HISTORY_TAG`. When set, it reads only history carrying that
tag, and records the restriction in the run's `NOTE`. The benchmark passes `SVC_WORKLOAD`, so it reads
exactly the 34 workload queries. With no tag, behaviour is unchanged, which is the right default for a
real estate where no answer key exists. The clean run read 34 queries, and its evidence cites real
workload queries, not answer-key labels. Reference queries must only be run with the `SVC_EVAL` tag set
in the same session.

**Finding 2: `AI_COMPLETE` intermittently returns NULL or an empty string.** Seen on
`CLAUDE-SONNET-5` with prompts of 13,547 to 25,102 characters, so size is not the trigger. A plain call
with no response schema also returned an empty string during one failure, and a trivial prompt answered
normally in a health check. `MAP_TERM` now makes up to five attempts, waiting 5, 15, 30 and 60 seconds,
raises the temperature on retries, records any retries in `NOTE`, and on total failure reports what a
schema-free call returned. One no-history run needed two NULL retries; the final run needed none that
the `NOTE` records.

**Finding 3: Snowpark binds Python `None` as the text `'None'`** in `INSERT ... SELECT ?` statements,
which broke a NUMBER column on the first run. Nullable values are now sent as empty strings and
converted with `NULLIF` in SQL.

**What this does not show.** One term, one model, one run each. T3 is among the easier terms and the
no-history run solved it unaided, so these runs do not show whether history helps. That needs the
harder terms with conflicting definitions and several runs per condition.

## ADR-014: Query history measured on two conflicting terms (9 October 2026)

**What ran.** `08_run_slice1b.sql`: `MAP_TERM` for T1 (active customer, marketing) and T2 (active
customer, finance) on `CLAUDE-SONNET-5`, two runs with history restricted to `SVC_WORKLOAD` and two
without, for each term. Five runs finished on 7 October; a failed call stopped the batch, and the last
three ran on 9 October. Each run's measure query was compared component by component with
`eval/answer_key.yaml`, and its value with the reference query run under the `SVC_EVAL` tag.

**T1.** The reference returns 2899 as of 7 October. Both history runs produced the reference logic
exactly: online orders excluding guests and cancellations, plus in-store sales, joined to the customer
master, with internal accounts excluded. Both returned 2899. Their evidence cites the simulated
workload: analyst queries filter `ORD_STAT <> 'CNL'`. Neither no-history run matched. Both left
cancelled orders in: one never mentioned them, and the other saw the `CNL` status in sample values,
rated it low confidence and asked the business instead. Both also kept only retail customers
(`CUSTYP = 'R'`), which drops employees as well, an open question in the answer key. The no-history
run on 7 October returned 2823. The one on 9 October is not compared on value, because the 90-day
window had moved; it also built the online join by padding the customer number to eight digits, a
format assumption the other runs did not make.

**T2.** The reference returns 1469. All four runs chose the right sources, summed the store-credit
ledger into a balance (the designed trap) and ignored purchase recency, so none confused the finance
definition with the marketing one. Two runs, one from each condition, returned 1469. The other two
returned 1413 because they also excluded employees. None applied the reference's literal reading of an
open subscription (`END_DT IS NULL`); all four asked the business how to treat subscription status. On
this data that filter does not change the count.

**Result.** History made a measurable difference on T1, where the deciding detail is a convention in
how analysts query the data rather than something the catalog states: 2 of 2 history runs matched the
reference, against 0 of 2 without. On T2 it made no visible difference: 1 of 2 matched in each
condition, and both misses came from an open question rather than a wrong mapping. This is consistent
with ADR-010: the mapper works without history, and history raises accuracy where conventions live in
usage.

**Retries.** All five no-history runs across T1, T2 and T3 needed one to four retries after an empty
`AI_COMPLETE` response; none of the five clean history runs did. That is too few runs to explain.
After 7 October `MAP_TERM` gained a last-resort fallback: if structured output stays empty after every
retry, it parses the same prompt's plain reply and says so in `NOTE`. It did not trigger in these runs,
so it has not yet run in Snowflake.

**What this does not show.** Two runs per condition, two terms, one model. It shows a direction on T1,
not a rate. The open questions (employees, paused and legacy subscriptions) are the business owner's to
settle in layer 1, and the scoring above does not count them as mapping errors.

## ADR-015: Closed loop from interview to mapping, run in Snowflake (9 October 2026)

**What ran.** `10_closed_loop.sql`. A T3 (engaged member) definition was captured in the interview app
and confirmed; I played the business owner, answering from T3's definition. Then `PROMOTE_TERM`
added it to the glossary as `T3I`, and `MAP_TERM` mapped it on `CLAUDE-SONNET-5` once without history and once with history restricted to `SVC_WORKLOAD`. The
reference query ran the same day under the `SVC_EVAL` tag. The account runs on US Pacific time, so
"the same day" means the same Snowflake date: the window is 60 days back from `CURRENT_DATE`.

**Result.** Both runs returned 769, and the reference returned 769. Both chose the same logic as the
reference: a points redemption (`TXN_CD = 'RDM'`) or an email open (`EVT_TYP = 'OPN'`) in the last 60
days, counted once per member. Both counted members through the member master (`LOY.MBR`), where the
reference takes the union of the two event tables directly; on this data that gives the same count.
Query history made no difference to this term, consistent with ADR-013 and ADR-014: T3's definition is
fully stated by the business, so there is no usage convention for history to supply.

**The fallback ran for the first time.** In the run without history, structured output came back
empty on all five attempts, so `MAP_TERM` used its plain-reply fallback (ADR-014). The first attempt
failed: the plain reply contained a complete proposal, but `AI_COMPLETE` returns it as a VARIANT, which
reaches Python as quoted, escaped JSON text, and the parser looked for the object without decoding it
first. The parser now decodes a quoted reply once (commit 8ea1c38, with a test for that exact shape).
The rerun succeeded and its `NOTE` records that the proposal was parsed from a plain reply. As in
ADR-014, every run without history needed retries; the run with history did not.

**What this does not show.** One interview, one term, one model. It shows the loop works end to end
in Snowflake: business wording in, confirmed draft, glossary entry, mapping, a value that matches the
reference. It does not show how well real business users answer an interview, which needs interviews
with people who did not write the glossary.

## ADR-016: Semantic view generation is deterministic, for one supported shape (10 October 2026)

**Decision.** Layer 3 starts as a thin slice: `GENERATE_SEMANTIC_VIEW(term)` turns the latest
successful mapping of a term into a Snowflake semantic view with no model call. The model proposes
the logic in layer 2 and proves it with a number; this step only translates, and it proves the
translation by querying the new semantic view and comparing the answer with the mapping's own measure
query, run at the same moment. Both values and the generated DDL are recorded in `SEMANTIC_VIEWS`.

**The supported shape.** "Counted once per thing, if it had a qualifying event in the last N days, in
any of these sources." Every time window must read `SCHEMA.TABLE.COLUMN >= DATEADD(day, -N,
CURRENT_DATE)`, windows on different sources are joined with OR, and every filter or exclusion is a
plain predicate on one table. Anything else is refused with the reason: aggregate conditions,
subqueries, windows joined with AND, filters spanning tables. The mapper's components are free text
and vary between runs, so a refusal is safer than a guess. Model-written fragments become part of a
view, so the same check rejects semicolons, comments, subqueries and write keywords.

**The design.** A semantic view metric cannot say "in this table or that one", so the generator
builds two objects. A view of qualifying events (one row per event, each source filtered and joined
to the counted table, the window evaluated at query time) and a semantic view over it: the counted
table with its key, the events view related to it, the event day and source as dimensions, and the
distinct count as the metric, named from the business term and carrying its definition and synonyms.

**Checked offline.** Run against the 13 proposals the mapper produced in Snowflake on 7 and 9
October: all five engaged-member runs (T3 and T3I) and the two marketing active-customer (T1) runs
with history are supported; one T3I run includes a join to an unrelated system, which is ignored and
reported. The four finance active-customer (T2) runs are refused, since a positive balance needs an
aggregate, as are the two T1 runs without history, one for joining its windows with AND and one for
an exclusion spanning two tables. Those two are also the T1 runs that missed the reference (ADR-014),
but the shape check is not a correctness test; that is a side effect.

**Run in Snowflake (10 October 2026, Brisbane; 9 October on the account's US Pacific clock).**
`11_semantic_view.sql` for T3I, from the mapping run with history, worked on the first run.
`SV_T3I` returned 769, the mapping's own measure returned 769 at the same moment, and the
independent check (the semantic view next to the reference query, as the evaluator under the
`SVC_EVAL` tag, same Snowflake date) returned 769 for both. The two ignored components (a note about
card status, and a join to an unrelated system) were recorded with their reasons. Broken down by
source, 558 members opened an email and 301 redeemed points, 859 in total, against 769 distinct
members: 90 did both, and the metric counts each once.

**Not yet shown.** One term, one shape. Not built: engineer review of the generated DDL, business
confirmation by example rows, and asking Cortex Analyst the users' own questions against the
semantic view.


## ADR-017: Recorded demo run, and corrections from the pre-publication audit (11 October 2026)

**What ran.** The full path once more for the demo recording, on the trial account: an interview for
"engaged member" in the app (I played the loyalty programme manager, answering from the T3 glossary
definition), `PROMOTE_TERM`, `MAP_TERM` with history, `GENERATE_SEMANTIC_VIEW`, then the independent check
as the evaluator under the `SVC_EVAL` tag. The mapping measure, the semantic view and the reference
query all returned 760. Broken down by source, 551 members opened an email (`LOY.EML_EVT`) and 299
redeemed points (`LOY.PTS_TXN`): 850 in total against 760 distinct members, so 90 did both. This is the
same logic as ADR-016 on a later Snowflake date; the 60-day window moves, which is why 760 differs from
the 769 in ADR-015 and ADR-016. Nothing in those entries was wrong; they record other days.

**What this does not show.** Still one interviewer who wrote the definition, one term, one model, one
shape. The demo interview answers are examples, not evidence about real business users.

**Audit corrections.**

- The README's "How it works" described the engineer review, example-row confirmation and Cortex Analyst
  validation in the present tense. None is built; the section now says so.
- ADR-012 says Snowsight activates all of a user's roles as secondary roles by default. I did not check
  that against Snowflake's documentation. The design does not depend on it: `require_mapper_role` reads
  the session's actual secondary roles and refuses to run unless they are off.
- The README said the Claude models are served cross-region only. The documentation says cross-region
  inference is needed for the full set of models, not that rule exactly. What was observed is in ADR-008:
  the trial account already had it enabled. The README now says that.
- `docs/layer1-slice-plan.md` still read "nothing here exists yet"; its status line now points to ADR-015.
- Added the MIT licence. Replaced a literal em dash in a test with an escape so the repo has none.
