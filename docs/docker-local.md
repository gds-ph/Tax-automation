# Local Docker trial

Reviewed 2 October 2026. This remains an isolated local trial; the active office deployment is described in [docker-server.md](docker-server.md).

Run from the repository root with Docker Desktop using Linux containers:

```powershell
docker compose -f compose.local.yaml up -d --build
docker compose -f compose.local.yaml exec web python manage.py createsuperuser
```

Open http://localhost:8002 and sign in using that new account.

The image excludes workstation secrets, .env files, databases, documents and
worker credentials. The named test-data volume contains a new SQLite database,
private media and a generated persistent Django encryption key. Keep that key
with the database when backing up; Gmail credentials depend on it.
The test settings force submission off and bind the published port to loopback.
No Windows worker or scheduled receipt checker is attached to this test instance.

The client directory uses the existing workstation service at
http://host.docker.internal:3021. This may expose real client folders to the test
dashboard; do not run archive tests against those folders. OCR integration and
end-to-end receipt/archive testing require separate test services and credentials.

```powershell
docker compose -f compose.local.yaml ps
docker compose -f compose.local.yaml logs --tail 50 web
docker compose -f compose.local.yaml down
```

Stopping with `down` retains test data. Do not add `--volumes` unless you intend
to delete the test database, media and encryption key.

This is a local trial, not the Linux production deployment. LAN host settings,
HTTPS, the client-files service/SMB mount, scheduled receipt checks, backup and
restore, and Windows worker connectivity must be configured before migration.
