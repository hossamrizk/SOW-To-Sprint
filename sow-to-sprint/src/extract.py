import re
from datetime import date, datetime
from pathlib import Path

from openai import OpenAI
from pydantic import ValidationError

from src.config import get_settings
from src.ingest import IngestedDoc
from src.models import SOWExtraction


# Cover-page metadata is usually one line like "Signature Date: 12 January 2026".
# The LLM occasionally mangles these into ISO format ("1201-06-26"). Regex-parse
# them ourselves as a deterministic fallback for the two most-cited fields.
_SIGNATURE_RE = re.compile(
    r"Signature\s*Date[:\s]+([0-9]{1,2}\s+[A-Za-z]+\s+[0-9]{4})",
    re.IGNORECASE,
)
_GO_LIVE_RE = re.compile(
    r"Go[-\s]?Live\s*Date[:\s]+([0-9]{1,2}\s+[A-Za-z]+\s+[0-9]{4})",
    re.IGNORECASE,
)


def _parse_cover_date(text: str, pattern: re.Pattern[str]) -> date | None:
    """Return the first '12 January 2026' style date matched by `pattern`."""
    m = pattern.search(text)
    if not m:
        return None
    for fmt in ("%d %B %Y", "%d %b %Y"):
        try:
            return datetime.strptime(m.group(1).strip(), fmt).date()
        except ValueError:
            continue
    return None


def _date_appears_in(d: date, text: str) -> bool:
    """True if `d` appears as a substring in `text` in any common format —
    ISO, `dd Month yyyy`, `Month dd, yyyy`, or `dd/mm/yyyy` / `mm/dd/yyyy`.
    Case-insensitive. Used to gate LLM-returned dates: if the model returns a
    date, we only trust it when the source text actually contains it."""
    hay = text.lower()
    formats = (
        d.isoformat(),                              # 2026-01-12
        d.strftime("%d %B %Y"),                     # 12 January 2026
        d.strftime("%d %b %Y"),                     # 12 Jan 2026
        d.strftime("%B %d, %Y"),                    # January 12, 2026
        d.strftime("%b %d, %Y"),                    # Jan 12, 2026
        d.strftime("%d/%m/%Y"),                     # 12/01/2026
        d.strftime("%m/%d/%Y"),                     # 01/12/2026
        d.strftime("%d-%m-%Y"),                     # 12-01-2026
    )
    # Also strip leading zeros (e.g. "1 January 2026")
    formats += tuple(f.lstrip("0").replace(" 0", " ") for f in formats)
    return any(f.lower() in hay for f in formats)


_PROMPT_PATH = Path(__file__).parent / "prompts" / "extract_sow.md"


def _load_prompt() -> str:
    return _PROMPT_PATH.read_text(encoding="utf-8")


def _validate_business_rules(
    extraction: SOWExtraction, ingested: IngestedDoc
) -> None:
    """Enforce checks that are not expressible in JSON schema alone."""
    known_ids = {c.id for c in ingested.clauses}

    unknown = [
        s.source_clause_id
        for s in extraction.scope_items
        if s.source_clause_id not in known_ids
    ]
    if unknown:
        raise ValueError(
            f"scope items cite unknown clause ids: {sorted(set(unknown))[:5]}"
        )

    unknown_unmapped = [
        c for c in extraction.unmapped_clauses if c not in known_ids
    ]
    if unknown_unmapped:
        raise ValueError(
            f"unmapped_clauses references unknown clause ids: {unknown_unmapped[:5]}"
        )

    # Regex is the source of truth for signature_date. The cover page is
    # deterministic — if we can parse it, that answer wins over anything the
    # LLM said. If the cover page is silent, the LLM's value is only trusted
    # when the date appears verbatim in the source text (same rule as
    # source_excerpt above). Otherwise we return None honestly.
    regex_date = _parse_cover_date(ingested.annotated_text, _SIGNATURE_RE)
    if regex_date is not None:
        extraction.signature_date = regex_date
    elif extraction.signature_date is not None and not _date_appears_in(
        extraction.signature_date, ingested.annotated_text
    ):
        extraction.signature_date = None

    if extraction.signature_date is not None and extraction.delivery_date <= extraction.signature_date:
        raise ValueError(
            f"delivery_date {extraction.delivery_date} must be after "
            f"signature_date {extraction.signature_date}"
        )


def extract_sow(ingested: IngestedDoc, *, max_retries: int = 1) -> SOWExtraction:
    """Run the extraction stage.

    Parameters
    ----------
    ingested:
        Output of `src.ingest.ingest_docx`.
    max_retries:
        Number of retry attempts on validation failure (default 1 — i.e. up
        to 2 API calls total).
    """
    settings = get_settings()
    client = OpenAI(api_key=settings.openai_api_key)

    input_text = ingested.annotated_text
    if len(input_text) > settings.max_input_chars:
        raise ValueError(
            f"SOW text ({len(input_text)} chars) exceeds "
            f"max_input_chars={settings.max_input_chars}. Chunking not yet "
            "implemented — reduce document or raise the cap."
        )

    messages: list[dict] = [
        {"role": "system", "content": _load_prompt()},
        {
            "role": "user",
            "content": (
                "The following is the full SOW document. Clause markers of "
                "the form [C-001] identify each numbered sub-clause. When "
                "citing `source_clause_id`, use these markers verbatim.\n\n"
                + input_text
            ),
        },
    ]

    last_error: Exception | None = None
    for attempt in range(max_retries + 1):
        try:
            response = client.chat.completions.parse(
                model=settings.openai_model,
                messages=messages,
                response_format=SOWExtraction,
                temperature=0,
            )
            choice = response.choices[0].message
            if choice.refusal:
                raise ValueError(f"model refused: {choice.refusal}")
            extraction: SOWExtraction | None = choice.parsed
            if extraction is None:
                raise ValueError("model returned no parsed output")

            _validate_business_rules(extraction, ingested)
            return extraction

        except (ValidationError, ValueError) as e:
            last_error = e
            if attempt >= max_retries:
                raise
            messages.append(
                {
                    "role": "assistant",
                    "content": "(previous response failed validation)",
                }
            )
            messages.append(
                {
                    "role": "user",
                    "content": (
                        f"Your previous response failed validation: {e}\n\n"
                        "Please correct the issue and return the full "
                        "SOWExtraction again."
                    ),
                }
            )

    # Unreachable — the for-loop either returns or re-raises.
    raise last_error  # type: ignore[misc]


def _demo() -> None:
    """Manual smoke test. Run: python3 -m src.extract [path_to_sow.docx]"""
    import json
    import sys

    from src.ingest import ingest_docx

    default = Path("data/sow/SOW-2026-014-nbe-loyalty-v1.docx")
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else default

    print(f"ingesting {target} …")
    ingested = ingest_docx(target)
    print(f"clauses: {len(ingested.clauses)}")

    print("extracting via OpenAI …")
    result = extract_sow(ingested)

    print(f"\n=== SOWExtraction ===")
    print(f"sow_id:           {result.sow_id}")
    print(f"version:          {result.version}")
    print(f"client:           {result.client_name}")
    print(f"project:          {result.project_name}")
    print(f"signature_date:   {result.signature_date}")
    print(f"delivery_date:    {result.delivery_date}")
    print(f"modules:          {result.modules}")
    print(f"scope_items:      {len(result.scope_items)}")
    print(f"commercial:       {len(result.commercial_targets)}")
    print(f"out_of_scope:     {len(result.out_of_scope)} entries")
    print(f"milestones:       {len(result.milestones)}")
    print(f"slas:             {len(result.slas)}")
    print(f"acceptance:       {len(result.acceptance_criteria)}")
    print(f"unmapped_clauses: {result.unmapped_clauses}")

    # Persist the run for later stages
    runs_dir = Path("data/runs")
    runs_dir.mkdir(parents=True, exist_ok=True)
    out_path = runs_dir / f"{result.sow_id}-v{result.version}-extraction.json"
    out_path.write_text(result.model_dump_json(indent=2))
    print(f"\nwrote {out_path}")


if __name__ == "__main__":
    _demo()
