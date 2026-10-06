# Milestone 1 verification

> Historical record. Reviewed 2 October 2026: implementation status, permissions, addresses and test counts below refer to the original delivery, not the current deployment. Start with the [current documentation index](README.md). For recovery use [the current guide](worker-preparation-recovery.md); do not replay old reset instructions against a new attempt.

## Created files

- `manage.py`, `config/`, and empty Django app scaffolds in `accounts/`,
  `workorders/`, `automation_api/`, and `audit/`.
- `config/tests.py`: four foundation checks.
- `.gitignore`, `.env.example`, `requirements.txt`, `README.md`.
- Placeholder directories `templates/`, `static/`, and architecture/verification
  documentation in `docs/`.
- Local ignored artifacts: `.venv/`, random-secret `.env`, `db.sqlite3`, `media/`.
- Git repository initialized; no commit or remote created.

## Commands executed

PowerShell in the repository root (all package installation used `.venv`):

```powershell
git init
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install 'Django>=5.2,<5.3' python-dotenv
.\.venv\Scripts\python.exe -m django startproject config .
foreach ($app in @('accounts','workorders','automation_api','audit')) {
    .\.venv\Scripts\python.exe manage.py startapp $app
}
.\.venv\Scripts\python.exe -m pip freeze
.\.venv\Scripts\python.exe manage.py migrate
.\.venv\Scripts\python.exe manage.py check
.\.venv\Scripts\python.exe manage.py test
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe manage.py makemigrations --check --dry-run
git check-ignore .env .venv/pyvenv.cfg db.sqlite3 media/example.pdf generated/example.xml taxpayer_data/example.txt secrets/token.txt
git status --short
.\.venv\Scripts\python.exe manage.py runserver 127.0.0.1:8000 --noreload
```

Local Python scripts wrote configuration, generated the secret without displaying
it, and pinned the installed dependencies in `requirements.txt`. File patches
added documentation and tests. An initial inspection command contained an invalid
`.\ .venv` invocation; it failed without making changes.

## Results

- Django 5.2.17 installed locally with pinned dependencies.
- All 18 built-in Django migrations applied successfully; no custom app models.
- Django system checks: no issues.
- Four foundation tests pass: local settings/storage separation, no media URL
  route, anonymous media request rejected with 404, nonlocal HTTP host rejected.
- The first test run had one assertion failure because Django's test runner adds
  `testserver` to runtime allowed hosts. The assertion now checks the project's
  configured hosts; no allowed-host setting was changed.
- `pip check`: no broken requirements.
- Migration drift check: no changes detected.
- Git exclusions verified for the local environment, database, media, output,
  taxpayer-data directory, and secrets directory. `.env.example` remains visible
  to Git. No real secret was printed or committed.
- The initial startup attempt on port 8000 was blocked. A socket preflight failed with
  Windows error 10013; Django's direct startup attempt reported that it did not
  have permission to access the port. Read-only inspection found an existing
  listener on `0.0.0.0:8000`, PID 2600. This listener was not started by this
  project. No existing process was stopped and no network setting was changed.
- The user subsequently authorized an available loopback port. Live startup on
  `127.0.0.1:8001` succeeded using:

  ```powershell
  .\.venv\Scripts\python.exe manage.py runserver 127.0.0.1:8001 --noreload
  ```

- HTTP checks: `/admin/login/` returned 200 with a CSRF token,
  `/static/admin/css/base.css` returned 200, and `/media/example.pdf` returned 404.
- Read-only listener inspection confirmed binding exclusively to `127.0.0.1:8001`.
  The initial verification script expected the listener PID to equal the launcher
  PID; Windows virtual-environment Python uses a child process. The corrected
  check verified that parent/child relationship and passed without changing the app.
- The verification server was stopped and port 8001 was confirmed no longer
  listening. The existing port-8000 process was left untouched.

## Completion and remaining limitations

Milestone 1 verification is complete on the user-authorized alternate loopback
port. Manual startup instructions in the README now use port 8001. No firewall,
LAN, VM-network, or allowed-host configuration changed.

The foundation is development-only. Dashboard permissions, protected file
upload/download, workflow models, API authentication, and deployment hardening
remain later milestones. No Milestone 2 implementation was started.
