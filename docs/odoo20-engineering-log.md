# Odoo 20 Engineering Log

## 2026-11-11 — Recovery and hybrid operation foundation

- Inspected Odoo 20 revision `17ff827a` and the native `mrp.unbuild`, `stock.move`, `stock.move.line`, `stock_account`, and `product.value` implementations.
- Kept native `mrp.unbuild` as the full/partial disassembly path. Added `ff.recovery.operation` because arbitrary recycling outputs do not fit the native Unbuild BoM contract safely.
- Recovery operations consume inputs and produce actual outputs through native stock moves. Manual move values use Odoo 20 `product.value`; no global `standard_price` rewrite or core patch is used.
- Recoverable value can be percentage-based or a documented target. Loss recognition is deferred unless an administrator explicitly supplies a loss account and valuation evidence.
- Verified module upgrade/install and two recovery tests on `ff_advanced_disassembly_test`; the existing disassembly suite still passes on the same database.
- Repaired and re-exported the Arabic PO so Odoo loads it cleanly; translated the new recovery/recycling UI labels and messages.
- Added administrator-only server checks for documented-loss recognition and controlled reversal. Full module run now reports `0 failed, 0 error(s)` for 19 post-tests / 29 Odoo-reported tests. A fresh database install and subsequent uninstall were also smoke-tested successfully.
- UX review: moved valuation/loss policy out of the primary entry area into a dedicated tab, replaced manually-rendered chatter internals with the native `<chatter/>` component, added standard empty-list guidance, and completed Arabic labels for the recovery workflow. Verified the form on desktop and mobile widths.
- Follow-up UX simplification: removed the informational recycling-cost input from the user form, hid valuation reconciliation until the operation is completed/reversed, hid loss classification and value-allocation weight by default, and translated the hybrid operation type. The underlying fields remain for compatibility and controlled reporting.
- Loss-recognition UX: made the loss account and evidence visibly required when recognition is selected, added an Arabic evidence placeholder, and translated the validation errors so the accounting safeguard explains the next action instead of surfacing English text.
- User decision: remove documented-loss recognition from the normal recovery UI. The recognition fields and action button are no longer shown; legacy backend fields and behavior remain for compatibility with existing records and integrations.
- Recovery usability fix: a single non-waste output now receives allocation weight `1.0` automatically, so users do not need to understand the hidden allocation-weight field. Positive weights remain required only when splitting value across multiple outputs; added regression coverage.
- Stock-flow fix: the recovery processing location now defaults to the warehouse production location instead of `WH/Stock`, preventing source moves from being created as stock-to-stock no-ops. Validation now blocks identical source/processing locations; existing completed operations are left immutable for auditability.
- Known boundaries: reversal/correction wizard, recipe/yield master data, full localization chart matrix for the new model, and browser/mobile regression evidence are not yet complete.
- Added an administrator-only controlled reversal action. It creates new stock moves with `origin_returned_move_id`, links them to the operation, and marks the operation `reversed`; completed moves remain immutable. A dedicated reversal test passes.
### 2026-11-11 — Internal recovery valuation journal

Recovery moves between stock and the production location do not receive native
stock-accounting entries when neither location has a valuation account. The
operation now posts one balanced valuation journal: source inventory is
credited, recovered output inventory is debited at the native move value, and
the difference is posted to the source product's stock variation account. The
existing demo operation `REC/00045` was repaired with posted journal
`STJ/2026/11/0001`.

### 2026-11-11 — Unified advanced unbuild UX

Advanced disassembly now auto-loads component lines when a product and BoM/MO
are selected. Recovery results can use a different product SKU when a component
is transformed into a new item. The standalone recovery menu is administrator-
only, technical locations and valuation fields are clarified or hidden, and
lot/serial columns are optional for non-tracked products.

### 2026-11-11 — Configurable disassembly valuation-difference account

Added a company-level Advanced Disassembly setting for the valuation-difference
account. Recovery-operation journals now use this account when configured and
fall back to the product category stock-variation account for backward
compatibility. The settings view and valuation explanation now describe the
fallback clearly in Arabic.

### 2026-11-11 — Simplified advanced disassembly form

Removed the user-facing Cost Allocation, Residual Assembly, and Audit Events
tabs from the advanced unbuild form. The main component screen now focuses on
expected quantity, recovered quantity, output product, recovery percentage, and
storage destination; valuation and audit records remain stored for controls and
reports.

Partial disassembly validation now requires residual assembly settings only when
the user explicitly marks a result as retained. Ordinary output results can be
validated from the simplified component table without the removed residual tab.

The demo database's `Production` location was configured with a distinct stock
variation/valuation-difference account (`110200 Inventory Variation`) rather
than the source inventory valuation account. This keeps native output and loss
entries balanced during real-time disassembly.

The component table now exposes the primary output product, output quantity,
recovery percentage, and destination directly. These fields stay synchronized
with the underlying result line. Changing the output SKU or quantity recalculates
its allocation weight from quantity × product standard cost, and a recovery
percentage below 100% automatically classifies the result as repairable so the
difference is allocated as loss.

The recovery percentage is now an operation-level field rather than a repeated
per-output input. The engine applies that single percentage to every result at
validation time, preventing inconsistent loss percentages across one operation.

The advanced unbuild header now shows the expected cost difference immediately.
Drafts estimate it from the current product standard cost, while executed
orders use the captured source carrying value; the configured recovery
percentage determines the unrecovered portion.

The component expected quantity is now an internal snapshot with a default,
not a required user-entered field. This keeps the source quantity available for
validation while allowing users to add a component line without exposing or
manually supplying that technical value.

### 2026-11-11 — Category-driven real-time valuation

The default remains category-driven: for real-time valuation, the engine derives
the production-side account from the source product category's Stock Variation
Account and applies it to the technical production location when Odoo's native
stock move engine requires a location valuation account. A company-level account
can now be selected as an explicit override when one account must be shared by
all advanced disassembly and recovery operations in that company.

### 2026-11-11 — Controlled advanced disassembly reversal

Completed advanced disassembly orders now expose an administrator-only “Reverse
Operation” action. It creates new stock moves in the opposite direction, preserves
lot/serial traceability, and relies on Odoo's native stock-accounting engine to
create the reversing valuation entries. Original posted moves and journal entries
remain immutable; the operation is marked `reversed` and linked to its reversal
moves and journal entries.

### 2026-11-12 — Single valuation journal per advanced disassembly

Advanced disassembly stock moves now defer native account-move creation until all
source, output, residual, and scrap moves are completed. Odoo still creates and
links the individual valuation layers, while one balanced posted journal contains
the complete operation. The inspection button is limited to draft advanced orders;
ready orders expose only the execution action.

### 2026-11-12 — Odoo Apps release packaging

Prepared the addon as a dedicated repository-root package for Odoo 20. The
manifest now includes a full description and project website, the package has a
release `.gitignore`, and the repository will publish only this addon on branch
`20.0`. Release validation excludes Python caches and local runtime artifacts;
Apps review, marketplace approval, and localization-specific accounting checks
remain external review boundaries.

