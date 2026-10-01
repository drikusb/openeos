# OpenEOS Roadmap

A living checklist of what's been built and what's coming next. PRs welcome for any item marked `[ ]`.

---

## ✅ v0.1 — Core EOS Modules

- [x] Project scaffold: Django 5, PostgreSQL 15, Docker Compose
- [x] Authentication: login, logout, password reset
- [x] Accounts: organisations, teams, user profiles, invite flow
- [x] Team switcher: session-based active team, team-scoped data
- [x] Rocks: quarterly priorities, status tracking, dependencies, archive
- [x] Issues: create, delegate across teams, activity log, IDS workflow
- [x] To-Dos: my/team views, Rock/Issue linking, overdue escalation
- [x] Scorecards: metrics, weekly entry, 13-week rolling view, off-track escalation
- [x] VTO: all 8 sections, inline edit, print view, live Rocks/Issues feed
- [x] Accountability Chart: org tree, seat management, vacant highlighting
- [x] Level 10 Meeting: full 7-segment runner, countdown timer, post-meeting summary
- [x] CI: GitHub Actions test suite on every push

---

## ✅ v0.2 — Rock & Meeting Enhancements

- [x] Rock milestones: title, due date, complete toggle, progress bar
- [x] Milestone descriptions: rich text block per milestone, edit page
- [x] Rock ↔ Issue linking from the Rock detail page
- [x] Meeting notes: per-segment notes block, shown in completed meeting summary

---

## ✅ v0.3 — Open-Source Housekeeping

- [x] `CONTRIBUTING.md`: dev setup, PR process, coding standards
- [ ] GitHub Actions: build and publish Docker image to Docker Hub on merge to `main`
- [x] `docker-compose.prod.yml` smoke-test in CI

---

## ✅ v0.4 — Search & Discoverability

- [x] Global search: find Rocks, Issues, and To-Dos from a single search bar
- [x] Search results page with module-grouped results, scoped to user's teams
- [x] Keyboard shortcut to open search (`/` or `Ctrl+K` / `Cmd+K`)

---

## ✅ v0.5 — Rock Check-ins

- [x] Weekly check-in model: progress note + confidence (on/off track) per Rock
- [x] Check-in form on Rock detail page
- [x] Check-in history timeline on Rock detail
- [x] Overdue check-in warning (no update in 7 days)

---

## ✅ v0.6 — Email Notifications

- [x] Overdue To-Do digest: daily email listing your overdue items
- [x] Meeting day reminder: email to team on the morning of a scheduled meeting
- [x] Rock off-track alert: email owner when a Rock is marked off-track
- [x] User invite email: send invite link when a user is added to an org
- [x] Configurable: users can opt out per notification type

---

## ✅ Multiple organisations

- [x] Scope every record fetched by id to the active organisation, with isolation tests
- [x] Membership model: a user can belong to several organisations with a role in each
- [x] Organisation switcher in the navbar; superusers can create further organisations
- [ ] Invite an existing user into another organisation from the Users page
- [ ] Serve uploaded logos and avatars through an authenticated view

---

## 🗺️ v0.7 — Export & Reporting

- [ ] Meeting notes PDF: export a completed meeting's notes and summary
- [ ] Rocks CSV: export current quarter's rocks with status and owner
- [ ] Scorecard CSV: export 13-week history for a scorecard
- [ ] Issues CSV: export open issues with status and delegation info

---

## 🗺️ v0.8 — Mobile Polish

- [ ] Audit all views on 375px viewport (iPhone SE baseline)
- [ ] Fix any broken layouts in meeting runner on mobile
- [ ] Responsive scorecard table (horizontal scroll or card layout)
- [ ] Touch-friendly milestone and to-do toggle buttons

---

## 🗺️ v0.9 — In-App Notifications

- [ ] Notification model: per-user feed of actionable events
- [ ] Notification bell in navbar with unread count badge
- [ ] Events: overdue To-Do, Rock off-track, Issue delegated to your team, meeting starting
- [ ] Mark as read / mark all read
- [ ] Notification preferences page

---

## 💡 Backlog (unscheduled ideas)

- [ ] Dark mode toggle
- [ ] Recurring To-Dos (weekly/monthly)
- [ ] Rock progress percentage (manual 0–100% slider)
- [ ] Issue voting / priority scoring in IDS
- [ ] VTO section permissions (lock sections to leadership only)
- [ ] Multi-language / i18n support
- [ ] REST API (Django REST Framework) for mobile or third-party integrations
- [ ] Webhooks: post events to Slack, Teams, or custom endpoints
