# SoyPaq WMS Changelog

Tracks every shipped change set for the mobile WMS app (`apps/soypaq/ui`, `apps/soypaq/soypaq/api.py`).
The current version is shown in the app under Settings → App version.

Convention: bump `APP_VERSION` / `APP_BUILD_DATE` in `apps/soypaq/ui/src/App.vue` on every change set that
reaches a running site (local or prod), and log it here with Backend/Frontend split.

## Unreleased - 2026-09-26

**Customer Onboarding desk workspace.** Run `bench migrate` (new standard workspace, patch `add_onboarding_workspace`). No version bump; no WMS UI change.

**Backend**
- New `Customer Onboarding` workspace at `/desk/customer-onboarding` (System Manager, Stock Manager, Accounts Manager). Number cards: 3PL Clients, Clients Awaiting Setup. "New Client" opens the Customer form with group 3PL Client prefilled, which triggers automatic onboarding. Link cards group the follow-up doctypes: contact and address, warehouse and items, staff and portal access (User, User Permission), storefront and billing.

**Frontend**
- None.

## v0.11.7 - 2026-09-26

**Live Inventory filters: Company replaces Drop, filters collapse.** Patch bump (`APP_VERSION`/`__version__` 0.11.7, cache-buster `0.11.7`). Restart the backend; no migrate needed.

**Backend**
- Inventory items carry `company` (company of the warehouse holding most of the stock; blank if unassigned).

**Frontend**
- Bins and Items filters are now Company, Color, Size (Company leftmost). The Drop filter is removed; the drop is still matched by search.
- The filter row is collapsed behind a "Filters" bar that shows how many filters are active, and expands on tap.

**Walkthrough (local)**: Company lists the two tenants; choosing the second tenant leaves only its bin and item; badge shows 1.

## v0.11.6 - 2026-09-26

**Second-tenant Medusa routing and tenant-safe bin codes.** Patch bump (`APP_VERSION`/`__version__` 0.11.6, cache-buster `0.11.6`). Restart the backend; no migrate needed. Full walkthrough saved in `tests/runs/2026-09-26-tenant-2.md`.

**Backend**
- Medusa intake routes each order to a tenant by its SKUs: the tenant group in the item's item-group ancestry, limited to the customers the bridge user has User Permissions for (the boundary is unchanged). A SKU no permitted tenant owns, or a cart mixing tenants, is rejected and logged. A bridge with one tenant behaves as before. `sync_stock_to_medusa` mirrors every permitted tenant's warehouses.
- Fix: a short bin code (`A01`) exists for every customer and used to resolve to whichever bin the database returned first. Now it resolves inside the customer in context (task customer, source bin's company); with none, it reports the ambiguity and asks for the full bin name.
- Duplicate intake rows record the task's customer.

**Frontend**: version bump only.

**Walkthrough (local)**: second tenant onboarded, one item stocked, storefront order #14 routed to it, picked and packed in WMS, draft billing entry logged with the Medusa reference; mixed-tenant order rejected. Ship not run.

## v0.11.5 - 2026-09-26

**Automatic tenant onboarding.** Patch bump (`APP_VERSION`/`__version__` 0.11.5, cache-buster `0.11.5`). Run `bench migrate`.

**Backend**
- Saving a Customer in the **3PL Client** group now sets up its tenant in the background (`soypaq/onboarding.py`), laid out like the first tenant: a Company of the same name (unique abbreviation from the initials, currency and country copied from the billing company), a root warehouse group with Receiving, PickPack, Returns, Damaged, a Storage group and first bin `A01`, plus an item group for its product-type groups. An "Item Code Prefix" (first three consonants, unique) is suggested. Idempotent and locked against overlapping saves; a failure is logged and noted on the Customer.
- New Customer fields: Item Code Prefix, Tenant Onboarded (read-only). Existing 3PL Clients that are already set up are marked onboarded by patch `add_tenant_onboarding`; the first tenant's prefix is HMN.
- The customer then appears in WMS "+ New bin" with the next free code (A02 after A01).

**Frontend**: none.

**Walkthrough (local)**: created a test customer through the Desk form; onboarding finished in the background with one activity note, the customer showed in the New bin options with code A02. Test tenant then deleted; company, account, warehouse, customer and item-group counts back to the starting values, no GL entries.

## v0.11.4 - 2026-09-26

**Item groups mean product type; New bin links to New customer.** Patch bump (`APP_VERSION`/`__version__` 0.11.4, cache-buster `0.11.4`). Run `bench migrate`.

**Backend**
- Patch `normalize_item_groups`: items in a season-style group (`Summer_2026`) move to a product-type group under their tenant group (`Example Client` > `Example Client - Tees`); the season is kept in the Collection trait. Applies to all 50 items including the disabled ones. Item codes, bins and stock are untouched. Product type comes from the product name (Tees, Shirts, Shorts, Pants, Sweatshirts, else Apparel), so future imports land in a sensible group.
- Traits backfill also reads color from the item code (`BLK`, `WHT`, `PNK`, `BLU`, `RED`) when the name has none.
- The Portal's Category column and category share now show the product type instead of the season.

**Frontend**
- New bin sheet: "Customer not listed? + New customer" opens Desk's New Customer form. Inventory search also matches the item group.

**Walkthrough (local)**: 50 items regrouped under `Example Client - Tees` with Collection "Summer 2026"; on hand 486, ledger 37; New bin sheet shows the customer link. Old `Summer_2026` group left in place, now empty. Medusa test orders #12 and #13 cancelled in Medusa.

## v0.11.3 - 2026-09-26

**Medusa order reference carried through ERP, and Medusa intake picks from the bin that has the stock.** Patch bump (`APP_VERSION`/`__version__` 0.11.3, cache-buster `0.11.3`). Run `bench migrate`.

**Backend**
- `Pick Task` gains `medusa_order_number` and `medusa_order_id` (read-only, "Medusa Source"). `create_order_from_medusa` takes the new optional `display_id` (the customer-facing order number), stamps both on the task, and records the number on `Medusa Intake Log` (new `medusa_order_number`).
- Pick/Pack/Shipment previews and the pick screen context now show the Medusa order (`Medusa #13`) as the source instead of "Manually created - no source order linked". Pack and Shipment follow the lineage back to the pick. No lines are compared for Medusa sources (integrity status `external`).
- Audit trail: the billing journal entry remark and line remarks read `Order PICK-MIA-##### - Medusa #13 (order_...)`, and `Pick Billing Log` has a searchable `source_reference` column.
- Fix: Medusa intake used one fixed bin for every item, so an item stocked elsewhere was rejected ("Only 0 units ... in ... A01"). Each line now goes to the Storage bin with the most available stock that covers it (`_best_pick_bin`); a task can span bins.

**Frontend**
- Task drawer and pick screen label the source `Medusa` instead of `PO`; the pick screen keeps the task name as its title for Medusa orders.

**Medusa (soyshop-local)**: `subscribers/order-placed.ts` now sends `display_id` with the order id.

**Walkthrough (local)**: storefront order placed, ERP task created with Medusa #13 in `A06`, picker drawer showed the Medusa order, completed pick wrote log and draft entry carrying the Medusa reference, packer view showed Medusa #13. Test data removed; on hand 486, ledger 37.

## v0.11.2 - 2026-09-26

**Pick Billing Log: one tracking row per completed pick task.** Minor-patch bump (`APP_VERSION`/`__version__` 0.11.2, cache-buster `0.11.2`). Run `bench migrate`.

**Backend**
- New read-only doctype `Pick Billing Log` (`/app/pick-billing-log`): pick task, customer, completed at, outcome (Created / Skipped / Failed), reason, journal entry, entry status (Draft / Submitted / Cancelled / Deleted), amount. Logging only; nothing edits it. Visible to System Manager and Accounts roles.
- `soypaq/billing.py` writes a row for every completion: Created (with the entry), Skipped (billing off, completed before billing started, no customer, zero fee) or Failed (error text). A task that already has an entry is not logged twice.
- Journal Entry `on_submit` / `on_cancel` / `on_trash` doc events keep the log's entry status current.

**Frontend**: none.

**Walkthrough (local)**: billing off gave a Skipped row; billing on gave Created with a draft entry (7.00); submit then cancel moved the status Draft, Submitted, Cancelled. Desk icons intact after migrate. Test data removed; on hand 486.

## v0.11.1 - 2026-09-26

**Bin shown per line in the task drawer.** Patch bump (`APP_VERSION`/`__version__` 0.11.1, cache-buster `0.11.1`).

**Frontend**
- Task drawer contents show each line's bin next to its SKU (`HMN-AFG-BLACK-L · Bin A02`).

**Walkthrough (local, bug pass)**: item in two bins (6 in A02, 4 in A05): switching bin in the line sheet clamps quantity to the new bin's availability, and + disables at the cap. One task across two bins: locked until each bin is confirmed (item scan, short code `A02`, or wrong bin rejected); short/exception flag and cancel work on multi-bin tasks; over-pick rejected. New bin from the Move bin sheet fills the destination and the move posts. Duplicate/invalid bin codes and customers without a Storage zone are rejected. `apply_medusa_products` stamps traits and reports unknown SKUs. Automated tests pass on the test site (21 run, 8 skipped for lack of stock data). Test data removed; inventory on hand 486. Known and held: "available" does not yet count completed-but-unshipped picks.

## v0.11.0 - 2026-09-25

**Per-task fulfilment billing, New bin, and item traits.** Minor bump (`APP_VERSION`/`__version__` 0.11.0, cache-buster `0.11.0`). Run `bench migrate` on every site.

**Backend**
- `soypaq/billing.py`: completing a Pick Task raises one **draft** Journal Entry (Dr Receivable / Cr Fulfilment Revenue, customer as party on both lines, cost center, `Order <task>` in the cheque reference and remark), matching the hand-made entries. Interim until Medusa pick-ship invoicing.
- `SoyPaq Settings` "Fulfilment Billing": enable switch, fee per task (default 7), billing company, receivable and revenue accounts, cost center. `billing_start` is stamped when billing is first enabled, so earlier tasks are never billed.
- `Pick Task.billing_journal_entry` (permlevel 1, System Manager only) makes billing idempotent and keeps the link away from warehouse users. A billing error is logged and never blocks the pick.
- `new_bin_options` / `create_bin`: create a storage bin for a chosen customer under its Storage zone; default code is the next free one (A07 after A06).
- Item traits (`soypaq/traits.py`, patch `add_item_traits`, re-asserted on install/migrate): Item fields `soy_product`, `soy_color`, `soy_size`, `soy_collection`, backfilled from item names and the old season group. `apply_medusa_products` stamps them from Medusa products (variant SKU = Item Code; option Color/Size; collection title).
- Inventory payload carries product/color/size/collection per item.

**Frontend**
- Inventory > Bins: "+ New bin" sheet (customer dropdown, code prefilled). Also reachable from an item's Move bin sheet, which fills the destination.
- Inventory: Color / Size / Drop filters, and search also matches traits.

**Walkthrough (local)**: completed a test pick, got one draft entry (7.00, both lines with party and cost center); created and removed bin A07; Pink + XL filter returned 1 item. Inventory unchanged: on hand 486, stock ledger entries 31.

## v0.10.2 - 2026-09-24

**Desk icons now survive `bench migrate`.** Patch bump (`APP_VERSION`/`__version__` 0.10.2, cache-buster `0.10.2`).

**Backend**
- `bench migrate` re-syncs Desktop Icons and dropped SoyPaq WMS from /desk (seen after the v0.10.0 migrate). New `after_migrate` hook (`soypaq.install.after_migrate`) re-asserts it through the existing idempotent setter on every migrate. The earlier once-only patch could not cover this. Confirmed by running migrate on the local site: the icon is present afterwards.

**Frontend**
- Version string only.

## v0.10.1 - 2026-09-24

**Pick screen lands on the route; builder quantities stop at what is left.** Patch bump (`APP_VERSION`/`__version__` 0.10.1, cache-buster `0.10.1`).

**Backend**
- `confirm_pick_location` on a single-bin task now also marks its rows `bin_confirmed`, so every task reports bin confirmation the same way. The single-bin gate itself is unchanged.

**Frontend**
- Removed the "Scan location first" screen. Opening a pick lands straight on the route. A bin is confirmed by scanning the bin code (full name or short code such as `A01`) into the scan field, by scanning an item in it (a scan proves presence), or by "I'm here" for tapping. All three confirm on the server; +/- stay disabled until the bin is confirmed. The scan field and camera button now read "item or bin barcode".
- Builder: a line can never exceed what is available in its bin. + on the line and in the sheet disables at the limit, further scans show "No more X left in <bin>", a bin change is refused for a bin with none available, and quantity is clamped when the bin changes. In the bin's "tap to add" list an item reads "0 left" and loses its + and click once none is left; an item with none available cannot be added at all.

**Verified (local, 2026-09-24):** scanned one item 9 times: stopped at 6 of 6 with "0 left" and no + in the bin list; opened the new task: no location screen, + disabled until a bin scan confirmed A01, then an item scan picked. Test task cancelled from the drawer; stock and commitments back to the earlier snapshot (on hand 486, stock ledger entries 31).

## v0.10.0 - 2026-09-24

**One Pick Task can span several bins.** Minor bump (`APP_VERSION`/`__version__` 0.10.0, cache-buster `0.10.0`). Adds a field: run `bench migrate` on every site.

**Backend**
- `Pick Task Item` gets `bin_confirmed` (Check, read-only). Each row already carried its own `source_bin`.
- `create_pick_task` now always creates one task. Each line has its own bin (line `warehouse`, else the argument, else the default Storage zone); repeats of an item in the same bin merge, the same item in two bins is rejected (a task holds an item in one bin), bins must belong to one company, and availability is checked per bin before anything is created. Rows are ordered by bin. The header `warehouse`/`scan_bin` is the first bin. Returns `name`/`route` plus a one-entry `tasks` list (`warehouses` lists the bins).
- `confirm_pick_location` on a multi-bin task accepts any of its bins (full name or short code such as `A02`), unlocks only that bin's rows, and moves `scan_bin` to the next bin still to confirm. Single-bin tasks keep the original task-level gate unchanged.
- `pick_item`, `unpick_item` and `flag_pick_item` require the row's own bin to be confirmed on a multi-bin task ("Confirm bin X first"). `pick_all` confirms every bin. Pack and Ship rows already carried per-row bins, so the Pack Task from a multi-bin pick keeps them (checked).
- Tests in `tests/test_pick_builder.py` (skip on sites without stock in two bins).

**Frontend**
- Builder sheet: one card headed by the (previewed) pick task name and its bin count, bins as sub-headings inside it; footer "Create pick task - N items - N units"; toast shows the real name.
- Pick screen: on a multi-bin task "I'm here" and item scans now confirm the bin on the server (rows carry `bin_confirmed`), so state survives a reload and other operators see it. Single-bin tasks unchanged.
- Known: the task drawer's contents list does not show each line's bin yet.

**Walkthrough (local site, 2026-09-24):** Before: on hand 486, open pick commitments 6, Pick Tasks 29, Pack Tasks 12, Stock Ledger Entries 31. Created one task over bins A01/A02/A04 (3 items, 4 units); confirmed A01 at the gate, "I'm here" on A02 (server), an item scan on A04 (implicit confirm); picked all, completed, Send to Pack: the Pack Task carried all three bins. After: on hand 486, Stock Ledger Entries 31 (stock still moves only at ship), Pick Tasks 30, Pack Tasks 13 (test records; the completed pick's Pick Action rows block deletion).

## v0.9.4 - 2026-09-24

**Pick builder: live count moves into the bin list.** Patch bump (`APP_VERSION`/`__version__` 0.9.4, cache-buster `0.9.4`).

**Backend**
- None.

**Frontend**
- The live quantity now lives in the scanned bin's "tap to add" list: an item reads "N available" until it is in the sheet from that bin, then "N left" (available minus the quantity chosen with - / +). Lines under a pick task no longer show a count; they show the item code, plus a red "only N available" when over.

## v0.9.3 - 2026-09-24

**Pick builder polish from warehouse feedback.** Patch bump (`APP_VERSION`/`__version__` 0.9.3, cache-buster `0.9.3`).

**Backend**
- New `preview_pick_task_names(count)`: the next Pick Task names from the naming series, so the builder can label each pending task. A preview only; the real name is assigned on insert and `create_pick_task` returns it (another operator creating a task in between can shift the number). Naming series is now the `PICK_NAMING_SERIES` constant.

**Frontend**
- Builder sheet: the pick task list now sits above the scan box.
- Each pending task is headed by its pick task name (`PICK-MIA-#####`, previewed) with the bin as secondary text, instead of the bin name. The success toast lists the real names.
- Each line shows a live "N left" (available minus the quantity in the sheet); over-available still shows "only N available" in red.
- Removed "Start pick task with this item" from Live Inventory item detail. A pick can now be started only from the Pick screen (New Pick Task) or Inventory > Bins > "Start pick from this bin".
- The scan field refocuses without scrolling the sheet.

**Verified (local, 2026-09-24):** previewed names PICK-MIA-00034/00035 matched the created tasks; item detail has no start-pick button; test tasks deleted, stock and commitments back to the pre-test snapshot.

## v0.9.2 - 2026-09-24

**Warehouse-reported: "New Pick Task" has no scan. Scan-first pick builder, steps 1-3 of 5 (Pick screen and both Inventory entry points).** Patch bump. `APP_VERSION`/`__version__` 0.9.2; asset cache-buster in `www/soypaq-wms.html` is `0.9.2b` (a second build shipped under the same version).

**Backend**
- New `resolve_scan(code, warehouse=None)`: resolves one scanned or typed code to an item (Item Barcode, then item code) with every bin holding stock and its available quantity, or to a bin (full name, warehouse name, or short code such as `A1`/`A01`) with the items in it. Available is on hand minus what open Pick Tasks already intend to take, the same figure `create_pick_task` enforces. An unknown code returns `resolved: false`, not an error.
- `_parse_manual_items` now accepts a barcode as well as an item code, so every create route (`create_pick_task`, `create_inbound_asn`, `create_pack_task`, `create_shipment_task`) takes scanned values. Lines may also carry an optional `warehouse`.
- `create_pick_task` creates one Pick Task per bin: lines are grouped by their own bin (else the `warehouse` argument, else the default Storage zone), repeat lines for the same item and bin are merged, and availability is checked for every bin before anything is created, so it creates all tasks or none. Returns the first task as `name`/`route` (unchanged for existing callers) plus `tasks`. A Pick Task stays single-bin, so the pick flow is untouched.
- Tests: `tests/test_pick_builder.py`.

**Frontend**
- Pick screen "New Pick Task" is now a scan-first builder sheet (Pack, Ship and Receive keep the old form until step 4). The scan field is always focused; Enter (handheld scanners) or the camera button, which follows the existing WMS pattern of one decode per open, adds the item or does +1 on its line, with vibration/beep feedback honouring the Settings toggles. An unknown code shows a toast and keeps focus.
- Lines are grouped by bin (one task per bin) and default to the bin already in the sheet. Scanning a bin code lists its items to tap. Tapping a line opens a second sheet to set the quantity, change the bin (with available quantities), or remove it. A line over the available quantity turns red and blocks Create.
- Footer reads "Create N pick tasks - N items - N units".
- Customer and Warehouse boxes are gone from this sheet: the customer is inferred from the bin's company, as before.
- Cache-buster in `www/soypaq-wms.html` bumped (it was stale at 0.8.6).
- Step 3: "Start pick from this bin" and "Start pick task with this item" (Inventory) now open the same builder, pre-seeded: a bin lists its items (new "Add all" adds each at its available quantity), an item is added at qty 1 in its best-stocked bin. The old quantity and checkbox sheets and their state are removed.
- Builder sheets are `position: fixed` (`.wms-fixed`) so they open in the viewport when launched from a scrolled Inventory list; the shared overlay sits at the bottom of the whole page.
- Known gap (unchanged): Live Inventory "Available" is on hand minus ERPNext `Bin.reserved_qty`, so it does not subtract open Pick Task commitments; the builder's "available" does.
- Still to do: Pack/Ship/Receive on the scan-first sheet (step 4), barcode resolution on the Pick and Pack scan screens (step 5).

**Walkthrough (local site, 2026-09-24)**
- Before: Bin on hand 486 units (20 stocked bins), Live Inventory on hand 486, open pick commitments 6, Pick Tasks 28, Pack Tasks 12, Stock Ledger Entries 31.
- Created via bin entry (A01, Add all: 4 items, 61 units), item entry (+ scan into a second bin: 2 tasks) and confirmed each in Pick > Open. Open commitments 6 -> 68 (61 + 1, plus 2 picked and completed).
- Picked one task end to end (confirm bin, two scans, complete, Send to Pack). On hand stayed 486 and Stock Ledger Entries 31: stock only moves at ship, as designed.
- After cleanup: on hand 486, commitments 6, Stock Ledger Entries 31, Inventory Actions 2. One completed test task (its three Pick Action audit rows block deletion) was left in place.

## v0.9.1 - 2026-09-20

**Medusa intake hardening: scoped bridge user, tenant-scoped stock mirror, idempotent orders, audit log, and a Send-to-Pack fix.** Patch bump.

**Backend**
- Fixed `complete_pick`: `skip_downstream` arrives over HTTP as the string `"0"`, which is truthy, so every "Send to Pack" silently took the bypass path (auto-completed Pack/Ship, no label). Now coerced with `cint()`.
- `create_order_from_medusa` runs as a scoped machine user (site config `medusa_bridge_user`, default `svc-medusa-bridge@soy-ops.com`) instead of Administrator, so roles and User Permissions apply. The tenant Customer comes from that user's single Customer User Permission; the payload `customer_name` is ignored, and the Pick Task warehouse is resolved inside the tenant's Company.
- Idempotent: a Medusa order id already logged as Created returns the existing Pick Task (`duplicate: true`) instead of creating a second one.
- New doctype `Medusa Intake Log` (Created / Duplicate / Rejected, reason, acting user, payload), viewable as a Desk report. Rejections are committed even though the request rolls back. Requests failing the shared-secret check are not logged, by design.
- `sync_stock_to_medusa` only mirrors Bins in warehouses of the tenant's Company, and returns the tenant name.
- `EasyShipProvider` and `easyship_client.py`: sandbox/live host chosen from the API key prefix (`sand_`); items nested under `parcels`; courier read from `courier_service`.
- Provisioning (manual, per tenant): Customer and Company User Permissions on the bridge user (RUNBOOK Step 1.5). Run `bench migrate` for the new doctype.

**Frontend**
- WMS: `APP_VERSION` bumped to 0.9.1 (UI bundle needs a rebuild to show it).
- Storefront (Medusa repo): Address Line 2 field added and Phone made required in checkout; `setAddresses()` no longer drops `address_2`.

**Docs / Medusa side (soyshop-local, branch `feat/portal-ui-rebridge`)**
- Admin UI served at `/dashboard` (not `/app`); README and RUNBOOK URLs corrected; `docs/LOCAL_DEV_INFO.txt` added.
- Medusa catalog reconciled to ERPNext: 4 starter demo products and their stale inventory removed; live catalog is 5 products / 20 variants, stock levels match ERPNext.
- `docs/API_MAP.md`: per-tenant API map, provisioning checklist, and the control-plane decision (ERPNext/SoyPaq receives webhooks and pulls APIs; the UI is a thin client; no extra layer).
- `docs/PORTAL_UI_COMPAT.md`: compatibility review of the React portal prototype (blockers: direct Medusa admin calls, exposed AI key, no ERPNext login).

**Known limits**
- Two simultaneous webhooks for the same order id could both create a Pick Task (no locking).
- No Sales Order / Invoice / Payment yet; no tracking push-back to Medusa; stock sync is manual.

## Unreleased - 2026-09-21

**SoyPaq Settings, minimal Medusa Bridge role, Soy Ops workspace.** Not yet version-bumped or committed.

**Backend**
- New single doctype `SoyPaq Settings`: `default_company`, `customer_mode` (Default or Manual), `default_customer`. `_default_warehouse()` and `_resolve_customer()` read it first and fall back to the old built-in constants when it is blank, so existing behaviour is unchanged until it is filled in.
- New role `Medusa Bridge` (patch `add_medusa_bridge_role`): Pick Task read/write/create, read on Item, Warehouse, Bin, Customer, Company. Replaces the broader Sales User, Stock User and Warehouse Operator roles on the bridge user. Tenant scope still comes from the bridge user's User Permissions.
- `Medusa Intake Log` gains `event` and `direction` fields.
- New standard workspace `Soy Ops` (`soypaq/workspace/soy_ops`) plus four Number Cards (patch `add_soy_ops_workspace`).

**Frontend**
- Desk workspace `Soy Ops`: KPI cards (open sales orders, open pick tasks, ready to ship, rejected Medusa orders) and shortcuts into existing doctypes, shown per role.

## v0.9.0 - 2026-09-20

**Shipping provider layer and access-control groundwork.** Minor bump.

**Backend**
- New `security.py` (`guard_wms_api`, wired via `auth_hooks`): a non-warehouse role hitting a WMS API method or the WMS page is rejected; `tests/test_wms_access.py` covers both.
- Shipping provider layer (`shipping_providers.py`, `easyship_client.py`) and `medusa_client.py` added.

**Frontend**
- WMS: `APP_VERSION` bumped to 0.9.0.

## v0.8.6 - 2026-09-13

**Bypass path now pushes real stock, not a dead end.**

**Backend**
- `complete_pick(skip_downstream=True)` ("Skip - mark done here" at Mark Order Complete) no
  longer just stops the chain. It now calls new `_auto_complete_downstream()`, which
  auto-creates and auto-completes a real Pack Task and Shipment Task and posts the actual
  stock-out Delivery Note - the same real doctypes and the same real stock movement the manual
  Pack/Ship screens produce, just done inline instead of requiring an operator to click through
  them. No Shippo label is purchased for this path (a real paid API call); `tracking_number` is
  left blank for a human, or a future webhook/API integration, to fill in later. This exists so
  a bypassed order still leaves behind a complete, real record any future integration can read
  from or patch, instead of a gap where nothing downstream was ever created.

## v0.8.5 - 2026-09-13

**Live Inventory tab/summary cleanup.**

**Frontend**
- Live Inventory now defaults to the **Bins** tab instead of Items.
- The separate On hand/Available stat box is gone; its counts are folded into the Bins/Items/
  History tab labels instead (e.g. `Bins (6)`), matching the same "count in the chip" pattern
  already used for Open in My Tasks.

## v0.8.4 - 2026-09-13

**Mark Order Complete now asks before releasing to packing.**

**Backend**
- `complete_pick` gained a `skip_downstream` param: still requires the pick to be fully
  picked, but lets the operator end the chain at Pick instead of always auto-releasing to Pack -
  for sites still running packing/shipping by hand outside the app.

**Frontend**
- "Mark order complete" now opens a confirmation popup - **Send to Pack** or **Skip - mark
  done here** - instead of silently always releasing to packing, since packing/shipping isn't
  handled through the app everywhere yet.

## v0.8.3 - 2026-09-13

**My Tasks: Open count badge, and a real bug where a freshly created task landed on an empty
screen.**

**Frontend**
- The **Open** filter chip now shows a live count (e.g. `Open (2)`), matching the badge already
  shown on the bottom-nav My Tasks icon.
- Fixed a real bug: creating a task from any of the three creation flows (bin-based pick, qty
  popup, manual create form) landed on the **Active** tab instead of **Open**, where the new
  task actually was - looked like an empty screen. Caused by a blanket tab-reset watcher racing
  the creation flow's own explicit tab assignment and winning because it fired one microtask
  later. Removed the watcher; each entry point now sets its own default tab explicitly instead.

## v0.8.2 - 2026-09-13

**My Tasks unified onto one list with three equal filters, replacing the Active-default /
forced-navigation design from v0.8.1.**

**Frontend**
- My Tasks is now **one continuous task list** filtered by three always-visible, equal chips -
  **Active / Open / History** - instead of Active being the default screen with Open/History
  reached via separate buttons and a "Back to Active" link. Releasing or cancelling a task from
  the drawer no longer forces a tab switch; the row simply disappears from whichever filter no
  longer matches it.
- Inventory Activity entries now route to the same task drawer used elsewhere (contents,
  activity log, etc.) when the underlying record maps to a known task kind, instead of always
  opening the raw ERPNext Desk record.
- Live Inventory gained a **History** tab alongside Bins/Items, showing all activity site-wide
  in one place instead of only per-item.

## v0.8.1 - 2026-09-13

**Follow-up fixes from the first round of production feedback on v0.8.0.**

**Frontend**
- A successful barcode scan on the Pick screen now also satisfies the "I'm here" per-bin
  confirmation gate, matching manual +/- entry - previously only the already-blocked manual
  path attempted this, so a real scan could still be blocked behind a redundant confirmation.
- Restored the bottom-nav task-icon highlighting, which had regressed.

## v0.8.0 - 2026-09-13

**Production QoL feedback: pick-quantity safety, and My Tasks navigation.**

**Backend**
- `create_pick_task` now validates requested qty against availability before creating the
  task - previously a request for more units than physically on hand would create the task
  anyway and only fail later at pick time. New `_open_pick_reserved_qty()` helper sums
  `required_qty - picked_qty` across other still-open Pick Tasks for the same item/warehouse,
  so two in-flight picks can no longer both be told the same units are available. This is a
  stand-in, not ERPNext's native Stock Reservation Entry - that mechanism only reserves
  against a Sales Order voucher, and Pick Tasks created here have none yet (see
  `MEDUSA_INTEGRATION.md`). Swap it out once Medusa order ingestion makes Pick Tasks
  order-backed.

**Frontend**
- "Start pick task with this item" (Live Inventory → item detail) no longer hardcodes qty 1 -
  it now opens a qty-stepper popup first, matching the existing adjust/move-bin popup pattern.
  Also fixed a latent bug where the screen navigated to Pick even when the create call failed.
- Live Inventory → Adjust qty now takes the **correct final count** directly instead of a
  +/- delta - operators read a number off a shelf and type that number. The backend endpoint
  is still delta-based; the delta is computed client-side against the on-hand qty read when
  the popup opened.
- My Tasks now defaults to the **Active** tab on every entry (it doubles as a shared
  live-progress view other people watch), instead of resetting to Open or silently falling
  back away from Active when it's empty. Open/History are reached from Active via explicit
  buttons; a "Back to Active" link returns from either.

## v0.7.1 - 2026-09-03

**Home screen simplified to a work-launcher + dashboard.**

**Backend**
- `_inventory_snapshot()`'s `summary` gained `stock_value` - `Bin.valuation_rate` wasn't being
  fetched at all before this, so total inventory value had no source anywhere in the app.

**Frontend**
- Home now shows only the four Receive/Pick/Pack/Ship tiles (bigger - `wms-work-tile-big`, 112px)
  and a renamed **Dashboard** section below them. Removed: the separate "Live inventory" button and
  the old three-stat "Open work" row (Open tasks / Units on hand / Stocked bins).
- Dashboard = a search bar (visual only for now, not wired to anything yet) + three live stats:
  total live items, total warehouses (bins), and total stock value.

## v0.7.0 - 2026-09-03

**Naming series regression fixed, and the Pick → Pack → Ship chain now actually chains.**

**Backend**
- Naming series regression fixed across all five task-chain doctypes (Pick Task, Pack Task, Inbound
  ASN, Shipment Task, Inbound Package). The `-MIA-` location code documented as fixed back in v0.5.0
  had silently regressed - the doctype JSON default AND every hardcoded `doc.naming_series = ...` in
  `api.py` had fallen back to the plain prefix; Inbound ASN's case was total, back to random hash
  names. Restored `PICK-MIA-.#####` / `PACK-MIA-.#####` / `ASN-MIA-.#####` / `SHIP-MIA-.#####` /
  `SPQ-MIA-.#####` everywhere. Existing records keep their names; new ones resume each series' real
  counter (verified directly against `tabSeries`, not assumed).
- **`_sync_pack_from_pick` never actually created a Pack Task** - it only ever updated one that
  already existed, so completing a Pick released nothing to Pack. Added
  `_create_pack_task_from_pick`, seeded from the picked rows (`picked_qty > 0` only), carrying
  `customer`/`sales_order` through, called from `complete_pick` when no open Pack Task is found.
- Same gap one stage later: `complete_pack` only ever updated an existing Shipment Task. Added
  `_create_shipment_task_from_pack`, same pattern, seeded from packed rows.
- `cancel_task(doctype, name)` - new endpoint. `release_task` only ever worked on a task you already
  had claimed; there was no way to cancel an Open, never-claimed task at all, even though `Cancelled`
  was already a modeled status everywhere else.
- `get_bin_activity` and `_pick_activity_rows` now return a `route` per entry, pointing at the real
  source document (the Stock Ledger Entry's voucher, or the Pick Action) - powers click-to-trace.

**Frontend**
- Bin cards in Live Inventory → Bins gained **"Start pick from this bin"**: a popup listing the bin's
  contents with a checkbox + qty per line, creating a real single-bin Pick Task via the existing
  `create_pick_task(warehouse, items)` - the backend already supported single-bin picks, it just had
  no entry point from Inventory.
- My Tasks drawer and Live Inventory Activity feeds are now clickable, opening the real source record
  in Desk instead of just displaying it as text.
- Activity entries get a plain-English description line (e.g. "Handpicked" → "Entered manually - no
  barcode scan") instead of only the raw action name.
- Origin folded into the Contents card instead of sitting in its own box; quantity badges read `×1`
  instead of a bare, unlabeled `1`.
- My Tasks: the Active tab only renders when it has something in it (Open/History otherwise).
- Bottom nav gained a task-count badge (My Tasks) and a negative-stock indicator (Inventory) - both
  were misaligned against the other two icons from inconsistent per-icon centering; fixed with
  `justify-items-center` on the nav grid itself instead of a one-off `mx-auto` per icon.
- "Cancel task" added to the My Tasks drawer alongside "Release back to queue" - distinct actions:
  release un-claims and reopens, cancel ends it outright.
- Pick screen: the bin-code input was a single ref never cleared between tasks, so a bin typed for
  one task silently carried into the next and produced false "Expected X, received Y" errors - now
  cleared whenever a new Pick Task becomes active. The Location step also now shows a Contents preview
  before the bin is confirmed, instead of no item visibility at all until after it's scanned.

Verified end-to-end in the browser: a real bin → pick → pack → ship chain, each stage auto-creating
the next; naming series confirmed directly against `tabSeries`; cancel/release/nav badges all
exercised live, not just compiled.

## v0.6.0 - 2026-09-03

**Pick screen QoL rework.** Full spec was captured in PROJECT.md across a few rounds of feedback
before this build; see "Project: Pick screen QoL" there for the reasoning behind each item.

**Backend**
- New **Pick Action** doctype - a per-event audit log (who/what/qty/reason/note/photo/when),
  mirroring what `Inventory Action` already does for stock adjustments. `pick_item`, `unpick_item`,
  `flag_pick_item`, and `complete_pick` all log to it now. Pick had no per-scan trail before this -
  only a single `last_scan_action` string the Pick Task doc overwrote on every scan.
- `Pick Task.claimed_at` (new field, set in `claim_task`) and `Pick Task Item.exception_note` /
  `exception_image` (new fields) - the timestamps and detail capture the audit log and exception
  popup needed.
- `get_pick_activity(task_name)` - new endpoint, the per-task activity feed.
- `get_task_preview` now returns `claimed_at`, `assigned_to`, and `activity` for Pick Task, so the
  shared My Tasks drawer can show picker/timer/audit trail on **any** tab (Open/Active/History), not
  just the live working screen.
- **Bug found and fixed** (pre-existing, not introduced this pass): `flag_pick_item`'s `handpick: int`
  parameter arrives off the wire as the string `"0"` for a non-handpick call - and `"0"` is truthy in
  Python. Every exception-reason button (Short/Missing, Damaged, Wrong Item, No Stock) was silently
  taking the handpick branch: incrementing `picked_qty` and marking the row "Picked" instead of
  "Short". This has been wrong since the feature was first built; caught only because building the
  note/photo capture required actually exercising that code path end-to-end in the browser. Fixed
  with `cint(handpick)` instead of relying on the raw value's truthiness.

**Frontend**
- Progress stepper (Location → Picking → Complete) added to the Pick active screen - the one working
  screen that didn't have one (Receive/Pack/Ship all do).
- Order details enriched: PO number, order date, source-mismatch badge, and a **live elapsed-time
  timer** ticking from `claimed_at`. The timer helper (`formatElapsed`) is written as a standalone
  (timestamp) → (string) function specifically so Receive/Pack/Ship can reuse it later rather than
  each growing their own.
- Adjust/exception drawer converted from a full-screen "Back to pick list" replace to the same popup
  pattern as everywhere else in the app (Adjust qty, Move bin, Start receiving).
- **Exception capture now takes a note and a photo.** Tapping a reason (e.g. "Wrong Item") opens a
  details panel - note field, camera-capture photo upload, then Save. Previously a reason button
  submitted immediately with no detail capture at all.
- Completed rows in the pick list grey out with a checkmark instead of staying visually identical to
  pending ones.
- The shared My Tasks drawer now shows Picker, live elapsed time (while active), per-item exception
  badges, and the full Pick Action activity log for Pick tasks - visible from the Open/Active tab
  (before claiming) and the History tab (audit trail after the fact), not only the working screen.

Verified end to end in the browser, including deliberately re-testing the exception flow after the
`handpick` fix to confirm both the Short-flag path (picked_qty stays 0, status Short) and the
handpick path (picked_qty increments, status Picked) now behave correctly, and that the completed
task's History drawer renders the full Activity log correctly.

## v0.5.3 - 2026-09-03

**Found from a round of user feedback on the just-verified unboxing flow.**

**Backend**
- `_TASK_PREVIEW_FIELDS["Inbound Package"]` mapped to `quantity`, which blind receiving deliberately
  leaves at 0 ("nothing was expected"). The My Tasks history drawer for a Receive task showed every
  line's contents as 0 regardless of how much was actually received. Now maps to `received_qty`, the
  real count.
- `create_pick_task`'s `warehouse` fallback used `_default_warehouse()` (the sanitized `DEFAULT_COMPANY`
  constant, matches nothing real) - "Start pick task with this item" on item detail threw "No warehouse
  is configured in ERPNext" every time. Now resolves by zone via `_zone_warehouse()`, same fix pattern as
  `start_receiving_session` in v0.5.0.
- Same function's blank-`customer` fallback hit the twin bug (`DEFAULT_TEST_CUSTOMER`). Now infers the
  customer from the resolved warehouse's company when one isn't passed - on this site a 3PL tenant's
  Customer and Company share a name by convention, so this also fixes it for the plain "New Pick Task"
  button, not just the item-detail entry point.

**Frontend**
- Item detail's header had no thumbnail - every other place an item appears in the app does. All 30
  catalogue items already have real images in ERPNext; this was a pure display gap, not missing data.
- "Start pick task with this item" now passes the item's actual known bin as `warehouse`, so it picks
  from wherever the item really sits instead of whatever bin `_zone_warehouse` happens to resolve first.
- Bin-code inputs (Receive staging, Pick location confirm) didn't say typing was an option - only the
  Move-bin field did. Relabelled both to "scan or type", matching the one field that already made that
  clear.

## v0.5.2 - 2026-09-03

**Found by actually running the "unbox a new package" scenario end to end** - the first real test of
blind receiving through the browser UI rather than direct API calls.

**Backend**
- `get_bin_activity()` didn't filter `is_cancelled` on `Stock Ledger Entry`. Cancelling a Stock Entry
  doesn't delete its ledger rows, it leaves both the original and its reversal marked `is_cancelled=1`;
  the previous-balance lookup was walking straight through them and reporting a receipt into an empty
  bin as e.g. "5 → 3" instead of "0 → 3". Now filtered at the query.

**Frontend**
- **The actual blind-receiving entry point had no button.** `start_receiving_session()` (Phase 1's
  no-ASN, no-fabricated-tracking-number flow) existed on the backend since v0.5.0 but nothing in the
  UI called it - the only "start a package" button still called `create_inbound_asn`, which requires
  typing every SKU and quantity before the package exists, i.e. the exact pre-verification workflow
  Phase 1 was built to replace. Added **Start receiving (scan as you go)** as the primary action on
  the Receive Orders screen; the old button is now demoted and relabelled **Log inbound ASN (advance
  notice)** for the case where one genuinely exists.
- The new flow lands straight on the scan screen, not the legacy "Accept package" step - that step's
  button is gated on expected lines existing, which a blind package by definition has none of.

Verified against a real 2-item unboxing through the browser: `start_receiving_session`, two
`receive_scan` calls, `stage_item` into two different bins (via `_resolve_bin` short-code resolution),
`complete_receipt` posting one Stock Entry, and both items appearing correctly in Live Inventory and
Recent activity.

## v0.5.1 - 2026-09-03

**Inventory/history UX follow-up** - a round of fixes to the Phase 1 build once it was actually used:
consolidating a redundant view, fixing what displayed, and surfacing data the backend already computed
but the frontend dropped on the floor.

**Backend**
- `_inventory_snapshot()` no longer includes zero-qty Bin rows in an item's per-location breakdown. A
  `Bin` doc persists after it empties out, so this list grew dead entries forever; negative rows still
  show (a real ledger discrepancy, not noise).
- `get_task_preview()` now returns `source` (linked Sales Order - customer, PO number, dates) and
  `source_integrity` (does the task still match that order) for Pick/Pack, plus `created`/`modified`
  timestamps for every task kind. `_task()` already computed this for the four "current work" slots;
  the on-demand history preview never did.
- `_list_pick_tasks` / `_list_pack_tasks` / `_list_shipment_tasks` / `_list_receive_packages` now fetch
  `creation` so task cards can show when work was created, not just last touched.

**Frontend**
- **Live Inventory collapsed from three views to two.** "Staged (bins)", "Total → Items", and
  "Total → Locations" overlapped: Locations and Staged (bins) were both bin-centric renderings of the
  same data, one of them going nowhere (no click handler at all). Now: **Bins** and **Items**. Each bin
  card carries an "open in ERPNext" link for the one case Locations existed for.
- Bin cards' item rows are now tappable, opening the same item-detail drawer Items already opens -
  previously only the Items list wired into it.
- Item detail's Storage locations and Recent activity are now a **Locations / Activity** segmented tab
  instead of one long stacked scroll.
- **Adjust qty / Move bin now open as the same popup-sheet pattern used everywhere else** (task drawer,
  create-task form) instead of an inline-expanding panel - one modal treatment app-wide, not two.
- Adjust/Move quantity defaults to **tap +/- (step of 1)** with the number field still available for a
  larger jump, matching the discussed default-to-tap-not-type convention.
- My Tasks cards show a created timestamp; the task drawer gained an **Origin** section showing the
  linked source order (or "Manually created - no source order linked") and, for Pick/Pack, whether the
  task still matches that order's line items.

## v0.5.0 - 2026-09-03

**Receive/Pick revision, Phase 1.** Inventory becomes an action surface, and receiving becomes
discovery rather than verification. Full rationale in PROJECT.md.

**Backend**
- `start_receiving_session()` - blank package, no ASN, no fabricated tracking number. `customer` is
  required with no default: mis-assigning a box to the wrong client is the error that surfaces months
  later at reconciliation. Re-scanning a tracking number **resumes** the open package instead of forking.
- `receive_scan()` / `capture_provisional_item()` - Tier 1 resolves a known barcode via `Item Barcode`
  and increments; anything unresolved returns `resolved: False` rather than erroring, and Tier 3
  captures it as a marked provisional Item plus an `Inventory Action` review record.
- `_package_row(create=True)` - an item that was never expected is now the normal case.
- `receive_item` **cap removed** - in blind receiving there is no expected quantity to over-receive
  against; `received_qty` is the truth.
- `stage_item` no longer posts stock; `complete_receipt` posts **one** Stock Entry for the whole
  package (a 40-line box made 40 vouchers before). Rows still save as scanned, so nothing is lost
  if a session is interrupted - only the posting is deferred.
- `stage_item` routes `Damaged` stock to the Damaged warehouse, so the flag has a stock consequence
  instead of landing in normal storage as available.
- `move_bin_stock` now resolves short bin codes through `_resolve_bin` - operators scan "A01", not the
  full internal warehouse name.
- `_resolve_bin` accepts padded and unpadded codes interchangeably, so relabelling never has to be
  finished before scanning works.
- `external_tracking_number` no longer mandatory on Inbound Package - a box with no scannable label
  was previously unreceivable, which is *why* tracking numbers were being fabricated.
- Bins zero-padded `A1..A6` -> `A01..A06`. String sort breaks at `A10`; 6 renames now, 300 later.

**Bugs found and fixed while testing the new Pick endpoints** (all three would have shipped silently):
- `get_bin_activity` computed `quantity_change` as `qty_after_transaction - actual_qty`, which is the
  *previous balance*, not the change. Every row was wrong and signs were lost, so a pick and a receipt
  rendered identically.
- `adjust_bin_qty` was completely non-functional - `MandatoryError: purpose`. It also set
  `reconciliation_date`, which is not a field on Stock Reconciliation (a silent no-op); the real
  mandatory fields are `posting_date`/`posting_time`. Valuation is now carried forward explicitly,
  since bins can legitimately sit at 0.0 and a never-stocked bin has no Bin row at all.
- Stock Reconciliation *sets* a balance rather than moving a delta (`actual_qty = 0`), so reconciliations
  displayed as "no change". The activity feed now derives the previous balance from the next-older
  entry for the same item+bin, which is correct for every voucher type.

**Frontend**
- Per-bin location cards in item detail are now actionable: **Adjust qty** and **Move bin**, expanding
  inline with a before -> after preview. The card is the anchor because work happens at *item x bin*.
- **Recent activity** feed on item detail - who, what, when, why. This is the piece that replaces the
  spreadsheet, whose real value was the change log rather than the numbers.
- `Start pick task with this item` promoted to primary; `Open item in ERPNext` demoted to a ghost
  button rather than being the only thing the screen could do.
- **Two-phase receive gate removed.** "Continue to staging" was `:disabled="!receiveConfirmed"`, forcing
  every line to be logged before anything could be put away. The backend always allowed interleaving.
- Receive scanning now goes through `receive_scan` instead of filtering the expected list client-side,
  with an editable quantity (40 units is one scan and a number, not 40 scans) and an inline provisional
  capture prompt for unrecognised codes.
- `pickApi` no longer fires an empty toast when a caller passes no message.

## v0.4.2 - 2026-08-29

**Bug found and fixed during a full Receive → Pick → Pack → Ship walkthrough through the real
browser UI** (not bench console): `mark_shipment_shipped` failed submitting the Delivery Note with
`Item {code} has zero rate but 'Allow Zero Valuation Rate' is not enabled`. `_create_delivery_note()`
was defaulting `rate` to 0 for any item with no `valuation_rate` set (true for most test/demo stock,
which never went through a real Purchase Receipt) but never told ERPNext that was intentional. Fixed
by setting `allow_zero_valuation_rate = 1` on any line where the resolved rate is actually 0. Real
pricing should come from real Sales Orders once that work lands (see PROJECT.md roadmap) - this is
the correct behavior for test data in the meantime, not a permanent state.

**Walkthrough result:** end-to-end Receive → Stage → Pick → Pack → Ship (real Shippo label + real
Delivery Note, `MAT-DN-2026-00003`) completed successfully through the actual deployed page once this
fix landed. Confirms the v0.4.1 CSRF fix holds for real write actions, and that v0.4.0's Shippo
integration works end-to-end from the UI, not just via direct API calls. Verified real stock moved
correctly: the shipped item's bin dropped by exactly the shipped quantity; a second item that was
received/picked/packed but not shipped in this walkthrough correctly still shows its full quantity in
its storage bin (Pick/Pack don't move stock - only Ship does, per the v0.3.0 design).

**Re-confirmed, not new:** the disconnected-task-creation gap (a standalone Pick/Pack/Ship Task
doesn't auto-link to the next stage) and the single-default-bin limitation on manually-created
Shipment Tasks (no per-item bin selection, so a manually created Ship task can only draw from
whichever bin `_default_warehouse("Storage")` picks) both still apply exactly as documented in
PROJECT.md - encountered directly during this walkthrough, not fixed here.

## v0.4.1 - 2026-08-29

**Bug found and fixed while testing the actual browser UI (not just the API):** the mobile app's
custom `www/soypaq-wms.html` shell had `<!-- csrf_token -->` as a literal, inert HTML comment instead
of Frappe's actual template marker being replaced - Frappe DOES do a string-replace of that exact
marker on render (`BaseTemplatePage.add_csrf_token`), but a stale, pre-fix copy of the file was
sitting deployed. Net effect: `window.csrf_token` was always `null`, so **every write action in the
app** (`generate_shipment_label`, `claim_task`, `pack_item`, etc.) would fail with `CSRFTokenError`
the moment a real operator used a real logged-in browser session - this had apparently never been
caught before because prior "live testing" exercised `api.py` directly (bench console / curl), not
the actual deployed page in a browser. Fixed by deploying the correct HTML (which already had the
right marker + `window.csrf_token = window.frappe.csrf_token || null;`).

Also fixed: `shipping_label_url` needed a backend container restart (not just `bench migrate`) before
the browser stopped seeing a stale CSRF token - Frappe appears to cache the compiled per-route
response in-process per worker, independent of `bench clear-cache`.

## v0.4.0 - 2026-08-29

Real Shippo integration for shipping labels, replacing the fake `1Z-XXXXXXXX` placeholder tracking
number that `generate_shipment_label` / `complete_pack` used to stamp on every shipment.

**Backend**
- Added `soypaq/shippo_client.py`: calls the Shippo SDK to request rates for a shipment and buy the
  cheapest one, returning tracking number, carrier, label URL, and transaction ID. Reads
  `SHIPPO_API_KEY` from the environment (wired through `pwd.yml` from `.env` to the
  backend/queue-long/queue-short/scheduler containers) and throws a clear error if it's unset.
- No Address or per-item weight data exists anywhere in SoyPaq yet, so `shippo_client.py` uses
  Shippo's own well-known sandbox test addresses and one fixed default parcel (12x9x6in, 2lb) for
  every shipment for now - real Address/Item data can replace these later without touching the
  rate/buy flow itself.
- `generate_shipment_label` now actually calls Shippo instead of stamping a fake tracking number;
  `complete_pack` no longer pre-fills a placeholder tracking number when a Pack Task completes (that
  would have skipped the real Shippo call by looking like a label already existed).
- `create_shipment_task` (the standalone test-data helper) no longer defaults to a fake tracking
  number either, for the same reason - it still pre-seeds as fully packed so `generate_shipment_label`
  can be exercised on it immediately.
- Added `shipping_label_url` / `shippo_transaction_id` custom fields on Shipment Task via
  `patches/add_shippo_label_fields.py`.
- Added `shippo>=3.0.0` to `pyproject.toml`.

**Frontend**
- Ship screen's label card now shows a "View / print label" link to the real Shippo label PDF when
  one exists (`data.ship.label_url`, threaded through `get_mobile_bootstrap`).

**Not yet done:** real ship-from/ship-to addresses (needs Address records on Customer + a proper
Example Company origin address - the current one is placeholder junk) and real parcel weight (needs a weight
field on Item). Swapping those in only touches `shippo_client.py`'s callers, not its shape.

**Bug found and fixed while testing:** `shipping_label_url` was first added as a `Data` field
(140-char limit). Shippo's signed label URLs run 400-500+ characters, so the very first live label
purchase failed on save with `CharacterLengthExceededError` - caught immediately by actually running
`generate_shipment_label` end-to-end against the real API instead of stopping at a compile check.
Fixed by changing the field to `Small Text`. Note for later: `create_custom_fields(..., update=True)`
did not alter the fieldtype on the already-existing Custom Field record - had to fix it directly via
`frappe.get_doc("Custom Field", ...).save()`. Not an issue for a fresh install (the field is created
correctly as `Small Text` from the start), only for a site that already had the old `Data` field.

## v0.3.1 - 2026-08-29

**Frontend**
- Fixed a real, previously-invisible bug: every error thrown by the backend (`frappe.throw()`)
  was showing the generic HTTP status text ("EXPECTATION FAILED", "BAD REQUEST") in the toast
  instead of the actual message, because Frappe puts the real user-facing text in
  `_server_messages` (a JSON-encoded array of JSON-encoded `{message}` objects), not in
  `payload.message` - that key holds the function's *return value* on success, so reusing it on
  error silently surfaced the wrong string. Added `extractErrorMessage()` and wired it into
  `pickApi`/`fetchApi`. This affects every validation error in the app, not just the one below -
  operators were never actually seeing the helpful messages we've been writing all session.

## v0.3.0 - 2026-08-29

Closed a real bug: one operator could claim two different active jobs at once (e.g. Start a Pick
while a Pack was still active), because the per-stage screens' own "Start" buttons never went
through the claim system at all - only My Tasks did. Fix was two-part: a backend guard, and
unifying every task list in the app onto the same Open/Active/History + drawer code path so there
is exactly one way to start anything, anywhere.

**Backend**
- Added `_other_active_claim()` and wired it into `claim_task()`: claiming a second, different
  task while you already hold one unfinished is now blocked with a clear message identifying the
  conflicting task. (The existing "someone else already has this" block was unaffected - this
  closes the other half: *you* holding two at once.)

**Frontend**
- Removed the Incomplete/Completed tabs from Receive/Pick/Pack/Ship - each screen's own "tasks"
  mode now renders the same Open/Active/History list and drawer as My Tasks, filtered to that one
  kind (`myTasksScreenKind` / `showMyTasksList`). The "New [Kind] Task" creation button moved into
  this shared view, shown contextually per kind.
- Home tiles and post-creation navigation now reliably reset stage mode before navigating instead
  of sometimes landing on stale state from a previous visit (`openStageList`) - a smaller version
  of the same "wrong screen shows because mode is stale" class of bug.
- Preserved the one truly unique piece of the old completed-detail views - Ship's full pick→pack→
  ship audit trail with timestamps - reachable from the drawer via "View full history" instead of
  a now-removed direct list-card click. The equivalent Pick/Pack/Receive detail views were
  redundant with the new drawer's Contents section and were removed outright; the "jump straight
  from a finished Pick to its linked Pack" shortcut they offered did not carry over (minor, not
  rebuilt this pass).
- Removed ~30 lines of now-dead computeds/functions/refs this uncovered (`incompletePickTasks`,
  `pickTab`/`packTab`/`shipTab`/`receiveTab`, `openPickCompletedDetail` and its three siblings,
  etc.) - JS bundle dropped from 377KB to 360KB.

## v0.2.0 - 2026-08-29

My Tasks redesign: consolidated worklist across all four stages, claim-based assignment, and a
forced preview drawer before starting any task.

**Backend**
- Added `CLAIM_FIELD` map plus `claim_task(doctype, name)` / `release_task(doctype, name)` -
  claiming sets `assigned_to`/`assigned_user` to the current user (no-op if already held by them,
  blocked outright if held by someone else); releasing clears it back to the open queue. Applies to
  Pick Task, Pack Task, Shipment Task - Inbound Package has no assignment field yet, so Receive
  tasks can't be claimed, only opened/completed as before.
- Added `_my_tasks_buckets()`: merges `_list_pick_tasks`/`_list_pack_tasks`/`_list_shipment_tasks`/
  `_list_receive_packages` into `open` (unclaimed, unfinished), `active` (claimed, unfinished), and
  `history` (finished, any assignee) - wired into `get_mobile_bootstrap` as `my_tasks`. All four list
  functions now carry `assigned_to` and `modified` so the merged view can show claimants and sort by
  true recency across kinds.
- Added `get_task_preview(doctype, name)`: full item breakdown (image, name, qty) for the drawer,
  fetched on demand rather than eagerly for every row in every bucket.
- **Removed creation-time auto-assignment** in `create_pick_task`, `create_pack_task`,
  `create_shipment_task`, and the Pack→Ship cascade in `complete_pack` - tasks now stay unclaimed
  until an operator actually taps Start, matching the "assignment happens at Start" design principle
  from `ui/DESIGN.md`. (This was a real gap caught during testing: without this fix, every newly
  created task was auto-claimed by its creator and never appeared as "Open.")
- `_operator_info()` now also returns `id` (the real ERPNext user id), so the frontend can tell
  "claimed by me" apart from "claimed by someone else" without guessing from display names.

**Frontend**
- My Tasks screen rewritten: three tabs (Open / Active / History) replace the old single list;
  every card is now a single tap target (no inline Start button) that opens a details drawer
- New details drawer: customer, status, claim state, full item contents with images, and
  Start/Continue/Release actions depending on claim state - this is the "insight before accepting a
  huge order" preview, and it's the only path to starting a task now
- Removed the now-dead `openTask()` function (its only caller was the old inline Start button)

## v0.1.2 - 2026-08-29

**Backend / site configuration**
- Granted the `Warehouse Operator` role real DocType permissions via `frappe.permissions.add_permission`
  (Custom DocPerm overlay, not raw DB edits): read/write/create on `Pick Task`, `Pack Task`,
  `Shipment Task`; read/write/create/submit on `Stock Entry` and `Delivery Note` (the two real
  stock-moving documents this app submits); read-only on `Item`, `Bin`, `Warehouse`, `Sales Order`,
  `Sales Order Item`, `Purchase Order`, `Customer`, and the `Pick Task Item` / `Pack Task Item` /
  `Shipment Task Item` / `Inbound Package Item` child tables. `Inbound ASN` and `Inbound Package`
  already had read/write/create from the doctype's own base permissions - left untouched. No
  delete/cancel granted anywhere. Verified via direct Custom DocPerm query; not yet verified via a
  live login as a real Warehouse-Operator-only user.

## v0.1.1 - 2026-08-29

**Backend**
- Added `_operator_info()`: the header now shows the real signed-in user's full name and their actual
  WMS-relevant role, instead of a hardcoded `"Warehouse Operator"` placeholder for both fields regardless
  of who was logged in

## v0.1.0 - 2026-08-29

Baseline tracked release - covers this session's full set of changes, since no version tracking existed before.

**Backend**
- Removed the Pick→PickPack stock transfer; stock now stays in its real Storage bin through Pick and Pack,
  and moves exactly once, at Ship, straight out of that bin
- Ship now posts a real, submitted Delivery Note (`_create_delivery_note`) instead of moving no stock at all
- `_default_warehouse()` scoped to the Example Company (was unscoped, could default to a Soy-company
  warehouse); zone-aware (`Receiving` vs `Storage`), skips Damaged/Returns as a fallback
- Fixed naming series for `Pack Task` (`PACK-MIA-.#####`) and `Inbound ASN` (`ASN-MIA-.#####`) - both
  doctypes had no naming rule configured at all and were getting random hash names
- `_resolve_customer()` fallback now prefers `TEST COMPANY CLIENT` instead of whichever real customer
  sorts first alphabetically (was silently attributing test data to a real client, "Example Legacy Co")
- Added `_first_item_images()` helper; task-list endpoints (`_list_pick_tasks`, `_list_pack_tasks`,
  `_list_shipment_tasks`, `_list_receive_packages`) now return a representative item image per row
- Removed the `priority` concept entirely from the API surface (`_task()`, `_list_pick_tasks()`,
  `create_pick_task()`, the issues/severity field) - was decorative only (no sorting/behavior tied to it,
  Receive was hardcoded "High", Pack/Ship had no real field). The `priority` DocField is left in place on
  Pick Task's schema, unused, in case this comes back later.

**Frontend**
- Item thumbnails added throughout: Incomplete + Completed task list rows (Pick/Pack/Ship/Receive), the
  completed-detail tables (previously plain text grids with no image), Ship's completed Contents section,
  and Inventory → Total (ERP stock) rows
- Removed all priority UI: the New Pick Task priority selector, the "High priority" filter chip, and every
  priority badge/label across task cards
- Removed the decorative "Station: STAGE-01" badge from the home screen
- Added App version / build date display in Settings

