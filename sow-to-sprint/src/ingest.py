import re
from dataclasses import dataclass
from pathlib import Path

from docx import Document
from docx.oxml.ns import qn
from docx.table import Table
from docx.text.paragraph import Paragraph

from src.models import Clause


# Match a top-level section heading: "1. Points Engine", "11. Out of Scope".
_SECTION_RE = re.compile(r"^(\d+)\.\s+(.+)$")
# Match a numbered sub-clause at any depth: "1.1 …", "10.3 …", "2.1.1 …",
# "4.3.2.1 …". Every sub-numbered item becomes its own citable clause so
# `T-TECH-001` can trace to `C-014` (which is precisely `2.1.1 Offers Engine`)
# rather than the coarser `C-008` (`2.1 Technical Deliverables`).
_CLAUSE_RE = re.compile(r"^(\d+(?:\.\d+)+)\s+.+$")
# Match an appendix clause: "A.1 …", "B.3 …".
_APPENDIX_RE = re.compile(r"^([A-Z]\.\d+)\s+.+$")


@dataclass
class IngestedDoc:
    source_file: str
    clauses: list[Clause]
    annotated_text: str


def _iter_block_items(doc):
    """Yield paragraphs and tables in document order.

    python-docx exposes them as separate collections; iterating the XML
    body directly is the way to keep contract order intact so section
    context stays correct when a table appears mid-document.
    """
    body = doc.element.body
    for child in body.iterchildren():
        if child.tag == qn("w:p"):
            yield Paragraph(child, doc)
        elif child.tag == qn("w:tbl"):
            yield Table(child, doc)


def _flatten_table(table: Table) -> list[str]:
    """Return one string per row: cell-separated by ' | '.

    Empty rows and header rows (all-caps or bold-only) are still emitted so
    the LLM sees the column headers as context.
    """
    rows: list[str] = []
    for row in table.rows:
        cells = [c.text.strip().replace("\n", " ") for c in row.cells]
        cells = [c for c in cells if c]
        if cells:
            rows.append(" | ".join(cells))
    return rows


def ingest_docx(path: str | Path) -> IngestedDoc:
    """Parse a SOW DOCX into clause-indexed form.

    Walks paragraphs *and* tables in document order so table content
    (milestones, timeline grids, commercial matrices) becomes citable —
    each table row gets its own `C-xxx` clause id.
    """
    path = Path(path)
    doc = Document(path)

    clauses: list[Clause] = []
    lines: list[str] = []
    current_section: str = "(preamble)"
    clause_counter = 0

    def _emit_clause(text: str) -> None:
        nonlocal clause_counter
        clause_counter += 1
        clause_id = f"C-{clause_counter:03d}"
        clauses.append(
            Clause(id=clause_id, section=current_section, text=text)
        )
        lines.append(f"[{clause_id}] {text}")

    for block in _iter_block_items(doc):
        if isinstance(block, Paragraph):
            text = block.text.strip()
            if not text:
                continue

            m_section = _SECTION_RE.match(text)
            if m_section:
                current_section = text
                lines.append(f"\n### {text}")
                continue

            if _CLAUSE_RE.match(text) or _APPENDIX_RE.match(text):
                _emit_clause(text)
                continue

            # Intro prose or cover text — preserved but not a clause.
            lines.append(text)

        elif isinstance(block, Table):
            lines.append(f"\n[table under: {current_section}]")
            for row_text in _flatten_table(block):
                # Every table row becomes its own citable clause so the
                # extractor can reference specific rows (e.g. milestones).
                _emit_clause(row_text)

    return IngestedDoc(
        source_file=str(path),
        clauses=clauses,
        annotated_text="\n".join(lines),
    )


def _demo() -> None:
    """Manual smoke test. Run: python3 -m src.ingest"""
    import sys

    default = Path("data/sow/SOW-2026-014-nbe-loyalty-v1.docx")
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else default
    result = ingest_docx(target)
    print(f"source: {result.source_file}")
    print(f"clauses extracted: {len(result.clauses)}")
    print("first 3 clauses:")
    for c in result.clauses[:3]:
        print(f"  {c.id}  [{c.section}]  {c.text[:80]}…")
    print("annotated text preview:")
    print(result.annotated_text[:400])


if __name__ == "__main__":
    _demo()
