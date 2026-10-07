/*
  eval/reference_queries.sql
  Ground truth: hand-written, correct SQL for each business term, as each SME defined it.
  Used only to score the tool's output. Never pass this file, eval/answer_key.yaml or the load
  script to the mapping step; it must work from catalog metadata, sample values and query history.

  Run after 02_load_data.sql in the same database. Open ambiguities (see answer_key.yaml) are
  resolved here with the most literal reading of the SME's words, and marked OPEN where they are.
*/

SET DB_NAME = 'ALDERGLEN_RAW';

-- Tag this session so the mapping step can exclude it from query history (ADR-007).
-- Run this whole file in ONE session. An untagged run leaks the answer key into query history (ADR-013).
ALTER SESSION SET QUERY_TAG = 'SVC_EVAL';
USE DATABASE IDENTIFIER($DB_NAME);
SET AS_OF = CURRENT_DATE();

-- T1. "Active customer" (Marketing): ordered on any channel, online or in store, in the last 90 days.
--     Excludes internal accounts. OPEN: whether employees (CUSTYP = 'E') count as internal.
WITH activity AS (
    SELECT TRY_TO_NUMBER(SUBSTR(CUST_REF, 2)) AS cusno
    FROM OMS.ORD_HDR
    WHERE CUST_REF <> 'GUEST'
      AND ORD_STAT <> 'CNL'
      AND ORD_TS >= DATEADD(day, -90, $AS_OF)
    UNION
    SELECT CUST_NO
    FROM POS.TXN_HDR
    WHERE TXN_TYP = 'S'
      AND CUST_NO IS NOT NULL
      AND TXN_DT >= DATEADD(day, -90, $AS_OF)
)
SELECT 'T1 active customer (marketing)' AS term, COUNT(DISTINCT c.CUSNO) AS value
FROM ERP.CUSMST c
JOIN activity a ON a.cusno = c.CUSNO
WHERE c.CUSTYP <> 'I';

-- T2. "Active customer" (Finance): holds an open subscription or a positive store-credit balance
--     right now, regardless of purchase recency. Excludes internal accounts.
--     OPEN: paused subscriptions (STAT = 'P'), and legacy cancellations with END_DT never set.
--     Literal reading used here: open = STAT = 'A' and END_DT IS NULL.
WITH open_sub AS (
    SELECT DISTINCT CUSNO FROM BIL.SUB WHERE STAT = 'A' AND END_DT IS NULL
),
credit AS (
    SELECT CUSNO FROM ERP.SCLDGR GROUP BY CUSNO HAVING SUM(TXNAMT) > 0
)
SELECT 'T2 active customer (finance)' AS term, COUNT(DISTINCT c.CUSNO) AS value
FROM ERP.CUSMST c
WHERE c.CUSTYP <> 'I'
  AND (c.CUSNO IN (SELECT CUSNO FROM open_sub) OR c.CUSNO IN (SELECT CUSNO FROM credit));

-- T3. "Engaged member" (Loyalty): redeemed points or opened a programme email in the last 60 days.
--     OPEN: whether a click (CLK) without a logged open counts as an open.
WITH engaged AS (
    SELECT MBR_ID FROM LOY.PTS_TXN
    WHERE TXN_CD = 'RDM' AND TXN_DT >= DATEADD(day, -60, $AS_OF)
    UNION
    SELECT MBR_ID FROM LOY.EML_EVT
    WHERE EVT_TYP = 'OPN' AND EVT_TS >= DATEADD(day, -60, $AS_OF)
)
SELECT 'T3 engaged member' AS term, COUNT(*) AS value FROM engaged;

-- T4. "On-time delivery" (Customer Experience): order arrives by the date promised at checkout.
--     Order grain; a split order is on time only when its last parcel arrives by the promise.
--     Excludes cancellations. Orders still in transit are not yet measurable.
WITH ord AS (
    SELECT h.ORD_ID,
           h.PRM_DLV_DT,
           MAX(s.DLV_TS) AS last_dlv,
           COUNT_IF(s.DLV_TS IS NULL) AS undelivered
    FROM OMS.ORD_HDR h
    JOIN OMS.SHPMT s ON s.ORD_ID = h.ORD_ID
    WHERE h.ORD_STAT <> 'CNL'
    GROUP BY h.ORD_ID, h.PRM_DLV_DT
)
SELECT 'T4 on-time delivery % (CX)' AS term,
       ROUND(100 * AVG(IFF(last_dlv::DATE <= PRM_DLV_DT, 1, 0)), 1) AS value
FROM ord
WHERE undelivered = 0;

-- T5. "On-time delivery" (Supply Chain, vendor): vendor shipped by the cutoff agreed in the PO,
--     regardless of when the goods reach the DC. PO grain, judged on the first shipment.
--     Alias "vendor OTIF" is misleading: no in-full test is part of this definition.
WITH first_rcv AS (
    SELECT PONUM, MIN(ACTSHPDT) AS first_ship
    FROM ERP.PORCV
    GROUP BY PONUM
)
SELECT 'T5 on-time delivery % (vendor)' AS term,
       ROUND(100 * AVG(IFF(r.first_ship <= p.AGRSHPDT, 1, 0)), 1) AS value
FROM ERP.POHDR p
JOIN first_rcv r ON r.PONUM = p.PONUM
WHERE p.POSTAT <> 'X';

-- T6. "Stockout" (Store Operations): a SKU is at stockout risk in a store once the stockroom count
--     drops below what the store would sell before its next scheduled delivery, not simply zero.
--     OPEN: the sales-rate window (28 days used here) and whether allocated stock counts as on hand.
WITH latest AS (
    SELECT LOC_ID, SKU, OH_QTY
    FROM WMS.INV_SNP
    WHERE SNP_DT = (SELECT MAX(SNP_DT) FROM WMS.INV_SNP)
      AND LOC_ID LIKE 'S%'
),
rate AS (
    SELECT 'S' || LPAD(h.STR_NO::VARCHAR, 3, '0') AS loc_id,
           l.SKU,
           SUM(l.QTY) / 28 AS units_per_day
    FROM POS.TXN_HDR h
    JOIN POS.TXN_LN l ON l.TXN_ID = h.TXN_ID
    WHERE h.TXN_TYP = 'S'
      AND h.TXN_DT >= DATEADD(day, -28, $AS_OF)
    GROUP BY 1, 2
),
risk AS (
    SELECT i.LOC_ID,
           i.SKU,
           i.OH_QTY,
           COALESCE(r.units_per_day, 0) * DATEDIFF(day, $AS_OF, s.NXT_DLV_DT) AS expected_sales
    FROM latest i
    JOIN WMS.REPL_SCHED s ON s.LOC_ID = i.LOC_ID
    LEFT JOIN rate r ON r.loc_id = i.LOC_ID AND r.SKU = i.SKU
)
SELECT 'T6 store-SKUs at stockout risk' AS term, COUNT_IF(OH_QTY < expected_sales) AS value FROM risk
UNION ALL
SELECT 'T6 decoy: store-SKUs at zero on hand', COUNT_IF(OH_QTY = 0) FROM risk
UNION ALL
SELECT 'T6 at risk but not at zero', COUNT_IF(OH_QTY < expected_sales AND OH_QTY > 0) FROM risk
UNION ALL
SELECT 'T6 at zero but not at risk (no recent sales)', COUNT_IF(OH_QTY = 0 AND expected_sales = 0) FROM risk;

-- Decoy check: the stale ERP column gives a very different "active customer" answer.
SELECT 'Decoy: active per ERP.CUSMST.LSTPURDT' AS term, COUNT(*) AS value
FROM ERP.CUSMST
WHERE CUSTYP <> 'I' AND LSTPURDT >= DATEADD(day, -90, $AS_OF);

-- Decoy check: ERP account status 'A' is not "active customer".
SELECT 'Decoy: ERP STSCD = A' AS term, COUNT(*) AS value FROM ERP.CUSMST WHERE STSCD = 'A';

-- Decoy check: loyalty card status 'ACT' is not "engaged member".
SELECT 'Decoy: LOY CARD_STAT = ACT' AS term, COUNT(*) AS value FROM LOY.MBR WHERE CARD_STAT = 'ACT';
