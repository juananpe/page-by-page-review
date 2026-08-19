# Upload and review a PDF

Upload and review lets a user choose or drop a PDF, see pages render immediately, receive streamed per-page mock findings, retry a page, and reject unsupported input without contacting a model service.

## Sub-features

- `upload-chooser` uploads the generated PDF through the file chooser.
- `upload-drop` uploads a PDF by dropping it on the labelled drop zone.
- `upload-invalid` rejects a non-PDF before sending it.
- `review-stream` fills the page index and review panel as mock results arrive.
- `review-reread` re-runs the selected page through the visible `Re-read page` action.

## How to get to it (user POV)

- Choose `Drop a PDF here, or click to choose` and select a PDF.
- Drop a PDF on the same upload area.
- After review, choose `Re-read page` in the right-hand result panel.

## Driving it with Browser

Preconditions:

- Doctor passes and the upload gate reports provider/model `mock`.
- `$VERIFY_RUN_DIR/scratch/verification-paper.pdf` exists.
- The verifier-owned Browser tab is on the app root.

- **Capture the action state.** Save `before-upload.png`. Require the heading `Read a paper one page at a time.` and text `mock · mock`.
- **Open the chooser.** Use one `Promise.all` that starts `tab.playwright.waitForEvent("filechooser")` and clicks visible text `Drop a PDF here, or click to choose` with `{ exact: true }`; take the chooser from the first result and set it to the absolute fixture path. This proves the user-visible chooser entry point without clicking the hidden input.
- **Observe upload.** Require the upload gate to hide, brand `verification-paper.pdf` to appear, and image alt `Page 1 of verification-paper.pdf` to become visible.
- **Observe streamed completion.** Wait for text `Mock review of page 1`, `Mock review of page 2`, enabled `Report .md` and `.json` buttons, and a visible `Across pages` button. The tally reports two analysed pages and the page index contains two rows.
- **Confirm server state.** Read `#sheet[src]`, extract the document ID, and fetch `/api/documents/<id>/results.json` plus `/report.md` into evidence. JSON has `document=verification-paper.pdf`, provider/model `mock`, two populated page results, and one cross-page finding. Page 1 has worst severity `warning`; page 2 has worst severity `note`.
- **Retry the page.** Choose `Re-read page`; require the selected page to return to `Mock review of page 1` and remain present in refreshed `results.json`.
- **Capture proof.** Save `after-upload-review.png` and `after-upload-review.dom.txt`, then record the action, visible state, document ID, and independent result paths in `proof-summary.txt`.

## Gotchas

- The file input is hidden. Use the visible upload text as the chooser target; clicking the hidden input can time out in the in-app Browser even though the user-facing label works.
- Create the chooser wait and visible click inside the same `Promise.all`. A separately stored wait can reject while another awaited browser action is still pending and reset the browser session.
- A `verification-paper.pdf` brand alone proves upload, not review completion. Wait for both page results and enabled report actions.
- The generated fixture is image-only, so `has_text_layer=false` is expected.
- For the two-page fixture, mock output contains warning/note on page 1 and note/ok on page 2; do not interpret it as a substantive review of fixture content.
- The drop entry point needs a real drag/drop operation and must be reported separately if skipped.
