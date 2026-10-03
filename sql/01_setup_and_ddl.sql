/*
  01_setup_and_ddl.sql
  Creates the Alderglen Outfitters "legacy estate": one database, one schema per source system,
  deliberately cryptic names, no comments, no declared keys. See docs/legacy-estate.md.

  Portable by design: no account, organisation or user identifiers anywhere. Object names are
  session variables; change them here if they clash with anything in your account.
  Run as a role that can create databases and warehouses (SYSADMIN on a trial account).
*/

SET DB_NAME = 'ALDERGLEN_RAW';
SET WH_NAME = 'SVC_WH';

-- Tag this session so the mapping step can exclude it from query history (ADR-007).
ALTER SESSION SET QUERY_TAG = 'SVC_BUILD';

CREATE WAREHOUSE IF NOT EXISTS IDENTIFIER($WH_NAME)
  WAREHOUSE_SIZE = 'XSMALL'
  AUTO_SUSPEND = 60
  AUTO_RESUME = TRUE
  INITIALLY_SUSPENDED = TRUE;
USE WAREHOUSE IDENTIFIER($WH_NAME);

CREATE DATABASE IF NOT EXISTS IDENTIFIER($DB_NAME);
USE DATABASE IDENTIFIER($DB_NAME);

-- One schema per source system, the way a lift-and-shift landing zone usually looks.
CREATE SCHEMA IF NOT EXISTS ERP;   -- legacy ERP: customers, locations, items, vendors, purchasing, store credit
CREATE SCHEMA IF NOT EXISTS OMS;   -- order management: online, click-and-collect, phone orders
CREATE SCHEMA IF NOT EXISTS POS;   -- in-store point of sale
CREATE SCHEMA IF NOT EXISTS WMS;   -- warehouse management: stock on hand, replenishment schedule
CREATE SCHEMA IF NOT EXISTS LOY;   -- Basecamp Rewards loyalty platform
CREATE SCHEMA IF NOT EXISTS BIL;   -- subscription billing

/* ---------- ERP ---------- */

CREATE OR REPLACE TABLE ERP.CUSMST (
  CUSNO     NUMBER(10,0),
  CUSNM1    VARCHAR(40),
  CUSTYP    CHAR(1),
  STSCD     CHAR(1),
  CRTDT     NUMBER(8,0),
  LOYNO     VARCHAR(16),
  LSTPURDT  DATE,
  LSTUPD    TIMESTAMP_NTZ
);

CREATE OR REPLACE TABLE ERP.LOCMST (
  LOCCD   VARCHAR(6),
  LOCNM   VARCHAR(40),
  LOCTYP  CHAR(1),
  REGCD   VARCHAR(4),
  OPNDT   NUMBER(8,0)
);

CREATE OR REPLACE TABLE ERP.VNDMST (
  VNDNO   NUMBER(6,0),
  VNDNM   VARCHAR(40),
  VNDCTY  VARCHAR(3)
);

CREATE OR REPLACE TABLE ERP.ITMMST (
  ITMNO   NUMBER(8,0),
  ITMDSC  VARCHAR(60),
  ITMCLS  VARCHAR(4),
  VNDNO   NUMBER(6,0),
  STDCST  NUMBER(10,2),
  RTLPRC  NUMBER(10,2)
);

CREATE OR REPLACE TABLE ERP.POHDR (
  PONUM     NUMBER(10,0),
  VNDNO     NUMBER(6,0),
  WHSCD     VARCHAR(6),
  ORDDT     DATE,
  AGRSHPDT  DATE,
  EXPRCVDT  DATE,
  POSTAT    CHAR(1)
);

CREATE OR REPLACE TABLE ERP.PODTL (
  PONUM   NUMBER(10,0),
  LINSEQ  NUMBER(4,0),
  ITMNO   NUMBER(8,0),
  ORDQTY  NUMBER(8,0),
  UNTCST  NUMBER(10,2)
);

CREATE OR REPLACE TABLE ERP.PORCV (
  RCVNO     NUMBER(10,0),
  PONUM     NUMBER(10,0),
  ACTSHPDT  DATE,
  RCVDT     DATE,
  RCVQTY    NUMBER(8,0)
);

CREATE OR REPLACE TABLE ERP.SCLDGR (
  LDGSEQ  NUMBER(12,0),
  CUSNO   NUMBER(10,0),
  TXNDT   DATE,
  TXNTYP  VARCHAR(3),
  TXNAMT  NUMBER(10,2)
);

/* ---------- OMS ---------- */

CREATE OR REPLACE TABLE OMS.ORD_HDR (
  ORD_ID      NUMBER(12,0),
  CUST_REF    VARCHAR(12),
  CHNL_CD     VARCHAR(3),
  ORD_TS      TIMESTAMP_NTZ,
  PRM_DLV_DT  DATE,
  ORD_STAT    VARCHAR(3),
  FUL_LOC     VARCHAR(6),
  SHP_FEE     NUMBER(8,2)
);

CREATE OR REPLACE TABLE OMS.ORD_LN (
  ORD_ID   NUMBER(12,0),
  LN_NO    NUMBER(4,0),
  ITM_NO   NUMBER(8,0),
  QTY      NUMBER(6,0),
  NET_AMT  NUMBER(10,2)
);

CREATE OR REPLACE TABLE OMS.SHPMT (
  SHPMT_ID    NUMBER(12,0),
  ORD_ID      NUMBER(12,0),
  CARRIER_CD  VARCHAR(4),
  SHP_TS      TIMESTAMP_NTZ,
  EST_DLV_DT  DATE,
  DLV_TS      TIMESTAMP_NTZ
);

/* ---------- POS ---------- */

CREATE OR REPLACE TABLE POS.TXN_HDR (
  TXN_ID   NUMBER(14,0),
  STR_NO   NUMBER(4,0),
  TXN_DT   DATE,
  TXN_TM   VARCHAR(6),
  CUST_NO  NUMBER(10,0),
  TXN_TYP  CHAR(1)
);

CREATE OR REPLACE TABLE POS.TXN_LN (
  TXN_ID    NUMBER(14,0),
  LN        NUMBER(4,0),
  SKU       NUMBER(8,0),
  QTY       NUMBER(6,0),
  UNIT_PRC  NUMBER(10,2),
  EXT_AMT   NUMBER(10,2)
);

/* ---------- WMS ---------- */

CREATE OR REPLACE TABLE WMS.INV_SNP (
  SNP_DT     DATE,
  LOC_ID     VARCHAR(6),
  SKU        NUMBER(8,0),
  OH_QTY     NUMBER(8,0),
  ALLOC_QTY  NUMBER(8,0),
  UPD_TS     TIMESTAMP_NTZ
);

CREATE OR REPLACE TABLE WMS.REPL_SCHED (
  LOC_ID         VARCHAR(6),
  NXT_DLV_DT     DATE,
  DLV_FREQ_DAYS  NUMBER(3,0)
);

/* ---------- LOY ---------- */

CREATE OR REPLACE TABLE LOY.MBR (
  MBR_ID     NUMBER(10,0),
  CARD_NO    VARCHAR(16),
  ENRL_DT    DATE,
  CARD_STAT  VARCHAR(3),
  TIER_CD    VARCHAR(2)
);

CREATE OR REPLACE TABLE LOY.PTS_TXN (
  PTS_TXN_ID  NUMBER(12,0),
  MBR_ID      NUMBER(10,0),
  TXN_DT      DATE,
  TXN_CD      VARCHAR(4),
  PTS         NUMBER(8,0)
);

CREATE OR REPLACE TABLE LOY.EML_EVT (
  EVT_ID   NUMBER(12,0),
  MBR_ID   NUMBER(10,0),
  CMP_CD   VARCHAR(10),
  EVT_TS   TIMESTAMP_NTZ,
  EVT_TYP  VARCHAR(3)
);

/* ---------- BIL ---------- */

CREATE OR REPLACE TABLE BIL.SUB (
  SUB_ID    NUMBER(10,0),
  CUSNO     NUMBER(10,0),
  PLAN_CD   VARCHAR(8),
  START_DT  DATE,
  END_DT    DATE,
  STAT      CHAR(1)
);
