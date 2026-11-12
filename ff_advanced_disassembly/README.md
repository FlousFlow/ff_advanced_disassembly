# Flous Flow Advanced Disassembly

Advanced component disassembly, recovery, and recycling controls for **Odoo 20
Community**. The addon extends the native Manufacturing Unbuild document while
keeping stock moves, valuation layers, journal entries, traceability, and audit
events in standard Odoo models.

## Why this addon exists

Standard unbuild is ideal when every component is returned exactly as defined by
the BoM. Real workshops also need to record recovered quantities, changed output
SKUs, repairable components, scrap, missing quantities, partial disassembly,
recycling, and valuation differences. This addon adds those controls without
replacing the standard Odoo flow when advanced mode is disabled.

## Compatibility

| Item | Value |
|---|---|
| Odoo series | 20.0 Community |
| License | LGPL-3 |
| Module technical name | `ff_advanced_disassembly` |
| Required modules | `mrp`, `stock_account`, `mail` |
| Enterprise dependency | None |
| Supported language | English and Arabic translation included |

The repository is intentionally a dedicated single-addon repository. The addon
is at the repository root and the supported Git ref is `20.0`.

## Main capabilities

### Advanced Manufacturing Unbuild

- Enable advanced mode on an Unbuild order while preserving native Unbuild when
  advanced mode is off.
- Use the standard source-location field, labelled **Source Product Location**
  in the advanced form.
- For lot- or serial-tracked source products, show the standard source tracking
  field only when tracking is enabled and filter it to matching lots/serials
  available in the selected source location. Untracked products do not show it.
- Select **Full** or **Partial** disassembly.
- Auto-load component lines from a completed Manufacturing Order or the selected
  Bill of Materials as soon as the product and source are available.
- Edit the output product, output quantity, destination, lot, or serial before
  validation. Enter the total output cost value once at operation level.
- Add a different product SKU when a component is transformed into another item.
- Mark outcomes as good, repairable, scrap, missing, or retained.
- Show the expected cost difference immediately from the source carrying value
  estimate and the operation output cost value.
- Validate an inspection, then execute the stock operation through native stock
  moves.
- Keep completed records immutable and expose an administrator-only reversal
  action that creates linked reversing stock moves and accounting entries.

### Partial disassembly

Partial mode uses the same component/result table. A residual assembly product
and internal destination are requested only when a result is explicitly marked
as **Retained**. The residual component snapshot is stored for traceability and
the residual stock move is linked to the operation.

### Recovery and recycling operations

The administrator-only **Manufacturing → Recovery Operations** menu is intended
for recycling or hybrid transformations where the output is not simply the BoM
component list.

- Record one or more source input lines.
- Choose Recycling or Disassembly and Recycling.
- Optionally apply a reusable recovery recipe.
- Enter actual output products and quantities before execution.
- Classify outputs as usable, secondary, or waste and assign internal
  destinations.
- Enter a single output cost value for the operation; the remaining source value
  becomes the valuation difference.
- Execute and reverse through linked native stock moves.

## Recommended workflow

### Full advanced disassembly

1. Open **Manufacturing → Operations → Unbuild Orders** and create an order.
2. Select the finished product, quantity, source location, and completed MO or
   BoM.
3. Enable **Advanced Disassembly**. The component inspection lines are loaded
   automatically.
4. In **Component Inspection**, set the actual output product, quantity, and
   internal destination. Add a result line when a component splits into more
   than one outcome.
5. Set the operation-level output cost value. The remaining source carrying
   value is the expected valuation difference/loss.
6. Click **Validate Inspection**. The order moves to Ready after quantities,
   locations, tracking, and valuation rules pass validation.
7. Click **Execute Disassembly**. Odoo creates the source/output stock moves
   and the valuation records.
8. If a completed operation must be corrected, an Advanced Disassembly
   Administrator can use **Reverse Operation**. The original moves and posted
   journal entries are never edited in place.

### Recovery operation

1. Open **Manufacturing → Recovery Operations**.
2. Choose the source location and review the default processing location. The
   processing location is the warehouse production location used to make the
   physical stock change visible.
3. Add input lines and actual output lines, or apply a recovery recipe.
4. Choose the recoverable-value policy and complete the required destinations.
5. Click **Validate**, then **Execute Recovery**.
6. Use **Reverse Operation** only when the operation is complete and the user
   has administrator rights.

## Valuation and accounting behavior

The addon uses the source carrying value captured from Odoo stock valuation. It
allocates the recoverable value across outputs using automatic reference weights
based on output quantity and product cost. Users do not need to maintain a
technical allocation-weight field for the normal workflow.

For advanced disassembly, source, output, residual, and scrap valuation moves
are consolidated into one balanced journal entry for the operation. The entry
contains the net stock valuation effect and the configured valuation-difference
account when a difference remains.

The valuation-difference account follows this order:

1. The optional company-level **Disassembly Valuation Difference Account** in
   Manufacturing settings, when configured.
2. Otherwise, the source product category's **Stock Variation Account**.

The module does **not** invent a new Production account automatically. Normal
Odoo category accounting remains the default; the company setting is an explicit
override for companies that want one shared account.

For real-time valuation, the relevant product categories must have valid stock
valuation accounts and the company must have a stock valuation journal. The
module reports a clear validation error when the accounting configuration is
incomplete instead of posting an unbalanced entry.

## Configuration

Go to **Manufacturing → Configuration → Settings → Advanced Disassembly**.

- **Enable Partial Disassembly**: allow retained residual assemblies.
- **Require Manager Approval**: enable the approval policy for the operation.
- **Require Financial Loss Approval**: enable the configured loss-approval
  policy.
- **Disassembly Valuation Difference Account**: optional company-wide override;
  leave empty to use the source category's Stock Variation Account.
- **Cost Policy** and **Destination Policy**: keep the company-approved policy
  used by the validation engine.

Before executing real-time valuation, also verify the standard Odoo setup:

- product category stock valuation account;
- product category stock variation account;
- stock valuation journal;
- internal warehouse and production locations;
- product tracking and lot/serial configuration when applicable.

## Security and permissions

The module exposes one dedicated **Advanced Disassembly** permission scope in
the standard Odoo 20 Users form under Supply Chain. Assign one of these module
roles explicitly:

| Module role | Purpose |
|---|---|
| Advanced Disassembly User | Create, inspect, validate, and execute module operations |
| Advanced Disassembly Cost Viewer | Includes User access and shows valuation/cost details |
| Advanced Disassembly Administrator | Includes Cost Viewer access, configuration, and reversal actions |

The roles imply the minimum native Manufacturing role needed by the underlying
stock/MRP documents. Native Manufacturing or Accounting roles alone do **not**
grant access to this addon, keeping module permissions separate and auditable.
The same external IDs are retained for upgrades from earlier releases.

Completed and reversed operations are immutable. Reversal creates new linked
records, preserving the audit trail.

## Troubleshooting

### “Configure the Stock Valuation Account…”

Open the source product's category and verify Stock Valuation Account and Stock
Variation Account. If the company override is used, verify that the selected
account belongs to the current company.

### “Select a destination…”

Recovered, repairable, and scrap results require a company-compatible internal
location. Missing and retained results do not receive a normal output location.

### Quantities do not validate

The result quantities for each component must fully account for the component
snapshot. Use separate result lines for different products or conditions.

### Tracked products fail validation

Select the matching lot or serial from the source tracking field. The field is
hidden for untracked products and its dropdown is limited to the selected
product's available stock in the source location (plus the lot produced by the
linked manufacturing order when applicable). Serial-tracked finished products
are handled one serial per operation, and each serial output quantity must be
one.

### A completed order cannot be edited

This is intentional. Use the administrator-only reversal action and create a new
corrective operation rather than rewriting posted stock or accounting history.

## Installation

### Command line

```sh
git clone --branch 20.0 \
  ssh://git@github.com/FlousFlow/ff_advanced_disassembly.git

# Add the cloned directory to --addons-path, then:
./odoo-bin -d my_database -i ff_advanced_disassembly
```

### Odoo Apps interface

1. Copy the addon into an active addons path.
2. Activate developer mode.
3. Open **Apps → Update Apps List**.
4. Search for **Flous Flow Advanced Disassembly** and install it.

## Tests and quality gates

Run the focused test suite on a disposable Odoo 20 database:

```sh
./odoo-bin -d ff_advanced_disassembly_test \
  --db_host=localhost --db_port=5432 --db_user=mohamedgamal \
  --addons-path=/path/to/odoo/addons,/path/to/ff_advanced_disassembly-parent \
  -u ff_advanced_disassembly --test-enable \
  --test-tags /ff_advanced_disassembly --stop-after-init --no-http
```

The maintained test evidence covers installation/upgrade, full and partial
execution, BOM and MO component resolution, stock deltas, valuation rollback,
real-time accounting combinations, access control, company isolation,
immutability, lots/serials, controlled reversal, and execution-claim
concurrency. See `docs/QUALITY_GATES.md` for the recorded command and test
boundaries.

## Upgrade notes

Back up the database before upgrading. The module adds fields to `mrp.unbuild`
and creates component, result, residual, cost, and event records. Existing
standard Unbuild orders continue to use native Odoo behavior when advanced mode
is disabled.

Completed advanced records are intentionally immutable. Corrections should use
the reversal workflow and a new traceable operation.

## Known limits

- Odoo Apps marketplace approval and automated review are external to this
  repository.
- Localization-specific account charts and every custom multi-company role
  matrix require customer-side validation.
- Physical warehouse execution, production load, and organization-specific
  approval policies must be tested in staging before production use.
- The module does not silently capitalize or expense undocumented losses.

## Repository and release

This is a dedicated single-addon repository. The supported branch is `20.0`,
the manifest version is `20.0.1.0.5`, and generated caches/local runtime files
are excluded from Git.
