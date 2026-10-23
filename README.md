# Tri9T AI Internship Assignment — Manual Versioning API (MVP)

A time-boxed FastAPI implementation for importing two versions of a PDF manual, browsing/searching sections, comparing versions, pinning selections to a version, generating test ideas, and reporting staleness.

## Features
- PDF text extraction with PyMuPDF; section headings are recognized by numbering patterns.
- SQLite persistence through SQLAlchemy for versions, nodes, selections, and generated results.
- Browse top-level sections, fetch nodes, search, and compare versions.
- Selection snapshots preserve the exact text and version selected.
- LLM test idea generation using `OPENAI_API_KEY`; if no key is configured or the response is invalid, a clearly labelled template fallback keeps the demo runnable.
- Staleness is determined by comparing the pinned source hash with the matching logical sections in the latest version.
- Duplicate generation requests return the existing output for the same selection/source hash unless `force=true`.

## Setup
```bash
python -m venv .venv
# Windows PowerShell: .venv\Scripts\Activate.ps1
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
```
Copy `ct200_manual.pdf` and `ct200_manual_v2.pdf` into this directory, or supply absolute paths to `seed.py`.

```bash
python seed.py
uvicorn app:app --reload
```
Open http://127.0.0.1:8000/docs.

To enable LLM generation, set `OPENAI_API_KEY` in the environment before starting the server. Optionally set `OPENAI_MODEL` (default `gpt-4o-mini`). Do not commit API keys.

## Demo flow
1. `GET /versions`
2. `GET /sections?version=v1`
3. `GET /compare?from_version=v1&to_version=v2`
4. `GET /search?q=Battery&version=v2`
5. `POST /selections` with a node ID returned from the desired version:
```json
{"name":"Battery section v1","version":"v1","node_ids":[1]}
```
6. `POST /selections/{selection_id}/generate`
7. `GET /generated/{generated_id}` to inspect staleness.

For a selection request, use the real node IDs returned by `/sections`; the sample ID above is illustrative only.

## Tests
```bash
pytest -q
```

## Approach and limitations
- **Matching:** logical keys use the section number and normalized heading. This is explainable and fast, but renumbered or renamed sections may appear as remove/add. No fuzzy matching is claimed.
- **Parsing:** PDF text is extracted in reading order and headings are inferred from numbered lines. This is not a general-purpose layout parser. Complex multi-column pages, image-only scans, table cell structure, and figure/caption relationships are not fully modeled; table text may be flattened.
- **Silent-error risk:** a body line could be mistaken for a heading or a PDF's reading order could scramble a table. The parser tests include deep numbering, out-of-order numbering, new sections, and changed text. Inspect extracted nodes for any production use.
- **Shortcut / first production failure:** hierarchy is inferred from numbering and not visual font/layout metadata. Scanned PDFs or unusual headings would be the first likely failure.
- **Unsupported input:** image-only scanned PDFs are not OCRed. The API reports extracted text, which may be empty or incomplete; it does not claim OCR succeeded.
- **Staleness:** hash differences mean the selected source text differs, not that the test is clinically invalid. A missing logical match is conservatively marked stale.
- **Storage:** generated outputs are stored as JSON text in SQLite in this MVP rather than a separate MongoDB service, reducing setup time; this is a deliberate scope trade-off.
- **Medical safety:** generated test ideas are software QA ideas only, not medical advice or validated clinical protocols.
