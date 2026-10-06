# eBIRForms work-order dashboard

Django 5.2.17 LTS and SQLite, with reusable Clients, versioned Form Definitions,
Client Filing Profiles, audited Work Orders, and immutable filing snapshots.
The approved Milestone 2 architecture revision is complete. The dashboard now starts with Clients: select a client, choose an available
form, select its period and queue preparation. See the
[client dashboard report](docs/client-dashboard-report.md).
Only calendar-year 2551Qv2018 zero preparation can be marked ready; 1701Q is a
planned definition with no executable route. The Stage 1 worker API, protected PDF
transfer/download and Windows bridge are implemented locally. Actual VM execution
and submission remain unconnected/disabled. See the [worker setup guide](docs/worker-api-setup.md)
and [implementation report](docs/worker-api-report.md).

See the [client architecture implementation report](docs/client-architecture-report.md)
for the current design, migration preservation, tests, and manual verification.
Earlier milestone reports describe their original delivery and are historical.

## Windows development setup

Use PowerShell in this repository. Existing local setup already has `.venv` and
a private `.env`; do not overwrite them. For a fresh checkout:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
```

For a fresh `.env`, replace its secret placeholder without printing the secret:

```powershell
@'
from pathlib import Path
import secrets
path = Path('.env')
text = path.read_text(encoding='utf-8')
placeholder = 'replace-with-a-secure-random-secret'
if placeholder not in text:
    raise SystemExit('No placeholder found; existing secret left unchanged.')
path.write_text(text.replace(placeholder, secrets.token_urlsafe(64)), encoding='utf-8')
'@ | .\.venv\Scripts\python.exe -
```

Environment variables take precedence over `.env`. `DJANGO_SECRET_KEY` is required
and must contain at least 50 characters; use a securely generated random value.
`DJANGO_DEBUG` accepts `True` or `False` and defaults to `False` when absent.
`DJANGO_ALLOWED_HOSTS` is restricted to `127.0.0.1` and `localhost` in this milestone.
Timezone is `Asia/Manila`, with timezone-aware timestamps (`USE_TZ = True`).

Run checks, migrations, and the development server:

```powershell
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe manage.py check
.\.venv\Scripts\python.exe manage.py migrate
.\.venv\Scripts\python.exe manage.py test
.\.venv\Scripts\python.exe manage.py runserver 127.0.0.1:8001
```

Port 8000 is occupied by an existing Windows process. The user approved an
available loopback port; startup was verified on 8001. Use 8001 for the commands
below, or another available loopback port if necessary. No host settings change
is required when changing only the port.

Open `http://127.0.0.1:8001/login/` and sign in with your existing account.
Your existing superuser has dashboard access. In `/admin/`, create a **Client**
with an explicit client type, then a **Client filing profile** linking it to the
seeded **2551Q** definition. Supply an ATC explicitly on the profile or work order.
Open **Clients**, select the client, choose **Prepare 2551Q**, enter the period
and confirm the zero filing, then click **Queue preparation**. Client source fields are not
re-entered on the work order. Marking ready records queue status; it does not
execute PAD yet. Work-order admin details and snapshots are read-only; admin
list actions support ready/draft and explicit snapshot refresh.
For a fresh database, create a local account with
`.\.venv\Scripts\python.exe manage.py createsuperuser`.
`/media/example.pdf` must return 404. Signing out uses the dashboard's POST button.
Stop the server with Ctrl+C. Virtual-environment activation and PowerShell execution
policy changes are unnecessary when using the explicit Python path above.

## Files and security

- `config/`: environment settings, URL routing, WSGI/ASGI scaffolds, foundation tests.
- `accounts/`: dashboard login/logout, role-group data migration, authentication tests.
- `workorders/`: model, 2551Qv2018 validators/reference data, status services, dashboard forms/views, admin, tests.
- `automation_api/`: authenticated Stage 1 claims, attempts/leases, result and PDF services, provisioning/recovery commands and tests.
- `worker/`: Windows PowerShell transfer helper and placeholder configuration; no credentials.
- `audit/`: append-only audit records, read-only admin, tests.
- `templates/` and `static/`: dashboard templates and the design-system stylesheet;
  no external CDN and no downloaded web font.
- `media/`: private dashboard storage, ignored by Git and never mounted as a URL.
- `db.sqlite3`: local prototype database, ignored by Git.
- `docs/architecture.md`: deployment components and deferred integration decisions.

The secret exists only in the ignored local `.env` (or process environment).
`.env.example` contains a placeholder. Git excludes media, PDF/XML files, databases,
common data/document formats, working/output folders, secrets, and `.venv`.
Ignore rules cannot detect sensitive content in arbitrary source files: keep all
taxpayer information out of source code, logs, examples, and commits. Use fake data only.
Only fake samples are included in source/tests. No demo records are automatically
inserted into your local database.

## Dashboard roles and optional demo data

The accounts role migrations configure these groups:

| Group | Dashboard access |
| --- | --- |
| Preparer | View configuration/orders/history; create/edit clients and filing profiles; create/edit/queue orders |
| Approver | View configuration/orders/history; no mutation or approval action yet |
| Administrator | Preparer capabilities, form-definition management, agent-registry viewing |

Use your existing superuser in `/admin/` to create users and assign their Groups.
Ordinary dashboard users do not need Staff status. Access to configuration through
Django admin requires Staff status in addition to the relevant model permissions. The Administrator group does
not automatically grant Django superuser, account-management, or Staff privileges.
Assigning multiple groups combines their permissions. Current authorized users
share the office work-order list; there is no per-client or per-owner isolation.
Accounts without the required permissions receive an access-needed page.

To deliberately create three clearly fake sample orders using an existing
authorized username (replace `YOUR_USERNAME`):

```powershell
.\.venv\Scripts\python.exe manage.py seed_demo --actor YOUR_USERNAME
```

This is optional. Re-running leaves existing demo references untouched; it does
not create accounts or passwords. Every sample is labeled FAKE DEMO and uses
`example.invalid` email addresses. ATC `PT 010` is explicitly supplied as sample
input, never as a default for ordinary work orders.

Protected PDF upload/download and hash verification are implemented. Human
approval and Stage 2 approval binding remain later work.
Do not add anonymous media routing, including Django's development media helper.
VM-local paths are metadata, never browser links or files for Django to open.

## Dashboard design system

`static/dashboard.css` is the single stylesheet: semantic dark/light tokens, a blue
accent, thin borders, Inter typography, compact spacing, a 220px fixed sidebar with
a 56px topbar, and bordered cards. The earlier `static/office-theme.css` override
layer and its separate navy/teal palette were folded into it, so one token set now
replaces three competing palettes. Tokens are defined on `:root` for light,
redefined under `:root[data-theme='dark']`, and again under
`@media (prefers-color-scheme: dark)` guarded by `:root:not([data-theme='light'])`
so the operating system is followed only when the viewer has not pinned a theme.
`static/office-theme.js` pins `data-theme` from `localStorage` before first paint;
the app default is light. Page components must use tokens, never literal colors,
so both themes stay correct.

Contrast was measured rather than assumed. Against the light surface `#ffffff`, the
source palette's accent `#4099ff` reaches only 2.91:1, its muted grey `#9ca3af`
2.54:1, and its danger `#ef4444` 3.76:1. Filled buttons and light-theme links
therefore use `--accent-action` `#1668d4` (5.30:1), muted text uses `#6b7280`
(4.83:1), and danger uses `#dc2626` (4.83:1). `#4099ff` is kept for what it reads
well against: active navigation tints, the tab underline, focus rings, borders, and
dark-theme link text (6.30:1 on `#14141c`). Dark-theme muted text is `#9494ad`
(6.19:1). Keep new colors at 4.5:1 or better in both themes.

Below 768px the sidebar becomes compact top navigation rather than a drawer, so no
JavaScript is required for the shell. Create, edit, prepare and COR review remain
full-page server-rendered forms, not modals: they re-render with field errors and a
409 on the optimistic-locking conflicts this app depends on, and that path is
covered by tests. `.tabs`/`.tab` primitives exist for future use; no navigation is
tabbed yet, so no URL tab state was added.

No web font is downloaded. `--font` keeps the existing office stack
(`'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial,
sans-serif`), which renders as Segoe UI on the office machines unless a viewer has
Inter installed locally. Adding a self-hosted `@font-face` later would change the
appearance on every machine, so treat it as a deliberate decision, not a detail.
Baseline sizes:
page heading 22px/700, topbar title and section headings 16px/700, body and table
text 13px, input labels 11px/600, metadata and badges 10–12px, metric values
22px/700, on a 4/6/8/12/16/20/24/32 spacing scale with 24px page padding.

`templates/workorders/status.html` maps each work-order status to one badge style:
queued is info, in-progress and awaiting approval are pending, failure and
review-required statuses are danger, and everything else is neutral. Keep that
mapping in one place instead of restyling badges per page.

## Scope and deployment

Bind only to `127.0.0.1` (verified port: 8001; originally planned port: 8000).
No LAN binding, firewall, VM-network, or remote hosting
configuration is included. `ALLOWED_HOSTS` validates HTTP hosts; the explicit
`runserver` address controls socket binding. Do not use `0.0.0.0` or the LAN IP.
The development server is not a production hosting solution. A production WSGI
server, internal reverse proxy, TLS, access controls, and backups require a later,
explicit deployment plan.

PAD and eBIRForms execute in a dedicated Windows VM. Django does not launch PAD;
the future worker polls the internal API. BIR Submit / Final Copy stays outside
the web application and disabled in PAD while fake data is used. No submission
operation is implemented here.

Actual execution still needs VM connectivity and the PAD wrapper configured in
the VM. A concrete private HTTPS/network configuration is required before
connecting it. The supplied guide maps all 20 existing Stage 1 inputs; approval
and Stage 2 execution remain later work.
Initial filings are calendar-year `2551Qv2018` with `YearEndMonth = "12"`.
TIN/RDO/ATC validation follows the user-approved Milestone 2 rules and the VM's
22-code ATC list. The prototype claims one job at a time, uses a 30-minute lease
with no automatic rerun, and requires PDF upload before successful result reporting.
See the worker guide for renewal/recovery limits. Identifiers preserve leading zeros.
