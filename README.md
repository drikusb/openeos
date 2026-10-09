# an open-source App that allows an org to implement and run the business using the EOS® framework.

An open-source web application that implements the full **Entrepreneurial Operating System® (EOS®)** framework. Run Level 10 Meeting®, track Rocks, manage Issues and To-Dos, maintain a V/TO®, review Scorecards, and navigate the The Accountability Chart® — all from a single self-hosted platform.

Built with Django, Bootstrap 5, PostgreSQL, and Docker. No JavaScript frameworks. No SaaS lock-in.

---

## Features

| Module | Description |
|--------|-------------|
| **V/TO®** | Vision/Traction Organizer® — Core Values, Core Focus, 10-Year Target, Marketing Strategy, 3-Year Picture, 1-Year Plan |
| **The Accountability Chart®** | Org-chart builder with seat owners, vacant seat tracking, and department grouping |
| **Rocks** | Quarterly priorities with on-track / off-track status, quarter labels, and dependency tracking |
| **Scorecards** | Weekly measurables with above/below/equal goal directions and colour-coded status cells |
| **Issues** | IDS® (Identify, Discuss, Solve) list with short-term / long-term types, cross-team delegation, and activity history |
| **To-Dos** | Weekly action items with escalation levels, due dates, and Rock/Issue linking |
| **Level 10 Meeting®** | Guided 90-minute meeting runner with timed segments, segue entries, headlines, IDS® integration, ratings, and cascading messages |

---

## Quick Start (Development)

**Requirements:** Docker and Docker Compose v2.

```bash
git clone https://github.com/drikusb/eos-app.git
cd eos-app
cp .env.example .env
docker compose up
```

The app starts at **http://localhost:8000**.

On first boot the entrypoint script:
- Runs all database migrations
- Collects static files
- Creates a superuser (`admin` / `adminpass` by default)

Log in at `/admin/` to set up your organisation, or visit the dashboard at `/` to get started.

### Multiple organisations

One deployment can host several organisations, each with its own teams, Rocks, Issues, To-Dos, Scorecards, VTO and Accountability Chart. This suits a consultancy running their own company alongside each client.

- A user belongs to an organisation through a **membership**, which carries their role (admin, team leader or member) in that organisation. The same user can be an admin of one organisation and a member of another.
- Superusers create additional organisations from the navbar switcher (**New organisation**) or at `/org/setup/`. The creator becomes its first admin.
- Members of more than one organisation see an **organisation switcher** in the navbar above the team switcher. Everything on screen, including lists, search and links by id, is scoped to the active organisation, so switch first if a link to another organisation returns "not found".
- Memberships can also be managed under **Memberships** in the Django admin.

---

## Configuration

All configuration is driven by environment variables. Copy `.env.example` to `.env` and edit it:

```bash
cp .env.example .env
```

| Variable | Default | Description |
|----------|---------|-------------|
| `SECRET_KEY` | *(dev key)* | Django secret key — **must** be changed in production |
| `DEBUG` | `True` | Set to `False` in production |
| `ALLOWED_HOSTS` | `localhost,127.0.0.1` | Comma-separated list of valid hostnames |
| `DB_NAME` | `eos_db` | PostgreSQL database name |
| `DB_USER` | `eos_user` | PostgreSQL username |
| `DB_PASSWORD` | `eos_password` | PostgreSQL password |
| `DJANGO_SUPERUSER_USERNAME` | `admin` | Admin username created on first run |
| `DJANGO_SUPERUSER_PASSWORD` | `adminpass` | Admin password created on first run |
| `SECURE_SSL_REDIRECT` | `False` | Set `True` when TLS terminates at Nginx |
| `SECURE_HSTS_SECONDS` | `0` | HSTS max-age in seconds (e.g. `31536000`) |
| `MEDIA_ACCEL_REDIRECT` | `False` | Set `True` behind the bundled Nginx so it sends avatar files after Django has checked the request |

---

## Production Deployment

### 1. Configure your environment

```bash
cp .env.example .env
# Edit .env — set SECRET_KEY, ALLOWED_HOSTS, strong DB_PASSWORD, MEDIA_ACCEL_REDIRECT=True, etc.
```

Generate a secret key:

```bash
python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
```

### 2. Start the production stack

The production compose file adds Nginx in front of Gunicorn and serves static files directly:

```bash
docker compose -f docker-compose.prod.yml up -d
```

This starts:
- **PostgreSQL 15** — database with persistent volume
- **Gunicorn** — 3-worker Django WSGI server on port 8000 (internal only)
- **Nginx** — reverse proxy on port 80, serves `/static/` and organisation logos under `/media/` directly

**Uploaded files and privacy.** Organisation logos are public: they appear on the login page and are not personal data. User avatars are personal data, so `/media/avatars/` is never served straight from disk. Django checks every request and only returns an avatar to its owner, a superuser, or a member of an organisation the owner also belongs to; anyone else gets a 404. With `MEDIA_ACCEL_REDIRECT=True` Nginx still delivers the bytes (via `X-Accel-Redirect`) once Django has approved the request, so the extra check costs no Gunicorn worker time for the file transfer itself. Without a proxy, leave it unset and Django streams the file.

`GET /healthz/` returns `{"status": "ok"}` (or HTTP 503 when the database is unreachable) and needs no login, so point container healthchecks and load balancer probes at it.

### 3. (Optional) TLS with a reverse proxy or load balancer

Point your TLS-terminating proxy (Nginx, Caddy, Cloudflare Tunnel, etc.) at port 80 of the host. Then set in `.env`:

```
SECURE_SSL_REDIRECT=True
SECURE_HSTS_SECONDS=31536000
```

### 4. Upgrades

```bash
git pull
docker compose -f docker-compose.prod.yml build --no-cache
docker compose -f docker-compose.prod.yml up -d
```

Migrations and `collectstatic` run automatically on startup via `entrypoint.sh`.

### 5. Daily email notifications

The overdue To-Do digest and same-day meeting reminders are sent by a management command,
not a background worker — schedule it to run once a day (mornings work well) with the
host's cron:

```
0 7 * * * cd /path/to/eos && docker compose -f docker-compose.prod.yml exec -T web python manage.py send_daily_notifications
```

Rock off-track alerts and user-invite emails are sent immediately and need no scheduling.
Configure SMTP via the `EMAIL_*` variables in `.env` (see `.env.example`) — without
`EMAIL_HOST` set, emails print to the container logs instead of sending, which is fine for
development.

---

## Running Tests

```bash
# Inside the dev container
docker compose exec web python manage.py test apps

# With coverage report
docker compose exec web coverage run manage.py test apps
docker compose exec web coverage report
```

---

## Project Structure

```
.
├── apps/
│   ├── accounts/       # Organisations, Memberships, Teams, UserProfiles
│   ├── accountability/ # The Accountability Chart® nodes and roles
│   ├── issues/         # Issues with IDS® workflow
│   ├── meetings/       # Level 10 Meeting® runner
│   ├── rocks/          # Quarterly Rocks
│   ├── scorecards/     # Weekly Scorecards
│   ├── todos/          # To-Dos
│   └── vto/            # Vision/Traction Organizer®
├── config/
│   ├── settings/
│   │   ├── base.py
│   │   ├── development.py
│   │   └── production.py
│   ├── urls.py
│   └── wsgi.py
├── nginx/
│   └── nginx.conf
├── static/             # Source static files (CSS, JS)
├── staticfiles/        # Collected static files (git-ignored)
├── templates/          # Django HTML templates
├── docker-compose.yml          # Development
├── docker-compose.prod.yml     # Production
├── Dockerfile
├── entrypoint.sh
└── requirements.txt
```

---

## Tech Stack

- **Python 3.11+** / **Django 5.x**
- **PostgreSQL 15**
- **Bootstrap 5.3** + Bootstrap Icons (CDN)
- **Gunicorn** (production WSGI)
- **Whitenoise** (static file serving / compression)
- **Nginx** (production reverse proxy)
- **Docker** + **Docker Compose v2**

No Node.js. No Webpack. No JavaScript build step.

---

## Contributing

Pull requests are welcome. For significant changes, please open an issue first to discuss what you'd like to change.

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/my-feature`)
3. Make your changes with tests
4. Ensure the test suite passes (`docker compose exec web python manage.py test apps`)
5. Open a pull request

---

## License

[MIT](LICENSE)
