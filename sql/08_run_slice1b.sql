/*
  08_run_slice1b.sql
  Slice 1, second part: map T1 (active customer, marketing) and T2 (active customer, finance), each
  with and without query history, two runs each (ADR-010, ADR-013). Eight calls, 5 to 25 minutes.
  History is restricted to the simulated workload's tag so the answer key cannot leak in.
  Run as SVC_MAPPER with secondary roles off. Run the calls one at a time, or select all and run;
  a failed call stops the rest, and every finished call is already stored in PROPOSALS.
*/

USE ROLE SVC_MAPPER;
USE SECONDARY ROLES NONE;
USE WAREHOUSE SVC_WH;
USE SCHEMA SVC_APP.MAPPER;

CALL MAP_TERM('T1', 'CLAUDE-SONNET-5', TRUE, 'ALDERGLEN_RAW', 'SVC_WORKLOAD');
CALL MAP_TERM('T1', 'CLAUDE-SONNET-5', FALSE);
CALL MAP_TERM('T2', 'CLAUDE-SONNET-5', TRUE, 'ALDERGLEN_RAW', 'SVC_WORKLOAD');
CALL MAP_TERM('T2', 'CLAUDE-SONNET-5', FALSE);
CALL MAP_TERM('T1', 'CLAUDE-SONNET-5', TRUE, 'ALDERGLEN_RAW', 'SVC_WORKLOAD');
CALL MAP_TERM('T1', 'CLAUDE-SONNET-5', FALSE);
CALL MAP_TERM('T2', 'CLAUDE-SONNET-5', TRUE, 'ALDERGLEN_RAW', 'SVC_WORKLOAD');
CALL MAP_TERM('T2', 'CLAUDE-SONNET-5', FALSE);

-- Results to send back (download as CSV): every run for T1 and T2.
SELECT RUN_ID, CREATED_AT, TERM_ID, MODEL, USE_HISTORY, HISTORY_QUERIES, PROMPT_CHARS,
       MEASURE_VALUE, MEASURE_ERROR, NOTE, MEASURE_SQL, USAGE, PROPOSAL
FROM PROPOSALS
WHERE TERM_ID IN ('T1', 'T2')
ORDER BY TERM_ID, USE_HISTORY, CREATED_AT;
