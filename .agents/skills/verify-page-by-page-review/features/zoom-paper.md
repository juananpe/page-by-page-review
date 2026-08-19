# Zoom the paper

Zoom lets a user fit the page to the reader or inspect it at 100% and 150% through buttons, the page image, or the `Z` key.

## Sub-features

- `zoom-buttons` selects Fit, 100%, or 150% directly.
- `zoom-image` cycles levels by choosing the paper image.
- `zoom-keyboard` cycles levels with `Z`.

## How to get to it (user POV)

- Choose `Fit`, `100%`, or `150%` above the page.
- Choose the displayed page image.
- Press `Z` while the review app has focus.

## Driving it with Browser

Preconditions:

- A reviewed page is visible and Fit begins with `aria-pressed=true`.

- **Direct buttons.** Choose `100%` and require `#sheet` class `sheet zoom100` plus `100%` pressed. Choose `150%` and require `sheet zoom150`. Choose `Fit` and require `sheet fit`.
- **Image cycle.** Choose the image `Page 1 of verification-paper.pdf` three times. Assert classes change Fit → zoom100 → zoom150 → Fit.
- **Keyboard cycle.** Press `z` three times and assert the same class and pressed-button sequence.
- **Capture proof.** At 150%, save a screenshot showing the pressed `150%` control and the enlarged paper, then restore Fit before cleanup.

## Gotchas

- Visual size alone is ambiguous in responsive layouts; assert both image class and `aria-pressed` state.
- The reader scroll container can move at 100%/150%; reset to Fit before testing another feature.
- Zoom state persists across page navigation.
- `Z` is ignored while the upload gate is visible or with Meta, Control, or Alt held.
