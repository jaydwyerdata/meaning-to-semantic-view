/*
  07_run_slice1.sql
  Slice 1: map "engaged member" (T3) twice, with and without query history (ADR-010).
  Run after 04 (as ACCOUNTADMIN), then 05 and 06 (as SVC_MAPPER). Run one statement at a time.
*/

USE ROLE SVC_MAPPER;
USE SECONDARY ROLES NONE;
USE WAREHOUSE SVC_WH;
USE SCHEMA SVC_APP.MAPPER;

-- 1. Isolation check: this must fail with "does not exist or not authorized".
SELECT COUNT(*) FROM SVC_APP.EVAL.INFORMATION_SCHEMA.TABLES;

-- 2. Profile the estate once (about a minute). Expect 19 tables, 105 columns.
CALL PROFILE_ESTATE();

-- 3. Map the term with query history, then without.
-- History is restricted to the simulated workload's tag so stray queries cannot leak the answer key (ADR-013).
CALL MAP_TERM('T3', 'CLAUDE-SONNET-5', TRUE, 'ALDERGLEN_RAW', 'SVC_WORKLOAD');
CALL MAP_TERM('T3', 'CLAUDE-SONNET-5', FALSE);

-- 4. Results to send back (download as CSV).
SELECT RUN_ID, CREATED_AT, TERM_ID, MODEL, USE_HISTORY, HISTORY_QUERIES, PROMPT_CHARS,
       MEASURE_VALUE, MEASURE_ERROR, NOTE, MEASURE_SQL, USAGE, PROPOSAL
FROM PROPOSALS
ORDER BY CREATED_AT;
