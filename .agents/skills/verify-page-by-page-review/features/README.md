# Page-by-page paper review verification map

This map covers the browser-visible behavior of the local Page-by-page paper review app. Read the generated skill first, then use the matching feature recipe.

## Baseline preconditions

- Work from the repository root with the existing `.venv` intact.
- Launch a verifier-owned mock instance and require Doctor to pass.
- Use only `$VERIFY_RUN_DIR/scratch/verification-paper.pdf`; never upload a personal paper.
- Use a verifier-owned Browser tab at `http://127.0.0.1:$VERIFY_PORT/`.
- Confirm the upload gate shows provider `mock`, model `mock`, two-page fixture limits, and the app title before driving.
- Never use or stop the app already listening on port 8000.

## Driving conventions

- Prefer Browser role, label, text, and CSS locators named in each recipe; do not use coordinates.
- Start file uploads with `waitForEvent("filechooser")` and click the visible `Drop a PDF here, or click to choose` action in the same `Promise.all`; do not click the hidden file input.
- Wait for visible result state instead of fixed sleeps.
- Capture the user action and resulting state, plus an independent JSON or Markdown result when the feature has a server-side effect.
- Start every recipe from its stated preconditions. Do not claim one entry point proves another.
- Choose `New PDF` before lifecycle cleanup when a document is loaded. Preserve evidence.

## Proof and skip reporting

- Record the feature ID and exact entry point in `proof-summary.txt`.
- A screenshot must show the app identity and the state under assertion.
- A DOM snapshot must accompany the final screenshot for semantic evidence.
- Report an unreachable entry point with its attempted Browser operation and missing precondition.
- Run Doctor after surprising behavior and clean up every failed iteration.

## Feature entry contract

Every feature file uses `Sub-features`, `How to get to it (user POV)`, `Driving it with Browser`, and `Gotchas` in that order. Commands and selectors are literal unless a `$VARIABLE` is shown.

## Features

- [Upload and review a PDF](./upload-and-review.md) covers chooser/drop entry, streamed mock analysis, retry, and input validation.
- [Navigate reviewed pages](./navigate-pages.md) covers the page index, spine, previous/next controls, and keyboard navigation.
- [Filter findings](./filter-findings.md) covers All, Errors, Warnings, Minor, and keyboard cycling.
- [Zoom the paper](./zoom-paper.md) covers Fit, 100%, 150%, image-click cycling, and keyboard cycling.
- [Inspect, export, and reset](./inspect-export-reset.md) covers cross-page findings, Markdown/JSON downloads, and returning to the upload gate.
