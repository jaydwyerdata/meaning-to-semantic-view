/*
  02_load_data.sql
  Loads synthetic data into the Alderglen legacy estate created by 01_setup_and_ddl.sql.

  Deterministic: every "random" choice is MOD(ABS(HASH(key, 'salt')), n), so the same keys always
  produce the same values. Dates are relative to AS_OF (the day you run it), so recency-based
  definitions ("ordered in the last 90 days") stay meaningful whenever the script is rerun.
  Rerunnable: every table is truncated first.

  Approximate volumes: 5,000 customers, 20,000 online orders, 150,000 POS transactions,
  3,000 purchase orders, ~3,000 loyalty members, ~350,000 inventory snapshot rows.
  Runs in a few minutes on an XSMALL warehouse.
*/

SET DB_NAME = 'ALDERGLEN_RAW';
SET WH_NAME = 'SVC_WH';

-- Tag this session so the mapping step can exclude it from query history (ADR-007).
ALTER SESSION SET QUERY_TAG = 'SVC_BUILD';
USE WAREHOUSE IDENTIFIER($WH_NAME);
USE DATABASE IDENTIFIER($DB_NAME);

SET AS_OF = CURRENT_DATE();

TRUNCATE TABLE ERP.CUSMST;  TRUNCATE TABLE ERP.LOCMST;  TRUNCATE TABLE ERP.VNDMST;
TRUNCATE TABLE ERP.ITMMST;  TRUNCATE TABLE ERP.POHDR;   TRUNCATE TABLE ERP.PODTL;
TRUNCATE TABLE ERP.PORCV;   TRUNCATE TABLE ERP.SCLDGR;
TRUNCATE TABLE OMS.ORD_HDR; TRUNCATE TABLE OMS.ORD_LN;  TRUNCATE TABLE OMS.SHPMT;
TRUNCATE TABLE POS.TXN_HDR; TRUNCATE TABLE POS.TXN_LN;
TRUNCATE TABLE WMS.INV_SNP; TRUNCATE TABLE WMS.REPL_SCHED;
TRUNCATE TABLE LOY.MBR;     TRUNCATE TABLE LOY.PTS_TXN; TRUNCATE TABLE LOY.EML_EVT;
TRUNCATE TABLE BIL.SUB;

/* =========================================================================================
   Reference data: locations, vendors, items
   ========================================================================================= */

-- 120 stores (S001..S120), 4 distribution centres (DC01..DC04), 1 web channel location.
INSERT INTO ERP.LOCMST (LOCCD, LOCNM, LOCTYP, REGCD, OPNDT)
WITH g AS (SELECT ROW_NUMBER() OVER (ORDER BY SEQ4()) AS rn FROM TABLE(GENERATOR(ROWCOUNT => 120))),
     a AS (SELECT ARRAY_CONSTRUCT('RIDGEWAY','PINE HOLLOW','KESTREL BAY','GRANITE FALLS','MOSSVALE',
                                  'EAGLE POINT','FERNBROOK','CEDAR FLATS','IRONBARK','WILLOW CREEK',
                                  'STONEY RISE','HARBOUR END') AS towns)
SELECT 'S' || LPAD(g.rn::VARCHAR, 3, '0'),
       'ALG ' || GET(a.towns, MOD(g.rn, 12))::VARCHAR || ' #' || g.rn,
       'S',
       'R' || (MOD(g.rn, 6) + 1),
       TO_NUMBER(TO_CHAR(DATEADD(day, -(400 + MOD(ABS(HASH(g.rn, 'opn')), 6000)), $AS_OF), 'YYYYMMDD'))
FROM g CROSS JOIN a;

INSERT INTO ERP.LOCMST (LOCCD, LOCNM, LOCTYP, REGCD, OPNDT) VALUES
  ('DC01', 'ALG DC NORTH',   'D', 'R1', 20120301),
  ('DC02', 'ALG DC SOUTH',   'D', 'R3', 20140715),
  ('DC03', 'ALG DC WEST',    'D', 'R5', 20170109),
  ('DC04', 'ALG DC CENTRAL', 'D', 'R2', 20200810),
  ('WEB1', 'ALG ONLINE',     'W', NULL, 20150201);

-- 40 vendors.
INSERT INTO ERP.VNDMST (VNDNO, VNDNM, VNDCTY)
WITH g AS (SELECT ROW_NUMBER() OVER (ORDER BY SEQ4()) AS rn FROM TABLE(GENERATOR(ROWCOUNT => 40))),
     a AS (SELECT ARRAY_CONSTRUCT('NORTHFACE TRADING','SUMMIT GOODS','TRAILCRAFT','BLUEGUM OUTDOOR',
                                  'KIWI GEAR','HIGHLINE MFG','PEAKSTONE','RIVERBEND SUPPLY') AS names,
                  ARRAY_CONSTRUCT('AUS','CHN','VNM','NZL','USA') AS ctys)
SELECT 5000 + g.rn,
       GET(a.names, MOD(g.rn, 8))::VARCHAR || ' ' || (FLOOR(g.rn / 8) + 1)::VARCHAR,
       GET(a.ctys, MOD(ABS(HASH(g.rn, 'cty')), 5))::VARCHAR
FROM g CROSS JOIN a;

-- 800 items across 8 classes. Items 200001..200200 are the fast movers.
INSERT INTO ERP.ITMMST (ITMNO, ITMDSC, ITMCLS, VNDNO, STDCST, RTLPRC)
WITH g AS (SELECT ROW_NUMBER() OVER (ORDER BY SEQ4()) AS rn FROM TABLE(GENERATOR(ROWCOUNT => 800))),
     a AS (SELECT ARRAY_CONSTRUCT('TNT','SLP','LGT','CKG','JKT','FTW','PCK','HYD') AS cls,
                  ARRAY_CONSTRUCT('TENT','SLEEPING BAG','HEADLAMP','CAMP STOVE','RAIN JACKET',
                                  'HIKING BOOT','DAYPACK','WATER FILTER') AS nouns,
                  ARRAY_CONSTRUCT('SUMMIT','TRAILHEAD','BASIN','RIDGE','TARN','SCREE','CAIRN','BLUFF') AS models),
     b AS (SELECT g.rn,
                  MOD(ABS(HASH(g.rn, 'cls')), 8) AS ci,
                  MOD(ABS(HASH(g.rn, 'mdl')), 8) AS mi,
                  (20 + MOD(ABS(HASH(g.rn, 'prc')), 580)) + 0.95 AS prc
           FROM g)
SELECT 200000 + b.rn,
       GET(a.models, b.mi)::VARCHAR || ' ' || GET(a.nouns, b.ci)::VARCHAR || ' MK' || (MOD(b.rn, 5) + 1),
       GET(a.cls, b.ci)::VARCHAR,
       5001 + MOD(ABS(HASH(b.rn, 'vnd')), 40),
       ROUND(b.prc * 0.45, 2),
       b.prc
FROM b CROSS JOIN a;

/* =========================================================================================
   Customers, subscriptions, store credit
   ========================================================================================= */

-- 5,000 customers. CUSTYP: R retail, E employee, I internal/test account.
-- STSCD is the ERP *account* status (A/I/X), which is not what anyone means by "active customer".
INSERT INTO ERP.CUSMST (CUSNO, CUSNM1, CUSTYP, STSCD, CRTDT, LOYNO, LSTPURDT, LSTUPD)
WITH g AS (SELECT ROW_NUMBER() OVER (ORDER BY SEQ4()) AS rn FROM TABLE(GENERATOR(ROWCOUNT => 5000))),
     a AS (SELECT ARRAY_CONSTRUCT('SMITH','NGUYEN','PATEL','JONES','WILLIAMS','BROWN','TAYLOR','LEE',
                                  'WILSON','MARTIN','ANDERSON','THOMPSON','WHITE','KELLY','RYAN',
                                  'WALKER','HARRIS','KING','CHEN','MURPHY') AS lasts,
                  ARRAY_CONSTRUCT('OLIVIA','JACK','MIA','NOAH','CHARLOTTE','WILLIAM','AVA','LEO',
                                  'GRACE','OLIVER','ISLA','HENRY','RUBY','LUCAS','ZOE','ARCHIE',
                                  'AMELIA','THOMAS','CHLOE','JAMES') AS firsts)
SELECT 100000 + g.rn,
       GET(a.lasts, MOD(ABS(HASH(g.rn, 'ln')), 20))::VARCHAR || ', ' ||
         GET(a.firsts, MOD(ABS(HASH(g.rn, 'fn')), 20))::VARCHAR,
       CASE WHEN MOD(ABS(HASH(g.rn, 'typ')), 100) < 2 THEN 'I'
            WHEN MOD(ABS(HASH(g.rn, 'typ')), 100) < 5 THEN 'E'
            ELSE 'R' END,
       CASE WHEN MOD(ABS(HASH(g.rn, 'sts')), 100) < 85 THEN 'A'
            WHEN MOD(ABS(HASH(g.rn, 'sts')), 100) < 95 THEN 'I'
            ELSE 'X' END,
       TO_NUMBER(TO_CHAR(DATEADD(day, -(60 + MOD(ABS(HASH(g.rn, 'crt')), 1800)), $AS_OF), 'YYYYMMDD')),
       CASE WHEN MOD(ABS(HASH(g.rn, 'loy')), 100) < 55
            THEN 'BC' || LPAD((900000 + g.rn)::VARCHAR, 10, '0') END,
       NULL,
       NULL
FROM g CROSS JOIN a;

-- ~800 subscriptions. "Open" is ambiguous on purpose: paused (P) subs have no END_DT, and a small
-- legacy batch is cancelled (C) with END_DT never populated.
INSERT INTO BIL.SUB (SUB_ID, CUSNO, PLAN_CD, START_DT, END_DT, STAT)
WITH g AS (SELECT ROW_NUMBER() OVER (ORDER BY SEQ4()) AS rn FROM TABLE(GENERATOR(ROWCOUNT => 800))),
     b AS (SELECT g.rn,
                  MOD(ABS(HASH(g.rn, 'sst')), 100) AS s,
                  DATEADD(day, -MOD(ABS(HASH(g.rn, 'sdt')), 900), $AS_OF) AS sdt
           FROM g)
SELECT 30000 + b.rn,
       100001 + MOD(ABS(HASH(b.rn, 'subc')), 5000),
       CASE WHEN MOD(ABS(HASH(b.rn, 'pln')), 3) = 0 THEN 'BCPLUSA' ELSE 'BCPLUS' END,
       b.sdt,
       CASE WHEN b.s < 65 OR b.s >= 95 THEN NULL
            ELSE LEAST(DATEADD(day, 30 + MOD(ABS(HASH(b.rn, 'end')), 300), b.sdt), DATEADD(day, -1, $AS_OF)) END,
       CASE WHEN b.s < 55 THEN 'A' WHEN b.s < 65 THEN 'P' ELSE 'C' END
FROM b;

-- ~6,000 store-credit ledger movements across ~1,500 customers. Balance = SUM(TXNAMT); there is no
-- balance column anywhere, and a few balances go negative (misposted redemptions).
INSERT INTO ERP.SCLDGR (LDGSEQ, CUSNO, TXNDT, TXNTYP, TXNAMT)
WITH g AS (SELECT ROW_NUMBER() OVER (ORDER BY SEQ4()) AS rn FROM TABLE(GENERATOR(ROWCOUNT => 6000))),
     b AS (SELECT g.rn, MOD(ABS(HASH(g.rn, 'sct')), 100) AS t FROM g)
SELECT b.rn,
       100001 + MOD(ABS(HASH(b.rn, 'scc')), 1500) * 3,
       DATEADD(day, -MOD(ABS(HASH(b.rn, 'scd')), 540), $AS_OF),
       CASE WHEN b.t < 55 THEN 'ISS' WHEN b.t < 85 THEN 'RDM' WHEN b.t < 95 THEN 'EXP' ELSE 'ADJ' END,
       CASE WHEN b.t < 55 THEN  (10 + MOD(ABS(HASH(b.rn, 'sca')), 190))
            WHEN b.t < 85 THEN -(5  + MOD(ABS(HASH(b.rn, 'sca')), 75))
            WHEN b.t < 95 THEN -(5  + MOD(ABS(HASH(b.rn, 'sca')), 35))
            ELSE (MOD(ABS(HASH(b.rn, 'sca')), 41) - 20) END
FROM b;

/* =========================================================================================
   Loyalty (Basecamp Rewards)
   ========================================================================================= */

-- Members linked to ERP customers by CARD_NO = CUSMST.LOYNO (not by MBR_ID), plus 300 members who
-- signed up in store and never got an ERP customer record.
INSERT INTO LOY.MBR (MBR_ID, CARD_NO, ENRL_DT, CARD_STAT, TIER_CD)
SELECT 7000000 + ROW_NUMBER() OVER (ORDER BY CUSNO),
       LOYNO,
       DATEADD(day, -(30 + MOD(ABS(HASH(CUSNO, 'enr')), 1500)), $AS_OF),
       CASE WHEN MOD(ABS(HASH(CUSNO, 'cst')), 100) < 90 THEN 'ACT'
            WHEN MOD(ABS(HASH(CUSNO, 'cst')), 100) < 95 THEN 'LST'
            ELSE 'CLS' END,
       CASE WHEN MOD(ABS(HASH(CUSNO, 'tir')), 100) < 70 THEN 'BR'
            WHEN MOD(ABS(HASH(CUSNO, 'tir')), 100) < 92 THEN 'SI'
            ELSE 'GO' END
FROM ERP.CUSMST
WHERE LOYNO IS NOT NULL;

INSERT INTO LOY.MBR (MBR_ID, CARD_NO, ENRL_DT, CARD_STAT, TIER_CD)
WITH g AS (SELECT ROW_NUMBER() OVER (ORDER BY SEQ4()) AS rn FROM TABLE(GENERATOR(ROWCOUNT => 300)))
SELECT 7100000 + g.rn,
       'BC' || LPAD((990000 + g.rn)::VARCHAR, 10, '0'),
       DATEADD(day, -(30 + MOD(ABS(HASH(g.rn, 'oenr')), 900)), $AS_OF),
       'ACT',
       'BR'
FROM g;

SET N_MBR = (SELECT COUNT(*) FROM LOY.MBR);

-- 40,000 points movements. ~45% of members are dormant: nothing in the last 180 days.
INSERT INTO LOY.PTS_TXN (PTS_TXN_ID, MBR_ID, TXN_DT, TXN_CD, PTS)
WITH g AS (SELECT ROW_NUMBER() OVER (ORDER BY SEQ4()) AS rn FROM TABLE(GENERATOR(ROWCOUNT => 40000))),
     m AS (SELECT MBR_ID, ROW_NUMBER() OVER (ORDER BY MBR_ID) - 1 AS idx FROM LOY.MBR),
     b AS (SELECT g.rn,
                  m.MBR_ID,
                  MOD(ABS(HASH(m.MBR_ID, 'dorm')), 100) < 45 AS dormant,
                  MOD(ABS(HASH(g.rn, 'pdt')), 540) AS d,
                  MOD(ABS(HASH(g.rn, 'pcd')), 100) AS c
           FROM g JOIN m ON m.idx = MOD(ABS(HASH(g.rn, 'pm')), $N_MBR))
SELECT 60000000 + b.rn,
       b.MBR_ID,
       DATEADD(day, -(CASE WHEN b.dormant THEN 180 + MOD(b.d, 360) ELSE b.d END), $AS_OF),
       CASE WHEN b.c < 70 THEN 'EARN' WHEN b.c < 85 THEN 'RDM' WHEN b.c < 95 THEN 'EXP' ELSE 'ADJ' END,
       CASE WHEN b.c < 70 THEN  (10 + MOD(ABS(HASH(b.rn, 'pts')), 490))
            WHEN b.c < 85 THEN -(500 + MOD(ABS(HASH(b.rn, 'pts')), 2000))
            WHEN b.c < 95 THEN -(10 + MOD(ABS(HASH(b.rn, 'pts')), 200))
            ELSE (MOD(ABS(HASH(b.rn, 'pts')), 201) - 100) END
FROM b;

-- 60,000 email events. Dormant members are still being *sent* email, they just stopped opening it.
-- SND = sent, OPN = opened, CLK = clicked (logged separately from the open), BNC = bounced,
-- UNS = unsubscribed.
INSERT INTO LOY.EML_EVT (EVT_ID, MBR_ID, CMP_CD, EVT_TS, EVT_TYP)
WITH g AS (SELECT ROW_NUMBER() OVER (ORDER BY SEQ4()) AS rn FROM TABLE(GENERATOR(ROWCOUNT => 60000))),
     m AS (SELECT MBR_ID, ROW_NUMBER() OVER (ORDER BY MBR_ID) - 1 AS idx FROM LOY.MBR),
     b AS (SELECT g.rn,
                  m.MBR_ID,
                  MOD(ABS(HASH(m.MBR_ID, 'dorm')), 100) < 45 AS dormant,
                  MOD(ABS(HASH(g.rn, 'edt')), 540) AS d,
                  MOD(ABS(HASH(g.rn, 'etp')), 100) AS t
           FROM g JOIN m ON m.idx = MOD(ABS(HASH(g.rn, 'em')), $N_MBR)),
     c AS (SELECT b.*, DATEADD(day, -b.d, $AS_OF) AS edate FROM b)
SELECT 80000000 + c.rn,
       c.MBR_ID,
       'BC' || TO_CHAR(c.edate, 'YY') || 'W' || LPAD(WEEKISO(c.edate)::VARCHAR, 2, '0'),
       DATEADD(second, MOD(ABS(HASH(c.rn, 'ets')), 86400), c.edate::TIMESTAMP_NTZ),
       CASE WHEN c.dormant AND c.d < 180 THEN 'SND'
            WHEN c.t < 60 THEN 'SND' WHEN c.t < 80 THEN 'OPN' WHEN c.t < 90 THEN 'CLK'
            WHEN c.t < 95 THEN 'BNC' ELSE 'UNS' END
FROM c;

/* =========================================================================================
   Point of sale
   ========================================================================================= */

-- 150,000 in-store transactions. STR_NO is numeric (12), while ERP.LOCMST uses 'S012'.
-- CUST_NO is only captured when a loyalty card or account is presented (~45%).
-- ~35% of customers are lapsed: no purchases in the last 120 days, on either channel.
-- TXN_TYP: S sale, R return, V void. Return quantities and amounts are stored as positive numbers.
INSERT INTO POS.TXN_HDR (TXN_ID, STR_NO, TXN_DT, TXN_TM, CUST_NO, TXN_TYP)
WITH g AS (SELECT ROW_NUMBER() OVER (ORDER BY SEQ4()) AS rn FROM TABLE(GENERATOR(ROWCOUNT => 150000))),
     b AS (SELECT g.rn,
                  CASE WHEN MOD(ABS(HASH(g.rn, 'pid')), 100) < 45
                       THEN 100001 + MOD(ABS(HASH(g.rn, 'pc')), 5000) END AS cust,
                  MOD(ABS(HASH(g.rn, 'pdt')), 540) AS d,
                  MOD(ABS(HASH(g.rn, 'ptp')), 100) AS t
           FROM g),
     c AS (SELECT b.*,
                  CASE WHEN b.cust IS NOT NULL AND MOD(ABS(HASH(b.cust, 'lapse')), 100) < 35
                       THEN 120 + MOD(b.d, 420) ELSE b.d END AS days_ago
           FROM b)
SELECT 50000000000 + c.rn,
       1 + MOD(ABS(HASH(c.rn, 'str')), 120),
       DATEADD(day, -c.days_ago, $AS_OF),
       LPAD((8 + MOD(ABS(HASH(c.rn, 'hh')), 13))::VARCHAR, 2, '0') ||
         LPAD(MOD(ABS(HASH(c.rn, 'mi')), 60)::VARCHAR, 2, '0') || '00',
       c.cust,
       CASE WHEN c.t < 90 THEN 'S' WHEN c.t < 97 THEN 'R' ELSE 'V' END
FROM c;

-- 1 to 4 lines per transaction. 60% of lines are the 10 hero SKUs (200001..200010), 25% the
-- other fast movers (up to 200200), 15% the long tail.
INSERT INTO POS.TXN_LN (TXN_ID, LN, SKU, QTY, UNIT_PRC, EXT_AMT)
WITH n AS (SELECT ROW_NUMBER() OVER (ORDER BY SEQ4()) AS ln FROM TABLE(GENERATOR(ROWCOUNT => 4))),
     b AS (SELECT h.TXN_ID,
                  n.ln,
                  CASE WHEN MOD(ABS(HASH(h.TXN_ID, n.ln, 'fast')), 100) < 60
                       THEN 200001 + MOD(ABS(HASH(h.TXN_ID, n.ln, 'sku')), 10)
                       WHEN MOD(ABS(HASH(h.TXN_ID, n.ln, 'fast')), 100) < 85
                       THEN 200001 + MOD(ABS(HASH(h.TXN_ID, n.ln, 'sku')), 200)
                       ELSE 200001 + MOD(ABS(HASH(h.TXN_ID, n.ln, 'sku')), 800) END AS sku,
                  CASE WHEN MOD(ABS(HASH(h.TXN_ID, n.ln, 'q')), 100) < 85 THEN 1
                       ELSE 2 + MOD(ABS(HASH(h.TXN_ID, n.ln, 'q2')), 3) END AS qty
           FROM POS.TXN_HDR h
           JOIN n ON n.ln <= 1 + MOD(ABS(HASH(h.TXN_ID, 'nl')), 4))
SELECT b.TXN_ID, b.ln, b.sku, b.qty, i.RTLPRC, b.qty * i.RTLPRC
FROM b JOIN ERP.ITMMST i ON i.ITMNO = b.sku;

/* =========================================================================================
   Order management
   ========================================================================================= */

-- 20,000 orders. CUST_REF is 'C' + zero-padded ERP CUSNO (C00101234), or 'GUEST' for guest checkout.
-- SHP_FEE is a header-level amount: summing it after joining to ORD_LN or SHPMT double counts it.
INSERT INTO OMS.ORD_HDR (ORD_ID, CUST_REF, CHNL_CD, ORD_TS, PRM_DLV_DT, ORD_STAT, FUL_LOC, SHP_FEE)
WITH g AS (SELECT ROW_NUMBER() OVER (ORDER BY SEQ4()) AS rn FROM TABLE(GENERATOR(ROWCOUNT => 20000))),
     b AS (SELECT g.rn,
                  100001 + MOD(ABS(HASH(g.rn, 'oc')), 5000) AS cust,
                  MOD(ABS(HASH(g.rn, 'gst')), 100) < 10 AS guest,
                  MOD(ABS(HASH(g.rn, 'odt')), 540) AS d,
                  MOD(ABS(HASH(g.rn, 'och')), 100) AS ch
           FROM g),
     c AS (SELECT b.*,
                  CASE WHEN NOT b.guest AND MOD(ABS(HASH(b.cust, 'lapse')), 100) < 35
                       THEN 120 + MOD(b.d, 420) ELSE b.d END AS days_ago,
                  CASE WHEN b.ch < 80 THEN 'WEB' WHEN b.ch < 95 THEN 'CNC' ELSE 'PHN' END AS chnl
           FROM b),
     o AS (SELECT c.*,
                  DATEADD(second, MOD(ABS(HASH(c.rn, 'ots')), 86400),
                          DATEADD(day, -c.days_ago, $AS_OF)::TIMESTAMP_NTZ) AS ots
           FROM c)
SELECT 900000000 + o.rn,
       CASE WHEN o.guest THEN 'GUEST' ELSE 'C' || LPAD(o.cust::VARCHAR, 8, '0') END,
       o.chnl,
       o.ots,
       DATEADD(day, 2 + MOD(ABS(HASH(o.rn, 'prm')), 6), o.ots::DATE),
       CASE WHEN o.days_ago < 5 THEN 'OPN'
            WHEN MOD(ABS(HASH(o.rn, 'cnl')), 100) < 6 THEN 'CNL'
            ELSE 'CMP' END,
       CASE WHEN o.chnl = 'CNC' THEN 'S' || LPAD((1 + MOD(ABS(HASH(o.rn, 'fl')), 120))::VARCHAR, 3, '0')
            ELSE 'DC0' || (1 + MOD(ABS(HASH(o.rn, 'fl')), 4)) END,
       CASE WHEN o.chnl = 'CNC' OR MOD(ABS(HASH(o.rn, 'fee')), 100) < 40 THEN 0 ELSE 9.95 END
FROM o;

INSERT INTO OMS.ORD_LN (ORD_ID, LN_NO, ITM_NO, QTY, NET_AMT)
WITH n AS (SELECT ROW_NUMBER() OVER (ORDER BY SEQ4()) AS ln FROM TABLE(GENERATOR(ROWCOUNT => 4))),
     b AS (SELECT h.ORD_ID,
                  n.ln,
                  CASE WHEN MOD(ABS(HASH(h.ORD_ID, n.ln, 'fast')), 100) < 70
                       THEN 200001 + MOD(ABS(HASH(h.ORD_ID, n.ln, 'itm')), 200)
                       ELSE 200001 + MOD(ABS(HASH(h.ORD_ID, n.ln, 'itm')), 800) END AS itm,
                  CASE WHEN MOD(ABS(HASH(h.ORD_ID, n.ln, 'q')), 100) < 88 THEN 1 ELSE 2 END AS qty,
                  CASE WHEN MOD(ABS(HASH(h.ORD_ID, n.ln, 'dsc')), 100) < 25 THEN 0.9 ELSE 1 END AS disc
           FROM OMS.ORD_HDR h
           JOIN n ON n.ln <= 1 + MOD(ABS(HASH(h.ORD_ID, 'nl')), 4))
SELECT b.ORD_ID, b.ln, b.itm, b.qty, ROUND(b.qty * i.RTLPRC * b.disc, 2)
FROM b JOIN ERP.ITMMST i ON i.ITMNO = b.itm;

-- Shipments for every non-cancelled order; ~15% are split into two shipments.
-- EST_DLV_DT is the carrier's estimate, PRM_DLV_DT on the order is what the customer was promised.
-- DLV_TS is NULL while a parcel is still in transit.
INSERT INTO OMS.SHPMT (SHPMT_ID, ORD_ID, CARRIER_CD, SHP_TS, EST_DLV_DT, DLV_TS)
WITH n AS (SELECT ROW_NUMBER() OVER (ORDER BY SEQ4()) AS sn FROM TABLE(GENERATOR(ROWCOUNT => 2))),
     a AS (SELECT ARRAY_CONSTRUCT('AUSP','STRT','CPLE','TOLL') AS carriers),
     b AS (SELECT h.ORD_ID,
                  n.sn,
                  DATEADD(hour, 6 + MOD(ABS(HASH(h.ORD_ID, n.sn, 'sh')), 54) + (n.sn - 1) * 24, h.ORD_TS) AS shp_ts,
                  1 + MOD(ABS(HASH(h.ORD_ID, n.sn, 'tr')), 4)
                    + CASE WHEN MOD(ABS(HASH(h.ORD_ID, n.sn, 'late')), 100) < 18
                           THEN 2 + MOD(ABS(HASH(h.ORD_ID, n.sn, 'lx')), 4) ELSE 0 END AS transit_days
           FROM OMS.ORD_HDR h
           JOIN n ON n.sn = 1 OR (n.sn = 2 AND MOD(ABS(HASH(h.ORD_ID, 'split')), 100) < 15)
           WHERE h.ORD_STAT <> 'CNL'),
     c AS (SELECT b.*,
                  DATEADD(hour, MOD(ABS(HASH(b.ORD_ID, b.sn, 'dh')), 10),
                          DATEADD(day, b.transit_days, b.shp_ts)) AS dlv_ts
           FROM b)
SELECT 800000000 + ROW_NUMBER() OVER (ORDER BY c.ORD_ID, c.sn),
       c.ORD_ID,
       GET(a.carriers, MOD(ABS(HASH(c.ORD_ID, 'car')), 4))::VARCHAR,
       c.shp_ts,
       DATEADD(day, 2 + MOD(ABS(HASH(c.ORD_ID, c.sn, 'est')), 3), c.shp_ts::DATE),
       CASE WHEN c.dlv_ts > $AS_OF::TIMESTAMP_NTZ THEN NULL ELSE c.dlv_ts END
FROM c CROSS JOIN a
WHERE c.shp_ts <= $AS_OF::TIMESTAMP_NTZ;

/* =========================================================================================
   Purchasing (ERP)
   ========================================================================================= */

-- 3,000 purchase orders to the DCs. AGRSHPDT is the ship-by cutoff agreed with the vendor;
-- EXPRCVDT is the planner's expected receipt date at the DC. POSTAT: O open, R received, X cancelled.
INSERT INTO ERP.POHDR (PONUM, VNDNO, WHSCD, ORDDT, AGRSHPDT, EXPRCVDT, POSTAT)
WITH g AS (SELECT ROW_NUMBER() OVER (ORDER BY SEQ4()) AS rn FROM TABLE(GENERATOR(ROWCOUNT => 3000))),
     b AS (SELECT g.rn,
                  DATEADD(day, -MOD(ABS(HASH(g.rn, 'pod')), 540), $AS_OF) AS orddt,
                  7 + MOD(ABS(HASH(g.rn, 'agr')), 15) AS lead_days
           FROM g)
SELECT 4000000 + b.rn,
       5001 + MOD(ABS(HASH(b.rn, 'pv')), 40),
       'DC0' || (1 + MOD(ABS(HASH(b.rn, 'pw')), 4)),
       b.orddt,
       DATEADD(day, b.lead_days, b.orddt),
       DATEADD(day, b.lead_days + 3 + MOD(ABS(HASH(b.rn, 'exr')), 8), b.orddt),
       CASE WHEN MOD(ABS(HASH(b.rn, 'px')), 100) < 2 THEN 'X'
            WHEN b.orddt > DATEADD(day, -25, $AS_OF) THEN 'O'
            ELSE 'R' END
FROM b;

INSERT INTO ERP.PODTL (PONUM, LINSEQ, ITMNO, ORDQTY, UNTCST)
WITH n AS (SELECT ROW_NUMBER() OVER (ORDER BY SEQ4()) AS ln FROM TABLE(GENERATOR(ROWCOUNT => 5))),
     b AS (SELECT p.PONUM,
                  n.ln,
                  200001 + MOD(ABS(HASH(p.PONUM, n.ln, 'pi')), 800) AS itm
           FROM ERP.POHDR p
           JOIN n ON n.ln <= 1 + MOD(ABS(HASH(p.PONUM, 'pnl')), 5))
SELECT b.PONUM, b.ln * 10, b.itm, 20 + MOD(ABS(HASH(b.PONUM, b.ln, 'oq')), 480), i.STDCST
FROM b JOIN ERP.ITMMST i ON i.ITMNO = b.itm;

-- One receipt per received PO, plus a backordered second receipt on ~8%.
-- ~75% of first shipments leave on or before the agreed cutoff.
INSERT INTO ERP.PORCV (RCVNO, PONUM, ACTSHPDT, RCVDT, RCVQTY)
WITH n AS (SELECT ROW_NUMBER() OVER (ORDER BY SEQ4()) AS sn FROM TABLE(GENERATOR(ROWCOUNT => 2))),
     b AS (SELECT p.PONUM,
                  n.sn,
                  CASE WHEN n.sn = 2
                       THEN DATEADD(day, 7 + MOD(ABS(HASH(p.PONUM, 'bo')), 14), p.AGRSHPDT)
                       WHEN MOD(ABS(HASH(p.PONUM, 'ot')), 100) < 75
                       THEN DATEADD(day, -MOD(ABS(HASH(p.PONUM, 'early')), 4), p.AGRSHPDT)
                       ELSE DATEADD(day, 1 + MOD(ABS(HASH(p.PONUM, 'lt')), 6), p.AGRSHPDT) END AS actshp
           FROM ERP.POHDR p
           JOIN n ON n.sn = 1 OR (n.sn = 2 AND MOD(ABS(HASH(p.PONUM, 'bk')), 100) < 8)
           WHERE p.POSTAT = 'R'),
     c AS (SELECT b.*, DATEADD(day, 2 + MOD(ABS(HASH(b.PONUM, b.sn, 'rcv')), 7), b.actshp) AS rcvdt FROM b)
SELECT 3000000 + ROW_NUMBER() OVER (ORDER BY c.PONUM, c.sn),
       c.PONUM,
       c.actshp,
       CASE WHEN c.rcvdt > $AS_OF THEN NULL ELSE c.rcvdt END,
       50 + MOD(ABS(HASH(c.PONUM, c.sn, 'rq')), 900)
FROM c
WHERE c.actshp <= $AS_OF;

/* =========================================================================================
   Warehouse management
   ========================================================================================= */

-- Next scheduled delivery per location. Stores get weekly deliveries from their DC.
INSERT INTO WMS.REPL_SCHED (LOC_ID, NXT_DLV_DT, DLV_FREQ_DAYS)
SELECT LOCCD,
       CASE WHEN LOCTYP = 'S' THEN DATEADD(day, 1 + MOD(ABS(HASH(LOCCD, 'nxt')), 7), $AS_OF)
            ELSE DATEADD(day, 3 + MOD(ABS(HASH(LOCCD, 'nxt')), 10), $AS_OF) END,
       CASE WHEN LOCTYP = 'S' THEN 7 ELSE 14 END
FROM ERP.LOCMST
WHERE LOCTYP IN ('S', 'D');

-- Overnight cycle-count snapshots for the last 14 days, fast movers only, stores and DCs.
-- Hero SKUs run lean in stores (0 to 8 on hand), so whether they are at risk depends on how fast
-- they sell and how far away the next delivery is, not on whether the count has hit zero. Some
-- slow fast-movers sit at zero with no recent sales at all.
-- The snapshot for day D posts at 02:15 on day D+1. ALLOC_QTY is stock reserved for
-- click-and-collect orders but still physically on the shelf.
INSERT INTO WMS.INV_SNP (SNP_DT, LOC_ID, SKU, OH_QTY, ALLOC_QTY, UPD_TS)
WITH d AS (SELECT ROW_NUMBER() OVER (ORDER BY SEQ4()) AS k FROM TABLE(GENERATOR(ROWCOUNT => 14))),
     s AS (SELECT ROW_NUMBER() OVER (ORDER BY SEQ4()) AS r FROM TABLE(GENERATOR(ROWCOUNT => 200))),
     l AS (SELECT LOCCD, LOCTYP FROM ERP.LOCMST WHERE LOCTYP IN ('S', 'D')),
     b AS (SELECT DATEADD(day, -d.k, $AS_OF) AS snp_dt,
                  l.LOCCD,
                  l.LOCTYP,
                  200000 + s.r AS sku,
                  CASE WHEN s.r <= 10
                       THEN GREATEST(0, MOD(ABS(HASH(l.LOCCD, s.r, 'base')), 9)
                                        - MOD(ABS(HASH(l.LOCCD, s.r, d.k, 'drift')), 3))
                       ELSE GREATEST(0, MOD(ABS(HASH(l.LOCCD, s.r, 'base')), 35)
                                        - MOD(ABS(HASH(l.LOCCD, s.r, d.k, 'drift')), 8)) END AS oh
           FROM d CROSS JOIN s CROSS JOIN l)
SELECT b.snp_dt,
       b.LOCCD,
       b.sku,
       CASE WHEN b.LOCTYP = 'D' THEN b.oh * 40 ELSE b.oh END,
       CASE WHEN b.LOCTYP = 'S' THEN LEAST(b.oh, MOD(ABS(HASH(b.LOCCD, b.sku, b.snp_dt, 'al')), 3)) ELSE 0 END,
       DATEADD(minute, 135, DATEADD(day, 1, b.snp_dt)::TIMESTAMP_NTZ)
FROM b;

/* =========================================================================================
   The stale "last purchase date" column
   ========================================================================================= */

-- ERP.CUSMST.LSTPURDT looks like the obvious answer to "when did this customer last buy", but the
-- nightly batch that maintained it stopped running 180 days ago and only ever read POS sales.
UPDATE ERP.CUSMST
SET LSTPURDT = s.last_dt,
    LSTUPD   = DATEADD(day, -180, $AS_OF)::TIMESTAMP_NTZ
FROM (SELECT CUST_NO, MAX(TXN_DT) AS last_dt
      FROM POS.TXN_HDR
      WHERE TXN_TYP = 'S' AND CUST_NO IS NOT NULL AND TXN_DT <= DATEADD(day, -180, $AS_OF)
      GROUP BY CUST_NO) s
WHERE ERP.CUSMST.CUSNO = s.CUST_NO;

/* =========================================================================================
   Row counts
   ========================================================================================= */

SELECT 'ERP.CUSMST' AS tbl, COUNT(*) AS row_count FROM ERP.CUSMST
UNION ALL SELECT 'ERP.LOCMST',  COUNT(*) FROM ERP.LOCMST
UNION ALL SELECT 'ERP.VNDMST',  COUNT(*) FROM ERP.VNDMST
UNION ALL SELECT 'ERP.ITMMST',  COUNT(*) FROM ERP.ITMMST
UNION ALL SELECT 'ERP.POHDR',   COUNT(*) FROM ERP.POHDR
UNION ALL SELECT 'ERP.PODTL',   COUNT(*) FROM ERP.PODTL
UNION ALL SELECT 'ERP.PORCV',   COUNT(*) FROM ERP.PORCV
UNION ALL SELECT 'ERP.SCLDGR',  COUNT(*) FROM ERP.SCLDGR
UNION ALL SELECT 'OMS.ORD_HDR', COUNT(*) FROM OMS.ORD_HDR
UNION ALL SELECT 'OMS.ORD_LN',  COUNT(*) FROM OMS.ORD_LN
UNION ALL SELECT 'OMS.SHPMT',   COUNT(*) FROM OMS.SHPMT
UNION ALL SELECT 'POS.TXN_HDR', COUNT(*) FROM POS.TXN_HDR
UNION ALL SELECT 'POS.TXN_LN',  COUNT(*) FROM POS.TXN_LN
UNION ALL SELECT 'WMS.INV_SNP', COUNT(*) FROM WMS.INV_SNP
UNION ALL SELECT 'WMS.REPL_SCHED', COUNT(*) FROM WMS.REPL_SCHED
UNION ALL SELECT 'LOY.MBR',     COUNT(*) FROM LOY.MBR
UNION ALL SELECT 'LOY.PTS_TXN', COUNT(*) FROM LOY.PTS_TXN
UNION ALL SELECT 'LOY.EML_EVT', COUNT(*) FROM LOY.EML_EVT
UNION ALL SELECT 'BIL.SUB',     COUNT(*) FROM BIL.SUB
ORDER BY 1;
