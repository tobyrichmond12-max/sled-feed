# Mississippi DFA — Schema-Drift Contract (input for Phase 4 self-healing)

Source: `POST https://www.ms.gov/dfa/contract_bid_search/Bid/BidData?AppId=1`
(session cookie `mssp` set by GETting `/Bid`; DataTables 1.9 server-side params).
Records live in JSON `aaData[]`. Verified against the live site on 2026-06-28
(10/10 hand-verified).

The monitor splits fields into LOAD-BEARING (ESCALATE on breakage) vs INCIDENTAL
(LOG only). "Breakage" = field missing on a high fraction of records, became null
where it was populated, changed type/shape, or (for enums/dates) stopped parsing.

## Structural invariants (ESCALATE on any failure)
- `/Bid` returns 200 and sets a session cookie WITHOUT a login wall.
- `BidData` returns 200 JSON with an `aaData` array and integer `iTotalRecords`.
- `aaData` non-empty for Status=Open (≥1 record; today 130).
- Response stays PII-safe: served fields never contain contact-shaped values
  (the mapper hard-fails otherwise — that failure must ESCALATE, not be swallowed).

## LOAD-BEARING fields (ESCALATE)
| served field      | raw source field(s)                         | invariant |
|-------------------|---------------------------------------------|-----------|
| solicitation_id   | `BidNumber`                                 | present, unique-ish, non-null |
| title             | `BidDescription`                            | present, non-empty |
| agency            | `Agency` (empty ⇒ "Statewide")              | present (may be "") |
| category          | `ProcurementCategoryDescription`            | present |
| posted_date       | `AdvertiseDate` + `AdvertiseTime`           | parses as `/Date(ms)/` (+HH:MM:SS) |
| **due_date**      | `SubmissionDate` + `SubmissionTime`         | parses; epoch = midnight America/Chicago; time from SubmissionTime; **highest stakes** |
| status            | `BidStatus`                                 | ∈ {Open, Closed, Awarded, Archived} |
| document_links    | `PDFUrl` + `Attachments[].Url`              | list; URLs on SRM.MAGIC.MS.GOV/DOCSERVER resolve 200 to a real file |

Date rule (do not regress): SubmissionDate `/Date(ms)/` decodes to **midnight
America/Chicago** of the due day; the closing time is the SEPARATE `SubmissionTime`
("HH:MM:SS", Central, incl. "00:00:00" ⇒ shown as 12:00 AM). Store ISO-8601 with
explicit Central offset (CDT −05:00 / CST −06:00 via zoneinfo). A due date off by a
tz or missing its closing hour is the one unacceptable error.

Status enum is CLOSED: {Open, Closed, Awarded, Archived}. Any new string ⇒ LOG +
ESCALATE (served as `UNKNOWN:<value>`, never silently passed).

## INCIDENTAL fields (LOG only)
`sub_category` (SubProcurementCategoryDescription), `bid_type` (BidType),
`estimated_value` (`AwardAmount` — **NOT populated by the grid even for Awarded
records**, so ~always null; treat as best-effort), `OpeningDate`/`OpeningTime`,
`FundingSource`, `Items`, `Vendor`/`VendorNumber`, `VerNumber`, `ObjectID`,
agency address parts.

## Dropped at the PII boundary (must STAY dropped — ESCALATE if they reach output)
`BuyerName`, `BuyerEmail`, `BuyerPhone`, `BuyerFax`, `AgencyContact`,
`AdditionalInfo` (free-text carrying officer name/email/phone).

## Known external caveats (LOG, do not escalate)
- Document host `SRM.MAGIC.MS.GOV` serves a valid GlobalSign-issued cert
  (`*.magic.ms.gov`, O=Mississippi DITS) but OMITS its intermediate — strict TLS
  verification fails; browsers/curl-with-chain succeed. Fetch tolerant of this.
- The grid `BidData?AppId=1` returns Open only; other statuses need `&Status=`.
- New input field appearing in `aaData` ⇒ LOG (possible upstream schema change).
