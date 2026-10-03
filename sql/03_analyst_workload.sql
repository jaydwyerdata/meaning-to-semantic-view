/*
  03_analyst_workload.sql
  Simulated query history: ad hoc and report queries from six analysts over the Alderglen estate.
  Run once after 02_load_data.sql, from a fresh worksheet. See ADR-009.
*/

SET DB_NAME = 'ALDERGLEN_RAW';
SET WH_NAME = 'SVC_WH';
USE WAREHOUSE IDENTIFIER($WH_NAME);
USE DATABASE IDENTIFIER($DB_NAME);
ALTER SESSION SET QUERY_TAG = 'SVC_WORKLOAD';

-- mkt: online orders by channel, last 30 days
SELECT h.CHNL_CD, COUNT(*) AS orders, SUM(l.NET_AMT) AS net_sales
FROM OMS.ORD_HDR h
JOIN OMS.ORD_LN l ON l.ORD_ID = h.ORD_ID
WHERE h.ORD_TS >= DATEADD(day, -30, CURRENT_DATE())
  AND h.ORD_STAT <> 'CNL'
GROUP BY h.CHNL_CD
ORDER BY net_sales DESC;

-- mkt: active customer count for the board pack
SELECT COUNT(*) AS active_customers
FROM ERP.CUSMST
WHERE STSCD = 'A';

-- mkt: lapsed customer list for win-back campaign
SELECT CUSNO, CUSNM1, LSTPURDT
FROM ERP.CUSMST
WHERE LSTPURDT < DATEADD(day, -180, CURRENT_DATE())
  AND CUSTYP = 'R'
ORDER BY LSTPURDT
LIMIT 500;

-- mkt: in-store buyers last 90 days
SELECT COUNT(DISTINCT t.CUST_NO) AS store_buyers
FROM POS.TXN_HDR t
JOIN ERP.CUSMST c ON c.CUSNO = t.CUST_NO
WHERE t.TXN_TYP = 'S'
  AND t.TXN_DT >= DATEADD(day, -90, CURRENT_DATE());

-- mkt: online buyers last 90 days, no guests or staff test accounts
SELECT COUNT(DISTINCT c.CUSNO) AS online_buyers
FROM OMS.ORD_HDR h
JOIN ERP.CUSMST c ON c.CUSNO = TRY_TO_NUMBER(SUBSTR(h.CUST_REF, 2))
WHERE h.CUST_REF <> 'GUEST'
  AND h.ORD_TS >= DATEADD(day, -90, CURRENT_DATE())
  AND c.CUSTYP <> 'I';

-- mkt: tried to get customer names onto orders
SELECT h.ORD_ID, h.ORD_TS, c.CUSNM1
FROM OMS.ORD_HDR h
JOIN ERP.CUSMST c ON h.CUST_REF = c.CUSNO::VARCHAR
LIMIT 100;

-- mkt: new customers by month
SELECT LEFT(CRTDT::VARCHAR, 6) AS yyyymm, COUNT(*) AS new_customers
FROM ERP.CUSMST
GROUP BY 1
ORDER BY 1 DESC
LIMIT 24;

-- fin: store credit liability by customer
SELECT CUSNO, SUM(TXNAMT) AS balance
FROM ERP.SCLDGR
GROUP BY CUSNO
HAVING SUM(TXNAMT) <> 0
ORDER BY balance DESC;

-- fin: total store credit outstanding
SELECT SUM(TXNAMT) AS outstanding
FROM ERP.SCLDGR;

-- fin: open subscriptions
SELECT PLAN_CD, COUNT(*) AS subs
FROM BIL.SUB
WHERE END_DT IS NULL
GROUP BY PLAN_CD;

-- fin: subscriptions by status
SELECT STAT, COUNT(*) AS subs
FROM BIL.SUB
GROUP BY STAT;

-- fin: store sales by month
SELECT DATE_TRUNC('month', h.TXN_DT) AS mth, SUM(l.EXT_AMT) AS sales
FROM POS.TXN_HDR h
JOIN POS.TXN_LN l ON l.TXN_ID = h.TXN_ID
GROUP BY 1
ORDER BY 1 DESC;

-- fin: store sales by month net of returns (fixed version)
SELECT DATE_TRUNC('month', h.TXN_DT) AS mth,
       SUM(CASE h.TXN_TYP WHEN 'S' THEN l.EXT_AMT WHEN 'R' THEN -l.EXT_AMT ELSE 0 END) AS net_sales
FROM POS.TXN_HDR h
JOIN POS.TXN_LN l ON l.TXN_ID = h.TXN_ID
GROUP BY 1
ORDER BY 1 DESC;

-- fin: shipping fee income by carrier
SELECT s.CARRIER_CD, SUM(h.SHP_FEE) AS fee_income
FROM OMS.ORD_HDR h
JOIN OMS.SHPMT s ON s.ORD_ID = h.ORD_ID
GROUP BY s.CARRIER_CD;

-- fin: shipping fee income by month
SELECT DATE_TRUNC('month', ORD_TS) AS mth, SUM(SHP_FEE) AS fee_income
FROM OMS.ORD_HDR
WHERE ORD_STAT <> 'CNL'
GROUP BY 1
ORDER BY 1 DESC;

-- loy: active members
SELECT TIER_CD, COUNT(*) AS members
FROM LOY.MBR
WHERE CARD_STAT = 'ACT'
GROUP BY TIER_CD;

-- loy: email open rate by campaign
SELECT CMP_CD,
       COUNT_IF(EVT_TYP = 'SND') AS sent,
       COUNT_IF(EVT_TYP = 'OPN') AS opened,
       ROUND(opened / NULLIF(sent, 0), 3) AS open_rate
FROM LOY.EML_EVT
GROUP BY CMP_CD
ORDER BY CMP_CD DESC
LIMIT 12;

-- loy: points redeemed last 60 days
SELECT COUNT(DISTINCT MBR_ID) AS redeemers, SUM(PTS) AS points
FROM LOY.PTS_TXN
WHERE TXN_CD = 'RDM'
  AND TXN_DT >= DATEADD(day, -60, CURRENT_DATE());

-- loy: members with customer details
SELECT m.MBR_ID, m.TIER_CD, c.CUSNM1
FROM LOY.MBR m
JOIN ERP.CUSMST c ON c.CUSNO = m.MBR_ID
LIMIT 100;

-- loy: tier mix of members who are also customers
SELECT m.TIER_CD, c.CUSTYP, COUNT(*) AS members
FROM LOY.MBR m
JOIN ERP.CUSMST c ON c.LOYNO = m.CARD_NO
GROUP BY 1, 2
ORDER BY 1, 2;

-- cx: late deliveries by carrier
SELECT CARRIER_CD,
       COUNT(*) AS shipments,
       COUNT_IF(DLV_TS::DATE > EST_DLV_DT) AS late
FROM OMS.SHPMT
WHERE DLV_TS IS NOT NULL
GROUP BY CARRIER_CD;

-- cx: on-time vs promise date
SELECT ROUND(100 * AVG(IFF(s.DLV_TS::DATE <= h.PRM_DLV_DT, 1, 0)), 1) AS on_time_pct
FROM OMS.SHPMT s
JOIN OMS.ORD_HDR h ON h.ORD_ID = s.ORD_ID
WHERE s.DLV_TS IS NOT NULL;

-- cx: transit days by carrier
SELECT CARRIER_CD, AVG(DATEDIFF(day, SHP_TS, DLV_TS)) AS avg_transit_days
FROM OMS.SHPMT
WHERE DLV_TS IS NOT NULL
GROUP BY CARRIER_CD;

-- cx: orders arriving after promise, per order
WITH o AS (
    SELECT h.ORD_ID, h.PRM_DLV_DT, MAX(COALESCE(s.DLV_TS, CURRENT_TIMESTAMP())) AS arrived
    FROM OMS.ORD_HDR h
    JOIN OMS.SHPMT s ON s.ORD_ID = h.ORD_ID
    GROUP BY h.ORD_ID, h.PRM_DLV_DT
)
SELECT COUNT(*) AS orders, COUNT_IF(arrived::DATE > PRM_DLV_DT) AS late_orders
FROM o;

-- cx: split shipments
SELECT shipments_per_order, COUNT(*) AS orders
FROM (SELECT ORD_ID, COUNT(*) AS shipments_per_order FROM OMS.SHPMT GROUP BY ORD_ID)
GROUP BY 1
ORDER BY 1;

-- sc: vendor late receipts
SELECT v.VNDNM,
       COUNT(*) AS receipts,
       COUNT_IF(r.RCVDT > p.EXPRCVDT) AS late
FROM ERP.PORCV r
JOIN ERP.POHDR p ON p.PONUM = r.PONUM
JOIN ERP.VNDMST v ON v.VNDNO = p.VNDNO
GROUP BY v.VNDNM
ORDER BY late DESC;

-- sc: vendor fill rate
SELECT p.VNDNO, SUM(r.RCVQTY) / NULLIF(SUM(d.ORDQTY), 0) AS fill_rate
FROM ERP.POHDR p
JOIN ERP.PODTL d ON d.PONUM = p.PONUM
JOIN ERP.PORCV r ON r.PONUM = p.PONUM
GROUP BY p.VNDNO;

-- sc: shipped by agreed date, per receipt
SELECT p.VNDNO,
       ROUND(100 * AVG(IFF(r.ACTSHPDT <= p.AGRSHPDT, 1, 0)), 1) AS shipped_on_time_pct
FROM ERP.PORCV r
JOIN ERP.POHDR p ON p.PONUM = r.PONUM
GROUP BY p.VNDNO
ORDER BY shipped_on_time_pct;

-- sc: open POs by DC
SELECT p.WHSCD, l.LOCNM, COUNT(*) AS open_pos
FROM ERP.POHDR p
JOIN ERP.LOCMST l ON l.LOCCD = p.WHSCD
WHERE p.POSTAT = 'O'
GROUP BY 1, 2;

-- ops: stockouts by store, last night
SELECT LOC_ID, COUNT(*) AS skus_out
FROM WMS.INV_SNP
WHERE SNP_DT = (SELECT MAX(SNP_DT) FROM WMS.INV_SNP)
  AND OH_QTY = 0
GROUP BY LOC_ID
ORDER BY skus_out DESC;

-- ops: store sales last 28 days with store names
SELECT l.LOCCD, l.LOCNM, l.REGCD, SUM(t.EXT_AMT) AS sales
FROM POS.TXN_HDR h
JOIN POS.TXN_LN t ON t.TXN_ID = h.TXN_ID
JOIN ERP.LOCMST l ON l.LOCCD = 'S' || LPAD(h.STR_NO::VARCHAR, 3, '0')
WHERE h.TXN_TYP = 'S'
  AND h.TXN_DT >= DATEADD(day, -28, CURRENT_DATE())
GROUP BY 1, 2, 3
ORDER BY sales DESC;

-- ops: stock on hand vs store sales
SELECT i.LOC_ID, i.SKU, i.OH_QTY, SUM(t.QTY) AS sold
FROM WMS.INV_SNP i
JOIN POS.TXN_HDR h ON h.STR_NO::VARCHAR = i.LOC_ID
JOIN POS.TXN_LN t ON t.TXN_ID = h.TXN_ID AND t.SKU = i.SKU
WHERE i.SNP_DT = (SELECT MAX(SNP_DT) FROM WMS.INV_SNP)
GROUP BY 1, 2, 3
LIMIT 100;

-- ops: next delivery per store
SELECT r.LOC_ID, l.LOCNM, r.NXT_DLV_DT, r.DLV_FREQ_DAYS
FROM WMS.REPL_SCHED r
JOIN ERP.LOCMST l ON l.LOCCD = r.LOC_ID
ORDER BY r.NXT_DLV_DT;

-- ops: top sellers last 4 weeks
SELECT t.SKU, i.ITMDSC, i.ITMCLS, SUM(t.QTY) AS units
FROM POS.TXN_LN t
JOIN POS.TXN_HDR h ON h.TXN_ID = t.TXN_ID
JOIN ERP.ITMMST i ON i.ITMNO = t.SKU
WHERE h.TXN_TYP = 'S'
  AND h.TXN_DT >= DATEADD(day, -28, CURRENT_DATE())
GROUP BY 1, 2, 3
ORDER BY units DESC
LIMIT 20;
