/*
  10_closed_loop.sql
  Layer 1 closed-loop test (docs/layer1-slice-plan.md, task 5). A term captured in the interview app is
  promoted into GLOSSARY, then mapped exactly like the hand-written entries. Pass condition: the mapping
  for the interviewed term chooses the same sources as hand-written T3, and its measure matches the
  reference query run on the same day (T3 uses a 60-day window, so the value moves with the date).
  Run sections 1 to 4 as SVC_MAPPER, section 5 as the evaluator.
*/

USE ROLE SVC_MAPPER;
USE SECONDARY ROLES NONE;
USE WAREHOUSE SVC_WH;
USE SCHEMA SVC_APP.MAPPER;

-- 1. The confirmed interview draft. Copy its DRAFT_ID into step 2.
SELECT DRAFT_ID, STATUS, TERM:term::STRING AS TERM, TERM:owner::STRING AS OWNER, CONFIRMED_AT
FROM SVC_APP.INTERVIEW.TERM_DRAFTS
WHERE STATUS = 'CONFIRMED'
ORDER BY CONFIRMED_AT DESC;

-- 2. Promote it under a new term id. Refuses a draft that is not confirmed, is missing a required field,
--    contains a catalog name, or would overwrite an existing glossary term.
CALL PROMOTE_TERM('<DRAFT_ID>', 'T3I');

-- 3. The interviewed entry next to the hand-written one.
SELECT TERM_ID, TERM FROM GLOSSARY WHERE TERM_ID IN ('T3', 'T3I') ORDER BY TERM_ID;

-- 4. Map the interviewed term without history (the harder test), then with the workload history.
CALL MAP_TERM('T3I', 'CLAUDE-SONNET-5', FALSE);
CALL MAP_TERM('T3I', 'CLAUDE-SONNET-5', TRUE, 'ALDERGLEN_RAW', 'SVC_WORKLOAD');

SELECT TERM_ID, USE_HISTORY, CREATED_AT, MEASURE_VALUE, MEASURE_ERROR, NOTE, MEASURE_SQL
FROM PROPOSALS
WHERE TERM_ID = 'T3I'
ORDER BY CREATED_AT;

-- 5. The reference value for today, in a separate worksheet session tagged out of query history.
--    Run this block on its own, as ACCOUNTADMIN, in ONE session.
-- ALTER SESSION SET QUERY_TAG = 'SVC_EVAL';
-- USE ROLE ACCOUNTADMIN;
-- USE DATABASE ALDERGLEN_RAW;
-- SET AS_OF = CURRENT_DATE();
-- WITH engaged AS (
--     SELECT MBR_ID FROM LOY.PTS_TXN WHERE TXN_CD = 'RDM' AND TXN_DT >= DATEADD(day, -60, $AS_OF)
--     UNION
--     SELECT MBR_ID FROM LOY.EML_EVT WHERE EVT_TYP = 'OPN' AND EVT_TS >= DATEADD(day, -60, $AS_OF)
-- )
-- SELECT 'T3 engaged member (reference, today)' AS term, COUNT(*) AS value FROM engaged;
