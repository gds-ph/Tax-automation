# Linux LAN deployment

Reviewed 2 October 2026. Active endpoint: `https://192.168.8.200:8443`; checkout: `/home/nodeadmin/ebir-deployment/tax-automation`. The Windows PAD worker is a separate machine.

This stack uses port 8443 on the configured LAN IP. Existing applications on
ports 8000/8080 and the other Docker projects are not modified. The web app and
client-files service have no directly published ports. Caddy terminates HTTPS.

## Before starting

- Confirm server free disk, memory, port 8443 and a working backup.
- Place this repository and `client-files` beside each other on the server.
- Mount the existing SMB CLIENT directory on Linux; verify it is the actual
  share, not an empty local directory. The client-files process uses uid 1000.
- Copy `deploy/server.env.example` to `.env.server`, mode 600. Set the mount path,
  host and HTTPS origin. Preserve the source `DJANGO_SECRET_KEY` when migrating
  data: it encrypts saved Gmail passwords. Supply the existing HTTPS GDS URL,
  key and model for COR scans. Never include secrets in an image or source bundle.
- Preserve the configured receipt sender during migration (the current test
  environment may use a simulated sender instead of BIR).

## Data migration

Stop the source receipt scheduler and pause the Windows worker before the final
snapshot. Prevent dashboard edits during cutover. Use SQLite's backup API to
make a consistent copy of db.sqlite3 and copy all private media. Do not copy
only the Docker trial database: it does not contain the original filing history.
Keep the source deployment available for rollback but do not run two workers or
receipt checkers against separate copies of the same pending filings.

Create the stack's app-data volume and import `db.sqlite3` and `media/` into its
root before starting web. Files must be owned by uid/gid 10001. Do not overwrite
an existing destination database without a backup. Run migrations against the
imported copy, then verify record counts, stored PDF/screenshot hashes and Gmail
credential decryption without displaying secrets.

```bash
docker compose --env-file .env.server -f compose.server.yaml config --quiet
docker compose --env-file .env.server -f compose.server.yaml up -d --build web client-files proxy
docker compose --env-file .env.server -f compose.server.yaml ps
```

Check https://192.168.8.200:8443/login/ using a trusted certificate and the
existing login. The Caddy private CA must be trusted on each client device and
the Windows automation VM. Export only its public root certificate:

```bash
docker compose --env-file .env.server -f compose.server.yaml cp proxy:/data/caddy/pki/authorities/local/root.crt ./ebir-root.crt
```

Verify the fingerprint over the trusted SSH connection before installing the
certificate. Do not distribute the CA private key. See
[Caddy local HTTPS](https://caddyserver.com/docs/automatic-https#local-https).

After validating the mounted share and credentials, start background services:

```bash
docker compose --env-file .env.server -f compose.server.yaml --profile background up -d
```

Receipts run sequentially every 60 seconds after each pass. COR scanning repeats
every 15 minutes after each pass and resumes saved scans. Only one instance of
each should run with this SQLite database. Existing finalized records are not
submitted again. Submission flags default off. Read-only verification on 2 October 2026 found the live 1601C, 1601EQ and 0619F switches enabled. Each return still needs approval and matching worker capabilities; deployments must review their own settings rather than assume these flags are on.

## Backup and rollback

Back up app-data, client-files-data, the protected `.env.server`, Caddy volumes
and the actual SMB archive. Stop web/cards/receipts while taking a filesystem
copy of the database plus media, or use SQLite backup with an application-aware
media snapshot. Regularly restore to an isolated test stack to verify backups.

To stop this stack, use the same compose/env arguments with `down`, without
`--volumes`. For rollback before server writes, stop this stack and restore the
old worker endpoint/scheduler. After server writes, reconcile or migrate the
latest database and media back before restarting the source. Never run both.
