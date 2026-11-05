# Issue tracker: Local Markdown

Issues and specs for this repo live as Markdown files in `.scratch/`.

## Conventions

- One feature per directory: `.scratch/<feature-slug>/`.
- The spec is `.scratch/<feature-slug>/spec.md`.
- Implementation issues are one file per ticket at `.scratch/<feature-slug>/issues/<NN>-<slug>.md`, numbered from `01`.
- Triage state is recorded as a `Status:` line near the top of each issue file. Use the role strings in `triage-labels.md`.
- Append comments and conversation history under a `## Comments` heading.

## Publishing and fetching tickets

When a skill says "publish to the issue tracker", create the appropriate spec or issue file under `.scratch/<feature-slug>/`, creating directories as needed.

When a skill says "fetch the relevant ticket", read the referenced file. If only a number is supplied, resolve it within the relevant feature's `issues/` directory; ask for the feature if ambiguous.

## Wayfinding operations

Used by `/wayfinder`. The map is a file with one child file per ticket.

- **Map**: `.scratch/<effort>/map.md`, containing Notes, Decisions-so-far, and Fog.
- **Child ticket**: `.scratch/<effort>/issues/NN-<slug>.md`, numbered from `01`, with the question in the body.
- **Type**: a `Type:` line records `research`, `prototype`, `grilling`, or `task`.
- **State**: wayfinding tickets use `Status: open`, `Status: claimed`, or `Status: resolved`.
- **Blocking**: a `Blocked by: NN, NN` line near the top lists dependencies. A ticket is unblocked when every listed ticket is resolved.
- **Frontier**: scan for open, unblocked tickets; lowest number wins.
- **Claim**: set `Status: claimed` and save before starting work.
- **Resolve**: append the answer under `## Answer`, set `Status: resolved`, then append a gist and link to the map's Decisions-so-far section.
