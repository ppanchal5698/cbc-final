# Data flow

How a bid moves through the system, and where each piece of data comes to rest.
Every box names something you can open.

## End to end

```mermaid
flowchart TB
  U[Estimator uploads a bid set] --> API["POST /api/projects/{id}/documents<br/>intake module"]
  API --> RAW["uploads/raw/*.pdf<br/>immutable"]
  API --> DOC[(documents)]
  API --> Q1["enqueue parse_document"]

  Q1 --> MIN["LlamaParse Cloud<br/>WORKER_DOMAIN=parsing"]
  MIN --> BLK["uploads/processed/parsed/&lt;docId&gt;/<br/>+ documentPages"]

  RAW --> Q2["enqueue extract_bid_set"]
  BLK --> Q2
  Q2 --> EX["worker: claude_pass.run<br/>toolsets=_READING"]

  EX --> M0["extracted/scope_metadata.json"]
  EX --> M1["extracted/scope_summary.json"]
  EX --> M2["extracted/line_items.json"]
  EX --> M3["extracted/frp_takeoff.json"]
  EX --> M4["extracted/div10_takeoff.json"]
  M2 --> OPN[(openings)]

  M2 --> Q3["enqueue match_and_price"]
  M3 --> Q3
  M4 --> Q3
  Q3 --> PR["worker: claude_pass.run<br/>toolsets=_PRICING"]
  PR --> M5["extracted/hardware_sets.json"]
  PR --> M6["priced/line_items.json"]
  PR --> LIN[(estimateLines)]

  M6 --> Q4["enqueue build_proposal"]
  Q4 --> RV["worker: claude_pass.run<br/>toolsets=calc+reference+artifacts"]
  RV --> M7["review/review_flags.json"]
  RV --> M8["quotation.html"]
  RV --> M9["review/quotation_email_draft.md"]
  M9 --> HALT(["Draft ready for<br/>estimator review"])

  M7 --> WEB["Ops-Hub review queue"]
  WEB --> HUMAN[Estimator approves]
```

The three `enqueue` steps are the autopilot chain in
`projects/api/autopilot.py`; each is enqueued when the previous job succeeds.

## Artifact handoffs

Which phase reads what. This is the contract that lets a phase be rerun on its
own.

```mermaid
flowchart LR
  subgraph P01["0/1 intake-coordinator"]
    A[scope_metadata.json]
  end
  subgraph P2["2 spec-scope-analyst"]
    B[scope_summary.json]
  end
  subgraph P3["3 / 3b / 3c — concurrent"]
    C[line_items.json]
    D[frp_takeoff.json]
    E[div10_takeoff.json]
  end
  subgraph P4a["4 product-matcher"]
    F[hardware_sets.json]
  end
  subgraph P4b["4 pricing-engineer"]
    G[line_items.json]
    H[margin_applied.json]
  end
  subgraph P5["5 quality-reviewer"]
    I[review_flags.json]
    J[review_summary.html]
  end
  subgraph P6["6 delivery-agent"]
    K[quotation_email_draft.md]
  end

  A --> B
  B --> C & D & E
  C & D & E --> F
  F --> G --> H
  H --> I --> J --> K
```

## Where a cost comes from

The decision tree in [Phase 4](pipeline/phase-4-pricing.md), as data flow. Each
path is tried in order; the first that answers wins, and the line records which
one it was.

```mermaid
flowchart TB
  L[A matched line] --> P1{"p21-connector<br/>lookup_last_po<br/>+ check_freshness"}
  P1 -->|fresh PO| C1["cost_source: P21_LAST_PO"]
  P1 -->|no / stale| P2{"catalog<br/>get_special_net"}
  P2 -->|hit| C2["cost_source: SPECIAL_NET<br/>already Our Cost —<br/>do not multiply"]
  P2 -->|miss| P3{"catalog<br/>lookup_catalog_item<br/>then search_catalog_items"}
  P3 -->|hit| C3["cost_source: CATALOG_BASELINE"]
  P3 -->|miss| P4{"catalog find_pages<br/>+ catalog-docs search_blocks<br/>+ calc-engine cost_from_list<br/>x get_multiplier"}
  P4 -->|found| C4["cost_source: LIST_X_MULTIPLIER<br/>+ multiplier_tier<br/>+ multiplier_effective_date"]
  P4 -->|no| C5["cost_source: MANUAL<br/>cost: null, confidence 0.0<br/>plain-language reason"]

  C1 & C2 & C3 & C4 & C5 --> MG["calc-engine apply_margin<br/>vs reference get_margin_bands"]
  MG --> VM{"validate_margin"}
  VM -->|below band| FL["review flag, severity medium"]
  VM -->|in band| OK["priced line"]
```

A miss from the catalog **is an answer** — it means CBC has no row for that
vendor, which is true for Allegion and Zero. The correct next step is manual,
not a PDF hunt for a substitute.

## Reading a PDF

Every phase that touches a drawing follows the same two-step, because the cheap
tool and the accurate tool are different tools.

```mermaid
flowchart LR
  N["I need a value"] --> F["bid-docs search_blocks<br/>— which page?"]
  F --> V{"in _visual_pages.json?"}
  V -->|yes| IMG["Read the pre-rendered image"]
  V -->|no| T["pdf-tools get_page_blocks<br/>/ extract_tables / extract_text"]
  T --> A{"text layer clear?"}
  A -->|no| CR["pdf-tools get_page_image(region=bbox)"]
  IMG & CR & A --> R["record tool + page + excerpt<br/>in evidence_note"]
  R --> W{"value found?"}
  W -->|yes| FILL["fill it, with bbox + page_size"]
  W -->|no| FLAG["null + review flag<br/>naming the pages searched"]
```

`bid-docs` finds; `pdf-tools` reads. Searching with `pdf-tools` across a whole
set is what the block index exists to avoid.

## Request paths

Two routes into the API, and they are not interchangeable.

```mermaid
flowchart LR
  SC["Server component"] -->|"lib/api.ts — GET only"| NX
  BR["Browser"] -->|fetch| PX["app/api/proxy/[...path]"]
  PX -->|auth() or 401| PX2["strip actor param<br/>allow-list headers<br/>reject .. and %2f<br/>mint X-Trace-Id"]
  PX2 --> NX["internal-api.ts<br/>X-Internal-Token or 60s JWT"]
  NX --> API["platform:8001"]
  API --> MW["TraceMiddleware<br/>→ InternalAuthMiddleware<br/>→ CORS"]
  MW --> RT["module router"]
```

`lib/api.ts` is `server-only` and exports `get` alone — **every write goes
through the proxy**, so there is exactly one place that authenticates a
browser-originated mutation. Note that `proxy.ts`'s matcher deliberately
excludes `api/proxy`, so a client fetch gets a real 401 rather than a 200
carrying sign-in HTML.

## A job's life

```mermaid
stateDiagram-v2
  [*] --> queued: POST /api/jobs
  queued --> running: claim()<br/>$inc claimGeneration
  running --> queued: retry (attempts < 3)<br/>nextAttemptAt = now + 30·2^(n-1)
  running --> queued: defer — bid busy / parsing<br/>$inc attempts -1
  running --> queued: reap — heartbeat stale
  running --> done: finish(ok=True)
  running --> dead: attempts exhausted<br/>or permanent
  running --> cancelled: estimator, or shutdown
  done --> [*]
  dead --> [*]
  cancelled --> [*]
```

Every transition out of `running` is guarded on workerId **and**
`claimGeneration`, so a worker that was declared dead and then wakes up cannot
write over its replacement. A defer costs no attempt.

## Provenance

What makes a number auditable months later.

```mermaid
flowchart LR
  subgraph EXT["every extracted record"]
    E1[source_file]
    E2[source_page]
    E3["bbox — mandatory"]
    E4["page_size — mandatory"]
    E5[extracted_at]
  end
  subgraph PRI["every priced line"]
    P1["cost_source"]
    P2[cost_source_detail]
    P3[multiplier_tier]
    P4[multiplier_effective_date]
    P5[price_book_version]
    P6[priced_at]
  end
  subgraph TRAIL["every tool call"]
    T1["audit_trail.jsonl<br/>append-only"]
  end
  EXT --> VIEW["sheet viewer draws<br/>the highlight"]
  PRI --> ANS["'where did this<br/>number come from?'"]
```

`bbox` and `page_size` together are what make a page number useful: a page
reference alone names a sheet the estimator still has to search by eye, and
`page_size` is what the viewer scales the box against. A transposed width and
height is every number being real and the highlight landing nowhere near its
row — which is why
`extraction/api/validation/artifacts.check_extraction` verifies the box sits on
real text and that `page_size` matches the frame it was measured in.

## See also

- [`system-design.md`](system-design.md) — the structure these flows run on
- [`pipeline/README.md`](pipeline/README.md) — what each phase does
- [`collections.mongodb.md`](collections.mongodb.md) — where the data lands
