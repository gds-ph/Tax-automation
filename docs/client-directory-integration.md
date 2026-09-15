# Office client directory

The eBIR Clients page combines configured Django clients with live folder names from the local client-files app. Directory entries link to COR/2303/Certificate of Registration documents. Search and pagination cover both sources. Dot-prefixed folders (including `.trash`) are excluded.

Set `CLIENT_FILES_URL=http://127.0.0.1:3021` in the dashboard's local `.env`, then restart Django if it does not reload automatically. Keep the client-files service and office share available. An empty setting disables the connection. The connection only permits HTTP loopback addresses and rejects redirects; user input cannot change its destination.

Names are cached for 60 seconds. Registration folders are searched when opening a directory client, rather than scanning all client folders on every list request. Source outages show a message while configured clients remain available. Documents require dashboard client-view permission and an expiring user-bound link; the current registration list is checked again before retrieval. Downloads are limited to 50 MB. PDFs open in the browser; other formats download.

This is a read-only directory connection, not an import of filing profiles. It creates no client records or work orders, modifies no shared files, and guesses no TIN, RDO, taxpayer type or ATC. A configured client and a same-named directory folder remain distinct entries until an explicit identity-linking workflow is implemented.

Verification: automated tests cover search/pagination, hidden-folder exclusion, invalid document paths, permissions, signed links, source failures and unchanged filing data. Live checks confirmed 954 visible directory names plus the existing configured test client, and a registration document listing.
