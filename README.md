# meaning-to-semantic-view

Turns what business people know about their data into a Snowflake semantic view, without asking
them to know anything about tables or columns.

## The problem

Cortex Analyst and Snowflake Intelligence answer business questions well when a good semantic view
sits underneath them. Writing one needs two kinds of knowledge that rarely live in the same head:
what the business means ("an active customer ordered in the last 90 days, excluding internal
accounts") and where that lives physically (which of four date columns, which join, which status
code). In teams with low governance maturity, the first kind lives with subject matter experts and
the second with a small, busy data team, and the semantic view never gets written.

I'm the engineer this lands on. Every definition question goes through the same few experts, and
the answer lives in their heads rather than anywhere I can query. This tool is my attempt to
capture that knowledge once, in their words, and do the translation work myself with help.

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
  [glossary/terms.yaml](glossary/terms.yaml). Stands in for the layer 1 interview until it is built.
- **Simulated query history**: 34 analyst queries, right and wrong in realistic proportion, so
  the mapping step has usage evidence to weigh. Run in Snowflake: all 34 succeeded. See
  [ADR-009](docs/architecture-decisions.md#adr-009-simulated-analyst-query-history-3-october-2026).
- **Offline smoke test**: runs the full build against a local Snowflake emulator, checks every
  designed trap exists in the data and runs every workload query. Passing.

Not yet built: all three layers above.

## Running it

**In Snowflake.** Run as a role that can create databases and warehouses (SYSADMIN on a trial
account). No account or organisation identifiers are hard-coded; object names are session
variables at the top of each script.

The estate scripts need no Cortex access. The mapping step (not yet built) will: the Claude models it
defaults to are served cross-region only, so an ACCOUNTADMIN must set
`CORTEX_ENABLED_CROSS_REGION` (for example to `'ANY_REGION'`) if the account has not already.

```
sql/01_setup_and_ddl.sql      creates warehouse, database, schemas, tables
sql/02_load_data.sql          loads deterministic synthetic data (a few minutes on XSMALL)
sql/03_analyst_workload.sql   simulated analyst query history for the mapping step to learn from
eval/reference_queries.sql    ground-truth answers for each business term
```

**Offline.**

```
pip install fakesnow sqlglot
python tests/emulator_smoke.py
```

## Repo layout

```
sql/      estate DDL, data load and simulated analyst workload
glossary/ business terms in business language (the mapping step's input)
eval/     answer key, reference queries and workload notes (never read by the tool)
tests/    offline emulator smoke test
docs/     design documents
```

## Design documents

- [docs/legacy-estate.md](docs/legacy-estate.md): the test estate, its codes and its traps
- [docs/architecture-decisions.md](docs/architecture-decisions.md): design decisions and findings

## Related

The business terms reuse the synthetic interview dataset from
[Requirements Accelerator](https://github.com/jaydai2488-lgtm/requirements-accelerator), an
interview tool that turns vague data requests into specs. That tool can emit semantic view DDL but
deliberately leaves every physical reference as a placeholder, because a requester cannot supply
schema. This project closes that gap.
