# Trademark Remediation — Tracking

> Part of the response agreed with EOS Worldwide on their [#17](https://github.com/drikusb/openeos/issues/17) request. No code changes in this PR — it exists to agree the plan and the project's new name before any area-specific PR opens.

## Background

EOS Worldwide asked us to either remove their trademarks, terminology, and the two tool copies they identified, or archive the repository. We've chosen to remove and generalize rather than archive. Their full findings and the agreed direction are in [#17](https://github.com/drikusb/openeos/issues/17) — this document turns that discussion into a concrete, reviewable scope.

## Proposed direction (credit: @RCheesley, issue #17)

Rather than swap EOS's names for different-but-equivalent names, make the project genuinely vendor-agnostic: a weekly meeting with a scorecard, quarterly priorities, to-dos, issue-solving, a vision document and a roles chart are shared by EOS, Scaling Up, 4DX, and others — none of that structure belongs to anyone. We ship generic names and a generic default agenda; each organisation can relabel things in their own instance if they want their own vocabulary. That's user content at that point, not something we ship, and it also opens the project to teams who aren't running EOS at all.

## What has to change

### 1. Project identity
- The project name itself (currently "OpenEOS")
- "EOS App" — appears in ~55 templates and in the sender name on every outgoing email
- The "Open-source EOS framework" wording (login page, footer, README, repo description) — misleading regardless of trademark, since EOS itself is proprietary to EOS Worldwide, not open source
- No current statement of trademark ownership or non-affiliation

### 2. Terms on EOS Worldwide's own trademark lists ([US](https://branding.eosworldwide.com/us-trademarks), [international](https://branding.eosworldwide.com/international-trademarks/))
Level 10 Meeting, L10, IDS, V/TO, Vision/Traction Organizer, Accountability Chart, Core Focus, 10-Year Target, 3-Year Picture, 3 Uniques, Traction, Integrator.

### 3. Terms not on either list, renamed anyway to avoid "confusingly similar"
Rocks, Scorecard, Issues, To-Dos, Core Values, Headlines, Segue, Milestones.

### 4. The two structural copies EOS Worldwide named specifically
- The V/TO's fixed section structure and two-page print layout
- The Level 10 Meeting agenda's exact segment timings (`[5, 5, 5, 5, 5, 60, 5]` minutes)

Proposed fix for both: turn them into features rather than fixed copies — a vision document with admin-defined sections (generic defaults, plain print view) and per-team agenda templates with editable segments and durations. This removes the copying concern at the root and is a better product regardless.

### 5. Prescriptive copy written in EOS Worldwide's voice
Five "EOS recommends ..." lines (e.g. "EOS recommends 3–7 Rocks") need rewording as our own guidance or removed.

## Scope, confirmed by file audit (2026-10-16, current `main`)

| Area | Files touched | Primary terms |
|---|---|---|
| Rocks | ~76 | Rock, Rocks |
| VTO | ~44 | VTO, V/TO, Core Focus, 3-Year Picture, 1-Year Plan, 10-Year Target |
| Level 10 Meeting | ~18 | Level 10 Meeting, L10, Segue (13 files), Cascading Messages (5 files) |
| Scorecards | ~32 | Scorecard |
| Accountability Chart | ~11 | Accountability Chart |
| Issues / IDS | ~14 | IDS specifically (plain "Issue" is generic, not on EOS's lists, almost certainly fine to keep) |
| Branding & docs | ~70 | EOS, Entrepreneurial Operating System, "EOS App", "openeos", README/CONTRIBUTING/LICENSE/ROADMAP/ENHANCEMENTS, page-title suffix across most templates |

156 files total have at least one of these terms. Renaming the `vto` app is expected to be the fiddliest piece because of Django's migration history, so it should go first.

## Proposed build sequence

1. Rename the `vto` Django app (migrations make this the hardest piece — do it while the scope is freshest).
2. Land the branding infrastructure (a single setting for the product name instead of it being hardcoded everywhere, and terminology as configurable defaults with per-organisation overrides) as the vehicle the rest of the work rides on.
3. Turn the two structural copies into the configurable features described above.
4. Sweep remaining hardcoded terms area by area (Rocks, Level 10 Meeting, Scorecards, Accountability Chart, Issues/IDS), each as its own PR.
5. Sweep README, ROADMAP, repo description, GitHub topics, and docs; reword the "recommends" lines.
6. Confirm the current README "on hold" banner comes down once the above lands.

Each area becomes its own PR once this plan and the new names are agreed — this PR isn't where the renaming happens.

## The project's new name

Proposed approach (credit: @RCheesley): a coined word rather than plain English — every real-word candidate tried so far turned out to already be a company, a Kubernetes project, or one of EOS Worldwide's own marks. Avoid anything containing Traction, Pulse, 90-day, Rocket, or Integrator specifically.

Quick collision checks run so far (not a substitute for a real trademark search — see below):

| Candidate | Result |
|---|---|
| Cadence | Taken — registered mark of Cadence Design Systems (EDA software, actively defended) |
| Helm | Likely collides — Helm is the Kubernetes package manager |
| Compass | Heavily crowded |
| Pulse / PulseOS | Taken — an existing "business operating system" product, same category |
| Keel | Taken — an existing no-code/ERP business platform, same category |
| Flywheel | Taken — registered mark + an existing content/growth tool |
| Trajectory | Taken — an existing project-management tool, same category |
| Wayfinder | Taken — multiple existing open-source projects with this name |
| Groundwork | Existing registered open-source company (different space — IT monitoring — lower risk, but not clean) |
| Northline | No collision found |

**Before committing to any name:** run the full check RCheesley proposed — GitHub, PyPI, domain availability, and a UK/EU/US trademark search. The quick checks above are a starting filter, not clearance.

## Open questions for this PR

- Does the generalization direction above match what's needed, or does anything need to go further / can anything stay?
- Any candidate names to add to the shortlist before running full checks?
- Anything in the proposed build sequence that should be reordered?
