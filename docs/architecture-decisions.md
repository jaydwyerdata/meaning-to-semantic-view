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
