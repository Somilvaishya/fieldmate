# Design handoff

Drop whatever the design tool produces in here, one folder per screen, numbered to match
`docs/UI_BRIEF.md`:

```
design/
  01-sign-in/
  02-today/
    screenshot.png
    export.html
  08-visit-hub/
    screenshot.png
    empty-state.png
```

**Screenshots alone are enough.** An exported HTML file is a useful reference for spacing and
layout, but the app is Vue 3 with plain CSS custom properties — not React, not Tailwind — so
exports are translated rather than dropped in.

Name files plainly: `screenshot.png`, `export.html`, `empty-state.png`, `error-state.png`.
