/*
  11_semantic_view.sql
  Layer 3 thin slice (ADR-016). Generates a Snowflake semantic view from a mapped term, checks it
  against the mapping's own measure, then checks it independently against the reference query.
  Run sections 1 to 3 as SVC_MAPPER, section 4 on its own as the evaluator.
  For another term, replace T3I throughout (for example with the term promoted in 10_closed_loop.sql).
*/

USE ROLE SVC_MAPPER;
USE SECONDARY ROLES NONE;
USE WAREHOUSE SVC_WH;
USE SCHEMA SVC_APP.MAPPER;

-- 1. Generate. Uses the latest successful mapping run with history (pass FALSE for the run without).
--    No model call. Refuses, with the reason, any mapping that is not an "event in the last N days" shape.
CALL GENERATE_SEMANTIC_VIEW('T3I');

-- 2. What was created, and the record of the check.
SHOW SEMANTIC VIEWS IN SCHEMA SVC_APP.MAPPER;
DESCRIBE SEMANTIC VIEW SV_T3I;
SELECT TERM_ID, CREATED_AT, SEMANTIC_VIEW, SV_VALUE, MEASURE_VALUE, MATCHED, IGNORED
FROM SEMANTIC_VIEWS
ORDER BY CREATED_AT DESC;

-- 3. Using it: the metric on its own, then broken down by source. A member who did both is counted
--    once in the total and once in each source row, so the rows can add up to more than the total.
SELECT * FROM SEMANTIC_VIEW(SV_T3I METRICS qualifying_events.ENGAGED_MEMBER_COUNT);
SELECT * FROM SEMANTIC_VIEW(
    SV_T3I
    DIMENSIONS qualifying_events.source_system
    METRICS qualifying_events.ENGAGED_MEMBER_COUNT
);

-- 4. Independent check, in a separate worksheet session tagged out of query history (ADR-007).
--    Run this block on its own, as ACCOUNTADMIN, in ONE session, on the same Snowflake date.
-- ALTER SESSION SET QUERY_TAG = 'SVC_EVAL';
-- USE ROLE ACCOUNTADMIN;
-- USE WAREHOUSE SVC_WH;
-- SET AS_OF = CURRENT_DATE();
-- SELECT 'semantic view' AS source, *
-- FROM SEMANTIC_VIEW(SVC_APP.MAPPER.SV_T3I METRICS qualifying_events.ENGAGED_MEMBER_COUNT)
-- UNION ALL
-- SELECT 'reference', COUNT(*) FROM (
--     SELECT MBR_ID FROM ALDERGLEN_RAW.LOY.PTS_TXN WHERE TXN_CD = 'RDM' AND TXN_DT >= DATEADD(day, -60, $AS_OF)
--     UNION
--     SELECT MBR_ID FROM ALDERGLEN_RAW.LOY.EML_EVT WHERE EVT_TYP = 'OPN' AND EVT_TS >= DATEADD(day, -60, $AS_OF)
-- );
