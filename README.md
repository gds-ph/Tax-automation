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
- `templates/` and `static/`: dashboard templates and local public CSS; no external CDN.
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
