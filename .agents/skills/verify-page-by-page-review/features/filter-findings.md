# Filter findings

Filtering lets a user restrict the page index to pages whose worst result is an error, warning, or minor/clean outcome and restore the complete index.

## Sub-features

- `filter-all` displays every page.
- `filter-errors` displays error and failed pages.
- `filter-warnings` displays warning pages.
- `filter-minor` displays note and clean pages.
- `filter-keyboard` cycles the same states with `F`.

## How to get to it (user POV)

- Choose `All`, `Errors`, `Warnings`, or `Minor` in the header.
- Press `F` while the review app has focus.

## Driving it with Browser

Preconditions:

- The two-page mock review completed: page 1 has worst severity `warning`, and page 2 has worst severity `note` (the `Minor` bucket).
- `All` has `aria-pressed=true` and the page index shows two rows.

- **Errors.** Choose `Errors 0`. Require it to have `aria-pressed=true`, `All` to be unpressed, and an empty index with text `No pages match this filter yet.`.
- **Warnings.** Choose `Warnings 1`. Require it to have `aria-pressed=true` and the index to contain only page 1.
- **Minor.** Choose `Minor 1`. Require it to have `aria-pressed=true` and the index to contain only page 2.
- **All.** Choose `All`. Require both page rows to return and `All` pressed.
- **Keyboard cycle.** Press `f` repeatedly and assert pressed states in order: Errors, Warnings, Minor, All. Capture at least one empty state and the restored state.
- **Capture proof.** Save screenshot and DOM evidence showing the pressed filter and corresponding page-index contents.

## Gotchas

- Button labels gain counts after analysis (`Errors 0`, `Warnings 1`, and `Minor 1`). Match by a name prefix or regular expression.
- The mock provider slices its finding pool by page number: page 1 returns warning/note, while page 2 returns note/ok. Filtering uses each page's worst actionable severity.
- Filtering changes the navigation set; previous/next wrap only through visible pages.
- `F` is ignored while the upload gate is visible or when Meta, Control, or Alt is held.
