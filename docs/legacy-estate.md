# The Alderglen legacy estate

Version 0.1, 3 October 2026.

The test environment the tool is built and scored against. It models what a small data team
actually inherits: six source systems landed side by side, cryptic names, no comments, no declared
keys, several columns that look like the right answer and are not. A mapping step that works on
clean, well-named sample data proves nothing about this problem, so the estate is messy on purpose.

**This document is evaluation-side.** It is the data dictionary nobody wrote down, which is exactly
the institutional knowledge the tool is meant to recover. It, `eval/` and the comments in
`sql/02_load_data.sql` must never be given to the mapping step. The tool sees only what a real
estate would offer: catalog metadata, sample values and query history.

The business is Alderglen Outfitters, the fictional outdoor retailer from the Requirements
Accelerator's synthetic interview dataset, so the SME definitions used here are the ones already
captured there. Nothing in the estate is drawn from any real organisation.

## Source systems

| Schema | System | Tables |
|---|---|---|
| ERP | Legacy ERP | CUSMST customers, LOCMST locations, VNDMST vendors, ITMMST items, POHDR / PODTL purchase orders, PORCV PO receipts, SCLDGR store-credit ledger |
| OMS | Order management | ORD_HDR orders, ORD_LN order lines, SHPMT shipments |
| POS | Point of sale | TXN_HDR transactions, TXN_LN transaction lines |
| WMS | Warehouse management | INV_SNP overnight stock snapshots, REPL_SCHED next delivery per location |
| LOY | Basecamp Rewards loyalty | MBR members, PTS_TXN points movements, EML_EVT programme email events |
| BIL | Subscription billing | SUB subscriptions |

## Codes

| Column | Values |
|---|---|
| ERP.CUSMST.CUSTYP | R retail, E employee, I internal or test |
| ERP.CUSMST.STSCD | A / I / X: ERP account status (open, inactive, closed) |
| ERP.LOCMST.LOCTYP | S store, D distribution centre, W web |
| ERP.POHDR.POSTAT | O open, R received, X cancelled |
| ERP.SCLDGR.TXNTYP | ISS issued, RDM redeemed, EXP expired, ADJ adjustment |
| OMS.ORD_HDR.CHNL_CD | WEB, CNC click-and-collect, PHN phone |
| OMS.ORD_HDR.ORD_STAT | OPN open, CMP complete, CNL cancelled |
| POS.TXN_HDR.TXN_TYP | S sale, R return, V void |
| LOY.MBR.CARD_STAT | ACT, LST lost, CLS closed |
| LOY.PTS_TXN.TXN_CD | EARN, RDM redeem, EXP expiry, ADJ adjustment |
| LOY.EML_EVT.EVT_TYP | SND sent, OPN opened, CLK clicked, BNC bounced, UNS unsubscribed |
| BIL.SUB.STAT | A active, P paused, C cancelled |

## Designed traps

Each trap is something a careless mapping would get wrong. `eval/answer_key.yaml` says which terms
each one affects.

**Key format mismatches.** OMS stores customers as `CUST_REF = 'C00101234'` (or `'GUEST'`); POS and
ERP use the number `101234`. POS stores are numbered `12`; ERP and WMS call the same store `'S012'`.
Loyalty members link to customers by `LOY.MBR.CARD_NO = ERP.CUSMST.LOYNO`, not by `MBR_ID`, and 300
members have no customer record at all.

**Plausible but wrong columns.** `ERP.CUSMST.STSCD` is account status, not customer activity.
`ERP.CUSMST.LSTPURDT` looks like last purchase date, but the batch that maintained it stopped
180 days before the load date and only ever read POS. `LOY.MBR.CARD_STAT = 'ACT'` is precisely what
Loyalty said engagement is not. `OMS.SHPMT.EST_DLV_DT` is a carrier estimate, not the customer
promise. `ERP.POHDR.EXPRCVDT` is a planner's expected receipt date, not the vendor cutoff.

**Competing dates.** On-time delivery can be measured against order, ship, estimated, promised or
delivered dates in OMS, and against agreed-ship, actual-ship, expected-receipt or received dates in
ERP purchasing. Two SMEs picked different ones, deliberately.

**Fan-out.** Orders split into multiple shipments; POs receive in more than one delivery; the
header-level `SHP_FEE` double counts when joined to lines or shipments.

**No stored balances.** Store-credit balance exists only as `SUM(TXNAMT)` over the ledger, and a few
balances go negative.

**Sign conventions.** POS returns store quantities and amounts as positive numbers; the transaction
type carries the meaning.

**Ambiguity only an SME can settle.** Whether employees are internal accounts; whether a paused
subscription is open; whether a click counts as an open; what window measures a SKU's sales rate.
These are recorded as open questions in the answer key, because the right behaviour is to ask, not
to guess.

## Data volumes and determinism

Roughly 5,000 customers, 20,000 orders, 150,000 POS transactions, 3,000 purchase orders, 3,000
loyalty members and 350,000 stock snapshot rows, loaded in a few minutes on an XSMALL warehouse.
Every generated value is a function of a hash of its key, so two loads on the same day are
identical. Dates are relative to the load date, so recency-based definitions stay meaningful
whenever the estate is rebuilt.
