# COR reader and reviewed filing setup

Reviewed 2 October 2026. Saved records, source documents and unreviewed scan suggestions are distinct; [client navigation](client-directory-integration.md) explains where to open the COR.

From a directory client, select the latest correct COR PDF and click **Read COR**. The dashboard checks the signed, user-bound document reference against the current registration list, downloads that one PDF, renders its pages locally, and sends the images through the configured GDS provider. Limits: 20 MB PDF, 1–6 pages, maximum 3000 pixels along the longest rendered edge. No client document was used for implementation tests.

Configuration: ignored `secrets/gds-gateway.env` contains `GDS_BASE_URL` (HTTPS API base ending `/v1`), `GDS_API_KEY`, and `GDS_MODEL`. `COR_NODE_MODULES` in `.env` points to the existing local PDF.js/canvas modules. The server image uses `/app/deploy/docker/node_modules`; local development must point to its installed modules. Restart Django after changing credentials. Keys are never rendered in HTML or logged by the reader.

GDS returns SSE, including possible error events even after HTTP 200. The client assembles only content deltas, requires completion, parses JSON, and validates the result structure. Tools are disabled with `tool_choice: none`. Native JSON mode is omitted because this gateway's injected tools caused an upstream incompatibility; malformed JSON fails closed. The configured gateway can have provider fallback rules: its operator controls the eventual provider destination.

The review shows table rows, source page/evidence, warnings, editable taxpayer details and selectable filing cards. Missing details must be filled in manually. TIN digits and branch codes are never padded. Alternative annual forms and conflicting VAT/percentage-tax suggestions require review. No deadlines are calculated. Historical 2550M and annual registration-fee 0605 entries are flagged rather than configured. Other unrecognized forms stay visible as source rows; the initial selection catalog is 1701, 1701A, 1701Q, 2550Q, 0619E, 1601EQ, 1604E and 2551Q.

Saving requires client/profile creation permissions and confirmation. The source hash is checked again. An atomic transaction creates an audited client and profiles plus a RegistrationSetup source record. Existing TIN/branch matches are refused for manual reconciliation, never automatically merged. Concurrent duplicate folder saves are constrained by the unique folder and deterministic client code. Replaying a completed review opens the existing client. No work order is queued and no BIR submission occurs. Existing dummy/test clients are preserved. The current preparation definitions are 2551Q, 1601C, 1601EQ and 0619F. A saved active profile and enabled catalog entry are required; other cards remain unavailable for preparation.

Review drafts contain extracted client information in the process-local Django cache for one hour. A restart, cache eviction, or another worker process can make a draft unavailable; production deployments should configure an access-controlled shared cache. Saved provenance includes the source path, SHA-256, unverified transcript, confirmed form selection, reviewing user and timestamp. The PDF itself remains in the office share. Company taxpayer fields can be edited through Company details ? Edit details. That does not replace the source COR, rerun extraction, or update existing work-order snapshots. Replacing a reviewed source setup is a separate operation, not an effect of editing company fields.

Validation: fake-image GDS vision connection, a synthetic scanned COR PDF through rendering and vision, mocked gateway failure/uncertainty tests, permission/CSRF checks, source-change rejection, duplicate prevention, replay behavior and no-task creation checks.

## Saved company filing cards

Company pages render registration cards from `RegistrationCardScan` in the database.
They no longer launch AI scans on page load. These are unreviewed suggestions;
creating filing profiles still requires the existing review, permissions and source
hash verification. No work orders are created by a background scan.

Run `python manage.py generate_registration_cards` to scan the directory. Completed
companies are skipped on resume; interrupted and failed companies are retried.
Only run one batch at a time. `--company "Company name"` limits the batch.
Use `--refresh` after source documents change: identical PDF hashes reuse saved
extractions, and deleted documents are removed after a successful directory read.
It can run as an explicit batch command. In the Linux deployment, the `cards` background service also runs it repeatedly, waiting 15 minutes after each pass. Avoid a competing manual batch.

Progress is stored as PENDING, SCANNING, READY, EMPTY or ERROR. EMPTY means the
source search completed with no matching PDFs; ERROR does not imply no filings.
The initial local batch logs to ignored `secrets/registration-cards-batch.log`.

## Choosing among multiple certificates

Company pages apply `cor_selection.select_documents` to saved scans without calling AI.
Exact complete TIN/branch and normalized taxpayer name define separate groups. Only
explicit `Date OCN Generated: Month D, YYYY` transcript dates determine recency;
filenames, PDF timestamps, TIN issuance and filing dates are never used.
Missing/conflicting dates retain separate groups. Same-date copies must agree on
OCN, RDO, normalized address and form codes before one copy is preferred.
Equivalent copies are ranked by AI visual readability score when available, then
missing identity/address fields and uncertain extraction rows. Older scans without
scores use the extraction evidence; this is not a fresh visual comparison.
Manual SHA-based preferences remain authoritative. All source records and PDFs
are retained, and omitted card groups remain accessible under Other COR copies.
A new unmatched source hash causes a stale manual preference to fall back to the
normal selection rules. Reviewed client setups are not silently changed.
