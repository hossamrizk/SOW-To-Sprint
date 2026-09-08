import json
import tempfile
from collections import Counter, defaultdict
from datetime import date, datetime
from pathlib import Path

import pandas as pd
import streamlit as st

from src.diff import compute_diff, field_deltas
from src.models import SOWExtraction, WorkItem
from src.pipeline import load_existing_run, run_pipeline
from src.settings_ui import render_settings_tab
from src.store import default_store
from src.sync import (
    apply_change_request,
    dry_run as sync_dry_run,
    sync as trello_sync,
)
from src.trello_client import TrelloError
from src.ui_theme import (
    BORDER,
    DANGER,
    LOW_CONF,
    PRIMARY,
    PRIMARY_HI,
    SUCCESS,
    SURFACE_1,
    SURFACE_2,
    TEXT,
    TEXT_2,
    WARNING,
    alert,
    badge,
    confidence_badge,
    function_badge,
    hint,
    inject_theme,
    source_clause,
    status_badge,
)


# ---------------------------------------------------------------------------
# Boot: page config + theme injection
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="Contract Task Engine",
    layout="wide",
    page_icon="🧬",
    initial_sidebar_state="expanded",
)
st.markdown(inject_theme(), unsafe_allow_html=True)

store = default_store()
_PROJECT_ROOT = Path(__file__).resolve().parent

# Feature flag — flip to True to re-enable the v1↔v2 change-request diff.
DIFF_ENABLED = False


# ---------------------------------------------------------------------------
# Bootstrap: import v1/v2 JSON runs if the store is empty
# ---------------------------------------------------------------------------

def _bootstrap_demo_runs() -> None:
    existing = {r["run_id"] for r in store.list_runs()}
    for version in (1, 2):
        ext_path = _PROJECT_ROOT / f"data/runs/SOW-2026-014-v{version}-extraction.json"
        items_path = _PROJECT_ROOT / f"data/runs/SOW-2026-014-v{version}-workitems.json"
        if not (ext_path.exists() and items_path.exists()):
            continue
        run_id = f"SOW-2026-014-v{version}-demo"
        if run_id in existing:
            continue
        extraction = SOWExtraction.model_validate_json(ext_path.read_text())
        items = [WorkItem.model_validate(x) for x in json.loads(items_path.read_text())]
        store.start_run(run_id=run_id, sow_id=extraction.sow_id,
                        version=extraction.version, source_file=str(ext_path))
        store.save_extraction(run_id, extraction)
        store.save_work_items(run_id, items)
        store.complete_run(run_id)


_bootstrap_demo_runs()


# ---------------------------------------------------------------------------
# Sidebar — scope pack + clause navigation + compare selector
# ---------------------------------------------------------------------------

def _render_sidebar(runs: list[dict], work_items: list[WorkItem] | None,
                    extraction: SOWExtraction | None) -> tuple[str | None, str | None]:
    """Draws the left rail. Returns (selected_run_id, base_run_id_for_compare)."""
    with st.sidebar:
        st.markdown(
            f'<div style="display:flex; align-items:center; gap:8px; padding: 4px 0 12px;">'
            f'  <span style="width:22px;height:22px;border-radius:4px;'
            f'background:linear-gradient(135deg,{PRIMARY_HI},{PRIMARY}); display:inline-block;"></span>'
            f'  <span style="font-family: JetBrains Mono; font-size: 12px; '
            f'letter-spacing: 0.1em; text-transform: uppercase; color: {TEXT};">Contract Task Engine</span>'
            f'</div>',
            unsafe_allow_html=True,
        )

        # Scope pack summary — current SoW
        st.markdown('<div class="sidebar-title">SCOPE PACK</div>', unsafe_allow_html=True)
        if extraction:
            st.markdown(
                f'<div style="background:{SURFACE_1}; border: 1px solid {BORDER}; '
                f'border-radius: 6px; padding: 10px 12px;">'
                f'  <div style="font-family: Geist; font-size: 13px; font-weight: 600; color: {TEXT};">'
                f'    {extraction.project_name[:32]}'
                f'  </div>'
                f'  <div style="font-family: JetBrains Mono; font-size: 11px; color: {TEXT_2}; margin-top: 4px;">'
                f'    {extraction.sow_id} · v{extraction.version}'
                f'  </div>'
                f'  <div style="margin-top: 8px; display: flex; justify-content: space-between; '
                f'font-family: JetBrains Mono; font-size: 10px; color: {TEXT_2};">'
                f'    <span>DELIVERY</span>'
                f'    <span style="color:{PRIMARY_HI};">{extraction.delivery_date}</span>'
                f'  </div>'
                f'</div>',
                unsafe_allow_html=True,
            )

        st.markdown("<br>", unsafe_allow_html=True)

        # Run selector
        st.markdown('<div class="sidebar-title">ACTIVE RUN</div>', unsafe_allow_html=True)

        def _fmt_run_label(r: dict, is_latest: bool) -> str:
            # Timestamp: "HH:MM" if today, else "MMM DD HH:MM".
            stamp = ""
            if r.get("started_at"):
                try:
                    ts = datetime.fromisoformat(r["started_at"])
                    stamp = (
                        ts.strftime("%H:%M") if ts.date() == datetime.now().date()
                        else ts.strftime("%b %d %H:%M")
                    )
                except (ValueError, TypeError):
                    pass
            label = f"{r['sow_id']} v{r['version']} · {r['run_id'][-8:]}"
            if stamp:
                label += f" · {stamp}"
            if is_latest:
                label += "  (latest)"
            return label

        options = ["(upload new SOW)"] + [
            _fmt_run_label(r, is_latest=(i == 0)) for i, r in enumerate(runs)
        ]
        choice = st.selectbox("Select run", options,
                              index=1 if runs else 0,
                              label_visibility="collapsed",
                              key="sidebar-run-select")

        run_id_val: str | None = None
        if choice == "(upload new SOW)":
            uploaded = st.file_uploader("SOW (.docx)", type=["docx"],
                                        label_visibility="collapsed")
            if uploaded and st.button("Run pipeline", type="primary", width="stretch"):
                # Persist the uploaded DOCX inside data/sow/ so we can
                # re-open it later — the OS may wipe /tmp.
                sow_dir = _PROJECT_ROOT / "data" / "sow"
                sow_dir.mkdir(parents=True, exist_ok=True)
                persisted_path = sow_dir / uploaded.name
                persisted_path.write_bytes(uploaded.getvalue())
                with st.spinner("Ingesting → extracting → decomposing → scheduling …"):
                    result = run_pipeline(str(persisted_path), store=store)
                st.session_state["run_id"] = result.run_id
                st.rerun()
        else:
            idx = options.index(choice) - 1
            run_id_val = runs[idx]["run_id"]

        # Compare-against — hidden behind DIFF_ENABLED flag.
        base_run_id_val: str | None = None
        if DIFF_ENABLED:
            st.markdown('<div class="sidebar-title">COMPARE AGAINST</div>',
                        unsafe_allow_html=True)
            other_runs = [r for r in runs if r["run_id"] != run_id_val]
            compare_options = ["(none)"] + [
                f"{r['sow_id']} v{r['version']} · {r['run_id'][-8:]}" for r in other_runs
            ]
            compare_choice = st.selectbox("Base run", compare_options,
                                           label_visibility="collapsed",
                                           key="sidebar-compare-select")
            if compare_choice != "(none)":
                base_run_id_val = other_runs[compare_options.index(compare_choice) - 1]["run_id"]

        # Deliverables & clauses navigation — grouped by module
        if work_items:
            st.markdown('<div class="sidebar-title" style="margin-top: 16px;">DELIVERABLES & CLAUSES</div>',
                        unsafe_allow_html=True)
            by_module: dict[str, list[WorkItem]] = defaultdict(list)
            for it in work_items:
                key = (it.source_clause_id or "Unclassified")[:6]
                # Use the item's function as a rough deliverable grouping
                mod_key = _module_for(it, extraction)
                by_module[mod_key].append(it)

            for mod, items in sorted(by_module.items(), key=lambda x: -len(x[1])):
                pending = sum(1 for i in items if i.status == "generated")
                approved = sum(1 for i in items if i.status in ("approved", "edited"))
                st.markdown(
                    f'<div style="display: flex; align-items: center; justify-content: space-between; '
                    f'padding: 6px 10px; background:{SURFACE_1}; border: 1px solid {BORDER}; '
                    f'border-radius: 4px; margin-bottom: 4px;">'
                    f'  <div style="font-size: 12px; color: {TEXT};">'
                    f'    <span style="display:inline-block;width:6px;height:6px;border-radius:50%;'
                    f'background:{PRIMARY_HI if approved else WARNING if pending else TEXT_2};'
                    f'margin-right:6px;"></span>{mod[:24]}'
                    f'  </div>'
                    f'  <div style="font-family: JetBrains Mono; font-size: 10px; color: {TEXT_2};">'
                    f'    {approved}/{len(items)}'
                    f'  </div>'
                    f'</div>',
                    unsafe_allow_html=True,
                )

        # Footer — status
        st.markdown("<br>", unsafe_allow_html=True)
        st.markdown(
            f'<div style="background:{SURFACE_1}; border: 1px solid {BORDER}; border-radius: 4px; '
            f'padding: 8px 10px;">'
            f'  <div style="font-family: JetBrains Mono; font-size: 10px; color: {TEXT_2}; '
            f'text-transform: uppercase; letter-spacing: 0.06em;">TRELLO ENDPOINT</div>'
            f'  <div style="font-family: JetBrains Mono; font-size: 11px; color: {PRIMARY_HI}; '
            f'margin-top: 4px;">● connected</div>'
            f'</div>',
            unsafe_allow_html=True,
        )

    return run_id_val, base_run_id_val


def _module_for(item: WorkItem, extraction: SOWExtraction | None) -> str:
    """Best-effort module label for the sidebar grouping."""
    # Scope items in the extraction sometimes carry `module`. Match by clause id.
    if extraction is not None:
        for s in extraction.scope_items:
            if s.source_clause_id == item.source_clause_id and s.module:
                return s.module
    return {"technical": "Technical Deliverables",
            "commercial": "Commercial Deliverables",
            "operations": "Operations Deliverables",
            "design": "Design Deliverables"}.get(item.function, "Other")


# ---------------------------------------------------------------------------
# Header + breadcrumb + top alert banner
# ---------------------------------------------------------------------------

def _render_header(extraction: SOWExtraction, run_id: str,
                   over_committed_count: int, unmapped_count: int) -> None:
    # Breadcrumb + title strip
    st.markdown(
        f'<div style="display: flex; align-items: baseline; gap: 12px; margin-bottom: 6px;">'
        f'  <span style="font-family: JetBrains Mono; font-size: 10px; text-transform: uppercase; '
        f'letter-spacing: 0.08em; color: {TEXT_2};">'
        f'    ENGINE / CONTRACT TASK / <span style="color:{PRIMARY_HI};">{extraction.sow_id}</span>'
        f'  </span>'
        f'</div>'
        f'<div style="display: flex; justify-content: space-between; align-items: flex-end;">'
        f'  <div>'
        f'    <div style="font-family: Geist; font-size: 22px; font-weight: 600; '
        f'color: {TEXT}; letter-spacing: -0.015em;">{extraction.project_name}</div>'
        f'    <div style="font-family: JetBrains Mono; font-size: 11px; color: {TEXT_2}; margin-top: 4px;">'
        f'      {extraction.client_name} · {extraction.sow_id} v{extraction.version} · signed {extraction.signature_date or "n/a"}'
        f'    </div>'
        f'  </div>'
        f'  <div style="display: flex; gap: 8px;">'
        f'    <span class="ctm-badge ctm-badge-approved">LIVE</span>'
        f'    <span class="ctm-badge ctm-badge-neutral">RUN {run_id[-8:]}</span>'
        f'  </div>'
        f'</div>',
        unsafe_allow_html=True,
    )

    # Alert row
    if over_committed_count or unmapped_count:
        text_parts = []
        if unmapped_count:
            text_parts.append(f"{unmapped_count} unmapped clauses need review")
        if over_committed_count:
            text_parts.append(
                f"{over_committed_count} tasks would start before contract signature"
            )
        alert_html = alert(
            " · ".join(text_parts) + ".",
            kind="danger" if over_committed_count else "warning",
            icon="⚠",
        )
        st.markdown(alert_html, unsafe_allow_html=True)
    else:
        st.markdown(
            alert("All clauses classified · Zero over-commitment · Pipeline healthy",
                  kind="success", icon="●"),
            unsafe_allow_html=True,
        )


# ---------------------------------------------------------------------------
# Tab 1 — Extraction summary
# ---------------------------------------------------------------------------

def render_tab_extraction(extraction: SOWExtraction, work_items: list[WorkItem]) -> None:
    # Metric row
    total_scope = len(extraction.scope_items)
    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("SCOPE ITEMS", total_scope)
    m2.metric("MODULES", len(extraction.modules))
    m3.metric("MILESTONES", len(extraction.milestones))
    m4.metric("OUT OF SCOPE", len(extraction.out_of_scope))
    m5.metric("SLAs", len(extraction.slas))

    st.markdown("<br>", unsafe_allow_html=True)

    # Two-column layout: milestones on the left, out-of-scope + unmapped on right
    left, right = st.columns([3, 2])

    with left:
        st.markdown('<div class="ctm-label">CONTRACT DELIVERY MILESTONES</div>',
                    unsafe_allow_html=True)
        if extraction.milestones:
            ms_df = pd.DataFrame([
                {
                    "ID": m.id,
                    "MILESTONE": m.name,
                    "DUE DATE": m.due_date,
                    "SCOPE LINKS": len(m.linked_scope_item_ids),
                }
                for m in extraction.milestones
            ])
            st.dataframe(ms_df, hide_index=True, width="stretch", height=250)
        else:
            st.markdown('<div class="ctm-hint">No milestones extracted.</div>',
                        unsafe_allow_html=True)

        # Modules chip row
        st.markdown("<br>", unsafe_allow_html=True)
        st.markdown('<div class="ctm-label">MODULES IN SCOPE</div>', unsafe_allow_html=True)
        chips = " ".join(badge(m, "neutral") for m in extraction.modules)
        st.markdown(f'<div style="margin-top: 6px;">{chips}</div>',
                    unsafe_allow_html=True)

        # Scope-per-function breakdown
        st.markdown("<br>", unsafe_allow_html=True)
        st.markdown('<div class="ctm-label">SCOPE ITEMS PER FUNCTION</div>',
                    unsafe_allow_html=True)
        fn_counts = pd.Series([s.function for s in extraction.scope_items]).value_counts()
        st.bar_chart(fn_counts, height=180)

    with right:
        # Out of scope
        st.markdown('<div class="ctm-label">EXPLICIT CONTRACTUAL EXCLUSIONS</div>',
                    unsafe_allow_html=True)
        oos_html_parts: list[str] = []
        for i, oos in enumerate(extraction.out_of_scope, 1):
            oos_html_parts.append(
                f'<div style="background:{SURFACE_1}; border: 1px solid {BORDER}; '
                f'border-left: 3px solid #ef4444; border-radius: 4px; '
                f'padding: 10px 12px; margin-bottom: 6px;">'
                f'  <div style="font-family: JetBrains Mono; font-size: 10px; '
                f'letter-spacing: 0.08em; color: {TEXT_2}; text-transform: uppercase;">'
                f'    EXCLUSION {i:02d}'
                f'  </div>'
                f'  <div style="font-size: 13px; color: {TEXT}; margin-top: 4px;">{oos}</div>'
                f'</div>'
            )
        st.markdown("".join(oos_html_parts), unsafe_allow_html=True)

        # Unmapped clauses
        if extraction.unmapped_clauses:
            st.markdown('<div class="ctm-label">UNMAPPED CLAUSES</div>',
                        unsafe_allow_html=True)
            for c in extraction.unmapped_clauses:
                st.markdown(
                    f'<div style="background:{SURFACE_1}; border: 1px solid {BORDER}; '
                    f'border-left: 3px solid {LOW_CONF}; padding: 8px 10px; '
                    f'border-radius: 3px; margin-bottom: 4px; '
                    f'font-family: JetBrains Mono; font-size: 12px; color: {TEXT};">'
                    f'{c}</div>',
                    unsafe_allow_html=True,
                )

    # ------------------------------------------------------------------
    # Full-width scope items panel — the atomic units the LLM extracted,
    # before Stage 3 decomposes them into work items. This is the level of
    # detail the PM should audit BEFORE the decomposer runs.
    # ------------------------------------------------------------------
    st.markdown("<br>", unsafe_allow_html=True)
    st.markdown(
        f'<div class="ctm-label">EXTRACTED SCOPE ITEMS ({len(extraction.scope_items)})</div>',
        unsafe_allow_html=True,
    )
    st.caption(
        "One row per atomic deliverable the extractor pulled from the SoW. "
        "These are the inputs to Stage 3 (decompose) — each becomes 1 to N work items."
    )

    if extraction.scope_items:
        scope_df = pd.DataFrame([
            {
                "SCOPE ID": s.id,
                "FN": s.function[:4].upper(),
                "MODULE": s.module or "—",
                "TITLE": s.title,
                "QTY": str(s.quantity) if s.quantity else "—",
                "UNIT": s.unit if s.unit else "—",
                "CONF": s.confidence.upper(),
                "SOURCE": s.source_clause_id,
            }
            for s in extraction.scope_items
        ])
        st.dataframe(scope_df, hide_index=True, width="stretch", height=380)

        # Detail panel for the selected scope item
        selected_scope_id = st.selectbox(
            "Inspect scope item",
            [s.id for s in extraction.scope_items],
            key="extraction-scope-select",
            label_visibility="collapsed",
        )
        sel = next(s for s in extraction.scope_items if s.id == selected_scope_id)

        col_l, col_r = st.columns([3, 2])
        with col_l:
            st.markdown(
                f'<div class="ctm-card">'
                f'  <div class="ctm-card-title">{sel.title}</div>'
                f'  <div class="ctm-card-subtitle">'
                f'    {sel.id} · {sel.function} · module: {sel.module or "—"}'
                f'  </div>'
                f'  <div style="margin-top: 8px; font-size: 13px; color: {TEXT};">'
                f'    {sel.description}'
                f'  </div>'
                f'  <div style="margin-top: 8px;">'
                f'    {function_badge(sel.function)}'
                f'    {confidence_badge(sel.confidence)}'
                + (
                    f'    <span class="ctm-badge ctm-badge-neutral">'
                    f'{sel.quantity} {sel.unit}</span>'
                    if sel.quantity else ''
                )
                + '  </div>'
                f'</div>',
                unsafe_allow_html=True,
            )
        with col_r:
            st.markdown(
                source_clause(
                    sel.source_clause_id, sel.source_excerpt,
                    extra_header=f"{extraction.sow_id} v{extraction.version}",
                ),
                unsafe_allow_html=True,
            )
    else:
        st.markdown('<div class="ctm-hint">No scope items extracted.</div>',
                    unsafe_allow_html=True)

    # ------------------------------------------------------------------
    # Full-width panels below scope items: SLAs, Acceptance Criteria,
    # Commercial Targets. These were previously only surfaced as counts
    # in the top metric strip.
    # ------------------------------------------------------------------
    st.markdown("<br>", unsafe_allow_html=True)
    col_sla, col_ac, col_ct = st.columns(3)

    with col_sla:
        st.markdown('<div class="ctm-label">SERVICE LEVEL AGREEMENTS</div>',
                    unsafe_allow_html=True)
        if extraction.slas:
            for i, sla in enumerate(extraction.slas, 1):
                st.markdown(
                    f'<div style="background:{SURFACE_1}; border: 1px solid {BORDER}; '
                    f'border-left: 3px solid {PRIMARY_HI}; border-radius: 4px; '
                    f'padding: 10px 12px; margin-bottom: 6px;">'
                    f'  <div style="font-family: JetBrains Mono; font-size: 10px; '
                    f'letter-spacing: 0.08em; color: {TEXT_2}; text-transform: uppercase;">'
                    f'    SLA {i:02d}'
                    f'  </div>'
                    f'  <div style="font-size: 13px; color: {TEXT}; margin-top: 4px;">{sla}</div>'
                    f'</div>',
                    unsafe_allow_html=True,
                )
        else:
            st.markdown('<div class="ctm-hint">No SLAs stated in this SoW.</div>',
                        unsafe_allow_html=True)

    with col_ac:
        st.markdown('<div class="ctm-label">ACCEPTANCE CRITERIA</div>',
                    unsafe_allow_html=True)
        if extraction.acceptance_criteria:
            for i, ac in enumerate(extraction.acceptance_criteria, 1):
                st.markdown(
                    f'<div style="background:{SURFACE_1}; border: 1px solid {BORDER}; '
                    f'border-left: 3px solid {WARNING}; border-radius: 4px; '
                    f'padding: 10px 12px; margin-bottom: 6px;">'
                    f'  <div style="font-family: JetBrains Mono; font-size: 10px; '
                    f'letter-spacing: 0.08em; color: {TEXT_2}; text-transform: uppercase;">'
                    f'    CRITERION {i:02d}'
                    f'  </div>'
                    f'  <div style="font-size: 13px; color: {TEXT}; margin-top: 4px;">{ac}</div>'
                    f'</div>',
                    unsafe_allow_html=True,
                )
        else:
            st.markdown('<div class="ctm-hint">No acceptance criteria stated.</div>',
                        unsafe_allow_html=True)

    with col_ct:
        st.markdown('<div class="ctm-label">COMMERCIAL TARGETS</div>',
                    unsafe_allow_html=True)
        if extraction.commercial_targets:
            for ct in extraction.commercial_targets:
                qty_line = (
                    f'<span style="font-family: JetBrains Mono; font-size: 16px; '
                    f'font-weight: 600; color: {PRIMARY_HI};">{ct.quantity} '
                    f'<span style="font-size: 11px; color: {TEXT_2}; font-weight: 400;">'
                    f'{ct.unit or ""}</span></span>'
                    if ct.quantity else ''
                )
                st.markdown(
                    f'<div style="background:{SURFACE_1}; border: 1px solid {BORDER}; '
                    f'border-left: 3px solid #58a6ff; border-radius: 4px; '
                    f'padding: 10px 12px; margin-bottom: 6px;">'
                    f'  <div style="display: flex; justify-content: space-between; '
                    f'align-items: baseline;">'
                    f'    <div style="font-size: 13px; color: {TEXT}; font-weight: 500;">{ct.title}</div>'
                    f'    {qty_line}'
                    f'  </div>'
                    f'  <div style="font-family: JetBrains Mono; font-size: 10px; '
                    f'color: {TEXT_2}; margin-top: 4px;">'
                    f'    source: {ct.source_clause_id}'
                    f'  </div>'
                    f'</div>',
                    unsafe_allow_html=True,
                )
        else:
            st.markdown('<div class="ctm-hint">No quantitative commercial targets.</div>',
                        unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Tab 2 — Review items
# ---------------------------------------------------------------------------

def _confidence_order(c: str) -> int:
    return {"low": 0, "medium": 1, "high": 2}.get(c, 3)


def render_tab_review(run_id: str, work_items: list[WorkItem],
                      extraction: SOWExtraction) -> None:
    # Filter row
    st.markdown('<div class="ctm-label">FILTERS</div>', unsafe_allow_html=True)
    f1, f2, f3, f4 = st.columns(4)
    functions_sel = f1.multiselect(
        "Function", ["technical", "commercial", "operations", "design"],
        default=["technical", "commercial", "operations", "design"],
        label_visibility="collapsed",
        placeholder="Function",
    )
    phases_sel = f2.multiselect(
        "Phase", ["Discovery", "Build", "UAT", "Launch", "Post-launch"],
        default=["Discovery", "Build", "UAT", "Launch", "Post-launch"],
        label_visibility="collapsed",
        placeholder="Phase",
    )
    confidence_sel = f3.multiselect(
        "Confidence", ["high", "medium", "low"],
        default=["high", "medium", "low"],
        label_visibility="collapsed",
        placeholder="Confidence",
    )
    status_sel = f4.multiselect(
        "Status", ["generated", "approved", "rejected", "edited"],
        default=["generated", "approved", "rejected", "edited"],
        label_visibility="collapsed",
        placeholder="Status",
    )

    filtered = [
        it for it in work_items
        if it.function in functions_sel
        and it.phase in phases_sel
        and it.confidence in confidence_sel
        and it.status in status_sel
    ]
    filtered.sort(key=lambda it: (_confidence_order(it.confidence), it.id))

    # Bulk actions strip
    b1, b2, b3, b4, b5 = st.columns([1, 1, 1, 1, 4])
    for i, fn in enumerate(["technical", "commercial", "operations", "design"]):
        col = [b1, b2, b3, b4][i]
        if col.button(f"✓ ALL {fn.upper()}", key=f"bulk-{fn}", width="stretch"):
            n = store.bulk_set_status_by_function(run_id, fn, "approved")
            st.toast(f"Approved {n} {fn} items")
            st.rerun()

    # Low-confidence alert — surfaces the "safe fallback" story visually.
    # These are tasks the LLM couldn't classify into a known archetype, so
    # code fell back to a conservative default (1 day, Tech Lead role).
    low_conf_ids = [it.id for it in work_items if it.confidence == "low"]
    if low_conf_ids:
        st.markdown(
            alert(
                f"{len(low_conf_ids)} tasks flagged LOW confidence — the LLM "
                f"couldn't classify them into a known archetype, so code applied "
                f"a conservative default estimate. Review before push.",
                kind="warning", icon="⚠",
            ),
            unsafe_allow_html=True,
        )

    # Counts strip
    counts = Counter(it.status for it in work_items)
    strip_parts = [
        f'{badge(str(counts.get("generated", 0)), "generated")} PENDING',
        f'{badge(str(counts.get("approved", 0)), "approved")} APPROVED',
        f'{badge(str(counts.get("edited", 0)), "edited")} EDITED',
        f'{badge(str(counts.get("rejected", 0)), "rejected")} REJECTED',
    ]
    st.markdown(
        f'<div style="margin-top: 12px; margin-bottom: 8px; font-size: 11px; color: {TEXT_2};">'
        f'{" &nbsp;·&nbsp; ".join(strip_parts)}</div>',
        unsafe_allow_html=True,
    )

    if not filtered:
        st.markdown(alert("No items match the current filters.", "info"),
                    unsafe_allow_html=True)
        return

    # Two-pane: task list (left) + detail (right)
    left, right = st.columns([3, 4], gap="medium")

    with left:
        st.markdown(f'<div class="ctm-label">TASK MATRIX ({len(filtered)} shown)</div>',
                    unsafe_allow_html=True)
        # Compact table — low-confidence rows get a leading ⚠ in the CONF
        # column so they're visually scannable in the matrix.
        df = pd.DataFrame([
            {
                "ID": it.id,
                "FN": it.function[:4].upper(),
                "TYPE": it.type,
                "PHASE": it.phase,
                "CONF": ("⚠ LOW" if it.confidence == "low" else it.confidence.upper()),
                "STATUS": it.status.upper(),
                "EST": f"{it.estimate_days:g}d",
                "TITLE": it.title[:60],
            }
            for it in filtered
        ])
        st.dataframe(df, hide_index=True, width="stretch", height=520)

        selected_id = st.selectbox(
            "Inspect item",
            [it.id for it in filtered],
            label_visibility="collapsed",
        )

    with right:
        selected = next(it for it in work_items if it.id == selected_id)

        # Card header
        st.markdown(
            f'<div class="ctm-card" style="padding: 14px 16px;">'
            f'  <div style="display: flex; justify-content: space-between; align-items: flex-start; gap: 12px;">'
            f'    <div>'
            f'      <div class="ctm-card-title">{selected.title}</div>'
            f'      <div class="ctm-card-subtitle">'
            f'        {selected.id} · {selected.type} · {selected.phase} phase'
            f'      </div>'
            f'    </div>'
            f'    <div style="text-align: right;">'
            f'      {function_badge(selected.function)}'
            f'      {confidence_badge(selected.confidence)}'
            f'      {status_badge(selected.status)}'
            f'    </div>'
            f'  </div>'
            f'</div>',
            unsafe_allow_html=True,
        )

        # Source SoW panel — the traceability moment
        st.markdown(
            source_clause(
                selected.source_clause_id, selected.source_excerpt,
                extra_header=f"{extraction.sow_id} v{extraction.version}",
            ),
            unsafe_allow_html=True,
        )
        st.markdown("<br>", unsafe_allow_html=True)

        # Editable fields
        st.markdown('<div class="ctm-label">OVERRIDE PARAMETERS</div>',
                    unsafe_allow_html=True)
        new_title = st.text_input("Title", value=selected.title,
                                    key=f"t-{selected.id}",
                                    label_visibility="collapsed")
        new_desc = st.text_area("Description", value=selected.description,
                                key=f"d-{selected.id}", height=100,
                                label_visibility="collapsed")
        c1, c2, c3 = st.columns(3)
        new_est = c1.number_input(
            "Est. days", value=float(selected.estimate_days),
            min_value=0.1, step=0.5, key=f"e-{selected.id}",
        )
        c2.markdown(
            f'<div class="ctm-label" style="margin-top: 4px;">SQUAD</div>'
            f'<div style="font-size:12px;">{selected.squad or "—"}</div>',
            unsafe_allow_html=True,
        )
        c3.markdown(
            f'<div class="ctm-label" style="margin-top: 4px;">ASSIGNEE</div>'
            f'<div style="font-size:12px;">{selected.assignee or "—"}</div>',
            unsafe_allow_html=True,
        )

        # Gherkin / criteria
        if selected.gherkin:
            st.markdown('<div class="ctm-label" style="margin-top: 10px;">GHERKIN</div>',
                        unsafe_allow_html=True)
            st.code(selected.gherkin, language="gherkin")
        if selected.acceptance_criteria:
            st.markdown('<div class="ctm-label" style="margin-top: 10px;">ACCEPTANCE CRITERIA</div>',
                        unsafe_allow_html=True)
            for c in selected.acceptance_criteria:
                st.markdown(f'<div style="font-size: 12px; color:{TEXT}; '
                            f'padding-left: 10px; border-left: 2px solid {BORDER}; '
                            f'margin-bottom: 4px;">{c}</div>',
                            unsafe_allow_html=True)

        # Schedule row
        st.markdown(
            f'<div style="display: flex; gap: 24px; margin-top: 14px; '
            f'font-family: JetBrains Mono; font-size: 11px; color: {TEXT_2};">'
            f'  <span>START <span style="color:{TEXT};">{selected.start_date or "—"}</span></span>'
            f'  <span>DUE <span style="color:{PRIMARY_HI};">{selected.due_date or "—"}</span></span>'
            f'</div>',
            unsafe_allow_html=True,
        )

        # Action bar
        st.markdown("<br>", unsafe_allow_html=True)
        a1, a2, a3, a4 = st.columns(4)
        if a1.button("✓ APPROVE", key=f"a-{selected.id}",
                     type="primary", width="stretch"):
            store.set_item_status(run_id, selected.id, "approved")
            st.rerun()
        if a2.button("✎ SAVE EDITS", key=f"s-{selected.id}",
                     width="stretch"):
            selected.title = new_title
            selected.description = new_desc
            selected.estimate_days = float(new_est)
            selected.status = "edited"
            store.update_item(run_id, selected)
            st.rerun()
        if a3.button("✕ REJECT", key=f"r-{selected.id}",
                     width="stretch"):
            store.set_item_status(run_id, selected.id, "rejected")
            st.rerun()
        if a4.button("↺ RESET", key=f"u-{selected.id}",
                     width="stretch"):
            store.set_item_status(run_id, selected.id, "generated")
            st.rerun()


# ---------------------------------------------------------------------------
# Tab 3 — Timeline & critical path
# ---------------------------------------------------------------------------

def render_tab_timeline(work_items: list[WorkItem], report) -> None:
    # Top metrics
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("SIGNATURE", str(report.signature_date) if report.signature_date else "—")
    m2.metric("DELIVERY", str(report.delivery_date))
    m3.metric("CRITICAL PATH", f"{report.critical_path_days:.0f}d")
    m4.metric("OVER-COMMITTED", len(report.over_committed_ids))

    if report.over_committed_ids:
        st.markdown(
            alert(
                f"{len(report.over_committed_ids)} tasks would start before "
                f"the contract signature date. SOW may be undeliverable "
                "without a scope or timeline change.",
                kind="danger", icon="⚠",
            ),
            unsafe_allow_html=True,
        )

    st.markdown("<br>", unsafe_allow_html=True)

    # Critical path chain
    critical = [it for it in work_items if it.id in report.critical_path_ids]
    if critical:
        st.markdown('<div class="ctm-label">CRITICAL PATH CHAIN</div>',
                    unsafe_allow_html=True)
        chain_parts: list[str] = ['<div class="ctm-chain">']
        for i, it in enumerate(critical):
            phase_cls = (it.phase or "").lower()
            chain_parts.append(
                f'<div class="ctm-chain-node {phase_cls}">'
                f'  <div>'
                f'    <div style="font-family: JetBrains Mono; font-size: 10px; '
                f'color: {TEXT_2}; text-transform: uppercase; letter-spacing: 0.06em;">'
                f'      STEP {i+1:02d} · {it.phase.upper()} · {it.type.upper()}'
                f'    </div>'
                f'    <div style="font-size: 14px; font-weight: 500; color: {TEXT}; margin-top: 2px;">'
                f'      {it.title[:80]}'
                f'    </div>'
                f'  </div>'
                f'  <div style="text-align: right; '
                f'font-family: JetBrains Mono; font-size: 11px; color: {TEXT_2};">'
                f'    <div style="color: {PRIMARY_HI};">{it.estimate_days:g} days</div>'
                f'    <div>{it.start_date} → {it.due_date}</div>'
                f'  </div>'
                f'</div>'
            )
            if i < len(critical) - 1:
                chain_parts.append('<div class="ctm-chain-arrow">▼</div>')
        chain_parts.append('</div>')
        st.markdown("".join(chain_parts), unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)

    left, right = st.columns([2, 3])
    with left:
        st.markdown('<div class="ctm-label">TASKS PER PHASE</div>',
                    unsafe_allow_html=True)
        phase_counts = pd.Series([it.phase for it in work_items]).value_counts()
        st.bar_chart(phase_counts, height=260)

        st.markdown('<div class="ctm-label">TASKS PER FUNCTION</div>',
                    unsafe_allow_html=True)
        fn_counts = pd.Series([it.function for it in work_items]).value_counts()
        st.bar_chart(fn_counts, height=180)

    with right:
        st.markdown('<div class="ctm-label">FULL SCHEDULE — TOP 40 BY START DATE</div>',
                    unsafe_allow_html=True)
        scheduled = sorted(
            (it for it in work_items if it.start_date is not None),
            key=lambda it: (it.start_date, it.id),
        )
        sched_df = pd.DataFrame([
            {
                "ID": it.id,
                "PHASE": it.phase,
                "FN": it.function[:4].upper(),
                "START": it.start_date,
                "DUE": it.due_date,
                "EST": f"{it.estimate_days:g}d",
                "TITLE": (it.title or "")[:60],
                "ASSIGNEE": it.assignee or "—",
            }
            for it in scheduled[:40]
        ])
        st.dataframe(sched_df, hide_index=True, width="stretch", height=560)


# ---------------------------------------------------------------------------
# Tab 4 — Push to Trello
# ---------------------------------------------------------------------------

def render_tab_push(run_id: str, extraction: SOWExtraction,
                     work_items: list[WorkItem]) -> None:
    approved = [it for it in work_items if it.status in ("approved", "edited")]
    generated = [it for it in work_items if it.status == "generated"]
    rejected = [it for it in work_items if it.status == "rejected"]

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("READY TO PUSH", len(approved))
    m2.metric("PENDING REVIEW", len(generated))
    m3.metric("REJECTED", len(rejected))
    m4.metric("BOARDS", 4)  # one per function

    st.markdown("<br>", unsafe_allow_html=True)

    left, right = st.columns([3, 2])

    with left:
        st.markdown('<div class="ctm-label">APPROVED TASKS PER FUNCTION</div>',
                    unsafe_allow_html=True)
        for fn in ["technical", "commercial", "operations", "design"]:
            fn_items = [it for it in approved if it.function == fn]
            fn_total = [it for it in work_items if it.function == fn]
            pct = int(100 * len(fn_items) / max(1, len(fn_total)))
            st.markdown(
                f'<div style="background:{SURFACE_1}; border: 1px solid {BORDER}; '
                f'border-radius: 4px; padding: 10px 14px; margin-bottom: 6px;">'
                f'  <div style="display: flex; justify-content: space-between; align-items: center;">'
                f'    <div style="font-family: Geist; font-size: 13px; font-weight: 500; color: {TEXT};">'
                f'      {fn.title()} → Delta Rewards — {fn.title()}'
                f'    </div>'
                f'    <div style="font-family: JetBrains Mono; font-size: 11px; color: {PRIMARY_HI};">'
                f'      {len(fn_items)}/{len(fn_total)}'
                f'    </div>'
                f'  </div>'
                f'  <div style="margin-top: 6px; height: 4px; background: {SURFACE_2}; '
                f'border-radius: 2px; overflow: hidden;">'
                f'    <div style="width: {pct}%; height: 100%; background: {PRIMARY_HI};"></div>'
                f'  </div>'
                f'</div>',
                unsafe_allow_html=True,
            )

    with right:
        st.markdown('<div class="ctm-label">DESTINATION & SYNC CONTROLS</div>',
                    unsafe_allow_html=True)
        is_dry = st.toggle("Dry run — preview only, no API calls", value=True)
        include_rejected = st.checkbox(
            "Archive dropped items to 'Removed by CR' list",
            value=False,
        )
        st.markdown('<br>', unsafe_allow_html=True)

        if not approved:
            st.markdown(alert("Approve at least one item on the Review tab.",
                              "info"), unsafe_allow_html=True)
        else:
            if st.button(
                f"► RUN PRE-FLIGHT DRY PUSH ({len(approved)} cards)"
                if is_dry else
                f"🚀 PUSH TO TRELLO ({len(approved)} cards)",
                type="primary", width="stretch",
            ):
                if is_dry:
                    result = sync_dry_run(run_id, extraction, work_items, store)
                    st.session_state["last_push_result"] = ("dry", result)
                else:
                    try:
                        with st.spinner("Pushing to Trello…"):
                            result = trello_sync(
                                run_id, extraction, work_items, store,
                                include_rejected=include_rejected,
                            )
                        st.session_state["last_push_result"] = ("real", result)
                    except TrelloError as e:
                        st.session_state["last_push_result"] = ("error", str(e))
                st.rerun()

    # Result panel
    if "last_push_result" in st.session_state:
        mode, res = st.session_state["last_push_result"]
        st.markdown("<br>", unsafe_allow_html=True)
        st.markdown('<div class="ctm-label">EXECUTION MANIFEST</div>',
                    unsafe_allow_html=True)
        if mode == "error":
            st.markdown(alert(f"Trello API error: {res}", "danger"),
                        unsafe_allow_html=True)
        else:
            rm1, rm2, rm3, rm4 = st.columns(4)
            rm1.metric("CREATED", len(res.created))
            rm2.metric("UPDATED", len(res.updated))
            rm3.metric("SKIPPED", len(res.skipped))
            rm4.metric("ARCHIVED", len(res.archived))

            # Preview table of the approved queue with actions
            actions = {i: "create" for i in res.created}
            actions.update({i: "update" for i in res.updated})
            actions.update({i: "skip" for i in res.skipped})
            preview = pd.DataFrame([
                {
                    "ACTION": actions.get(it.id, "—").upper(),
                    "ID": it.id,
                    "BOARD": f"Delta Rewards — {it.function.title()}",
                    "LIST": it.phase,
                    "DUE": it.due_date,
                    "TITLE": (it.title or "")[:70],
                }
                for it in approved
            ])
            st.dataframe(preview, hide_index=True, width="stretch", height=360)


# ---------------------------------------------------------------------------
# Tab 5 — Change-request diff
# ---------------------------------------------------------------------------

def render_tab_diff(run_id: str, base_run_id: str,
                    work_items: list[WorkItem], extraction: SOWExtraction,
                    report) -> None:
    base = load_existing_run(base_run_id, store=store)
    if base is None:
        st.markdown(alert("Base run not found.", "danger"), unsafe_allow_html=True)
        return

    diff = compute_diff(
        v1_run_id=base_run_id, v1_items=base.work_items, v1_report=base.report,
        v2_run_id=run_id, v2_items=work_items, v2_report=report,
    )
    s = diff.summary()

    # Delta metric strip
    cp_delta = f"{s['critical_path_days_delta']:+.0f}d"
    oc_delta = f"{s['over_committed_delta']:+d}"
    st.markdown(
        f'<div style="display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 12px;">'
        f'  {_delta_pill("ADDED",     s["added"],     SUCCESS)}'
        f'  {_delta_pill("REMOVED",   -s["removed"],  DANGER)}'
        f'  {_delta_pill("CHANGED",   s["changed"],   WARNING)}'
        f'  {_delta_pill("UNCHANGED", s["unchanged"], TEXT_2)}'
        f'  {_delta_pill("CRIT-PATH Δ", cp_delta, PRIMARY_HI)}'
        f'  {_delta_pill("OVER-COMMIT Δ", oc_delta, LOW_CONF)}'
        f'</div>',
        unsafe_allow_html=True,
    )

    # Added
    st.markdown('<div class="ctm-label">ADDED ITEMS · scope expansions in this revision</div>',
                unsafe_allow_html=True)
    if diff.added:
        st.dataframe(pd.DataFrame([
            {"ID": it.id, "FN": it.function[:4].upper(), "TYPE": it.type,
             "PHASE": it.phase, "EST": f"{it.estimate_days:g}d",
             "TITLE": (it.title or "")[:80]}
            for it in diff.added
        ]), hide_index=True, width="stretch", height=220)
    else:
        st.markdown(hint("No items added."), unsafe_allow_html=True)

    # Removed
    st.markdown('<div class="ctm-label" style="margin-top: 12px;">REMOVED ITEMS · previously in scope, dropped</div>',
                unsafe_allow_html=True)
    if diff.removed:
        st.dataframe(pd.DataFrame([
            {"ID": it.id, "FN": it.function[:4].upper(), "TYPE": it.type,
             "PHASE": it.phase, "EST": f"{it.estimate_days:g}d",
             "TITLE": (it.title or "")[:80]}
            for it in diff.removed
        ]), hide_index=True, width="stretch", height=200)
    else:
        st.markdown(hint("No items removed."), unsafe_allow_html=True)

    # Changed
    st.markdown('<div class="ctm-label" style="margin-top: 12px;">CHANGED ITEMS · field-level revisions</div>',
                unsafe_allow_html=True)
    if diff.changed:
        rows = []
        for v1, v2 in diff.changed[:80]:
            deltas = field_deltas(v1, v2)
            rows.append({
                "ID V1": v1.id, "ID V2": v2.id, "FN": v2.function[:4].upper(),
                "CHANGED FIELDS": ", ".join(deltas) if deltas else "—",
                "TITLE": (v2.title or "")[:70],
            })
        st.dataframe(pd.DataFrame(rows), hide_index=True,
                     width="stretch", height=300)
        if len(diff.changed) > 80:
            st.markdown(hint(f"showing 80 of {len(diff.changed)} changed items"),
                        unsafe_allow_html=True)
    else:
        st.markdown(hint("No field changes."), unsafe_allow_html=True)

    # Apply CR bar
    st.markdown("<br>", unsafe_allow_html=True)
    st.markdown('<div class="ctm-label">APPLY CHANGE REQUEST</div>',
                unsafe_allow_html=True)
    st.markdown(
        f'<div style="font-size: 12px; color: {TEXT_2};">'
        f'Carries {len(diff.unchanged) + len(diff.changed)} matched card ids from the base run · '
        f'creates {len(diff.added)} new cards · archives {len(diff.removed)} to "Removed by CR".'
        f'</div>',
        unsafe_allow_html=True,
    )
    st.markdown("<br>", unsafe_allow_html=True)
    cr_dry = st.toggle("Dry run — preview only", value=True, key="cr-dry")
    if st.button("APPLY CHANGE REQUEST", type="primary"):
        if cr_dry:
            st.markdown(
                alert(
                    f"Dry run: would carry {len(diff.unchanged) + len(diff.changed)} card ids, "
                    f"create {len(diff.added)}, archive {len(diff.removed)}.",
                    "success",
                ),
                unsafe_allow_html=True,
            )
        else:
            try:
                with st.spinner("Applying change request…"):
                    result = apply_change_request(
                        base_run_id=base_run_id, cr_run_id=run_id,
                        diff=diff, cr_extraction=extraction, cr_items=work_items,
                        store=store,
                    )
                st.markdown(
                    alert(f"Applied — {result.summary()}", "success"),
                    unsafe_allow_html=True,
                )
            except TrelloError as e:
                st.markdown(alert(f"Trello error: {e}", "danger"),
                            unsafe_allow_html=True)


def _delta_pill(label: str, value, color: str) -> str:
    return (
        f'<div style="background:{SURFACE_1}; border: 1px solid {BORDER}; '
        f'border-radius: 4px; padding: 10px 14px; flex: 1; min-width: 130px;">'
        f'  <div style="font-family: JetBrains Mono; font-size: 10px; letter-spacing: 0.08em; '
        f'text-transform: uppercase; color: {TEXT_2};">{label}</div>'
        f'  <div style="font-family: JetBrains Mono; font-size: 22px; font-weight: 600; '
        f'color: {color}; margin-top: 2px;">{value}</div>'
        f'</div>'
    )


def main() -> None:
    runs = store.list_runs()

    # Preload data for whichever run is currently active (from session state)
    # so we can pass populated clause navigation into the sidebar. This
    # keeps the sidebar as a single render pass — no duplicate widget ids.
    prev_run_id = st.session_state.get("run_id")
    preloaded = load_existing_run(prev_run_id, store=store) if prev_run_id else None

    selected_id, base_run_id = _render_sidebar(
        runs,
        preloaded.work_items if preloaded else None,
        preloaded.extraction if preloaded else None,
    )

    # Sidebar returned a new choice → rerun with it as the active run
    if selected_id and selected_id != prev_run_id:
        st.session_state["run_id"] = selected_id
        st.rerun()

    run_id = st.session_state.get("run_id")
    if not run_id:
        st.markdown(
            alert("👈 Pick an existing run or upload a SOW in the sidebar.",
                  "info"),
            unsafe_allow_html=True,
        )
        return

    result = preloaded if preloaded and preloaded.run_id == run_id else load_existing_run(run_id, store=store)
    if result is None:
        st.markdown(alert(f"Run `{run_id}` not found.", "danger"),
                    unsafe_allow_html=True)
        return

    extraction = result.extraction
    work_items = result.work_items
    report = result.report

    _render_header(extraction, run_id,
                   over_committed_count=len(report.over_committed_ids),
                   unmapped_count=len(extraction.unmapped_clauses))

    tab_names = [
        "EXTRACTION",
        f"REVIEW ITEMS ({len(work_items)})",
        "TIMELINE & CRITICAL PATH",
        "PUSH TO TRELLO",
    ]
    if base_run_id:
        tab_names.append("CHANGE-REQUEST DIFF")
    tab_names.append("⚙  SETTINGS")   # last — admin surface

    _tabs = st.tabs(tab_names)
    with _tabs[0]:
        render_tab_extraction(extraction, work_items)
    with _tabs[1]:
        render_tab_review(run_id, work_items, extraction)
    with _tabs[2]:
        render_tab_timeline(work_items, report)
    with _tabs[3]:
        render_tab_push(run_id, extraction, work_items)
    idx = 4
    if base_run_id:
        with _tabs[idx]:
            render_tab_diff(run_id, base_run_id, work_items, extraction, report)
        idx += 1
    with _tabs[idx]:
        render_settings_tab()


main()
