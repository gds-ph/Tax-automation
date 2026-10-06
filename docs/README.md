# Project documentation

Reviewed 2 October 2026 against the application source and selected read-only server checks. Dates are Asia/Manila. Live settings can change; an enabled route is not proof of a successful PAD or BIR execution.

Cancellation instructions and admin-only installer access updated 6 October 2026; the operational snapshot below retains its original review date.

## Start here

| Topic | Guide |
| --- | --- |
| Components and current operating boundaries | [Architecture](architecture.md) |
| Clients, Saved tab, company editing and COR access | [Client directory](client-directory-integration.md) |
| COR extraction, review and saved cards | [COR reader](cor-reader.md) |
| Parent worker setup and API | [Worker setup](worker-api-setup.md) and [polling loop](dashboard-worker-loop.md) |
| Failed preparation, release and retry | [Preparation recovery](worker-preparation-recovery.md) |
| Submission approval and evidence | [Stage 2](stage2-connection.md) |
| Form contracts | [1601C](1601c-integration.md), [1601EQ](1601eq-integration.md), [0619F](0619f-integration.md) |
| Receipts and final package destinations | [Receipt guide](bir-receipts.md) |
| Prepared PDFs automatically copied to client folders | [Prepared return archive](prepared-return-archive.md) |
| Cancellation eligibility, admin installer and VM XML cleanup | [Cancellation guide](cancelled-xml-cleanup.md) |
| Submitted XML on the VM | [XML archive](submitted-xml-archive.md) |
| Server and local trial | [Linux deployment](docker-server.md), [Docker trial](docker-local.md) |
| Login permissions | [Feishu and password login](feishu-login.md) |
| Business overview | [White paper](tax-automation-white-paper.md) |

## Verified operational snapshot

- Server: `https://192.168.8.200:8443`; Windows PAD runs separately.
- Live preparation catalog: 2551Q, 1601C, 1601EQ and 0619F.
- Server switches `ENABLE_1601C_SUBMISSION`, `ENABLE_1601EQ_SUBMISSION` and `ENABLE_0619F_SUBMISSION` were all True when checked on 2 October 2026. Defaults remain off in source. Every submission still requires its own approval and worker checks.
- All active users receive client view/edit permission on sign-in. Other permissions depend on roles and sign-in provisioning; Feishu currently also grants work-order creation/change and Stage 2 approval. Worker recovery remains operator-only.
- Retry preparation retains the same order and prior attempts. Releasing an interrupted run requires confirmation that both PAD flows stopped. The updated VM bridge clears only its matching released preparation journal when restarted.
- Monthly final packages use `BIR/<filing year>/01 JANUARY/` through `12 DECEMBER/`, with `FILED RETURNS` as the alternate archive root. Quarterly packages currently remain directly under that root.

## Historical records

The milestone reports, client architecture/dashboard reports, worker API implementation report and original worker HTTPS guide describe their delivery dates. Their old ports, permissions, feature omissions and test counts are historical, not current operating instructions. The 0619F conversion guide is retained as an action-mapping reference; later integration notes supersede its unfinished-work statements.

No documents claim current live PAD reliability solely from unit tests, configured capabilities or submission flags.
