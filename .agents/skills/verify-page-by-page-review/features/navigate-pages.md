# Navigate reviewed pages

Navigation lets a user move between reviewed pages from the page index, page spine, previous/next controls, or keyboard while keeping the displayed paper image and findings synchronized.

## Sub-features

- `navigate-index` chooses a page from the labelled page index.
- `navigate-spine` chooses a page from the header's page strip.
- `navigate-buttons` uses Previous and Next.
- `navigate-keyboard` uses arrow keys or `j`/`k`.

## How to get to it (user POV)

- Choose a numbered result in `Page index` or a tick in `Pages`.
- Choose `← Prev` or `Next →`.
- Press `←`, `→`, `j`, or `k` while the review app has focus.

## Driving it with Browser

Preconditions:

- The two-page fixture completed review with filter `All`.
- Page 1 is selected and the page view, not the cross-page panel, is active.

- **Next button.** Choose `Next →`. Require `PAGE 2 / 2`, image alt `Page 2 of verification-paper.pdf`, text `Mock review of page 2`, and the page-2 row's `aria-current=true`.
- **Previous button.** Choose `← Prev`. Require the equivalent page-1 label, image alt, result text, and current row.
- **Index entry.** Under navigation `Page index`, choose the button containing `p2`. Require page 2 in reader and notes panels.
- **Spine entry.** Under the `Pages` region, choose the first tick (`button.tick[data-n="1"]`). Require page 1 in reader and notes panels.
- **Keyboard entries.** Press `ArrowRight`, `j`, `ArrowLeft`, and `k` one at a time, asserting the expected page after each. These are four distinct entry points.
- **Capture proof.** Save the final screenshot and DOM snapshot with both the current page label and matching result visible.

## Gotchas

- Previous/next wrap within the current filter rather than stopping at the ends.
- Page-row accessible names include the gist after analysis; match `p1` or `p2` rather than the full generated sentence.
- Spine ticks have useful `data-n`, `title`, and `aria-current` attributes but no visible text.
- Keyboard handlers ignore modified shortcuts and do not run while the upload gate is visible.
