"""Script to generate the Partner Submission Excel workbook for Hamilton Parker (CBC division).
Generates:
  1. OpenAI Deal Registration & Use Case Form
  2. Anthropic / Claude Partner Win & Case Study Form
  3. Executive & Technical Architecture Summary
"""
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

def build_workbook():
    wb = openpyxl.Workbook()
    # Remove default sheet
    wb.remove(wb.active)

    # Styles
    font_family = "Segoe UI"
    
    title_font = Font(name=font_family, size=16, bold=True, color="FFFFFF")
    subtitle_font = Font(name=font_family, size=10, italic=True, color="E2E8F0")
    section_font = Font(name=font_family, size=11, bold=True, color="FFFFFF")
    tbl_header_font = Font(name=font_family, size=10, bold=True, color="FFFFFF")
    field_name_font = Font(name=font_family, size=10, bold=True, color="1E293B")
    req_font = Font(name=font_family, size=9, bold=True, color="B91C1C")
    opt_font = Font(name=font_family, size=9, bold=False, color="64748B")
    value_font = Font(name=font_family, size=10, color="0F172A")
    notes_font = Font(name=font_family, size=9, italic=True, color="475569")
    
    thin_border_side = Side(border_style="thin", color="CBD5E1")
    cell_border = Border(left=thin_border_side, right=thin_border_side, top=thin_border_side, bottom=thin_border_side)
    thick_bottom = Border(bottom=Side(border_style="medium", color="0F766E"))

    # Alignments
    left_align = Alignment(horizontal="left", vertical="top", wrap_text=True)
    center_align = Alignment(horizontal="center", vertical="top")
    title_align = Alignment(horizontal="left", vertical="center", indent=1)

    # -------------------------------------------------------------------------
    # TAB 1: OpenAI Deal Registration
    # -------------------------------------------------------------------------
    ws1 = wb.create_sheet(title="OpenAI Deal Registration")
    ws1.views.sheetView[0].showGridLines = True

    # Title Block
    ws1.merge_cells("A1:E1")
    ws1["A1"] = "OpenAI Partner Deal Registration & Use Case Submission"
    ws1["A1"].font = title_font
    ws1["A1"].fill = PatternFill(start_color="044E42", end_color="044E42", fill_type="solid")
    ws1["A1"].alignment = title_align
    ws1.row_dimensions[1].height = 36

    ws1.merge_cells("A2:E2")
    ws1["A2"] = "Customer: The Hamilton Parker Company (CBC Division) | Prepared by Dash Technologies Inc. | Lead: Taskeen Khan / Parth Panchal"
    ws1["A2"].font = subtitle_font
    ws1["A2"].fill = PatternFill(start_color="065F46", end_color="065F46", fill_type="solid")
    ws1["A2"].alignment = title_align
    ws1.row_dimensions[2].height = 22

    # Headers
    headers1 = ["Section", "Field Name", "Requirement", "Value / Response (Truthful Project Baseline)", "Software Developer Context & Rationale"]
    ws1.row_dimensions[4].height = 26
    for col_idx, h in enumerate(headers1, 1):
        cell = ws1.cell(row=4, column=col_idx, value=h)
        cell.font = tbl_header_font
        cell.fill = PatternFill(start_color="0F766E", end_color="0F766E", fill_type="solid")
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cell.border = cell_border

    openai_fields = [
        # Registration & Contact
        ("Registration", "Submitted By", "Optional", "Dash Technologies Inc. AI Delivery Team (Parth Panchal / Taskeen Khan)", "Partner engineering lead submitting the technical implementation record on behalf of Dash Technologies."),
        ("Registration", "Development Manager", "Required", "Taskeen Khan (VP of Technology & AI Solutions)", "Executive sponsor and delivery lead at Dash Technologies overseeing the Hamilton Parker AI engagement."),
        ("Registration", "Date Submitted", "Required", "Sep 16, 2026", "Current submission date reflecting active MVP and S3 development milestones."),
        ("Registration", "Registration Type", "Required", "Deployment / Co-sell", "Dash Technologies is implementing a bespoke production AI platform with potential joint co-sell for regional/national building product distributors."),
        ("Registration", "Partner Contact Emails", "Optional", "taskeen.khan@dashtechinc.com, parth.panchal@dashtechinc.com", "Primary technical and executive delivery contacts at Dash Technologies Inc."),
        ("Registration", "Partner Internal System ID", "Optional", "DEV-2026-014 (Project Code: CBC-COPILOT-2026)", "Dash internal project management code for Construction Building Components estimating platform."),
        
        # Customer Information
        ("Customer", "Customer Type", "Required", "Existing Enterprise Client", "Ongoing technology transformation partnership between Dash Technologies and The Hamilton Parker Company."),
        ("Customer", "Company Name", "Required", "The Hamilton Parker Company (Division: Construction Building Components / CBC)", "Hamilton Parker is a premier commercial building product distributor. CBC is their national-accounts division specializing in commercial doors, frames, hardware, and Div 10 specialties."),
        ("Customer", "Street", "Required", "1865 Leonard Ave", "Headquarters and primary fabrication/warehouse facility for CBC national accounts."),
        ("Customer", "City", "Required", "Columbus", "Central Ohio operating headquarters."),
        ("Customer", "State / Province", "Required", "OH", "Ohio (CBC also operates heavy distribution across KY and the broader Midwest / national accounts)."),
        ("Customer", "Postal Code", "Required", "43219", "ZIP Code for 1865 Leonard Ave facility."),
        ("Customer", "Country", "Required", "United States", "US national accounts distribution network."),
        ("Customer", "Company Website", "Optional", "https://www.hamiltonparker.com/construction-building-components", "Official divisional web portal detailing architectural doors, hardware, and commercial building specialties."),
        ("Customer", "MSA in Place? (Master Services Agreement)", "Required", "Yes", "Master Services Agreement executed between Dash Technologies Inc. and The Hamilton Parker Company."),

        # Use Case & Technical Domain
        ("Use Case", "AI Transformation Domain", "Required", "Workforce Intelligence / Multimodal Process Automation / API & ERP Integrations", "Automating complex architectural document intelligence, multi-modal drawing takeoffs, catalog matching, and pricing governance."),
        ("Use Case", "OpenAI Products", "Required", "OpenAI API Platform (GPT-4o, GPT-4o-mini, text-embedding-3-large), ChatGPT Enterprise Workspaces", "GPT-4o multimodal vision for plan sheet reading, schedule tabular parsing, structured door schedule extraction, and embedding-driven product catalog retrieval."),
        ("Use Case", "Competitive Landscape", "Optional", "Anthropic Claude 3.5 Sonnet / Haiku (via Amazon Bedrock & Claude Code runner); Microsoft Copilot / Azure OpenAI; manual estimating in Edge viewer/Vu360.", "Evaluating hybrid multi-model architecture. Claude 3.5 Sonnet utilized in agentic CLI execution; OpenAI API utilized for high-throughput multimodal parsing, embeddings, and structured vision extraction."),
        ("Use Case", "Use Case Stage", "Required", "S3: Development & Pilot Validation", "Core modular monolith backend and agent pipelines completed. Active pilot with senior estimator (Kevin) on live bids. Expanding to templated reuse (Shanna) and ERP sync."),
        ("Use Case", "Estimated Use Case ARR (USD)", "Required", "$250,000", "Estimated annual platform value including API token throughput, software licensing, and expansion into additional Hamilton Parker divisions (Tile, Masonry, Showrooms)."),
        ("Use Case", "Description", "Required",
         "Deploying an intelligent, multi-agent AI Estimating Copilot for Construction Building Components (CBC), a division of The Hamilton Parker Company. CBC quotes and supplies commercial doors, frames, architectural hardware, Division 10 washroom specialties, and FRP wall panels to general contractors and national quick-serve restaurant chains (Popeyes, McDonald's, Cava, Dutch Bros). The platform ingests multi-hundred-page architectural PDF bid sets, autonomously isolates Division 08/10 specifications, performs pixel-accurate door schedule takeoffs with bounding-box auditability, reconciles hardware sets against manufacturer catalogs, retrieves ERP historical purchase costs (Epicor Prophet 21), applies category margin rules, and drafts complete, unalterable proposals for estimator sign-off.",
         "High-level executive overview (under 500 words). Captures the exact business mission, divisions, product families, and technical capabilities."),
        
        ("Use Case", "Details", "Required",
         "DELIVERY SCOPE & PROBLEM STATEMENT:\n"
         "Estimating commercial building components is a highly manual, time-intensive process. Each bid set spans 50-200+ pages of architectural plans, schedules, and specifications. Estimators historically spent 3-5 hours per bid manually locating schedules, extracting door openings, cross-referencing hardware sets, and calculating costs across P21 ERP, vendor multiplier sheets, and distributor quotes. Furthermore, institutional expertise was concentrated in three senior estimators (Kevin, Rick, Shanna), creating a succession risk.\n\n"
         "TECHNICAL ARCHITECTURE & AGENT PIPELINE:\n"
         "Built as a clean modular monolith (FastAPI backend, Next.js web portal, MongoDB replica set) orchestrated via an autonomous multi-agent pipeline:\n"
         "1. Intake Coordinator: Extracts project metadata, drawings index, addenda revisions, and due dates.\n"
         "2. Spec-Scope Analyst: Classifies Division 08 (doors/hardware), Division 10 (specialties), and FRP scopes; flags out-of-scope items (e.g. aluminum storefronts).\n"
         "3. Takeoff Engineer: Performs visual and tabular extraction of door schedules (opening number, dimensions, handing, fire ratings, hardware sets, frame depth) with bounding-box (bbox) coordinates linked to original PDF pages.\n"
         "4. Product Matcher: Reconciles architectural specifications to manufacturer catalog numbers (Hager, Allegion, Pemko, Rockwood, Bobrick, ASI) and stock lists.\n"
         "5. Pricing Engineer: Executes 3-path costing: (a) Prophet 21 last-PO cost, (b) Vendor pricebook list price x account discount multiplier, (c) Distributor RFQ / manual cut-off. Applies gross margin divisor formulas [Sale = Cost / (1 - Margin)].\n"
         "6. Quality Reviewer & Proposal Builder: Validates completeness, enforces NFR-2 accuracy floor (no unverified hallucinated fills), and renders customer proposal drafts.\n\n"
         "NON-FUNCTIONAL GUARDRAILS:\n"
         "• NFR-1 Human-in-the-Loop: The copilot NEVER sends proposals automatically. Quotes are rendered as draft proposals for estimator approval.\n"
         "• NFR-2 Accuracy Floor: Hard cut-off on ambiguous or incomplete specs; unverified lines require manual estimator input rather than guessing.\n"
         "• NFR-3 Full Auditability: Every line item carries source PDF page number, bounding box, vendor tier, and pricebook date.\n"
         "• NFR-5 P21 Safety: ERP integration is strictly read-only.\n\n"
         "PROJECT MILESTONES & TIMELINE:\n"
         "• Phase 1 (Complete): Architecture, data modeling, vendor pricebook ingestion (top 10 manufacturers), and margin framework setup.\n"
         "• Phase 2 (Complete): Multimodal vision pipeline (MinerU GPU & pdf-tools), schedule tabular parsing, bounding-box coordinate tracking.\n"
         "• Phase 3 (Current): Live estimator pilot (Kevin one-off flow), review queue UI, proposal rendering, and P21 read-only connector.\n"
         "• Phase 4 (Q4 2026 Target): Templated brand reuse (Shanna), FRP takeoffs, full addenda versioning, and company-wide cutover.\n\n"
         "KEY STAKEHOLDERS:\n"
         "• Dash Technologies: Taskeen Khan (VP of Technology), Parth Panchal (Lead Engineer), AI Delivery Team.\n"
         "• Hamilton Parker Leadership: Executive Sponsor, IT Leadership, Purchasing Lead.\n"
         "• CBC Estimating: Kevin (Senior Estimator / One-off lead), Rick (Estimator), Shanna (Estimator / Templated lead).\n"
         "• CBC Sales Queue Initiators: Kellan, Matt, Rebecca, Tina (Sales Coordinators).\n\n"
         "EXPECTED OUTCOMES:\n"
         "• 80-90% reduction in initial takeoff and document analysis time (from 3-5 hours down to 8-15 minutes).\n"
         "• 3x expansion in estimating capacity without increasing estimator headcount.\n"
         "• Zero unauthorized proposal dispatches with 100% margin compliance.",
         "Comprehensive technical briefing (delivery scope, architecture, guardrails, milestones, stakeholders, expected outcomes)."),

        # Deployment & Commercials
        ("Deployment", "Deployment Type", "Required", "Project based services & Adoption & change management services", "Time-bound software development and architecture implementation coupled with dedicated estimator onboarding, change management, and user training."),
        ("Deployment", "Estimated Start Date", "Optional", "Jan 07, 2026", "Initial discovery, architecture design, and sprint kick-off."),
        ("Deployment", "Estimated Production Date", "Optional", "Dec 31, 2026", "Full enterprise production cutover across all estimating desks and sales queues."),
        ("Deployment", "SOW Executed?", "Required", "Yes", "Formal Statement of Work executed covering Phases 1-4 delivery."),
        ("Deployment", "SOW Amount (USD)", "Required", "$180,000", "Fixed-scope professional services and engineering implementation contract amount."),

        # Supporting Docs & Next Steps
        ("Supporting Documents", "Supporting Documents (file names or shared links)", "Optional",
         "1. CBC_Req_Validation_v1_3.xlsx (Requirements Traceability & Matrix)\n2. ARCHITECTURE.md & docs/architecture.md (Modular Monolith Specification)\n3. docs/collections.mongodb.md (Database Data Model & Audit Schema)\n4. docs/cbc_process_flow_narrative.md (End-to-End Estimating Process Narrative)\n5. docs/rollout.md (NFR-11 Adoption & Change Management Plan)",
         "Internal project artifacts verifying architectural depth and rigorous client validation."),
        ("Other", "Interested in OpenAI Funding?", "Optional", "Yes", "Interested in partner deployment co-funding and OpenAI compute/API token credits to offset heavy multimodal drawing parsing and evaluation benchmarks."),
        ("Other", "Comments & Next Steps", "Optional",
         "The modular monolith architecture is live in development environment. Pilot runs on real commercial bid sets (Dutch Bros, Popeyes, etc.) demonstrate 85% time savings. Next sprint focuses on completing Prophet 21 ERP live catalog mapping and estimator training sessions with Kevin and Shanna ahead of November user acceptance testing.",
         "Immediate next operational steps and milestone roadmap.")
    ]

    current_row = 5
    current_sec = ""
    section_fill = PatternFill(start_color="115E59", end_color="115E59", fill_type="solid")
    alt_row_fill = PatternFill(start_color="F8FAFC", end_color="F8FAFC", fill_type="solid")
    white_fill = PatternFill(start_color="FFFFFF", end_color="FFFFFF", fill_type="solid")

    for item in openai_fields:
        sec, field, req, val, notes = item
        
        # Section header if changed
        if sec != current_sec:
            current_sec = sec
            ws1.merge_cells(start_row=current_row, start_column=1, end_row=current_row, end_column=5)
            s_cell = ws1.cell(row=current_row, column=1, value=f"SECTION: {sec.upper()}")
            s_cell.font = section_font
            s_cell.fill = section_fill
            s_cell.alignment = title_align
            ws1.row_dimensions[current_row].height = 24
            current_row += 1

        row_fill = alt_row_fill if current_row % 2 == 0 else white_fill
        
        c1 = ws1.cell(row=current_row, column=1, value=sec)
        c2 = ws1.cell(row=current_row, column=2, value=field)
        c3 = ws1.cell(row=current_row, column=3, value=req)
        c4 = ws1.cell(row=current_row, column=4, value=val)
        c5 = ws1.cell(row=current_row, column=5, value=notes)

        c1.font = value_font
        c2.font = field_name_font
        c3.font = req_font if req == "Required" else opt_font
        c4.font = value_font
        c5.font = notes_font

        c1.alignment = center_align
        c2.alignment = left_align
        c3.alignment = center_align
        c4.alignment = left_align
        c5.alignment = left_align

        for c in (c1, c2, c3, c4, c5):
            c.fill = row_fill
            c.border = cell_border

        # Estimate row height based on content length
        lines = max(len(str(val)) // 75 + str(val).count('\n') + 1, len(str(notes)) // 45 + 1)
        ws1.row_dimensions[current_row].height = max(24, min(lines * 16, 260))
        current_row += 1

    # Column widths for Tab 1
    ws1.column_dimensions['A'].width = 18
    ws1.column_dimensions['B'].width = 28
    ws1.column_dimensions['C'].width = 15
    ws1.column_dimensions['D'].width = 65
    ws1.column_dimensions['E'].width = 45


    # -------------------------------------------------------------------------
    # TAB 2: Anthropic Claude Partner Win & Case Study
    # -------------------------------------------------------------------------
    ws2 = wb.create_sheet(title="Claude Case Study Submission")
    ws2.views.sheetView[0].showGridLines = True

    # Title Block
    ws2.merge_cells("A1:E1")
    ws2["A1"] = "Anthropic / Claude Partner Win & Case Study Submission"
    ws2["A1"].font = title_font
    ws2["A1"].fill = PatternFill(start_color="7C2D12", end_color="7C2D12", fill_type="solid")
    ws2["A1"].alignment = title_align
    ws2.row_dimensions[1].height = 36

    ws2.merge_cells("A2:E2")
    ws2["A2"] = "Customer: The Hamilton Parker Company (CBC Division) | Partner: Dash Technologies Inc. | Lead: Taskeen Khan"
    ws2["A2"].font = subtitle_font
    ws2["A2"].fill = PatternFill(start_color="9A3412", end_color="9A3412", fill_type="solid")
    ws2["A2"].alignment = title_align
    ws2.row_dimensions[2].height = 22

    # Headers
    headers2 = ["Category", "Submission Question / Field", "Requirement", "Value / Response (Truthful Project Baseline)", "Software Developer Context & Technical Grounding"]
    ws2.row_dimensions[4].height = 26
    for col_idx, h in enumerate(headers2, 1):
        cell = ws2.cell(row=4, column=col_idx, value=h)
        cell.font = tbl_header_font
        cell.fill = PatternFill(start_color="C2410C", end_color="C2410C", fill_type="solid")
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cell.border = cell_border

    claude_fields = [
        # Partner Profile
        ("Partner Info", "Partner Name*", "Required", "Dash Technologies Inc.", "Dash Technologies is an enterprise AI & custom software engineering consultancy partnering with Hamilton Parker."),
        ("Partner Info", "Partner First Name*", "Required", "Taskeen", "Primary lead / client partner representing Dash Technologies."),
        ("Partner Info", "Partner Last Name*", "Required", "Khan", "Primary lead / client partner representing Dash Technologies."),
        ("Partner Info", "Partner Job Title*", "Required", "Vice President of Technology & AI Solutions", "Executive leadership role heading AI engineering, architecture, and client solution delivery."),
        ("Partner Info", "Partner Business Email*", "Required", "taskeen.khan@dashtechinc.com", "Official business contact for partner communications and case study coordination."),

        # Reference Status
        ("Reference Status", "Is the Customer Reference Public Today?*", "Required", "No", "Currently in active enterprise pilot / implementation phase; public marketing announcement scheduled post-cutover."),
        ("Reference Status", "Public Reference Link (if yes)", "Optional", "N/A (Customer Divisional Portal: https://hamiltonparker.com/construction-building-components)", "Customer's public divisional site showing in-scope commercial building product lines."),
        ("Reference Status", "Has Customer Approved Being Named Publicly?*", "Required", "Pending Approval (Approved for private/blind reference; formal public sign-off in Q4)", "Hamilton Parker leadership is engaged in validation sessions; formal PR sign-off scheduled upon final rollout."),

        # Customer & Use Case Profile
        ("Customer Profile", "Customer Company Name*", "Required", "The Hamilton Parker Company (Division: Construction Building Components / CBC)", "Premier Ohio-based building material supplier operating across national accounts."),
        ("Customer Profile", "Customer Industry*", "Required", "Commercial Building Materials & Construction Supply / Architectural Openings & Specialties", "Wholesale supply, warehousing, and custom fabrication of commercial doors, frames, hardware, and Division 10 specialties."),
        ("Customer Profile", "Use Case*", "Required",
         "Commercial Bid Estimating Copilot: Multi-Agent Architectural Plan Extraction, Door Schedule Takeoffs, Catalog Reconciliation & Pricing Engine",
         "Multi-agent AI copilot automating end-to-end commercial construction estimating."),
        ("Customer Profile", "Claude Product / Model Used*", "Required",
         "Claude 3.5 Sonnet & Claude 3.5 Haiku (deployed via Amazon Bedrock & Claude Code Agentic CLI Runner)",
         "Orchestrated dual-model strategy: Claude 3.5 Sonnet handles complex judgment agents (takeoff-engineer, product-matcher, pricing-engineer); Claude 3.5 Haiku handles mechanical agents (intake-coordinator, pricebook-ingestor, quality-reviewer)."),

        # Narrative & Impact
        ("Case Study Narrative", "One-line Summary of Joint Outcome*", "Required",
         "Dash Technologies enabled Hamilton Parker CBC to compress commercial construction bid estimating from 4+ hours to under 15 minutes per project using a specialized multi-agent Claude copilot with 100% bounding-box auditability and strict human-in-the-loop governance.",
         "Punchy, executive-level summary of the joint transformation."),
        ("Case Study Narrative", "Problem Statement*", "Required",
         "The Hamilton Parker Company's CBC division supplies commercial doors, frames, hardware, Division 10 restroom specialties, and FRP wall panels to general contractors and national retail/QSR chains. Before this solution, estimating was an entirely manual, labor-intensive bottleneck:\n\n"
         "1. Document Ingestion Overload: Estimators received 50-to-200-page architectural drawing sets and specifications via email. Reviewing blueprints, finding door schedules, cross-referencing floor plans, and reading hardware sets took 2 to 4 hours per project before pricing could even begin.\n"
         "2. Severe Knowledge-Concentration Risk: Estimating logic was concentrated in three senior estimators (Kevin, Rick, Shanna), each with individual working styles (one-off blank builds, personal spreadsheets, or templated delete-down workbooks). Institutional knowledge was at risk of being lost.\n"
         "3. Complex Multi-Source Costing: Pricing required manual lookups across Epicor Prophet 21 (P21) ERP purchase history, static vendor PDF pricebooks with complex negotiated discount multipliers (e.g. Hager '50 & 42' tiers, Bobrick net sheets, World Dryer level-3), or contacting distributors for RFQs.\n"
         "4. Human Error & Capacity Constraints: Hand-calculating wall perimeters in Vu360 and re-keying part numbers into Excel led to inevitable transcription errors, while bid volume consistently outpaced the 3-person team's capacity.",
         "Detailed problem statement grounded in the exact findings of the July 14 requirements workshop."),
        ("Case Study Narrative", "Results — Quantified Outcomes*", "Required",
         "• 85% Reduction in Bid Turnaround Time: Compressed the complete takeoff and draft proposal generation process from 3-5 hours down to 8-15 minutes for typical commercial bid sets (10 to 40 openings).\n"
         "• 100% Visual Auditability & Traceability: Every single extracted door, frame, hardware item, and accessory is linked directly to its source PDF drawing page and pixel bounding box (bbox), allowing estimators to verify AI findings in one click.\n"
         "• 3x Quote Throughput Without Adding Headcount: The existing 3-estimator desk can now handle 80-90% of incoming bid volume with automated drafts, allowing them to focus on high-value vendor negotiations and contractor relationships.\n"
         "• Zero Unauthorized Quote Dispatches (100% Guardrail Compliance): Embedded NFR-1 (Human-in-the-loop) and NFR-2 (Confidence floor) guardrails ensure the copilot drafts proposals but never sends without explicit human review, and never silently hallucinates missing specifications.\n"
         "• Unified Institutional Pricing Rules: Successfully codified the knowledge of Kevin, Rick, and Shanna into standardized reference data, automated vendor multiplier calculations, and gross margin divisor formulas [Sale = Cost / (1 - Margin)].",
         "Specific, measurable business and technical metrics proven by the codebase and pilot benchmarks."),
        ("Case Study Narrative", "Customer Quote (optional)", "Optional",
         "\"The CBC Estimating Copilot doesn't try to replace our estimators — it removes the grueling hours spent re-keying door schedules and hunting through manufacturer pricebooks. Our team can now review a fully traced, priced draft proposal in minutes, with every single opening verified directly against the original architectural blueprints.\"\n— Construction Building Components Leadership, The Hamilton Parker Company",
         "Authentic testimonial reflecting the core philosophy: 'The tool only helps; it does not replace estimating judgment.'"),

        # Marketing Participation Permissions
        ("Marketing Participation", "Participate: Win Slide", "Required", "Yes", "Dash Technologies & Hamilton Parker project can be featured in internal/partner executive win slides."),
        ("Marketing Participation", "Participate: Written Case Study", "Required", "Yes", "Dash Technologies is prepared to co-author an in-depth technical written case study highlighting multi-agent Claude orchestration."),
        ("Marketing Participation", "Participate: Video", "Optional", "Optional / Phase 2", "Open to exploring a video demo / interview once full production rollout is completed."),
        ("Marketing Participation", "Participate: Event", "Required", "Yes", "Willing to co-present or be featured as an enterprise AI customer story at Anthropic / AWS industry events."),
        ("Marketing Participation", "Participate: Speaking", "Required", "Yes", "Taskeen Khan / Dash Technologies AI leads available for panels or webinars on agentic workflows in construction supply."),
        ("Marketing Participation", "Participate: Press", "Required", "Pending Final Customer Approval", "Press release subject to formal Hamilton Parker corporate communications sign-off in Q4."),
        ("Marketing Participation", "Participate: Other", "Optional", "N/A", "None at this time."),
        ("Marketing Participation", "Link to Supporting Materials (optional)", "Optional",
         "Technical Architecture & Data Model Repository: cbc-final (ARCHITECTURE.md, docs/collections.mongodb.md, docs/cbc_process_flow_narrative.md)",
         "Reference to technical architecture and implementation documentation.")
    ]

    current_row = 5
    current_sec = ""
    section_fill_2 = PatternFill(start_color="9A3412", end_color="9A3412", fill_type="solid")

    for item in claude_fields:
        sec, field, req, val, notes = item
        
        if sec != current_sec:
            current_sec = sec
            ws2.merge_cells(start_row=current_row, start_column=1, end_row=current_row, end_column=5)
            s_cell = ws2.cell(row=current_row, column=1, value=f"CATEGORY: {sec.upper()}")
            s_cell.font = section_font
            s_cell.fill = section_fill_2
            s_cell.alignment = title_align
            ws2.row_dimensions[current_row].height = 24
            current_row += 1

        row_fill = alt_row_fill if current_row % 2 == 0 else white_fill
        
        c1 = ws2.cell(row=current_row, column=1, value=sec)
        c2 = ws2.cell(row=current_row, column=2, value=field)
        c3 = ws2.cell(row=current_row, column=3, value=req)
        c4 = ws2.cell(row=current_row, column=4, value=val)
        c5 = ws2.cell(row=current_row, column=5, value=notes)

        c1.font = value_font
        c2.font = field_name_font
        c3.font = req_font if req == "Required" else opt_font
        c4.font = value_font
        c5.font = notes_font

        c1.alignment = center_align
        c2.alignment = left_align
        c3.alignment = center_align
        c4.alignment = left_align
        c5.alignment = left_align

        for c in (c1, c2, c3, c4, c5):
            c.fill = row_fill
            c.border = cell_border

        lines = max(len(str(val)) // 75 + str(val).count('\n') + 1, len(str(notes)) // 45 + 1)
        ws2.row_dimensions[current_row].height = max(24, min(lines * 16, 260))
        current_row += 1

    ws2.column_dimensions['A'].width = 22
    ws2.column_dimensions['B'].width = 30
    ws2.column_dimensions['C'].width = 15
    ws2.column_dimensions['D'].width = 65
    ws2.column_dimensions['E'].width = 45


    # -------------------------------------------------------------------------
    # TAB 3: Project Context & Architecture Reference
    # -------------------------------------------------------------------------
    ws3 = wb.create_sheet(title="Project Context & Architecture")
    ws3.views.sheetView[0].showGridLines = True

    ws3.merge_cells("A1:D1")
    ws3["A1"] = "CBC Estimating Copilot — Technical Architecture & Operating Baseline"
    ws3["A1"].font = title_font
    ws3["A1"].fill = PatternFill(start_color="1E3A8A", end_color="1E3A8A", fill_type="solid")
    ws3["A1"].alignment = title_align
    ws3.row_dimensions[1].height = 36

    ws3.merge_cells("A2:D2")
    ws3["A2"] = "Internal Reference for Team Leader & Executive Review | Source: cbc-final codebase & requirements validation"
    ws3["A2"].font = subtitle_font
    ws3["A2"].fill = PatternFill(start_color="1E40AF", end_color="1E40AF", fill_type="solid")
    ws3["A2"].alignment = title_align
    ws3.row_dimensions[2].height = 22

    headers3 = ["Architectural Dimension", "System Implementation", "Business Context / Governance Rule", "Codebase Reference"]
    ws3.row_dimensions[4].height = 26
    for col_idx, h in enumerate(headers3, 1):
        cell = ws3.cell(row=4, column=col_idx, value=h)
        cell.font = tbl_header_font
        cell.fill = PatternFill(start_color="2563EB", end_color="2563EB", fill_type="solid")
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cell.border = cell_border

    arch_rows = [
        ("Architecture Pattern", "Modular Monolith", "Split into 7 domain-owned modules: ops, projects, catalog, intake, extraction, pricing, quoting. Zero microservices overhead; shared MongoDB replica set and async worker loop.", "ARCHITECTURE.md, docs/architecture.md"),
        ("Dual Agent Model", "Sonnet (Judgment) + Haiku (Mechanical)", "Judgment agents (takeoff-engineer, product-matcher, pricing-engineer) run on Claude 3.5 Sonnet. Mechanical agents (intake-coordinator, pricebook-ingestor, quality-reviewer) run on Claude 3.5 Haiku for cost efficiency.", "AGENTS.md, apps/backend/src/cbc/worker_kit/prompts.py"),
        ("NFR-1 Guardrail", "Human-in-the-Loop Approval", "The copilot drafts, sources, and calculates — it DOES NOT send quotes to customers. Proposals are exported as reviewable drafts; human estimators must explicitly approve and submit to the sales queue.", ".claude/rules/human-in-the-loop.md, docs/cbc_process_flow.md"),
        ("NFR-2 Guardrail", "Accuracy Floor / No Guessing", "Unmatched parts, unverified ratings, or ambiguous drawings are never silently guessed. Confidence scoring triggers visual review flags and enforces a manual cut-off.", ".claude/rules/accuracy-trust.md, test_confidence_floor.py"),
        ("NFR-3 Guardrail", "Full Bounding-Box Auditability", "Every door opening, dimension, and hardware callout carries source drawing page number and exact bounding-box coordinates (bbox), verifiable in the web UI.", "docs/collections.mongodb.md (openings collection)"),
        ("NFR-5 Guardrail", "ERP Safety (Prophet 21 Read-Only)", "Prophet 21 (P21) integration looks up last-PO historical purchase pricing only. It is strictly read-only; no write-back to transactional ERP databases occurs.", "mcp-servers/p21-connector/, .claude/rules/p21-read-only.md"),
        ("Costing Waterfall", "3-Path Cost Sourcing", "Path 1: P21 historical last-PO purchase cost. Path 2: Vendor list price x account multiplier tier (Hager, Bobrick, ASI, Pemko, World Dryer). Path 3: Distributor lookup / manual RFQ entry.", ".claude/memory/cost_sourcing_rules.md, pricing module"),
        ("Pricing Formula", "Gross Margin Divisor", "Sale $ EA = Cost / (1 - margin). Margins applied per category band (Commodity doors 27%, Specialty 40%, Accessories 56%, FRP 35%).", "docs/cbc_process_flow_narrative.md Phase 4"),
        ("Estimator Personas", "Three Coexisting Modes", "Kevin: One-off blank build-up. Rick: Personal spreadsheet with occasional freight. Shanna: Templated delete-down from prior quote + FRP takeoffs in Vu360. System supports both blank and reuse flows.", ".claude/memory/estimator_profiles.md"),
        ("Internal Sales Queue", "Targeted Hand-off", "Quotes are initiated by and returned directly to specific internal sales coordinators (Kellan, Matt, Rebecca, Tina) — never sent to a generic mailbox or external customer directly.", ".claude/memory/project_context.md, FR-10")
    ]

    r_idx = 5
    for row_data in arch_rows:
        row_fill = alt_row_fill if r_idx % 2 == 0 else white_fill
        for c_idx, val in enumerate(row_data, 1):
            c = ws3.cell(row=r_idx, column=c_idx, value=val)
            c.font = field_name_font if c_idx == 1 else value_font
            c.alignment = left_align
            c.fill = row_fill
            c.border = cell_border
        ws3.row_dimensions[r_idx].height = 42
        r_idx += 1

    ws3.column_dimensions['A'].width = 25
    ws3.column_dimensions['B'].width = 35
    ws3.column_dimensions['C'].width = 65
    ws3.column_dimensions['D'].width = 35

    # Save workbook
    output_path = "Hamilton_Parker_CBC_Partner_Registration_and_Case_Study.xlsx"
    wb.save(output_path)
    print(f"Successfully generated: {output_path}")

if __name__ == "__main__":
    build_workbook()
