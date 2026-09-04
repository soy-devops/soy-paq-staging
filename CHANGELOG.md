# SoyPaq WMS Changelog

Tracks every shipped change set for the mobile WMS app (`apps/soypaq/ui`, `apps/soypaq/soypaq/api.py`).
The current version is shown in the app under Settings → App version.

Convention: bump `APP_VERSION` / `APP_BUILD_DATE` in `apps/soypaq/ui/src/App.vue` on every change set that
reaches a running site (local or prod), and log it here with Backend/Frontend split.

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

