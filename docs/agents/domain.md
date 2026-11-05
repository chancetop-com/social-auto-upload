# Domain Docs

This repo uses a single-context layout.

## Before exploring

- Read `GLOSSARY.md` at the repo root.
- Read ADRs in `docs/adr/` that touch the area being explored.

If these files or directories do not exist, proceed silently. Domain documentation is created lazily through `/domain-modeling` when terms or decisions are resolved.

## File structure

- `GLOSSARY.md`: vocabulary shared across the repo.
- `docs/adr/NNNN-<decision-slug>.md`: architectural decisions.

## Use the glossary's vocabulary

When naming domain concepts in issue titles, refactor proposals, hypotheses, or tests, use the terms defined in `GLOSSARY.md`.

If a needed concept is absent, reconsider whether it belongs to the project's vocabulary. Note real gaps for `/domain-modeling`.

## Flag ADR conflicts

If a proposal contradicts an existing ADR, identify the ADR and explain why the decision should be reconsidered.
