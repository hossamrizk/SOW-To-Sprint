# sow-to-sprint

**Turn a signed Scope of Work into a fully populated, scheduled, multi-team
project board — with a human approval gate and full traceability back to
the contract.**

Built as the demo for Dsquares' AI Transformation Specialist evaluation.

---

## The problem

Today, when Dsquares signs a deal, the Project Manager spends **days** breaking
the SOW into work — reading the contract, splitting scope across four functions
(technical / commercial / operations / design), opening Jira and Asana,
creating epics, user stories, test cases, acquisition targets, POS setup tasks,
merchant training waves, wireframes, then building the delivery timeline
back-scheduled from the contracted go-live date.

**The bottleneck is not the delivery work. It's the decomposition and the
data entry.** That's what this tool automates — with a firm rule that
nothing gets written to any downstream tool until the PM has approved it.

---

## What it does

```
                    ┌──── SOW.docx ────┐
                    │                   ▼
    (1) INGEST      →  clause-indexed text, stable C-xxx ids
                    ▼
    (2) EXTRACT     →  SOWExtraction  (LLM, strict JSON schema)
                    ▼
    (3) DECOMPOSE   →  WorkItem[]     (LLM writes titles; code fans out + assigns)
                    ▼
    (4) SCHEDULE    →  dated WorkItems + critical path + over-commit warnings
                    ▼
    (5) REVIEW GATE →  Streamlit UI — PM approves / edits / rejects
                    ▼
    (6) TRELLO SYNC →  boards per function, idempotent re-runs
                    ▼
    (7) CR DIFF     →  v2 SOW → diff report → apply to Trello (no duplicates)
```

Six stages of pipeline; the fifth is the human. Nothing writes to Trello
without PM approval.

---

## Quickstart

```bash
# 1. install deps
pip install -r requirements.txt

# 2. set env — a `.env` in this dir or any parent is auto-discovered
#    (the demo keeps it one level up in Dsquares/.env)
# required:  OPENAI_API_KEY
# optional:  TRELLO_API_KEY, TRELLO_API_TOKEN (Phase 6/7 only)
# optional:  OPENAI_MODEL (defaults to gpt-4o-mini)

# 3. (optional) regenerate the sample SOWs
python3 scripts/generate_sows.py

# 4. run individual stages from the CLI (each also runs a smoke test)
python3 -m src.ingest       # DOCX → clauses
python3 -m src.extract      # → SOWExtraction (calls OpenAI)
python3 -m src.decompose    # → WorkItem[] (calls OpenAI, ~1–2 min)
python3 -m src.schedule     # → dated WorkItems + report

# 5. run the review UI
streamlit run app.py

# 6. run the tests
python3 -m pytest tests/ -v
```

The Streamlit UI auto-seeds the SQLite store from the JSON runs already in
`data/runs/` on first launch, so v1 and v2 are inspectable immediately.

---

## Repository layout

```
sow-to-sprint/
├── README.md
├── requirements.txt
├── metrics.md                 ← ROI framing + assumptions register
├── app.py                     ← Streamlit review gate (Phase 5)
├── scripts/
│   ├── generate_sows.py       ← one-shot DOCX generator for the demo SOWs
│   ├── inspect_ingest.py      ← dump parsed clauses for a SOW
│   └── inspect_dag.py         ← visualise the scheduled DAG
├── src/
│   ├── models.py              ← Pydantic schemas — the contracts
│   ├── config.py              ← settings loader (env + .env)
│   ├── ingest.py              ← DOCX → clauses
│   ├── extract.py             ← LLM → SOWExtraction
│   ├── decompose.py           ← ScopeItem → WorkItem[]
│   ├── schedule.py            ← DAG + back-schedule + critical path
│   ├── store.py               ← SQLite persistence
│   ├── pipeline.py            ← orchestrator (stages 1–4)
│   ├── trello_client.py       ← thin REST wrapper
│   ├── sync.py                ← idempotent push (Phase 6) + CR apply (Phase 7)
│   ├── diff.py                ← structural v1 vs v2 diff (Phase 7)
│   ├── settings_ui.py         ← in-app YAML config editor (Settings tab)
│   ├── ui_theme.py            ← Streamlit CSS + component helpers
│   └── prompts/               ← LLM prompts (one per stage / function)
├── data/
│   ├── sow/                   ← sample DOCX files (v1 + v2)
│   ├── config/                ← estimation library, teams, calendar, task templates
│   └── runs/                  ← persisted extractions, work items, SQLite store
├── tests/                     ← 18 tests (schedule / sync / diff)
└── docs/                      ← phase-by-phase walkthroughs (interview defence)
```

---

## The design in one paragraph

**The LLM does classification and language, not arithmetic.** Estimates come
from a versioned YAML library of task archetypes. Dependencies come from
another YAML. The schedule is back-computed by code over a working calendar
that respects Egyptian weekends and holidays. The LLM only maps messy
contract prose onto the right archetype and writes readable task text — the
one thing templates cannot do well. Every generated task carries the
verbatim SOW clause it came from; anything the model cannot ground goes to
a separate `unmapped_clauses` list, not silently dropped. A human approves
before anything is written outside our system. That approval-gate + trace
combination is what makes the tool adoptable rather than threatening.

---

## What's assumed vs what's real

- The estimation library values are plausible for loyalty-program delivery,
  not calibrated on Dsquares' actual historicals.
- The org chart in `teams.yaml` is invented.
- Islamic-calendar holiday dates are the widely-published 2026 Egyptian
  observed dates (can shift ±1 day on moon-sighting).
- The SOW format assumes numbered sections and sub-clauses. Real Dsquares
  SOWs may need a tailored parser.

None of these affect the *design* of the pipeline — only the *values*
inside the deterministic layers. Calibrating them is the first-week task
against real data.

---

## What's deliberately out of scope

Same list from the master plan (§2):

- Real Jira / Asana connectors (Trello is the free stand-in; the sync layer
  is written against a work-item abstraction — Jira is another adapter,
  not a rewrite).
- Auth, multi-tenancy, RBAC.
- Ongoing status collection and reporting (Phase 2 of the product roadmap).
- Resource levelling / capacity planning across concurrent projects.
- Learning estimates from historical actuals — needs their data.

---

## Tech stack

- Python 3.11+
- OpenAI Chat Completions API with strict JSON schema (`gpt-4o-mini` by
  default; any `≥ 2024-08-06` snapshot works)
- Pydantic v2 for every schema at every stage boundary
- `python-docx` for parsing
- `networkx` for the DAG + critical path
- SQLite for persistence
- Streamlit for the review UI
- `requests` for the Trello REST API

Full list in `requirements.txt`.
