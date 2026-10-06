# Office client directory and the Clients page (search, Saved tab)

Reviewed 2 October 2026. See [COR setup](cor-reader.md) and [current architecture](architecture.md).

The eBIR Clients page combines configured Django clients with live folder names from the local client-files app. Directory entries link to COR/2303/Certificate of Registration documents. Search and pagination cover both sources. Dot-prefixed folders (including `.trash`) are excluded.

Set `CLIENT_FILES_URL=http://127.0.0.1:3021` in the dashboard's local `.env`, then restart Django if it does not reload automatically. Keep the client-files service and office share available. An empty setting disables the connection. Local defaults allow loopback HTTP. Server settings explicitly allow the internal `http://client-files:3020` service. Redirects are rejected; user input cannot change the destination.

Names are cached for 60 seconds. Registration folders are searched when opening a directory client, rather than scanning all client folders on every list request. Source outages show a message while configured clients remain available. Documents require dashboard client-view permission and an expiring user-bound link; the current registration list is checked again before retrieval. Downloads are limited to 50 MB. PDFs open in the browser; other formats download.

Browsing registration documents is read-only. The separate reviewed COR workflow can create a client and filing profiles with source provenance; ordinary browsing does not do so. The final-package workflow can create filing-year/month folders and upload PDFs to the office share. Therefore the integration as a whole is not read-only. Existing reviewed directory setups link to their configured client; names alone must not be used to merge taxpayers.

Verification: automated tests cover search/pagination, hidden-folder exclusion, invalid document paths, permissions, signed links, source failures and unchanged filing data. Live checks confirmed 954 visible directory names plus the existing configured test client, and a registration document listing.

## Saved clients (bookmarking a company)

Staff can keep the companies they work with most on a personal **Saved** tab of the **Clients** page.

To save a company:

1. Open **Clients** in the left menu and choose the **All clients** tab.
2. Find the company; use **Find a client** to search by name or code if needed.
3. Click the **star** (☆) in the top-right corner of the company's card. The star fills in (★) to show the
   company is saved.

Configured clients and client-directory entries without a client record yet can both be saved.

To see saved companies, open **Clients** and choose the **Saved** tab next to **All clients**; the tab shows
how many companies are saved. Search and the grid/list view work the same way as on **All clients**. To remove
a company, click its filled star (★) on either tab.

The Saved list is personal: other staff do not see it, and saving a company does not change who can open it.
It is stored with the dashboard account, so it follows the user to any computer or browser they sign in with.
With nothing saved, the **Saved** tab says "No saved companies yet" and links to **All clients**.

## Company details, filing cards and COR access

Company pages separate Company details, Filing cards and History. All active signed-in users can edit company details; existing filings retain their snapshots. Filing cards are grouped into Monthly, Quarterly, Annual and Special filing. Only active client profiles appear, and a card does not imply automation is available. The old generic Create work order routes now redirect to Clients.

On Company details, open **Registration documents** beneath **Reviewed COR setup** to locate the source COR. This tab does not currently have a direct View 2303 / COR button. Directory card views can show that button when a source link is available. The PDF stays on the office share; a reviewed record is not an embedded PDF copy. A share outage can leave saved details visible while document access fails.
