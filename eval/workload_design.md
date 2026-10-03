# Analyst workload: design notes

Evaluation-side. Says which queries in `sql/03_analyst_workload.sql` are right, wrong or partly
right. The mapping step must never read this file; it sees only the queries themselves, through
query history, the way it would in a real account.

## Principles

- Written as six analysts would write them: short comments in their own words, including their
  wrong beliefs. Nothing in the SQL file says which queries are correct.
- Not copied from `eval/reference_queries.sql`. No query encodes a full SME definition; correct
  evidence comes in fragments (a join key here, a status filter there).
- Wrong usages outnumber or match correct ones for most traps, because that is what a real legacy
  estate's history looks like. A mapper that counts votes will be misled; one that weighs evidence
  against sample values and the SME's words should not be.

## Query by query

| # | Analyst comment | Verdict | What it shows |
|---|---|---|---|
| 1 | mkt: online orders by channel | Correct | `ORD_LN` to `ORD_HDR` on `ORD_ID`; `CNL` means cancelled |
| 2 | mkt: active customer count | Wrong | `STSCD = 'A'` used as activity (decoy) |
| 3 | mkt: lapsed customer list | Wrong | Stale `LSTPURDT` used as last purchase date (decoy) |
| 4 | mkt: in-store buyers | Partial | Correct POS to ERP key; POS channel only |
| 5 | mkt: online buyers | Partial | Correct `CUST_REF` parsing; online only, excludes `CUSTYP = 'I'` |
| 6 | mkt: customer names onto orders | Wrong | `CUST_REF` joined as a raw number; returns no rows |
| 7 | mkt: new customers by month | Neutral | `CRTDT` is a YYYYMMDD number |
| 8 | fin: store credit by customer | Correct | Balance is `SUM(TXNAMT)` over the ledger |
| 9 | fin: total store credit | Correct | As above, unaggregated by customer |
| 10 | fin: open subscriptions | Wrong | `END_DT IS NULL` alone; misses legacy cancelled rows with no end date |
| 11 | fin: subscriptions by status | Neutral | Shows `STAT` codes |
| 12 | fin: store sales by month | Wrong | Sums returns as positive sales (sign convention trap) |
| 13 | fin: net store sales (fixed) | Correct | `TXN_TYP` carries the sign |
| 14 | fin: fee income by carrier | Wrong | Header `SHP_FEE` fanned out over shipments |
| 15 | fin: fee income by month | Correct | `SHP_FEE` at header grain |
| 16 | loy: active members | Wrong | `CARD_STAT = 'ACT'` used as engagement (decoy) |
| 17 | loy: email open rate | Correct | `EVT_TYP` codes `SND`, `OPN` |
| 18 | loy: points redeemed | Correct | `TXN_CD = 'RDM'` is redemption |
| 19 | loy: members with customer details | Wrong | `MBR_ID = CUSNO`; returns no rows |
| 20 | loy: tier mix of members | Correct | `CARD_NO = LOYNO` is the member to customer link |
| 21 | cx: late deliveries by carrier | Wrong | Carrier estimate `EST_DLV_DT`, not the customer promise (decoy) |
| 22 | cx: on-time vs promise | Partial | Right date, wrong grain: per shipment, not per order |
| 23 | cx: transit days | Neutral | `SHP_TS` to `DLV_TS` |
| 24 | cx: late orders, per order | Partial | Right grain and date; counts undelivered parcels as late |
| 25 | cx: split shipments | Neutral | Shows the one-to-many fan-out |
| 26 | sc: vendor late receipts | Wrong | Planner's `EXPRCVDT` against receipt date (decoy) |
| 27 | sc: vendor fill rate | Wrong | `PODTL` and `PORCV` both joined on `PONUM`; fans out |
| 28 | sc: shipped by agreed date | Partial | Right columns; per receipt, not first shipment per PO |
| 29 | sc: open POs by DC | Correct | `WHSCD` to `LOCCD`; `POSTAT = 'O'` |
| 30 | ops: stockouts by store | Wrong | Zero on hand used as stockout (decoy) |
| 31 | ops: store sales with names | Correct | `STR_NO` to `LOCCD` as `'S' + LPAD(STR_NO, 3)` |
| 32 | ops: stock vs store sales | Wrong | `STR_NO` cast directly against `LOC_ID`; returns no rows |
| 33 | ops: next delivery per store | Correct | `REPL_SCHED.LOC_ID` to `LOCCD` |
| 34 | ops: top sellers | Correct | `SKU = ITMNO` |

## Known limits

- Each query runs once. Real history repeats dashboards hundreds of times; frequency is not
  simulated, so the mapper must not weight evidence by run count against this workload.
- One user and one role ran everything. Real history spreads across users, which is itself evidence.
