# Feishu sign-in

Reviewed 2 October 2026. The permission policy below reflects current code; it does not change account permissions.

The existing password login remains available. Feishu is enabled only when
FEISHU_APP_ID, FEISHU_APP_SECRET, FEISHU_TENANT_KEY and FEISHU_REDIRECT_URI are set.
The redirect URI registered in Feishu must match exactly:

    https://192.168.8.200:8443/auth/feishu/callback/

Run on the Linux host:

```bash
python3 ~/ebir-deployment/tax-automation/deploy/configure-feishu.py
```

Enter the current secret at the hidden prompt, verify the organization name,
and confirm. The script queries the app's tenant using Feishu, stores the
configuration in the protected .env.server file, and recreates web. If Feishu
denies the organization query, check the app's permissions in its console.
Never paste secrets into commands, chat, or source control. A shared app secret
rotation must also be applied to its other integrations, including QuickBooks.

Publish the required app configuration and make the app available to the
organization's employees. Each browser needs LAN access and trust in the local
HTTPS certificate. This does not make the app reachable from outside the LAN.

On each successful Feishu sign-in, provisioning grants client/work-order/profile/form/snapshot/PDF viewing, client and work-order add/change, filing-profile creation, and Stage 2 approval. These grants are reapplied at sign-in; Feishu users are not view-only. No local password, staff/superuser flag, mailbox editing or worker-management permission is granted by this flow.

All active password and Feishu users additionally receive `view_client` and `change_client` through the shared login signal. This does not grant every user preparation, approval or worker recovery. Regular preparers may retry an eligible failed preparation; Release interrupted run requires `workorders.view_workorder`, `workorders.change_workorder` and `automation_api.change_agent`. Company edits leave existing filing snapshots unchanged.
Identity is keyed by app ID, tenant key and open ID. Email addresses never link
accounts automatically. Existing local administrators continue using password
login unless an administrator explicitly manages their identity mapping.

OAuth state is session-bound, expires after ten minutes, and is consumed on
callback. PKCE binds the authorization code to the initiating session. Tokens
are used only for user-info lookup and are not persisted. User-info tenant keys
must match the configured organization. Inactive Django users cannot sign in.
Account deactivation is checked on login and on normal Django session access;
Feishu employee offboarding does not immediately revoke an existing Django
session, so disable the local account when removing access.

Validation includes other-tenant rejection, expired/invalid/reused state, CSRF,
inactive accounts, no email-based linking, default permissions and missing
configuration. For a new deployment, verify a real employee login after console setup; code tests alone do not verify tenant configuration.

References: [authorization codes](https://open.feishu.cn/document/authentication-management/access-token/obtain-oauth-code),
[token exchange](https://open.feishu.cn/document/authentication-management/access-token/get-user-access-token),
[user information](https://open.feishu.cn/document/server-docs/authentication-management/login-state-management/get).
