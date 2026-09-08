from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st
import yaml

from src.ui_theme import (
    BORDER,
    LOW_CONF,
    PRIMARY_HI,
    SUCCESS,
    SURFACE_1,
    SURFACE_2,
    TEXT,
    TEXT_2,
    WARNING,
    alert,
    badge,
)


_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_CONFIG_DIR = _PROJECT_ROOT / "data" / "config"


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def _load_yaml(name: str) -> dict[str, Any]:
    path = _CONFIG_DIR / name
    return yaml.safe_load(path.read_text()) if path.exists() else {}


def _save_yaml(name: str, data: dict[str, Any]) -> None:
    path = _CONFIG_DIR / name
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True))


def _section_header(title: str, subtitle: str = "") -> None:
    st.markdown(
        f'<div style="margin-bottom: 10px;">'
        f'  <div style="font-family: Geist; font-size: 16px; font-weight: 600; '
        f'color: {TEXT}; letter-spacing: -0.01em;">{title}</div>'
        + (
            f'  <div style="font-size: 12px; color: {TEXT_2}; margin-top: 2px;">{subtitle}</div>'
            if subtitle else ''
        )
        + '</div>',
        unsafe_allow_html=True,
    )


def _status_pill(label: str, kind: str) -> str:
    return badge(label, kind)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Entry point — the "Settings" tab
# ---------------------------------------------------------------------------

def render_settings_tab() -> None:
    

    sub_teams, sub_est, sub_tpl, sub_cal = st.tabs([
        "TEAMS & SQUADS",
        "ESTIMATION LIBRARY",
        "TASK TEMPLATES",
        "WORKING CALENDAR",
    ])

    with sub_teams:
        _render_teams()
    with sub_est:
        _render_estimation()
    with sub_tpl:
        _render_task_templates()
    with sub_cal:
        _render_calendar()


# ---------------------------------------------------------------------------
# Teams
# ---------------------------------------------------------------------------

def _render_teams() -> None:
    teams = _load_yaml("teams.yaml")
    _section_header(
        "Teams & squads",
        "Full Dsquares roster. Updated when people join/leave/reorg — never per project.",
    )

    # ── Squads ──
    st.markdown('<div class="ctm-label" style="margin-top: 8px;">SQUADS</div>',
                unsafe_allow_html=True)
    squads = teams.get("squads", [])
    for i, squad in enumerate(squads):
        with st.container(border=True):
            c1, c2 = st.columns([3, 1])
            new_name = c1.text_input(
                "Squad name", value=squad["name"], key=f"squad-name-{i}",
                label_visibility="collapsed",
            )
            if c2.button("✕ remove squad", key=f"remove-squad-{i}",
                         width="stretch"):
                squads.pop(i)
                teams["squads"] = squads
                _save_yaml("teams.yaml", teams)
                st.rerun()
            squad["name"] = new_name

            # Modules owned
            st.markdown(
                '<div class="ctm-label" style="margin-top: 8px;">MODULES OWNED</div>',
                unsafe_allow_html=True,
            )
            modules_str = st.text_input(
                "Modules (comma-separated)",
                value=", ".join(squad.get("modules", [])),
                key=f"squad-modules-{i}",
                label_visibility="collapsed",
            )
            squad["modules"] = [m.strip() for m in modules_str.split(",") if m.strip()]

            # Members table
            st.markdown(
                '<div class="ctm-label" style="margin-top: 8px;">MEMBERS</div>',
                unsafe_allow_html=True,
            )
            members = squad.get("members", [])
            edited_members = st.data_editor(
                pd.DataFrame(members) if members else
                pd.DataFrame([{"name": "", "role": ""}]),
                num_rows="dynamic",
                width="stretch",
                key=f"squad-members-{i}",
                hide_index=True,
            )
            squad["members"] = [
                {"name": row["name"], "role": row["role"]}
                for row in edited_members.to_dict(orient="records")
                if row.get("name")
            ]

    # ── Add squad ──
    c1, c2 = st.columns([1, 3])
    if c1.button("＋ Add squad", width="stretch"):
        squads.append({
            "name": f"Squad — new (rename me)",
            "modules": [],
            "members": [],
        })
        teams["squads"] = squads
        _save_yaml("teams.yaml", teams)
        st.rerun()

    st.markdown("<br>", unsafe_allow_html=True)

    # ── Function pools ──
    st.markdown('<div class="ctm-label">FUNCTION POOLS</div>', unsafe_allow_html=True)
    st.caption(
        "People available to any function-level assignment (QA cycles, "
        "commercial batches, field-ops waves, design tasks) when no squad "
        "owns the specific module."
    )
    for pool_key, pool_label in [
        ("qa_pool", "QA POOL"),
        ("commercial_team", "COMMERCIAL TEAM"),
        ("field_ops_team", "FIELD OPS TEAM"),
        ("designers", "DESIGNERS"),
    ]:
        with st.container(border=True):
            st.markdown(
                f'<div class="ctm-label">{pool_label}</div>',
                unsafe_allow_html=True,
            )
            pool = teams.get(pool_key, [])
            edited = st.data_editor(
                pd.DataFrame(pool) if pool else pd.DataFrame([{"name": "", "role": ""}]),
                num_rows="dynamic",
                width="stretch",
                key=f"pool-{pool_key}",
                hide_index=True,
            )
            teams[pool_key] = [
                {"name": row["name"], "role": row["role"]}
                for row in edited.to_dict(orient="records")
                if row.get("name")
            ]

    # ── Assignment rule ──
    st.markdown('<div class="ctm-label">ASSIGNMENT RULE</div>', unsafe_allow_html=True)
    rule = st.selectbox(
        "Rule",
        ["round_robin_by_role", "load_balanced_by_role", "capacity_aware"],
        index=["round_robin_by_role", "load_balanced_by_role", "capacity_aware"]
        .index(teams.get("assignment_rule", "round_robin_by_role")),
        key="assignment-rule",
        label_visibility="collapsed",
        help="Only round_robin_by_role is implemented in the current pipeline.",
    )
    teams["assignment_rule"] = rule

    st.markdown("<br>", unsafe_allow_html=True)
    c1, c2 = st.columns([1, 4])
    if c1.button("💾 Save teams.yaml", type="primary", width="stretch"):
        _save_yaml("teams.yaml", teams)
        st.markdown(
            alert(f"Saved {sum(len(s.get('members', [])) for s in squads)} squad members "
                  f"and {sum(len(teams.get(p, [])) for p in ['qa_pool', 'commercial_team', 'field_ops_team', 'designers'])} pool members.",
                  kind="success", icon="✓"),
            unsafe_allow_html=True,
        )


# ---------------------------------------------------------------------------
# Estimation library
# ---------------------------------------------------------------------------

def _render_estimation() -> None:
    est = _load_yaml("estimation_library.yaml")
    _section_header(
        "Estimation library",
        "The rate card. One entry per archetype (task type). Set once, "
        "recalibrated quarterly from actual delivery data.",
    )

    for function in ["technical", "commercial", "operations", "design"]:
        st.markdown(f'<div class="ctm-label" style="margin-top: 12px;">'
                    f'{function.upper()} ARCHETYPES</div>',
                    unsafe_allow_html=True)
        archetypes = est.get(function, {})

        # Flatten into a dataframe
        rows = []
        for key, val in archetypes.items():
            rows.append({
                "archetype_key": key,
                "base_days": val.get("base_days", 0),
                "role": val.get("role", ""),
                "unit_size": val.get("unit_size", None),
            })
        if not rows:
            rows = [{"archetype_key": "", "base_days": 0, "role": "", "unit_size": None}]

        edited = st.data_editor(
            pd.DataFrame(rows),
            num_rows="dynamic",
            width="stretch",
            key=f"est-{function}",
            hide_index=True,
            column_config={
                "archetype_key": st.column_config.TextColumn("Archetype (snake_case)",
                                                              required=True),
                "base_days":     st.column_config.NumberColumn("Days",
                                                                min_value=0.1,
                                                                step=0.5),
                "role":          st.column_config.TextColumn("Role"),
                "unit_size":     st.column_config.NumberColumn("Unit size (batch)",
                                                                help="Only for fan-out archetypes"),
            },
        )

        # Materialise back to dict form
        new_archetypes: dict[str, dict[str, Any]] = {}
        for row in edited.to_dict(orient="records"):
            key = (row.get("archetype_key") or "").strip()
            if not key:
                continue
            entry: dict[str, Any] = {
                "base_days": row["base_days"],
                "role": row.get("role", ""),
            }
            if row.get("unit_size") is not None and not pd.isna(row["unit_size"]):
                entry["unit_size"] = int(row["unit_size"])
            new_archetypes[key] = entry
        est[function] = new_archetypes

    st.markdown("<br>", unsafe_allow_html=True)
    c1, c2 = st.columns([1, 4])
    if c1.button("💾 Save estimation_library.yaml", type="primary", width="stretch"):
        _save_yaml("estimation_library.yaml", est)
        total = sum(len(est.get(f, {})) for f in ["technical", "commercial", "operations", "design"])
        st.markdown(alert(f"Saved {total} archetypes across 4 functions.",
                          kind="success", icon="✓"),
                    unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Task templates — mostly read-only, raw YAML editor
# ---------------------------------------------------------------------------

_PHASES = ["Discovery", "Build", "UAT", "Launch", "Post-launch"]
_WORK_ITEM_TYPES = [
    "epic", "user_story", "test_case", "tech_validation",
    "commercial_task", "ops_task", "design_task", "milestone",
]


def _edit_default_children(function: str, rows: list[dict]) -> list[dict]:
    """Editable table for the default_children list of one function."""
    st.markdown(
        '<div class="ctm-label">DEFAULT CHILDREN</div>',
        unsafe_allow_html=True,
    )
    st.caption(
        "Sub-tasks always generated per scope item of this function. "
        "`count: variable` = LLM decides how many; `per: user_story` = "
        "one per sibling of that type."
    )
    if not rows:
        rows = [{"type": "", "archetype": "", "count": "1", "per": "",
                 "phase": "Build"}]
    # Ensure every row is a dict with all keys — data_editor requires uniform shape
    normalized = [
        {
            "type": r.get("type", ""),
            "archetype": r.get("archetype", ""),
            "count": str(r.get("count", "")) if r.get("count") is not None else "",
            "per": r.get("per", "") if r.get("per") else "",
            "phase": r.get("phase", "Build"),
        }
        for r in rows
    ]
    edited = st.data_editor(
        pd.DataFrame(normalized),
        num_rows="dynamic",
        width="stretch",
        key=f"tpl-children-{function}",
        hide_index=True,
        column_config={
            "type": st.column_config.SelectboxColumn(
                "Task type", options=_WORK_ITEM_TYPES, required=True,
            ),
            "archetype": st.column_config.TextColumn(
                "Archetype key", required=True,
                help="Must match a key in estimation_library.yaml for this function",
            ),
            "count": st.column_config.TextColumn(
                "Count", help="'1' for fixed, 'variable' for LLM-decided",
            ),
            "per": st.column_config.TextColumn(
                "Per (optional)", help="e.g. 'user_story' = one per sibling story",
            ),
            "phase": st.column_config.SelectboxColumn(
                "Phase", options=_PHASES, required=True,
            ),
        },
    )
    out: list[dict] = []
    for r in edited.to_dict(orient="records"):
        if not r.get("type") or not r.get("archetype"):
            continue
        entry: dict[str, Any] = {
            "type": r["type"],
            "archetype": r["archetype"].strip(),
            "phase": r["phase"],
        }
        count = (r.get("count") or "").strip()
        if count:
            # Try int first; fall back to string ("variable")
            try:
                entry["count"] = int(count)
            except ValueError:
                entry["count"] = count
        per = (r.get("per") or "").strip()
        if per:
            entry["per"] = per
        out.append(entry)
    return out


def _edit_fanout_rules(function: str, rows: list[dict]) -> list[dict]:
    """Editable table for the fanout_rules list of one function."""
    st.markdown(
        '<div class="ctm-label" style="margin-top: 12px;">FANOUT RULES</div>',
        unsafe_allow_html=True,
    )
    st.caption(
        "When a scope item has `quantity + unit` matching one of these "
        "rows, fan out into batches deterministically. Keyword optional — "
        "used when two rules share the same unit."
    )
    if not rows:
        rows = [{"unit": "", "keyword": "", "archetype": "", "phase": "Build"}]
    normalized = [
        {
            "unit": r.get("unit", ""),
            "keyword": r.get("keyword", "") if r.get("keyword") else "",
            "archetype": r.get("archetype", ""),
            "phase": r.get("phase", "Build"),
        }
        for r in rows
    ]
    edited = st.data_editor(
        pd.DataFrame(normalized),
        num_rows="dynamic",
        width="stretch",
        key=f"tpl-fanout-{function}",
        hide_index=True,
        column_config={
            "unit": st.column_config.TextColumn(
                "Unit (from ScopeItem)", required=True,
                help="e.g. 'merchants', 'regions', 'offers'",
            ),
            "keyword": st.column_config.TextColumn(
                "Keyword (optional)",
                help="Disambiguates when multiple rules share the same unit",
            ),
            "archetype": st.column_config.TextColumn(
                "Archetype key", required=True,
                help="Must exist in estimation_library.yaml for this function",
            ),
            "phase": st.column_config.SelectboxColumn(
                "Phase", options=_PHASES, required=True,
            ),
        },
    )
    out: list[dict] = []
    for r in edited.to_dict(orient="records"):
        if not r.get("unit") or not r.get("archetype"):
            continue
        entry: dict[str, Any] = {
            "unit": r["unit"].strip(),
            "archetype": r["archetype"].strip(),
            "phase": r["phase"],
        }
        kw = (r.get("keyword") or "").strip()
        if kw:
            entry["keyword"] = kw
        out.append(entry)
    return out


def _edit_dependency_rules(function: str, rows: list[dict]) -> list[dict]:
    """Editable table for the dependency_rules list of one function.

    depends_on is a list — we render it as a comma-separated string in
    the UI and parse it back on save.
    """
    st.markdown(
        '<div class="ctm-label" style="margin-top: 12px;">DEPENDENCY RULES</div>',
        unsafe_allow_html=True,
    )
    st.caption(
        "Every item of type/archetype 'from' automatically depends on "
        "every sibling of type/archetype in 'depends_on'. Comma-separate "
        "multiple values in 'depends_on'."
    )
    if not rows:
        rows = [{"from": "", "depends_on": ""}]
    normalized = [
        {
            "from": r.get("from", ""),
            "depends_on": ", ".join(r.get("depends_on", []))
            if isinstance(r.get("depends_on"), list)
            else (r.get("depends_on", "") or ""),
        }
        for r in rows
    ]
    edited = st.data_editor(
        pd.DataFrame(normalized),
        num_rows="dynamic",
        width="stretch",
        key=f"tpl-deps-{function}",
        hide_index=True,
        column_config={
            "from": st.column_config.TextColumn(
                "From (type or archetype)", required=True,
                help="e.g. 'test_case' or 'merchant_training_wave'",
            ),
            "depends_on": st.column_config.TextColumn(
                "Depends on (comma-separated)", required=True,
                help="e.g. 'user_story' or 'anchor_partner_deal'",
            ),
        },
    )
    out: list[dict] = []
    for r in edited.to_dict(orient="records"):
        src = (r.get("from") or "").strip()
        deps_raw = (r.get("depends_on") or "").strip()
        if not src or not deps_raw:
            continue
        out.append({
            "from": src,
            "depends_on": [d.strip() for d in deps_raw.split(",") if d.strip()],
        })
    return out


def _edit_global_rules(rows: list[dict]) -> list[dict]:
    """Editable table for global_dependency_rules (cross-function phase gates)."""
    st.markdown(
        '<div class="ctm-label">GLOBAL PHASE-GATE RULES</div>',
        unsafe_allow_html=True,
    )
    st.caption(
        "Whole-project rules — every task in `from_phase` waits for every "
        "task in `depends_on_phase` to finish. Applied by the scheduler, "
        "not the LLM."
    )
    if not rows:
        rows = [{"from_phase": "Build", "depends_on_phase": "Discovery"}]
    normalized = [
        {
            "from_phase": r.get("from_phase", "Build"),
            "depends_on_phase": r.get("depends_on_phase", "Discovery"),
        }
        for r in rows
    ]
    edited = st.data_editor(
        pd.DataFrame(normalized),
        num_rows="dynamic",
        width="stretch",
        key="tpl-global-deps",
        hide_index=True,
        column_config={
            "from_phase": st.column_config.SelectboxColumn(
                "From phase", options=_PHASES, required=True,
            ),
            "depends_on_phase": st.column_config.SelectboxColumn(
                "Depends on phase", options=_PHASES, required=True,
            ),
        },
    )
    out: list[dict] = []
    for r in edited.to_dict(orient="records"):
        if not r.get("from_phase") or not r.get("depends_on_phase"):
            continue
        out.append({
            "from_phase": r["from_phase"],
            "depends_on_phase": r["depends_on_phase"],
        })
    return out


def _render_task_templates() -> None:
    tpl = _load_yaml("task_templates.yaml")
    _section_header(
        "Task templates",
        "The delivery playbook — how each function's scope items break down "
        "into tasks. Edit each function's three rule tables below.",
    )

    # Per-function editors — one container per function
    new_tpl: dict[str, Any] = {}
    for function in ["technical", "commercial", "operations", "design"]:
        fn_tpl = tpl.get(function, {})
        with st.container(border=True):
            st.markdown(
                f'<div style="font-family: Geist; font-size: 15px; '
                f'font-weight: 600; color: {TEXT}; margin-bottom: 4px;">'
                f'  {function.upper()}'
                f'</div>',
                unsafe_allow_html=True,
            )
            new_children = _edit_default_children(function, fn_tpl.get("default_children", []))
            new_fanouts  = _edit_fanout_rules(function, fn_tpl.get("fanout_rules", []))
            new_deps     = _edit_dependency_rules(function, fn_tpl.get("dependency_rules", []))

            fn_out: dict[str, Any] = {}
            if new_children:
                fn_out["default_children"] = new_children
            if new_fanouts:
                fn_out["fanout_rules"] = new_fanouts
            if new_deps:
                fn_out["dependency_rules"] = new_deps
            if fn_out:
                new_tpl[function] = fn_out

    # Global rules — separate container
    with st.container(border=True):
        new_global = _edit_global_rules(tpl.get("global_dependency_rules", []))
        if new_global:
            new_tpl["global_dependency_rules"] = new_global

    # Save
    st.markdown("<br>", unsafe_allow_html=True)
    c1, c2, c3 = st.columns([1, 1, 3])
    if c1.button("💾 Save task_templates.yaml", type="primary",
                 width="stretch"):
        _save_yaml("task_templates.yaml", new_tpl)
        total_rules = sum(
            len(new_tpl.get(f, {}).get("default_children", [])) +
            len(new_tpl.get(f, {}).get("fanout_rules", [])) +
            len(new_tpl.get(f, {}).get("dependency_rules", []))
            for f in ["technical", "commercial", "operations", "design"]
        )
        total_rules += len(new_tpl.get("global_dependency_rules", []))
        st.markdown(
            alert(f"Saved {total_rules} rules across all functions.",
                  kind="success", icon="✓"),
            unsafe_allow_html=True,
        )

    # Optional escape hatch — raw YAML for edge cases
    with st.expander("⚙  Raw YAML editor (advanced)", expanded=False):
        st.caption(
            "Direct YAML editing for edge cases the visual editor can't "
            "represent yet. Save validates parse before writing."
        )
        raw = yaml.safe_dump(new_tpl or tpl, sort_keys=False, allow_unicode=True)
        edited_raw = st.text_area("YAML", value=raw, height=280,
                                  key="tpl-raw", label_visibility="collapsed")
        if st.button("Save from raw YAML", key="tpl-raw-save"):
            try:
                parsed = yaml.safe_load(edited_raw)
                _save_yaml("task_templates.yaml", parsed)
                st.markdown(alert("Saved via raw YAML.", kind="success", icon="✓"),
                            unsafe_allow_html=True)
            except yaml.YAMLError as e:
                st.markdown(alert(f"YAML parse error — not saved: {e}",
                                  kind="danger", icon="✗"),
                            unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Calendar
# ---------------------------------------------------------------------------

def _render_calendar() -> None:
    cal = _load_yaml("calendar.yaml")
    _section_header(
        "Working calendar",
        "Weekend definition and public holidays. Updated once per year, "
        "or when holiday dates are officially confirmed.",
    )

    # Weekend selector
    st.markdown('<div class="ctm-label">WEEKEND</div>', unsafe_allow_html=True)
    weekend_now = cal.get("weekend", ["Friday", "Saturday"])
    all_days = ["Monday", "Tuesday", "Wednesday", "Thursday",
                "Friday", "Saturday", "Sunday"]
    weekend_selected = st.multiselect(
        "Non-working days of the week",
        all_days,
        default=weekend_now,
        key="weekend-select",
        label_visibility="collapsed",
    )
    cal["weekend"] = weekend_selected

    st.markdown("<br>", unsafe_allow_html=True)

    # Holidays table
    st.markdown('<div class="ctm-label">PUBLIC HOLIDAYS 2026</div>',
                unsafe_allow_html=True)
    st.caption(
        "Any date listed here is treated as a non-working day by the "
        "back-scheduler. Islamic-calendar dates can shift ±1 day on "
        "moon-sighting — update when official."
    )
    holidays = cal.get("public_holidays_2026", [])
    if not holidays:
        holidays = [{"date": "2026-01-01", "name": ""}]

    edited = st.data_editor(
        pd.DataFrame(holidays),
        num_rows="dynamic",
        width="stretch",
        key="holidays-edit",
        hide_index=True,
        column_config={
            "date": st.column_config.TextColumn("Date (YYYY-MM-DD)", required=True),
            "name": st.column_config.TextColumn("Name", required=True),
        },
    )
    cal["public_holidays_2026"] = [
        {"date": row["date"], "name": row.get("name", "")}
        for row in edited.to_dict(orient="records")
        if row.get("date")
    ]

    st.markdown("<br>", unsafe_allow_html=True)

    # Preview: next 10 working days
    st.markdown('<div class="ctm-label">WORKING-DAY PREVIEW</div>',
                unsafe_allow_html=True)
    st.caption(
        "The next 10 working days starting today, given the current "
        "weekend and holiday settings."
    )
    try:
        weekend_idx = {"Monday":0, "Tuesday":1, "Wednesday":2, "Thursday":3,
                       "Friday":4, "Saturday":5, "Sunday":6}
        wend = {weekend_idx[d] for d in weekend_selected}
        hols = {row["date"] for row in cal["public_holidays_2026"]}
        preview_rows = []
        from datetime import timedelta
        d = date.today()
        count = 0
        while count < 10:
            iso = d.isoformat()
            if d.weekday() not in wend and iso not in hols:
                preview_rows.append({
                    "date": iso,
                    "weekday": all_days[d.weekday()],
                    "status": "✓ working day",
                })
                count += 1
            d += timedelta(days=1)
        st.dataframe(pd.DataFrame(preview_rows), hide_index=True,
                     width="stretch", height=380)
    except Exception as e:
        st.markdown(alert(f"Preview error: {e}", kind="danger", icon="✗"),
                    unsafe_allow_html=True)

    c1, c2 = st.columns([1, 4])
    if c1.button("💾 Save calendar.yaml", type="primary", width="stretch"):
        _save_yaml("calendar.yaml", cal)
        st.markdown(
            alert(f"Saved: {len(cal['weekend'])} weekend days + "
                  f"{len(cal['public_holidays_2026'])} holidays.",
                  kind="success", icon="✓"),
            unsafe_allow_html=True,
        )
