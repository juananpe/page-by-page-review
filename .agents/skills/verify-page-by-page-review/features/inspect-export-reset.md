# Inspect, export, and reset

Whole-document actions let a user inspect cross-page findings, export the finished review as Markdown or JSON, and forget the current document to start again.

## Sub-features

- `cross-open` opens the across-pages panel after analysis.
- `cross-navigate` follows a referenced page and leaves the cross panel.
- `cross-escape` returns to the current page with Escape.
- `export-markdown` downloads the Markdown report.
- `export-json` downloads structured results.
- `reset-new-pdf` forgets the in-memory document and restores the upload gate.

## How to get to it (user POV)

- Choose `Across pages <count>` after review, then choose a referenced page or press Escape.
- Choose `Report .md` or `.json`.
- Choose `New PDF`.

## Driving it with Browser

Preconditions:

- The two-page mock review and cross-page pass completed.
- Report buttons and `Across pages 1` are visible.

- **Open across-pages.** Choose `Across pages 1`. Require heading `Across pages`, the mock cross-page finding, and page-reference buttons `1` and `2`.
- **Referenced-page entry.** Choose page reference `2`. Require `PAGE 2 / 2`, the page-2 image, and page-2 result panel.
- **Escape entry.** Reopen the panel, press `Escape`, and require return to the previously current page.
- **Markdown export.** Start `waitForEvent("download")`, choose `Report .md`, and require a download event. Independently fetch `/api/documents/<id>/report.md`; require the report heading, `verification-paper.pdf`, page sections, and `Mock cross-page finding`.
- **JSON export.** Start a second download wait, choose `.json`, and require a download event. Independently fetch `results.json`; require two page results and one cross-page finding.
- **Reset.** Choose `New PDF`. Require the heading `Read a paper one page at a time.`, visible file input/drop label, and hidden review app. A subsequent GET of the old results URL must return HTTP 404.
- **Capture proof.** Capture the cross panel before reset and the restored upload gate after reset. Keep both server exports in evidence.

## Gotchas

- The cross button is hidden until the cross-page pass finishes.
- Page-reference buttons are inside the cross panel and share numeric names with page rows; scope the locator to the notes panel.
- Export controls use `location.assign` with attachment responses; start the download wait before clicking.
- `New PDF` performs a best-effort DELETE and resets immediately. Confirm deletion independently with the old document URL.
- Cleanup kills the verifier-owned server only after the UI reset evidence is captured.
