# Approach Notes

## Data model
- `versions`: each imported PDF version is immutable by label (`v1`, `v2`).
- `nodes`: one row per inferred section, keyed by version plus logical key; stores heading, section number, body, parent number, and SHA-256 content hash.
- `selections`: stores node IDs, version ID, source text snapshot, and snapshot hash so old selections remain reproducible.
- `generated_tests`: stores structured output and the source hash used at generation time.

## Parser decisions and irregularities
The parser uses PyMuPDF text extraction and recognizes numbered heading lines with a regular expression. It preserves original section numbers instead of forcing sequential order. The supplied v1 manual includes `2.1.1.1 Battery Life Under Typical Use` and section 3.4 appears before 3.3; these are retained. The v2 manual adds section 5.3 Data Export and error code E6. Text from tables is retained in a flattened form, but cell structure is not modeled.

## Matching strategy and failure modes
A logical key combines the section number and normalized heading. Exact matches make changed-body detection simple using SHA-256. This strategy can miss identity when a section is renamed or renumbered, and repeated headings can be ambiguous. A future version could combine parent path, heading similarity, and body similarity, with an explicit ambiguous-match status rather than guessing.

## Prompt and output validation
When `OPENAI_API_KEY` is set, the API asks the configured model for JSON containing 3–5 test cases with title, preconditions, steps, expected result, and source excerpt. The response is parsed and checked for a list of 3–5 objects with required fields. Invalid output or API errors use a clearly labelled template fallback; fallback results are not claimed to be model-generated. Duplicate generation returns an existing record for the same selection/source hash unless forced.

## Staleness and limits
The selection stores its original text snapshot and hash. Retrieval compares that hash with the current version's matched source text. Missing nodes are considered stale. This is content-based impact detection only; it cannot tell whether a textual change is clinically significant or whether a generated test remains adequate.

## Required decision log
1. **Most likely silent wrong result:** PDF reading order can flatten or reorder table rows, causing a numeric value to be associated with the wrong parameter. Detection: inspect extracted output and add document-specific assertions around important table values; a production parser should preserve coordinates and table structure.
2. **Simplicity over correctness:** numbered-heading regex instead of visual layout analysis. In production, scanned or irregularly formatted PDFs would fail first.
3. **Unsupported input:** image-only scanned PDFs. Current behavior is text extraction only; no OCR is performed, so extraction may be empty/incomplete and should be reviewed rather than trusted.

## Improvements with more time
Use layout-aware hierarchy and table extraction, add OCR for scanned pages, support fuzzy matching with ambiguity review, validate generated outputs with stronger Pydantic models, use a dedicated document store if scale requires it, and add broader API integration tests.
