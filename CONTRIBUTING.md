# Contributing to OpenEOS

Thanks for your interest in contributing! OpenEOS is an open-source Django implementation of the EOS (Entrepreneurial Operating System) framework. All contributions — bug fixes, new features, docs, and tests — are welcome.

---

## Table of Contents

- [Prerequisites](#prerequisites)
- [Getting started](#getting-started)
- [Running tests](#running-tests)
- [Code style](#code-style)
- [Branching and PRs](#branching-and-prs)
- [Commit messages](#commit-messages)
- [Project structure](#project-structure)

---

## Prerequisites

- [Docker](https://docs.docker.com/get-docker/) + Docker Compose v2
- Python 3.11+ (only needed if running outside Docker)
- Git

---

## Getting started

```bash
# 1. Fork and clone
git clone https://github.com/YOUR_USERNAME/openeos.git
cd openeos

# 2. Copy the example env file
cp .env.example .env

# 3. Start the stack
docker compose up --build
```

The app will be available at **http://localhost:8000**.

The `web` container runs as uid 1000 (user `app`), not root, and writes `staticfiles/` and `mediafiles/` into the bind-mounted checkout as that uid. On macOS this maps to your own user; on a Linux host, if your checkout is owned by a different uid, `chown` it or set `user:` on the `web` service in `docker-compose.yml`.

On first run the entrypoint automatically runs `migrate` and `collectstatic`. A superuser is **not** created automatically — use the Django admin:

```bash
docker compose exec web python manage.py createsuperuser
```

---

## Running tests

```bash
# All tests
docker compose exec web python manage.py test apps

# Single app
docker compose exec web python manage.py test apps.rocks

# With coverage
docker compose exec web coverage run manage.py test apps
docker compose exec web coverage report
```

The CI enforces **60% minimum coverage** on the model layer. New features should include model tests.

---

## Code style

- **Python**: follow PEP 8. No external linter is enforced yet, but keep lines under 100 characters.
- **Django**: class-based views, `LoginRequiredMixin` on everything, no raw SQL.
- **Templates**: Bootstrap 5 only — no additional CSS frameworks. Minimal vanilla JS; no frontend build step.
- **No comments** that explain *what* the code does — only *why* if the reason is non-obvious.
- **No print statements** — use Django's logging if you need debug output.
- **Migrations**: always commit migrations alongside model changes. CI will fail if migrations are missing.

---

## Branching and PRs

| Branch | Purpose |
|--------|---------|
| `main` | Stable, always deployable |
| `feature/<name>` | New features |
| `fix/<name>` | Bug fixes |
| `chore/<name>` | Maintenance, deps, docs |

1. Branch off `main`.
2. Keep PRs focused — one feature or fix per PR.
3. Make sure `docker compose exec web python manage.py test apps` passes locally before opening a PR.
4. Fill in the PR description: what changed and why, plus a short test plan.

CI runs automatically on every PR. A PR cannot be merged if tests fail or coverage drops below 60%.

---

## Commit messages

Use the imperative mood, present tense. Keep the subject line under 72 characters.

```
Add milestone due-date warning on Rock detail

Long description if needed — explain WHY, not what.
```

Common prefixes:

| Prefix | When to use |
|--------|-------------|
| `Add` | New feature or file |
| `Fix` | Bug fix |
| `Update` | Change to existing feature |
| `Remove` | Delete code or file |
| `Refactor` | Code change with no behaviour change |
| `Test` | Adding or updating tests |
| `Docs` | Documentation only |
| `Chore` | Dependencies, CI, tooling |

---

## Project structure

```
apps/
  accounts/       # Organisations, memberships, teams, user profiles
  rocks/          # Quarterly priorities (Rocks), milestones
  issues/         # Issues with IDS workflow and delegation
  todos/          # Weekly To-Dos
  scorecards/     # Weekly metrics and 13-week history
  vto/            # Vision/Traction Organiser (8 sections)
  accountability/ # Accountability Chart (org tree)
  meetings/       # Level 10 Meeting runner

config/
  settings/
    base.py         # Shared settings
    development.py  # Local dev (DEBUG=True)
    production.py   # Production hardening

templates/        # All Django templates (per-app subdirectories)
static/           # CSS and JS
nginx/            # Nginx config for production
```

Each EOS module lives in its own Django app. Views are class-based. Forms receive a `team=` kwarg so querysets are always scoped to the active team — do not pass `team` as a form field.

Every record reachable by primary key must be limited to the active organisation. Use `OrgScopedMixin` on generic detail, update and delete views and `get_org_object_or_404()` in plain `View` classes (both in `apps/accounts/scoping.py`), and add the new URL to `apps/accounts/tests/test_isolation.py`.

---

## Questions?

Open a [GitHub Discussion](https://github.com/drikusb/openeos/discussions) or file an issue. We're happy to help.
