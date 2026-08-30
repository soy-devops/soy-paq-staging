# SoyPaq WMS — Frontend Design Philosophy

This is the standing reference for how the mobile WMS app (`apps/soypaq/ui`) makes UI decisions.
When a new screen or feature raises a question this doesn't answer, use the reasoning here to judge
it the way we'd judge it together — then add the answer back to this file.

See `apps/soypaq/CHANGELOG.md` for what's actually shipped. This file is principles, not history.

## Core principles

**1. Global visibility, not per-user silos.**
Every task — open, active, or completed — is visible to every operator, not filtered to "mine."
Individual identity (real ERPNext users/roles/permissions) already governs who's *allowed* to do
what; the task lists themselves don't need a second, parallel local/global permission model layered
on top. Splitting "my view" from "everyone's view" adds real complexity for no operational benefit
here, and it's explicitly something we chose to avoid as the codebase grows.

**2. Assignment happens at Start, not at creation.**
Creating a task (however it originates — typed form, inventory browsing, future ASN/shop sync)
does not assign it to anyone. Tapping **Start** is the claim: it stamps the current real user as
the assignee at that moment. This is what makes "who's working on what" trustworthy — the assignee
field reflects who is actually doing the work, never who happened to create the record.

**3. Forced context before commitment.**
A task card is never itself the "go" button. Tapping a card always opens a details drawer first
(items with images, quantities, customer, claim status, any source-order mismatch) — **Start** or
**Continue** lives *inside* that drawer, not on the card. There is no shortcut path to starting a
task blind. This applies everywhere task cards appear (My Tasks, and every stage's own Incomplete
tab) — one interaction pattern, not a special case per screen.

**4. Claim conflicts: timeout + manual release, not silent overwrite.**
A claimed task can't be silently re-claimed by someone else. If it sits inactive too long, it
auto-releases back to the open queue (timeout). An operator can also manually release it early
(Cancel → back to queue) — distinct from the doctype's real Cancelled status, which abandons the
order entirely. Never let two operators end up mid-pick on the same task at once.

**5. No decorative UI.** Every field or badge either drives real behavior or gets removed. We've
already removed two things that looked functional but weren't: the "Station: STAGE-01" badge (pure
decoration, no underlying concept) and Priority tiers (a field that existed and rendered a badge but
never sorted, routed, or changed anything — Urgent and Normal literally rendered identically). If a
feature is worth having, wire it up for real; if it's not being wired up, don't leave the
half-built version sitting in the UI implying it does something.

**6. Real data over hardcoded placeholders.** The header used to show a static "Warehouse Operator"
string regardless of who was actually logged in. Now it computes the real signed-in user's name and
their actual relevant role. Never let a hardcoded string stand in for something the system already
knows — if the real value can be fetched, fetch it, even for a value that's "always been right" in
testing so far (it was right by coincidence, not by construction).

**7. One visual treatment per kind of data, applied everywhere.** Anywhere an item appears — task
list rows, completed-detail views, contents sections, inventory rows — it gets the same
`wms-item-thumb` treatment (image, or a `lucide-shirt` fallback icon). Don't let some views show
images and others show plain text for the same underlying data; that inconsistency is itself a bug,
not a style choice.

**8. One path for one cross-cutting action.** Returning to ERPNext Desk should exist as a single,
predictable entry point, not scattered per-record "Open in Desk" buttons duplicated across every
screen. When an action is conceptually global (not tied to the specific record you're looking at),
give it one home, not N.

**9. Bottom nav reflects true state, not just the literal screen name.** The active nav icon should
represent where the operator actually *is* conceptually — e.g. "My tasks" stays highlighted while
inside any Receive/Pick/Pack/Ship working screen, not only on the literal task-list screen. Nav
highlighting should never leave the operator with nothing lit up while they're clearly doing
something.

**10. Multiple creation paths are fine when the real world has multiple paths.** Typed item-code
entry and inventory-browse-to-build both stay, side by side, because a worker holding a paper
invoice sometimes has clean SKUs to type and sometimes doesn't. Don't collapse two genuinely
different real-world workflows into one UI just for the sake of having only one way to do it.

**11. This is a job tracker, not a shop.** Avoid retail/e-commerce metaphors (persistent cart icons,
"checkout" language, badge counters styled like a shopping cart). The mental model is "jobs
operators accept and complete," not "items a customer purchases" — language and iconography should
stay consistent with that.

**12. Don't guess at facts only the user knows.** Business-model questions (3PL client vs. supplier
relationship, per-user vs. per-station logins, what counts as "urgent") get asked, not assumed, even
when a plausible-sounding default exists. A wrong assumption here isn't a UI bug, it's a business
logic bug.

## Concrete conventions

- **Item thumbnail markup:** `<div class="wms-item-thumb shrink-0"><img v-if="x.image" :src="x.image" :alt="x.name" /><span v-else class="lucide-shirt size-5 text-ink-green-6" aria-hidden="true" /></div>` — reuse this exact pattern, don't invent a new one per screen.
- **Backend vs. frontend split:** every change gets communicated (and committed to CHANGELOG.md) with an explicit Backend/Frontend breakdown.
- **Version discipline:** bump `APP_VERSION` / `APP_BUILD_DATE` in `App.vue` on every shipped change set, and log it in `apps/soypaq/CHANGELOG.md` with the same Backend/Frontend split.

## Status: directional vs. shipped

Principle 3 (forced-drawer Start) and the manual-release half of principle 4 shipped in v0.2.0.
As of v0.3.0, principle 3 is universal in practice, not just in intent - every stage's own task
list (not only My Tasks) renders through the same Open/Active/History + drawer code path, so there
is no remaining screen with an inline "Start" button that bypasses the claim system. That
unification is also what fixed a real bug: the old per-stage screens' own Start buttons never
called `claim_task` at all, letting one operator hold two active jobs at once.

The *timeout* half of principle 4 (auto-releasing a stale claim) is still agreed design, not built —
manual "Release back to queue" is live, automatic release after inactivity is not. Don't assume the
timeout is running; check CHANGELOG.md for what's actually shipped before building on top of it.

Also worth knowing: v0.3.1 fixed a bug where backend error messages (`frappe.throw()`) never
actually reached the user - the toast showed generic HTTP status text instead. If you're adding a
new error path, use `extractErrorMessage()` (or the `pickApi`/`fetchApi` helpers that already call
it) rather than reading `payload.message` directly - that key holds the whitelisted function's
return value on success, not the error text on failure.
