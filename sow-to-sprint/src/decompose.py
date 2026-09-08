import math
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import yaml
from openai import OpenAI
from pydantic import BaseModel, Field

from src.config import get_settings
from src.models import (
    Phase,
    ScopeItem,
    SOWExtraction,
    WorkItem,
    WorkItemType,
)

class LLMWorkItem(BaseModel):
    type: WorkItemType
    title: str
    description: str
    acceptance_criteria: list[str] = Field(default_factory=list)
    gherkin: str | None = None
    archetype_key: str
    confidence: Literal["high", "medium", "low"]


class LLMDecomposition(BaseModel):
    items: list[LLMWorkItem]


_PHASE_BY_TYPE: dict[WorkItemType, Phase] = {
    "epic": "Discovery",
    "user_story": "Build",
    "test_case": "Build",
    "tech_validation": "Build",
    "commercial_task": "Discovery",
    "ops_task": "Build",
    "design_task": "Build",
    "milestone": "Discovery",
}

# Archetype-specific overrides — used when the type alone is ambiguous.
_PHASE_BY_ARCHETYPE: dict[str, Phase] = {
    "wireframes": "Discovery",
    "hi_fi_screens": "Build",
    "design_system": "Build",
    "design_qa": "UAT",
    "uat_cycle": "UAT",
    "merchant_training_wave": "Launch",
    "merchant_onboarding_wave": "Launch",
    "support_playbook": "Launch",
    "anchor_partner_deal": "Discovery",
    "merchant_acquisition_batch": "Build",
    "offer_negotiation_batch": "Build",
    "pos_setup_per_region": "Build",
    "system_configuration": "Build",
    "tech_validation": "Build",
}


# ---------------------------------------------------------------------------
# Loading configuration
# ---------------------------------------------------------------------------

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_CONFIG_DIR = _PROJECT_ROOT / "data" / "config"
_PROMPT_DIR = Path(__file__).parent / "prompts"
_PROMPT_PATHS = {
    "technical": _PROMPT_DIR / "decompose_technical.md",
    "commercial": _PROMPT_DIR / "decompose_commercial.md",
    "operations": _PROMPT_DIR / "decompose_operations.md",
    "design": _PROMPT_DIR / "decompose_design.md",
}


@dataclass
class _Ctx:
    estimation: dict[str, Any]
    templates: dict[str, Any]
    teams: dict[str, Any]
    client: OpenAI
    model: str
    # Assignment state (mutable — round-robin counters per role).
    role_counters: dict[str, int] = field(
        default_factory=lambda: defaultdict(int)
    )
    # Per-function id counter (T-TECH-001, T-COM-001, …).
    id_counters: dict[str, int] = field(
        default_factory=lambda: defaultdict(int)
    )


def _load_ctx() -> _Ctx:
    estimation = yaml.safe_load(
        (_CONFIG_DIR / "estimation_library.yaml").read_text()
    )
    templates = yaml.safe_load(
        (_CONFIG_DIR / "task_templates.yaml").read_text()
    )
    teams = yaml.safe_load((_CONFIG_DIR / "teams.yaml").read_text())
    settings = get_settings()
    return _Ctx(
        estimation=estimation,
        templates=templates,
        teams=teams,
        client=OpenAI(api_key=settings.openai_api_key),
        model=settings.openai_model,
    )


# ---------------------------------------------------------------------------
# Assignment (round-robin by role, respecting squad ownership by module)
# ---------------------------------------------------------------------------

def _people_for_role(ctx: _Ctx, role: str, module: str | None) -> list[str]:
    """Return the candidate list of names for a given role, preferring the
    squad that owns `module` when applicable."""
    if module:
        for squad in ctx.teams["squads"]:
            if module in squad["modules"]:
                names = [m["name"] for m in squad["members"] if m["role"] == role]
                if names:
                    return names
    # Fallback pools by role family
    for pool_key in (
        "qa_pool",
        "commercial_team",
        "field_ops_team",
        "designers",
    ):
        pool = ctx.teams.get(pool_key, [])
        names = [m["name"] for m in pool if m["role"] == role]
        if names:
            return names
    # Last resort: search every squad
    names = []
    for squad in ctx.teams["squads"]:
        names.extend(m["name"] for m in squad["members"] if m["role"] == role)
    return names


def _assign(ctx: _Ctx, role: str, module: str | None) -> tuple[str | None, str | None]:
    """Return (assignee, squad_name) using round-robin within role scope."""
    people = _people_for_role(ctx, role, module)
    if not people:
        return (None, None)
    idx = ctx.role_counters[role] % len(people)
    ctx.role_counters[role] += 1
    assignee = people[idx]
    # Find which squad this assignee belongs to (for the squad label).
    for squad in ctx.teams["squads"]:
        if assignee in {m["name"] for m in squad["members"]}:
            return (assignee, squad["name"])
    return (assignee, None)


# ---------------------------------------------------------------------------
# Lookups
# ---------------------------------------------------------------------------

def _archetype(ctx: _Ctx, function: str, key: str) -> dict[str, Any] | None:
    return ctx.estimation.get(function, {}).get(key)


def _phase_for(item_type: WorkItemType, archetype_key: str) -> Phase:
    return _PHASE_BY_ARCHETYPE.get(archetype_key, _PHASE_BY_TYPE.get(item_type, "Build"))


def _next_id(ctx: _Ctx, function: str) -> str:
    prefix_map = {
        "technical": "TECH",
        "commercial": "COM",
        "operations": "OPS",
        "design": "DES",
    }
    prefix = prefix_map[function]
    ctx.id_counters[function] += 1
    return f"T-{prefix}-{ctx.id_counters[function]:03d}"


# ---------------------------------------------------------------------------
# Fan-out path (no LLM)
# ---------------------------------------------------------------------------

def _has_fanout_rule(scope: ScopeItem, ctx: _Ctx) -> bool:
    """Peek at whether _resolve_fanout would produce items — no ctx mutations.

    Used by decompose() to decide which scope items need an LLM call before
    firing them off in parallel.
    """
    if scope.quantity is None or scope.unit is None:
        return False
    fnc_templates = ctx.templates.get(scope.function, {})
    return any(
        r.get("unit") == scope.unit
        for r in fnc_templates.get("fanout_rules", [])
    )


def _resolve_fanout(scope: ScopeItem, ctx: _Ctx) -> list[WorkItem] | None:
    """Return fan-out work items if the scope item matches one or more
    fan-out rules, else `None` (caller falls back to LLM decomposition).

    **Compound scope handling:** if the scope item mentions the keywords of
    *multiple* keyword-guarded rules (e.g. "Merchant Training and
    Onboarding" — both `training` and `onboarding` present), fire **all**
    matching keyword rules. This mirrors the fix in
    extract_sow.md rule 6, and is the belt-and-braces backstop when the
    extractor fails to split a compound clause into two scope items.
    """
    if scope.quantity is None or scope.unit is None:
        return None

    fnc_templates = ctx.templates.get(scope.function, {})
    unit_matches = [
        r for r in fnc_templates.get("fanout_rules", []) if r.get("unit") == scope.unit
    ]
    if not unit_matches:
        return None

    haystack = f"{scope.title} {scope.description}".lower()

    # Split rules into: with keyword vs without.
    with_kw = [r for r in unit_matches if r.get("keyword")]
    without_kw = [r for r in unit_matches if not r.get("keyword")]

    # Which keyword-guarded rules are actually triggered by this scope item?
    keyword_hits = [r for r in with_kw if r["keyword"].lower() in haystack]

    if with_kw:
        # Keyword-guarded rules exist. Fire each one whose keyword matches.
        # If none matched (odd edge case), fall back to the first one.
        rules_to_apply = keyword_hits if keyword_hits else [with_kw[0]]
    else:
        # No keyword guards → just use the first matching rule.
        rules_to_apply = [without_kw[0]] if without_kw else []

    items: list[WorkItem] = []
    for rule in rules_to_apply:
        archetype_key = rule["archetype"]
        archetype = _archetype(ctx, scope.function, archetype_key)
        if archetype is None:
            continue  # inconsistent config — skip this rule
        unit_size = archetype.get("unit_size", 1)
        n_batches = max(1, math.ceil(scope.quantity / unit_size))
        items.extend(_make_fanout_items(
            scope=scope,
            archetype_key=archetype_key,
            unit_size=unit_size,
            n_batches=n_batches,
            ctx=ctx,
        ))
    return items if items else None


def _make_fanout_items(
    *,
    scope: ScopeItem,
    archetype_key: str,
    unit_size: int,
    n_batches: int,
    ctx: _Ctx,
) -> list[WorkItem]:
    archetype = _archetype(ctx, scope.function, archetype_key)
    assert archetype is not None
    role = archetype["role"]
    phase = _phase_for(_type_for_function(scope.function), archetype_key)

    items: list[WorkItem] = []
    for i in range(1, n_batches + 1):
        remainder = min(unit_size, scope.quantity - (i - 1) * unit_size) if scope.quantity else unit_size
        title = f"{_pretty(archetype_key)} — batch {i}/{n_batches} ({remainder} {scope.unit})"
        description = (
            f"Batch {i} of {n_batches} for scope item '{scope.title}'. "
            f"Covers up to {remainder} {scope.unit}. "
            f"Total scope: {scope.quantity} {scope.unit}."
        )
        assignee, squad = _assign(ctx, role, scope.module)
        items.append(
            WorkItem(
                id=_next_id(ctx, scope.function),
                type=_type_for_function(scope.function),
                function=scope.function,
                title=title,
                description=description,
                acceptance_criteria=[
                    f"All {remainder} {scope.unit} in this batch onboarded successfully.",
                    "Batch sign-off recorded in the ops portal.",
                ],
                gherkin=None,
                squad=squad,
                assignee=assignee,
                estimate_days=float(archetype["base_days"]),
                depends_on=[],
                phase=phase,
                source_clause_id=scope.source_clause_id,
                source_excerpt=scope.source_excerpt,
                confidence=scope.confidence,
            )
        )
    return items


def _type_for_function(function: str) -> WorkItemType:
    return {
        "technical": "user_story",
        "commercial": "commercial_task",
        "operations": "ops_task",
        "design": "design_task",
    }[function]


def _pretty(key: str) -> str:
    return key.replace("_", " ").title()


# ---------------------------------------------------------------------------
# LLM path
# ---------------------------------------------------------------------------

def _llm_call(scope: ScopeItem, ctx: _Ctx) -> LLMDecomposition | None:
    """One LLM decompose call. Thread-safe — reads ctx, never mutates it.

    Materialization into WorkItems (which assigns ids and round-robins
    assignees) happens back in `decompose()` on the main thread so those
    counters stay deterministic.
    """
    prompt = _PROMPT_PATHS[scope.function].read_text(encoding="utf-8")
    user_msg = (
        f"Scope item: {scope.id}\n"
        f"Function: {scope.function}\n"
        f"Module: {scope.module or '(none)'}\n"
        f"Quantity: {scope.quantity or '(n/a)'} {scope.unit or ''}\n"
        f"\n"
        f"Title: {scope.title}\n"
        f"Description: {scope.description}\n"
        f"\n"
        f"Source clause ({scope.source_clause_id}): {scope.source_excerpt}\n"
    )
    response = ctx.client.chat.completions.parse(
        model=ctx.model,
        messages=[
            {"role": "system", "content": prompt},
            {"role": "user", "content": user_msg},
        ],
        response_format=LLMDecomposition,
        temperature=0,
    )
    return response.choices[0].message.parsed


def _lift(llm_item: LLMWorkItem, scope: ScopeItem, ctx: _Ctx) -> WorkItem:
    """Turn an LLMWorkItem into a full WorkItem by filling in the fields the
    LLM is not allowed to touch."""
    archetype = _archetype(ctx, scope.function, llm_item.archetype_key)
    if archetype is None:
        # Master plan §9 Phase 3: unknown archetype → confidence: low, do not improvise.
        estimate_days = 1.0
        role = "Tech Lead"  # safe default
        confidence: Literal["high", "medium", "low"] = "low"
    else:
        estimate_days = float(archetype["base_days"])
        role = archetype["role"]
        confidence = llm_item.confidence
    assignee, squad = _assign(ctx, role, scope.module)
    phase = _phase_for(llm_item.type, llm_item.archetype_key)
    return WorkItem(
        id=_next_id(ctx, scope.function),
        type=llm_item.type,
        function=scope.function,
        title=llm_item.title,
        description=llm_item.description,
        acceptance_criteria=llm_item.acceptance_criteria,
        gherkin=llm_item.gherkin,
        squad=squad,
        assignee=assignee,
        estimate_days=estimate_days,
        depends_on=[],  # intra-scope deps applied post-hoc
        phase=phase,
        source_clause_id=scope.source_clause_id,
        source_excerpt=scope.source_excerpt,
        confidence=confidence,
    )


# ---------------------------------------------------------------------------
# Dependency wiring
# ---------------------------------------------------------------------------

def _apply_intra_scope_dependencies(items: list[WorkItem], ctx: _Ctx) -> None:
    """Apply `dependency_rules` from task_templates.yaml as edges among
    siblings (items from the same scope item).

    Grouping key: (source_clause_id, function). A rule like
    `test_case depends_on user_story` adds every test_case's depends_on to
    include every sibling user_story id.
    """
    groups: dict[tuple[str, str], list[WorkItem]] = defaultdict(list)
    for it in items:
        groups[(it.source_clause_id, it.function)].append(it)

    for (_clause, function), group in groups.items():
        rules = ctx.templates.get(function, {}).get("dependency_rules", [])
        for rule in rules:
            src_key = rule["from"]
            dep_keys = rule["depends_on"]
            for src_item in group:
                if src_item.type != src_key and _archetype_key_of(src_item) != src_key:
                    continue
                for dep_key in dep_keys:
                    dep_ids = [
                        d.id
                        for d in group
                        if d.type == dep_key or _archetype_key_of(d) == dep_key
                    ]
                    for did in dep_ids:
                        if did != src_item.id and did not in src_item.depends_on:
                            src_item.depends_on.append(did)


def _archetype_key_of(item: WorkItem) -> str | None:
    """Reverse-lookup: try to figure out what archetype an item came from
    based on estimate_days + function. This is a best-effort helper for
    matching rules keyed by archetype (e.g. `merchant_training_wave`)."""
    # For fan-out items, we included the archetype key in the title in
    # Pretty Case; recover the snake_case key from it.
    prefix = item.title.split(" — ")[0]
    return prefix.replace(" ", "_").lower()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def decompose(extraction: SOWExtraction) -> list[WorkItem]:
    """Two-phase: fire LLM calls in parallel, then materialize in scope order.

    Phase 1 (parallel): for every scope item that isn't a fan-out candidate,
    fire its LLM decompose call on a worker thread. `_llm_call` is
    thread-safe — it reads ctx but never mutates it.

    Phase 2 (sequential, in scope order): walk the scope items in order and
    materialize into WorkItems. This is where ids (`T-TECH-001`, …) and
    round-robin assignees are stamped, so the ordering must be deterministic
    — hence "sequential on the main thread."

    Result: on a 15-scope SOW, decompose drops from ~90s (sequential) to
    ~10s (parallel), with byte-identical output.
    """
    ctx = _load_ctx()

    # Phase 1 — fan out LLM calls concurrently.
    llm_indexes = [
        i for i, s in enumerate(extraction.scope_items)
        if not _has_fanout_rule(s, ctx)
    ]
    llm_results: dict[int, LLMDecomposition | None] = {}
    if llm_indexes:
        with ThreadPoolExecutor(max_workers=8) as pool:
            futures = {
                i: pool.submit(_llm_call, extraction.scope_items[i], ctx)
                for i in llm_indexes
            }
            for i, fut in futures.items():
                llm_results[i] = fut.result()

    # Phase 2 — materialize in original scope order so id/assignment stays
    # deterministic across runs.
    items: list[WorkItem] = []
    for i, scope in enumerate(extraction.scope_items):
        if i in llm_results:
            parsed = llm_results[i]
            if parsed is not None:
                items.extend(_lift(li, scope, ctx) for li in parsed.items)
        else:
            fanout = _resolve_fanout(scope, ctx)
            if fanout is not None:
                items.extend(fanout)

    _apply_intra_scope_dependencies(items, ctx)
    return items


# ---------------------------------------------------------------------------
# Demo
# ---------------------------------------------------------------------------

def _demo() -> None:
    import json
    import sys

    src_path = (
        Path(sys.argv[1]) if len(sys.argv) > 1
        else Path("data/runs/SOW-2026-014-v1-extraction.json")
    )
    extraction = SOWExtraction.model_validate_json(src_path.read_text())
    print(f"decomposing {src_path.name} ({len(extraction.scope_items)} scope items) …")
    items = decompose(extraction)

    by_func: dict[str, int] = defaultdict(int)
    for it in items:
        by_func[it.function] += 1
    print(f"\n=== decomposition ===")
    print(f"total work items: {len(items)}")
    for f, n in by_func.items():
        print(f"  {f:12} {n}")

    # Persist
    out_path = Path("data/runs") / src_path.name.replace(
        "-extraction.json", "-workitems.json"
    )
    out_path.write_text(
        json.dumps([it.model_dump(mode="json") for it in items], indent=2)
    )
    print(f"\nwrote {out_path}")


if __name__ == "__main__":
    _demo()
