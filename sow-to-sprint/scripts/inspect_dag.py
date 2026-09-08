"""Show what the DAG in schedule.py actually is, using real WorkItems.

Run:  python scripts/inspect_dag.py

Loads the saved cashback-SOW WorkItems, builds the same DAG that
schedule.py builds, and prints each thing networkx gives us:

  1. Nodes + edges (with a sample of each)
  2. Phase-boundary trick: naive O(N^2) vs actual O(N) edge count
  3. Cycle check (nx.is_directed_acyclic_graph)
  4. Topological sort (why back-scheduling works in one pass)
  5. Critical path (longest chain by estimate_days)
  6. What happens if we inject a cycle -> loud failure
"""
from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path

import networkx as nx

from src.models import WorkItem
from src.schedule import (
    _PHASE_ORDER,
    _build_dag,
    _critical_path,
    _phase_boundary_node,
)


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ITEMS = ROOT / "data" / "runs" / "SOW-2026-014-v2-workitems.json"


def load_items(path: Path) -> list[WorkItem]:
    raw = json.loads(path.read_text())
    return [WorkItem.model_validate(x) for x in raw]


def section(title: str) -> None:
    print(f"\n{'=' * 72}\n{title}\n{'=' * 72}")


def show_nodes_and_edges(g: nx.DiGraph, items: list[WorkItem]) -> None:
    section("1. NODES + EDGES")
    real = [n for n, d in g.nodes(data=True) if d.get("kind") == "workitem"]
    virtual = [n for n, d in g.nodes(data=True) if d.get("kind") == "boundary"]
    print(f"total nodes:    {g.number_of_nodes()}")
    print(f"  real tasks:   {len(real)}")
    print(f"  virtual (phase boundaries): {len(virtual)} -> {virtual}")
    print(f"total edges:    {g.number_of_edges()}")

    by_id = {it.id: it for it in items}

    print("\n-- 5 sample explicit dependency edges (Build depends on Design, etc.) --")
    shown = 0
    for u, v in g.edges():
        if g.nodes[u].get("kind") == "boundary" or g.nodes[v].get("kind") == "boundary":
            continue
        u_it, v_it = by_id[u], by_id[v]
        print(f"  {u} [{u_it.phase:>10}] {u_it.title[:45]!r:50} --> "
              f"{v} [{v_it.phase:>10}] {v_it.title[:45]!r}")
        shown += 1
        if shown >= 5:
            break

    print("\n-- 5 sample phase-gate edges (through a boundary node) --")
    shown = 0
    for u, v in g.edges():
        if g.nodes[v].get("kind") == "boundary":
            u_it = by_id[u]
            print(f"  {u} [{u_it.phase:>10}] --> {v}")
            shown += 1
            if shown >= 5:
                break


def show_phase_boundary_savings(items: list[WorkItem]) -> None:
    section("2. PHASE-BOUNDARY TRICK (O(N) vs O(N^2))")
    by_phase: dict[str, int] = defaultdict(int)
    for it in items:
        by_phase[it.phase] += 1

    print("items per phase:")
    for p in _PHASE_ORDER:
        print(f"  {p:>12}: {by_phase[p]}")

    naive_edges = 0
    smart_edges = 0
    for i, p in enumerate(_PHASE_ORDER[:-1]):
        n = _PHASE_ORDER[i + 1]
        if by_phase[p] and by_phase[n]:
            naive_edges += by_phase[p] * by_phase[n]
            smart_edges += by_phase[p] + by_phase[n]

    print(f"\nnaive all-pairs edges: {naive_edges}")
    print(f"boundary-node edges:   {smart_edges}")
    print(f"savings: {naive_edges - smart_edges} edges "
          f"({(1 - smart_edges / naive_edges) * 100:.0f}% fewer)")
    print("\nsame semantic guarantee: every Build task depends on 'end_of_Discovery',")
    print("which depends on every Discovery task. Fewer edges, same math.")


def show_acyclic_check(g: nx.DiGraph) -> None:
    section("3. IS IT ACYCLIC?")
    is_dag = nx.is_directed_acyclic_graph(g)
    print(f"nx.is_directed_acyclic_graph(g) -> {is_dag}")
    if is_dag:
        print("no cycles found -> safe to schedule.")
    else:
        cycle = next(iter(nx.simple_cycles(g)), None)
        print(f"CYCLE DETECTED: {cycle}")


def show_topological_sort(g: nx.DiGraph, items: list[WorkItem]) -> None:
    section("4. TOPOLOGICAL SORT")
    print("guarantee: every node appears AFTER all its dependencies.")
    print("this is what lets back-scheduling work in ONE pass in reverse order.\n")

    order = list(nx.topological_sort(g))
    by_id = {it.id: it for it in items}

    print(f"first 5 in topo order (sources — nothing depends on them upstream):")
    for n in order[:5]:
        kind = g.nodes[n].get("kind", "?")
        if kind == "workitem":
            it = by_id[n]
            print(f"  {n} [{it.phase:>10}] {it.title[:60]}")
        else:
            print(f"  {n} (virtual boundary)")

    print(f"\nlast 5 in topo order (sinks — nothing depends on them downstream):")
    for n in order[-5:]:
        kind = g.nodes[n].get("kind", "?")
        if kind == "workitem":
            it = by_id[n]
            print(f"  {n} [{it.phase:>10}] {it.title[:60]}")
        else:
            print(f"  {n} (virtual boundary)")


def show_critical_path(g: nx.DiGraph, items: list[WorkItem]) -> None:
    section("5. CRITICAL PATH (longest chain by estimate_days)")
    print("if any task on this path slips by 1 day, the whole project slips 1 day.")
    print("everything NOT on it has slack.\n")
    path, total = _critical_path(g, items)
    by_id = {it.id: it for it in items}
    print(f"critical path length: {total:.1f} working days across {len(path)} tasks\n")
    for i, wid in enumerate(path[:15], 1):
        it = by_id[wid]
        print(f"  {i:2}. {wid} [{it.phase:>10}] ({it.estimate_days:>4} d) {it.title[:55]}")
    if len(path) > 15:
        print(f"     ... and {len(path) - 15} more")


def show_cycle_injection(items: list[WorkItem]) -> None:
    section("6. WHAT IF WE INJECT A CYCLE?")
    print("simulating a bug: add A -> B AND B -> A between two real items.")
    if len(items) < 2:
        print("(not enough items to demo)")
        return
    a, b = items[0].id, items[1].id
    g = _build_dag(items)
    g.add_edge(a, b)
    g.add_edge(b, a)
    is_dag = nx.is_directed_acyclic_graph(g)
    print(f"injected: {a} <-> {b}")
    print(f"nx.is_directed_acyclic_graph(g) -> {is_dag}")
    if not is_dag:
        cycle = next(iter(nx.simple_cycles(g)))
        print(f"nx.simple_cycles picks it up: {cycle}")
        print("\nthis is what triggers schedule.py's _assert_dag() to raise loudly")
        print("instead of silently producing garbage dates.")


def main() -> None:
    items = load_items(DEFAULT_ITEMS)
    print(f"loaded {len(items)} WorkItems from {DEFAULT_ITEMS.name}")
    g = _build_dag(items)

    show_nodes_and_edges(g, items)
    show_phase_boundary_savings(items)
    show_acyclic_check(g)
    show_topological_sort(g, items)
    show_critical_path(g, items)
    show_cycle_injection(items)


if __name__ == "__main__":
    main()
