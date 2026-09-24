export type LineStatus = "clear" | "needs_look" | "duplicate" | "by_hand";
export type Stage = "intake" | "extraction" | "quote" | "proposal";
export type JobStatus = "queued" | "running" | "done" | "failed" | "cancelled" | "dead";
export type ChainState =
  | "idle"
  | "extracting"
  | "extraction_done"
  | "extraction_needs_review"
  | "pricing"
  | "pricing_failed"
  | "quoting"
  | "quoting_failed"
  | "complete"
  | "awaiting_manual_retry"
  | "dead";

export interface Counts {
  total: number;
  clear: number;
  needsLook: number;
  duplicate: number;
  byHand: number;
}

export interface Job {
  id: string;
  type: string;
  projectId: string | null;
  status: JobStatus;
  attempts: number;
  error: string | null;
  errorCode?: string | null;
  log: string | null;
  note?: string | null;
  traceId?: string | null;
  projectCode?: string | null;
  projectName?: string | null;
  nextAttemptAt?: string | null;
  coalesceUntil?: string | null;
  stragglerPending?: boolean;
  createdAt: string;
  startedAt: string | null;
  finishedAt: string | null;
}

/** Provenance for a create-form field autofilled from the bid PDF. */
export interface IntakeFieldSource {
  filledBy?: string;
  filledAt?: string;
  fromPdf?: boolean;
  sourceFile?: string | null;
  sourcePage?: number | string | null;
  excerpt?: string | null;
}

export type BidStatus = "bid" | "not_bid";
/** "" means open - the board cycles open -> won -> lost -> open. */
export type Outcome = "" | "won" | "lost";
export type EnteredByRole = "Sales" | "Estimating" | "Purchasing" | "Operations";

export interface Person {
  email: string;
  name: string;
  initials: string;
}

export interface Project {
  id: string;
  code: string;
  slug: string;
  name: string;
  brand?: string | null;
  jobName?: string | null;
  projectNumber?: string | null;
  location?: string | null;
  state?: string | null;
  architect?: string | null;
  gc?: string | null;
  initiator?: string | null;
  bidDue?: string | null;
  /** Matrix 3.0: one_off (Kevin) or templated (Shanna). */
  mode?: "one_off" | "templated" | null;
  /** Phase 0: alternate names noted at intake (Matrix 4.1 reconciliation pending). */
  bidAlternates?: string[];
  stage: Stage;
  progress: number;
  /** Which phase an autopilot / coalesce run has reached. */
  phase?: string | null;
  /** Autopilot saga state — source of truth for "what stage is this bid at". */
  chainState?: ChainState | null;
  /** Estimator-facing note when autopilot pauses or stragglers are pending. */
  pipelineNote?: string | null;
  /**
   * Provenance for create-form fields filled from the bid PDF (Ops-Hub empties only).
   * Keys match project fields: brand, location, state, architect, gc, bidDue, …
   */
  intakeFieldSources?: Record<string, IntakeFieldSource> | null;
  /** Run Phase 0-6 in one pass when a drawing is uploaded. */
  autopilot?: boolean;
  version?: number;
  handedOffTo?: string | null;
  /** The team `initiator` sits on - a per-bid label, not an auth role. */
  enteredByRole?: EnteredByRole | null;
  /** The assigned estimator's email, "" when unassigned. */
  assignedEstimator?: string;
  /** Resolved from `users` by the API; null when the address is unknown. */
  estimator?: Person | null;
  /** Whether CBC is quoting this job at all. Defaults to "bid". */
  bidStatus?: BidStatus;
  /**
   * How the bid ended, entered by hand. "" is still open. Held apart from
   * `not_bid` so an unworked job is never counted as a loss.
   */
  outcome?: Outcome;
  /** The P21 order raised against a won bid. */
  p21OrderNo?: string | null;
  counts: Counts;
  documentCount: number;
  quoteTotal?: number | null;
  activeJob?: Job | null;
  createdAt: string;
}

export interface BidDocument {
  id: string;
  projectId: string;
  filename: string;
  kind: string;
  pages: number | null;
  bytes: number | null;
  path: string;
  contentSha?: string | null;
  state: string;
  uploadedAt: string;
  /** Parse progress when PARSER_API_KEY is set; absent means read via pdf-tools. */
  parse?: {
    state?: string;
    pages?: number;
    pagesDone?: number;
    settings?: Record<string, unknown>;
    error?: string | null;
  };
}

export interface Evidence {
  note?: string | null;
  sheet?: string | null;
  row?: number | null;
  confidence?: number | null;
  sourceFile?: string | null;
  sourcePage?: number | null;
  /** [x0, y0, x1, y1] in PDF points, measured against pageSize. */
  bbox?: number[] | null;
  pageSize?: { width: number; height: number } | null;
}

export interface OpeningKeying {
  coreType?: string | null;
  keyway?: string | null;
  lockFunction?: string | null;
  notes?: string | null;
}

export interface LineItem {
  id: string;
  projectId: string;
  mark?: string | null;
  description: string;
  size?: string | null;
  qty: number;
  hwSet?: string | null;
  division?: string | null;
  handing?: string | null;
  finish?: string | null;
  fireRating?: string | null;
  frameType?: string | null;
  wallType?: string | null;
  /** Derived from wall type against the five standard throats (Matrix 7.0). */
  frameDepth?: string | null;
  notes?: string | null;
  doorType?: string | null;
  doorMaterial?: string | null;
  frameMaterial?: string | null;
  glass?: string | null;
  manufacturer?: string | null;
  series?: string | null;
  hardware?: string | null;
  location?: string | null;
  keying?: OpeningKeying | null;
  /** null = base bid; named group = bid alternate (Matrix 4.1 interim). */
  alternateGroup?: string | null;
  status: LineStatus;
  confidence?: number | null;
  flags: string[];
  /** The schedule row exactly as it was printed, before any interpretation. */
  rawRow?: string | null;
  width?: string | null;
  height?: string | null;
  sizeNotation?: string | null;
  /** Decided by `domain.scope_rules`; null means the rules do not cover this row. */
  inScope?: boolean | null;
  scopeRule?: string | null;
  scopeReason?: string | null;
  /**
   * Set on Division 10 and FRP lines. They are line items like any other -
   * `division` routes them to the right quote block (`10 21`, `10 28`, `06 64`)
   * and this carries what a door row has no column for.
   */
  specialty?: {
    kind: "div10" | "frp";
    productType?: string | null;
    specifiedModel?: string | null;
    unit?: string | null;
    drawingRef?: string | null;
    room?: string | null;
    perimeterLf?: number | null;
    insideCorners?: number | null;
    outsideCorners?: number | null;
    wallHeightFt?: number | null;
    drawingScale?: string | null;
    status?: string | null;
  } | null;
  evidence?: Evidence | null;
  duplicateOf?: string | null;
  duplicateReason?: string | null;
  addedByHand: boolean;
  confirmedBy?: string | null;
  confirmedAt?: string | null;
}

export interface SpecialtyTakeoff {
  id: string;
  takeoffType?: string | null;
  productType?: string | null;
  manufacturer?: string | null;
  location?: string | null;
  drawingRef?: string | null;
  qty?: number | null;
  unit?: string | null;
  specifiedModel?: string | null;
  finish?: string | null;
  perimeterLf?: number | null;
  insideCorners?: number | null;
  outsideCorners?: number | null;
  wallHeightFt?: number | null;
  drawingScale?: string | null;
  status?: string | null;
  notes?: string | null;
  flags?: string[];
  /** Set once an estimator corrects the row; survives the next re-extraction. */
  editedBy?: string | null;
  editedAt?: string | null;
  /**
   * Measured against the sheet by the extraction pass, never typed. `bbox` is
   * null when the row could not be pinned to exactly one printed line - the
   * reason is in `bboxNote` / the `bbox_*` flag, and the panel says "no
   * highlight" rather than pointing at a rectangle nobody measured.
   */
  sourceRef?: {
    sourcePage?: number | null;
    sourceFile?: string | null;
    bbox?: number[] | null;
    cellBoxes?: number[][] | null;
    pageSize?: { width: number; height: number } | null;
    bboxNote?: string | null;
    evidenceNote?: string | null;
  } | null;
}

export interface TakeoffsResponse {
  takeoffs: SpecialtyTakeoff[];
  /** From extracted/scope_summary.json — drives empty-state visibility. */
  frpInScope?: boolean;
  div10InScope?: boolean;
}

export interface LineItemsResponse {
  lineItems: LineItem[];
  counts: {
    all: number;
    needs_look: number;
    duplicate: number;
    by_hand: number;
    clear: number;
  };
}

export interface QuoteLine {
  id: string;
  projectId: string;
  lineKey?: string;
  part?: string | null;
  description: string;
  division?: string | null;
  group?: string | null;
  qty: number;
  cost: number | null;
  margin: number | null;
  sell: number | null;
  extended: number | null;
  basis?: string | null;
  costSource?: string | null;
  costSourceDetail?: string | null;
  multiplier?: number | null;
  multiplierTier?: string | null;
  multiplierEffectiveDate?: string | null;
  priceBookVersion?: string | null;
  sourcePage?: number | null;
  addedByHand: boolean;
  marginOverridden: boolean;
  overrideReason?: string | null;
  priceStatus?: string | null;
  /** The price book this cost came from is past its review window. */
  lapsed?: boolean;
  /**
   * Margin against its product-type floor (NFR-8). The API has computed this on
   * every line since quote.py:68 and the screen ignored it, so the one guardrail
   * that exists to make below-band pricing visible was visible to nobody.
   * `status` is "pass" | "fail" | "unpriced" | "unknown_product_type".
   */
  marginCheck?: {
    status: string;
    flag?: string | null;
    floor?: number;
    applied_margin?: number;
    product_type?: string;
  } | null;
  alternateGroup?: string | null;
  flags: string[];
}

export interface QuoteTotals {
  subtotal: number;
  cost: number;
  margin: number | null;
  taxRate: number;
  tax: number;
  freight: number | null;
  freightNote: string;
  grandTotal: number;
  taxJurisdiction: string | null;
  taxNote: string;
  unpricedLines: number;
  groups: { group: string; line_count: number; subtotal: number }[];
}

export interface QuoteResponse {
  quote: Record<string, unknown> | null;
  /**
   * One entry per opening (the hardware group the pass assigned), with the
   * division carried alongside and used as the key for a line that has no
   * opening.
   */
  groups: { group: string; division: string; lines: QuoteLine[]; subtotal: number }[];
  totals: QuoteTotals;
  lineCount: number;
  edited?: { count: number; firstId: string | null };
  lapsedCount?: number;
  reviewWindowMonths?: number;
}

export interface Product {
  id: string;
  part: string;
  description: string;
  manufacturer?: string | null;
  division?: string | null;
  cost: number | null;
  listPrice: number | null;
  /** The raw figure off the sheet, whatever its basis. */
  price?: number | null;
  /** Only set when priceBasis is "net" - a cost, not a list figure. */
  netPrice?: number | null;
  /** "list" | "net" | "unknown". Says what listPrice/netPrice mean. */
  priceBasis?: string | null;
  priceBasisNote?: string | null;
  multiplier: number | null;
  sellAt: number | null;
  availability?: string | null;
  priceBookId?: string | null;
  priceBook?: string | null;
  xref?: { manufacturer: string; part: string }[];
  seedSource?: string | null;
  updatedAt?: string | null;
  updatedBy?: string | null;
  /**
   * Where the row came from. "catalog" rows are read out of the SQLite FTS
   * index built from the vendor PDFs and carry an `idx:` id, not a Mongo one;
   * "manual" rows are the estimator's own, in Mongo.
   */
  source?: "manual" | "catalog";
  /**
   * False for indexed rows: the next reindex rewrites them from the PDF, so an
   * edit here would silently disappear. The API refuses them outright - their
   * `idx:` id is not a valid ObjectId.
   */
  editable?: boolean;
  unit?: string | null;
  sourcePage?: number | null;
  effective?: string | null;
}

/** A page of a vendor price book worth opening - not a priced line.
 *
 * The price books are PDFs. They used to be pre-extracted into product rows so
 * they could be listed beside the estimator's own parts, and that produced an
 * index where 37.8% of the codes carried no letter and dates were recorded as
 * part numbers. The vendor half now says where to look instead of guessing what
 * is there. */
export interface CatalogPage {
  catalog_id: string;
  vendor: string;
  file: string;
  pdf_page: number;
  printed_page: string | null;
  /** How the book itself names this page, e.g. "PDF p297 (printed p23)". */
  locator: string;
  title: string;
  description: string;
  code_prefixes: string[];
  keywords: string[];
  has_prices: boolean;
  kind: string;
  price_basis: string;
  effective_date: string | null;
  score: number;
  /** Why this page matched, so a wrong hit is legible rather than mysterious. */
  why: string[];
}

export interface ProductSearchResponse {
  /** The estimator's own parts. Editable. */
  products: Product[];
  /** Pages of the vendor price books. Read-only, and not priced lines. */
  pages?: CatalogPage[];
  /** Full filtered match count (not the current page length). */
  total: number;
  counts?: { manual: number; pages: number };
  divisions: { division: string; count: number }[];
  /** False until `python -m cbc.pageindex.build --all` has been run. */
  indexAvailable?: boolean;
  note?: string | null;
  pagesNote?: string | null;
}

/** Legacy parse progress on a price book (mirrors BidDocument.parse). */
export interface PriceBookParse {
  state?: string;
  pages?: number;
  pagesDone?: number;
  error?: string | null;
  sheetId?: string | null;
  catalogId?: string | null;
  startedAt?: string | null;
  finishedAt?: string | null;
}

export interface PriceBook {
  id: string;
  vendor: string;
  displayName?: string | null;
  program?: string | null;
  multiplier: number | null;
  categories?: Record<string, number> | null;
  effective: string | null;
  protectedThrough?: string | null;
  lastReviewed?: string | null;
  steward?: string | null;
  account?: string | null;
  note?: string | null;
  /** `price_book` (default) or `multiplier_sheet`. */
  kind?: string | null;
  filename?: string | null;
  path?: string | null;
  bytes?: number | null;
  uploadedAt?: string | null;
  catalogId?: string | null;
  /** Page-index status after `index_catalog` (e.g. ready / removed). */
  indexStatus?: string | null;
  parse?: PriceBookParse | null;
  partCount: number;
  ageDays: number | null;
  stale: boolean;
  undated: boolean;
  /** Sheets this book has carried before, newest supersession last. */
  sheetHistory?: {
    filename?: string | null;
    path?: string | null;
    bytes?: number | null;
    effective?: string | null;
    uploadedAt?: string | null;
    supersededAt?: string | null;
    supersededBy?: string | null;
  }[];
  /** Local dev: staleness follows lastReviewed when set. */
  devFreshnessControls?: boolean;
  staleReferenceField?: "effective" | "lastReviewed";
  staleReferenceDate?: string | null;
}

/** `POST /api/price-books/{id}/file` — sheet attached and jobs queued. */
export interface PriceBookUploadResponse {
  priceBook: PriceBook;
  job: Job;
  parseJob?: Job | null;
}

/**
 * `GET /api/catalog/products/{id}`.
 * `marginBand` is the division band key from the API (e.g. "commodity").
 */
export interface ProductDetailResponse {
  product: Product;
  priceBook: PriceBook | null;
  marginBand: string | null;
}

export interface ProposalSection {
  key: string;
  title: string;
  subtotal: number;
  lines: {
    part: string | null;
    qty: number;
    uom: string;
    description: string;
    unitPrice: number | null;
    extPrice: number | null;
    priceStatus?: string | null;
  }[];
}

export interface ProposalResponse {
  proposal: {
    proposalNo: string;
    date: string;
    validityDays: number;
    customer: Record<string, string | null>;
    salesRep: Record<string, string | null>;
    estimator: Record<string, string | null>;
    markup: number;
    exclusions: string[];
    signoff: { role: string; by: string; at: string; state: string }[];
    sentAt: string | null;
  };
  project: Project;
  sections: ProposalSection[];
  totals: QuoteTotals & { markup: number };
  readiness: {
    flaggedLineItems: number;
    unpricedQuoteLines: number;
    /** Lines priced off a sheet past its review window. */
    lapsedLines: number;
    /** Who took responsibility for those lines, if anyone has. */
    lapsedAcknowledgedBy?: string | null;
    /** True only for lapsed lines: the one gate that stops a hand-off. */
    blocking: boolean;
    note: string;
  };
}

export interface ProviderField {
  value: string | null;
  variable: string;
  secret: boolean;
  /** Set from the environment, so the settings screen cannot change it. */
  locked: boolean;
  configured: boolean;
}

export interface ClaudeSettings {
  mode: "subscription" | "anthropic_api" | "bedrock" | "ollama" | "nim";
  modes: string[];
  fields: Record<string, ProviderField>;
  /** Field shape for every mode, so an unsaved provider still renders a form. */
  schema: Record<string, Record<string, ProviderField>>;
  updatedAt?: string | null;
  updatedBy?: string | null;
  localDev: boolean;
  cliAvailable: boolean;
}

/** One runtime PARSER_* field from GET /api/settings/parsing. */
export interface ParsingField {
  value: string | number | boolean | null;
  source: string;
  /** Process env owns this field — the settings screen cannot change it. */
  locked: boolean;
}

export interface ParsingSettings {
  enabled: boolean;
  fields: Record<string, ParsingField>;
  /** cost_effective | agentic | agentic_plus. `fast` is excluded: no bboxes. */
  tiers: string[];
  updatedAt?: string | null;
  updatedBy?: string | null;
}

export interface ParsingTestResult {
  ok: boolean;
  seconds: number | null;
  blocks: number | null;
  tier?: string;
  /**
   * Share of returned boxes landing on text actually present on the sample page.
   * Null when there was no text layer to score against.
   */
  verified?: number | null;
  error: string | null;
}

/** `GET /api/projects/{code}/documents/{id}/pages/{n}/blocks`. */
export interface PageBlock {
  n?: number;
  type?: string;
  text?: string;
  bbox?: number[] | null;
  html?: string;
  lines?: { bbox?: number[] | null; text?: string }[];
}

export interface PageBlocksResponse {
  documentId: string;
  page: number;
  pageSize?: { width: number; height: number } | null;
  verified: number | null;
  parser?: Record<string, unknown> | null;
  blocks: PageBlock[];
  start: number;
  next: number | null;
  total: number;
}

export interface ProviderTest {
  ok: boolean;
  error: string | null;
  provider: {
    mode: string;
    model: string;
    baseUrl: string | null;
    region: string | null;
    credentialSource: Record<string, string>;
    warnings?: string[];
  };
}

export interface OllamaModel {
  name: string | null;
  size: number | null;
  modifiedAt: string | null;
}

export interface OllamaModelsResponse {
  baseUrl: string;
  models: OllamaModel[];
}


/* --- Mutation responses -------------------------------------------------- */
/* Shapes the screens used to read straight off an untyped `response.json()`. */

export interface BulkResult {
  affected: number;
}

export interface AlternateAssignResult {
  moved: number;
}

export interface UploadResult {
  document: BidDocument;
  job?: Job | null;
  autopilot?: boolean;
  version?: number | null;
  waitingForSiblings?: boolean;
  stragglerPending?: boolean;
  note?: string | null;
}

export interface HandOffResult {
  handedOffTo: string | null;
  message: string;
  draftPath: string;
  sent: boolean;
}

export interface EmailDraft {
  to: string | null;
  subject: string;
  body: string;
  note?: string | null;
}

export interface OauthStart {
  session: string;
  url: string;
}

/** A rejected code makes the CLI start a fresh authorization, hence the new url. */
export interface OauthCodeError {
  message?: string;
  hint?: string;
  url?: string;
}

export interface CallEntry {
  id: string;
  kind: "call" | "note" | "rfi";
  text: string;
  who: string;
  org?: string | null;
  ref?: string | null;
  createdAt: string;
  resolvedAt?: string | null;
}

export interface CallsResponse {
  calls: CallEntry[];
  count: number;
  openRfis: number;
}

export interface VersionSummary {
  id: string;
  version: number;
  reason: string;
  createdAt: string;
  createdBy: string;
  reconciled: boolean;
  lineItemCount: number;
  quoteLineCount: number;
}

export interface VersionDiff {
  version: number;
  added: string[];
  removed: string[];
  changed: {
    mark: string;
    fields: string[];
    before: Record<string, unknown>;
    after: Record<string, unknown>;
  }[];
  pending: string;
}

export interface VersionsResponse {
  versions: VersionSummary[];
  current: number;
  unreconciled: number;
  pending: string;
}

export interface Alternate {
  name: string | null;
  label: string;
  isBase: boolean;
  lineItemCount: number;
  quoteLineCount: number;
  subtotal: number;
  grandTotal: number;
  unpricedLines: number;
}

export interface AlternatesResponse {
  alternates: Alternate[];
  pending: string;
}

export interface PriceBooksResponse {
  priceBooks: PriceBook[];
  counts: { total: number; stale: number; undated: number };
  stewardship: { owner: string | null; cadence: string | null; note: string };
  devFreshnessControls?: boolean;
}

export interface PriceBookDetail {
  priceBook: PriceBook;
  parts: Product[];
  partCount: number;
}

export interface MarginBand {
  key: string;
  name: string;
  margin: number;
  divisor: number;
  examples?: string[];
}

export interface MarginFramework {
  bands: MarginBand[];
  accessoriesDerived: number | null;
  formula: string | null;
  overridable: boolean | null;
  governance: string | null;
  source: string | null;
  effective: Record<string, number>;
}

export interface TaxRates {
  rates: Record<string, number>;
  description: string | null;
  source: string | null;
  note: string | null;
}

export interface AdderItem {
  name: string;
  list_adder: number;
}

export interface AdderType {
  type: string;
  note: string;
}

export interface ManualAdders {
  adderTypes: AdderType[];
  hagerListAdders: {
    source: string | null;
    status: string | null;
    application: string | null;
    items: AdderItem[];
  };
  pending: string[];
  rule: string | null;
}

export interface SpecialCustomer {
  name: string;
  margin: number | null;
  note?: string | null;
  source?: string | null;
}

export interface SpecialMargins {
  customers: SpecialCustomer[];
  rule: string | null;
  status: string | null;
  description: string | null;
}

export interface FinishEntry {
  us_code: string;
  numeric_code: string | null;
  description: string | null;
  premium: boolean | null;
  note: string | null;
}

export interface FinishCrosswalk {
  finishes: FinishEntry[];
  warning?: string | null;
  hager_rules?: string[];
  premium_finish_rule?: string | null;
}

export interface WallTypeEntry {
  type: string;
  depth: string;
  depth_inches: number;
  note: string | null;
}

export interface FrameDepths {
  wall_types: WallTypeEntry[];
  custom_option?: boolean;
  custom_max?: number;
  adjustable_frames?: boolean;
  adjustable_note?: string | null;
  unknown_wall_type_rule?: string | null;
}

export interface FrpConstants {
  status: string;
  blocking?: string | null;
  description?: string | null;
  panel_size: string | null;
  panel_size_note?: string;
  waste_pct: number | null;
  waste_pct_note?: string;
  trim_stick_length: number | null;
  trim_stick_length_note?: string;
  adhesive_coverage_sqft_per_unit: number | null;
  adhesive_coverage_note?: string;
  opening_handling: string | null;
  opening_handling_note?: string;
  trim_types?: string[];
  vendors?: string[];
}

export interface VendorTierRow {
  key: string;
  name?: string;
  categories?: Record<string, number>;
  multiplier?: number | null;
  tier?: string | null;
  note?: string | null;
}

export interface VendorTierDoc {
  vendors: VendorTierRow[];
  description?: string;
  rule?: string;
}

export interface SpecialNetsDoc {
  vendor?: string;
  items: Array<{
    part_number: string;
    net_price: number;
    description?: string;
    item_code?: string;
  }>;
  effective_date?: string;
  source?: string;
}

export interface LiteKitTableMeta {
  index: number;
  pdf_page?: number;
  title?: string;
  widthCount: number;
  heightCount: number;
}

export interface LiteKitResponse {
  tableCount: number;
  tables: LiteKitTableMeta[];
  data: Record<string, unknown>;
}

export interface StockListDoc {
  items: Array<{ part_number: string; description?: string }>;
  status?: string;
  status_note?: string;
  source?: string;
}

export type CustomOtherMatrix = Record<string, unknown>;

export interface AuditEntry {
  id: string;
  at: string;
  actor: string;
  action: string;
  note?: string | null;
}

export interface UserRow {
  id: string;
  email: string;
  name: string;
  initials: string;
  role: string;
}

export interface PipelineSettings {
  autopilotDefault: boolean;
  note?: string;
  updatedAt?: string | null;
  updatedBy?: string | null;
}

export interface FreshnessSettings {
  catalogStaleMonths: number;
  discardAfterMonths: number;
  catalogStaleDays: number;
  discardAfterDays: number;
  rule?: string;
  note?: string;
  updatedAt?: string | null;
  updatedBy?: string | null;
}

export interface IntegrationStatus {
  connected: boolean;
  path?: number;
  requirement?: string;
  status: string;
  title: string;
  summary: string;
  note: string;
  adminNote?: string | null;
  fallbacks?: string[];
}

export interface IntegrationsResponse {
  p21: IntegrationStatus;
}

/** `GET /api/jobs/metrics` — queue depth and throughput, for the admin screen. */
export interface JobMetrics {
  windowHours: number;
  queued: number;
  running: number;
  oldestQueuedAt: string | null;
  finished: number;
  failed: number;
  /** null when nothing finished in the window — no news, not good news. */
  failureRate: number | null;
  byType: Record<
    string,
    { total: number; done: number; failed: number; avgSeconds: number | null }
  >;
}

/** `GET /api/ops/spend` — LLM spend vs worker cost caps. */
export interface SpendSummary {
  windowHours: number;
  since: string;
  totalCostUsd: number;
  runs: number;
  dailyCapUsd: number | null;
  projectCapUsd: number | null;
  overDailyCap: boolean;
  byType: { jobType: string; totalCostUsd: number; runs: number }[];
  byProject: {
    projectId: string | null;
    projectSlug: string | null;
    totalCostUsd: number;
    runs: number;
    overProjectCap: boolean;
  }[];
  recent: {
    id: string;
    jobId?: string | null;
    jobType?: string | null;
    projectId?: string | null;
    projectSlug?: string | null;
    totalCostUsd: number | null;
    cacheHitRatio: number | null;
    startedAt?: string | null;
    finishedAt?: string | null;
  }[];
}

/** One statistic over a cohort's runs. */
export interface CohortStat {
  median: number;
  mean: number;
  n: number;
}

/** `GET /api/ops/cohorts` — LLM spend grouped by config cohort (W1b). */
export interface CohortSummary {
  days: number;
  since: string;
  jobType: string | null;
  cohorts: {
    cohortId: string;
    jobType: string;
    context: Record<string, unknown>;
    runs: number;
    costUsd: CohortStat;
    durationApiMs: CohortStat;
    toolCalls: CohortStat;
    firstRun?: string | null;
    lastRun?: string | null;
    changedFrom: {
      keys: string[];
      deltaPct: { costUsd?: number };
    } | null;
  }[];
}

/** `GET /api/projects/{code}/review-flags` - NFR-2, derived on every read. */
export interface ReviewFlag {
  opening?: string | null;
  opening_id?: string | null;
  field?: string | null;
  category?: string | null;
  severity: string;
  source_page?: number | null;
  note?: string | null;
  issue?: string | null;
  action_required?: string | null;
  derived?: boolean;
}

/** `GET /api/projects/{code}/vendor-rfqs` - FR-16, the third cost path. */
export interface VendorRfq {
  id: string;
  rfqNumber: string;
  triggerReason: string;
  vendorId?: string | null;
  requestedItems?: {
    description?: string | null;
    partNumber?: string | null;
    quantity?: number | null;
  }[];
  status: string;
  dueBy?: string | null;
  blocksBid?: boolean;
  /** Recorded when the RFQ is marked received, each against the quote line it prices. */
  quotedPrices?: {
    estimateLineId: string;
    amount: number;
    leadTimeDays?: number | null;
    notes?: string | null;
  }[];
  respondedAt?: string | null;
}

/** `GET /api/projects/{code}/rfis` - questions raised before the quote is final. */
export interface Rfi {
  id: string;
  rfiNumber: string;
  subject: string;
  question: string;
  category: string;
  status: string;
  blocksFinalization?: boolean;
  raisedBy?: string | null;
  raisedAt?: string | null;
  answer?: string | null;
  answeredAt?: string | null;
}
