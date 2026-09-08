"""Generate two sample SOW DOCX files for the demo dataset.

Produces:
    data/sow/SOW-2026-014-nbe-loyalty-v1.docx
    data/sow/SOW-2026-014-nbe-loyalty-v2.docx

Both files share the same cover metadata and 11 numbered scope sections. v2
differs only in the merchant target (250 -> 320) and defers the Upper Egypt
region to phase 2 — the change-request payload for Phase 7's diff demo.

Content is authored as short numbered sub-clauses (1.1, 1.2, ...) so Phase 2's
clause-indexed ingest produces stable C-xxx ids the rest of the pipeline can
cite.

Run:
    python3 scripts/generate_sows.py
"""
from __future__ import annotations

from pathlib import Path

from docx import Document
from docx.shared import Pt


# ---------------------------------------------------------------------------
# Content — shared between v1 and v2, with parameterised differences.
# ---------------------------------------------------------------------------

COVER = {
    "sow_id": "SOW-2026-014",
    "client": "Delta Commercial Bank S.A.E.",
    "vendor": "Dsquares",
    "project": "Delta Rewards — White-Label Loyalty Program",
    "signature_date": "12 January 2026",
    "delivery_date": "30 June 2026",
}


def scope_sections(*, merchant_target: int, regions: list[str]) -> list[dict]:
    """Return the 11 numbered scope sections.

    Parameters
    ----------
    merchant_target:
        Number of merchants Dsquares commits to acquire (250 in v1, 320 in v2).
    regions:
        POS-setup regions (all four in v1, three in v2 with Upper Egypt deferred).
    """
    regions_str = ", ".join(regions)
    n_regions = len(regions)

    return [
        {
            "title": "1. Points Engine",
            "intro": (
                "Dsquares shall design, build and deliver the core points engine "
                "that powers accrual, expiry and redemption for the Delta Rewards "
                "program."
            ),
            "clauses": [
                "1.1 Points accrual rules configurable per card tier "
                "(Classic, Gold, Platinum, Infinite) with per-merchant multipliers.",
                "1.2 Points expiry logic: rolling 24-month expiry from date of earn, "
                "with configurable warning notifications at 60 and 30 days.",
                "1.3 Points ledger with immutable append-only entries; every earn, "
                "burn, expiry and reversal is a discrete ledger row.",
                "1.4 Refund handling: transaction reversals must debit the exact "
                "points originally earned, even if the balance is otherwise negative.",
                "1.5 Reconciliation report generated daily and shared with Delta "
                "Commercial Bank finance.",
            ],
        },
        {
            "title": "2. Redemption Catalog",
            "intro": (
                "The redemption catalog exposes offers, e-vouchers and cash-back "
                "options to program members via the mobile SDK and admin portal."
            ),
            "clauses": [
                "2.1 Merchant offers with category, geo and card-tier eligibility rules.",
                "2.2 E-voucher inventory with unique-code allocation on redemption.",
                "2.3 Points-to-cash-back at POS with configurable conversion ratio.",
                "2.4 Catalog scheduling: offers may be time-boxed with start and end dates.",
            ],
        },
        {
            "title": "3. Mobile SDK",
            "intro": (
                "Dsquares shall deliver an embeddable loyalty module for the "
                "existing Delta Commercial Bank iOS and Android applications."
            ),
            "clauses": [
                "3.1 SDK exposes: balance view, catalog browse, offer redeem, "
                "transaction history for the current member.",
                "3.2 iOS SDK compatible with iOS 15 and above; Android SDK compatible "
                "with API level 26 and above.",
                "3.3 Authentication via the bank's existing OAuth2 identity provider; "
                "no separate loyalty login.",
                "3.4 Localisation: English and Arabic (right-to-left layouts).",
                "3.5 Offline mode: balance and last redemption cached for at least 24 hours.",
            ],
        },
        {
            "title": "4. Admin Portal",
            "intro": (
                "A web-based portal for the bank's loyalty operations team to run "
                "the program end-to-end without engineering support."
            ),
            "clauses": [
                "4.1 Campaign setup: create, schedule and pause point-earning campaigns.",
                "4.2 Merchant management: onboard, edit and suspend merchants; view "
                "per-merchant redemption volume.",
                "4.3 Reporting dashboards: daily earn/burn, active members, top "
                "merchants, redemption latency.",
                "4.4 Role-based access with at minimum three roles: Admin, Ops, Read-only.",
                "4.5 Full audit trail on every write action in the portal.",
            ],
        },
        {
            "title": "5. Integrations",
            "intro": (
                "The platform integrates with existing bank and third-party systems."
            ),
            "clauses": [
                "5.1 Core banking API integration for account lookup and card metadata.",
                "5.2 Card transaction feed ingestion — near-real-time (target < 60s) "
                "so accrual reflects on member's app within one minute of transaction.",
                "5.3 SMS gateway integration for OTP and redemption confirmation.",
                "5.4 Push notification gateway integration for offer alerts and expiry warnings.",
                "5.5 All integrations to be documented with API contracts, error codes and retry semantics.",
            ],
        },
        {
            "title": "6. Merchant Network (Commercial)",
            "intro": (
                "Dsquares shall build the redemption merchant network for the launch."
            ),
            "clauses": [
                f"6.1 Acquire {merchant_target} merchants distributed across five "
                "categories: Food & Beverage, Grocery, Fashion, Pharmacy, Fuel.",
                "6.2 Negotiate 60 exclusive or preferential offers with the acquired "
                "merchants for the first six months of operation.",
                "6.3 Sign 3 anchor partnerships with nationally-recognised brands, "
                "one each in F&B, Grocery and Fuel.",
                "6.4 Commercial terms with merchants must include a minimum program "
                "commitment of 12 months.",
            ],
        },
        {
            "title": "7. Operations",
            "intro": (
                "Operational readiness across the merchant network and internal "
                "support."
            ),
            "clauses": [
                f"7.1 POS configuration and rollout across {n_regions} regions "
                f"({regions_str}).",
                f"7.2 On-ground merchant training for all {merchant_target} "
                "acquired merchants; batch size 40 merchants per training wave.",
                f"7.3 Merchant onboarding (data setup, first-transaction validation, "
                "manager handover) at batch size 40 merchants per wave.",
                "7.4 Support playbook covering member queries, merchant issues and "
                "escalation matrix; live from pilot launch.",
                "7.5 Field ops readiness sign-off gate before full launch.",
            ],
        },
        {
            "title": "8. Design",
            "intro": (
                "Dsquares shall deliver a brand-aligned visual and interaction "
                "design covering all member-facing surfaces."
            ),
            "clauses": [
                "8.1 18 mobile screens covering onboarding, balance, catalog, "
                "redeem flow, history and settings.",
                "8.2 Wireframes for the admin portal covering all screens in section 4.",
                "8.3 Design system: colour, typography, iconography, motion, in a "
                "shared Figma library aligned to the bank's brand guidelines.",
                "8.4 Design QA sign-off after implementation, prior to UAT.",
            ],
        },
        {
            "title": "9. Milestones",
            "intro": (
                "The following milestones anchor the delivery schedule and are the "
                "acceptance gates for staged payments."
            ),
            "clauses": [
                "9.1 Discovery sign-off — end of week 4 from signature.",
                "9.2 Integration complete — end of week 14 from signature.",
                "9.3 UAT start — end of week 18 from signature.",
                "9.4 Pilot launch with 50 merchants — end of week 20 from signature.",
                "9.5 Full launch — on or before 30 June 2026.",
            ],
        },
        {
            "title": "10. SLAs & Acceptance Criteria",
            "intro": (
                "The platform must meet the following service levels and be signed "
                "off against these acceptance criteria before final payment is released."
            ),
            "clauses": [
                "10.1 Platform availability of 99.5% measured monthly, excluding "
                "scheduled maintenance windows.",
                "10.2 Redemption latency of less than 2 seconds end-to-end for 95% "
                "of transactions.",
                "10.3 UAT pass rate of at least 95% of test cases on first execution.",
                "10.4 Zero critical defects and no more than 5 open major defects "
                "at go-live.",
                "10.5 Points ledger reconciliation must balance to zero variance daily.",
            ],
        },
        {
            "title": "11. Out of Scope",
            "intro": (
                "The following are explicitly excluded from the scope of this SOW. "
                "Any request to include these items shall be handled via a formal "
                "change request."
            ),
            "clauses": [
                "11.1 Any modifications to the bank's core banking platform.",
                "11.2 Physical loyalty-card production, issuance or logistics.",
                "11.3 ATM integration for points redemption.",
                "11.4 Marketing campaigns, creative production and paid media spend.",
                "11.5 Data-warehouse or BI-stack integration beyond the reporting "
                "dashboards in section 4.3.",
            ],
        },
    ]


# ---------------------------------------------------------------------------
# DOCX writer
# ---------------------------------------------------------------------------

def _set_default_font(doc: Document) -> None:
    style = doc.styles["Normal"]
    style.font.name = "Calibri"
    style.font.size = Pt(11)


def _add_cover(doc: Document, version: int) -> None:
    title = doc.add_heading(f"Scope of Work — {COVER['project']}", level=0)
    title.alignment = 1  # centered

    p = doc.add_paragraph()
    p.add_run(f"SOW ID: {COVER['sow_id']}    Version: {version}\n").bold = True
    p.add_run(f"Client: {COVER['client']}\n")
    p.add_run(f"Vendor: {COVER['vendor']}\n")
    p.add_run(f"Signature Date: {COVER['signature_date']}\n")
    p.add_run(f"Go-Live Date: {COVER['delivery_date']}\n")

    doc.add_paragraph()


def _add_section(doc: Document, section: dict) -> None:
    doc.add_heading(section["title"], level=1)
    doc.add_paragraph(section["intro"])
    for clause in section["clauses"]:
        p = doc.add_paragraph(clause)
        p.paragraph_format.left_indent = Pt(18)


def _add_change_request_appendix(doc: Document) -> None:
    doc.add_heading("Appendix A — Change Request Notes (v2)", level=1)
    doc.add_paragraph(
        "The following changes were requested by Delta Commercial Bank on "
        "24 February 2026 and are incorporated into this version of the SOW:"
    )
    for note in [
        "A.1 Merchant acquisition target raised from 250 to 320 to widen "
        "F&B and grocery coverage in Cairo and Alexandria.",
        "A.2 POS rollout in the Upper Egypt region is deferred to a "
        "post-launch phase 2 engagement. All operations activities for "
        "Upper Egypt are removed from this SOW.",
        "A.3 The go-live date of 30 June 2026 is unchanged. Dsquares to "
        "confirm feasibility with updated schedule.",
    ]:
        p = doc.add_paragraph(note)
        p.paragraph_format.left_indent = Pt(18)


def build_sow(version: int, output_path: Path) -> None:
    doc = Document()
    _set_default_font(doc)
    _add_cover(doc, version=version)

    if version == 1:
        merchant_target = 250
        regions = ["Cairo", "Alexandria", "Delta", "Upper Egypt"]
    elif version == 2:
        merchant_target = 320
        regions = ["Cairo", "Alexandria", "Delta"]  # Upper Egypt deferred
    else:
        raise ValueError(f"Unknown SOW version {version}")

    for section in scope_sections(
        merchant_target=merchant_target, regions=regions
    ):
        _add_section(doc, section)

    if version == 2:
        _add_change_request_appendix(doc)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(output_path)
    print(f"wrote {output_path}")


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    out_dir = root / "data" / "sow"
    build_sow(1, out_dir / "SOW-2026-014-nbe-loyalty-v1.docx")
    build_sow(2, out_dir / "SOW-2026-014-nbe-loyalty-v2.docx")


if __name__ == "__main__":
    main()
