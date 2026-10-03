# Working rules for this repo

- No em dashes anywhere: code, comments, docs, generated output. Use commas, colons, semicolons or full stops.
- Australian spelling.
- Document as you go. README states current state only; design reasoning, findings and history go in
  docs/architecture-decisions.md as a new ADR entry.
- Claim integrity: nothing ships that cannot be defended. Distinguish "passed the emulator smoke test"
  from "verified in Snowflake". Unverified numbers stay flagged.
- Never hard-code Snowflake account, organisation or user identifiers. Object names are variables.
- No real employer data, schemas, names or documents. Alderglen Outfitters is fictional.
- glossary/terms.yaml is the mapping step's only input about meaning. Keep it in business language:
  no table or column names, mappings, traps or conflict notes.
- Evaluation isolation: the mapping step may read catalog metadata, sample values and query history
  only. It must never read eval/, docs/legacy-estate.md or the comments in sql/02_load_data.sql.
  When reading query history it uses SELECT statements only and excludes queries tagged SVC_BUILD
  or SVC_EVAL (ADR-007).
- Business users never see table or column names. Validation with them uses example rows in plain language.
- Keep scope tight: one working slice beats three started.
- Demo-prep working files (scripts, slide outlines, diagrams for recordings) live in demo/ and are gitignored.
