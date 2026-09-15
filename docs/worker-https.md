# Hyper-V worker HTTPS connection

Prepared 2026-09-14. Dashboard host: 192.168.8.148/21, Domain network profile.
VM: 192.168.14.135/21. Gateway reported by VM: 192.168.8.1.
Host-to-VM ping succeeds; VM-to-host ping times out. Test TCP below instead.

## Components and boundary

- Dashboard remains at http://127.0.0.1:8001 for local browser use.
- Caddy 2.11.4 listens exclusively on 192.168.8.148 TCP 8443 (HTTP/1.1 and HTTP/2).
- Only peer 192.168.14.135 and paths /api/agent/* reach Django. Other requests
  receive 403; forged forwarding headers cannot change the peer matcher.
- Worker endpoints additionally require the existing bearer credential.
- Host header is rewritten to 127.0.0.1:8001 for the loopback upstream.
  Django ALLOWED_HOSTS stays loopback-only. No public dashboard/admin/media route.
- Caddy admin API, HTTP redirects, automatic trust installation and HTTP/3 are off.
- Protected dashboard PDFs stay in media; XML remains in the automation VM.
- This is a supervised fake-data prototype using the existing development
  server, not a production deployment or unattended Windows service.

## On the dashboard host: Administrator PowerShell

The Codex shell is not elevated, so the firewall has NOT been changed.
Run the reviewed script (it limits source IP, destination IP, TCP port, executable
and Domain profile; it does not enable ping or change any network profile):

```powershell
& 'C:\Users\A.Heiner.PDMN\Music\tax-automation\deploy\Enable-WorkerFirewall.ps1'
```

If domain policy rejects or overrides the rule, ask the office administrator
to apply this same scoped rule; do not disable the firewall or broaden the rule.

## On the VM: normal PowerShell

```powershell
Test-NetConnection 192.168.8.148 -Port 8443
```

Expect TcpTestSucceeded: True. This checks TCP only, not certificate trust.
Next copy ONLY `worker\dashboard-root.crt` from the dashboard workspace to
`C:\TaxAutomation\dashboard-root.crt` on the VM. It is the public CA certificate.
Never copy secrets\caddy: that directory contains the CA private keys.
Compare SHA256 output on both computers before importing:

```powershell
Get-FileHash -LiteralPath C:\TaxAutomation\dashboard-root.crt -Algorithm SHA256
Import-Certificate -FilePath C:\TaxAutomation\dashboard-root.crt -CertStoreLocation Cert:\CurrentUser\Root
```

Run the import as the same Windows user who runs PAD. This explicitly trusts
this dashboard's local certificate authority for that user. No TLS validation
bypass is used. The host can verify with its public root file without importing
the CA into its own trust store.

Follow worker-api-setup.md to provision the worker with
`--base-url https://192.168.8.148:8443` and copy its credential privately to the VM.
Run WorkerBridge.ps1 -Action Health first. Do not Poll until ready to run the
queued fake-data job. No credential or work attempt was created by HTTPS setup.

## Restart, rollback and local artifacts

The proxy was started hidden for this session. After reboot, start Django on
127.0.0.1:8001 and run deploy\Start-WorkerHttps.ps1 from normal PowerShell.
This script refuses an occupied port. Runtime logs are in ignored logs/.
The Caddy executable is ignored under tools/caddy; its official Windows AMD64
ZIP was checked against the release's SHA512 checksum file before extraction.
CA storage is ignored under secrets/caddy, with inheritance removed and access
granted only to the current user and SYSTEM. The copied public certificate is
also ignored, since it belongs to this local deployment.

To stop, inspect the owner of TCP 8443, confirm it is this workspace's caddy.exe,
then stop that process by its verified PID. Remove the firewall rule using
`Remove-NetFirewallRule -Name 'eBIR-Worker-HTTPS-8443'` in Administrator PowerShell.
Remove only this imported CA's matching thumbprint from the VM user trust store
if retiring the deployment. Do not remove unrelated certificates.
If either IP changes, review the proxy, firewall, certificate and worker base URL
together. No static IP, DHCP reservation, switch or router changes were made.

## Verification performed

- Official Caddy archive SHA512 matched; Caddy 2.11.4 configuration validation passed.
- Live listener verified at 192.168.8.148:8443 only.
- Python TLS client verified the certificate chain and IP using the local CA;
  host-origin requests to API health, admin and media each returned expected 403.
- Django system check passed. VM-allowed path, firewall policy, certificate
  import and authenticated VM health still require the VM-side steps above.
- No queued task claimed, no PAD run, no BIR submission.

References: [Caddy global options](https://caddyserver.com/docs/caddyfile/options),
[peer matchers](https://caddyserver.com/docs/caddyfile/matchers),
[reverse proxy](https://caddyserver.com/docs/caddyfile/directives/reverse_proxy),
[Windows firewall rules](https://learn.microsoft.com/en-us/powershell/module/netsecurity/new-netfirewallrule),
[certificate import](https://learn.microsoft.com/en-us/powershell/module/pki/import-certificate).
