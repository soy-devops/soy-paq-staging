# SoyPaq WMS — Project Overview

Living reference for what this project is, the decisions made so far, and what's next. Update this
alongside `CHANGELOG.md` (exact shipped history) and `ui/DESIGN.md` (frontend patterns in depth) —
this file is the higher-level map that ties them together.

## What this is

A warehouse management app built by **Soy-Ops** (the Soy parent company's 3PL division, "SoyPaq")
to run logistics on behalf of **Example Company**, currently Soy-Ops' one client, out of a Miami warehouse.
Example Company is the client, not the operator — Soy-Ops staff (the `User` accounts in this ERPNext
instance) run pick/pack/ship on Example Company's behalf until Example Company's own storefront is connected to
ERPNext directly. `Company = Example Company` is deliberate, not a modeling mistake: Example Company needs its own
legal/tax books, so its Purchase Orders, Sales Orders, and Delivery Notes are Example Company's own real
accounting transactions — Soy-Ops is the service provider operating the software and warehouse, not
the entity buying or selling the inventory. `TEST COMPANY CLIENT` was a throwaway local-dev fixture
and has been deleted. **`Example Legacy Co` is not** — it turned out to carry 11 submitted Journal Entries
under the **Soy** company's books (real Fulfillment/Storage/Shipping revenue, and a **$693.36
outstanding receivable**), so ERPNext correctly refuses to delete it. Treat it as a real Soy-Ops
client record, not test data. Example Company remains the only client the *WMS* operates on.

Until Example Company's storefront is connected, order data arrives as a screenshot/photo of a sale from
Example Company (think: a paper invoice) and gets entered manually. It's a custom Frappe app (`soypaq`) with
a mobile-first Vue frontend, running against real ERPNext doctypes and real stock movements — not a
mocked demo layer.

Core workflow: **Receive → Pick → Pack → Ship**, each stage backed by its own doctype (`Inbound ASN`
/ `Inbound Package`, `Pick Task`, `Pack Task`, `Shipment Task`) and real ERPNext side effects
(Stock Entries on receipt, a Delivery Note on ship).

Currently running as a local Docker demo/test environment, with the explicit goal of eventually
going to production.

## Architecture at a glance

- **Backend**: `apps/soypaq/soypaq/api.py` — whitelisted methods consumed by the mobile app
- **Frontend**: `apps/soypaq/ui` (Vue 3 + Vite) — builds to `apps/soypaq/soypaq/public/wms/`, served
  via `apps/soypaq/soypaq/www/soypaq-wms.py` / `.html`
- **Custom doctypes**: Inbound ASN (+ Item, Package), Inbound Package (+ Item), Pick Task (+ Item),
  Pack Task (+ Item), Shipment Task (+ Item), Receiving Desk — **12 doctypes, now exported to
  source-controlled JSON** under `soypaq/soypaq/doctype/<name>/<name>.json`, each with a controller
  `.py`. They used to be `custom=1` (Desk-UI-only, database-resident); they are now standard
  app-owned doctypes, so a fresh `bench install-app soypaq` recreates the full schema from code.
  Schema changes should now be made with `developer_mode=1` and committed as JSON diffs, not made
  directly against a running site and left there.
- **Warehouse structure**: company `Example Company` → `Example Company - S` → `Receiving` / `Storage` (bins A1–A6)
  / `PickPack` / `Returns` / `Damaged`
- **Deploy note (local dev)**: the running containers hold a *baked copy* of the app, not a live
  mount of this repo — changes need `docker cp` into `erpnext-backend-1` / `erpnext-frontend-1`
  plus a container restart to take effect (see recent session history for the exact commands).
  After changing `www/soypaq-wms.html` specifically, also run
  `bench --site frontend clear-cache` - Frappe's Redis page cache can keep serving a stale
  version-labeled HTML shell even after the file on disk (and the actual JS/CSS content) is
  current, which is confusing to debug since the app still *functions* correctly, just under
  the wrong version label. **`sites/assets` is a symlink to a path local to each container**, not
  the shared volume it looks like - backend and frontend each hold their own separate copy, so a
  built frontend asset change (`soypaq/public/wms/*`) needs `docker cp` into **both**
  `erpnext-backend-1` and `erpnext-frontend-1` (nginx on frontend only ever reads its own local
  copy). Python file changes need `docker cp` into `erpnext-backend-1` specifically (that's the
  container that serves whitelisted API calls), plus `bench --site frontend migrate` if a patch
  added new custom fields. Also: Frappe sends `Cache-Control: private,max-age=300` on this page even
  with `context.no_cache=1` - when verifying a fresh deploy in a browser, force a cache-busting query
  string on the page URL itself, don't trust a plain reload. Before chasing any of this, check
  server state directly first (`curl -I`, `docker exec ... cat/grep`) - it's far cheaper than
  looping through browser screenshots to test the same hypothesis.
- **Shipping labels**: real Shippo integration (`soypaq/shippo_client.py`), not a placeholder. Needs
  `SHIPPO_API_KEY` in `.env`, wired through `pwd.yml` to backend/queue-long/queue-short/scheduler -
  setting the key alone isn't enough, those containers need recreating (`docker compose up -d
  --force-recreate ...`) to actually pick it up as an env var.

## Decisions made so far

### Inventory & stock accuracy
- Removed the Pick→PickPack stock transfer — stock stays in its real Storage bin through Pick and
  Pack, and moves exactly once, at Ship, via a real Delivery Note
- `_default_warehouse()` scoped to the Example Company (was unscoped — could silently default to a
  Soy-company warehouse), zone-aware, skips Damaged/Returns as a fallback
- Fixed naming series for Pack Task and Inbound ASN (were untracked, generating random hash names)
- Customer fallback pinned to `DEFAULT_TEST_CUSTOMER = "Example Customer"`, and it now **throws** rather
  than silently falling back to whichever Customer sorts first alphabetically. The alphabetical
  fallback was actively dangerous: with `TEST COMPANY CLIENT` deleted it would have started
  attributing manually created test tasks to **Example Legacy Co**, a real client with live receivables.
- Removed Priority tiers entirely — the field existed and rendered a badge but never drove sorting,
  routing, or any real behavior (dormant on Pick Task's schema in case it's revived later)
- Header now shows the real signed-in user's name and actual role, not a hardcoded placeholder
- `Warehouse Operator` role granted real DocType permissions (was desk-access-only with read/write/
  create limited to Inbound ASN/Inbound Package; now also covers Pick Task, Pack Task, Shipment
  Task, and submit rights on Stock Entry/Delivery Note, plus read on the supporting lookups) — a
  real operator login can now actually use the app, not just Administrator

### App packaging & production installability
The app was previously **not installable anywhere but this dev database**. Fixed:
- All 12 doctypes converted `custom=1` → `custom=0` and exported to JSON in the app. The `Module
  Def` for SoyPaq was *also* `custom=1`, which blocks export with `Package must be set for custom
  Module` — it has to be flipped first, or every doctype export fails.
- Generated the 12 missing controller `.py` files. Frappe resolves the class as
  `doctype.replace(" ", "").replace("-", "")`, so `Inbound ASN` → `InboundASN`.
- The 12 fields previously added as **Custom Fields by patches are now real fields in the doctype
  JSON** (`company`/`supplier`/`purchase_order`, `assigned_user`, `box_confirmed`, `packed_qty`,
  `exception_reason`, `received_qty`, `assigned_bin`, `shipping_label_url`,
  `shippo_transaction_id`). They belong to the app's own doctypes, so Custom Fields were the wrong
  mechanism.
- `soypaq/install.py` + `after_install` hook now handles anything a *fresh* site needs (currently
  the desktop icon). **Patches do not run on a fresh install** — see the bug note below.
- `soypaq.patches.remove_legacy_custom_fields` runs in **`pre_model_sync`** to delete the old Custom
  Field rows *before* the doctype JSON syncs, avoiding a duplicate-fieldname clash on existing
  sites. Column data survives untouched (the sync re-declares an identical column).
- `required_apps = ["frappe/erpnext"]` declared in `hooks.py`.
- `Receiving Desk` is `issingle=1` — it legitimately has no `tab...` table; that's not a bug.

**Verified both paths**, not just one: a from-scratch `bench new-site` + `install-app soypaq`
(all 12 doctypes, fields, DB columns, controllers, naming series, desktop icon) *and* `bench
migrate` on the existing dev site (0 leftover Custom Fields, all existing data preserved), plus a
functional `create_pick_task` → `get_mobile_bootstrap` round trip.

### Task lifecycle & UX philosophy
Full detail and rationale lives in `ui/DESIGN.md`. Summary:
- Tasks are globally visible to every operator — no per-user/per-station filtering, since ERPNext's
  own user/role/permission system already governs who can do what
- **Shipped**: assignment happens at Start (claim), not at creation — `claim_task`/`release_task`
  set/clear `assigned_to`/`assigned_user`, and creation no longer auto-assigns. Claiming something
  someone else actively holds is blocked outright, and so is claiming a *second, different* task
  while you already hold one unfinished — one operator, one active job, enforced server-side.
- **Shipped**: there is exactly one task-list implementation in the whole app. My Tasks (Open /
  Active / History, all four stages) and each stage's own list (same UI, filtered to that kind) are
  the same code path — not four screens reimplementing the same pattern. Every task card opens a
  details drawer (items with images, qty, customer, claim state) before Start/Continue is even
  offered — no path to starting a task blind, and no per-stage screen that bypasses the claim system
  the way the old inline "Start" buttons used to.
- **Not yet built**: the *timeout* half of claim-conflict handling — a stale claim currently only
  clears via the manual "Release back to queue" action, not automatically. Policy agreed, not wired
  up (see Next goals).
- **Not yet built**: Receive (Inbound Package) has no assignment field, so it can be opened and
  worked by anyone but never shows up in "Active" with a named claimant the way Pick/Pack/Ship do.
- Two task-creation paths stay side by side: typed item-code entry, and browsing Live
  Inventory/Staged bins to build up a task — because a worker with a paper invoice sometimes has
  clean SKUs to type and sometimes needs to browse instead (inventory-browsing side still unbuilt)
- Item images/thumbnails render consistently everywhere a task or item appears
- "Open in Desk" consolidates to one entry point instead of scattered per-record buttons (deferred —
  see Next goals)
- Minor, accepted regression: the old completed-detail views let you jump straight from a finished
  Pick to its linked Pack, or a finished Pack to its linked Shipment. That shortcut didn't carry
  over to the new drawer and hasn't been rebuilt - the data/workflow itself is unaffected, it's a
  navigational convenience worth revisiting rather than a functional loss

### Process
- Every change is communicated (and logged) with an explicit Backend/Frontend split
- `APP_VERSION` / `APP_BUILD_DATE` (shown in Settings) bump on every shipped change set, logged in
  `CHANGELOG.md` with the same split
- Business-model-dependent questions get asked, not assumed (see Open decisions below)
- Every live-tested change set gets an actual live test, not just a compile check - the two bugs in
  v0.3.0/v0.3.1 (two-active-jobs, and error toasts showing "EXPECTATION FAILED" instead of the real
  message) were both caught this way, not by inspection

### Bugs found and fixed while testing (worth knowing about)
- **Error messages were never reaching the user.** `frappe.throw()`'s real text lives in a response
  field (`_server_messages`) the hand-written `pickApi`/`fetchApi` fetch calls weren't reading -
  every validation error in the app was silently showing generic HTTP status text instead. This
  means error messages written earlier in the session may be the first time they've ever actually
  displayed correctly.
- **One operator could hold two active jobs at once** (e.g. start a Pick while a Pack was still
  active) because the per-stage screens' own old "Start" buttons never called `claim_task` at all -
  only My Tasks did. Fixed by both a backend guard and by unifying every task list onto one code
  path (see above), so there's no longer a second door that skips the claim system.
- **CSRF token was always null in a real browser session** (v0.4.1) - a stale deployed copy of
  `soypaq-wms.html` had Frappe's CSRF marker as a literal inert comment instead of the real template
  tag, so every write action would have failed the moment a real operator (not bench console/curl)
  used the app. Never caught before because no prior testing exercised the actual deployed page.
- **Delivery Note submission failed on zero-valuation-rate items** (v0.4.2) - found by running a
  full Receive→Ship walkthrough through the real UI. `_create_delivery_note()` now sets
  `allow_zero_valuation_rate=1` when an item has no real valuation rate, which is the normal state
  for test/demo stock. Fixed and reverified with a real Delivery Note submission
  (`MAT-DN-2026-00003`).
- **Patches never run on a fresh install — the app would have shipped broken.** Frappe marks all
  existing patches as already-executed when you `install-app` onto a new site; they only actually
  run on *upgrades*. Every custom field the app relied on was therefore silently absent on a clean
  install, so `pack_item()` would have thrown *"Run the SoyPaq migration before packing items"* on
  day one in production. Only surfaced by actually building a throwaway site and installing onto it
  — a compile check, a `migrate` on the dev site, and even the first `install-app` run all looked
  clean. Anything a fresh site needs belongs in `after_install`, not a patch.
- **Pattern worth naming**: three of the last four real bugs (CSRF, zero-valuation, the original
  two-active-jobs) were only found by testing through the actual browser UI end-to-end, not by
  compile checks or direct API calls. Prefer a real UI walkthrough over `bench console`/`curl` when
  verifying anything that touches a write path.

## Open decisions — waiting on you

| Item | Status |
|---|---|
| Receiving → Purchase Receipt / Ship → Delivery Note as Example Company's real books | **Resolved in principle** — both are the *correct* long-term doctypes now that `Company = Example Company` is understood to be Example Company's own real legal entity, not a modeling mismatch. Both are blocked purely on real upstream data (a real PO to receive against; a real Sales Order to ship against), not on redesign. Inbound ASN already has unused `supplier`/`purchase_order` fields anticipating this. |
| "Open in Desk" single-button placement | **Deferred** — you mentioned a fuller UI redesign is coming; holding this specific change until then rather than doing partial surgery now |
| Sales Order Customer granularity for manually-entered Example Company orders | **Open** — one shared placeholder Customer (e.g. "Example Company Storefront") vs. a real distinct Customer per end-buyer from each screenshot. Shipping address uniqueness doesn't depend on this either way (Address is a separate per-order record in ERPNext regardless of Customer) - this is a pure accounting-granularity call for Example Company/the accountant, not a technical constraint. |
| Splitting `apps/soypaq` into its own Git repo | **Open — this is the last blocker for Frappe Cloud.** The app is currently tracked inside the parent `frappe_docker` repo. Frappe Cloud installs custom apps *only* from a standalone Git repository. Needs a GitHub org + repo name before it can be done. |
| Opening-stock import target (`stockMaster.csv`) | **Open, but one wrong answer to avoid** — do **not** Data Import straight into `Bin`. Bin is a derived table computed from Stock Ledger Entries; writing to it directly creates quantities with no matching ledger entry and breaks valuation the moment any real Stock Entry / Delivery Note touches that item. Use **Stock Reconciliation** for opening balances. |
| Does the `Soy` company travel to production? | **Open** — Example Legacy Co's entire financial history (46 Journal Entries, 106 GL Entries) lives in **Soy**'s books, while the WMS runs on **Example Company**. That split is what made customer cleanup messy; worth settling deliberately before any data migration. |
| Delivery Note pricing source | **Open** — `_create_delivery_note()` currently takes `rate` from the Item's **valuation rate** (cost), not from a Price List. Once `itemPrice.csv` populates real `Item Price` records, shipped Delivery Notes will still post at cost unless this is switched to standard price-list resolution. |
| Real parcel weight/dimensions for Shippo (currently one fixed default box for every shipment) | **Superseded by the manual entry-at-label-time plan below** — no longer planned as an Item-level weight field |
| 3PL tenant modelling: Company-per-client vs Customer-per-client | **Resolved — Customer-per-client is the default.** A new 3PL client is a Customer, not a Company. This is what the seed script and the import templates target. |
| Inventory write-back: voucher volume | **Deferred, but flagged as important.** Every submitted Stock Reconciliation posts GL entries. Floor-frequency qty adjustments would generate high voucher and ledger volume, which grows the database and therefore future hosting cost. Options when revisited: accept it, batch adjustments into one periodic voucher, or use Material Receipt/Issue for small deltas. Not blocking the first build. |
| Warehouse-operator permissions for stock writes | **Deferred, low priority.** Adjusting or moving stock from the WMS needs write access to Stock Reconciliation / Stock Entry. This will map to a real ERPNext user role rather than a WMS-only permission concept. Everything currently runs as Administrator. |
| Condition / quality flagging from the Inventory screen | **Deferred.** QC is prioritised at **Receive**, not from Inventory. `Inventory Action` therefore ships without the Flag path; damaged/returns stock keeps moving by warehouse transfer (`Damaged` / `Returns` warehouses already exist). Expected to matter later, so the doctype leaves room for it. |

## Phase 1 build status — shipped in v0.5.0, UX follow-up v0.5.1, verified v0.5.2, feedback fixes v0.5.3 (all 2026-09-03)

**v0.5.3:** the `DEFAULT_COMPANY`/`DEFAULT_TEST_CUSTOMER` sanitized-constant break flagged since v0.5.0
is now fixed for `create_pick_task` specifically (both the warehouse and customer fallback), using the
same zone/company-resolution pattern as `start_receiving_session`. It is **not yet fixed** for
`create_inbound_asn`'s blank-customer path (`_resolve_customer`'s own `DEFAULT_TEST_CUSTOMER` fallback) -
only touched where a real bug was hit and verified. Also fixed: the My Tasks history preview showing
0 for every Receive line (wrong field mapped), and the item-detail header missing its thumbnail.

**Open design question, not yet built:** the "Start receiving" popup's Customer and Warehouse fields are
free text with no reference for what to type. Warehouses are Company-scoped in ERPNext with no formal
Customer link; on this site Customer and Company share a name by convention only. Proposed: Customer as
a real dropdown of existing Customers, Warehouse as a dropdown scoped to that customer's resolved
company once chosen. Not built - would formalize the naming-convention assumption, which is the kind of
thing `SoyPaq Settings` is meant to hold instead of code.

**Receive Phase 1 was not actually reachable through the UI until v0.5.2.** The backend
(`start_receiving_session`, `receive_scan`, `stage_item`, `complete_receipt`) was verified directly
against the API in v0.5.0, but no button in the frontend called `start_receiving_session` - the only
"start a package" entry point still called the legacy `create_inbound_asn`, which requires typing
every SKU/quantity up front. This was only caught by actually running the "unbox a new package"
scenario end to end through the browser. Fixed in v0.5.2: **Start receiving (scan as you go)** is now
the primary action on Receive Orders; verified with a real 2-item unboxing (scan, stage into two bins,
one batched Stock Entry, correct Live Inventory + activity). Also found and fixed in the same pass:
`get_bin_activity` wasn't filtering cancelled Stock Ledger Entries, so history from the v0.5.1 test-data
reset was corrupting the previous-balance calculation for new, real receipts.

**Lesson for future phases:** backend verification (rollback-tested transactions, direct API calls) does
not catch a missing frontend entry point. Before calling any phase "complete," run its actual operator
scenario through the real UI, start to finish - not just its component pieces.

**Receive Phase 1 is complete. Pick Phase 1 is complete except one item**: `Start pick from this bin`
(a single-bin pick entry point) is still not built. The other outstanding item from v0.5.0 - making a
bin's contents actionable - shipped in v0.5.1: tapping an item inside a bin card now opens the same
item-detail drawer (with `Adjust qty` / `Move bin`) that the Items list already opened, rather than
duplicating those actions inline in the bin card. v0.5.1 also collapsed the redundant third inventory
view ("Total → Locations") into Bins, since both were bin-centric renderings of the same data and
Locations had no click-through at all. See CHANGELOG v0.5.1.

**Test stock reset (2026-09-03):** the 13 Stock Entries posted 2026-08-28/29 while testing the Pick
backend (all of the site's on-hand inventory at the time - not real counts) were cancelled. Live
Inventory reads 0 on hand / 0 stocked bins as of this writing; the two `Completed` history cards this
left behind (a Pick and a Pack task) are a known, harmless audit inconsistency - their stock movement
was reversed but their status field wasn't, since neither doctype links back to the Stock Entry that
moved its stock. Real receiving/adjusting from here on populates a clean, trustworthy activity feed.

`Start pick task with this item` **is** built, on item detail. Everything else in the table below is
built. Mutation endpoints were tested inside a rolled-back transaction, so the full code path
(including `submit()`) ran without persisting anything to live data.

Three bugs in the Pick backend were found by testing and fixed — see CHANGELOG v0.5.0. All three
would have shipped silently: an inverted `quantity_change`, a completely non-functional
`adjust_bin_qty` (`MandatoryError: purpose`, plus a `reconciliation_date` field that does not exist),
and reconciliations rendering as "no change" because a Stock Reconciliation sets a balance rather
than moving a delta.

**Discovered, not introduced:** the working copy carries the *sanitized* constants
`DEFAULT_COMPANY = "Example Company"` and `DEFAULT_TEST_CUSTOMER = "Example Customer"` (api.py:444/568).
Neither exists on a real site, so `_default_warehouse()` returns `None` for every zone and
`create_inbound_asn` / `create_pick_task` are **currently broken against real data locally**, not just
in the mirror. New code deliberately resolves by zone instead of via the global constant, which is
also what BUSINESS_CONTEXT.md requires — but the existing callers still need fixing, and a
`SoyPaq Settings` doctype remains the real answer.

### Prepared for Phase 2 and 3

- **Tier 2 slots in without rework.** `_resolve_scanned_item()` is the single resolution point;
  parsing `RED-DRG-S` against Item Variants becomes one additional branch there, and the scan UI
  already handles an unresolved result as a normal outcome rather than an error.
- **The futureproofing rule is honoured.** The receiving screen renders a line set that *happens to
  be* empty. An ASN later pre-seeds those lines and adds an expected-vs-counted column: same screen,
  same endpoints, one code path.
- **`Inventory Action` is already the review queue.** Provisional items log against it today, so
  surfacing "N items need review" in Phase 2 is a read, not new machinery.
- **Bin relabelling is de-risked.** `_resolve_bin` accepts `A1` and `A01` interchangeably, so the
  bulk bin generator and label printing can land without a flag-day relabel.
- **Still gated on decisions:** Item Variants migration, `item_group` as category, the per-client
  parsing rule, and the bulk bin generator. Import template 02 stays unfrozen until variants land.

## Receive/Pick revision — Phase 1 at a glance

Neither column needs Item Variants, a parsing rule, or any data migration. That is all Phase 2.
Full reasoning in the two Project sections below.

| Receive — Phase 1 | Picking — Phase 1 |
|---|---|
| Break the two-phase gate (`App.vue:847`) — loop becomes **scan -> qty -> scan bin -> next** | Make per-bin location cards **actionable** — they are inert text today |
| `start_receiving_session()` — blank package, no ASN, **no fabricated tracking number** | `Start pick from this bin` — **single-bin only**; multi-bin is Phase 2 |
| Relax `external_tracking_number` from REQD; a duplicate scan **resumes** a package, never forks one | Demote `Open item in ERPNext` to secondary; `Start pick task` becomes the primary button |
| **Explicit client selection** at session start — never a default | `Adjust qty` -> posts a **Stock Reconciliation** |
| Add-line-on-scan (`_package_row` must accept new lines); `received_qty` is the truth, **no cap** | `Move bin` -> posts a **Material Transfer**, entered by barcode scan |
| **Scan Tier 1** — known barcode, qty +1, zero typing | Staged view: expand a bin to its contents, same per-line actions |
| **Scan Tier 3** — unknown code: name it, **stage it anyway**, tag `Provisional` | **Activity feed** — reads SLE + `Inventory Action` (who / what / when / why) |
| Qty defaults to 1 but editable — 40 units is one scan and a number, not 40 scans | **New doctype: `Inventory Action`** — annotates, never stores stock |
| **Directed put-away** — suggest the bin the item already occupies, one tap; override by scanning any other | `get_bin_activity()` endpoint feeding the activity view |
| `condition` on the item card, plus **two photo destinations**: catalogue -> `Item.image`, condition -> the receipt line | — |
| **`Damaged` routes to the Damaged warehouse** on staging (today it lands in normal stock) | — |
| **One Stock Entry per package** at Finish; rows persist continuously so a crash loses nothing | — |
| **Zero-pad bins** `A1..A6` -> `A01..A06` | — |

**Two cross-links.** `Inventory Action` sits in the Pick column but **Receive depends on it** — it is
what gives Receive a correction path after Finish, since `_writable_package` blocks reopening a
stored package. Build Pick's doctype and Receive inherits the fix. Separately, the **one Stock Entry
per package** row is what resolves the deferred voucher-volume concern, which is already live in
Receive today at one voucher per item.

## Project: Pick revision — inventory as the action surface

Driven by warehouse-worker feedback: operators go to the Inventory screen *before* picking,
because the pick screen never shows whether the stock is actually in the bin. That trip is
correct and stays. The problem is that Inventory is read-only, so every real-world correction
(count is wrong, box moved) ends up in a spreadsheet instead of the system.

**Frontend**
- Per-bin location cards in item detail become actionable (`Adjust qty`, `Move bin`).
  The card is the right anchor: work happens at *item x bin*, not at item.
- `Open item in ERPNext` demoted from sole button to secondary; `Start pick task` becomes primary.
- Staged (bins) view: expand a bin to its contents, same per-line actions, plus `Start pick from this bin`.
- **Activity feed** on item and bin — who changed what, when, and why. This is the piece that
  actually replaces the spreadsheet, whose real value was the change log, not the numbers.
- `Move bin` reuses the existing bin-scan affordance from `confirm_pick_location`, so it feels like picking.

**Backend**
- `adjust_bin_qty()` -> Stock Reconciliation; `move_bin_stock()` -> Stock Entry (Material Transfer).
  Both are ordinary ERPNext documents - no parallel stock tracking invented.
- `get_bin_activity()` feeds the activity view.
- **Stock Ledger Entry is already the audit log** (`item_code`, `warehouse`, `actual_qty`,
  `voucher_type/no`, `owner`, `creation`). Do not build an audit doctype for movements.

**New doctype: `Inventory Action`** — annotates, does not store stock. SLE records *what* changed
but not *why* ("Stock Reconciliation #7", not "count correction, by Maria"). This holds the reason
code and links to the ERPNext voucher. If it were wiped, stock would still be correct.
Must be `custom=0` + exported JSON + controller (`scripts/check_doctypes.py` guards this).

**Known prerequisite — smaller than goal 5 below suggests.** `Pick Task Item` *already has*
per-row `source_warehouse` / `source_bin`. The gap is that `create_pick_task` flattens every row
to one task-level warehouse, and `confirm_pick_location` / `scan_bin` validate a single bin scan
for the whole task. So a multi-bin pick fails at the *scan* step, not just creation. Consequence
for sequencing: **single-bin `Start pick from this bin` is easy; multi-bin `Start pick with this
item` needs the pick flow to become a route across bins** (scan A1, pick its lines, scan A3, ...).

**Deferred by explicit decision** — see Open decisions for detail: voucher volume, operator
permissions, and condition/quality flagging (QC belongs to Receive, not Inventory).

## Project: Receive revision — discovery, not verification

**Root cause, shared with the Pick revision.** Both flows require a document to exist before the
physical event. In this warehouse the physical event always comes first: nobody tells the
warehouse what is arriving, so the worker opens a box with no idea of contents or quantity,
logs everything into a spreadsheet by hand, and only then gets to put anything away. That is why
the ASN is currently useless — there is nothing to expect against.

**Receiving here is *blind receiving*** — a real, deliberate practice, not a deficiency. The goal
is not to escape it but to make it fast.

### What the schema already allows (verified, no migration needed)

- `Inbound Package.inbound_asn` is **not required** — a package can already stand alone.
- `Inbound Package Item.item_code` is **not required**, and the row already has `barcode`,
  `item_name` and `notes` — raw capture of an unidentified item is already possible.
- `scan_state` (`Waiting for Item` / `Waiting for Bin`) already models the alternating
  scan-item-then-scan-bin loop.
- `Item Attribute` already defines `Colour` and `Size`. **Zero items use them** — all items are
  flat with size baked into the code and name.
- `Warehouse` has native `customer` and `warehouse_type` fields, both unused.

### What blocks it (all code, not schema)

- `create_inbound_asn` is the only way to start a receive; it always creates an ASN and
  **fabricates** `external_tracking_number`.
- `external_tracking_number` is REQD on Inbound Package — a box with no scannable label cannot be
  received at all, which is *why* the fake number exists.
- `_package_row` rejects any item not already on the package.
- `receive_item` caps at expected qty — over-receipt cannot be recorded.
- `flag_receive_item` calls `_package_row` first, so the `"Unknown SKU"` condition **can only be
  applied to items already in the list**. The schema anticipates the real case; the code blocks it.
- The two-phase gate is one line — `App.vue:847`, `"Continue to staging"` is
  `:disabled="!receiveConfirmed"`. The backend already allows interleaving.
- `stage_item` posts **one Stock Entry per item** (a 40-line box makes 40 vouchers) and **ignores
  `condition`** — an item flagged Damaged lands in normal storage and counts as available.
- `_writable_package` hard-throws once status is `Stored` — **no correction path after Finish**.
- `_resolve_bin` dead-ends on any unknown code.
- `Inbound ASN Package` is a **dead doctype** (multi-box deliveries, designed and never built).

### Scan resolution — three tiers

| Tier | Scan result | Behaviour | Needs |
|---|---|---|---|
| 1 | known barcode | qty +1 on that line; zero typing | nothing — exact `Item Barcode` lookup |
| 2 | unknown code, known style | offer constrained variant creation from existing attribute values | Item Variants + per-client parsing rule |
| 3 | nothing matches | name it, fill blanks, **stage it anyway**, tag Provisional | nothing |

Tier 1 needs **no parsing and no variants** — this is what keeps Phase 1 free of migration.
Tier 2 is the only thing that needs either. Floor workers never free-type an item *name* in
Tier 2; they pick from existing attribute values, so two workers cannot invent two names for one
product.

### Phase 1 — replaces the spreadsheet (no variants, no migration)

- Break the two-phase gate (`App.vue:847`); loop becomes **scan item -> qty -> scan bin -> next**.
- `start_receiving_session()` — blank package, no ASN, **no fabricated tracking number**.
- Relax `external_tracking_number` from REQD; duplicate tracking **resumes** a package, never
  creates a second one.
- **Explicit client selection at session start** — never a default. Highest integrity risk in a
  multi-client 3PL: silently mis-assigned stock surfaces months later at reconciliation.
- Add-line-on-scan (`_package_row` must accept new lines); `received_qty` is the truth, no cap.
- Scan Tiers 1 and 3.
- Qty entry defaults to 1 but is editable — 40 units is one scan and a number, not 40 scans.
- **Directed put-away**: suggest the bin the item already occupies, one tap to confirm, override
  by scanning any other bin.
- `condition` on the item card; **`Damaged` routes to the Damaged warehouse** on staging.
- Photos, two distinct destinations: **catalogue photo -> `Item.image`** (permanent, helps every
  future picker) and **condition photo -> the receipt line** (evidence for this delivery).
  A damage photo must never become the catalogue image.
- **One Stock Entry per package, posted at Finish.** Rows save continuously so nothing is lost on
  a crash; only the stock posting is deferred. Directly fixes the voucher-volume concern, which is
  already live in Receive today.
- **Zero-pad bins now** (`A1..A6` -> `A01..A06`). At `A10` string sorting breaks every bin picker
  and inventory list. Six renames today; 300 renames with a year of ledger history later.
- Correction after Finish is **not** reopening the package — it is a bin adjustment via
  `Inventory Action` from the Pick revision. Stock has already posted; unwinding a receipt is
  messier than correcting a count.

### Phase 2 — needs a decision or a migration

- **Item Variants migration** — 30 flat items become templates + `Colour`/`Size` attributes.
  Cheap at 30 items, expensive at 300. Also settles import template 02, which therefore **cannot
  be frozen** until this is decided (01 and 03 still can).
- Scan Tier 2, which this unlocks.
- **Per-client code parsing rule** — `RED-DRG-S` is a proprietary fabricator scheme; the next
  client will delimit or order segments differently. This is per-client *data*, not app logic.
  Hardcode for one client now; extract to a per-Customer profile when client #2 appears.
- **`item_group` becomes a category, not a season.** Required for category fallback icons
  (shirt / pants / shoe) — today it is `Summer_2026`, so nothing can be derived and the UI
  hardcodes one icon. Third independent argument for category over season.
- **Bulk bin generator** (admin) + **register-on-scan** (floor, pattern-constrained, never free
  text). Bins are generated from a naming scheme and physically labelled, not invented one at a
  time — a bin with no physical label cannot be scanned next time. Guardrails matter because a
  warehouse with stock history **cannot be deleted**, only disabled: typos are permanent.
- Surface the provisional/review queue (open `Inventory Action` records) so flagged items cannot
  quietly rot.

### Phase 3 — futureproofing

- **ASN entry** (form, email, or Medusa). ASN becomes *reconciliation*, never a prerequisite:
  Package stands alone; link an ASN only if one happens to exist.
- Barcode label printing (pairs with register-on-scan and with items that arrive unlabelled).
- `Warehouse.customer` for real client segregation; `warehouse_type` to replace the fragile
  string matching in `_default_warehouse` (which currently excludes `"Damaged"`/`"Returns"` by name).
- Per-line receiver (only `received_by` at package level today, so two workers splitting a box
  are indistinguishable).
- Multi-box deliveries **if ever actually needed** — otherwise one box = one package, and the dead
  `Inbound ASN Package` doctype should be deleted rather than shipped unused.

### The one futureproofing rule

> **Build the screen to render a line set that *happens to be* empty — not a screen that assumes
> empty.**

Then ASN later just pre-seeds those lines and adds an expected-vs-counted column: same screen,
same endpoints, one code path. Hardcoding "starts blank" turns ASN into a second parallel flow
that must be maintained forever. Nearly free now, expensive to retrofit.

### Deliberately out of scope

Serial/batch tracking, expiry dates, cross-docking, and returns (a different flow, though a
Returns warehouse exists). Named here so they are decisions rather than oversights.

## Project: Pick screen QoL — shipped in v0.6.0 (2026-09-03)

Stepper, enriched order details (incl. a live elapsed-time timer, reused via a standalone
`formatElapsed()` helper meant for Receive/Pack/Ship too), visual cleanup of the pick list
(bin-grouping and pick-order freedom kept as-is), the row drawer converted to the same popup
pattern as the rest of the app, per-row grey-out on completion, and exception flags gained a note +
photo capture. New **Pick Action** doctype logs every pick/unpick/exception/complete event
(who/what/qty/reason/note/photo/when) - Pick had no per-event audit trail before this, only a
single overwritten status string. That log now feeds both a live activity view and the My Tasks
drawer's History tab, and the same drawer (Picker, live timer, item-level exception badges) now
shows on the Open/Active tabs too, not just the live working screen. Full detail in CHANGELOG v0.6.0.

**Bug found and fixed in the same pass** (pre-existing, not introduced this session): every
exception-reason button (Short/Missing, Damaged, Wrong Item, No Stock) was silently taking the
handpick branch - incrementing `picked_qty` and marking the row "Picked" - because `flag_pick_item`
trusted the raw `handpick` value's truthiness, and the string `"0"` off the wire is truthy in
Python. Fixed with `cint(handpick)`. This had been wrong since the feature was first built.

**Not done, explicitly out of scope:** verifying/rebuilding the Pack handoff (`_sync_pack_from_pick`
still only syncs into an *already-existing* Pack Task, doesn't create one) - flagged as a bigger,
separate item, not touched. A separate "retry scan" popup was skipped as redundant with the existing
handpick flow. Warehouse-operator roles/permissions remain deferred (AGENT.md).

**Also noticed, not fixed** (unrelated to this build): `confirm_pick_location` requires the *exact*
full warehouse name (e.g. `Example Company - Storage - A03 - S`) - unlike Receive's `_resolve_bin`, it
doesn't accept short bin codes like `A03`. Worth aligning the two at some point.

## Next goals — roughly sequenced

**Active — the Receive/Pick revision** (full spec in the two Project sections above)

1. **Receive Phase 1** — no decisions or migration needed. Break the two-phase gate; blank
   receiving session with no fabricated tracking; explicit client selection; add-line-on-scan
   (Tiers 1 + 3); directed put-away; condition + two photo destinations; one Stock Entry per
   package; `Damaged` routes to the Damaged warehouse; zero-pad bins.
2. **Pick Phase 1** — actionable per-bin location cards (`Adjust qty` / `Move bin`), activity feed
   over SLE + `Inventory Action`, `Start pick from this bin`. Needs the `Inventory Action` doctype.
3. **Receive Phase 2 / Pick multi-bin** — gated on decisions: Item Variants migration, `item_group`
   as category, per-client parsing rule, bulk bin generator. Multi-bin picking additionally needs
   `create_pick_task` to stop flattening per-row bins and the scan flow to become a route.

**Independent of the revision**

4. **Split `apps/soypaq` into its own Git repository** — the remaining blocker for a Frappe Cloud
   deploy. Everything else for a clean cloud install is done and verified.
5. **Manual ship-to entry at label time** — worker types real ship-to, weight/dimensions and
   carrier on the Ship screen just before "Generate shipping label", instead of routing through
   Sales Order/Address records. Replaces `shippo_client.py`'s `DEFAULT_ADDRESS_TO`/`DEFAULT_PARCEL`
   placeholders — see the `TODO(manual-entry)` comment. `DEFAULT_ADDRESS_FROM` is real; its
   phone/email are still Shippo sandbox values. Not urgent on the sandbox key.
6. **Real Sales Orders** per incoming order instead of hand-made test data. Unblocks Purchase
   Receipt / Delivery Note as real books; depends on the Customer-granularity decision above.
7. **Claim timeout** — auto-release a stale claim after inactivity (manual release already works;
   needs a scheduled job).
8. **Receive claiming** — Inbound Package has no assignment field, so Receive can't show in
   "Active" with a named claimant like the other three stages.
9. **Bottom-nav highlighting during active work** — "My tasks" stays lit for list views but not
   inside the working/scanning screen (`pickMode === 'active'`).
10. **"Open in Desk" consolidation** — single home-button entry point; deferred to the larger redesign.
11. ~~Pick screen QoL rework~~ — **shipped in v0.6.0**. See "Project: Pick screen QoL" above.
    Pack-handoff verification remains genuinely open (not just deferred-and-forgotten).

**Superseded by the revision** — kept here so they aren't re-raised:

- *Inventory-driven task creation* -> Pick revision (and its stated prerequisite was wrong:
  `Pick Task Item` already has per-row `source_warehouse`/`source_bin`; the gap is that
  `create_pick_task` flattens them and `confirm_pick_location` validates a single bin).
- *Receive: real tracking numbers* -> Receive Phase 1 stops fabricating them outright. Shippo's
  **Track** API (carrier + real tracking in, delivery status out) remains the eventual follow-on,
  once operators are entering real inbound tracking numbers.

## Local environment state

Facts about this dev box that aren't obvious from the code:

- **`developer_mode = 1`** is now set in `sites/common_site_config.json`. Required for doctype
  export — keep it on locally, keep it **off** in production.
- **Two sites exist**: `frontend` (the real dev site, all the data) and **`testprod.local`** (a
  throwaway built to prove a clean install works). Rebuild it any time with
  `bench new-site testprod.local --mariadb-root-password admin --admin-password admin
  --mariadb-user-host-login-scope='%' --install-app erpnext` then `bench --site testprod.local
  install-app soypaq`. **Re-run that check before any production deploy** — it is the only thing
  that catches fresh-install-only bugs.
- **MariaDB root password is `admin`** (from the db container env); the site DB password in `.env`
  is separate.
- **Pre-conversion backup**: `erpnext-local/backups/20260829_213842-*` (taken immediately before the
  custom→standard doctype surgery).
- **Stock is consolidated in Storage bins.** `Example Company - PickPack - S` was drained back to A1/A2 via
  `MAT-STE-2026-00014` — it had stranded units left over from the old Pick→PickPack transfer that
  the app could no longer reach after that transfer was removed. `ITEM-BLK-CE01-M` had no prior
  Storage home and was placed in A1 by fallback; move it if that's wrong.

## Current version

**v0.7.1** — see `CHANGELOG.md` for the full shipped history.
