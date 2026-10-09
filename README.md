# meaning-to-semantic-view

Turns what business people know about their data into a Snowflake semantic view, without asking
them to know anything about tables or columns.

## The problem

Cortex Analyst and Snowflake Intelligence answer business questions well when a good semantic view
sits underneath them. Writing one needs two kinds of knowledge that rarely live in the same head:
what the business means ("an active customer ordered in the last 90 days, excluding internal
accounts") and where that lives physically (which of four date columns, which join, which status
code). In teams still building their governance practice, the first kind lives with subject matter
experts and the second with the data team, and the semantic view waits until someone joins the two.

That gap is the opportunity. Definition questions tend to go to the same few experts, and the
answers live in conversations rather than anywhere queryable. This tool captures that knowledge
once, in the experts' own words, and turns it into a governed, reusable asset that engineers map
and validate, a right-sized step up in governance rather than a programme to stand up first.

## How it works

Three layers, each with a different audience:

1. **Capture meaning** (business users). A guided conversation collects concepts, measures, time
   logic, exclusions, synonyms and the questions people actually ask. No schema is ever shown.
2. **Map meaning to structure** (engineers). Cortex proposes candidate tables, columns, joins and
   filters for each concept from catalog metadata, sample values and query history. An engineer
   confirms or corrects each proposal.
3. **Generate and validate** (both). Business users confirm mappings by judging example rows in
   plain language. The tool emits `CREATE SEMANTIC VIEW` DDL, then asks Cortex Analyst the users'
   own questions against it.

## Status

Early build. What exists today:

- **Test estate**: a synthetic legacy data estate (6 source schemas, 19 tables, about 1 million
  rows) built to be hard to map: cryptic names, no comments, no declared keys, mismatched key
  formats, stale and decoy columns, competing dates and fan-out. See
  [docs/legacy-estate.md](docs/legacy-estate.md).
- **Ground truth**: six business term definitions (including two genuine conflicts between teams)
  mapped to their correct physical structure, the traps each must avoid, and the questions only an
  SME can settle, in [eval/answer_key.yaml](eval/answer_key.yaml), with executable versions in
  [eval/reference_queries.sql](eval/reference_queries.sql).
- **Verified in Snowflake**: the estate has been built and loaded on a Snowflake trial account
  (19 tables, 1,094,354 rows, no failed statements) and every designed trap holds in the real
  data. Results are in [ADR-008](docs/architecture-decisions.md#adr-008-estate-verified-in-snowflake-3-october-2026).
- **Glossary**: the six business terms as business users stated them, with no schema, in
  [glossary/terms.yaml](glossary/terms.yaml). Stands in for the layer 1 interview until that has run in Snowflake.
- **Simulated query history**: 34 analyst queries, right and wrong in realistic proportion, so
  the mapping step has usage evidence to weigh. Run in Snowflake: all 34 succeeded. See
  [ADR-009](docs/architecture-decisions.md#adr-009-simulated-analyst-query-history-3-october-2026).
- **Offline smoke test**: runs the full build against a local Snowflake emulator, checks every
  designed trap exists in the data and runs every workload query. Passing.

- **Mapping step (layer 2)**: Python stored procedures that profile the estate and ask Cortex to map
  one term at a time, with evidence, under a role that cannot see the answer key. Unit tested offline
  and run in Snowflake for three terms on one model. T3 (engaged member): every run chose the right
  sources, rejected the card-status trap and returned 794, matching the reference query, with or
  without query history. T1 (active customer, marketing): both runs with history matched the
  reference logic and value (2899); neither run without history did, because both kept cancelled
  orders. T2 (active customer, finance): all runs avoided the ledger trap, and one run in each
  condition matched the reference (1469); the others differed only on an open question for the
  business. Two runs per condition: a direction, not a rate. See
  [ADR-012](docs/architecture-decisions.md#adr-012-the-mapper-runs-inside-snowflake-under-its-own-isolated-role-3-october-2026),
  [ADR-013](docs/architecture-decisions.md#adr-013-first-snowflake-run-of-the-mapper-and-a-history-leak-caught-7-october-2026)
  and [ADR-014](docs/architecture-decisions.md#adr-014-query-history-measured-on-two-conflicting-terms-9-october-2026).

Built and tested offline, not yet run in Snowflake: the business user interview (layer 1), a
Streamlit app in `app/`. Not yet built: engineer review, and semantic view generation and validation
(layer 3).

## Running it

**In Snowflake.** Scripts 01 to 03 run as a role that can create databases and warehouses
(SYSADMIN on a trial account); 04 runs as ACCOUNTADMIN; 05 to 07 switch to `SVC_MAPPER` themselves. Run the reference queries only with the `SVC_EVAL` tag set (ADR-013).
No account or organisation identifiers are hard-coded; object names are session variables at the
top of each script.

The mapping step needs Cortex. The Claude models it defaults to are served cross-region only, so an
ACCOUNTADMIN must set `CORTEX_ENABLED_CROSS_REGION` (for example to `'ANY_REGION'`) if the account
has not already.

```
sql/01_setup_and_ddl.sql      creates warehouse, database, schemas, tables
sql/02_load_data.sql          loads deterministic synthetic data (a few minutes on XSMALL)
sql/03_analyst_workload.sql   simulated analyst query history for the mapping step to learn from
sql/04_app_setup.sql          tool database and isolated roles (run as ACCOUNTADMIN)
sql/05_glossary.sql           loads the glossary (generated)
sql/06_procedures.sql         mapping step procedures (generated)
sql/07_run_slice1.sql         profiles the estate and maps one term, with and without history
sql/08_run_slice1b.sql        maps two conflicting terms, two runs each with and without history
sql/09_interview_setup.sql    interviewer role, schema and draft tables for the layer 1 app (run as ACCOUNTADMIN)
sql/10_closed_loop.sql        promotes a confirmed interview draft into the glossary, then maps it
app/interview_app.py          the layer 1 interview: paste into a Streamlit app in SVC_APP.INTERVIEW (generated)
eval/reference_queries.sql    ground-truth answers for each business term
```

**Offline.**

```
pip install fakesnow sqlglot pyyaml
python tests/emulator_smoke.py
python -m unittest discover -s tests
python tools/build_sql.py      regenerates 05 and 06 after editing glossary/ or python/
```

## Repo layout

```
sql/      estate DDL, data load and simulated analyst workload
glossary/ business terms in business language (the mapping step's input)
python/   stored procedure source (inlined into sql/06 by tools/build_sql.py)
tools/    build script for the generated SQL
eval/     answer key, reference queries and workload notes (never read by the tool)
tests/    offline emulator smoke test and procedure unit tests
docs/     design documents
```

## Design documents

- [docs/legacy-estate.md](docs/legacy-estate.md): the test estate, its codes and its traps
- [docs/architecture-decisions.md](docs/architecture-decisions.md): design decisions and findings

## Related

The business terms reuse the synthetic interview dataset from
[Requirements Accelerator](https://github.com/jaydwyerdata/requirements-accelerator), an
interview tool that turns vague data requests into specs. That tool can emit semantic view DDL but
deliberately leaves every physical reference as a placeholder, because a requester cannot supply
schema. This project closes that gap.
