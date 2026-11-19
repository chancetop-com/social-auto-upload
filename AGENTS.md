## Agent skills

### Issue tracker

Issues and specs use local Markdown under `.scratch/<feature>/`. See `docs/agents/issue-tracker.md`.

### Triage labels

Use the five default triage labels. See `docs/agents/triage-labels.md`.

### Domain docs

Use a single-context layout: root `GLOSSARY.md` and `docs/adr/`. See `docs/agents/domain.md`.

## Browser automation

1. **Reliable selectors.** Scope locators to the relevant form, dialog, or row. Prefer stable attributes or semantic roles that uniquely identify the target across locales and copy changes. Use a text-dependent locator only when stable non-text signals cannot distinguish the target. In that case, prefer English UI text or an English accessible name when available.
2. **Humanized interactions.** Follow the sequence a user would take through the visible UI. Reuse the uploader’s existing interaction helpers backed by `Humanizer` in `utils/humanize.py` for clicks, typing, and pacing. Wait for the expected UI state before the next action so the flow also works with humanization disabled.
