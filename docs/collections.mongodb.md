# CBC Estimating & Pricing Copilot — MongoDB Database Schema

**Source of truth:** `CBC_Req_Validation_v1_3.xlsx` (Construction Building Components, a division of The Hamilton Parker Company · prepared by Dash Technologies · v1.3, 14 Jul 2026)
**Schema version:** 1.0
**Status:** Design-complete, pending the four still-open workbook items (see §6.3)

---

## 1. Overview

CBC is Hamilton Parker's national-accounts division. It quotes and supplies commercial building components — doors and frames, door hardware, Division 10 specialties, and FRP wall panels — to general contractors, franchisees, and architects, with heavy concentration in retail and quick-serve restaurant chains. Estimating today is a manual pipeline: a bid set arrives as one or more PDFs, an estimator reads the specs and drawings to identify Division 08 and Division 10 scope, performs take-offs by hand, prices each line from Prophet 21 purchase history or from a vendor list price times a negotiated multiplier, applies a product-type margin as a divisor, and exports a customer-facing PDF proposal.

This database backs the **estimating-and-pricing copilot**: the system that ingests the bid set, extracts the opening schedule, matches openings to a structured reference library, sources cost, computes the quote, and presents a draft for estimator review. The database's role is threefold — (1) hold the **reference library** (catalog items, hardware sets, vendor tiers, price books, margin rules) that the copilot prices against; (2) hold the **operational record** of every bid request, extraction, take-off, estimate version, and proposal; and (3) hold enough **immutable audit evidence** that any line on any sent quote can be reconstructed back to the source drawing page and the exact price sheet, tier, and margin in force at the moment it was priced (NFR-3).

The guiding constraint from the workbook governs the whole design: *the estimator stays in control of every quote — the copilot drafts, sources, and calculates; it does not send.* Nothing in this schema permits an approved-and-sent state that was not written by a human user.

### Collections

**Foundation & parties**
- [3.1 `organizations`](#31-organizations)
- [3.2 `users`](#32-users)
- [3.3 `customers`](#33-customers)
- [3.4 `brandPrograms`](#34-brandprograms)
- [3.5 `taxRules`](#35-taxrules)
- [3.6 `commercialTermsTemplates`](#36-commercialtermstemplates)

**Product & catalog**
- [3.7 `productTypes`](#37-producttypes)
- [3.8 `vendors`](#38-vendors)
- [3.9 `catalogItems`](#39-catalogitems)
- [3.10 `hardwareSets`](#310-hardwaresets)
- [3.11 `adders`](#311-adders)
- [3.12 `lightKitRates`](#312-lightkitrates)

**Pricing**
- [3.13 `priceBooks`](#313-pricebooks)
- [3.14 `priceBookEntries`](#314-pricebookentries)
- [3.15 `vendorTiers`](#315-vendortiers)
- [3.16 `marginRules`](#316-marginrules)
- [3.17 `p21ItemMappings`](#317-p21itemmappings)

**Opening reference data**
- [3.18 `frameDepths`](#318-framedepths)
- [3.19 `finishCodes`](#319-finishcodes)
- [3.20 `frpConstants`](#320-frpconstants)

**Operational**
- [3.21 `bidRequests`](#321-bidrequests)
- [3.22 `documents`](#322-documents)
- [3.23 `openings`](#323-openings)
- [3.24 `takeoffs`](#324-takeoffs)
- [3.25 `estimates`](#325-estimates)
- [3.26 `estimateVersions`](#326-estimateversions)
- [3.27 `estimateLines`](#327-estimatelines)
- [3.28 `vendorRfqs`](#328-vendorrfqs)
- [3.29 `rfis`](#329-rfis)
- [3.30 `proposals`](#330-proposals)
- [3.31 `feedbackEvents`](#331-feedbackevents)
- [3.32 `auditLogs`](#332-auditlogs)

**32 collections.** Eight entities from the Phase 1 map are deliberately embedded rather than given their own collection; each is justified in §2.3.

**Infrastructure (implemented, not in the workbook):** [`documentPages`](#documentpages-implemented) — one Mongo document per MinerU-parsed PDF page (blocks + bbox). See also `jobs`, `settings` and `pageIndex`, and [`backend/modules.md`](backend/modules.md) for which module owns each one.

---

## 2. Entity Relationship Summary

### 2.1 Reference map

Every collection carries `orgId` → `organizations._id` (Q2). That edge is omitted from the table below to avoid repeating it 31 times.

| Child collection | Field | → Parent collection | Cardinality | Notes |
|---|---|---|---|---|
| `users` | `orgId` | `organizations` | N:1 | Five named individuals across five roles |
| `customers` | `brandProgramId` | `brandPrograms` | N:1 (optional) | A GC may work under a brand standard, or none |
| `customers` | `taxRuleId` | `taxRules` | N:1 (derived from ship-to state) | Resolved at quote time, not stored on the customer |
| `catalogItems` | `vendorId` | `vendors` | N:1 | |
| `catalogItems` | `productTypeId` | `productTypes` | N:1 | Drives the default margin band |
| `catalogItems` | `defaultFinishCode` | `finishCodes` | N:1 (optional) | By `code`, not ObjectId — see §3.9 |
| `hardwareSets` | `items[].catalogItemId` | `catalogItems` | 1:N embedded | Set composition is bounded (~9–15 components) |
| `hardwareSets` | `vendorId` | `vendors` | N:1 (optional) | Brand-program sets (Hager-led) |
| `adders` | `vendorId` | `vendors` | N:1 | |
| `adders` | `appliesToProductTypeIds[]` | `productTypes` | N:N | |
| `lightKitRates` | `vendorId` | `vendors` | N:1 | NGP / PEMKO-Markar / Rockwood |
| `priceBooks` | `vendorId` | `vendors` | N:1 | Dated memo, protection window |
| `priceBookEntries` | `priceBookId` | `priceBooks` | N:1 | Unbounded — separate collection |
| `priceBookEntries` | `catalogItemId` | `catalogItems` | N:1 (optional) | Null until reconciled to the library |
| `vendorTiers` | `vendorId` | `vendors` | N:1 | Account-level attribute, not per-item |
| `marginRules` | `productTypeId` | `productTypes` | N:1 | |
| `marginRules` | `customerId` / `brandProgramId` | `customers` / `brandPrograms` | N:1 (optional) | Override scope (Q11) |
| `p21ItemMappings` | `catalogItemId` | `catalogItems` | N:1 (optional) | Null = unmatched P21 item |
| `bidRequests` | `customerId` | `customers` | N:1 | |
| `bidRequests` | `brandProgramId` | `brandPrograms` | N:1 (optional) | |
| `bidRequests` | `initiatorUserId` | `users` | N:1 | The sales person in the queue |
| `bidRequests` | `assignedEstimatorId` | `users` | N:1 | |
| `documents` | `bidRequestId` | `bidRequests` | N:1 | One combined PDF or many |
| `documents` | `supersedesDocumentId` | `documents` | N:1 (optional) | Addendum chain |
| `openings` | `bidRequestId` | `bidRequests` | N:1 | 10–40 typical, unbounded |
| `openings` | `sourceRef.documentId` | `documents` | N:1 | Audit trail to page |
| `openings` | `hardwareSetId` | `hardwareSets` | N:1 (optional) | Matched CBC library set |
| `takeoffs` | `bidRequestId` | `bidRequests` | N:1 | |
| `takeoffs` | `openingId` | `openings` | N:1 (optional) | Null for area-based FRP take-offs |
| `estimates` | `bidRequestId` | `bidRequests` | 1:1 | |
| `estimates` | `currentVersionId` | `estimateVersions` | 1:1 | Denormalized pointer |
| `estimateVersions` | `estimateId` | `estimates` | N:1 | Immutable chain |
| `estimateVersions` | `supersededByVersionId` | `estimateVersions` | 1:1 (optional) | Self-reference |
| `estimateVersions` | `triggeringAddendumDocumentId` | `documents` | N:1 (optional) | |
| `estimateLines` | `estimateVersionId` | `estimateVersions` | N:1 | Referenced, not embedded (Q15) |
| `estimateLines` | `lineGroupId` | `estimateVersions.lineGroups[]._id` | N:1 | Embedded-subdoc reference |
| `estimateLines` | `alternateId` | `estimateVersions.alternates[]._id` | N:1 (nullable = base bid) | |
| `estimateLines` | `openingId` | `openings` | N:1 (optional) | Null for accessories/freight |
| `estimateLines` | `catalogItemId` | `catalogItems` | N:1 (optional) | Null for custom/manual lines |
| `estimateLines` | `vendorRfqId` | `vendorRfqs` | N:1 (optional) | |
| `vendorRfqs` | `bidRequestId` | `bidRequests` | N:1 | |
| `vendorRfqs` | `vendorId` | `vendors` | N:1 | |
| `rfis` | `bidRequestId` | `bidRequests` | N:1 | |
| `proposals` | `estimateVersionId` | `estimateVersions` | 1:1 | |
| `proposals` | `sentToUserId` | `users` | N:1 | The initiator, never a group alias |
| `feedbackEvents` | `estimateLineId` | `estimateLines` | N:1 | |
| `auditLogs` | `entityId` | *(polymorphic)* | N:1 | `entityType` discriminator |

### 2.2 The spine, in flow order

```
organizations
    └── users ──────────────────────────────┐
    └── customers ── brandPrograms          │
            │                               │
            ▼                               │
      bidRequests ◄── initiatorUserId ──────┘
            │
            ├── documents (bid set PDFs, specs, drawings, addenda)
            │       └── pages[] { pageNumber, sheetLabel, ocrStatus }
            │
            ├── openings ──── sourceRef → documents.pages[]
            │       └── matchCandidates[] → catalogItems / hardwareSets
            │
            ├── takeoffs (FRP perimeter/corners, counts)
            │
            ├── vendorRfqs ─────────────┐
            ├── rfis                    │
            │                           │
            └── estimates               │
                    └── estimateVersions (immutable chain, v1 → v2 → v3)
                            ├── alternates[]  { _id, number, label }
                            ├── lineGroups[]  { _id, groupType, openingId, alternateId }
                            │
                            └── estimateLines ◄──────┘
                                    ├── costSnapshot        (frozen)
                                    ├── priceBookSnapshot   (frozen)
                                    ├── multiplierTierSnapshot (frozen)
                                    ├── marginSnapshot      (frozen)
                                    ├── matchResult { confidence, ratingConflict }
                                    ├── sourcingNote / substitutionNote
                                    └── feedbackEvents

  Reference library priced against:
    productTypes ── marginRules
    vendors ── vendorTiers ── priceBooks ── priceBookEntries
           └── catalogItems ── hardwareSets.items[]
           └── adders / lightKitRates
    p21ItemMappings (cached, read-only mirror)
    frameDepths / finishCodes / frpConstants / taxRules
```

### 2.3 Entities intentionally embedded (no standalone collection)

| Entity (Phase 1 #) | Embedded into | Justification |
|---|---|---|
| Hardware Set Item (#15) | `hardwareSets.items[]` | Bounded (~9–15 components per set per Matrix 7.2), always read with the parent set, never queried independently of it. Classic embed. |
| Document Page (#8) | `documents.pages[]` | Bounded by page count; always loaded with the document; needed only as a citation target for `openings.sourceRef` and line audit (NFR-3). A 400-page set at ~120 bytes/page entry is ~48 KB — far inside the 16 MB limit. |
| Line Group (#32) | `estimateVersions.lineGroups[]` | Bounded (one per door + one accessories block + one freight line); has no lifecycle independent of its version; `estimateLines` reference it by subdocument `_id`. |
| Bid Alternate (#30) | `estimateVersions.alternates[]` | Typically 1–5 per bid; defined at version scope; a dimension on line groups, not an entity with its own workflow (Q6). |
| Match Result / Candidates (#34) | `estimateLines.matchResult` and `openings.matchCandidates[]` | Bounded to the top N candidates surfaced for review ("here are 3 close matches"); meaningless outside the parent. |
| Substitution / Direct-Equal Note (#35) | `estimateLines.substitutionNote` | One optional note per line; 1:1 with parent. |
| Sourcing Note (#36) | `estimateLines.sourcingNote` | 1:1 with parent (Matrix 6.5). |
| Keying Option (#41) | `estimateLines.options.keying` | Matrix 7.6 confirmed: keying lives inside lock options, there is no separate keying-schedule workflow, so there is no entity to give a collection to. |
| Cost Record (#26) | `estimateLines.costSnapshot` + `p21ItemMappings` | The *lookup source* is a collection (`p21ItemMappings`); the *cost as quoted* is a frozen snapshot on the line per Q7. A third "costRecords" collection would duplicate both. |

Entities from the Phase 1 map with **no representation at all**, and why: door-size notation (#43 — a parser rule, not data; encoded as `openings.sizeCode` plus derived width/height); margin governance and approval routing (Matrix 6.7, FR-15, NFR-8, NFR-9, Open Item 14 — all confirmed *Out of scope (future)* by the 14 Jul estimator session); business-case metrics (the sheet does not exist in the workbook — see Q3 in §6.1).

---

## 3. Collections

**Reading the validators.** Every collection carries the standard envelope defined in §4.2. To keep the validator blocks copy-paste-runnable in `mongosh` without repeating fifteen lines thirty-two times, run this once in your shell session first — every subsequent `db.createCollection` block spreads it in:

```javascript
// Run once per mongosh session before the createCollection blocks below.
const envelope = {
  orgId:         { bsonType: "objectId",  description: "Tenant scope — organizations._id (Q2)" },
  schemaVersion: { bsonType: "int",       description: "Document schema version (§4.4)" },
  createdAt:     { bsonType: "date" },
  updatedAt:     { bsonType: "date" },
  createdBy:     { bsonType: ["objectId", "null"], description: "users._id; null for system/import writes" },
  updatedBy:     { bsonType: ["objectId", "null"] }
};
const envelopeRequired = ["orgId", "schemaVersion", "createdAt", "updatedAt"];

// Soft-delete block — only on the five collections named in Q13 (§4.3).
const softDelete = {
  isDeleted:       { bsonType: "bool" },
  deletedAt:       { bsonType: ["date", "null"] },
  deletedBy:       { bsonType: ["objectId", "null"] },
  retentionPolicy: { bsonType: ["string", "null"], description: "e.g. '7-year'; intentionally unset (Q13)" }
};

// Reusable status-history shape (§4.5).
const statusHistory = {
  bsonType: "array",
  items: {
    bsonType: "object",
    required: ["to", "at"],
    properties: {
      from: { bsonType: ["string", "null"] },
      to:   { bsonType: "string" },
      at:   { bsonType: "date" },
      by:   { bsonType: ["objectId", "null"] },
      note: { bsonType: ["string", "null"] }
    }
  }
};
```

In the **Source** column of every field table: a value like `Matrix 6.1 (D18)` is a workbook cell reference; `Q7` means the field originates from the Phase 1 decision round rather than a workbook cell; `§4.x` means it is a cross-cutting convention.

---

### 3.1 `organizations`

**Purpose:** Tenant root. CBC is the only tenant today; the workbook states the approach may extend to other Hamilton Parker divisions later (Matrix 2.0, I4).

**`_id` strategy:** `ObjectId`. No stable natural key exists in the workbook.

| Field | Type | Required | Default | Description | Source |
|---|---|---|---|---|---|
| `_id` | objectId | yes | auto | | — |
| `code` | string | yes | — | Short tenant key, e.g. `CBC` | Q2 |
| `name` | string | yes | — | `Construction Building Components` | Matrix 2.0 (D4) |
| `parentCompany` | string | no | null | `The Hamilton Parker Company` | Matrix 2.0 (D4) |
| `address` | object | no | null | `{ street, city, state, postalCode }` — 1865 Leonard Ave, Columbus OH | Matrix 2.0 (D4) |
| `divisionScope` | string | no | null | Free text; `national-accounts estimating only` | Matrix 2.0 (I4) |
| `active` | bool | yes | `true` | | Q2 |
| *envelope* | — | — | — | `orgId` on this collection equals `_id` (self-referential; kept for index uniformity) | §4.2 |

**Relationships:** parent of every other collection via `orgId` (1:N).

**Indexes:**
- `{ code: 1 }` — **unique**. Serves tenant resolution at login/bootstrap.

```javascript
db.createCollection("organizations", {
  validator: { $jsonSchema: {
    bsonType: "object",
    required: [...envelopeRequired, "code", "name", "active"],
    properties: {
      ...envelope,
      _id: { bsonType: "objectId" },
      code: { bsonType: "string", maxLength: 16 },
      name: { bsonType: "string" },
      parentCompany: { bsonType: ["string", "null"] },
      address: { bsonType: ["object", "null"], properties: {
        street: { bsonType: "string" }, city: { bsonType: "string" },
        state: { bsonType: "string" }, postalCode: { bsonType: "string" } } },
      divisionScope: { bsonType: ["string", "null"] },
      active: { bsonType: "bool" }
    }
  } }
});
db.organizations.createIndex({ code: 1 }, { unique: true });
```

**Notes:** Only one document is expected in production for the foreseeable future. Its existence is a deliberate cost paid now to avoid a full-database migration if the tile, masonry, fireplace, or garage-door divisions are onboarded later (Matrix 2.0 I4: *"approach can extend to them later"*).

---

### 3.2 `users`

**Purpose:** Estimators, sales initiators, and the owners named against guardrails and dependencies. Drives who may approve and send (NFR-1) and who receives the exported proposal (FR-10).

**`_id` strategy:** `ObjectId`. Email is unique but is not a durable identity key.

| Field | Type | Required | Default | Description | Source |
|---|---|---|---|---|---|
| `_id` | objectId | yes | auto | | — |
| `name` | string | yes | — | e.g. `Kevin`, `Rick`, `Shanna`, `Kellan`, `Matt`, `Rebecca`, `Tina` | Matrix 8.1 (I36), FR-10 (I47) |
| `email` | string | yes | — | Format-validated; Outlook is the intake and delivery channel | Flow D4, D12 |
| `role` | string (enum) | yes | — | `estimator` \| `salesInitiator` \| `purchasing` \| `leadership` \| `it` | Q10; owners named in Matrix I55–I65, Assumptions D4:D8 |
| `seniority` | string (enum) | no | `null` | `senior` \| `junior` — NFR-7 distinguishes the two for usability | NFR-7 (D61) |
| `externalIdpSubject` | string | no | null | Future SSO hook; unused in v1 | Q10 |
| `active` | bool | yes | `true` | | Q10 |
| `canApproveSend` | bool | yes | `false` | Human-in-the-loop gate (NFR-1). `true` for `estimator` by default | NFR-1 (D55) |
| *envelope* | — | — | — | | §4.2 |

**Relationships:** referenced by `bidRequests.initiatorUserId` and `.assignedEstimatorId`, `proposals.sentToUserId` and `.approvedBy`, `estimateVersions.approvedBy`, `feedbackEvents.userId`, `auditLogs.userId`, and every `createdBy`/`updatedBy` (all N:1).

**Indexes:**
- `{ orgId: 1, email: 1 }` — **unique**. Login and initiator resolution from an inbound email address (Flow Phase 0).
- `{ orgId: 1, role: 1, active: 1 }` — serves "list active estimators for assignment" and "list sales initiators for the send-back picker" (FR-10, I47).

```javascript
db.createCollection("users", {
  validator: { $jsonSchema: {
    bsonType: "object",
    required: [...envelopeRequired, "name", "email", "role", "active", "canApproveSend"],
    properties: {
      ...envelope,
      _id: { bsonType: "objectId" },
      name: { bsonType: "string" },
      email: { bsonType: "string", pattern: "^[^@\\s]+@[^@\\s]+\\.[^@\\s]+$" },
      role: { enum: ["estimator", "salesInitiator", "purchasing", "leadership", "it"] },
      seniority: { enum: ["senior", "junior", null] },
      externalIdpSubject: { bsonType: ["string", "null"] },
      active: { bsonType: "bool" },
      canApproveSend: { bsonType: "bool" }
    }
  } }
});
db.users.createIndex({ orgId: 1, email: 1 }, { unique: true });
db.users.createIndex({ orgId: 1, role: 1, active: 1 });
```

**Notes:** `canApproveSend` is the schema-level expression of NFR-1. It is stored on the user rather than inferred from `role` so that the future approval-authority work (NFR-9, deferred) has a field to build on without a migration. No password/credential fields — authentication is an application concern and no credential material belongs in this database.

---

### 3.3 `customers`

**Purpose:** The paying party — a GC, franchisee, or the internal initiator. Matrix 2.4 (I8) is explicit: *CBC sells to the GC / internal initiator, not the architect.*

**`_id` strategy:** `ObjectId`.

| Field | Type | Required | Default | Description | Source |
|---|---|---|---|---|---|
| `_id` | objectId | yes | auto | | — |
| `name` | string | yes | — | | Matrix 2.0 (D4) |
| `customerType` | string (enum) | yes | — | `generalContractor` \| `franchisee` \| `architect` \| `internal` — architect retained as a contact type, never a bill-to | Matrix 2.0 (D4), 2.4 (I8) |
| `brandProgramId` | objectId | no | null | → `brandPrograms` | Q11 |
| `shipToState` | string | no | null | 2-letter US state or `CA-<prov>`; drives tax resolution | Matrix 2.4 (I8) |
| `country` | string (enum) | yes | `US` | `US` \| `CA` | Matrix 2.4 (I8) |
| `marginOverride` | object | no | null | `{ productTypeId, marginRate, reason, effectiveFrom, effectiveTo }[]` — customer-level override | Q11; Open NR-9 |
| `defaultInitiatorUserId` | objectId | no | null | → `users`; usual sales owner | FR-10 (I47) |
| `active` | bool | yes | `true` | | §4.2 |
| *envelope* | — | — | — | | §4.2 |

**Relationships:** `brandProgramId` → `brandPrograms` (N:1, optional). Referenced by `bidRequests.customerId` (1:N) and `marginRules.customerId` (1:N).

**Indexes:**
- `{ orgId: 1, name: 1 }` — **unique**. Prevents duplicate accounts on intake.
- `{ orgId: 1, brandProgramId: 1 }` — **partial** (`brandProgramId: { $exists: true, $ne: null }`). Serves "all bids for this brand" reuse lookups (FR-11).
- `{ orgId: 1, shipToState: 1 }` — serves tax-rule resolution at quote time (Matrix 2.4).

```javascript
db.createCollection("customers", {
  validator: { $jsonSchema: {
    bsonType: "object",
    required: [...envelopeRequired, "name", "customerType", "country", "active"],
    properties: {
      ...envelope,
      _id: { bsonType: "objectId" },
      name: { bsonType: "string" },
      customerType: { enum: ["generalContractor", "franchisee", "architect", "internal"] },
      brandProgramId: { bsonType: ["objectId", "null"] },
      shipToState: { bsonType: ["string", "null"] },
      country: { enum: ["US", "CA"] },
      defaultInitiatorUserId: { bsonType: ["objectId", "null"] },
      active: { bsonType: "bool" },
      marginOverride: { bsonType: ["array", "null"], items: {
        bsonType: "object",
        required: ["marginRate", "reason"],
        properties: {
          productTypeId: { bsonType: ["objectId", "null"] },
          marginRate: { bsonType: "double", minimum: 0, exclusiveMaximum: 1 },
          reason: { bsonType: "string" },
          effectiveFrom: { bsonType: ["date", "null"] },
          effectiveTo: { bsonType: ["date", "null"] }
        } } }
    }
  } }
});
db.customers.createIndex({ orgId: 1, name: 1 }, { unique: true });
db.customers.createIndex({ orgId: 1, brandProgramId: 1 },
  { partialFilterExpression: { brandProgramId: { $exists: true, $type: "objectId" } } });
db.customers.createIndex({ orgId: 1, shipToState: 1 });
```

**Notes:** `marginOverride` is embedded rather than referenced because it is bounded (a handful of product-type carve-outs per account) and always read with the customer during margin resolution. `marginRate` is stored as the **margin**, never as the divisor — the divisor is derived (`1 - marginRate`) so a single number can never drift out of sync with its own reciprocal. See §4.7.

---

### 3.4 `brandPrograms`

**Purpose:** The chain brand whose standard governs the spec — McDonald's, Cava, Wendy's, Dutch Bros and similar. Distinct from who pays (Q11). Drives templated-mode reuse (Matrix 3.0, FR-11) and brand-level margin carve-outs (Open NR-9).

**`_id` strategy:** `ObjectId`.

| Field | Type | Required | Default | Description | Source |
|---|---|---|---|---|---|
| `_id` | objectId | yes | auto | | — |
| `name` | string | yes | — | e.g. `Wendy's`, `McDonald's`, `Cava` | Matrix 3.0 (I10), 6.1 (I18) |
| `segment` | string (enum) | no | null | `quickServe` \| `fastCasual` \| `retail` \| `other` | Matrix 2.0 (D4) |
| `preferredMode` | string (enum) | no | null | `templated` \| `oneOff` — McDonald's and Cava are named one-off exceptions | Matrix 3.0 (I10), Open 8 (E11) |
| `standardHardwareSetIds` | array<objectId> | no | `[]` | → `hardwareSets`; the brand's usual sets | FR-3 (C40) |
| `marginOverride` | array<object> | no | `[]` | Same shape as `customers.marginOverride`; Wendy's special margin | Matrix 6.1 (I18); Open NR-9 |
| `active` | bool | yes | `true` | | §4.2 |
| *envelope* | — | — | — | | §4.2 |

**Relationships:** referenced by `customers.brandProgramId`, `bidRequests.brandProgramId`, `marginRules.brandProgramId` (all 1:N).

**Indexes:**
- `{ orgId: 1, name: 1 }` — **unique**.
- `{ orgId: 1, active: 1 }` — picker population.

```javascript
db.createCollection("brandPrograms", {
  validator: { $jsonSchema: {
    bsonType: "object",
    required: [...envelopeRequired, "name", "active"],
    properties: {
      ...envelope,
      _id: { bsonType: "objectId" },
      name: { bsonType: "string" },
      segment: { enum: ["quickServe", "fastCasual", "retail", "other", null] },
      preferredMode: { enum: ["templated", "oneOff", null] },
      standardHardwareSetIds: { bsonType: "array", items: { bsonType: "objectId" } },
      marginOverride: { bsonType: "array", items: {
        bsonType: "object",
        required: ["marginRate", "reason"],
        properties: {
          productTypeId: { bsonType: ["objectId", "null"] },
          marginRate: { bsonType: "double", minimum: 0, exclusiveMaximum: 1 },
          reason: { bsonType: "string" },
          effectiveFrom: { bsonType: ["date", "null"] },
          effectiveTo: { bsonType: ["date", "null"] }
        } } },
      active: { bsonType: "bool" }
    }
  } }
});
db.brandPrograms.createIndex({ orgId: 1, name: 1 }, { unique: true });
db.brandPrograms.createIndex({ orgId: 1, active: 1 });
```

**Notes:** `preferredMode` exists because the workbook records mode as a *per-brand* fact, not only a per-estimator habit: Matrix 3.0 (I10) records Kevin building one-off *"exceptions McDonald's, Cava"*. Storing it here lets the copilot pre-select the right starting mode on intake.

---

### 3.5 `taxRules`

**Purpose:** Sales-tax handling on the quote. Matrix 2.4 (I8) is unusually precise: tax is charged **only** for Ohio (~8%) and Kentucky (6.5%, border nexus); the other 48 states and Canada carry none because the sale is to a GC or corporation, not an end customer.

**`_id` strategy:** `ObjectId`, with a unique business key on `{ orgId, country, state, effectiveFrom }`.

| Field | Type | Required | Default | Description | Source |
|---|---|---|---|---|---|
| `_id` | objectId | yes | auto | | — |
| `country` | string (enum) | yes | — | `US` \| `CA` | Matrix 2.4 (I8) |
| `state` | string | no | null | `OH`, `KY`; null = country-wide default | Matrix 2.4 (I8) |
| `taxable` | bool | yes | — | `false` for everything outside OH/KY | Matrix 2.4 (I8) |
| `rate` | double | yes | `0` | Decimal rate: `0.08` (OH), `0.065` (KY) | Matrix 2.4 (I8) |
| `basis` | string (enum) | yes | `material` | `material` — supply-only; no installed labor exists to tax | Matrix 2.4 (D8, I8) |
| `nexusReason` | string | no | null | e.g. `border-nexus` for KY | Matrix 2.4 (I8) |
| `effectiveFrom` | date | yes | — | | §4.6 |
| `effectiveTo` | date | no | null | Null = currently in force | §4.6 |
| *envelope* | — | — | — | | §4.2 |

**Relationships:** resolved at quote time from `customers.shipToState` / `.country`; the resolved rule is frozen onto `estimateVersions.taxSnapshot` (§3.26).

**Indexes:**
- `{ orgId: 1, country: 1, state: 1, effectiveFrom: -1 }` — serves "current rule for this ship-to" (most recent effective rule wins).
- `{ orgId: 1, effectiveTo: 1 }` — **partial** (`effectiveTo: null`) — lists rules currently in force for the admin screen.

```javascript
db.createCollection("taxRules", {
  validator: { $jsonSchema: {
    bsonType: "object",
    required: [...envelopeRequired, "country", "taxable", "rate", "basis", "effectiveFrom"],
    properties: {
      ...envelope,
      _id: { bsonType: "objectId" },
      country: { enum: ["US", "CA"] },
      state: { bsonType: ["string", "null"], maxLength: 8 },
      taxable: { bsonType: "bool" },
      rate: { bsonType: "double", minimum: 0, maximum: 1 },
      basis: { enum: ["material"] },
      nexusReason: { bsonType: ["string", "null"] },
      effectiveFrom: { bsonType: "date" },
      effectiveTo: { bsonType: ["date", "null"] }
    }
  } }
});
db.taxRules.createIndex({ orgId: 1, country: 1, state: 1, effectiveFrom: -1 });
db.taxRules.createIndex({ orgId: 1, effectiveTo: 1 },
  { partialFilterExpression: { effectiveTo: null } });
```

**Notes:** `basis` is a single-value enum today rather than a free string, because Matrix 2.4 confirms supply-only with no installed or turnkey scopes. Keeping it as an enum with one member makes the constraint visible and makes adding `installed` later an explicit, reviewed change rather than a silent data drift. Rates are stored as decimals, never percentages — see §4.7.

---

### 3.6 `commercialTermsTemplates`

**Purpose:** The standard commercial terms carried on every exported proposal — HP PO required, 30-day validity (FR-10 C47, Flow C12).

**`_id` strategy:** `ObjectId`.

| Field | Type | Required | Default | Description | Source |
|---|---|---|---|---|---|
| `_id` | objectId | yes | auto | | — |
| `name` | string | yes | — | e.g. `CBC Standard Supply-Only` | FR-10 (C47) |
| `validityDays` | int | yes | `30` | Quote validity window | FR-10 (C47), Flow C12 |
| `poRequired` | bool | yes | `true` | Hamilton Parker PO required | FR-10 (C47) |
| `supplyOnly` | bool | yes | `true` | No installed labor | Matrix 2.4 (I8) |
| `freightPolicyText` | string | no | null | Freight generally omitted at estimate stage | FR-7 (I44); Open 1 (E4) |
| `bodyMarkdown` | string | yes | — | Full terms block rendered into the PDF | FR-10 (C47) |
| `isDefault` | bool | yes | `false` | Exactly one default per org | §4.6 |
| `effectiveFrom` / `effectiveTo` | date | yes / no | — / null | Versioned so old proposals reproduce | NFR-3 (D57) |
| *envelope* | — | — | — | | §4.2 |

**Relationships:** frozen into `proposals.termsSnapshot` at export (1:N).

**Indexes:**
- `{ orgId: 1, isDefault: 1, effectiveTo: 1 }` — **partial** (`isDefault: true, effectiveTo: null`) — resolves the current default in one hit at export.
- `{ orgId: 1, name: 1, effectiveFrom: -1 }` — **unique**. Version history per named template.

```javascript
db.createCollection("commercialTermsTemplates", {
  validator: { $jsonSchema: {
    bsonType: "object",
    required: [...envelopeRequired, "name", "validityDays", "poRequired",
               "supplyOnly", "bodyMarkdown", "isDefault", "effectiveFrom"],
    properties: {
      ...envelope,
      _id: { bsonType: "objectId" },
      name: { bsonType: "string" },
      validityDays: { bsonType: "int", minimum: 1 },
      poRequired: { bsonType: "bool" },
      supplyOnly: { bsonType: "bool" },
      freightPolicyText: { bsonType: ["string", "null"] },
      bodyMarkdown: { bsonType: "string" },
      isDefault: { bsonType: "bool" },
      effectiveFrom: { bsonType: "date" },
      effectiveTo: { bsonType: ["date", "null"] }
    }
  } }
});
db.commercialTermsTemplates.createIndex({ orgId: 1, isDefault: 1, effectiveTo: 1 },
  { partialFilterExpression: { isDefault: true, effectiveTo: null } });
db.commercialTermsTemplates.createIndex({ orgId: 1, name: 1, effectiveFrom: -1 }, { unique: true });
```

**Notes:** Terms are versioned rather than mutated so a proposal sent 18 months ago still renders under the terms actually offered. The snapshot on `proposals` makes this bulletproof even if a template row is deleted.

---

### 3.7 `productTypes`

**Purpose:** The in-scope product families, and the hook the margin framework hangs on. Matrix 2.1 (I5) confirms scope: metal and wood doors, metal frames (welded/loaded and knock-down), store hardware, Division 10 specialties, FRP wall panels — plus HP-Fabrication doors. Out-of-scope categories are stored here too, flagged `inScope: false`, so the copilot can *recognise and reject* an out-of-scope line rather than silently mis-price it (Open 7, C10: *"bounds the copilot so it doesn't attempt out-of-scope items"*).

**`_id` strategy:** `ObjectId`, unique business key on `{ orgId, code }`.

| Field | Type | Required | Default | Description | Source |
|---|---|---|---|---|---|
| `_id` | objectId | yes | auto | | — |
| `code` | string | yes | — | e.g. `DOOR_HM`, `DOOR_WOOD`, `FRAME_HM_WELDED`, `FRAME_HM_KD`, `HW_LOCK`, `HW_EXIT`, `HW_CLOSER`, `HW_HINGE`, `DIV10_PARTITION`, `DIV10_ACCESSORY`, `DIV10_HANDDRYER`, `FRP_PANEL` | Matrix 2.1 (D5, I5) |
| `name` | string | yes | — | Display label | Matrix 2.1 (D5) |
| `csiDivision` | string (enum) | no | null | `08` \| `10` \| `06` \| `other` | Flow C6 |
| `family` | string (enum) | yes | — | `doorsAndFrames` \| `doorHardware` \| `div10Specialties` \| `frpWallPanels` | Matrix 2.1 (D5) |
| `inScope` | bool | yes | `true` | `false` for ceiling tile & grid, tile, thin brick masonry, related products (JL Industries), aluminum/glass storefront, coiling/overhead/oversized doors, engineered wood, metal siding / extruded aluminum, "not-wood" | Matrix 2.3 (I7); Scope tab E10:E15; Open 7 (E10) |
| `outOfScopeReason` | string | no | null | e.g. `another department / showroom`, `low margin — likely being discontinued` | Matrix 2.3 (I7); Open 7 (E10) |
| `defaultMarginBand` | string (enum) | no | null | `commodity` \| `restroomPartitions` \| `specialty` \| `customFabricated` \| `accessories` | Matrix 6.1 (D18, I18) |
| `ratingSensitive` | bool | yes | `false` | Whether fire rating drives selection/price for this type. **Currently unset for all types — see §6.3 Open Item 9** | Matrix 7.3 (G29); Q5 |
| `handingSensitive` | bool | yes | `false` | `true` for locks, closers, exit devices | Matrix 7.4 (D30) |
| `finishSensitive` | bool | yes | `false` | `true` for most hardware | Matrix 7.5 (D31) |
| `phase1` | bool | yes | `false` | In the Phase 1 automation slice | Matrix 3.1 (I11); Open NR-13 |
| `sortOrder` | int | no | `100` | Proposal grouping order | FR-7 (C44) |
| *envelope* | — | — | — | | §4.2 |

**Relationships:** referenced by `catalogItems.productTypeId`, `marginRules.productTypeId`, `adders.appliesToProductTypeIds[]`, `estimateLines.productTypeId` (all 1:N).

**Indexes:**
- `{ orgId: 1, code: 1 }` — **unique**.
- `{ orgId: 1, inScope: 1, family: 1 }` — serves the scope guard and the item-picker grouping.

```javascript
db.createCollection("productTypes", {
  validator: { $jsonSchema: {
    bsonType: "object",
    required: [...envelopeRequired, "code", "name", "family", "inScope",
               "ratingSensitive", "handingSensitive", "finishSensitive", "phase1"],
    properties: {
      ...envelope,
      _id: { bsonType: "objectId" },
      code: { bsonType: "string", pattern: "^[A-Z0-9_]+$" },
      name: { bsonType: "string" },
      csiDivision: { enum: ["08", "10", "06", "other", null] },
      family: { enum: ["doorsAndFrames", "doorHardware", "div10Specialties", "frpWallPanels"] },
      inScope: { bsonType: "bool" },
      outOfScopeReason: { bsonType: ["string", "null"] },
      defaultMarginBand: { enum: ["commodity", "restroomPartitions", "specialty",
                                  "customFabricated", "accessories", null] },
      ratingSensitive: { bsonType: "bool" },
      handingSensitive: { bsonType: "bool" },
      finishSensitive: { bsonType: "bool" },
      phase1: { bsonType: "bool" },
      sortOrder: { bsonType: "int" }
    }
  } }
});
db.productTypes.createIndex({ orgId: 1, code: 1 }, { unique: true });
db.productTypes.createIndex({ orgId: 1, inScope: 1, family: 1 });
```

**Notes:** `defaultMarginBand` is a *pointer to a band name*, not a rate. The rate lives in `marginRules` with effective dating, because Matrix 6.1 records the framework as stable for ~14 years but explicitly overridable — a rate embedded here would have to be updated in two places. The three `*Sensitive` booleans are what let FR-4's matcher know which attributes are hard constraints for a given product type instead of hard-coding that logic in application code.

---

### 3.8 `vendors`

**Purpose:** Manufacturers and distributors. The workbook draws a sharp, price-affecting line between the two: Allegion product is *bought through* Banner Solutions or SecLock, laminate through Pionite/Wilsonart, some accessories through J2 — and every distributor-bought line requires **manual price entry** (Matrix 2.2 I6, 6.5 I22, Open NR-2).

**`_id` strategy:** `ObjectId`, unique business key on `{ orgId, name }`.

| Field | Type | Required | Default | Description | Source |
|---|---|---|---|---|---|
| `_id` | objectId | yes | auto | | — |
| `name` | string | yes | — | `Hager`, `Allegion`, `National Guard`, `Rockwood`, `PEMKO`, `Bobrick`, `Bradley`, `ASI`, `Gamco`, `World Dryer`, `Dyson`, `Excel XLERATOR`, `Marlite`, `NUDO`, `Five Lakes`, `Pioneer`, `Masonite Architectural`, `Special-Lite`, `HP Fabrication`, `Cal-Royal`, `Alarm Lock` | Matrix 2.2 (D6, I6); Scope tab C4:D9 |
| `vendorType` | string (enum) | yes | — | `manufacturer` \| `distributor` \| `fabricator` | Matrix 6.5 (I22) |
| `subBrands` | array<string> | no | `[]` | Allegion → `Von Duprin`, `LCN`, `Schlage`, `Ives` | Matrix 2.2 (D6) |
| `purchasePath` | string (enum) | yes | `direct` | `direct` \| `viaDistributor` \| `manualOnly` | Matrix 6.2 (I19), 6.5 (I22) |
| `distributorIds` | array<objectId> | no | `[]` | → `vendors` (self-ref) — Banner Solutions, SecLock, J2, Pionite, Wilsonart | Matrix 2.2 (I6), 6.5 (I22) |
| `requiresManualPrice` | bool | yes | `false` | `true` for every distributor-bought line; drives the "price may be out of date — refresh" prompt | Open NR-2; FR-16 (I53) |
| `isTop10` | bool | yes | `false` | Phase 1 automation set; ~90%+ of quotes | Matrix 6.3 (I20) |
| `volumeShareNote` | string | no | null | e.g. `~75% of volume` (Hager) | Matrix 6.3 (D20); Scope tab D5 |
| `productTypeIds` | array<objectId> | no | `[]` | → `productTypes` this vendor supplies | Scope tab A4:C9 |
| `active` | bool | yes | `true` | `false` for American Dryer (not used) and Scranton (access lost — must go through a costlier distributor) | Matrix 2.2 (I6); Scope tab G8 |
| `inactiveReason` | string | no | null | | Matrix 2.2 (I6) |
| `hasApiFeed` | bool | yes | `false` | Hager live-data/API feed under investigation | Open NR-12 |
| `websiteUrl` | string | no | null | Third cost path: mfr website for never-sold-direct parts | Matrix 6.2 (I19) |
| *soft delete* | — | — | — | Per Q13 | §4.3 |
| *envelope* | — | — | — | | §4.2 |

**Relationships:** self-referential `distributorIds` (N:N); referenced by `catalogItems`, `vendorTiers`, `priceBooks`, `adders`, `lightKitRates`, `vendorRfqs` (all 1:N); `productTypeIds` → `productTypes` (N:N).

**Indexes:**
- `{ orgId: 1, name: 1 }` — **unique**.
- `{ orgId: 1, isTop10: 1, active: 1 }` — serves the Phase 1 vendor slice ("top-10 vendors only", Matrix 6.3 I20).
- `{ orgId: 1, requiresManualPrice: 1 }` — **partial** (`requiresManualPrice: true`) — drives the manual-entry banner and the refresh prompt (NR-2).
- `{ orgId: 1, isDeleted: 1, active: 1 }` — admin list.

```javascript
db.createCollection("vendors", {
  validator: { $jsonSchema: {
    bsonType: "object",
    required: [...envelopeRequired, "name", "vendorType", "purchasePath",
               "requiresManualPrice", "isTop10", "active", "hasApiFeed", "isDeleted"],
    properties: {
      ...envelope, ...softDelete,
      _id: { bsonType: "objectId" },
      name: { bsonType: "string" },
      vendorType: { enum: ["manufacturer", "distributor", "fabricator"] },
      subBrands: { bsonType: "array", items: { bsonType: "string" } },
      purchasePath: { enum: ["direct", "viaDistributor", "manualOnly"] },
      distributorIds: { bsonType: "array", items: { bsonType: "objectId" } },
      requiresManualPrice: { bsonType: "bool" },
      isTop10: { bsonType: "bool" },
      volumeShareNote: { bsonType: ["string", "null"] },
      productTypeIds: { bsonType: "array", items: { bsonType: "objectId" } },
      active: { bsonType: "bool" },
      inactiveReason: { bsonType: ["string", "null"] },
      hasApiFeed: { bsonType: "bool" },
      websiteUrl: { bsonType: ["string", "null"] }
    }
  } }
});
db.vendors.createIndex({ orgId: 1, name: 1 }, { unique: true });
db.vendors.createIndex({ orgId: 1, isTop10: 1, active: 1 });
db.vendors.createIndex({ orgId: 1, requiresManualPrice: 1 },
  { partialFilterExpression: { requiresManualPrice: true } });
db.vendors.createIndex({ orgId: 1, isDeleted: 1, active: 1 });
```

**Notes:** Distributors are modelled as `vendors` with `vendorType: "distributor"` and linked by self-reference rather than as a separate `distributors` collection. They share every meaningful attribute with manufacturers (tiers, price books, RFQ targets, manual-price flags), and a separate collection would force every cost-path query to union two collections. Deactivated vendors are kept, not deleted — Scranton and American Dryer must remain resolvable so historical quotes still render (NFR-3).

---

### 3.9 `catalogItems`

**Purpose:** The central reference library of parts — FR-3's *"central, structured reference library of hardware sets & standard line items, independent of any single job file."* The seeding rule from the 14 Jul session is decisive for the design: build the **top-10 stock items per product type** (~20 with grade variants) plus a **CUSTOM/OTHER** path for the full option matrix (Matrix 7.2 I28, Open NR-6, NR-13).

**`_id` strategy:** `ObjectId`. Unique business key on `{ orgId, vendorId, partNumber }` — manufacturer part numbers are unique within a vendor but not globally.

| Field | Type | Required | Default | Description | Source |
|---|---|---|---|---|---|
| `_id` | objectId | yes | auto | | — |
| `vendorId` | objectId | yes | — | → `vendors` | Matrix 2.2 |
| `partNumber` | string | yes | — | The quoting key. Architects specify by part number/series | Matrix 7.7 (I33) |
| `series` | string | no | null | e.g. `3400`, `3500` (Hager) | Matrix 7.2 (I28) |
| `description` | string | yes | — | | Matrix 7.2 |
| `productTypeId` | objectId | yes | — | → `productTypes` | Matrix 2.1 |
| `grade` | string (enum) | no | null | `1` \| `2` \| `3` — Hager 3400 = grade 1, 3500 = grade 2. **Recorded but never quoted on** | Matrix 7.2 (I28) |
| `isStock` | bool | yes | `false` | On the CBC top-10 stock list | Open NR-6 |
| `stockRank` | int | no | null | 1–10 within its product type | Open NR-6 |
| `isCustomPlaceholder` | bool | yes | `false` | `true` = the CUSTOM/OTHER entry for its product type; forces the manual path | Matrix 7.2 (I28); Open NR-13 |
| `unitOfMeasure` | string (enum) | yes | `EA` | `EA` \| `LF` \| `SF` \| `PR` \| `SET` | Matrix 5.0 (D16); Flow C8 |
| `options` | object | no | `{}` | Option matrix: `{ function, backset, finish, lever, keyway, strike, electrified, handing }` | Matrix 7.2 (I28) |
| `defaultFinishCode` | string | no | null | → `finishCodes.code` | Matrix 7.5 (I31) |
| `availableFinishCodes` | array<string> | no | `[]` | → `finishCodes.code` | Matrix 7.5 (I31) |
| `handedProduct` | bool | yes | `false` | Locks, closers, exit devices are handed | Matrix 7.4 (D30) |
| `fireRatings` | array<string(enum)> | no | `[]` | UL-labelled ratings this item carries: `20`,`45`,`60`,`90` | Matrix 7.3 (D29); Q5 |
| `ulLabelled` | bool | yes | `false` | Required for `ratingConflict` evaluation | Q5 |
| `sizeCodes` | array<string> | no | `[]` | For doors/frames: `3070`, `3670` | Matrix 7.1 (D27) |
| `frameDepthCode` | string | no | null | → `frameDepths.code` (frames only) | Matrix 7.0 (I26) |
| `isDiscontinued` | bool | yes | `false` | | Matrix 2.2 (I6) |
| `p21ItemId` | string | no | null | Denormalized from `p21ItemMappings` for fast display; authoritative record is the mapping collection | Q4; Matrix 6.2 (I19) |
| `searchTerms` | array<string> | no | `[]` | Synonyms/spec callouts feeding the matcher | FR-4 (C41) |
| *envelope* | — | — | — | | §4.2 |

**Relationships:** `vendorId` → `vendors` (N:1); `productTypeId` → `productTypes` (N:1); referenced by `hardwareSets.items[].catalogItemId`, `priceBookEntries.catalogItemId`, `p21ItemMappings.catalogItemId`, `estimateLines.catalogItemId`, `openings.matchCandidates[].catalogItemId` (all 1:N).

**Indexes:**
- `{ orgId: 1, vendorId: 1, partNumber: 1 }` — **unique**. Primary lookup; also the reconciliation key for price-book ingestion.
- `{ orgId: 1, productTypeId: 1, isStock: 1, stockRank: 1 }` — serves the item picker ("top-10 per product type", NR-6).
- `{ orgId: 1, partNumber: 1 }` — cross-vendor part-number search from a spec callout (FR-4).
- `{ orgId: 1, productTypeId: 1, "options.function": 1, defaultFinishCode: 1 }` — serves attribute-based matching when the spec names a function but no manufacturer (Matrix 6.4, direct-equal).
- `{ orgId: 1, fireRatings: 1, productTypeId: 1 }` — **multikey**. Serves rating-constrained matching (FR-4, Q5).
- **Text index** on `{ description: "text", searchTerms: "text", partNumber: "text" }` — serves the estimator's free-text library search, the analogue of the P21 search behaviour described in FR-8 (I45).

```javascript
db.createCollection("catalogItems", {
  validator: { $jsonSchema: {
    bsonType: "object",
    required: [...envelopeRequired, "vendorId", "partNumber", "description", "productTypeId",
               "isStock", "isCustomPlaceholder", "unitOfMeasure", "handedProduct",
               "ulLabelled", "isDiscontinued"],
    properties: {
      ...envelope,
      _id: { bsonType: "objectId" },
      vendorId: { bsonType: "objectId" },
      partNumber: { bsonType: "string" },
      series: { bsonType: ["string", "null"] },
      description: { bsonType: "string" },
      productTypeId: { bsonType: "objectId" },
      grade: { enum: ["1", "2", "3", null] },
      isStock: { bsonType: "bool" },
      stockRank: { bsonType: ["int", "null"], minimum: 1 },
      isCustomPlaceholder: { bsonType: "bool" },
      unitOfMeasure: { enum: ["EA", "LF", "SF", "PR", "SET"] },
      options: { bsonType: ["object", "null"], properties: {
        function:   { bsonType: ["string", "null"] },
        backset:    { bsonType: ["string", "null"] },
        finish:     { bsonType: ["string", "null"] },
        lever:      { bsonType: ["string", "null"] },
        keyway:     { bsonType: ["string", "null"] },
        strike:     { bsonType: ["string", "null"] },
        electrified:{ bsonType: ["bool", "null"] },
        handing:    { enum: ["LH", "RH", "LHR", "RHR", "reversible", null] } } },
      defaultFinishCode: { bsonType: ["string", "null"] },
      availableFinishCodes: { bsonType: "array", items: { bsonType: "string" } },
      handedProduct: { bsonType: "bool" },
      fireRatings: { bsonType: "array", items: { enum: ["20", "45", "60", "90"] } },
      ulLabelled: { bsonType: "bool" },
      sizeCodes: { bsonType: "array", items: { bsonType: "string", pattern: "^[0-9]{4}$" } },
      frameDepthCode: { bsonType: ["string", "null"] },
      isDiscontinued: { bsonType: "bool" },
      p21ItemId: { bsonType: ["string", "null"] },
      searchTerms: { bsonType: "array", items: { bsonType: "string" } }
    }
  } }
});
db.catalogItems.createIndex({ orgId: 1, vendorId: 1, partNumber: 1 }, { unique: true });
db.catalogItems.createIndex({ orgId: 1, productTypeId: 1, isStock: 1, stockRank: 1 });
db.catalogItems.createIndex({ orgId: 1, partNumber: 1 });
db.catalogItems.createIndex({ orgId: 1, productTypeId: 1, "options.function": 1, defaultFinishCode: 1 });
db.catalogItems.createIndex({ orgId: 1, fireRatings: 1, productTypeId: 1 });
db.catalogItems.createIndex({ description: "text", searchTerms: "text", partNumber: "text" },
  { name: "catalogItems_text" });
```

**Notes on denormalization:** `p21ItemId` is duplicated here from `p21ItemMappings` purely so a line-item grid can render the P21 reference without a join. It is written **only** by the P21 sync job, which updates the mapping first and the catalog item second in the same task; the mapping collection is authoritative in any disagreement. This is the extended-reference pattern, justified by the line-review grid being the single highest-frequency read in the application.

`grade` deserves its own note. Matrix 7.2 (I28) is emphatic: *quote by part number/series, NOT by grade.* The field is stored because architects and estimators talk in grades, but no index leads with it and no matching rule may use it as a primary key — it is display and disambiguation context only.

---

### 3.10 `hardwareSets`

**Purpose:** Hardware sets for an opening — both the spec's sets (HW-1, HW-2… from the Division 08 hardware schedule) and CBC's own reference sets. Matrix 7.7 (I33) resolves the source-of-truth question: architects specify by part number/series, and CBC **reconciles that to its stock/top-10**, with the custom/other tab covering everything beyond.

**`_id` strategy:** `ObjectId`.

| Field | Type | Required | Default | Description | Source |
|---|---|---|---|---|---|
| `_id` | objectId | yes | auto | | — |
| `setCode` | string | yes | — | `HW-1`, `HW-2`, or a CBC library code | Matrix 7.7 (D33) |
| `setSource` | string (enum) | yes | — | `cbcLibrary` \| `specExtracted` \| `brandProgram` | Matrix 7.7 (D33, I33) |
| `bidRequestId` | objectId | no | null | Populated only when `setSource = specExtracted` | Matrix 7.7 (I33) |
| `name` | string | yes | — | e.g. `Exterior storeroom, rated` | Matrix 7.2 (D28) |
| `vendorId` | objectId | no | null | → `vendors`; usually Hager (~75%) | Matrix 7.2 (I28) |
| `items` | array<object> | yes | `[]` | Embedded components — see sub-table | Matrix 7.2 (D28) |
| `applicableOpeningType` | string (enum) | no | null | `exterior` \| `interior` \| `restroom` \| `storeroom` \| `other` | Matrix 7.2 (E28) |
| `fireRating` | string (enum) | no | null | `20`\|`45`\|`60`\|`90`\|`none` | Matrix 7.3 (D29); Q5 |
| `handing` | string (enum) | no | null | `LH`\|`RH`\|`LHR`\|`RHR` | Matrix 7.4 (D30) |
| `finishCode` | string | no | null | → `finishCodes.code` | Matrix 7.5 (D31) |
| `isStandard` | bool | yes | `false` | Part of the seeded library | FR-3 (I40) |
| `matchedLibrarySetId` | objectId | no | null | Spec set → CBC library set reconciliation | Matrix 7.7 (I33) |
| `active` | bool | yes | `true` | | §4.2 |
| *envelope* | — | — | — | | §4.2 |

**Embedded `items[]` sub-document:**

| Field | Type | Required | Description | Source |
|---|---|---|---|---|
| `_id` | objectId | yes | Stable subdocument id | §4.5 |
| `component` | string (enum) | yes | `hingeContinuous`, `hingeButt`, `lock`, `exitDevice`, `closer`, `kickPlate`, `threshold`, `doorSweep`, `weatherstrip`, `smokeSeal`, `floorStop`, `holder`, `silencer`, `other` | Matrix 7.2 (D28) |
| `catalogItemId` | objectId | no | → `catalogItems`; null when the spec named something not yet in the library | Matrix 7.7 (I33) |
| `specifiedPartNumber` | string | no | Verbatim from the spec, retained even when unmatched | Matrix 7.7 (I33) |
| `quantity` | double | yes | Per opening (e.g. 3 hinges, 1 lock) | Matrix 5.0 (D16) |
| `finishCode` | string | no | Component-level finish override | Matrix 7.5 (D31) |
| `notes` | string | no | | Matrix 7.2 |

**Relationships:** `items[].catalogItemId` → `catalogItems` (N:1); `vendorId` → `vendors` (N:1); `matchedLibrarySetId` → `hardwareSets` (self, N:1); referenced by `openings.hardwareSetId` and `brandPrograms.standardHardwareSetIds[]` (1:N).

**Indexes:**
- `{ orgId: 1, setSource: 1, setCode: 1 }` — **unique** on `{ orgId, setCode }` restricted to `setSource: "cbcLibrary"` via a partial index; spec-extracted sets repeat `HW-1` across bids and must not collide.
- `{ orgId: 1, bidRequestId: 1, setCode: 1 }` — **partial** (`bidRequestId` non-null). Serves "the HW sets extracted from this bid".
- `{ orgId: 1, isStandard: 1, applicableOpeningType: 1, fireRating: 1 }` — serves FR-4 set matching under rating constraint.
- `{ orgId: 1, "items.catalogItemId": 1 }` — **multikey**. Serves "which sets contain this part" — required for impact analysis when a part is discontinued or a vendor tier is renegotiated.

```javascript
db.createCollection("hardwareSets", {
  validator: { $jsonSchema: {
    bsonType: "object",
    required: [...envelopeRequired, "setCode", "setSource", "name", "items", "isStandard", "active"],
    properties: {
      ...envelope,
      _id: { bsonType: "objectId" },
      setCode: { bsonType: "string" },
      setSource: { enum: ["cbcLibrary", "specExtracted", "brandProgram"] },
      bidRequestId: { bsonType: ["objectId", "null"] },
      name: { bsonType: "string" },
      vendorId: { bsonType: ["objectId", "null"] },
      applicableOpeningType: { enum: ["exterior", "interior", "restroom", "storeroom", "other", null] },
      fireRating: { enum: ["20", "45", "60", "90", "none", null] },
      handing: { enum: ["LH", "RH", "LHR", "RHR", null] },
      finishCode: { bsonType: ["string", "null"] },
      isStandard: { bsonType: "bool" },
      matchedLibrarySetId: { bsonType: ["objectId", "null"] },
      active: { bsonType: "bool" },
      items: { bsonType: "array", items: {
        bsonType: "object",
        required: ["_id", "component", "quantity"],
        properties: {
          _id: { bsonType: "objectId" },
          component: { enum: ["hingeContinuous", "hingeButt", "lock", "exitDevice", "closer",
                              "kickPlate", "threshold", "doorSweep", "weatherstrip", "smokeSeal",
                              "floorStop", "holder", "silencer", "other"] },
          catalogItemId: { bsonType: ["objectId", "null"] },
          specifiedPartNumber: { bsonType: ["string", "null"] },
          quantity: { bsonType: "double", minimum: 0 },
          finishCode: { bsonType: ["string", "null"] },
          notes: { bsonType: ["string", "null"] }
        } } }
    }
  } }
});
db.hardwareSets.createIndex({ orgId: 1, setCode: 1 }, { unique: true,
  partialFilterExpression: { setSource: "cbcLibrary" } });
db.hardwareSets.createIndex({ orgId: 1, bidRequestId: 1, setCode: 1 },
  { partialFilterExpression: { bidRequestId: { $type: "objectId" } } });
db.hardwareSets.createIndex({ orgId: 1, isStandard: 1, applicableOpeningType: 1, fireRating: 1 });
db.hardwareSets.createIndex({ orgId: 1, "items.catalogItemId": 1 });
```

**Embedding justification:** `items[]` is embedded because a set is bounded at roughly 9–15 components (Matrix 7.2 lists nine typical component classes), is always read in full with its parent when pricing an opening, and has no independent lifecycle. `specifiedPartNumber` is retained alongside `catalogItemId` deliberately — Matrix 7.2 (I28) says there is *no single standard hardware list*, so an unmatched spec component must survive in the record rather than being dropped when the library has no entry for it.

---

### 3.11 `adders`

**Purpose:** Manual adders that are **not shown cleanly in the base price book** and must be added on top of the base price — electrification, non-removable-pin hinges, premium/lead-time finishes (Matrix 6.3 I20, Open NR-4, NR-7). Left implicit, these silently under-price a line, which is why they are a first-class collection rather than a free-text note.

**`_id` strategy:** `ObjectId`.

| Field | Type | Required | Default | Description | Source |
|---|---|---|---|---|---|
| `_id` | objectId | yes | auto | | — |
| `code` | string | yes | — | `ELECTRIFICATION`, `NRP_HINGE`, `PREMIUM_FINISH` | Open NR-4 |
| `name` | string | yes | — | | Open NR-4 |
| `vendorId` | objectId | yes | — | → `vendors`; adder tables are vendor-specific (Hager values pending, NR-7) | Open NR-7 |
| `appliesToProductTypeIds` | array<objectId> | yes | `[]` | → `productTypes` | Matrix 6.3 (I20) |
| `appliesToSeries` | array<string> | no | `[]` | Narrow to specific series when the price book does | Open NR-7 |
| `valueType` | string (enum) | yes | — | `flatAmount` \| `percentOfList` \| `perUnit` | Open NR-7 |
| `value` | double | no | null | **Null until CBC supplies the Hager adder values (NR-7)** | Open NR-7 |
| `currency` | string | yes | `USD` | | §4.7 |
| `addsLeadTime` | bool | yes | `false` | Premium finishes carry lead time | Matrix 7.5 (I31) |
| `leadTimeDays` | int | no | null | | Matrix 7.5 (I31) |
| `priceBookId` | objectId | no | null | → `priceBooks` when the adder was derived from one | Open NR-7 |
| `dataStatus` | string (enum) | yes | `pending` | `pending` \| `confirmed` — `pending` blocks automated application | Open NR-7 |
| `effectiveFrom` / `effectiveTo` | date | yes / no | — / null | | §4.6 |
| *envelope* | — | — | — | | §4.2 |

**Relationships:** `vendorId` → `vendors` (N:1); `appliesToProductTypeIds[]` → `productTypes` (N:N); applied adders are frozen into `estimateLines.appliedAdders[]`.

**Indexes:**
- `{ orgId: 1, vendorId: 1, code: 1, effectiveFrom: -1 }` — **unique**. Current adder resolution.
- `{ orgId: 1, appliesToProductTypeIds: 1, dataStatus: 1 }` — **multikey**. Serves "which adders are offerable for this line".

```javascript
db.createCollection("adders", {
  validator: { $jsonSchema: {
    bsonType: "object",
    required: [...envelopeRequired, "code", "name", "vendorId", "appliesToProductTypeIds",
               "valueType", "currency", "addsLeadTime", "dataStatus", "effectiveFrom"],
    properties: {
      ...envelope,
      _id: { bsonType: "objectId" },
      code: { bsonType: "string", pattern: "^[A-Z0-9_]+$" },
      name: { bsonType: "string" },
      vendorId: { bsonType: "objectId" },
      appliesToProductTypeIds: { bsonType: "array", items: { bsonType: "objectId" } },
      appliesToSeries: { bsonType: "array", items: { bsonType: "string" } },
      valueType: { enum: ["flatAmount", "percentOfList", "perUnit"] },
      value: { bsonType: ["double", "null"], minimum: 0 },
      currency: { enum: ["USD"] },
      addsLeadTime: { bsonType: "bool" },
      leadTimeDays: { bsonType: ["int", "null"], minimum: 0 },
      priceBookId: { bsonType: ["objectId", "null"] },
      dataStatus: { enum: ["pending", "confirmed"] },
      effectiveFrom: { bsonType: "date" },
      effectiveTo: { bsonType: ["date", "null"] }
    }
  } }
});
db.adders.createIndex({ orgId: 1, vendorId: 1, code: 1, effectiveFrom: -1 }, { unique: true });
db.adders.createIndex({ orgId: 1, appliesToProductTypeIds: 1, dataStatus: 1 });
```

**Notes:** `value` is nullable *by design* — the workbook records the adder categories but NR-7 lists the actual Hager values as data CBC still owes. A `pending` adder is visible to the estimator as a prompt ("this line may need an electrification adder") but must never be auto-applied with a fabricated number.

---

### 3.12 `lightKitRates`

**Purpose:** Backs NR-1, the light-kit (lites/louvers) pricing calculator: input glazing type + size, return price from the vendor tables (National Guard, PEMKO/Markar, Rockwood). The workbook notes the underlying data is already on file; NR-8 asks for the table *logic* to be confirmed.

**`_id` strategy:** `ObjectId`.

| Field | Type | Required | Default | Description | Source |
|---|---|---|---|---|---|
| `_id` | objectId | yes | auto | | — |
| `vendorId` | objectId | yes | — | → `vendors`: National Guard, PEMKO/Markar, Rockwood | Open NR-1 |
| `glazingType` | string | yes | — | e.g. `clear`, `wire`, `tempered`, `fire-rated` | Open NR-1 |
| `kitType` | string (enum) | yes | `lite` | `lite` \| `louver` | Open NR-1 |
| `widthIn` | double | no | null | Nominal cut-out width | Open NR-1 |
| `heightIn` | double | no | null | Nominal cut-out height | Open NR-1 |
| `sizeBand` | string | no | null | Where the vendor prices by band rather than exact size | Open NR-8 |
| `listPrice` | double | no | null | | Open NR-1 |
| `sizeMultiplier` | double | no | null | Where the table is multiplier-driven | Open NR-8 |
| `fireRating` | string (enum) | no | null | Rated glazing carries a rating | Matrix 7.3; Q5 |
| `priceBookId` | objectId | no | null | → `priceBooks` | Matrix 6.3 |
| `dataStatus` | string (enum) | yes | `pending` | `pending` \| `confirmed` — NR-8 outstanding | Open NR-8 |
| `effectiveFrom` / `effectiveTo` | date | yes / no | — / null | | §4.6 |
| *envelope* | — | — | — | | §4.2 |

**Relationships:** `vendorId` → `vendors` (N:1); `priceBookId` → `priceBooks` (N:1). Resolved rates are frozen into `estimateLines.costSnapshot`.

**Indexes:**
- `{ orgId: 1, vendorId: 1, kitType: 1, glazingType: 1, widthIn: 1, heightIn: 1 }` — the calculator's lookup path (NR-1).
- `{ orgId: 1, dataStatus: 1 }` — surfaces what still needs confirming (NR-8).

```javascript
db.createCollection("lightKitRates", {
  validator: { $jsonSchema: {
    bsonType: "object",
    required: [...envelopeRequired, "vendorId", "glazingType", "kitType", "dataStatus", "effectiveFrom"],
    properties: {
      ...envelope,
      _id: { bsonType: "objectId" },
      vendorId: { bsonType: "objectId" },
      glazingType: { bsonType: "string" },
      kitType: { enum: ["lite", "louver"] },
      widthIn: { bsonType: ["double", "null"], minimum: 0 },
      heightIn: { bsonType: ["double", "null"], minimum: 0 },
      sizeBand: { bsonType: ["string", "null"] },
      listPrice: { bsonType: ["double", "null"], minimum: 0 },
      sizeMultiplier: { bsonType: ["double", "null"], minimum: 0 },
      fireRating: { enum: ["20", "45", "60", "90", "none", null] },
      priceBookId: { bsonType: ["objectId", "null"] },
      dataStatus: { enum: ["pending", "confirmed"] },
      effectiveFrom: { bsonType: "date" },
      effectiveTo: { bsonType: ["date", "null"] }
    }
  } }
});
db.lightKitRates.createIndex({ orgId: 1, vendorId: 1, kitType: 1, glazingType: 1, widthIn: 1, heightIn: 1 });
db.lightKitRates.createIndex({ orgId: 1, dataStatus: 1 });
```

**Notes:** Both `listPrice` and `sizeMultiplier` are nullable because NR-8 has not yet confirmed whether the vendor tables are absolute-price or multiplier-driven — the schema holds either shape without a migration, and `dataStatus` keeps unconfirmed rows out of automated pricing.

---

### 3.13 `priceBooks`

**Purpose:** A dated vendor price sheet or memo. Matrix 6.3 (D20) records that *price changes arrive as dated memos with a protection window* — so a price book is a versioned artifact with a validity period, not a mutable table. NFR-3 requires every quoted line to name the price-sheet version and effective date it was priced from.

**`_id` strategy:** `ObjectId`; unique business key `{ orgId, vendorId, version }`.

| Field | Type | Required | Default | Description | Source |
|---|---|---|---|---|---|
| `_id` | objectId | yes | auto | | — |
| `vendorId` | objectId | yes | — | → `vendors` | Matrix 6.3 |
| `version` | string | yes | — | Vendor's own memo/edition label | Matrix 6.3 (D20) |
| `effectiveFrom` | date | yes | — | | Matrix 6.3 (D20) |
| `effectiveTo` | date | no | null | Null = currently in force | §4.6 |
| `protectionWindowEnds` | date | no | null | Price-protection window from the memo | Matrix 6.3 (D20) |
| `currency` | string | yes | `USD` | | §4.7 |
| `sourceDocumentId` | objectId | no | null | → `documents`; the PDF price book | Q9 |
| `isMap` | bool | yes | `false` | Marks a MAP sheet. **MAP is NOT cost** — this flag exists to stop a MAP sheet ever being consumed as a cost source | Matrix 6.3 (D20) |
| `entryCount` | int | no | null | Denormalized count for the admin list | §4.8 |
| `ingestStatus` | string (enum) | yes | `pending` | `pending` \| `ingested` \| `failed` \| `superseded` | Q4 |
| `ownerUserId` | objectId | no | null | Data-steward owner. **Unset — NFR-10 open** | NFR-10; §6.3 |
| `refreshCadence` | string | no | null | **Unset — NFR-10 open** | NFR-10; §6.3 |
| `lastReviewedAt` | date | no | null | Staleness signal for the stewardship dashboard | NFR-10 |
| *soft delete* | — | — | — | Per Q13 | §4.3 |
| *envelope* | — | — | — | | §4.2 |

**Relationships:** `vendorId` → `vendors` (N:1); parent of `priceBookEntries` (1:N, unbounded → referenced); frozen into `estimateLines.priceBookSnapshot`.

**Indexes:**
- `{ orgId: 1, vendorId: 1, version: 1 }` — **unique**.
- `{ orgId: 1, vendorId: 1, effectiveFrom: -1 }` — resolves "current price book for this vendor" at pricing time.
- `{ orgId: 1, effectiveTo: 1, isDeleted: 1 }` — **partial** (`effectiveTo: null`) — the live-sheets list for stewardship (NFR-10).

```javascript
db.createCollection("priceBooks", {
  validator: { $jsonSchema: {
    bsonType: "object",
    required: [...envelopeRequired, "vendorId", "version", "effectiveFrom",
               "currency", "isMap", "ingestStatus", "isDeleted"],
    properties: {
      ...envelope, ...softDelete,
      _id: { bsonType: "objectId" },
      vendorId: { bsonType: "objectId" },
      version: { bsonType: "string" },
      effectiveFrom: { bsonType: "date" },
      effectiveTo: { bsonType: ["date", "null"] },
      protectionWindowEnds: { bsonType: ["date", "null"] },
      currency: { enum: ["USD"] },
      sourceDocumentId: { bsonType: ["objectId", "null"] },
      isMap: { bsonType: "bool" },
      entryCount: { bsonType: ["int", "null"], minimum: 0 },
      ingestStatus: { enum: ["pending", "ingested", "failed", "superseded"] },
      ownerUserId: { bsonType: ["objectId", "null"] },
      refreshCadence: { bsonType: ["string", "null"] },
      lastReviewedAt: { bsonType: ["date", "null"] }
    }
  } }
});
db.priceBooks.createIndex({ orgId: 1, vendorId: 1, version: 1 }, { unique: true });
db.priceBooks.createIndex({ orgId: 1, vendorId: 1, effectiveFrom: -1 });
db.priceBooks.createIndex({ orgId: 1, effectiveTo: 1, isDeleted: 1 },
  { partialFilterExpression: { effectiveTo: null } });
```

**Notes:** `ownerUserId` and `refreshCadence` are deliberately present-but-empty. NFR-10 and Open Item 15 both remain unanswered, and Assumptions row 11 names stale price sheets as an active risk. Having the fields ready means the stewardship answer, when it arrives, is a data change rather than a schema change — and in the meantime `lastReviewedAt` gives a queryable staleness signal.

---

### 3.14 `priceBookEntries`

**Purpose:** One list price for one item in one price book. Referenced rather than embedded in `priceBooks` because a vendor price book runs to thousands of lines — the Hager book alone — which is unbounded relative to the 16 MB document limit and is queried by part number, not by book.

**`_id` strategy:** `ObjectId`; unique business key `{ orgId, priceBookId, partNumber }`.

| Field | Type | Required | Default | Description | Source |
|---|---|---|---|---|---|
| `_id` | objectId | yes | auto | | — |
| `priceBookId` | objectId | yes | — | → `priceBooks` | Matrix 6.3 |
| `vendorId` | objectId | yes | — | Denormalized from the parent book — see notes | §4.8 |
| `partNumber` | string | yes | — | Vendor's part number | Matrix 6.3 (D20) |
| `description` | string | no | null | | Matrix 6.3 |
| `listPrice` | double | yes | — | e.g. Hager 3500-series storeroom lock at `256.31` | Matrix 6.3 (D20) |
| `netPrice` | double | no | null | Some sheets pre-compute net (World Dryer) | Matrix 6.3 (D20) |
| `unitOfMeasure` | string (enum) | yes | `EA` | | Matrix 5.0 |
| `catalogItemId` | objectId | no | null | → `catalogItems`; null until reconciled | Q4 |
| `finishCode` | string | no | null | Finish-specific pricing | Matrix 7.5 |
| `sizeCode` | string | no | null | Size-specific pricing for doors/frames | Matrix 7.1 |
| `currency` | string | yes | `USD` | | §4.7 |
| *envelope* | — | — | — | | §4.2 |

**Relationships:** `priceBookId` → `priceBooks` (N:1); `catalogItemId` → `catalogItems` (N:1, optional); `vendorId` → `vendors` (N:1, denormalized).

**Indexes:**
- `{ orgId: 1, priceBookId: 1, partNumber: 1 }` — **unique**. Ingestion idempotency and direct lookup.
- `{ orgId: 1, vendorId: 1, partNumber: 1 }` — resolves "current list price for this part" without first loading the book document. This is the index that makes the denormalized `vendorId` worth carrying.
- `{ orgId: 1, catalogItemId: 1 }` — **partial** (`catalogItemId` non-null). Serves pricing from a matched library item (FR-6).

```javascript
db.createCollection("priceBookEntries", {
  validator: { $jsonSchema: {
    bsonType: "object",
    required: [...envelopeRequired, "priceBookId", "vendorId", "partNumber",
               "listPrice", "unitOfMeasure", "currency"],
    properties: {
      ...envelope,
      _id: { bsonType: "objectId" },
      priceBookId: { bsonType: "objectId" },
      vendorId: { bsonType: "objectId" },
      partNumber: { bsonType: "string" },
      description: { bsonType: ["string", "null"] },
      listPrice: { bsonType: "double", minimum: 0 },
      netPrice: { bsonType: ["double", "null"], minimum: 0 },
      unitOfMeasure: { enum: ["EA", "LF", "SF", "PR", "SET"] },
      catalogItemId: { bsonType: ["objectId", "null"] },
      finishCode: { bsonType: ["string", "null"] },
      sizeCode: { bsonType: ["string", "null"] },
      currency: { enum: ["USD"] }
    }
  } }
});
db.priceBookEntries.createIndex({ orgId: 1, priceBookId: 1, partNumber: 1 }, { unique: true });
db.priceBookEntries.createIndex({ orgId: 1, vendorId: 1, partNumber: 1 });
db.priceBookEntries.createIndex({ orgId: 1, catalogItemId: 1 },
  { partialFilterExpression: { catalogItemId: { $type: "objectId" } } });
```

**Denormalization note:** `vendorId` is copied from the parent `priceBooks` document. It is immutable in practice — a price book never changes vendor — so there is no sync burden; it is written once at ingestion. `netPrice` exists because Matrix 6.3 (D20) records that some vendor sheets (World Dryer) **pre-compute the net**, meaning the list × multiplier calculation must be skipped for those rows rather than applied twice.

---

### 3.15 `vendorTiers`

**Purpose:** CBC's negotiated discount tier per vendor account. Matrix 6.3 (E20) settles the modelling question explicitly: *the multiplier is a per-vendor account attribute (a tier), not a per-item value.* Worked examples in the workbook: a Hager "50 & 42" discount ≈ 0.29 multiplier turning a $256.31 list into ≈ $74 cost; Hamilton Parker is World Dryer Level-3 at 0.339.

**`_id` strategy:** `ObjectId`; unique business key `{ orgId, vendorId, tierCode, effectiveFrom }`.

| Field | Type | Required | Default | Description | Source |
|---|---|---|---|---|---|
| `_id` | objectId | yes | auto | | — |
| `vendorId` | objectId | yes | — | → `vendors` | Matrix 6.3 |
| `tierCode` | string | yes | — | `L3`, `50 & 42` | Matrix 6.3 (D20) |
| `tierName` | string | no | null | `Level-3` | Matrix 6.3 (D20) |
| `multiplier` | double | yes | — | Decimal applied to list: `0.339`, `0.29` | Matrix 6.3 (D20) |
| `discountChain` | array<double> | no | `[]` | Source chain where quoted as one, e.g. `[0.50, 0.42]` | Matrix 6.3 (D20) |
| `appliesToProductTypeIds` | array<objectId> | no | `[]` | Empty = whole account | Matrix 6.3 (E20) |
| `preComputedNet` | bool | yes | `false` | `true` where the vendor sheet already nets the price (World Dryer) — suppresses multiplier application | Matrix 6.3 (D20) |
| `effectiveFrom` | date | yes | — | | Open 3 |
| `effectiveTo` | date | no | null | | §4.6 |
| `sourceDocumentId` | objectId | no | null | → `documents`; the multiplier sheet on file | Assumptions row 3 (F6) |
| `ownerUserId` / `refreshCadence` | objectId / string | no | null | **Unset — NFR-10 open** | NFR-10 |
| *envelope* | — | — | — | | §4.2 |

**Relationships:** `vendorId` → `vendors` (N:1); frozen into `estimateLines.multiplierTierSnapshot`.

**Indexes:**
- `{ orgId: 1, vendorId: 1, tierCode: 1, effectiveFrom: -1 }` — **unique**.
- `{ orgId: 1, vendorId: 1, effectiveTo: 1 }` — **partial** (`effectiveTo: null`) — resolves the tier in force at pricing time in one hit.

```javascript
db.createCollection("vendorTiers", {
  validator: { $jsonSchema: {
    bsonType: "object",
    required: [...envelopeRequired, "vendorId", "tierCode", "multiplier",
               "preComputedNet", "effectiveFrom"],
    properties: {
      ...envelope,
      _id: { bsonType: "objectId" },
      vendorId: { bsonType: "objectId" },
      tierCode: { bsonType: "string" },
      tierName: { bsonType: ["string", "null"] },
      multiplier: { bsonType: "double", exclusiveMinimum: 0, maximum: 1 },
      discountChain: { bsonType: "array", items: { bsonType: "double", minimum: 0, maximum: 1 } },
      appliesToProductTypeIds: { bsonType: "array", items: { bsonType: "objectId" } },
      preComputedNet: { bsonType: "bool" },
      effectiveFrom: { bsonType: "date" },
      effectiveTo: { bsonType: ["date", "null"] },
      sourceDocumentId: { bsonType: ["objectId", "null"] },
      ownerUserId: { bsonType: ["objectId", "null"] },
      refreshCadence: { bsonType: ["string", "null"] }
    }
  } }
});
db.vendorTiers.createIndex({ orgId: 1, vendorId: 1, tierCode: 1, effectiveFrom: -1 }, { unique: true });
db.vendorTiers.createIndex({ orgId: 1, vendorId: 1, effectiveTo: 1 },
  { partialFilterExpression: { effectiveTo: null } });
```

**Notes:** `multiplier` is constrained to `(0, 1]` because it is a discount multiplier applied to list — a value above 1 would represent a markup on list, which the workbook never describes. `discountChain` preserves the vendor's own "50 & 42" phrasing alongside the computed 0.29 so an estimator can verify the arithmetic against the vendor's memo without recomputing it. `appliesToProductTypeIds` being empty (the common case) means account-wide, which matches Matrix 6.3's *"the model is near-universal."*

---

### 3.16 `marginRules`

**Purpose:** The margin framework — stable for ~14 years, applied by division as a **divisor** (Matrix 6.1). Bands from the workbook: Commodity 27% (÷0.73), Restroom partitions 35% (÷0.65), Specialty e.g. laminated doors 40% (÷0.60), Custom-built via outside fabricator 25% (÷0.75), and Accessories which *derive to ~56% from the data* (was 35%). The 14 Jul session is emphatic that margin is **overridable on essentially every quote** based on sourcing.

**`_id` strategy:** `ObjectId`.

| Field | Type | Required | Default | Description | Source |
|---|---|---|---|---|---|
| `_id` | objectId | yes | auto | | — |
| `band` | string (enum) | yes | — | `commodity` \| `restroomPartitions` \| `specialty` \| `customFabricated` \| `accessories` | Matrix 6.1 (D18, I18) |
| `productTypeId` | objectId | no | null | → `productTypes`; null = band-level default | Matrix 6.1 (D18) |
| `marginRate` | double | yes | — | `0.27`, `0.35`, `0.40`, `0.25`, `0.56` | Matrix 6.1 (D18, I18) |
| `scope` | string (enum) | yes | `default` | `default` \| `customer` \| `brandProgram` | Q11 |
| `customerId` | objectId | no | null | → `customers` when `scope = customer` | Q11; Open NR-9 |
| `brandProgramId` | objectId | no | null | → `brandPrograms` when `scope = brandProgram`; e.g. Wendy's | Matrix 6.1 (I18); Open NR-9 |
| `precedence` | int | yes | — | Resolution order: `10` default, `20` brand, `30` customer (higher wins) | Q11 |
| `overridable` | bool | yes | `true` | Every band is an editable default | Matrix 6.1 (I18); FR-5 |
| `floorRate` | double | no | null | **Unset — margin governance is out of scope (future)** | Matrix 6.7 (H24); NFR-8 |
| `notes` | string | no | null | e.g. `lower margin when bought via Banner/SecLock at higher cost` | Matrix 6.1 (I18) |
| `effectiveFrom` / `effectiveTo` | date | yes / no | — / null | | §4.6 |
| *envelope* | — | — | — | | §4.2 |

**Relationships:** `productTypeId` → `productTypes`, `customerId` → `customers`, `brandProgramId` → `brandPrograms` (all N:1, optional); frozen into `estimateLines.marginSnapshot`.

**Resolution order** (highest precedence first), evaluated at pricing time:
1. Line-level estimator override on `estimateLines.marginSnapshot.overridden = true`
2. `scope: customer` rule matching `customerId` (+ `productTypeId` if set)
3. `scope: brandProgram` rule matching `brandProgramId`
4. `scope: default` rule matching `productTypeId`
5. `scope: default` band-level rule with `productTypeId: null`

**Indexes:**
- `{ orgId: 1, scope: 1, customerId: 1, brandProgramId: 1, productTypeId: 1, effectiveTo: 1 }` — the resolution query above, in one index.
- `{ orgId: 1, band: 1, effectiveFrom: -1 }` — band history for audit.

```javascript
db.createCollection("marginRules", {
  validator: { $jsonSchema: {
    bsonType: "object",
    required: [...envelopeRequired, "band", "marginRate", "scope",
               "precedence", "overridable", "effectiveFrom"],
    properties: {
      ...envelope,
      _id: { bsonType: "objectId" },
      band: { enum: ["commodity", "restroomPartitions", "specialty", "customFabricated", "accessories"] },
      productTypeId: { bsonType: ["objectId", "null"] },
      marginRate: { bsonType: "double", exclusiveMinimum: 0, exclusiveMaximum: 1 },
      scope: { enum: ["default", "customer", "brandProgram"] },
      customerId: { bsonType: ["objectId", "null"] },
      brandProgramId: { bsonType: ["objectId", "null"] },
      precedence: { bsonType: "int", minimum: 0 },
      overridable: { bsonType: "bool" },
      floorRate: { bsonType: ["double", "null"], exclusiveMinimum: 0, exclusiveMaximum: 1 },
      notes: { bsonType: ["string", "null"] },
      effectiveFrom: { bsonType: "date" },
      effectiveTo: { bsonType: ["date", "null"] }
    }
  } }
});
db.marginRules.createIndex({ orgId: 1, scope: 1, customerId: 1, brandProgramId: 1,
                             productTypeId: 1, effectiveTo: 1 });
db.marginRules.createIndex({ orgId: 1, band: 1, effectiveFrom: -1 });
```

**Notes:** `marginRate` is stored strictly as the margin, never the divisor, and is constrained to the open interval (0, 1) — a rate of exactly 1 would make `cost / (1 - margin)` divide by zero, which the validator now makes structurally impossible. The divisor is always derived at calculation time (§4.7).

`floorRate` exists but is unset everywhere. Matrix 6.7, FR-15, NFR-8 and Open Item 14 all landed on *out of scope (future) — no margin deviation today*. The field is carried so that when more estimators join and governance becomes relevant, the rule rows already have somewhere to put the number.

---

### 3.17 `p21ItemMappings`

**Purpose:** The cached, read-only mirror of Prophet 21 cost data (Q4). Matrix 6.2 defines the cost rule precisely: cost is the **last purchase-order price**, and P21's supplier-list / supplier-cost fields are *not* to be trusted because purchasing doesn't reliably update them. Freshness matters: cost older than ~6–8 months is unreliable, 3–4 years must be discarded. NR-10 flags the key integration risk — P21 item IDs often differ from manufacturer part numbers, and semi/custom items won't match at all.

**`_id` strategy:** `ObjectId`; unique business key `{ orgId, p21ItemId }`.

| Field | Type | Required | Default | Description | Source |
|---|---|---|---|---|---|
| `_id` | objectId | yes | auto | | — |
| `p21ItemId` | string | yes | — | P21's own item identifier | Matrix 6.2 (I19) |
| `p21Description` | string | no | null | | Matrix 6.2 |
| `mfrPartNumber` | string | no | null | Manufacturer part number, where derivable | Q4; Open NR-10 |
| `catalogItemId` | objectId | no | null | → `catalogItems`; null = unreconciled | Q4 |
| `vendorId` | objectId | no | null | → `vendors` | Matrix 6.5 (I22) |
| `matchStatus` | string (enum) | yes | `unmatched` | `matched` \| `unmatched` \| `semiItem` \| `manualOverride` — `semiItem` marks the "semi/custom items won't match" class | Open NR-10 |
| `matchConfidence` | double | no | null | 0–1, when matched heuristically | FR-8; Open NR-10 |
| `lastPoPrice` | double | no | null | **The** cost figure. Never the supplier-list field | Matrix 6.2 (D19) |
| `lastPoDate` | date | no | null | Drives freshness | Matrix 6.2 (D19) |
| `lastSoldDate` | date | no | null | "Sold <1 yr" test from the 14 Jul session | Matrix 6.2 (I19) |
| `freshness` | string (enum) | yes | `unknown` | `fresh` \| `aging` \| `stale` \| `discard` \| `unknown` — derived, see notes | Q4; Matrix 6.2 (D19) |
| `isSpecialPriced` | bool | yes | `false` | Special-priced items already carry their cost in P21 | Matrix 6.2 (D19) |
| `lastSyncedAt` | date | yes | — | | Q4 |
| `syncSource` | string (enum) | yes | `p21` | `p21` \| `manual` | Q4 |
| `unitOfMeasure` | string (enum) | no | `EA` | | Matrix 5.0 |
| *envelope* | — | — | — | | §4.2 |

**Derived `freshness` bands** (computed at sync from `lastPoDate`):

| Band | Age of `lastPoDate` | Behaviour | Source |
|---|---|---|---|
| `fresh` | < 6 months | Auto-usable | Matrix 6.2 (D19); Q4 |
| `aging` | 6–24 months | Usable with a visible "verify price" prompt | Matrix 6.2 (D19); Q4 |
| `stale` | 24–36 months | Not auto-applied; estimator must confirm | **Derived** — bridges the workbook's 6–8 month and 3–4 year thresholds; see §6.2 |
| `discard` | > 36 months | Never applied; forces another cost path | Matrix 6.2 (D19) |
| `unknown` | no `lastPoDate` | Never applied | Q4 |

**Relationships:** `catalogItemId` → `catalogItems` (N:1); `vendorId` → `vendors` (N:1); read by the cost resolver and frozen into `estimateLines.costSnapshot`.

**Indexes:**
- `{ orgId: 1, p21ItemId: 1 }` — **unique**. Sync idempotency.
- `{ orgId: 1, mfrPartNumber: 1 }` — **partial** (non-null). The primary cost-lookup path from a matched catalog item.
- `{ orgId: 1, catalogItemId: 1, freshness: 1 }` — **partial** (`catalogItemId` non-null). Serves "give me a usable cost for this library item".
- `{ orgId: 1, matchStatus: 1, lastSyncedAt: -1 }` — the reconciliation worklist for unmatched and semi-items (NR-10).

```javascript
db.createCollection("p21ItemMappings", {
  validator: { $jsonSchema: {
    bsonType: "object",
    required: [...envelopeRequired, "p21ItemId", "matchStatus", "freshness",
               "isSpecialPriced", "lastSyncedAt", "syncSource"],
    properties: {
      ...envelope,
      _id: { bsonType: "objectId" },
      p21ItemId: { bsonType: "string" },
      p21Description: { bsonType: ["string", "null"] },
      mfrPartNumber: { bsonType: ["string", "null"] },
      catalogItemId: { bsonType: ["objectId", "null"] },
      vendorId: { bsonType: ["objectId", "null"] },
      matchStatus: { enum: ["matched", "unmatched", "semiItem", "manualOverride"] },
      matchConfidence: { bsonType: ["double", "null"], minimum: 0, maximum: 1 },
      lastPoPrice: { bsonType: ["double", "null"], minimum: 0 },
      lastPoDate: { bsonType: ["date", "null"] },
      lastSoldDate: { bsonType: ["date", "null"] },
      freshness: { enum: ["fresh", "aging", "stale", "discard", "unknown"] },
      isSpecialPriced: { bsonType: "bool" },
      lastSyncedAt: { bsonType: "date" },
      syncSource: { enum: ["p21", "manual"] },
      unitOfMeasure: { enum: ["EA", "LF", "SF", "PR", "SET", null] }
    }
  } }
});
db.p21ItemMappings.createIndex({ orgId: 1, p21ItemId: 1 }, { unique: true });
db.p21ItemMappings.createIndex({ orgId: 1, mfrPartNumber: 1 },
  { partialFilterExpression: { mfrPartNumber: { $type: "string" } } });
db.p21ItemMappings.createIndex({ orgId: 1, catalogItemId: 1, freshness: 1 },
  { partialFilterExpression: { catalogItemId: { $type: "objectId" } } });
db.p21ItemMappings.createIndex({ orgId: 1, matchStatus: 1, lastSyncedAt: -1 });
```

**Notes:** There is deliberately **no** field for P21's supplier-list or supplier-cost values. Matrix 6.2 (D19) instructs that they must not be trusted; the cleanest way to guarantee they are never used is to give them nowhere to live. If a future sync needs them for diagnostics, that should be an explicit, reviewed schema change.

`matchStatus: "semiItem"` is a first-class value rather than a variant of `unmatched` because NR-10 identifies semi/custom items as a *structurally* unmatchable class, not a backlog item — they will never reconcile, and the reconciliation worklist should not keep re-presenting them.

---

### 3.18 `frameDepths`

**Purpose:** Frame throat/depth by wall construction — Open Item 6, answered in the 14 Jul session with five standard sizes plus a custom entry option (Matrix 7.0, I26).

**`_id` strategy:** `ObjectId`; unique business key `{ orgId, code }`.

| Field | Type | Required | Default | Description | Source |
|---|---|---|---|---|---|
| `_id` | objectId | yes | auto | | — |
| `code` | string | yes | — | `5_5_8`, `5_3_4`, `5_7_8`, `7_3_4`, `8_1_4`, `CUSTOM`, `ADJUSTABLE` | Matrix 7.0 (I26) |
| `displayValue` | string | yes | — | `5-5/8"`, `5-3/4"`, `5-7/8"`, `7-3/4"`, `8-1/4"` | Matrix 7.0 (I26) |
| `decimalInches` | double | no | null | `5.625`, `5.75`, `5.875`, `7.75`, `8.25`; null for CUSTOM/ADJUSTABLE | Matrix 7.0 (I26) |
| `wallType` | string (enum) | yes | — | `drywallHalfInch` \| `masonry` \| `drywall` \| `woodFrame` \| `metalStud6InPlus5_8Drywall` \| `custom` \| `adjustable` | Matrix 7.0 (I26) |
| `wallDescription` | string | no | null | e.g. `half-inch drywall, common at McDonald's` | Matrix 7.0 (I26) |
| `isCustomEntry` | bool | yes | `false` | `true` for the manual-entry option | Matrix 7.0 (I26) |
| `isAdjustable` | bool | yes | `false` | Adjustable frames also exist | Matrix 7.0 (I26) |
| `sortOrder` | int | no | `100` | Pick-list order | Matrix 7.0 (I26) |
| `active` | bool | yes | `true` | | §4.2 |
| *envelope* | — | — | — | | §4.2 |

**Relationships:** referenced by `openings.frameDepthCode` and `catalogItems.frameDepthCode` **by `code`, not ObjectId** — see notes.

**Indexes:**
- `{ orgId: 1, code: 1 }` — **unique**.
- `{ orgId: 1, wallType: 1, active: 1 }` — auto-selection of depth from an extracted wall type.

```javascript
db.createCollection("frameDepths", {
  validator: { $jsonSchema: {
    bsonType: "object",
    required: [...envelopeRequired, "code", "displayValue", "wallType",
               "isCustomEntry", "isAdjustable", "active"],
    properties: {
      ...envelope,
      _id: { bsonType: "objectId" },
      code: { bsonType: "string", pattern: "^[A-Z0-9_]+$" },
      displayValue: { bsonType: "string" },
      decimalInches: { bsonType: ["double", "null"], exclusiveMinimum: 0 },
      wallType: { enum: ["drywallHalfInch", "masonry", "drywall", "woodFrame",
                         "metalStud6InPlus5_8Drywall", "custom", "adjustable"] },
      wallDescription: { bsonType: ["string", "null"] },
      isCustomEntry: { bsonType: "bool" },
      isAdjustable: { bsonType: "bool" },
      sortOrder: { bsonType: "int" },
      active: { bsonType: "bool" }
    }
  } }
});
db.frameDepths.createIndex({ orgId: 1, code: 1 }, { unique: true });
db.frameDepths.createIndex({ orgId: 1, wallType: 1, active: 1 });
```

**Reference-by-code justification:** frame depths, finish codes and similar small stable lookups are referenced by their string `code` rather than by `ObjectId` throughout the schema. The set is tiny (~7 rows, the workbook caps it at *"~10 sizes max"*), the codes are human-meaningful and stable, and this means an `estimateLines` document read in isolation is self-describing — `"5_5_8"` needs no join to be understood by a support engineer looking at raw documents. The referential integrity cost is real but small and is covered by the enum-style `pattern` validation plus an application-level check on write.

---

### 3.19 `finishCodes`

**Purpose:** The dual finish-nomenclature interpreter (NR-3). Matrix 7.5 (I31) records the specific traps: **US26D = 626**, **619 = US15**, and **US19 and 26D are different satins** — so a naive string comparison will both miss true matches and create false ones. Some finishes are premium and carry lead time.

**`_id` strategy:** `ObjectId`; unique business key `{ orgId, code }`.

| Field | Type | Required | Default | Description | Source |
|---|---|---|---|---|---|
| `_id` | objectId | yes | auto | | — |
| `code` | string | yes | — | Canonical code, BHMA-numeric preferred: `626`, `630`, `615` | Matrix 7.5 (I31) |
| `usEquivalent` | string | no | null | `US26D` for `626`, `US15` for `619` | Matrix 7.5 (I31); NR-3 |
| `bhmaCode` | string | no | null | Explicit BHMA number | Matrix 7.5 (D31) |
| `aliases` | array<string> | yes | `[]` | Every spelling seen in specs: `US26D`, `26D`, `626` | NR-3 |
| `description` | string | yes | — | e.g. `Satin chrome` | Matrix 7.5 (D31) |
| `notEquivalentTo` | array<string> | no | `[]` | **Explicit non-equivalence.** `US19` lists `26D` here | Matrix 7.5 (I31) |
| `isPremium` | bool | yes | `false` | Premium finishes may need an adder | Matrix 7.5 (I31); NR-4 |
| `leadTimeDays` | int | no | null | | Matrix 7.5 (I31) |
| `active` | bool | yes | `true` | | §4.2 |
| *envelope* | — | — | — | | §4.2 |

**Relationships:** referenced by `code` from `catalogItems.defaultFinishCode` / `.availableFinishCodes[]`, `hardwareSets.finishCode` and `items[].finishCode`, `openings.finishCode`, `estimateLines.finishCode`, `priceBookEntries.finishCode`.

**Indexes:**
- `{ orgId: 1, code: 1 }` — **unique**.
- `{ orgId: 1, aliases: 1 }` — **multikey**. This is the interpreter: a spec string in any nomenclature resolves to a canonical code in one lookup (NR-3).
- `{ orgId: 1, isPremium: 1 }` — **partial** (`isPremium: true`) — flags lines that may need a premium-finish adder (NR-4).

```javascript
db.createCollection("finishCodes", {
  validator: { $jsonSchema: {
    bsonType: "object",
    required: [...envelopeRequired, "code", "aliases", "description", "isPremium", "active"],
    properties: {
      ...envelope,
      _id: { bsonType: "objectId" },
      code: { bsonType: "string" },
      usEquivalent: { bsonType: ["string", "null"] },
      bhmaCode: { bsonType: ["string", "null"] },
      aliases: { bsonType: "array", items: { bsonType: "string" } },
      description: { bsonType: "string" },
      notEquivalentTo: { bsonType: "array", items: { bsonType: "string" } },
      isPremium: { bsonType: "bool" },
      leadTimeDays: { bsonType: ["int", "null"], minimum: 0 },
      active: { bsonType: "bool" }
    }
  } }
});
db.finishCodes.createIndex({ orgId: 1, code: 1 }, { unique: true });
db.finishCodes.createIndex({ orgId: 1, aliases: 1 });
db.finishCodes.createIndex({ orgId: 1, isPremium: 1 },
  { partialFilterExpression: { isPremium: true } });
```

**Notes:** `notEquivalentTo` is the unusual field here and it earns its place. Most alias systems only encode what *is* the same; Matrix 7.5 (I31) specifically warns that US19 and 26D are different satins, which is exactly the kind of near-miss an automated matcher would get wrong. Storing the negative assertion lets the matcher refuse a substitution rather than quietly making it.

---

### 3.20 `frpConstants`

**Purpose:** The geometry-to-quantity conversion constants for FRP wall panels. Flow Phase 3b records that Vu360 gives **geometry only** — perimeter (LF), inside corners, outside corners — and the estimator converts to material quantities by hand. FR-12 and Open Item 5 ask to automate that conversion; the constants themselves (panel size, waste %, trim/stick lengths, adhesive coverage, opening handling) are **still to be provided**.

**`_id` strategy:** `ObjectId`; unique business key `{ orgId, vendorId, constantKey, effectiveFrom }`.

| Field | Type | Required | Default | Description | Source |
|---|---|---|---|---|---|
| `_id` | objectId | yes | auto | | — |
| `constantKey` | string (enum) | yes | — | `panelWidthIn` \| `panelHeightIn` \| `wastePercent` \| `trimStickLengthFt` \| `adhesiveCoverageSfPerUnit` \| `insideCornerTrimPerCorner` \| `outsideCornerTrimPerCorner` \| `openingDeductionRule` | Open 5 (B8) |
| `vendorId` | objectId | no | null | → `vendors`: Marlite, NUDO, Midwest/East Coast FRP | Scope tab G9 |
| `numericValue` | double | no | null | **Null until CBC provides the constants** | Open 5 (F8, Partial) |
| `textValue` | string | no | null | For rule-shaped constants (opening handling) | Open 5 (B8) |
| `unit` | string | no | null | `in`, `ft`, `sf`, `%` | Open 5 |
| `dataStatus` | string (enum) | yes | `pending` | `pending` \| `confirmed` | Open 5 (F8) |
| `effectiveFrom` / `effectiveTo` | date | yes / no | — / null | | §4.6 |
| *envelope* | — | — | — | | §4.2 |

**Relationships:** `vendorId` → `vendors` (N:1); consumed by `takeoffs` when converting FRP geometry to quantities.

**Indexes:**
- `{ orgId: 1, vendorId: 1, constantKey: 1, effectiveFrom: -1 }` — **unique**. Constant resolution.
- `{ orgId: 1, dataStatus: 1 }` — surfaces the outstanding data (Open 5).

```javascript
db.createCollection("frpConstants", {
  validator: { $jsonSchema: {
    bsonType: "object",
    required: [...envelopeRequired, "constantKey", "dataStatus", "effectiveFrom"],
    properties: {
      ...envelope,
      _id: { bsonType: "objectId" },
      constantKey: { enum: ["panelWidthIn", "panelHeightIn", "wastePercent", "trimStickLengthFt",
                            "adhesiveCoverageSfPerUnit", "insideCornerTrimPerCorner",
                            "outsideCornerTrimPerCorner", "openingDeductionRule"] },
      vendorId: { bsonType: ["objectId", "null"] },
      numericValue: { bsonType: ["double", "null"] },
      textValue: { bsonType: ["string", "null"] },
      unit: { bsonType: ["string", "null"] },
      dataStatus: { enum: ["pending", "confirmed"] },
      effectiveFrom: { bsonType: "date" },
      effectiveTo: { bsonType: ["date", "null"] }
    }
  } }
});
db.frpConstants.createIndex({ orgId: 1, vendorId: 1, constantKey: 1, effectiveFrom: -1 }, { unique: true });
db.frpConstants.createIndex({ orgId: 1, dataStatus: 1 });
```

**Notes:** This collection is a key-value store rather than a single wide document because the constants arrive piecemeal (Open Item 5 is `Partial`), are vendor-specific, and need independent effective dating — panel sizes change with product lines, waste percentages change with estimator experience. Until `dataStatus` flips to `confirmed`, FR-12's automated conversion stays disabled and the estimator continues the Vu360-plus-calculator workflow, with the take-off geometry still captured in `takeoffs` so no work is lost when the constants land.

---

### 3.21 `bidRequests`

**Purpose:** The intake record and the root of everything job-specific. Flow Phase 0 and FR-1: a bid request arrives **mostly by email** with the job workbook plus plans/RFP attached, and **sometimes by phone** — which is why NR-5 adds a "create new bid request" option. Requests come from the internal initiator in the queue (Kellan/Matt/Rebecca/Tina), never from the architect.

**`_id` strategy:** `ObjectId`, plus a human-facing `bidNumber` unique per org for estimator reference.

| Field | Type | Required | Default | Description | Source |
|---|---|---|---|---|---|
| `_id` | objectId | yes | auto | | — |
| `bidNumber` | string | yes | — | Human reference, e.g. `LA0701` | Flow Phase 1 (C5) |
| `projectName` | string | yes | — | | Flow Phase 1 (C5) |
| `projectLocation` | object | no | null | `{ city, state, country }` — drives tax resolution | Matrix 2.4 (I8) |
| `customerId` | objectId | yes | — | → `customers` (the GC / bill-to) | Matrix 2.4 (I8) |
| `brandProgramId` | objectId | no | null | → `brandPrograms` | Q11 |
| `architectName` | string | no | null | Contact context only; never the bill-to | Matrix 2.4 (I8) |
| `initiatorUserId` | objectId | yes | — | → `users`; the salesperson in the queue. The proposal returns to **this person**, not a group alias | FR-10 (I47) |
| `assignedEstimatorId` | objectId | no | null | → `users` | Matrix 8.1 (I36) |
| `intakeChannel` | string (enum) | yes | — | `email` \| `phone` \| `manual` | Flow C4 (G4); NR-5 |
| `receivedAt` | date | yes | — | | Flow Phase 0 |
| `bidDueDate` | date | no | null | Noted at intake | Flow C4 |
| `estimationMode` | string (enum) | no | null | `templated` \| `oneOff` | Matrix 3.0 (D10, I10) |
| `scopeCategories` | array<objectId> | no | `[]` | → `productTypes` identified in Phase 2 scoping | Flow C6 |
| `csiDivisionsInScope` | array<string> | no | `[]` | `08`, `10` | Flow C6 |
| `hasAlternates` | bool | yes | `false` | Alternates noted at intake | Flow C4; Matrix 4.1 |
| `alternateCountNoted` | int | no | null | | Flow C4 |
| `status` | string (enum) | yes | `received` | See state machine below | Flow Phases 0–6 |
| `statusHistory` | array<object> | yes | `[]` | `{ from, to, at, by, note }` — the timestamped record Q3 relies on for future KPI computation | Q3; §4.5 |
| `sourceEmailMessageId` | string | no | null | Outlook message id for traceability | Flow D4 |
| `notes` | string | no | null | | Flow G4 |
| *soft delete* | — | — | — | Per Q13 | §4.3 |
| *envelope* | — | — | — | | §4.2 |

**State machine** (`status`) — derived from Flow Phases 0–6:

| From | To | Trigger | Source |
|---|---|---|---|
| — | `received` | Intake (email, phone, or manual) | Flow Phase 0 |
| `received` | `fileSetup` | Job workbook created / estimate opened | Flow Phase 1 |
| `fileSetup` | `specScoping` | Div 08/10 scope identification begins | Flow Phase 2 |
| `specScoping` | `takeoff` | Drawing review & take-offs begin (incl. FRP 3b) | Flow Phase 3, 3b |
| `takeoff` | `pricing` | Populate & price the quote | Flow Phase 4 |
| `pricing` | `review` | Draft complete, estimator review | Flow Phase 5; FR-9 |
| `review` | `pricing` | Rework after review | FR-9 |
| `review` | `approved` | Explicit estimator approval — **human only** | NFR-1 |
| `approved` | `delivered` | Proposal exported and sent to initiator | Flow Phase 6; FR-10 |
| `delivered` | `pricing` | Addendum received → new version | Matrix 4.1; Flow 4b |
| any active | `onHold` | Awaiting vendor RFQ or RFI answer | Matrix 6.6; Flow Phase 5 |
| `onHold` | previous | Blocker resolved | — |
| any active | `cancelled` / `noBid` | **Assumed** — see §6.2 | Assumption A-17 |

**Relationships:** `customerId`, `brandProgramId`, `initiatorUserId`, `assignedEstimatorId` (all N:1). Parent of `documents`, `openings`, `takeoffs`, `vendorRfqs`, `rfis`, and `estimates` (1:N / 1:1).

**Indexes:**
- `{ orgId: 1, bidNumber: 1 }` — **unique**.
- `{ orgId: 1, status: 1, bidDueDate: 1 }` — the estimator work queue, due-date ordered. The single highest-frequency read in the app.
- `{ orgId: 1, assignedEstimatorId: 1, status: 1 }` — "my bids".
- `{ orgId: 1, customerId: 1, receivedAt: -1 }` and `{ orgId: 1, brandProgramId: 1, receivedAt: -1 }` — serve FR-11's reuse lookup ("closest prior quote for the same brand / architect / GC").
- `{ orgId: 1, initiatorUserId: 1, status: 1 }` — the sales-side view of the queue (FR-10, I47).
- `{ orgId: 1, isDeleted: 1, receivedAt: -1 }` — general listing.

```javascript
db.createCollection("bidRequests", {
  validator: { $jsonSchema: {
    bsonType: "object",
    required: [...envelopeRequired, "bidNumber", "projectName", "customerId",
               "initiatorUserId", "intakeChannel", "receivedAt", "hasAlternates",
               "status", "statusHistory", "isDeleted"],
    properties: {
      ...envelope, ...softDelete,
      _id: { bsonType: "objectId" },
      bidNumber: { bsonType: "string" },
      projectName: { bsonType: "string" },
      projectLocation: { bsonType: ["object", "null"], properties: {
        city: { bsonType: "string" }, state: { bsonType: "string" },
        country: { enum: ["US", "CA"] } } },
      customerId: { bsonType: "objectId" },
      brandProgramId: { bsonType: ["objectId", "null"] },
      architectName: { bsonType: ["string", "null"] },
      initiatorUserId: { bsonType: "objectId" },
      assignedEstimatorId: { bsonType: ["objectId", "null"] },
      intakeChannel: { enum: ["email", "phone", "manual"] },
      receivedAt: { bsonType: "date" },
      bidDueDate: { bsonType: ["date", "null"] },
      estimationMode: { enum: ["templated", "oneOff", null] },
      scopeCategories: { bsonType: "array", items: { bsonType: "objectId" } },
      csiDivisionsInScope: { bsonType: "array", items: { enum: ["08", "10", "06", "other"] } },
      hasAlternates: { bsonType: "bool" },
      alternateCountNoted: { bsonType: ["int", "null"], minimum: 0 },
      status: { enum: ["received", "fileSetup", "specScoping", "takeoff", "pricing",
                       "review", "approved", "delivered", "onHold", "cancelled", "noBid"] },
      statusHistory: statusHistory,
      sourceEmailMessageId: { bsonType: ["string", "null"] },
      notes: { bsonType: ["string", "null"] }
    }
  } }
});
db.bidRequests.createIndex({ orgId: 1, bidNumber: 1 }, { unique: true });
db.bidRequests.createIndex({ orgId: 1, status: 1, bidDueDate: 1 });
db.bidRequests.createIndex({ orgId: 1, assignedEstimatorId: 1, status: 1 });
db.bidRequests.createIndex({ orgId: 1, customerId: 1, receivedAt: -1 });
db.bidRequests.createIndex({ orgId: 1, brandProgramId: 1, receivedAt: -1 });
db.bidRequests.createIndex({ orgId: 1, initiatorUserId: 1, status: 1 });
db.bidRequests.createIndex({ orgId: 1, isDeleted: 1, receivedAt: -1 });
```

**Notes:** `statusHistory` is the collection's most consequential field and it exists because of Q3. With every transition timestamped and attributed, turnaround time (received → delivered), time-in-phase, and hit rate become aggregation pipelines over data already being written — so when the Business Case & Metrics sheet eventually materialises, no schema change is needed to compute the KPIs it names.

`intakeChannel: "phone"` and `"manual"` exist specifically to satisfy NR-5. Without them, a phoned-in bid would have to be faked as an email, and the intake-channel mix — useful operational data — would be lost.

---

### 3.22 `documents`

**Purpose:** Every file attached to a bid — plans, spec book, RFP, quote request, addenda — plus reference PDFs like vendor price books and multiplier sheets. Two workbook facts drive the design: a bid arrives as **one combined PDF or several separate PDFs** (Matrix 8.0, I35), and bid sets are digital but may be **native or scanned** (Assumptions row 7), so OCR state must be tracked per page.

**`_id` strategy:** `ObjectId`.

| Field | Type | Required | Default | Description | Source |
|---|---|---|---|---|---|
| `_id` | objectId | yes | auto | | — |
| `bidRequestId` | objectId | no | null | → `bidRequests`; null for reference docs (price books) | Matrix 8.0 |
| `docType` | string (enum) | yes | — | `plans` \| `specBook` \| `rfp` \| `quoteRequest` \| `addendum` \| `jobWorkbook` \| `priceBook` \| `multiplierSheet` \| `vendorQuote` \| `other` | Flow C4; Matrix 6.3 |
| `fileName` | string | yes | — | | Q9 |
| `storageUri` | string | yes | — | External object-storage URI (S3 or equivalent) | Q9 |
| `checksum` | string | yes | — | SHA-256; deduplication and tamper evidence | Q9 |
| `byteSize` | long | yes | — | `long`, not `int` — bid sets exceed 2 GB in aggregate and int overflows at ~2.1 GB | Q9 |
| `mimeType` | string | yes | `application/pdf` | | Assumptions row 7 |
| `pageCount` | int | no | null | | Q9 |
| `isCombinedSet` | bool | yes | `false` | One combined PDF vs one of several | Matrix 8.0 (I35) |
| `sourceType` | string (enum) | yes | — | `nativeDigital` \| `scanned` \| `mixed` | Assumptions row 7 (C10) |
| `ocrStatus` | string (enum) | yes | `notRequired` | `notRequired` \| `pending` \| `complete` \| `partial` \| `failed` | Assumptions row 7 |
| `pages` | array<object> | no | `[]` | Embedded page index — see sub-table | NFR-3 (D57) |
| `addendumNumber` | string | no | null | Populated when `docType = addendum` | Matrix 4.1 (D14) |
| `supersedesDocumentId` | objectId | no | null | → `documents`; addendum revision chain | Matrix 4.1 (D14) |
| `receivedAt` | date | yes | — | | Flow Phase 0 |
| `uploadedBy` | objectId | no | null | → `users` | §4.2 |
| *envelope* | — | — | — | | §4.2 |

**Embedded `pages[]` sub-document:**

| Field | Type | Required | Description | Source |
|---|---|---|---|---|
| `pageNumber` | int | yes | 1-based | NFR-3 |
| `sheetLabel` | string | no | Drawing sheet number, e.g. `A8.1`, `A3.2` | Flow Phase 3 |
| `contentType` | string (enum) | no | `doorSchedule` \| `hardwareSchedule` \| `floorPlan` \| `elevation` \| `specText` \| `other` | Flow C6, C7 |
| `ocrStatus` | string (enum) | yes | `notRequired` \| `complete` \| `failed` — per-page, because graphic sheets frequently fail while text sheets succeed | Assumptions row 7 |
| `textExtracted` | bool | yes | Whether a usable text layer exists | Assumptions row 7 |

**Relationships:** `bidRequestId` → `bidRequests` (N:1); `supersedesDocumentId` → `documents` (self, N:1); referenced by `openings.sourceRef.documentId`, `priceBooks.sourceDocumentId`, `vendorTiers.sourceDocumentId`, `estimateVersions.triggeringAddendumDocumentId`, `vendorRfqs.responseDocumentId`.

**Indexes:**
- `{ orgId: 1, bidRequestId: 1, docType: 1 }` — the bid's document list, grouped.
- `{ orgId: 1, checksum: 1 }` — **unique**. Prevents the same PDF being ingested twice when a combined set and a separate file overlap.
- `{ orgId: 1, docType: 1, receivedAt: -1 }` — **partial** (`docType: "addendum"`) — the addendum feed (Flow 4b).
- `{ orgId: 1, ocrStatus: 1 }` — **partial** (`ocrStatus: { $in: ["pending","failed","partial"] }`) — the extraction worklist; a failed graphic sheet is exactly the "unparsed content" FR-8 requires be flagged for review.

```javascript
db.createCollection("documents", {
  validator: { $jsonSchema: {
    bsonType: "object",
    required: [...envelopeRequired, "docType", "fileName", "storageUri", "checksum",
               "byteSize", "mimeType", "isCombinedSet", "sourceType", "ocrStatus", "receivedAt"],
    properties: {
      ...envelope,
      _id: { bsonType: "objectId" },
      bidRequestId: { bsonType: ["objectId", "null"] },
      docType: { enum: ["plans", "specBook", "rfp", "quoteRequest", "addendum", "jobWorkbook",
                        "priceBook", "multiplierSheet", "vendorQuote", "other"] },
      fileName: { bsonType: "string" },
      storageUri: { bsonType: "string" },
      checksum: { bsonType: "string" },
      byteSize: { bsonType: "long", minimum: 0 },
      mimeType: { bsonType: "string" },
      pageCount: { bsonType: ["int", "null"], minimum: 0 },
      isCombinedSet: { bsonType: "bool" },
      sourceType: { enum: ["nativeDigital", "scanned", "mixed"] },
      ocrStatus: { enum: ["notRequired", "pending", "complete", "partial", "failed"] },
      addendumNumber: { bsonType: ["string", "null"] },
      supersedesDocumentId: { bsonType: ["objectId", "null"] },
      receivedAt: { bsonType: "date" },
      uploadedBy: { bsonType: ["objectId", "null"] },
      pages: { bsonType: "array", items: {
        bsonType: "object",
        required: ["pageNumber", "ocrStatus", "textExtracted"],
        properties: {
          pageNumber: { bsonType: "int", minimum: 1 },
          sheetLabel: { bsonType: ["string", "null"] },
          contentType: { enum: ["doorSchedule", "hardwareSchedule", "floorPlan",
                                "elevation", "specText", "other", null] },
          ocrStatus: { enum: ["notRequired", "complete", "failed"] },
          textExtracted: { bsonType: "bool" }
        } } }
    }
  } }
});
db.documents.createIndex({ orgId: 1, bidRequestId: 1, docType: 1 });
db.documents.createIndex({ orgId: 1, checksum: 1 }, { unique: true });
db.documents.createIndex({ orgId: 1, docType: 1, receivedAt: -1 },
  { partialFilterExpression: { docType: "addendum" } });
db.documents.createIndex({ orgId: 1, ocrStatus: 1 },
  { partialFilterExpression: { ocrStatus: { $in: ["pending", "failed", "partial"] } } });
```

**Notes:** Binaries live in external object storage per Q9; this collection holds metadata only. `pages[]` is embedded because it is bounded by page count and always read with its parent, and because it is the *citation target* for NFR-3 — `openings.sourceRef` points at `{ documentId, pageNumber }`, and having the page index in the same document means rendering "this line came from sheet A8.1" costs one read, not two.

Per-page `ocrStatus` matters more than it might appear. Bid sets routinely contain graphic sheets that yield no text layer while the rest of the set extracts cleanly, and a document-level status alone would either mark the whole set failed or hide the gap. Per-page status makes the gap visible and reviewable, which is what NFR-2's *"never silently guessed"* requires.

### `documentPages` (implemented)

**Purpose:** MinerU parse output — one document per PDF page — so agents and the sheet viewer can query text blocks with bboxes without re-reading page images. Owned by intake (`cbc.modules.intake`); deleted with the parent document.

| Field | Type | Notes |
|---|---|---|
| `projectId` | ObjectId | Bid / project |
| `documentId` | ObjectId | → `documents` |
| `contentSha` | string | Upload content hash; retries skip windows already stored |
| `page` | int | 1-based |
| `pageSize` | `{ width, height }` | Display frame (rotated page rect) |
| `blocks` | array | `{ n, type, text, bbox, lines?: [{bbox,text}], html? }`; discarded blocks kept as `type: discarded` |
| `verified` | float \| null | Share of text blocks ≥50% covered by pdf text-layer boxes; `null` if no text layer |
| `parser` | object | `{ name, version, backend, effort }` used for this parse |
| `parsedAt` | date | |

**Indexes:** unique `(documentId, page)`; `(projectId, page)`; text on `blocks.text`.

### `catalogPages` (implemented)

**Purpose:** MinerU parse output for vendor price books — one document per PDF page — so `match_and_price` can query blocks with bboxes via **catalog-docs** (mirror of bid `documentPages` / bid-docs). Owned by catalog; purged with `delete_catalog`.

| Field | Type | Notes |
|---|---|---|
| `priceBookId` | ObjectId | → `priceBooks` |
| `catalogId` | string | Stable stem id (same as pageIndex) |
| `vendor` | string | |
| `filename` / `filePath` | string | Path for pdf-tools crop |
| `contentSha` | string | Upload hash; retries skip windows already stored |
| `page` | int | 1-based |
| `pageSize` | `{ width, height }` | |
| `blocks` | array | Same shape as `documentPages.blocks` |
| `verified` | float \| null | Bbox coverage vs PDF text layer |
| `parser` | object | MinerU meta |
| `parsedAt` | date | |

**Indexes:** unique `(priceBookId, page)`; `(catalogId, page)`; `(vendor, page)`; text on `blocks.text`.

### `multiplierPages` (implemented)

**Purpose:** MinerU blocks for multiplier / special-net PDFs (`parse_multiplier`). Structured `referenceData` multipliers remain calc SoT; this collection is for sheet evidence.

| Field | Type | Notes |
|---|---|---|
| `sheetId` | string | Stem id |
| `family` / `vendor` | string | |
| `priceBookId` | ObjectId \| null | When uploaded as a price book |
| `filename` / `filePath` | string | |
| `contentSha`, `page`, `pageSize`, `blocks`, `verified`, `parser`, `parsedAt` | | Same as catalogPages |

**Indexes:** unique `(sheetId, page)`; `(family, page)`; text on `blocks.text`.

---

### 3.23 `openings`

**Purpose:** One door/opening extracted from the door schedule — FR-2's core deliverable: door number, size, handing, finish, **fire rating**, hardware-group/set callouts, and any alternate designation. This is the object the matcher (FR-4) works against and the object the proposal groups by (FR-7).

**`_id` strategy:** `ObjectId`; unique business key `{ orgId, bidRequestId, doorNumber }`.

| Field | Type | Required | Default | Description | Source |
|---|---|---|---|---|---|
| `_id` | objectId | yes | auto | | — |
| `bidRequestId` | objectId | yes | — | → `bidRequests` | FR-2 |
| `doorNumber` | string | yes | — | Schedule door mark, e.g. `101`, `A-2` | FR-2 (C39) |
| `sizeCode` | string | no | null | 4-digit shorthand: `3070`, `3670` | Matrix 7.1 (D27, I27) |
| `widthFeet` / `widthInches` | int | no | null | Parsed from `sizeCode`: `3070` → 3'-0" | Matrix 7.1 (I27) |
| `heightFeet` / `heightInches` | int | no | null | `3070` → 7'-0" | Matrix 7.1 (I27) |
| `thicknessIn` | double | no | null | | FR-2 |
| `doorMaterial` | string (enum) | no | null | `hollowMetal` \| `wood` \| `frp` \| `other` | Matrix 2.1 (I5) |
| `frameType` | string (enum) | no | null | `hmWelded` \| `hmKnockDown` \| `other` — "loaded and knocked-down" | Matrix 2.1 (I5) |
| `frameDepthCode` | string | no | null | → `frameDepths.code` | Matrix 7.0 (I26) |
| `wallType` | string (enum) | no | null | Drives frame-depth derivation | Matrix 7.0 (D26) |
| `handing` | string (enum) | no | null | `LH` \| `RH` \| `LHR` \| `RHR` | Matrix 7.4 (D30, I30) |
| `swing` | string (enum) | no | null | `in` \| `out` | Matrix 7.4 (D30) |
| `finishCode` | string | no | null | → `finishCodes.code` | Matrix 7.5 (I31) |
| `fireRating` | string (enum) | yes | `none` | `20` \| `45` \| `60` \| `90` \| `none` | Matrix 7.3 (D29); Q5 |
| `fireRatingSource` | string (enum) | no | null | `doorSchedule` \| `frameSchedule` \| `notes` \| `specText` \| `estimatorEntered` \| `unknown` — **which of these actually occur is Open Item 9** | Matrix 7.3 (G29); Q5 |
| `ulLabelRequired` | bool | yes | `false` | Derived: `true` when `fireRating != "none"` | Matrix 7.3 (D29) |
| `ratingConflict` | bool | yes | `false` | **`true` when the opening carries a fire rating but the matched hardware/frame combination is not UL-labelled for it.** Computed at match time | Q5 |
| `ratingMissing` | bool | yes | `false` | Rating could not be read from the set — flagged, never defaulted | FR-8 (C45); Q5 |
| `hardwareSetCallout` | string | no | null | Verbatim spec callout, e.g. `HW-3` | Matrix 7.7 (D33) |
| `hardwareSetId` | objectId | no | null | → `hardwareSets` (spec-extracted or matched library set) | Matrix 7.7 (I33) |
| `keying` | object | no | null | `{ coreType, keyway, notes }` — IC small/large format, storeroom w/ IC | Matrix 7.6 (I32) |
| `alternateDesignation` | string | no | null | Verbatim alternate marking from the schedule | FR-2 (C39); Matrix 4.1 |
| `quantity` | int | yes | `1` | Openings of this exact configuration | Matrix 5.0 (D16) |
| `sourceRef` | object | no | null | `{ documentId, pageNumber, sheetLabel, rowRef }` — NFR-3 traceability | NFR-3 (D57) |
| `matchCandidates` | array<object> | no | `[]` | Top-N candidates for review — see sub-table | FR-4, FR-8 |
| `extractionConfidence` | double | no | null | 0–1 for the extraction itself | FR-8 (C45) |
| `reviewStatus` | string (enum) | yes | `pending` | `pending` \| `confirmed` \| `corrected` \| `flagged` | FR-9 |
| `unparsedNote` | string | no | null | What could not be read from the set | FR-8 (C45) |
| *envelope* | — | — | — | | §4.2 |

**Embedded `matchCandidates[]` sub-document:**

| Field | Type | Required | Description | Source |
|---|---|---|---|---|
| `catalogItemId` | objectId | no | → `catalogItems` | FR-4 |
| `hardwareSetId` | objectId | no | → `hardwareSets` | FR-4 |
| `confidence` | double | yes | 0–1 | FR-8 (C45) |
| `rank` | int | yes | 1..N — the "here are 3 close matches" behaviour | FR-8 (I45) |
| `matchedOn` | array<string> | no | Which attributes matched: `rating`, `handing`, `finish`, `partNumber`, `size` | FR-4 (C41) |
| `failedOn` | array<string> | no | Which attributes did **not** match | FR-8; Q5 |
| `selected` | bool | yes | Estimator's choice | FR-9 |

**Relationships:** `bidRequestId` → `bidRequests` (N:1); `hardwareSetId` → `hardwareSets` (N:1); `sourceRef.documentId` → `documents` (N:1); referenced by `estimateLines.openingId` and `estimateVersions.lineGroups[].openingId` (1:N).

**Indexes:**
- `{ orgId: 1, bidRequestId: 1, doorNumber: 1 }` — **unique**. Extraction idempotency and the door-grouped proposal order (FR-7).
- `{ orgId: 1, bidRequestId: 1, reviewStatus: 1 }` — the review worklist (FR-9).
- `{ orgId: 1, ratingConflict: 1 }` — **partial** (`ratingConflict: true`). The defect query: *an unrated match on a rated opening is a defect* (Matrix 7.3). This index exists so that check is cheap enough to run on every draft.
- `{ orgId: 1, ratingMissing: 1 }` — **partial** (`ratingMissing: true`). FR-8's "flag missing ratings".
- `{ orgId: 1, bidRequestId: 1, hardwareSetCallout: 1 }` — groups openings by HW set for set-level pricing.

```javascript
db.createCollection("openings", {
  validator: { $jsonSchema: {
    bsonType: "object",
    required: [...envelopeRequired, "bidRequestId", "doorNumber", "fireRating",
               "ulLabelRequired", "ratingConflict", "ratingMissing", "quantity", "reviewStatus"],
    properties: {
      ...envelope,
      _id: { bsonType: "objectId" },
      bidRequestId: { bsonType: "objectId" },
      doorNumber: { bsonType: "string" },
      sizeCode: { bsonType: ["string", "null"], pattern: "^[0-9]{4}$" },
      widthFeet: { bsonType: ["int", "null"], minimum: 0 },
      widthInches: { bsonType: ["int", "null"], minimum: 0, maximum: 11 },
      heightFeet: { bsonType: ["int", "null"], minimum: 0 },
      heightInches: { bsonType: ["int", "null"], minimum: 0, maximum: 11 },
      thicknessIn: { bsonType: ["double", "null"], minimum: 0 },
      doorMaterial: { enum: ["hollowMetal", "wood", "frp", "other", null] },
      frameType: { enum: ["hmWelded", "hmKnockDown", "other", null] },
      frameDepthCode: { bsonType: ["string", "null"] },
      wallType: { enum: ["drywallHalfInch", "masonry", "drywall", "woodFrame",
                         "metalStud6InPlus5_8Drywall", "custom", "adjustable", null] },
      handing: { enum: ["LH", "RH", "LHR", "RHR", null] },
      swing: { enum: ["in", "out", null] },
      finishCode: { bsonType: ["string", "null"] },
      fireRating: { enum: ["20", "45", "60", "90", "none"] },
      fireRatingSource: { enum: ["doorSchedule", "frameSchedule", "notes", "specText",
                                 "estimatorEntered", "unknown", null] },
      ulLabelRequired: { bsonType: "bool" },
      ratingConflict: { bsonType: "bool" },
      ratingMissing: { bsonType: "bool" },
      hardwareSetCallout: { bsonType: ["string", "null"] },
      hardwareSetId: { bsonType: ["objectId", "null"] },
      keying: { bsonType: ["object", "null"], properties: {
        coreType: { enum: ["icSmallFormat", "icLargeFormat", "conventional", "none", null] },
        keyway: { bsonType: ["string", "null"] },
        notes: { bsonType: ["string", "null"] } } },
      alternateDesignation: { bsonType: ["string", "null"] },
      quantity: { bsonType: "int", minimum: 1 },
      sourceRef: { bsonType: ["object", "null"], required: ["documentId", "pageNumber"],
        properties: {
          documentId: { bsonType: "objectId" },
          pageNumber: { bsonType: "int", minimum: 1 },
          sheetLabel: { bsonType: ["string", "null"] },
          rowRef: { bsonType: ["string", "null"] } } },
      extractionConfidence: { bsonType: ["double", "null"], minimum: 0, maximum: 1 },
      reviewStatus: { enum: ["pending", "confirmed", "corrected", "flagged"] },
      unparsedNote: { bsonType: ["string", "null"] },
      matchCandidates: { bsonType: "array", items: {
        bsonType: "object",
        required: ["confidence", "rank", "selected"],
        properties: {
          catalogItemId: { bsonType: ["objectId", "null"] },
          hardwareSetId: { bsonType: ["objectId", "null"] },
          confidence: { bsonType: "double", minimum: 0, maximum: 1 },
          rank: { bsonType: "int", minimum: 1 },
          matchedOn: { bsonType: "array", items: { bsonType: "string" } },
          failedOn: { bsonType: "array", items: { bsonType: "string" } },
          selected: { bsonType: "bool" }
        } } }
    }
  } }
});
db.openings.createIndex({ orgId: 1, bidRequestId: 1, doorNumber: 1 }, { unique: true });
db.openings.createIndex({ orgId: 1, bidRequestId: 1, reviewStatus: 1 });
db.openings.createIndex({ orgId: 1, ratingConflict: 1 },
  { partialFilterExpression: { ratingConflict: true } });
db.openings.createIndex({ orgId: 1, ratingMissing: 1 },
  { partialFilterExpression: { ratingMissing: true } });
db.openings.createIndex({ orgId: 1, bidRequestId: 1, hardwareSetCallout: 1 });
```

**Notes on `fireRating` (Q5):** the field is required with an explicit `none` rather than being nullable, and `ratingMissing` is a separate boolean. That distinction is deliberate and load-bearing: *"unrated"* and *"we could not read the rating"* are different facts with different consequences, and collapsing them into a null would let a missing rating masquerade as an unrated opening — precisely the silent drop Matrix 7.3 (E29) forbids.

`ratingConflict` is stored rather than computed on read because it must be indexable. FR-4 matches on rating, and the defect check "rated opening, unlabelled match" needs to run across a whole bid in one query at draft time, not per-line in application code.

`openings` is a separate collection rather than an array on `bidRequests` because it is unbounded (Q14 — no hard cap), because each opening carries its own review lifecycle, and because the matcher updates individual openings concurrently during extraction. Embedding would make every match write contend on one document.

---

### 3.24 `takeoffs`

**Purpose:** Quantities measured from the drawings — counts for openings, and the FRP geometry captured in Vu360. Flow Phase 3b is precise about the FRP split: **Vu360 gives geometry only** (perimeter LF, inside corners, outside corners) and the estimator converts to material quantities by hand. This collection stores both sides of that conversion so no work is lost when the constants (Open 5) finally arrive.

**`_id` strategy:** `ObjectId`.

| Field | Type | Required | Default | Description | Source |
|---|---|---|---|---|---|
| `_id` | objectId | yes | auto | | — |
| `bidRequestId` | objectId | yes | — | → `bidRequests` | Flow Phase 3 |
| `openingId` | objectId | no | null | → `openings`; null for area-based FRP take-offs | Flow Phase 3 |
| `takeoffType` | string (enum) | yes | — | `openingCount` \| `frpArea` \| `linearFeet` \| `accessoryCount` \| `other` | Flow C7, C8 |
| `productTypeId` | objectId | no | null | → `productTypes` | Flow Phase 3 |
| `method` | string (enum) | yes | — | `manualPdfRead` \| `vu360` \| `edgeViewer` \| `copilotExtracted` | Flow D7, D8 |
| `geometry` | object | no | null | Vu360 output — see sub-table | Flow C8 |
| `convertedQuantity` | double | no | null | Material quantity after conversion | Flow C8 |
| `convertedUnit` | string (enum) | no | null | `EA` \| `LF` \| `SF` \| `PC` | Flow C8 |
| `conversionMethod` | string (enum) | yes | `manual` | `manual` \| `automatedConstants` — `automatedConstants` is only available once `frpConstants.dataStatus = confirmed` | FR-12; Open 5 |
| `constantsUsed` | array<object> | no | `[]` | `{ constantKey, value, frpConstantId }` — frozen for audit | FR-12; NFR-3 |
| `sourceRef` | object | no | null | `{ documentId, pageNumber, sheetLabel }` | NFR-3 |
| `drawingScale` | string | no | null | Scale set in Vu360 | Flow C8 |
| `enteredBy` | objectId | no | null | → `users` | Flow C8 |
| `reviewStatus` | string (enum) | yes | `pending` | `pending` \| `confirmed` \| `corrected` | FR-9 |
| `notes` | string | no | null | | Flow G8 |
| *envelope* | — | — | — | | §4.2 |

**Embedded `geometry` sub-document** (FRP, per Flow C8):

| Field | Type | Required | Description | Source |
|---|---|---|---|---|
| `perimeterLf` | double | no | Perimeter in linear feet | Flow C8 |
| `insideCorners` | int | no | Count | Flow C8 |
| `outsideCorners` | int | no | Count | Flow C8 |
| `heightFt` | double | no | Panel run height | FR-12 |
| `areaSf` | double | no | Derived where measured directly | FR-12 |
| `openingDeductions` | array<object> | no | `{ widthFt, heightFt, description }` — "opening handling" from Open 5 | Open 5 (B8) |

**Relationships:** `bidRequestId` → `bidRequests` (N:1); `openingId` → `openings` (N:1, optional); `productTypeId` → `productTypes` (N:1); feeds `estimateLines.quantity`.

**Indexes:**
- `{ orgId: 1, bidRequestId: 1, takeoffType: 1 }` — the bid's take-off sheet.
- `{ orgId: 1, openingId: 1 }` — **partial** (non-null). Quantities for one opening.
- `{ orgId: 1, bidRequestId: 1, reviewStatus: 1 }` — review worklist (FR-9).

```javascript
db.createCollection("takeoffs", {
  validator: { $jsonSchema: {
    bsonType: "object",
    required: [...envelopeRequired, "bidRequestId", "takeoffType", "method",
               "conversionMethod", "reviewStatus"],
    properties: {
      ...envelope,
      _id: { bsonType: "objectId" },
      bidRequestId: { bsonType: "objectId" },
      openingId: { bsonType: ["objectId", "null"] },
      takeoffType: { enum: ["openingCount", "frpArea", "linearFeet", "accessoryCount", "other"] },
      productTypeId: { bsonType: ["objectId", "null"] },
      method: { enum: ["manualPdfRead", "vu360", "edgeViewer", "copilotExtracted"] },
      convertedQuantity: { bsonType: ["double", "null"], minimum: 0 },
      convertedUnit: { enum: ["EA", "LF", "SF", "PC", null] },
      conversionMethod: { enum: ["manual", "automatedConstants"] },
      drawingScale: { bsonType: ["string", "null"] },
      enteredBy: { bsonType: ["objectId", "null"] },
      reviewStatus: { enum: ["pending", "confirmed", "corrected"] },
      notes: { bsonType: ["string", "null"] },
      geometry: { bsonType: ["object", "null"], properties: {
        perimeterLf:    { bsonType: ["double", "null"], minimum: 0 },
        insideCorners:  { bsonType: ["int", "null"], minimum: 0 },
        outsideCorners: { bsonType: ["int", "null"], minimum: 0 },
        heightFt:       { bsonType: ["double", "null"], minimum: 0 },
        areaSf:         { bsonType: ["double", "null"], minimum: 0 },
        openingDeductions: { bsonType: "array", items: {
          bsonType: "object",
          properties: {
            widthFt: { bsonType: "double", minimum: 0 },
            heightFt: { bsonType: "double", minimum: 0 },
            description: { bsonType: ["string", "null"] } } } } } },
      constantsUsed: { bsonType: "array", items: {
        bsonType: "object",
        required: ["constantKey", "value"],
        properties: {
          constantKey: { bsonType: "string" },
          value: { bsonType: ["double", "string"] },
          frpConstantId: { bsonType: ["objectId", "null"] } } } },
      sourceRef: { bsonType: ["object", "null"], properties: {
        documentId: { bsonType: "objectId" },
        pageNumber: { bsonType: ["int", "null"], minimum: 1 },
        sheetLabel: { bsonType: ["string", "null"] } } }
    }
  } }
});
db.takeoffs.createIndex({ orgId: 1, bidRequestId: 1, takeoffType: 1 });
db.takeoffs.createIndex({ orgId: 1, openingId: 1 },
  { partialFilterExpression: { openingId: { $type: "objectId" } } });
db.takeoffs.createIndex({ orgId: 1, bidRequestId: 1, reviewStatus: 1 });
```

**Notes:** `geometry` and `convertedQuantity` are stored side by side rather than one replacing the other. Today the estimator types the converted number and the geometry is context; once FR-12 automates the conversion, the geometry becomes the input and `constantsUsed[]` records exactly which constants produced the number — which is what makes a re-run reproducible and satisfies NFR-3 for FRP lines the same way `priceBookSnapshot` does for hardware lines.

---

### 3.25 `estimates`

**Purpose:** The stable identity of a quote across all its versions. One estimate per bid request; the mutable working state lives in `estimateVersions` (Q6). This document exists so that "the quote for bid LA0701" has a single durable id that survives every addendum.

**`_id` strategy:** `ObjectId`; unique business key `{ orgId, bidRequestId }`.

| Field | Type | Required | Default | Description | Source |
|---|---|---|---|---|---|
| `_id` | objectId | yes | auto | | — |
| `bidRequestId` | objectId | yes | — | → `bidRequests` (1:1) | Flow Phase 1 |
| `estimateNumber` | string | yes | — | Human reference | Flow Phase 1 |
| `currentVersionId` | objectId | no | null | → `estimateVersions`; denormalized pointer to the head of the chain | Q6 |
| `currentVersionNumber` | int | yes | `0` | Denormalized; `0` until the first version is created | Q6 |
| `estimationMode` | string (enum) | yes | — | `templated` \| `oneOff` | Matrix 3.0 (D10, I10) |
| `sourceType` | string (enum) | yes | `native` | `native` \| `importedLegacy` | Q8 |
| `legacyWorkbookRef` | string | no | null | Filename/path of the imported ESTIMATOR-protected workbook | Q8 |
| `templateSourceEstimateId` | objectId | no | null | → `estimates`; the prior quote this one was started from (templated mode / FR-11) | Matrix 3.0 (I10); FR-11 |
| `versionCount` | int | yes | `0` | Denormalized | §4.8 |
| `hasAlternates` | bool | yes | `false` | Denormalized from the current version | Matrix 4.1 |
| *soft delete* | — | — | — | Per Q13 | §4.3 |
| *envelope* | — | — | — | | §4.2 |

**Relationships:** `bidRequestId` → `bidRequests` (1:1); `currentVersionId` → `estimateVersions` (1:1); `templateSourceEstimateId` → `estimates` (self, N:1); parent of `estimateVersions` (1:N).

**Indexes:**
- `{ orgId: 1, bidRequestId: 1 }` — **unique**. Enforces one estimate per bid.
- `{ orgId: 1, estimateNumber: 1 }` — **unique**.
- `{ orgId: 1, sourceType: 1, isDeleted: 1 }` — separates native from imported legacy records (Q8).
- `{ orgId: 1, templateSourceEstimateId: 1 }` — **partial** (non-null). "What was reused from this quote" (FR-11).

```javascript
db.createCollection("estimates", {
  validator: { $jsonSchema: {
    bsonType: "object",
    required: [...envelopeRequired, "bidRequestId", "estimateNumber", "currentVersionNumber",
               "estimationMode", "sourceType", "versionCount", "hasAlternates", "isDeleted"],
    properties: {
      ...envelope, ...softDelete,
      _id: { bsonType: "objectId" },
      bidRequestId: { bsonType: "objectId" },
      estimateNumber: { bsonType: "string" },
      currentVersionId: { bsonType: ["objectId", "null"] },
      currentVersionNumber: { bsonType: "int", minimum: 0 },
      estimationMode: { enum: ["templated", "oneOff"] },
      sourceType: { enum: ["native", "importedLegacy"] },
      legacyWorkbookRef: { bsonType: ["string", "null"] },
      templateSourceEstimateId: { bsonType: ["objectId", "null"] },
      versionCount: { bsonType: "int", minimum: 0 },
      hasAlternates: { bsonType: "bool" }
    }
  } }
});
db.estimates.createIndex({ orgId: 1, bidRequestId: 1 }, { unique: true });
db.estimates.createIndex({ orgId: 1, estimateNumber: 1 }, { unique: true });
db.estimates.createIndex({ orgId: 1, sourceType: 1, isDeleted: 1 });
db.estimates.createIndex({ orgId: 1, templateSourceEstimateId: 1 },
  { partialFilterExpression: { templateSourceEstimateId: { $type: "objectId" } } });
```

**Notes:** `currentVersionId` and `currentVersionNumber` are denormalized pointers, updated in the same operation that creates a new version. They exist because the single most common read in the app — "open the current quote for this bid" — should not require sorting the version chain. If they ever disagree with the chain, the chain wins: `currentVersionId` is a cache, `estimateVersions.supersededByVersionId = null` is the truth.

`sourceType: "importedLegacy"` and `legacyWorkbookRef` implement Q8. Imported records live in the same structure as native ones, so FR-11's future similarity search over prior quotes needs no separate code path — only the seeding differs.

---

### 3.26 `estimateVersions`

**Purpose:** An immutable snapshot of the quote at a point in time (Q6). This is the structural heart of the schema. Matrix 4.1 requires that the estimate *track a base bid plus alternates and absorb addendum revisions without losing prior work*, and FR-14 requires versioning that does not lose history. A new version is created on each addendum or re-issue; unaffected line groups are reference-copied forward, affected ones are rewritten.

**`_id` strategy:** `ObjectId`; unique business key `{ orgId, estimateId, versionNumber }`.

| Field | Type | Required | Default | Description | Source |
|---|---|---|---|---|---|
| `_id` | objectId | yes | auto | | — |
| `estimateId` | objectId | yes | — | → `estimates` | Q6 |
| `versionNumber` | int | yes | — | 1-based, monotonic | Q6 |
| `supersededByVersionId` | objectId | no | null | → `estimateVersions`; null = head of chain | Q6 |
| `previousVersionId` | objectId | no | null | → `estimateVersions`; null for v1 | Q6 |
| `versionReason` | string (enum) | yes | — | `initial` \| `addendum` \| `estimatorRevision` \| `reissue` \| `alternateAdded` | Matrix 4.1 (D14) |
| `triggeringAddendumDocumentId` | objectId | no | null | → `documents` | Matrix 4.1; Flow 4b |
| `status` | string (enum) | yes | `draft` | See state machine below | FR-9, NFR-1 |
| `statusHistory` | array<object> | yes | `[]` | `{ from, to, at, by, note }` | Q3; §4.5 |
| `alternates` | array<object> | yes | `[]` | Embedded — `{ _id, number, label, description, isBase }` | Matrix 4.1; Q6 |
| `lineGroups` | array<object> | yes | `[]` | Embedded — see sub-table | FR-7 (C44) |
| `totals` | object | yes | — | Computed roll-up — see sub-table | Matrix 5.0 (D16) |
| `taxSnapshot` | object | no | null | `{ taxRuleId, country, state, taxable, rate, resolvedAt }` frozen at pricing | Matrix 2.4 (I8); Q7 |
| `termsTemplateId` | objectId | no | null | → `commercialTermsTemplates` | FR-10 |
| `approvedBy` | objectId | no | null | → `users`. **Must be a human** — NFR-1 | NFR-1 (D55) |
| `approvedAt` | date | no | null | | NFR-1 |
| `lockedAt` | date | no | null | Set when superseded; document becomes read-only | Q6 |
| `hasUnresolvedFlags` | bool | yes | `false` | Any low-confidence match, missing rating, unparsed content, or pending RFQ | FR-8; NFR-2 |
| `flagSummary` | object | no | null | `{ lowConfidence, ratingMissing, ratingConflict, awaitingRfq, unparsed }` counts | FR-8 |
| *soft delete* | — | — | — | Per Q13 | §4.3 |
| *envelope* | — | — | — | | §4.2 |

**Embedded `alternates[]`:**

| Field | Type | Required | Description | Source |
|---|---|---|---|---|
| `_id` | objectId | yes | Referenced by `estimateLines.alternateId` | Q6 |
| `number` | int | yes | `1`, `2`, … | Matrix 4.1 (D14) |
| `label` | string | yes | `Alternate 1` | Matrix 4.1 (D14) |
| `description` | string | no | What the alternate changes | Matrix 4.1 |
| `isBase` | bool | yes | `false` for all entries; base bid is represented by `alternateId: null` on the line | Q6 |

**Embedded `lineGroups[]`:**

| Field | Type | Required | Description | Source |
|---|---|---|---|---|
| `_id` | objectId | yes | Referenced by `estimateLines.lineGroupId` | Q6 |
| `groupType` | string (enum) | yes | `door` \| `accessories` \| `frp` \| `freight` \| `other` — the proposal's structure: grouped by door, separate restroom-accessories block, freight line | FR-7 (C44) |
| `label` | string | yes | e.g. `Door 101`, `Restroom Accessories` | FR-7 |
| `openingId` | objectId | no | → `openings` when `groupType = door` | FR-7 |
| `alternateId` | objectId | no | Null = base bid | Q6 |
| `sequence` | int | yes | Display order on the proposal | FR-7 |
| `subtotal` | double | yes | Sum of member line `extendedPrice` | Matrix 5.0 (D16) |
| `carriedForwardFromVersionId` | objectId | no | Set when reference-copied unchanged from the previous version | Q6 |

**Embedded `totals` sub-document:**

| Field | Type | Required | Description | Source |
|---|---|---|---|---|
| `baseSubtotal` | double | yes | Sum of base-bid group subtotals | Matrix 5.0 (D16) |
| `alternateSubtotals` | array<object> | yes | `{ alternateId, label, subtotal }` — alternates priced as distinct, comparable groups | Matrix 4.1; Flow C10 |
| `freightAmount` | double | no | Usually absent at estimate stage | FR-7 (I44); Open 1 |
| `taxAmount` | double | no | OH/KY only | Matrix 2.4 (I8) |
| `grandTotal` | double | yes | `SUM(subtotals)` + freight + tax | Matrix 5.0 (D16) |
| `currency` | string | yes | `USD` | §4.7 |

**State machine** (`status`):

| From | To | Trigger | Source |
|---|---|---|---|
| — | `draft` | Version created | FR-9 |
| `draft` | `priced` | All lines have a cost and margin | Matrix 5.0 |
| `priced` | `pendingReview` | Submitted for estimator review | FR-9 |
| `pendingReview` | `draft` | Edits requested | FR-9 |
| `pendingReview` | `approved` | **Explicit human approval** — sets `approvedBy`, `approvedAt` | NFR-1 (D55) |
| `approved` | `sent` | Proposal exported and delivered to the initiator | FR-10 (I47) |
| `draft`\|`priced`\|`pendingReview`\|`approved`\|`sent` | `superseded` | A newer version supersedes this one; sets `lockedAt`, `supersededByVersionId` | Q6; Matrix 4.1 |

**Relationships:** `estimateId` → `estimates` (N:1); `supersededByVersionId` / `previousVersionId` → self (1:1); `triggeringAddendumDocumentId` → `documents` (N:1); `termsTemplateId` → `commercialTermsTemplates` (N:1); `approvedBy` → `users` (N:1); parent of `estimateLines` (1:N, referenced) and of `proposals` (1:1).

**Indexes:**
- `{ orgId: 1, estimateId: 1, versionNumber: -1 }` — **unique**. Version chain traversal and "latest version".
- `{ orgId: 1, estimateId: 1, supersededByVersionId: 1 }` — **partial** (`supersededByVersionId: null`) — resolves the head of the chain directly.
- `{ orgId: 1, status: 1, updatedAt: -1 }` — review and approval queues.
- `{ orgId: 1, hasUnresolvedFlags: 1, status: 1 }` — **partial** (`hasUnresolvedFlags: true`) — NFR-2's "nothing silently guessed" dashboard.
- `{ orgId: 1, approvedAt: -1 }` — **partial** (non-null) — approval audit and future turnaround KPIs (Q3).

```javascript
db.createCollection("estimateVersions", {
  validator: { $jsonSchema: {
    bsonType: "object",
    required: [...envelopeRequired, "estimateId", "versionNumber", "versionReason", "status",
               "statusHistory", "alternates", "lineGroups", "totals",
               "hasUnresolvedFlags", "isDeleted"],
    properties: {
      ...envelope, ...softDelete,
      _id: { bsonType: "objectId" },
      estimateId: { bsonType: "objectId" },
      versionNumber: { bsonType: "int", minimum: 1 },
      supersededByVersionId: { bsonType: ["objectId", "null"] },
      previousVersionId: { bsonType: ["objectId", "null"] },
      versionReason: { enum: ["initial", "addendum", "estimatorRevision", "reissue", "alternateAdded"] },
      triggeringAddendumDocumentId: { bsonType: ["objectId", "null"] },
      status: { enum: ["draft", "priced", "pendingReview", "approved", "sent", "superseded"] },
      statusHistory: statusHistory,
      termsTemplateId: { bsonType: ["objectId", "null"] },
      approvedBy: { bsonType: ["objectId", "null"] },
      approvedAt: { bsonType: ["date", "null"] },
      lockedAt: { bsonType: ["date", "null"] },
      hasUnresolvedFlags: { bsonType: "bool" },
      flagSummary: { bsonType: ["object", "null"], properties: {
        lowConfidence:  { bsonType: "int", minimum: 0 },
        ratingMissing:  { bsonType: "int", minimum: 0 },
        ratingConflict: { bsonType: "int", minimum: 0 },
        awaitingRfq:    { bsonType: "int", minimum: 0 },
        unparsed:       { bsonType: "int", minimum: 0 } } },
      taxSnapshot: { bsonType: ["object", "null"], properties: {
        taxRuleId: { bsonType: ["objectId", "null"] },
        country: { enum: ["US", "CA"] },
        state: { bsonType: ["string", "null"] },
        taxable: { bsonType: "bool" },
        rate: { bsonType: "double", minimum: 0, maximum: 1 },
        resolvedAt: { bsonType: "date" } } },
      alternates: { bsonType: "array", items: {
        bsonType: "object",
        required: ["_id", "number", "label", "isBase"],
        properties: {
          _id: { bsonType: "objectId" },
          number: { bsonType: "int", minimum: 1 },
          label: { bsonType: "string" },
          description: { bsonType: ["string", "null"] },
          isBase: { bsonType: "bool" } } } },
      lineGroups: { bsonType: "array", items: {
        bsonType: "object",
        required: ["_id", "groupType", "label", "sequence", "subtotal"],
        properties: {
          _id: { bsonType: "objectId" },
          groupType: { enum: ["door", "accessories", "frp", "freight", "other"] },
          label: { bsonType: "string" },
          openingId: { bsonType: ["objectId", "null"] },
          alternateId: { bsonType: ["objectId", "null"] },
          sequence: { bsonType: "int", minimum: 0 },
          subtotal: { bsonType: "double" },
          carriedForwardFromVersionId: { bsonType: ["objectId", "null"] } } } },
      totals: { bsonType: "object",
        required: ["baseSubtotal", "alternateSubtotals", "grandTotal", "currency"],
        properties: {
          baseSubtotal: { bsonType: "double" },
          alternateSubtotals: { bsonType: "array", items: {
            bsonType: "object",
            required: ["alternateId", "subtotal"],
            properties: {
              alternateId: { bsonType: "objectId" },
              label: { bsonType: ["string", "null"] },
              subtotal: { bsonType: "double" } } } },
          freightAmount: { bsonType: ["double", "null"], minimum: 0 },
          taxAmount: { bsonType: ["double", "null"], minimum: 0 },
          grandTotal: { bsonType: "double" },
          currency: { enum: ["USD"] } } }
    }
  } }
});
db.estimateVersions.createIndex({ orgId: 1, estimateId: 1, versionNumber: -1 }, { unique: true });
db.estimateVersions.createIndex({ orgId: 1, estimateId: 1, supersededByVersionId: 1 },
  { partialFilterExpression: { supersededByVersionId: null } });
db.estimateVersions.createIndex({ orgId: 1, status: 1, updatedAt: -1 });
db.estimateVersions.createIndex({ orgId: 1, hasUnresolvedFlags: 1, status: 1 },
  { partialFilterExpression: { hasUnresolvedFlags: true } });
db.estimateVersions.createIndex({ orgId: 1, approvedAt: -1 },
  { partialFilterExpression: { approvedAt: { $type: "date" } } });
```

**Notes on immutability:** a version with `lockedAt` set must never be written again — enforced in the application's data-access layer and observable in `auditLogs`. MongoDB's schema validation cannot express "this document is now read-only", so this is a convention with an audit trail rather than a database-enforced constraint; it is called out here so no future contributor assumes the database is stopping them.

**Why alternates are embedded and lines are not:** alternates number in the low single digits per bid, are defined once at version scope, and are always read with the version — textbook embedding. Line groups are similar: one per door plus an accessories block and at most a freight line, all bounded by opening count and all needed to render the proposal skeleton. Lines themselves are referenced (Q15), so a 40-opening bid with several hundred lines keeps this document small and fast to list.

**Addendum mechanics:** when an addendum arrives, the application creates version N+1, copies forward every `lineGroup` whose scope is unaffected with `carriedForwardFromVersionId` set to version N, rewrites the affected groups, and re-points the affected `estimateLines` to the new version. Version N gets `supersededByVersionId` and `lockedAt`. Prior work is preserved intact, which is exactly what Matrix 4.1 (D14) demands — *absorb addendum revisions without losing prior work*.

---

### 3.27 `estimateLines`

**Purpose:** One priced line on the quote. Matrix 5.0 is the specification for this collection, and it is unusually clear: *the quote workbook is a calculator. Only three cells are human per line — Quantity, Our Cost, and Margin. Everything to the right is computed.* Every computed value below is stored, not derived on read, because NFR-3 requires the quote to be reproducible exactly as sent.

**`_id` strategy:** `ObjectId`.

| Field | Type | Required | Default | Description | Source |
|---|---|---|---|---|---|
| `_id` | objectId | yes | auto | | — |
| `estimateVersionId` | objectId | yes | — | → `estimateVersions` | Q15 |
| `estimateId` | objectId | yes | — | → `estimates`; denormalized for cross-version queries | Q15 |
| `lineGroupId` | objectId | yes | — | → `estimateVersions.lineGroups[]._id` | FR-7 |
| `alternateId` | objectId | no | null | Null = base bid | Q6 |
| `openingId` | objectId | no | null | → `openings`; null for accessories/freight | FR-7 |
| `lineType` | string (enum) | yes | — | `product` \| `hardwareSetComponent` \| `frp` \| `accessory` \| `freight` \| `custom` \| `note` | FR-7; Q12 |
| `sequence` | int | yes | — | Order within the group | FR-7 |
| `catalogItemId` | objectId | no | null | → `catalogItems`; null for custom/manual lines | FR-4 |
| `vendorId` | objectId | no | null | → `vendors`; denormalized — see notes | §4.8 |
| `productTypeId` | objectId | no | null | → `productTypes`; drives the margin band | Matrix 6.1 |
| `partNumber` | string | no | null | Frozen at pricing time | Matrix 7.7 (I33) |
| `description` | string | yes | — | Appears on the customer-facing proposal | FR-10 |
| `finishCode` | string | no | null | → `finishCodes.code` | Matrix 7.5 |
| `handing` | string (enum) | no | null | `LH`\|`RH`\|`LHR`\|`RHR` | Matrix 7.4 |
| `fireRating` | string (enum) | no | null | Carried from the opening | Matrix 7.3; Q5 |
| `options` | object | no | null | `{ function, backset, lever, keyway, strike, electrified, keying: { coreType, keyway, notes } }` | Matrix 7.2 (I28); 7.6 (I32) |
| **`quantity`** | double | yes | — | **MANUAL INPUT 1** — from the take-off | Matrix 5.0 (D16) |
| `unitOfMeasure` | string (enum) | yes | `EA` | | Matrix 5.0 |
| **`ourCost`** | double | no | null | **MANUAL INPUT 2** — the cost actually used | Matrix 5.0 (D16) |
| **`marginRate`** | double | no | null | **MANUAL INPUT 3** — decimal margin, e.g. `0.27` | Matrix 5.0 (D16); 6.1 |
| `salePriceEach` | double | no | null | **COMPUTED**: `ourCost / (1 - marginRate)` | Matrix 5.0 (D16) |
| `unitPrice` | double | no | null | **COMPUTED**: equals `salePriceEach` | Matrix 5.0 (D16) |
| `extendedPrice` | double | no | null | **COMPUTED**: `unitPrice × quantity` | Matrix 5.0 (D16) |
| `lineSubtotal` | double | no | null | **COMPUTED**: `salePriceEach × quantity` | Matrix 5.0 (D16) |
| `costSnapshot` | object | no | null | Frozen — see sub-table | Q7 |
| `priceBookSnapshot` | object | no | null | Frozen — see sub-table | Q7 |
| `multiplierTierSnapshot` | object | no | null | Frozen — see sub-table | Q7 |
| `marginSnapshot` | object | no | null | Frozen — see sub-table | Q7 |
| `appliedAdders` | array<object> | no | `[]` | `{ adderId, code, valueType, value, amount }` frozen | Open NR-4 |
| `matchResult` | object | no | null | `{ confidence, rank, matchedOn[], failedOn[], ratingConflict, autoMatched }` | FR-4, FR-8; Q5 |
| `sourcingNote` | object | no | null | `{ path, distributorVendorId, text }` — how the item will be sourced and why | Matrix 6.5 (D22, I22) |
| `substitutionNote` | object | no | null | `{ specifiedPartNumber, substitutedPartNumber, reason, gcApprovalStatus }` | Matrix 6.4 (D21, I21) |
| `vendorRfqId` | objectId | no | null | → `vendorRfqs` | Matrix 6.6; FR-16 |
| `priceMayBeStale` | bool | yes | `false` | Drives the "price may be out of date — refresh" prompt | Open NR-2; FR-16 (I53) |
| `manualEntryRequired` | bool | yes | `false` | `true` for distributor-bought lines and beyond-cut-off custom items | Open NR-2, NR-13 |
| `status` | string (enum) | yes | `draft` | See state machine below | FR-9 |
| `statusHistory` | array<object> | yes | `[]` | | §4.5 |
| `reviewAction` | string (enum) | no | null | `accepted` \| `edited` \| `added` \| `deleted` — feeds FR-13 | FR-9 (C46); FR-13 |
| `sourceRef` | object | no | null | `{ documentId, pageNumber, sheetLabel }` — NFR-3 | NFR-3 (D57) |
| `notes` | string | no | null | Appears on the proposal where relevant | Matrix 6.4 (I21) |
| `currency` | string | yes | `USD` | | §4.7 |
| *envelope* | — | — | — | | §4.2 |

**Frozen snapshot sub-documents (Q7):**

| Snapshot | Fields | Source |
|---|---|---|
| `costSnapshot` | `amount`, `source` (enum: `p21LastPo`, `listTimesMultiplier`, `vendorRfq`, `distributorLookup`, `mfrWebsite`, `manual`, `preComputedNet`), `sourceDate`, `p21ItemId`, `p21LastPoDate`, `freshness`, `enteredBy` | Matrix 6.2 (I19), 6.3, 6.6; FR-6; Q7 |
| `priceBookSnapshot` | `priceBookId`, `version`, `effectiveDate`, `listPrice`, `priceBookEntryId` | Matrix 6.3; NFR-3; Q7 |
| `multiplierTierSnapshot` | `vendorTierId`, `tier`, `rate`, `preComputedNet`, `effectiveDate` | Matrix 6.3 (D20); NFR-3; Q7 |
| `marginSnapshot` | `band`, `rate`, `overridden` (bool), `overrideReason`, `marginRuleId`, `resolvedScope` (enum: `default`, `brandProgram`, `customer`, `lineOverride`) | Matrix 6.1 (I18); Q7, Q11 |

**State machine** (`status`):

| From | To | Trigger | Source |
|---|---|---|---|
| — | `draft` | Line created by the matcher or by hand | FR-4 |
| `draft` | `matched` | A library match was proposed and accepted | FR-4 |
| `draft`\|`matched` | `awaitingVendorQuote` | Sent to a vendor RFQ | Matrix 6.6; FR-16 |
| `awaitingVendorQuote` | `priced` | Returned price captured | FR-16 (C53) |
| `draft`\|`matched` | `pricedManual` | Estimator entered the price by hand | Open NR-2 |
| `matched` | `priced` | Cost + margin resolved automatically | FR-6 |
| `priced`\|`pricedManual` | `approved` | Included in an approved version | NFR-1 |
| any | `excluded` | Removed from the quote but retained for history (freight defaults here) | Q12; FR-9 |

**Relationships:** `estimateVersionId` → `estimateVersions` (N:1); `estimateId` → `estimates` (N:1, denormalized); `lineGroupId` / `alternateId` → embedded subdocuments in the version; `openingId` → `openings`; `catalogItemId` → `catalogItems`; `vendorId` → `vendors`; `productTypeId` → `productTypes`; `vendorRfqId` → `vendorRfqs`; referenced by `feedbackEvents.estimateLineId`.

**Indexes:**
- `{ orgId: 1, estimateVersionId: 1, lineGroupId: 1, sequence: 1 }` — the proposal render query, in proposal order. The primary read path and the reason Q15's reference model costs so little.
- `{ orgId: 1, estimateVersionId: 1, alternateId: 1 }` — base-vs-alternate comparison (Matrix 4.1).
- `{ orgId: 1, catalogItemId: 1, createdAt: -1 }` — **the cross-estimate query Q15 was decided on**: *every line where a Hager 3500 was quoted*. Serves vendor-tier renegotiation impact analysis and catalog pricing audits.
- `{ orgId: 1, vendorId: 1, createdAt: -1 }` — vendor-level exposure, the coarser version of the same need (Hager ≈ 75% of volume).
- `{ orgId: 1, status: 1, estimateVersionId: 1 }` — "what is still unpriced on this quote".
- `{ orgId: 1, vendorRfqId: 1 }` — **partial** (non-null) — slot a returned RFQ price back into its lines (FR-16).
- `{ orgId: 1, priceMayBeStale: 1, estimateVersionId: 1 }` — **partial** (`priceMayBeStale: true`) — the refresh prompt (NR-2).
- `{ orgId: 1, openingId: 1 }` — **partial** (non-null) — all lines for one door.

```javascript
db.createCollection("estimateLines", {
  validator: { $jsonSchema: {
    bsonType: "object",
    required: [...envelopeRequired, "estimateVersionId", "estimateId", "lineGroupId",
               "lineType", "sequence", "description", "quantity", "unitOfMeasure",
               "priceMayBeStale", "manualEntryRequired", "status", "statusHistory", "currency"],
    properties: {
      ...envelope,
      _id: { bsonType: "objectId" },
      estimateVersionId: { bsonType: "objectId" },
      estimateId: { bsonType: "objectId" },
      lineGroupId: { bsonType: "objectId" },
      alternateId: { bsonType: ["objectId", "null"] },
      openingId: { bsonType: ["objectId", "null"] },
      lineType: { enum: ["product", "hardwareSetComponent", "frp", "accessory",
                         "freight", "custom", "note"] },
      sequence: { bsonType: "int", minimum: 0 },
      catalogItemId: { bsonType: ["objectId", "null"] },
      vendorId: { bsonType: ["objectId", "null"] },
      productTypeId: { bsonType: ["objectId", "null"] },
      partNumber: { bsonType: ["string", "null"] },
      description: { bsonType: "string" },
      finishCode: { bsonType: ["string", "null"] },
      handing: { enum: ["LH", "RH", "LHR", "RHR", null] },
      fireRating: { enum: ["20", "45", "60", "90", "none", null] },
      options: { bsonType: ["object", "null"], properties: {
        function: { bsonType: ["string", "null"] },
        backset: { bsonType: ["string", "null"] },
        lever: { bsonType: ["string", "null"] },
        keyway: { bsonType: ["string", "null"] },
        strike: { bsonType: ["string", "null"] },
        electrified: { bsonType: ["bool", "null"] },
        keying: { bsonType: ["object", "null"], properties: {
          coreType: { enum: ["icSmallFormat", "icLargeFormat", "conventional", "none", null] },
          keyway: { bsonType: ["string", "null"] },
          notes: { bsonType: ["string", "null"] } } } } },
      quantity: { bsonType: "double", minimum: 0 },
      unitOfMeasure: { enum: ["EA", "LF", "SF", "PR", "SET", "PC"] },
      ourCost: { bsonType: ["double", "null"], minimum: 0 },
      marginRate: { bsonType: ["double", "null"], minimum: 0, exclusiveMaximum: 1 },
      salePriceEach: { bsonType: ["double", "null"], minimum: 0 },
      unitPrice: { bsonType: ["double", "null"], minimum: 0 },
      extendedPrice: { bsonType: ["double", "null"], minimum: 0 },
      lineSubtotal: { bsonType: ["double", "null"], minimum: 0 },
      currency: { enum: ["USD"] },
      costSnapshot: { bsonType: ["object", "null"],
        required: ["amount", "source"],
        properties: {
          amount: { bsonType: "double", minimum: 0 },
          source: { enum: ["p21LastPo", "listTimesMultiplier", "vendorRfq",
                           "distributorLookup", "mfrWebsite", "manual", "preComputedNet"] },
          sourceDate: { bsonType: ["date", "null"] },
          p21ItemId: { bsonType: ["string", "null"] },
          p21LastPoDate: { bsonType: ["date", "null"] },
          freshness: { enum: ["fresh", "aging", "stale", "discard", "unknown", null] },
          enteredBy: { bsonType: ["objectId", "null"] } } },
      priceBookSnapshot: { bsonType: ["object", "null"], properties: {
        priceBookId: { bsonType: ["objectId", "null"] },
        version: { bsonType: ["string", "null"] },
        effectiveDate: { bsonType: ["date", "null"] },
        listPrice: { bsonType: ["double", "null"], minimum: 0 },
        priceBookEntryId: { bsonType: ["objectId", "null"] } } },
      multiplierTierSnapshot: { bsonType: ["object", "null"], properties: {
        vendorTierId: { bsonType: ["objectId", "null"] },
        tier: { bsonType: ["string", "null"] },
        rate: { bsonType: ["double", "null"], exclusiveMinimum: 0, maximum: 1 },
        preComputedNet: { bsonType: ["bool", "null"] },
        effectiveDate: { bsonType: ["date", "null"] } } },
      marginSnapshot: { bsonType: ["object", "null"],
        required: ["rate", "overridden"],
        properties: {
          band: { enum: ["commodity", "restroomPartitions", "specialty",
                         "customFabricated", "accessories", null] },
          rate: { bsonType: "double", minimum: 0, exclusiveMaximum: 1 },
          overridden: { bsonType: "bool" },
          overrideReason: { bsonType: ["string", "null"] },
          marginRuleId: { bsonType: ["objectId", "null"] },
          resolvedScope: { enum: ["default", "brandProgram", "customer", "lineOverride", null] } } },
      appliedAdders: { bsonType: "array", items: {
        bsonType: "object",
        required: ["code", "amount"],
        properties: {
          adderId: { bsonType: ["objectId", "null"] },
          code: { bsonType: "string" },
          valueType: { enum: ["flatAmount", "percentOfList", "perUnit", null] },
          value: { bsonType: ["double", "null"] },
          amount: { bsonType: "double" } } } },
      matchResult: { bsonType: ["object", "null"], properties: {
        confidence: { bsonType: ["double", "null"], minimum: 0, maximum: 1 },
        rank: { bsonType: ["int", "null"], minimum: 1 },
        matchedOn: { bsonType: "array", items: { bsonType: "string" } },
        failedOn: { bsonType: "array", items: { bsonType: "string" } },
        ratingConflict: { bsonType: ["bool", "null"] },
        autoMatched: { bsonType: ["bool", "null"] } } },
      sourcingNote: { bsonType: ["object", "null"], properties: {
        path: { enum: ["buyDirect", "viaDistributor", "fabricated", "stock", null] },
        distributorVendorId: { bsonType: ["objectId", "null"] },
        text: { bsonType: ["string", "null"] } } },
      substitutionNote: { bsonType: ["object", "null"], properties: {
        specifiedPartNumber: { bsonType: ["string", "null"] },
        substitutedPartNumber: { bsonType: ["string", "null"] },
        reason: { bsonType: ["string", "null"] },
        gcApprovalStatus: { enum: ["notRequested", "requested", "approved", "rejected", null] } } },
      vendorRfqId: { bsonType: ["objectId", "null"] },
      priceMayBeStale: { bsonType: "bool" },
      manualEntryRequired: { bsonType: "bool" },
      status: { enum: ["draft", "matched", "awaitingVendorQuote", "priced",
                       "pricedManual", "approved", "excluded"] },
      statusHistory: statusHistory,
      reviewAction: { enum: ["accepted", "edited", "added", "deleted", null] },
      sourceRef: { bsonType: ["object", "null"], properties: {
        documentId: { bsonType: "objectId" },
        pageNumber: { bsonType: ["int", "null"], minimum: 1 },
        sheetLabel: { bsonType: ["string", "null"] } } },
      notes: { bsonType: ["string", "null"] }
    }
  } }
});
db.estimateLines.createIndex({ orgId: 1, estimateVersionId: 1, lineGroupId: 1, sequence: 1 });
db.estimateLines.createIndex({ orgId: 1, estimateVersionId: 1, alternateId: 1 });
db.estimateLines.createIndex({ orgId: 1, catalogItemId: 1, createdAt: -1 });
db.estimateLines.createIndex({ orgId: 1, vendorId: 1, createdAt: -1 });
db.estimateLines.createIndex({ orgId: 1, status: 1, estimateVersionId: 1 });
db.estimateLines.createIndex({ orgId: 1, vendorRfqId: 1 },
  { partialFilterExpression: { vendorRfqId: { $type: "objectId" } } });
db.estimateLines.createIndex({ orgId: 1, priceMayBeStale: 1, estimateVersionId: 1 },
  { partialFilterExpression: { priceMayBeStale: true } });
db.estimateLines.createIndex({ orgId: 1, openingId: 1 },
  { partialFilterExpression: { openingId: { $type: "objectId" } } });
```

**Notes on what is *not* here:** there is no `unitWeight` and no `totalWeight`. Matrix 5.0 (I16) is explicit — *all quote-calc formulas validated EXCEPT 'unit weight' — legacy from truck-loading years ago; not used, remove it.* Omitting it is a deliberate schema decision, recorded here so nobody re-adds it from the older process document.

**On storing computed values:** `salePriceEach`, `unitPrice`, `extendedPrice` and `lineSubtotal` are all derivable from the three manual inputs, and storing derived values usually invites drift. They are stored anyway because NFR-3 requires that a quote sent to a customer be reproducible exactly, and recomputation depends on floating-point and rounding behaviour that may change with a code deploy. The stored value is what the customer saw; the formula is documented in §4.7 for verification.

**On `vendorId` denormalization:** copied from `catalogItems` at pricing time. It is needed for the vendor-exposure index above, and going through `catalogItemId` would require a `$lookup` on every such query. It is frozen at pricing time by design — if a part later moves vendors, historical lines correctly continue to name the vendor it was actually quoted from.

**On the three manual inputs:** `quantity`, `ourCost` and `marginRate` are the only human-writable numeric fields, per Matrix 5.0. They are nullable (except quantity) because a line can legitimately exist before it is priced — that is exactly the `awaitingVendorQuote` state.

---

### 3.28 `vendorRfqs`

**Purpose:** The third cost path (Matrix 6.6, FR-16). Triggered by custom sizes (9-ft doors), unusual preps, or options not sold in years — for example electric latch retraction in a given model, size and finish. The estimator requests a live quote, waits, and enters the returned price by hand. Matrix 6.6 (G23) notes this *can hold up a bid*, so the RFQ's state is visible on the estimator's queue.

**`_id` strategy:** `ObjectId`; unique business key `{ orgId, rfqNumber }`.

| Field | Type | Required | Default | Description | Source |
|---|---|---|---|---|---|
| `_id` | objectId | yes | auto | | — |
| `rfqNumber` | string | yes | — | Human reference | FR-16 |
| `bidRequestId` | objectId | yes | — | → `bidRequests` | Matrix 6.6 |
| `vendorId` | objectId | yes | — | → `vendors` (manufacturer, distributor, or fabricator) | Matrix 6.6 |
| `triggerReason` | string (enum) | yes | — | `customSize` \| `unusualPrep` \| `notSoldInYears` \| `nonStock` \| `firstTime` \| `beyondCutoff` | Matrix 6.6 (I23); NR-13 |
| `requestedItems` | array<object> | yes | `[]` | `{ description, partNumber, quantity, sizeCode, finishCode, options, estimateLineId }` | Matrix 6.6 |
| `status` | string (enum) | yes | `draft` | See state machine below | FR-16 (C53) |
| `statusHistory` | array<object> | yes | `[]` | | Q3; §4.5 |
| `requestedAt` | date | no | null | | Matrix 6.6 |
| `requestedBy` | objectId | no | null | → `users` | Matrix 6.6 |
| `dueBy` | date | no | null | Derived from the bid due date | Flow C4 |
| `respondedAt` | date | no | null | Turnaround measurement (Open 12) | Open 12 (C15) |
| `responseDocumentId` | objectId | no | null | → `documents` (`docType: vendorQuote`) | Q9 |
| `quotedPrices` | array<object> | no | `[]` | `{ estimateLineId, amount, currency, validUntil, leadTimeDays, notes }` | FR-16 (C53) |
| `blocksBid` | bool | yes | `false` | `true` when the bid cannot be delivered without this | Matrix 6.6 (G23) |
| `notes` | string | no | null | | Matrix 6.6 |
| *envelope* | — | — | — | | §4.2 |

**State machine** (`status`): `draft` → `requested` → `awaiting` → `received` → `applied`; plus `expired` (from `awaiting` or `received`, when `validUntil` passes) and `cancelled` (from any pre-`applied` state).

**Relationships:** `bidRequestId` → `bidRequests` (N:1); `vendorId` → `vendors` (N:1); `responseDocumentId` → `documents` (N:1); referenced by `estimateLines.vendorRfqId` (1:N).

**Indexes:**
- `{ orgId: 1, rfqNumber: 1 }` — **unique**.
- `{ orgId: 1, bidRequestId: 1, status: 1 }` — outstanding RFQs on a bid.
- `{ orgId: 1, status: 1, dueBy: 1 }` — **partial** (`status: { $in: ["requested","awaiting"] }`) — the chase list, due-date ordered.
- `{ orgId: 1, blocksBid: 1, status: 1 }` — **partial** (`blocksBid: true`) — what is holding up delivery.
- `{ orgId: 1, vendorId: 1, requestedAt: -1 }` — vendor responsiveness, and the data that will eventually answer Open Item 12's turnaround question.

```javascript
db.createCollection("vendorRfqs", {
  validator: { $jsonSchema: {
    bsonType: "object",
    required: [...envelopeRequired, "rfqNumber", "bidRequestId", "vendorId",
               "triggerReason", "requestedItems", "status", "statusHistory", "blocksBid"],
    properties: {
      ...envelope,
      _id: { bsonType: "objectId" },
      rfqNumber: { bsonType: "string" },
      bidRequestId: { bsonType: "objectId" },
      vendorId: { bsonType: "objectId" },
      triggerReason: { enum: ["customSize", "unusualPrep", "notSoldInYears",
                              "nonStock", "firstTime", "beyondCutoff"] },
      status: { enum: ["draft", "requested", "awaiting", "received",
                       "applied", "expired", "cancelled"] },
      statusHistory: statusHistory,
      requestedAt: { bsonType: ["date", "null"] },
      requestedBy: { bsonType: ["objectId", "null"] },
      dueBy: { bsonType: ["date", "null"] },
      respondedAt: { bsonType: ["date", "null"] },
      responseDocumentId: { bsonType: ["objectId", "null"] },
      blocksBid: { bsonType: "bool" },
      notes: { bsonType: ["string", "null"] },
      requestedItems: { bsonType: "array", items: {
        bsonType: "object",
        required: ["description", "quantity"],
        properties: {
          description: { bsonType: "string" },
          partNumber: { bsonType: ["string", "null"] },
          quantity: { bsonType: "double", minimum: 0 },
          sizeCode: { bsonType: ["string", "null"] },
          finishCode: { bsonType: ["string", "null"] },
          options: { bsonType: ["object", "null"] },
          estimateLineId: { bsonType: ["objectId", "null"] } } } },
      quotedPrices: { bsonType: "array", items: {
        bsonType: "object",
        required: ["amount", "currency"],
        properties: {
          estimateLineId: { bsonType: ["objectId", "null"] },
          amount: { bsonType: "double", minimum: 0 },
          currency: { enum: ["USD"] },
          validUntil: { bsonType: ["date", "null"] },
          leadTimeDays: { bsonType: ["int", "null"], minimum: 0 },
          notes: { bsonType: ["string", "null"] } } } }
    }
  } }
});
db.vendorRfqs.createIndex({ orgId: 1, rfqNumber: 1 }, { unique: true });
db.vendorRfqs.createIndex({ orgId: 1, bidRequestId: 1, status: 1 });
db.vendorRfqs.createIndex({ orgId: 1, status: 1, dueBy: 1 },
  { partialFilterExpression: { status: { $in: ["requested", "awaiting"] } } });
db.vendorRfqs.createIndex({ orgId: 1, blocksBid: 1, status: 1 },
  { partialFilterExpression: { blocksBid: true } });
db.vendorRfqs.createIndex({ orgId: 1, vendorId: 1, requestedAt: -1 });
```

**Notes:** `requestedItems[]` and `quotedPrices[]` are embedded because an RFQ covers a handful of items and both arrays are always read with the parent. `estimateLineId` appears in both so the returned price can be slotted straight back into the draft, which is precisely FR-16's requirement. `respondedAt` minus `requestedAt` will, over time, answer Open Item 12's unanswered turnaround question from real data rather than recollection.

---

### 3.29 `rfis`

**Purpose:** Requests for information raised for unclear or missing bid information before finalizing (Flow Phase 5). Also the natural home for direct-equal substitution approvals sought from the GC (Matrix 6.4).

**`_id` strategy:** `ObjectId`.

| Field | Type | Required | Default | Description | Source |
|---|---|---|---|---|---|
| `_id` | objectId | yes | auto | | — |
| `bidRequestId` | objectId | yes | — | → `bidRequests` | Flow C11 |
| `rfiNumber` | string | yes | — | | Flow Phase 5 |
| `subject` | string | yes | — | | Flow C11 |
| `question` | string | yes | — | | Flow C11 |
| `category` | string (enum) | yes | — | `missingRating` \| `missingHanding` \| `missingFinish` \| `scopeAmbiguity` \| `substitutionApproval` \| `quantityAmbiguity` \| `other` | Flow C11; Matrix 6.4, 7.3 |
| `relatedOpeningIds` | array<objectId> | no | `[]` | → `openings` | Flow C11 |
| `relatedEstimateLineIds` | array<objectId> | no | `[]` | → `estimateLines` | Matrix 6.4 |
| `raisedBy` | objectId | no | null | → `users` | Flow C11 |
| `raisedAt` | date | yes | — | | Flow C11 |
| `sentToParty` | string (enum) | no | null | `gc` \| `architect` \| `initiator` \| `vendor` | Matrix 6.4 (D21) |
| `status` | string (enum) | yes | `open` | `open` \| `sent` \| `answered` \| `closed` \| `withdrawn` | Flow C11 |
| `statusHistory` | array<object> | yes | `[]` | | §4.5 |
| `answer` | string | no | null | | Flow C11 |
| `answeredAt` | date | no | null | | Flow C11 |
| `blocksFinalization` | bool | yes | `false` | *"before finalizing"* | Flow C11 |
| *envelope* | — | — | — | | §4.2 |

**Relationships:** `bidRequestId` → `bidRequests` (N:1); `relatedOpeningIds[]` → `openings` (N:N); `relatedEstimateLineIds[]` → `estimateLines` (N:N).

**Indexes:**
- `{ orgId: 1, bidRequestId: 1, status: 1 }` — open RFIs on a bid.
- `{ orgId: 1, rfiNumber: 1 }` — **unique**.
- `{ orgId: 1, blocksFinalization: 1, status: 1 }` — **partial** (`blocksFinalization: true`) — what prevents approval.
- `{ orgId: 1, category: 1, raisedAt: -1 }` — RFI-category frequency. This is the evidence that will eventually answer Open Item 9: if `missingRating` dominates, the fire-rating gap is measurable rather than anecdotal.

```javascript
db.createCollection("rfis", {
  validator: { $jsonSchema: {
    bsonType: "object",
    required: [...envelopeRequired, "bidRequestId", "rfiNumber", "subject", "question",
               "category", "raisedAt", "status", "statusHistory", "blocksFinalization"],
    properties: {
      ...envelope,
      _id: { bsonType: "objectId" },
      bidRequestId: { bsonType: "objectId" },
      rfiNumber: { bsonType: "string" },
      subject: { bsonType: "string" },
      question: { bsonType: "string" },
      category: { enum: ["missingRating", "missingHanding", "missingFinish", "scopeAmbiguity",
                         "substitutionApproval", "quantityAmbiguity", "other"] },
      relatedOpeningIds: { bsonType: "array", items: { bsonType: "objectId" } },
      relatedEstimateLineIds: { bsonType: "array", items: { bsonType: "objectId" } },
      raisedBy: { bsonType: ["objectId", "null"] },
      raisedAt: { bsonType: "date" },
      sentToParty: { enum: ["gc", "architect", "initiator", "vendor", null] },
      status: { enum: ["open", "sent", "answered", "closed", "withdrawn"] },
      statusHistory: statusHistory,
      answer: { bsonType: ["string", "null"] },
      answeredAt: { bsonType: ["date", "null"] },
      blocksFinalization: { bsonType: "bool" }
    }
  } }
});
db.rfis.createIndex({ orgId: 1, bidRequestId: 1, status: 1 });
db.rfis.createIndex({ orgId: 1, rfiNumber: 1 }, { unique: true });
db.rfis.createIndex({ orgId: 1, blocksFinalization: 1, status: 1 },
  { partialFilterExpression: { blocksFinalization: true } });
db.rfis.createIndex({ orgId: 1, category: 1, raisedAt: -1 });
```

---

### 3.30 `proposals`

**Purpose:** The exported customer-facing PDF and its delivery record (FR-10, Flow Phase 6). The delivery rule from the 14 Jul session is specific and is enforced here: the export goes **back to whoever initiated the request in the queue** — Kellan, Matt, Rebecca or Tina — **not a group email**; that person then deals with the customer.

**`_id` strategy:** `ObjectId`.

| Field | Type | Required | Default | Description | Source |
|---|---|---|---|---|---|
| `_id` | objectId | yes | auto | | — |
| `estimateVersionId` | objectId | yes | — | → `estimateVersions` (1:1) | FR-10 |
| `estimateId` | objectId | yes | — | Denormalized for the proposal history list | §4.8 |
| `bidRequestId` | objectId | yes | — | Denormalized | §4.8 |
| `proposalNumber` | string | yes | — | | FR-10 |
| `storageUri` | string | yes | — | External object storage, or GridFS for small generated PDFs | Q9 |
| `gridFsFileId` | objectId | no | null | Set when stored in GridFS instead | Q9 |
| `checksum` | string | yes | — | | Q9 |
| `byteSize` | long | yes | — | | Q9 |
| `generatedAt` | date | yes | — | | FR-10 |
| `generatedBy` | objectId | no | null | → `users` | FR-10 |
| `approvedBy` | objectId | yes | — | → `users`. **Required — a proposal cannot exist without a human approval** | NFR-1 (D55) |
| `sentAt` | date | no | null | Null = generated but not yet sent | FR-10 |
| `sentToUserId` | objectId | no | null | → `users`; the initiator | FR-10 (I47) |
| `sentToEmail` | string | no | null | Individual address | FR-10 (I47) |
| `deliveryChannel` | string (enum) | yes | `outlook` | `outlook` \| `download` \| `other` | Flow D12 |
| `termsSnapshot` | object | yes | — | `{ templateId, validityDays, poRequired, supplyOnly, bodyMarkdown }` frozen | FR-10; Q7 |
| `totalsSnapshot` | object | yes | — | Copy of `estimateVersions.totals` as rendered | Q7 |
| `status` | string (enum) | yes | `generated` | `generated` \| `sent` \| `superseded` \| `withdrawn` | FR-10 |
| `statusHistory` | array<object> | yes | `[]` | | Q3; §4.5 |
| `supersededByProposalId` | objectId | no | null | → `proposals`; set on re-issue after an addendum | Flow C10 |
| *envelope* | — | — | — | | §4.2 |

**Relationships:** `estimateVersionId` → `estimateVersions` (1:1); `sentToUserId` / `approvedBy` / `generatedBy` → `users` (N:1); `supersededByProposalId` → self.

**Indexes:**
- `{ orgId: 1, estimateVersionId: 1 }` — **unique**. One proposal per version.
- `{ orgId: 1, proposalNumber: 1 }` — **unique**.
- `{ orgId: 1, bidRequestId: 1, generatedAt: -1 }` — proposal history for a bid, including re-issues.
- `{ orgId: 1, sentToUserId: 1, sentAt: -1 }` — **partial** (`sentAt` non-null) — the sales-side "what was sent to me" view.
- `{ orgId: 1, status: 1, generatedAt: -1 }` — delivery monitoring; catches proposals generated but never sent.

```javascript
db.createCollection("proposals", {
  validator: { $jsonSchema: {
    bsonType: "object",
    required: [...envelopeRequired, "estimateVersionId", "estimateId", "bidRequestId",
               "proposalNumber", "storageUri", "checksum", "byteSize", "generatedAt",
               "approvedBy", "deliveryChannel", "termsSnapshot", "totalsSnapshot",
               "status", "statusHistory"],
    properties: {
      ...envelope,
      _id: { bsonType: "objectId" },
      estimateVersionId: { bsonType: "objectId" },
      estimateId: { bsonType: "objectId" },
      bidRequestId: { bsonType: "objectId" },
      proposalNumber: { bsonType: "string" },
      storageUri: { bsonType: "string" },
      gridFsFileId: { bsonType: ["objectId", "null"] },
      checksum: { bsonType: "string" },
      byteSize: { bsonType: "long", minimum: 0 },
      generatedAt: { bsonType: "date" },
      generatedBy: { bsonType: ["objectId", "null"] },
      approvedBy: { bsonType: "objectId" },
      sentAt: { bsonType: ["date", "null"] },
      sentToUserId: { bsonType: ["objectId", "null"] },
      sentToEmail: { bsonType: ["string", "null"] },
      deliveryChannel: { enum: ["outlook", "download", "other"] },
      status: { enum: ["generated", "sent", "superseded", "withdrawn"] },
      statusHistory: statusHistory,
      supersededByProposalId: { bsonType: ["objectId", "null"] },
      termsSnapshot: { bsonType: "object",
        required: ["validityDays", "poRequired", "supplyOnly"],
        properties: {
          templateId: { bsonType: ["objectId", "null"] },
          validityDays: { bsonType: "int", minimum: 1 },
          poRequired: { bsonType: "bool" },
          supplyOnly: { bsonType: "bool" },
          bodyMarkdown: { bsonType: ["string", "null"] } } },
      totalsSnapshot: { bsonType: "object",
        required: ["grandTotal", "currency"],
        properties: {
          baseSubtotal: { bsonType: ["double", "null"] },
          alternateSubtotals: { bsonType: ["array", "null"] },
          freightAmount: { bsonType: ["double", "null"] },
          taxAmount: { bsonType: ["double", "null"] },
          grandTotal: { bsonType: "double" },
          currency: { enum: ["USD"] } } }
    }
  } }
});
db.proposals.createIndex({ orgId: 1, estimateVersionId: 1 }, { unique: true });
db.proposals.createIndex({ orgId: 1, proposalNumber: 1 }, { unique: true });
db.proposals.createIndex({ orgId: 1, bidRequestId: 1, generatedAt: -1 });
db.proposals.createIndex({ orgId: 1, sentToUserId: 1, sentAt: -1 },
  { partialFilterExpression: { sentAt: { $type: "date" } } });
db.proposals.createIndex({ orgId: 1, status: 1, generatedAt: -1 });
```

**Notes:** `approvedBy` is **required**, not optional. This is the strongest available schema-level expression of NFR-1 — *no estimate or quote is sent to a customer without explicit estimator approval.* A proposal document literally cannot be inserted without naming the human who approved it, so an automated send path cannot be built by accident.

`sentToUserId` points at a `users` document rather than storing only an address, because the requirement is about *a specific person*, not an address string. Storing both means the historical record survives even if the person changes email.

---

### 3.31 `feedbackEvents`

**Purpose:** FR-13 — *capture estimator corrections as structured feedback to improve future matching.* The 14 Jul session framed this as the long-term direction: *"keep feeding it information and grow it."* This collection is the structured record of every correction, which is what makes improvement measurable rather than anecdotal.

**`_id` strategy:** `ObjectId`.

| Field | Type | Required | Default | Description | Source |
|---|---|---|---|---|---|
| `_id` | objectId | yes | auto | | — |
| `estimateLineId` | objectId | no | null | → `estimateLines` | FR-13 |
| `openingId` | objectId | no | null | → `openings` — extraction corrections | FR-2, FR-13 |
| `bidRequestId` | objectId | yes | — | → `bidRequests` | FR-13 |
| `eventType` | string (enum) | yes | — | `matchRejected` \| `matchCorrected` \| `costOverridden` \| `marginOverridden` \| `lineAdded` \| `lineDeleted` \| `extractionCorrected` \| `substitutionMade` | FR-13; FR-9 (C46) |
| `field` | string | no | null | Which field was corrected | FR-13 |
| `proposedValue` | object | no | null | What the copilot proposed (typed as an object to hold any shape) | FR-13 |
| `correctedValue` | object | no | null | What the estimator chose | FR-13 |
| `proposedCatalogItemId` | objectId | no | null | → `catalogItems` | FR-4, FR-13 |
| `correctedCatalogItemId` | objectId | no | null | → `catalogItems` | FR-13 |
| `matchConfidenceAtTime` | double | no | null | Confidence the copilot reported when it was wrong (or right) | FR-8, FR-13 |
| `reason` | string | no | null | Estimator's stated reason | FR-13 |
| `userId` | objectId | yes | — | → `users` | FR-13 |
| `occurredAt` | date | yes | — | | FR-13 |
| `appliedToLearning` | bool | yes | `false` | Whether this event has been consumed by a retraining/tuning pass | FR-13 |
| *envelope* | — | — | — | | §4.2 |

**Relationships:** `estimateLineId` → `estimateLines`; `openingId` → `openings`; `bidRequestId` → `bidRequests`; `userId` → `users`; catalog item pointers → `catalogItems` (all N:1).

**Indexes:**
- `{ orgId: 1, eventType: 1, occurredAt: -1 }` — correction-type frequency over time; the core improvement metric.
- `{ orgId: 1, proposedCatalogItemId: 1, eventType: 1 }` — **partial** (non-null) — "which library items get rejected most", the direct input to library curation.
- `{ orgId: 1, appliedToLearning: 1, occurredAt: 1 }` — **partial** (`appliedToLearning: false`) — the unconsumed-feedback queue.
- `{ orgId: 1, bidRequestId: 1, occurredAt: -1 }` — corrections on one bid.

```javascript
db.createCollection("feedbackEvents", {
  validator: { $jsonSchema: {
    bsonType: "object",
    required: [...envelopeRequired, "bidRequestId", "eventType", "userId",
               "occurredAt", "appliedToLearning"],
    properties: {
      ...envelope,
      _id: { bsonType: "objectId" },
      estimateLineId: { bsonType: ["objectId", "null"] },
      openingId: { bsonType: ["objectId", "null"] },
      bidRequestId: { bsonType: "objectId" },
      eventType: { enum: ["matchRejected", "matchCorrected", "costOverridden",
                          "marginOverridden", "lineAdded", "lineDeleted",
                          "extractionCorrected", "substitutionMade"] },
      field: { bsonType: ["string", "null"] },
      proposedValue: { bsonType: ["object", "null"] },
      correctedValue: { bsonType: ["object", "null"] },
      proposedCatalogItemId: { bsonType: ["objectId", "null"] },
      correctedCatalogItemId: { bsonType: ["objectId", "null"] },
      matchConfidenceAtTime: { bsonType: ["double", "null"], minimum: 0, maximum: 1 },
      reason: { bsonType: ["string", "null"] },
      userId: { bsonType: "objectId" },
      occurredAt: { bsonType: "date" },
      appliedToLearning: { bsonType: "bool" }
    }
  } }
});
db.feedbackEvents.createIndex({ orgId: 1, eventType: 1, occurredAt: -1 });
db.feedbackEvents.createIndex({ orgId: 1, proposedCatalogItemId: 1, eventType: 1 },
  { partialFilterExpression: { proposedCatalogItemId: { $type: "objectId" } } });
db.feedbackEvents.createIndex({ orgId: 1, appliedToLearning: 1, occurredAt: 1 },
  { partialFilterExpression: { appliedToLearning: false } });
db.feedbackEvents.createIndex({ orgId: 1, bidRequestId: 1, occurredAt: -1 });
```

**Notes:** `proposedValue` and `correctedValue` are typed as generic objects rather than strings because the corrected thing might be a number, a part number, an enum, or a whole option set. Wrapping them (`{ value: ... }`) keeps the collection usable for every `eventType` without a discriminated union per field. `matchConfidenceAtTime` is the field that makes confidence calibration measurable — if corrections cluster at high reported confidence, the score is miscalibrated and FR-8's flagging threshold needs to move.

**This collection is not `auditLogs`.** Feedback is about *what the copilot got wrong and what the right answer was*, for improving matching. Audit is about *who changed what and when*, for accountability. Merging them would make both queries slower and the learning signal noisier.

---

### 3.31a `matchLearning`

**Purpose:** FR-13's *output*. §3.31 captures each correction; this is what the corrections add up to — one row per specification an estimator has ruled on, holding the catalog part they chose and how often they have chosen it. `feedbackEvents` is the journal; this is the balance.

Deliberately a lookup table and not a model: it is auditable by name and date, useful on the second bid, and needs no training run to be either. Owned by `catalog` (a learned answer is a catalog fact); written by `extraction.api.feedback.apply_to_learning`, which drains the queue it owns.

**`_id` strategy:** `ObjectId`.

| Field | Type | Required | Default | Description | Source |
|---|---|---|---|---|---|
| `_id` | objectId | yes | auto | | — |
| `specKey` | string | yes | — | The specification, normalised by `catalog.domain.partquery.spec_key` — the same normaliser the catalog lookup uses, so both agree on what a spec string is | FR-13 |
| `specSample` | string | no | null | The most recent raw spec, for display | FR-13 |
| `catalogItemId` | objectId | yes | — | → `catalogItems` — what the estimator chose | FR-4, FR-13 |
| `part` / `manufacturer` / `division` | string | no | null | Denormalised from the catalog row, so a recall needs no join | FR-13 |
| `confirmCount` | int | yes | `0` | How many times an estimator has chosen this part for this spec | FR-13 |
| `rejectCount` | int | yes | `0` | How many times one has rejected it. `confirmCount <= rejectCount` is never recalled | FR-13 |
| `lastConfirmedAt` / `lastConfirmedBy` | date / objectId | no | null | Who said so, and when — what a Tier 0 match cites (NFR-3) | FR-13, NFR-3 |
| `reasons` | string[] | no | `[]` | The estimators' stated reasons | FR-13 |
| `sourceEventIds` | objectId[] | no | `[]` | → `feedbackEvents` — the corrections this row was built from | FR-13 |
| *envelope* | — | — | — | | §4.2 |

**Indexes:**
- `{ orgId: 1, specKey: 1 }` — **unique**. One learned answer per specification, so re-draining cannot double-count a lesson.
- `{ orgId: 1, catalogItemId: 1, rejectCount: 1 }` — "which library items get rejected most", the curation question §3.31 asks and nothing could answer until this existed.

**Notes:** recall is exact-key first, then similarity over token sets, with part-number tokens treated as decisive — `275A` and `2750A` are different parts however alike the surrounding prose reads. The matcher reads this through `catalog.api.pageindex.reader.recall_match` (sync, read-only credential) as MCP tool `recall_match`; a hit is **Tier 0 (0.97)**. Fire rating, handing and finish still veto it: an estimator confirming a part on one opening did not confirm it for every opening, and a learned mistake nothing can overrule is worse than no learning at all.

---

### 3.32 `auditLogs`

**Purpose:** NFR-3's accountability record — who did what, when, to which entity. Distinct from the *pricing* audit trail, which lives in the frozen snapshots on `estimateLines` (Q7). This collection covers state transitions, approvals, overrides, reference-data edits, and P21 sync runs.

**`_id` strategy:** `ObjectId`.

| Field | Type | Required | Default | Description | Source |
|---|---|---|---|---|---|
| `_id` | objectId | yes | auto | | — |
| `entityType` | string (enum) | yes | — | `bidRequest` \| `estimate` \| `estimateVersion` \| `estimateLine` \| `opening` \| `takeoff` \| `proposal` \| `vendorRfq` \| `rfi` \| `catalogItem` \| `hardwareSet` \| `priceBook` \| `priceBookEntry` \| `vendorTier` \| `marginRule` \| `vendor` \| `customer` \| `user` \| `p21Sync` \| `other` | NFR-3 |
| `entityId` | objectId | no | null | Polymorphic reference; null for system-wide events (a sync run) | NFR-3 |
| `action` | string (enum) | yes | — | `create` \| `update` \| `delete` \| `softDelete` \| `restore` \| `statusChange` \| `approve` \| `send` \| `override` \| `import` \| `sync` \| `login` | NFR-3 |
| `userId` | objectId | no | null | → `users`; null for system/scheduled actions | NFR-3 |
| `actorType` | string (enum) | yes | `user` | `user` \| `system` \| `import` | NFR-3 |
| `occurredAt` | date | yes | — | | NFR-3 |
| `changes` | array<object> | no | `[]` | `{ field, from, to }` | NFR-3 |
| `context` | object | no | null | `{ bidRequestId, estimateId, estimateVersionId }` for scoped querying | NFR-3 |
| `reason` | string | no | null | Free text, e.g. an override justification | Matrix 6.1 (I18) |
| `ipAddress` | string | no | null | **Populated only if NFR-4's data-security owner requires it** | NFR-4; §6.3 |
| `userAgent` | string | no | null | Same condition as `ipAddress` | NFR-4 |
| *envelope* | — | — | — | `createdBy`/`updatedBy` unused here — `userId` is the actor | §4.2 |

**Relationships:** polymorphic — `entityId` + `entityType` together identify the target. `userId` → `users` (N:1). `context.*` → the respective collections.

**Indexes:**
- `{ orgId: 1, entityType: 1, entityId: 1, occurredAt: -1 }` — the audit trail for one record. Primary read.
- `{ orgId: 1, userId: 1, occurredAt: -1 }` — everything one person did.
- `{ orgId: 1, "context.bidRequestId": 1, occurredAt: -1 }` — **partial** (non-null) — the complete history of a bid across every entity it touched. This is the query NFR-3 is really asking for.
- `{ orgId: 1, action: 1, occurredAt: -1 }` — **partial** (`action: { $in: ["approve","send","override"] }`) — the high-sensitivity actions.
- `{ occurredAt: 1 }` — **TTL, disabled by default** (`expireAfterSeconds` unset). See notes.

```javascript
db.createCollection("auditLogs", {
  validator: { $jsonSchema: {
    bsonType: "object",
    required: [...envelopeRequired, "entityType", "action", "actorType", "occurredAt"],
    properties: {
      ...envelope,
      _id: { bsonType: "objectId" },
      entityType: { enum: ["bidRequest", "estimate", "estimateVersion", "estimateLine",
                           "opening", "takeoff", "proposal", "vendorRfq", "rfi", "catalogItem",
                           "hardwareSet", "priceBook", "priceBookEntry", "vendorTier",
                           "marginRule", "vendor", "customer", "user", "p21Sync", "other"] },
      entityId: { bsonType: ["objectId", "null"] },
      action: { enum: ["create", "update", "delete", "softDelete", "restore", "statusChange",
                       "approve", "send", "override", "import", "sync", "login"] },
      userId: { bsonType: ["objectId", "null"] },
      actorType: { enum: ["user", "system", "import"] },
      occurredAt: { bsonType: "date" },
      reason: { bsonType: ["string", "null"] },
      ipAddress: { bsonType: ["string", "null"] },
      userAgent: { bsonType: ["string", "null"] },
      changes: { bsonType: "array", items: {
        bsonType: "object",
        required: ["field"],
        properties: {
          field: { bsonType: "string" },
          from: {},
          to: {} } } },
      context: { bsonType: ["object", "null"], properties: {
        bidRequestId: { bsonType: ["objectId", "null"] },
        estimateId: { bsonType: ["objectId", "null"] },
        estimateVersionId: { bsonType: ["objectId", "null"] } } }
    }
  } }
});
db.auditLogs.createIndex({ orgId: 1, entityType: 1, entityId: 1, occurredAt: -1 });
db.auditLogs.createIndex({ orgId: 1, userId: 1, occurredAt: -1 });
db.auditLogs.createIndex({ orgId: 1, "context.bidRequestId": 1, occurredAt: -1 },
  { partialFilterExpression: { "context.bidRequestId": { $type: "objectId" } } });
db.auditLogs.createIndex({ orgId: 1, action: 1, occurredAt: -1 },
  { partialFilterExpression: { action: { $in: ["approve", "send", "override"] } } });
// TTL index intentionally NOT created until a retention policy exists (Q13, NFR-10).
// When a policy is set, e.g. 7 years:
//   db.auditLogs.createIndex({ occurredAt: 1 }, { expireAfterSeconds: 220752000 });
```

**Notes on the TTL index:** it is documented but **not created**. Q13 established that no retention rule exists in the workbook and that inventing one is not this document's call. Creating a TTL index with a guessed duration would silently destroy audit evidence — the worst possible failure mode for a collection whose entire purpose is evidence. The command is left ready for whoever holds the authority to set the number.

`changes[].from` and `.to` are declared with an empty schema `{}`, which in `$jsonSchema` means "any BSON type". This is deliberate: an audit entry must be able to record a change to any field of any type without the validator rejecting it.

---

## 4. Cross-Cutting Conventions

### 4.1 Multi-tenancy

**Strategy: shared collections with a leading `orgId`** (Q2). Every collection carries `orgId` and every compound index leads with it, so the tenant filter is always index-covered and a missing filter degrades to a scan that will be noticed in profiling rather than silently returning another tenant's data.

CBC is the only tenant today. The workbook (Matrix 2.0, I4) confirms modelling is scoped to CBC national-accounts estimating, with other Hamilton Parker divisions separate and out of scope but extensible later. Separate databases per division were rejected: the reference library (vendors, price books, finish codes, margin bands) would either be duplicated across databases or need a shared-database exception, and cross-division reporting would become an application-layer merge.

**Enforcement:** the data-access layer must inject `orgId` into every query. No collection has an index that omits it except the two text/`_id` cases noted in §5.

### 4.2 Auditing envelope

Every document carries:

| Field | Type | Semantics |
|---|---|---|
| `orgId` | objectId | Tenant scope (§4.1) |
| `schemaVersion` | int | Document schema version (§4.4) |
| `createdAt` | date | Set on insert, never modified |
| `updatedAt` | date | Set on every write |
| `createdBy` | objectId \| null | `users._id`; null for system and import writes |
| `updatedBy` | objectId \| null | Same |

This is the lightweight, always-on layer. The heavyweight accountability record is `auditLogs` (§3.32), written for state transitions, approvals, overrides, reference-data edits and sync runs — not for every field touch, which would swamp the collection without adding evidentiary value.

The **pricing** audit trail is a third, separate mechanism: the frozen snapshots on `estimateLines` (Q7). NFR-3 asks that every generated line be traceable to a source drawing page *and* to a reference-library / price-sheet version including vendor multiplier tier and effective date. That is satisfied by `sourceRef` (page) plus `priceBookSnapshot`, `multiplierTierSnapshot`, `costSnapshot` and `marginSnapshot` (pricing basis) — all resolvable without joining anything that may since have changed.

### 4.3 Soft delete

Applied to exactly five collections (Q13): `estimates`, `estimateVersions`, `bidRequests`, `priceBooks`, `vendors`.

| Field | Type | Semantics |
|---|---|---|
| `isDeleted` | bool | Default `false` |
| `deletedAt` | date \| null | |
| `deletedBy` | objectId \| null | |
| `retentionPolicy` | string \| null | **Intentionally unset** — e.g. `"7-year"` |

Every query on these collections must filter `isDeleted: false` unless explicitly restoring or auditing. The other twenty-seven collections use hard delete, because they are either append-only records (`auditLogs`, `feedbackEvents`), children whose parent's soft-delete already hides them (`estimateLines`, `openings`, `takeoffs`), or reference data that is deactivated via `active: false` rather than deleted.

`retentionPolicy` is present-but-null by design. The workbook gives no retention rule anywhere, and Q13 was explicit that this is a business decision not to be manufactured. The field exists and is queryable so that setting a policy later is a data change, not a migration.

### 4.4 Schema versioning

Every document carries `schemaVersion: 1`. The workbook describes a long-lived engagement with ongoing maintenance (Matrix 8.1 I36, NFR-11 I65), and several collections are explicitly waiting on data that will reshape them — FRP constants (Open 5), Hager adder values (NR-7), light-kit table logic (NR-8), fire-rating placement (Open 9). When a shape changes, new documents are written at version N+1 and readers handle both until a backfill completes. This is cheaper than a stop-the-world migration on an operational estimating desk.

### 4.5 Status history and state machines

Six collections carry a `statusHistory` array of `{ from, to, at, by, note }`: `bidRequests`, `estimateVersions`, `estimateLines`, `vendorRfqs`, `rfis`, `proposals`. Embedded rather than a separate collection because transitions are bounded (a handful per record), always read with the parent, and never queried independently of it.

This is the mechanism Q3 depends on. With every transition timestamped and attributed, the KPIs named in Open Item 16 — turnaround, hours per bid, hit rate — are computable by aggregation over data already being written, so the absent Business Case & Metrics sheet costs nothing structurally.

Full transition tables are documented per collection in §3.21, §3.26, §3.27, §3.28, §3.29 and §3.30.

### 4.6 Effective dating

Reference data that changes over time is **versioned by effective date, never updated in place**: `priceBooks`, `priceBookEntries` (via their book), `vendorTiers`, `marginRules`, `adders`, `lightKitRates`, `taxRules`, `commercialTermsTemplates`, `frpConstants`.

Convention: `effectiveFrom` (required) and `effectiveTo` (null = currently in force). The "current" record is resolved with a partial index on `effectiveTo: null` where the access pattern is hot, or by `effectiveFrom: -1` sort otherwise.

This exists because Matrix 6.3 (D20) records that price changes arrive as **dated memos with a protection window** — an in-place update would destroy the ability to answer "what was the price when we quoted this?", which NFR-3 requires.

### 4.7 Money, rates, and the quote calculation

- **Currency:** `USD` throughout, stored explicitly on every monetary document so a future Canadian job (Matrix 2.4 mentions Canada) is a data change, not a migration.
- **Numeric type:** `double`. Not `decimal128`, which would be the stricter choice — see the trade-off note in §6.2, assumption A-19.
- **Rates are decimals, never percentages:** `0.27`, not `27`. Enforced by validators (`minimum: 0, exclusiveMaximum: 1`).
- **Margin is stored as margin, never as the divisor.** The divisor is always derived.

The quote calculation, exactly as specified in Matrix 5.0 (D16) and validated in the 14 Jul session:

```
salePriceEach  = ourCost / (1 - marginRate)
unitPrice      = salePriceEach
extendedPrice  = unitPrice     × quantity
lineSubtotal   = salePriceEach × quantity
groupSubtotal  = SUM(lineSubtotal) for lines in the group
grandTotal     = SUM(groupSubtotal) [+ freight] [+ tax]
```

Worked example from Matrix 6.1/6.3: a Hager 3500-series storeroom lock lists at $256.31; the "50 & 42" discount chain gives a 0.29 multiplier, so cost ≈ $74.33; at the commodity band of 27%, sale ≈ $74.33 / 0.73 ≈ $101.82 each.

**Explicitly not modelled:** `unitWeight` and `totalWeight`. Matrix 5.0 (I16) instructs their removal as legacy from truck-loading years ago.

### 4.8 Denormalization register

Every duplicated field in the schema, with its sync rule. Nothing is denormalized that is not listed here.

| Field | Copied from | Why | Sync rule |
|---|---|---|---|
| `catalogItems.p21ItemId` | `p21ItemMappings.p21ItemId` | Line-review grid renders without a join | Written only by the P21 sync job; mapping is authoritative |
| `priceBookEntries.vendorId` | `priceBooks.vendorId` | Enables `{ vendorId, partNumber }` price lookup without loading the book | Immutable — written once at ingestion |
| `estimates.currentVersionId` / `.currentVersionNumber` / `.versionCount` / `.hasAlternates` | `estimateVersions` | "Open the current quote" is the hottest read | Updated in the same operation that creates a version; chain wins on conflict |
| `estimateLines.estimateId` | `estimateVersions.estimateId` | Cross-version line queries without a join | Immutable per line |
| `estimateLines.vendorId` | `catalogItems.vendorId` | Vendor-exposure index (Hager ≈ 75% of volume) | Frozen at pricing time — historical lines keep the vendor actually quoted |
| `estimateLines.partNumber` | `catalogItems.partNumber` | Proposal rendering and audit | Frozen at pricing time |
| `proposals.estimateId` / `.bidRequestId` | `estimateVersions` | Proposal history list without two joins | Immutable |
| `priceBooks.entryCount` | count of `priceBookEntries` | Admin list | Updated at ingestion |
| All `*Snapshot` sub-documents on `estimateLines` | Various reference collections | NFR-3 reproducibility (Q7) | **Never synced** — frozen by design |

The snapshots are the important row. They are not caches and must never be refreshed: their whole purpose is to record what was true at pricing time.

### 4.9 File and attachment handling

**External object storage with `storageUri` + `checksum`** (Q9). Bid sets run to hundreds of pages and arrive as one combined PDF or several separate files (Matrix 8.0, I35); they do not belong in MongoDB documents or in GridFS. `documents` holds metadata only: `fileName`, `storageUri`, `checksum` (SHA-256), `byteSize` (`long`), `mimeType`, `pageCount`, `sourceType`, `ocrStatus`, and the embedded `pages[]` index.

GridFS is permitted for one narrow case: small, system-generated artifacts, specifically proposal PDFs the application itself creates (`proposals.gridFsFileId`). Even there, `storageUri` is the preferred path.

`checksum` is unique per org on `documents`, which deduplicates the common case where the same drawing arrives both inside a combined set and again as a separate file.

### 4.10 Enum strategy

Following the brief's rule — stable and small enums are inlined and validated; large, growing, or admin-editable value sets get their own collection.

**Inlined as validated enums:** fire ratings (`20`/`45`/`60`/`90`/`none`), handing (`LH`/`RH`/`LHR`/`RHR`), swing, user roles, intake channels, all workflow statuses, cost sources, margin bands, line types, group types, document types, units of measure, CSI divisions, `vendorType`, `purchasePath`, `matchStatus`, `freshness`, `conversionMethod`, `triggerReason`, `entityType`, `action`.

**Given their own collections** because they grow or are admin-maintained: `productTypes`, `vendors`, `catalogItems`, `hardwareSets`, `finishCodes`, `frameDepths`, `marginRules`, `adders`, `lightKitRates`, `taxRules`, `frpConstants`, `commercialTermsTemplates`.

Two borderline calls worth stating. **Margin bands** are inlined as an enum (five stable values, unchanged for ~14 years per Matrix 6.1) while their *rates* live in `marginRules` — the names are stable, the numbers are not. **Frame depths** got a collection despite being only ~7 values, because Matrix 7.0 (I26) requires a custom manual-entry option alongside the five standards, which means the set is user-extensible, which means it is data.

### 4.11 Referential integrity

MongoDB does not enforce foreign keys. Conventions:

- ObjectId references are validated at the application layer on write.
- Small stable lookups (`finishCodes`, `frameDepths`) are referenced **by string `code`**, validated by pattern plus an application check. The trade-off is discussed in §3.18 — the payoff is that a raw `estimateLines` document is readable without joins during support work.
- Reference data is **deactivated (`active: false`), never deleted**, so historical documents always resolve. Scranton and American Dryer are the live examples (Matrix 2.2, I6).
- Cascade behaviour: soft-deleting a `bidRequest` hides its `openings`, `takeoffs`, `estimates` and `estimateLines` by application-level filtering; it does not delete them.

---

## 5. Indexing Summary

Every index in the schema. `orgId` leads all compound indexes per §4.1.

| Collection | Index fields | Type | Query it serves |
|---|---|---|---|
| `organizations` | `{ code: 1 }` | unique | Tenant resolution at bootstrap |
| `users` | `{ orgId, email }` | unique | Login; initiator resolution from an inbound email |
| `users` | `{ orgId, role, active }` | compound | Estimator assignment; sales-initiator picker (FR-10) |
| `customers` | `{ orgId, name }` | unique | Duplicate prevention at intake |
| `customers` | `{ orgId, brandProgramId }` | partial | All customers under a brand (FR-11) |
| `customers` | `{ orgId, shipToState }` | compound | Tax-rule resolution (Matrix 2.4) |
| `brandPrograms` | `{ orgId, name }` | unique | Lookup |
| `brandPrograms` | `{ orgId, active }` | compound | Picker population |
| `taxRules` | `{ orgId, country, state, effectiveFrom: -1 }` | compound | Current rule for a ship-to |
| `taxRules` | `{ orgId, effectiveTo }` | partial (`null`) | Rules in force — admin |
| `commercialTermsTemplates` | `{ orgId, isDefault, effectiveTo }` | partial | Current default terms at export |
| `commercialTermsTemplates` | `{ orgId, name, effectiveFrom: -1 }` | unique | Template version history |
| `productTypes` | `{ orgId, code }` | unique | Lookup |
| `productTypes` | `{ orgId, inScope, family }` | compound | Scope guard (Open 7); picker grouping |
| `vendors` | `{ orgId, name }` | unique | Lookup |
| `vendors` | `{ orgId, isTop10, active }` | compound | Phase 1 vendor slice (Matrix 6.3) |
| `vendors` | `{ orgId, requiresManualPrice }` | partial (`true`) | Manual-entry / refresh prompt (NR-2) |
| `vendors` | `{ orgId, isDeleted, active }` | compound | Admin list |
| `catalogItems` | `{ orgId, vendorId, partNumber }` | unique | Primary lookup; price-book reconciliation |
| `catalogItems` | `{ orgId, productTypeId, isStock, stockRank }` | compound | Top-10 item picker (NR-6) |
| `catalogItems` | `{ orgId, partNumber }` | compound | Cross-vendor part search from a spec callout |
| `catalogItems` | `{ orgId, productTypeId, "options.function", defaultFinishCode }` | compound | Attribute matching / direct-equal (Matrix 6.4) |
| `catalogItems` | `{ orgId, fireRatings, productTypeId }` | multikey | Rating-constrained matching (FR-4, Q5) |
| `catalogItems` | `{ description, searchTerms, partNumber }` | **text** | Free-text library search (FR-8) |
| `hardwareSets` | `{ orgId, setCode }` | unique, partial (`cbcLibrary`) | Library set lookup without colliding with spec sets |
| `hardwareSets` | `{ orgId, bidRequestId, setCode }` | partial | HW sets extracted from a bid |
| `hardwareSets` | `{ orgId, isStandard, applicableOpeningType, fireRating }` | compound | Set matching under rating constraint (FR-4) |
| `hardwareSets` | `{ orgId, "items.catalogItemId" }` | multikey | Which sets contain a part — discontinuation / tier impact |
| `adders` | `{ orgId, vendorId, code, effectiveFrom: -1 }` | unique | Current adder resolution |
| `adders` | `{ orgId, appliesToProductTypeIds, dataStatus }` | multikey | Offerable adders for a line (NR-4) |
| `lightKitRates` | `{ orgId, vendorId, kitType, glazingType, widthIn, heightIn }` | compound | Light-kit calculator lookup (NR-1) |
| `lightKitRates` | `{ orgId, dataStatus }` | compound | Outstanding data (NR-8) |
| `priceBooks` | `{ orgId, vendorId, version }` | unique | Lookup |
| `priceBooks` | `{ orgId, vendorId, effectiveFrom: -1 }` | compound | Current book for a vendor at pricing time |
| `priceBooks` | `{ orgId, effectiveTo, isDeleted }` | partial (`null`) | Live sheets — stewardship (NFR-10) |
| `priceBookEntries` | `{ orgId, priceBookId, partNumber }` | unique | Ingestion idempotency |
| `priceBookEntries` | `{ orgId, vendorId, partNumber }` | compound | Current list price for a part (FR-6) |
| `priceBookEntries` | `{ orgId, catalogItemId }` | partial | Pricing from a matched library item |
| `vendorTiers` | `{ orgId, vendorId, tierCode, effectiveFrom: -1 }` | unique | Tier history |
| `vendorTiers` | `{ orgId, vendorId, effectiveTo }` | partial (`null`) | Tier in force at pricing time (Matrix 6.3) |
| `marginRules` | `{ orgId, scope, customerId, brandProgramId, productTypeId, effectiveTo }` | compound | Full margin-resolution chain (Q11) |
| `marginRules` | `{ orgId, band, effectiveFrom: -1 }` | compound | Band history for audit |
| `p21ItemMappings` | `{ orgId, p21ItemId }` | unique | Sync idempotency |
| `p21ItemMappings` | `{ orgId, mfrPartNumber }` | partial | Cost lookup by manufacturer part number |
| `p21ItemMappings` | `{ orgId, catalogItemId, freshness }` | partial | Usable cost for a library item (FR-6) |
| `p21ItemMappings` | `{ orgId, matchStatus, lastSyncedAt: -1 }` | compound | Unmatched / semi-item reconciliation worklist (NR-10) |
| `frameDepths` | `{ orgId, code }` | unique | Lookup |
| `frameDepths` | `{ orgId, wallType, active }` | compound | Depth auto-selection from wall type (Matrix 7.0) |
| `finishCodes` | `{ orgId, code }` | unique | Lookup |
| `finishCodes` | `{ orgId, aliases }` | multikey | **Dual-nomenclature interpreter** (NR-3) |
| `finishCodes` | `{ orgId, isPremium }` | partial (`true`) | Premium-finish adder prompt (NR-4) |
| `frpConstants` | `{ orgId, vendorId, constantKey, effectiveFrom: -1 }` | unique | Constant resolution (FR-12) |
| `frpConstants` | `{ orgId, dataStatus }` | compound | Outstanding data (Open 5) |
| `bidRequests` | `{ orgId, bidNumber }` | unique | Lookup |
| `bidRequests` | `{ orgId, status, bidDueDate }` | compound | **Estimator work queue** — highest-frequency read |
| `bidRequests` | `{ orgId, assignedEstimatorId, status }` | compound | "My bids" |
| `bidRequests` | `{ orgId, customerId, receivedAt: -1 }` | compound | Prior-quote reuse by GC (FR-11) |
| `bidRequests` | `{ orgId, brandProgramId, receivedAt: -1 }` | compound | Prior-quote reuse by brand (FR-11) |
| `bidRequests` | `{ orgId, initiatorUserId, status }` | compound | Sales-side queue view (FR-10) |
| `bidRequests` | `{ orgId, isDeleted, receivedAt: -1 }` | compound | General listing |
| `documents` | `{ orgId, bidRequestId, docType }` | compound | A bid's document list |
| `documents` | `{ orgId, checksum }` | unique | Deduplication of combined vs separate PDFs |
| `documents` | `{ orgId, docType, receivedAt: -1 }` | partial (`addendum`) | Addendum feed (Flow 4b) |
| `documents` | `{ orgId, ocrStatus }` | partial | Extraction worklist / unparsed content (FR-8) |
| `openings` | `{ orgId, bidRequestId, doorNumber }` | unique | Extraction idempotency; door-grouped order (FR-7) |
| `openings` | `{ orgId, bidRequestId, reviewStatus }` | compound | Review worklist (FR-9) |
| `openings` | `{ orgId, ratingConflict }` | partial (`true`) | **Rated-opening defect check** (Matrix 7.3, Q5) |
| `openings` | `{ orgId, ratingMissing }` | partial (`true`) | Missing-rating flag (FR-8) |
| `openings` | `{ orgId, bidRequestId, hardwareSetCallout }` | compound | Openings grouped by HW set |
| `takeoffs` | `{ orgId, bidRequestId, takeoffType }` | compound | The bid's take-off sheet |
| `takeoffs` | `{ orgId, openingId }` | partial | Quantities for one opening |
| `takeoffs` | `{ orgId, bidRequestId, reviewStatus }` | compound | Review worklist (FR-9) |
| `estimates` | `{ orgId, bidRequestId }` | unique | One estimate per bid |
| `estimates` | `{ orgId, estimateNumber }` | unique | Lookup |
| `estimates` | `{ orgId, sourceType, isDeleted }` | compound | Native vs imported legacy (Q8) |
| `estimates` | `{ orgId, templateSourceEstimateId }` | partial | Reuse lineage (FR-11) |
| `estimateVersions` | `{ orgId, estimateId, versionNumber: -1 }` | unique | Version chain traversal (Q6) |
| `estimateVersions` | `{ orgId, estimateId, supersededByVersionId }` | partial (`null`) | Head of the chain |
| `estimateVersions` | `{ orgId, status, updatedAt: -1 }` | compound | Review and approval queues (FR-9) |
| `estimateVersions` | `{ orgId, hasUnresolvedFlags, status }` | partial (`true`) | "Nothing silently guessed" dashboard (NFR-2) |
| `estimateVersions` | `{ orgId, approvedAt: -1 }` | partial | Approval audit; future turnaround KPI (Q3) |
| `estimateLines` | `{ orgId, estimateVersionId, lineGroupId, sequence }` | compound | **Proposal render, in order** — primary read |
| `estimateLines` | `{ orgId, estimateVersionId, alternateId }` | compound | Base-vs-alternate comparison (Matrix 4.1) |
| `estimateLines` | `{ orgId, catalogItemId, createdAt: -1 }` | compound | **"Every line where a Hager 3500 was quoted"** (Q15) |
| `estimateLines` | `{ orgId, vendorId, createdAt: -1 }` | compound | Vendor exposure for tier renegotiation |
| `estimateLines` | `{ orgId, status, estimateVersionId }` | compound | What is still unpriced |
| `estimateLines` | `{ orgId, vendorRfqId }` | partial | Slot a returned RFQ price into its lines (FR-16) |
| `estimateLines` | `{ orgId, priceMayBeStale, estimateVersionId }` | partial (`true`) | Refresh prompt (NR-2) |
| `estimateLines` | `{ orgId, openingId }` | partial | All lines for one door |
| `vendorRfqs` | `{ orgId, rfqNumber }` | unique | Lookup |
| `vendorRfqs` | `{ orgId, bidRequestId, status }` | compound | Outstanding RFQs on a bid |
| `vendorRfqs` | `{ orgId, status, dueBy }` | partial | Chase list (Matrix 6.6) |
| `vendorRfqs` | `{ orgId, blocksBid, status }` | partial (`true`) | What is holding up delivery |
| `vendorRfqs` | `{ orgId, vendorId, requestedAt: -1 }` | compound | Vendor turnaround (answers Open 12 from data) |
| `rfis` | `{ orgId, bidRequestId, status }` | compound | Open RFIs on a bid |
| `rfis` | `{ orgId, rfiNumber }` | unique | Lookup |
| `rfis` | `{ orgId, blocksFinalization, status }` | partial (`true`) | What prevents approval |
| `rfis` | `{ orgId, category, raisedAt: -1 }` | compound | RFI-category frequency (evidence for Open 9) |
| `proposals` | `{ orgId, estimateVersionId }` | unique | One proposal per version |
| `proposals` | `{ orgId, proposalNumber }` | unique | Lookup |
| `proposals` | `{ orgId, bidRequestId, generatedAt: -1 }` | compound | Proposal history incl. re-issues |
| `proposals` | `{ orgId, sentToUserId, sentAt: -1 }` | partial | Sales-side "sent to me" (FR-10) |
| `proposals` | `{ orgId, status, generatedAt: -1 }` | compound | Generated-but-never-sent monitoring |
| `feedbackEvents` | `{ orgId, eventType, occurredAt: -1 }` | compound | Correction frequency over time (FR-13) |
| `feedbackEvents` | `{ orgId, proposedCatalogItemId, eventType }` | partial | Most-rejected library items — curation input |
| `feedbackEvents` | `{ orgId, appliedToLearning, occurredAt }` | partial (`false`) | Unconsumed-feedback queue |
| `feedbackEvents` | `{ orgId, bidRequestId, occurredAt: -1 }` | compound | Corrections on one bid |
| `auditLogs` | `{ orgId, entityType, entityId, occurredAt: -1 }` | compound | Audit trail for one record (NFR-3) |
| `auditLogs` | `{ orgId, userId, occurredAt: -1 }` | compound | Everything one person did |
| `auditLogs` | `{ orgId, "context.bidRequestId", occurredAt: -1 }` | partial | **Complete history of a bid** (NFR-3) |
| `auditLogs` | `{ orgId, action, occurredAt: -1 }` | partial | Approve / send / override events |
| `auditLogs` | `{ occurredAt: 1 }` | TTL — **not created** | Retention; blocked on Q13 |

**Count:** 111 indexes across 32 collections (excluding the default `_id` index on each, and the one documented-but-uncreated TTL index). Two do not lead with `orgId`: `organizations.{code}` (which resolves the tenant itself) and the `catalogItems` text index (MongoDB permits only one text index per collection and it cannot be usefully compounded with a leading equality field here — text queries must therefore include an `orgId` filter in the query predicate, which the data-access layer enforces).

Every index above maps to a query named in the workbook's described flows or in a Phase 1 decision. No speculative indexes were added.

---

## 6. Assumptions & Open Questions

### 6.1 Binding design decisions (Phase 1 decision round)

These fifteen decisions were made explicitly during the Phase 1 review, before schema design began. They are reproduced here with their original rationale so that any future reviewer can understand *why*, not just *what*, without needing access to the design conversation.

---

**Q1 — Scope of the database**
**Decision: Copilot application only.** Do not model requirement rows, confirmations, or open items as collections. The Requirements Matrix, Assumptions sheet, and Open Items sheet are inputs to this design exercise, not runtime data the app needs to persist. Modeling them would conflate a one-time governance artifact with a live operational schema.
*Affects:* the whole database. No `requirements`, `confirmations`, or `openItems` collections exist.

**Q2 — Multi-tenancy**
**Decision: Shared collections with `orgId` as the leading field in every compound index.** CBC is the only tenant today, but the workbook explicitly states other HP divisions may be added later. Adding `orgId` now costs nothing; retrofitting it into every collection and every query later is expensive and error-prone. Every collection in Phase 2 must carry `orgId`.
*Affects:* all 32 collections; §4.1; 109 of the 111 indexes.

**Q3 — Missing "Business Case & Metrics" sheet**
**Decision: Omit the KPI/metrics collection entirely.** Do not create a placeholder collection for data you have no field definitions for. Instead: ensure `estimates`, `bidRequests`, and `vendorRfqs` already carry full timestamped state-transition history (see Q6/Q7 decisions) so that when the metrics sheet eventually materializes, KPIs like turnaround time and hit rate can be computed from existing data via aggregation pipelines — no schema change required at that point.
*Note:* READ ME cell B13 lists a fourth tab, *"Business Case & Metrics — the 'why' and the numbers: strategic objectives, baseline, targets, and success criteria"*, described as new in v1.1. **That sheet is not present in `CBC_Req_Validation_v1_3.xlsx`.** Open Item 16 (baseline & target metrics — bids/month, hours/bid, turnaround, hit rate) remains `Open`, and Assumptions row 9 remains `Open` with only the directional hint that automating stock plus top-10 vendors could speed ~80–90% of quotes. **This is the reason no metrics collection exists in this schema.**
*Affects:* absence of a metrics collection; presence of `statusHistory` on `bidRequests`, `estimateVersions`, `estimateLines`, `vendorRfqs`, `rfis`, `proposals` (§4.5).

**Q4 — P21 integration**
**Decision: Cached mapping collection, not a live query.** Build `p21ItemMappings` with `lastSyncedAt`, `p21ItemId`, `mfrPartNumber`, `lastPoPrice`, `lastPoDate`, and a staleness derived flag (fresh <6mo, aging 6–24mo, discard >3–4yr per the workbook's own freshness rule). Every cost lookup must support manual override — P21 is read-only and unreliable by the workbook's own admission (9/10 correct is not good enough to trust blindly). This is not optional; it's the only design consistent with NR-10's stated uncertainty.
*Affects:* §3.17 `p21ItemMappings`; `estimateLines.costSnapshot.source` includes `manual`; `catalogItems.p21ItemId` denormalization.

**Q5 — Fire rating**
**Decision: Model fully, required-on-rated-openings, with a hard-stop validation flag.** `fireRating` is an enum (20, 45, 60, 90, none) on openings. Add a boolean `ratingConflict` (true when an opening has a fire rating but the matched hardware/frame combination isn't UL-labelled for that rating) computed at match time. This directly enforces FR-2 and NFR-2's Must priority — an unrated match on a rated opening is a defect per the workbook, so the schema must be able to flag it, not just store a string.
*Affects:* §3.23 `openings.fireRating`, `.fireRatingSource`, `.ulLabelRequired`, `.ratingConflict`, `.ratingMissing`; `catalogItems.fireRatings[]`, `.ulLabelled`; `hardwareSets.fireRating`; `productTypes.ratingSensitive`; two partial indexes on `openings`.

**Q6 — Alternates & addenda (the structural decision)**
**Decision: Immutable version chain.** Build `estimateVersions` — each version is a full immutable snapshot linked by `estimateId` + `versionNumber` + `supersededByVersionId`. Every line group carries an `alternateId` (nullable = base bid; populated = Alternate 1, 2, etc.), so alternates are a dimension on line groups within a version, not separate documents. Addenda create a new version that inherits unaffected line groups by reference-copy and only mutates affected ones. This is the highest-leverage decision in the schema — locking it in now avoids a full data-migration later when the first addendum arrives mid-bid.
*Affects:* §3.25, §3.26, §3.27 — the entire estimate spine.

**Q7 — Priced snapshot immutability**
**Decision: Freeze a full snapshot sub-document on every quote line at pricing time.** Each line stores `costSnapshot { amount, source, sourceDate }`, `priceBookSnapshot { versionId, effectiveDate }`, `multiplierTierSnapshot { tier, rate }`, and `marginSnapshot { band, rate, overridden, overrideReason }`. References alone break NFR-3's audit requirement the moment a price book is superseded — you'd have no way to reconstruct what a customer was actually quoted.
*Affects:* §3.27 `estimateLines` snapshot sub-documents; `estimateVersions.taxSnapshot`; `proposals.termsSnapshot` / `.totalsSnapshot`; §4.8.

**Q8 — Historical Excel import**
**Decision: Model the import path now; seed initially from the top-10 stock list only.** Add `estimates.sourceType` enum (`native`, `importedLegacy`) and `legacyWorkbookRef` (filename/path) on imported records. Do not build the similarity-search-for-reuse feature in v1 — that's an application-layer feature on top of a schema that already supports it, since import records live in the same `estimates`/`estimateVersions` structure as native ones.
*Affects:* §3.25 `estimates.sourceType`, `.legacyWorkbookRef`, `.templateSourceEstimateId`.

**Q9 — File storage**
**Decision: External object storage with `storageUri` + `checksum`.** GridFS only for small system-generated artifacts (proposal PDFs the app itself creates, under a few MB). Multi-hundred-page scanned bid sets do not belong in MongoDB documents or GridFS — store the binary externally, store metadata (`pageCount`, `sourceType`, `uploadedAt`, `checksum`) in `documents`.
*Affects:* §3.22 `documents`; §3.30 `proposals.storageUri` / `.gridFsFileId`; §4.9.

**Q10 — Identity**
**Decision: Own the `users` collection.** Fields: `name`, `email`, `role` (enum: `estimator`, `salesInitiator`, `purchasing`, `leadership`, `it`), `externalIdpSubject` (optional, nullable — future SSO hook), `active`. Do not build an IdP dependency into v1; the workbook names five specific individuals by role, which is native user-management scope, not federated identity scope.
*Affects:* §3.2 `users`.

**Q11 — Customer vs. brand program**
**Decision: Two separate collections — `customers` and `brandPrograms` — with a `marginOverride` sub-document attachable to either.** A customer (GC/internal initiator) references an optional `brandProgramId`. Special-customer margins (Wendy's) attach at whichever level the override actually applies, resolved at quote time by checking line-level override → brand override → customer override → default margin band, in that precedence order. This correctly separates "who pays" from "whose brand standard governs the spec."
*Affects:* §3.3, §3.4, §3.16 `marginRules.scope` / `.precedence`; `estimateLines.marginSnapshot.resolvedScope`.
*Implementation note:* the precedence order as implemented is line-level override → customer → brand → default. The decision text lists brand before customer in one clause and the resolution list places customer nearer the payer; the implemented order treats the **customer-specific** rule as more specific than the brand-wide one, since a customer override is by definition narrower. **This ordering should be confirmed** — see §6.3, OQ-6.

**Q12 — Freight**
**Decision: Persist an optional line of `lineType: "freight"`, defaulting to `status: "excluded"` unless explicitly added.** This matches the workbook's own observation that freight is usually omitted at estimate stage but sometimes included — the schema needs to represent both states without a special-case field bolted on later.
*Affects:* §3.27 `estimateLines.lineType`, `.status: "excluded"`; `estimateVersions.lineGroups[].groupType: "freight"`; `totals.freightAmount` nullable.

**Q13 — Soft delete & retention**
**Decision: Soft-delete (`isDeleted`, `deletedAt`, `deletedBy`) on `estimates`, `estimateVersions`, `bidRequests`, `priceBooks`, and `vendors`.** Add a `retentionPolicy` field (nullable string, e.g. `"7-year"`) on these collections rather than hard-coding indefinite retention — the workbook gives no retention rule, so the field exists and is queryable but left unset pending an actual policy decision from someone with authority to set one. This is a business decision I won't manufacture a number for; the schema just needs to be ready to hold whatever number eventually gets decided.
*Affects:* §4.3; the five named collections; the **uncreated** TTL index on `auditLogs`.

**Q14 — Volume / upper bound on openings per bid**
**Decision: Design for 10–40 openings per bid per NFR-6, but do not hard-cap anything in the schema.** No document, array, or index design should assume a fixed maximum — MongoDB's 16MB document limit is the only real ceiling, and 40 openings with full line-item embedding is nowhere near it. If a multi-building bid set with hundreds of openings shows up, the schema (per Q15) already handles it because openings and lines are referenced, not embedded inside a single monolithic document.
*Affects:* `openings` as a standalone collection; `estimateLines` as a standalone collection; no `maxItems` constraint anywhere in the validators.

**Q15 — Line items: embed or reference**
**Decision: Reference, not embed.** Create `estimateLines` as its own collection, referencing `estimateVersionId`, `openingId`, and `lineGroupId`. Reasoning: (1) it directly future-proofs Q14 — no volume assumption baked into document size; (2) it enables exactly the cross-estimate query pattern flagged as the deciding factor — "every line where a Hager 3500 was quoted" — which matters here because vendor-tier renegotiation (Hager is ~75% of volume per the vendor sheet) and catalog pricing audits are realistic, recurring needs for an estimating desk, not hypothetical; (3) it keeps `estimateVersions` documents small and fast to load/list even as line count grows. The only cost is one extra `$lookup`/join on read, which is a non-issue at this scale and is exactly what indexes on `estimateVersionId` are for.
*Affects:* §3.27 `estimateLines`; the `{ orgId, catalogItemId, createdAt }` and `{ orgId, vendorId, createdAt }` indexes.

### 6.2 Additional assumptions made during Phase 2

Where the workbook was silent and a schema decision was unavoidable, the assumption is recorded here against the field it affects.

| # | Assumption | Affects | Basis |
|---|---|---|---|
| A-16 | The `stale` freshness band (24–36 months) is **derived**, not from the workbook. Matrix 6.2 gives two thresholds — "~6–8 months is unreliable" and "3–4 years must be discarded" — leaving the middle undefined. A four-band ladder (fresh / aging / stale / discard) fills it without inventing a rule that contradicts either stated threshold. | `p21ItemMappings.freshness` | Matrix 6.2 (D19) |
| A-17 | `bidRequests.status` includes `cancelled` and `noBid`. The workbook describes Phases 0–6 as a happy path and never mentions a bid being lost, declined, or withdrawn. Real estimating desks decline bids; omitting the states would force cancelled bids to sit in `pricing` forever and would corrupt the future hit-rate KPI. | `bidRequests.status` | Flow Phases 0–6; **not stated** |
| A-18 | `bidRequests.status` includes `onHold` for bids blocked on a vendor RFQ or RFI. Matrix 6.6 (G23) asks whether an RFQ "holds up a bid" without answering; the state is needed to represent the blockage either way. | `bidRequests.status`; `vendorRfqs.blocksBid`; `rfis.blocksFinalization` | Matrix 6.6 (G23) |
| A-19 | Monetary values use BSON `double`, not `decimal128`. Trade-off: `decimal128` is the textbook-correct choice for currency and avoids binary floating-point representation error. `double` was chosen because the quote calculation is a division by a margin divisor whose result is rounded for display anyway, the values involved are small (line items in the tens to thousands of dollars), and `double` is far better supported across drivers and aggregation operators. **If the estimating team reports cent-level discrepancies against the Excel workbooks, this should be revisited** — the migration is mechanical but touches every monetary field. | Every monetary field | **Not stated**; engineering judgment |
| A-20 | Rounding of computed prices is an application concern, not a schema one; the schema stores whatever the application computed. NFR-3 reproducibility is satisfied by storing the computed values rather than by pinning a rounding rule. | `estimateLines.salePriceEach`, `.extendedPrice`, `.lineSubtotal` | **Not stated** |
| A-21 | `openings` are one document per *configuration* with a `quantity`, not one document per physical door. The door schedule lists door marks, and identical openings share a mark with a count. | `openings.quantity` | Matrix 5.0 (D16); FR-2 |
| A-22 | Hardware sets extracted from a spec live in the same collection as CBC library sets, discriminated by `setSource`. Matrix 7.7 requires both to exist and be reconciled to each other; separate collections would make the reconciliation a cross-collection join for no benefit. | `hardwareSets.setSource`, `.matchedLibrarySetId` | Matrix 7.7 (I33) |
| A-23 | Distributors are `vendors` with `vendorType: "distributor"`, not a separate collection. | `vendors.vendorType`, `.distributorIds[]` | Matrix 6.5 (I22) |
| A-24 | `catalogItems` gets a text index for free-text search. FR-8 (I45) describes the estimator's P21 search behaviour ("here are 3 close matches — is it one of these?") as the model for the matcher; free-text search over descriptions is the minimum needed to reproduce it. | `catalogItems` text index | FR-8 (I45) |
| A-25 | `productTypes` stores out-of-scope categories with `inScope: false` rather than omitting them, so the copilot can recognise and reject an out-of-scope line rather than failing to match it silently. | `productTypes.inScope`, `.outOfScopeReason` | Open 7 (C10) |
| A-26 | `currency` is stored explicitly as `USD` on every monetary document even though only USD appears in the workbook, because Matrix 2.4 (I8) mentions Canadian sales (untaxed). | All monetary collections | Matrix 2.4 (I8) |
| A-27 | Immutability of superseded `estimateVersions` is enforced by the application's data-access layer and evidenced in `auditLogs`. MongoDB's `$jsonSchema` cannot express "this document is now read-only". | `estimateVersions.lockedAt` | Q6; MongoDB capability |
| A-28 | `proposals.approvedBy` is **required**, making it structurally impossible to record a proposal that no human approved. This is a stricter reading of NFR-1 than the workbook's wording strictly demands, chosen deliberately because the guardrail is the workbook's stated guiding principle. | `proposals.approvedBy` | NFR-1 (D55); READ ME B23 |
| A-29 | `finishCodes.notEquivalentTo[]` exists to encode negative assertions (US19 ≠ 26D). The workbook states the non-equivalence but does not ask for it to be stored; storing it is what lets the matcher refuse a wrong substitution rather than make it. | `finishCodes.notEquivalentTo` | Matrix 7.5 (I31) |
| A-30 | Fields for data CBC still owes (`adders.value`, `lightKitRates.listPrice`/`.sizeMultiplier`, `frpConstants.numericValue`) are nullable with a `dataStatus: "pending"` guard rather than being omitted until the data arrives. Pending rows are visible as prompts but must never be auto-applied. | `adders`, `lightKitRates`, `frpConstants` | Open 5, NR-7, NR-8 |
| A-31 | No credential, password, or session material is stored in this database. Authentication is an application concern. | `users` | **Not stated**; security practice |
| A-32 | `auditLogs.ipAddress` and `.userAgent` are present but populated only if NFR-4's data-security owner requires them. Capturing them by default would be a data-protection decision made without the owner named in NFR-4. | `auditLogs` | NFR-4 (H58, Pending) |

### 6.3 Open questions still requiring a stakeholder answer

These are the workbook's own unresolved items, restated with their schema consequence. **None blocks implementation** — each has a modelled placeholder — but each leaves a field unset or a behaviour disabled.

| # | Question | Owner | Workbook status | Schema consequence |
|---|---|---|---|---|
| OQ-1 | **Fire rating** — where does the rating live in your bid sets (door schedule column, frame schedule, notes)? Which categories are rating-sensitive for pricing? Are there rating-specific vendors/lines? Should a missing rating hard-stop the line for review? | Sr. Estimator | Matrix 7.3 `Pending`; Open Item 9 `Open` | `openings.fireRatingSource` has no confirmed value set; `productTypes.ratingSensitive` is `false` for every type pending the answer; whether `ratingMissing` should *block* approval or merely flag it is currently a flag |
| OQ-2 | **Alternates & addenda** — how are alternates quoted today (separate line groups, separate totals)? How are addenda received and reconciled, and how often do they land? | Estimating | Matrix 4.1 `Pending`; FR-14 `Pending`; Flow 4b `Pending`; Open Item 11 `Open` | The **structure** is settled by Q6 (immutable version chain + `alternateId` on line groups). What remains open is the *process*: whether addenda arrive by email as new documents, what triggers a re-issue, and whether alternates are ever priced as fully independent quotes rather than groups within one |
| OQ-3 | **Data security (NFR-4)** — confirm the owner (IT) and the approved, access-controlled environment for drawings, pricing, and customer data. | IT | NFR-4 `Pending` | Determines whether `auditLogs.ipAddress`/`.userAgent` are captured; determines encryption-at-rest, field-level encryption for any PII, and network placement — none of which this schema fixes |
| OQ-4 | **Data stewardship (NFR-10)** — name an owner and refresh cadence for the reference library, each vendor multiplier sheet, and the margin sheet. | Purchasing / Estimating | NFR-10 `Open`; Open Item 15 `Open`; Assumptions row 11 `Open` | `priceBooks.ownerUserId`, `.refreshCadence` and `vendorTiers.ownerUserId`, `.refreshCadence` are all null. Until set, staleness is only visible via `lastReviewedAt`, not enforced |
| OQ-5 | **Retention policy** — how long must superseded estimates, price books, and audit records be kept? | Leadership / IT | **Not addressed anywhere in the workbook** | `retentionPolicy` is null on all five soft-delete collections; the `auditLogs` TTL index is documented but **not created** |
| OQ-6 | **Margin precedence: customer vs brand** — when a customer-specific override and a brand-program override both apply, which wins? | Estimating Lead | Implied by Open NR-9, not stated | `marginRules.precedence` is implemented as customer (30) > brand (20) > default (10). One line of the Q11 decision text can be read the other way. A wrong order silently mis-prices any account that has both |
| OQ-7 | **FRP conversion constants** — panel size, waste %, trim/stick lengths, adhesive coverage, opening handling. | Estimating | Open Item 5 `Partial` | `frpConstants.numericValue` null, `dataStatus: "pending"`; FR-12's automated conversion stays disabled and take-offs remain `conversionMethod: "manual"` |
| OQ-8 | **Top-10 stock list per product type** (locks, exits, closers, hinges…). | CBC | Open NR-6 `Data needed` | `catalogItems.isStock` / `.stockRank` cannot be populated; the item picker has no Phase 1 content |
| OQ-9 | **Hager adder values** (electrification / NRP / premium finish). | CBC | Open NR-7 `Data needed` | `adders.value` null, `dataStatus: "pending"`; lines needing an adder can be prompted but not auto-priced |
| OQ-10 | **Light-kit table logic** (glazing types + size multipliers) from the NGP / PEMKO / Rockwood sheets. | CBC | Open NR-8 `Data needed` | `lightKitRates.listPrice` and `.sizeMultiplier` both null; NR-1's calculator cannot run |
| OQ-11 | **Special-customer margins** — which accounts get non-standard margins beyond Wendy's? | CBC | Open NR-9 `Data needed` | `marginRules` with `scope: "customer"` has no rows; `customers.marginOverride` empty |
| OQ-12 | **P21 integration feasibility** and the part-number / semi-item matching strategy. | Dash / IT | Open NR-10 `Investigate` | Determines whether `p21ItemMappings` is populated by an automated sync or stays manual. The collection is designed for either (`syncSource: "p21" \| "manual"`) |
| OQ-13 | **HP-Fabrication "peelle/peeling" doors** — exact term and scope. | CBC | Open NR-11 `Confirm` | A `productTypes` row cannot be named correctly; currently absent rather than guessed |
| OQ-14 | **Baseline & target metrics** — bids/month, hours/bid, turnaround, hit rate. | Leadership | Open Item 16 `Open`; the Business Case & Metrics sheet is missing entirely | No metrics collection (Q3). `statusHistory` will supply the raw data when targets are defined |
| OQ-15 | **Keying** — confirmed as living inside lock options with no separate keying-schedule workflow, but Open Item 10 is still marked `Partial`. | Estimating | Matrix 7.6 `Partial`; Open Item 10 `Partial` | Modelled as embedded `options.keying` per the 14 Jul answer. If a separate keying schedule turns out to exist on some bids, it would need its own collection |
| OQ-16 | **Margin governance** — margin floor / discount threshold and who approves overrides. | President / Sales Mgmt | Matrix 6.7, FR-15, NFR-8, NFR-9, Open Item 14 — all `Out of scope (future)` | `marginRules.floorRate` exists but is null everywhere. No approval-routing collection was built. When governance becomes relevant (the workbook says "with more estimators"), the field is ready and a `marginApprovals` collection would be additive, not a migration |

---

## 7. Requirements Traceability Map

Every entity identified in Phase 1, its source in the workbook, the key fields extracted, and where it landed in the schema. Sheet abbreviations: **Matrix** = Requirements Matrix; **Flow** = Process Flow; **Scope** = Product & Scope Confirmation; **Assump** = Assumptions & Dependencies; **Open** = Open Items.

| # | Entity | Source (sheet · cells) | Key fields / rules extracted | Where it landed |
|---|---|---|---|---|
| 1 | Organization / Division | Matrix 2.0 (B4:I4), 2.3 (I7) | CBC = Hamilton Parker national-accounts division; other HP divisions out of scope, extensible later | §3.1 `organizations` |
| 2 | User | Matrix 8.1 (I36), FR-10 (I47), NFR-1/3/5 (I55, I57, I59); Assump A7, D4:D8 | Estimators Kevin/Rick/Shanna; initiators Kellan/Matt/Rebecca/Tina; owners Estimating, IT, Purchasing, Leadership | §3.2 `users` |
| 3 | Customer / Account | Matrix 2.0 (D4), 2.4 (I8), 6.1 (I18); Open NR-9 | Sells to GC/internal initiator, not architect; state→tax; special margins | §3.3 `customers` |
| 4 | Brand Program | Matrix 3.0 (I10), 6.1 (I18); Open 8 (E11) | McDonald's, Cava, Wendy's; per-brand mode preference; brand margin carve-outs | §3.4 `brandPrograms` |
| 5 | Tax Rule | Matrix 2.4 (I8); Open 13 (E16) | OH ~8%, KY 6.5% border-nexus, other 48 states + Canada none; supply-only | §3.5 `taxRules` |
| 6 | Commercial Terms | Matrix FR-10 (C47); Flow C12 | HP PO required; 30-day validity; supply-only | §3.6 `commercialTermsTemplates` |
| 7 | Product Type | Matrix 2.1 (D5, I5), 2.3 (I7); Scope A4:A15; Open 7 (E10) | In: metal & wood doors, HM frames welded & KD, hardware, Div 10 partitions/accessories/hand dryers, FRP. Out: ceiling tile & grid, tile, brick, masonry, storefront, coiling/oversized, engineered wood, metal siding | §3.7 `productTypes` |
| 8 | Vendor / Manufacturer | Matrix 2.2 (D6, I6); Scope C4:D9, G4:G9 | Hager ~75%, Allegion, NGP, Rockwood, PEMKO, Bobrick, Bradley, ASI, Gamco, World Dryer, Dyson, Excel XLERATOR, Marlite, NUDO, Five Lakes, Pioneer, Masonite Arch., Special-Lite, HP Fabrication. Remove American Dryer, Scranton. Top-10 = Phase 1 | §3.8 `vendors` |
| 9 | Distributor | Matrix 2.2 (I6), 6.5 (I22); Open NR-2 | Banner Solutions, SecLock, J2, Pionite, Wilsonart → manual price entry + refresh prompt | §3.8 `vendors` (`vendorType: distributor`) — A-23 |
| 10 | Catalog Item | Matrix 7.2 (I28), 7.7 (I33), FR-3 (I40); Open NR-6, NR-13 | Part number/series is the quoting key; top-10 stock per type (~20 with grades) + CUSTOM/OTHER; option matrix (function, backset, finish, lever, keyway, strike, electrified) | §3.9 `catalogItems` |
| 11 | Hardware Set | Matrix 7.2 (D28, I28), 7.7 (D33, I33); FR-3 | Spec sets HW-1, HW-2… vs CBC library; reconcile to stock/top-10; no single standard list | §3.10 `hardwareSets` |
| 12 | Hardware Set Item | Matrix 7.2 (D28) | Hinges (continuous/butt), lock or exit device, closer, kick plate, threshold, sweep, weatherstrip/smoke seal, floor stop/holder, silencers | **Embedded** `hardwareSets.items[]` — §2.3 |
| 13 | Adder | Matrix 6.3 (I20); Open NR-4, NR-7 | Electrification, non-removable-pin hinges, premium/lead-time finishes — not clean in the price book | §3.11 `adders` |
| 14 | Light Kit | Open NR-1, NR-8 | Glazing type + size → price from NGP / PEMKO-Markar / Rockwood tables | §3.12 `lightKitRates` |
| 15 | Price Book Version | Matrix 6.3 (D20, I20); NFR-3, NFR-10 | Dated memos with a protection window; MAP is NOT cost | §3.13 `priceBooks` |
| 16 | Price Book Entry | Matrix 6.3 (D20) | List price per part (Hager 3500 storeroom lock $256.31); some sheets pre-compute net | §3.14 `priceBookEntries` |
| 17 | Multiplier Tier | Matrix 6.3 (D20, E20); Open 3 (E6) | Per-vendor **account** attribute; Hager "50 & 42" ≈ 0.29; World Dryer Level-3 = 0.339 | §3.15 `vendorTiers` |
| 18 | Margin Band | Matrix 6.1 (D18, I18); Open 2 (E5), NR-9 | Divisor model: commodity 27%/0.73, restroom partitions 35%/0.65, specialty 40%/0.60, custom fabricated 25%/0.75; accessories ~56%; overridable on essentially every quote | §3.16 `marginRules` |
| 19 | Cost Record | Matrix 6.2 (D19, I19), 6.3, 6.6; FR-6 (C43) | Three paths: P21 last-PO if sold <1yr; else Banner/SecLock lookup; else mfr website / RFQ. Never the supplier-list field. Freshness 6–8mo unreliable, 3–4yr discard | **Embedded** `estimateLines.costSnapshot` + §3.17 — §2.3 |
| 20 | P21 Item Mapping | Matrix 6.2 (I19); NFR-5 (I59); Open 4 (E7), NR-10 | P21 item IDs ≠ mfr part numbers; semi/custom items won't match; read-only, no write-back | §3.17 `p21ItemMappings` |
| 21 | Frame Depth / Wall Type | Matrix 7.0 (I26); Open 6 (E9) | Five throats: 5-5/8", 5-3/4", 5-7/8", 7-3/4", 8-1/4" + CUSTOM (~10 max); adjustable frames exist | §3.18 `frameDepths` |
| 22 | Finish Code | Matrix 7.5 (D31, I31); Open NR-3 | US26D = 626; 619 = US15; **US19 ≠ 26D**; premium finishes carry lead time | §3.19 `finishCodes` |
| 23 | FRP Constants | FR-12 (C49, I49); Flow 3b (C8, G8); Open 5 (B8, E8) | Panel size, waste %, trim/stick lengths, adhesive coverage, opening handling — **still to be provided** | §3.20 `frpConstants` |
| 24 | Bid Request | Matrix 4.0 (I13), FR-1 (C38, I38); Flow Phase 0 (C4, G4); Open NR-5 | Email (mostly) or phone → "create new bid request"; job workbook + plans/RFP; due date; alternates noted; initiator in the queue | §3.21 `bidRequests` |
| 25 | Bid Document | Matrix 8.0 (D35, I35); Assump row 7 (C10, F10); Flow C4 | One combined PDF or several separate PDFs; native or scanned | §3.22 `documents` |
| 26 | Document Page | NFR-3 (D57); Flow C6, C7 | Every generated line traceable to a source drawing page | **Embedded** `documents.pages[]` — §2.3 |
| 27 | Addendum | Matrix 4.1 (D14); Flow 4b (C10) | Changes scope, products, or counts mid-bid; must not lose prior work | §3.22 (`docType: addendum`) + §3.26 version chain |
| 28 | Spec Scope | Flow Phase 2 (C6, G6) | Div 08 doors/frames/hardware + Div 10 partitions/accessories/washroom + FRP | **Embedded** `bidRequests.scopeCategories[]`, `.csiDivisionsInScope[]` |
| 29 | Opening (door) | FR-2 (C39, I39); Matrix 7.0–7.6 | Door number, size (3070 = 3'-0"×7'-0"), handing (LH/RH/LHR/RHR), finish, fire rating, HW set callout, frame depth, wall type, alternate designation | §3.23 `openings` |
| 30 | Fire Rating | Matrix 7.3 (D29, E29, I29); Open 9 | 20/45/60/90-min UL-labelled; drives selection and price; **unrated match on a rated opening is a defect** | §3.23 `openings.fireRating` + `.ratingConflict` (Q5) |
| 31 | Keying Option | Matrix 7.6 (D32, I32); Open 10 (E13) | IC small/large format, storeroom w/ IC, keyways; architect-specified; lives in the lock custom tab; no separate keying-schedule workflow | **Embedded** `openings.keying` / `estimateLines.options.keying` — §2.3 |
| 32 | Take-off | FR-12 (C49); Flow Phase 3 (C7), 3b (C8) | Perimeter LF, inside/outside corners, counts, drawing scale; Vu360 gives geometry only | §3.24 `takeoffs` |
| 33 | Estimate | Matrix 3.0 (D10, I10); Flow Phase 1 (C5); FR-11 | Templated ("start full, delete down") vs one-off ("start blank, build up"); templated starts from a prior job's workbook | §3.25 `estimates` |
| 34 | Quote Version | Matrix 4.1 (D14); FR-14 (C51); Flow 4b | Base bid + alternates; absorb addenda without losing prior work; re-issue if already sent | §3.26 `estimateVersions` |
| 35 | Bid Alternate | Matrix 4.1 (D14); Flow C10 | Alternate 1, 2… priced as distinct, comparable line groups | **Embedded** `estimateVersions.alternates[]` — §2.3 |
| 36 | Line Group | FR-7 (C44, I44); Flow C12 | Grouped by door with subtotals; separate restroom-accessories block; freight line | **Embedded** `estimateVersions.lineGroups[]` — §2.3 |
| 37 | Quote Line | Matrix 5.0 (D16, I16); FR-5, FR-6, FR-7 | Manual: quantity, our cost, margin. Computed: sale EA = cost/(1−margin), unit = sale EA, ext = unit×qty, subtotal = sale EA×qty. **Remove unit weight** | §3.27 `estimateLines` |
| 38 | Match Result | FR-4 (C41, I41), FR-8 (C45, I45); NFR-2 | Confidence score; "here are 3 close matches"; flag low confidence, missing ratings, unparsed content; hard cut-off → manual | **Embedded** `openings.matchCandidates[]`, `estimateLines.matchResult` — §2.3 |
| 39 | Substitution / Direct-Equal | Matrix 6.4 (D21, I21); Flow C11 | GC approves a direct equal (usually Hager); propose closest of top 2–3 brands **with a note** | **Embedded** `estimateLines.substitutionNote` — §2.3 |
| 40 | Sourcing Note | Matrix 6.5 (D22, I22) | Buy direct vs via wholesaler/distributor; primary source recorded in P21 | **Embedded** `estimateLines.sourcingNote` — §2.3 |
| 41 | Freight | FR-7 (I44); Open 1 (E4); Flow C12 | Generally NOT quoted at estimate stage; occasionally included for all-inclusive customers | `estimateLines.lineType: "freight"` (Q12) |
| 42 | Vendor RFQ | Matrix 6.6 (D23, I23); FR-16 (C53, I53); Open 12 (E15) | Custom sizes (9-ft doors), unusual preps, options not sold in years; wait for pricing; hard cut-off stays manual | §3.28 `vendorRfqs` |
| 43 | RFI | Flow Phase 5 (C11, E11) | Raised for unclear or missing info before finalizing | §3.29 `rfis` |
| 44 | Proposal / Export | FR-10 (C47, I47); Flow Phase 6 (C12, G12); NFR-1 | PDF in the customer-facing format; sent to the **initiating salesperson**, not a group email; nothing sent without approval | §3.30 `proposals` |
| 45 | Estimator Feedback | FR-13 (C50, I50) | Capture corrections as structured feedback; "keep feeding it information and grow it" | §3.31 `feedbackEvents` |
| 46 | Audit Event | NFR-3 (D57, I57) | Line traceable to a source drawing page and to a reference-library / price-sheet version incl. tier and effective date | §3.32 `auditLogs` + Q7 snapshots |
| 47 | Door-size notation | Matrix 7.1 (D27, I27) | 4-digit shorthand; first two digits width, second two height | **Parser rule**, not an entity — stored as `openings.sizeCode` + derived width/height |
| 48 | Margin governance / approval | Matrix 6.7 (H24, I24); FR-15 (H52); NFR-8 (H62), NFR-9 (H63); Open 14 (F17) | All confirmed **Out of scope (future)** — no margin deviation today | **Not modelled**; `marginRules.floorRate` reserved — OQ-16 |
| 49 | Business case / metrics | READ ME B13; Open 16 (F19); Assump row 9 (E12) | Sheet referenced in READ ME but **absent from the workbook**; baseline/target metrics not captured | **Not modelled** (Q3); computable later from `statusHistory` |
| 50 | Knowledge-continuity risk | Matrix 8.1 (D36, I36); Assump row 10 | Knowledge concentrated in Kevin/Rick/Shanna; mitigated by capturing rules & reference data | **Non-schema** — mitigated by the reference-library collections existing at all |
| 51 | Adoption / change management | NFR-11 (D65, I65); Assump row 12 | Uneven adoption of the blank-quote system; rollout must not disrupt estimators | **Non-schema** |
| 52 | Workbook protection | Matrix 3.1 (D11, I11); Flow D5 | Both Excel workbooks password-protected ('ESTIMATOR') | `estimates.legacyWorkbookRef` (Q8) — the protection itself is an import concern |

**Coverage check:** all six sheets are represented above. Every one of the 54 requirement rows in the Requirements Matrix, all 10 Process Flow steps, all 12 Product & Scope rows, all 12 Assumptions & Dependencies rows, and all 16 Open Items plus the 13 NR items appear in at least one row of this map or in §6.3 as an open question.
