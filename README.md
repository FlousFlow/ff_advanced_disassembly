# Flous Flow Advanced Disassembly

Odoo 20 Community addon extending Manufacturing Unbuild with component inspection, per-result destinations, allocation records, audit events, and a residual assembly representation for partial disassembly. It also provides a native stock-move based Recovery Operation for recycling and hybrid disassembly/recycling workflows.

## Compatibility and dependencies

- Odoo 20.0 Community
- `mrp`, `stock_account`, and `mail`
- No Enterprise dependencies

## Install

Place this addon in an active Odoo addons path, update the Apps list, and install **Flous Flow Advanced Disassembly**. For command-line installation, include its parent directory in `--addons-path` and use `-i ff_advanced_disassembly`.

## Configuration

Manufacturing settings store company-scoped values. Defaults are partial disassembly enabled, manager approval disabled, financial loss approval disabled, allocated cost policy, and manual destinations. Changing settings does not rewrite completed order snapshots.

Users need the Advanced Disassembly User group; the cost viewer and administrator groups provide additional cost and administration access.

## Recycling and hybrid operations

Use **Manufacturing → Recovery Operations** when the source product can be transformed into different products or when disassembly and recycling must be coordinated in one controlled operation. Inputs and actual outputs are editable before validation, output products may be selected dynamically, and each output can be classified as usable, secondary, or waste. Every physical quantity is posted through standard `stock.move` and `stock.move.line` records.

The Recoverable Value policy supports a percentage of the source carrying value or a documented target amount. Values are allocated across usable outputs using explicit weights; recycling costs are captured as an operational field but are not silently capitalized or expensed. Loss recognition is deferred by default and requires an accounting account plus valuation evidence before a journal entry can be posted.

## Full workflow

Enable Advanced Disassembly on an Unbuild order, load components from a completed Manufacturing Order or the selected BoM, review the component snapshot, split each component into result quantities, assign lots and destinations, validate, and execute. Native Unbuild remains in use when Advanced Disassembly is disabled.

## Partial workflow

Choose Partial, classify retained component quantities, select a distinct residual product and internal destination, then validate and execute. The residual assembly is created as a separate stock move with a stored retained-component snapshot.

## Destinations and traceability

Good, repairable, and physically recovered scrap outcomes need a company-compatible internal destination. Missing and retained outcomes cannot have their own receiving location. Tracked recovered goods need a matching lot or serial. Source lot/serial is required for tracked finished products.

## Cost allocation and accounting

The addon allocates the source move's carrying value using the explicit reference weights on inspection results. Repairable results use the recorded recovery factor; residual assembly uses retained-result weights. Odoo 20's `product.value` API supplies manual move valuation for asset outputs. The source move and actual output move values are compared before completion.

**Accounting validation status:** automated tests cover Standard, FIFO, and AVCO crossed with periodic and real-time valuation (six cases), including allocated-loss reconciliation and native Odoo valuation layers; real-time journal posting is used when the chart has the required valuation accounts. The suite also records (rather than silently capitalizes) any recovered-output valuation mismatch for review. Other localization charts and custom account configurations still need validation.

Odoo 20 in the inspected checkout does not expose the legacy `stock.scrap` model. The implementation uses native `stock.move.is_scrap` for recovered-scrap disposal.

## Odoo Apps packaging

This repository is a dedicated single-addon repository. The addon directory is
the repository root and the `20.0` branch matches the supported Odoo series.
Generated Python caches, local databases, logs, and virtual environments are
excluded from version control. The package includes an LGPL-3 manifest license,
an application icon, a cover image, Arabic translations, access controls, and
installation/upgrade documentation.

## Tests

Run the module tests on a dedicated database with Odoo's `--test-tags /ff_advanced_disassembly` runner. The automated suite covers default settings, allocation arithmetic, stock execution and exact stock deltas, missing/recovered scrap, valuation rollback, residual execution, MO component resolution, native Unbuild regression, immutability, audit visibility, cost access, tracked component lots/serials, company isolation, and the six-case accounting matrix. A separate shell smoke test covers concurrent execution claims. See `docs/QUALITY_GATES.md` for the exact run and evidence.

## Upgrade notes

Back up the database before upgrading. The addon adds fields to `mrp.unbuild` and creates component, result, residual, cost, and event records. Completed advanced orders are guarded against ordinary edits; corrections currently require a separately designed traceable corrective workflow.

Recovery operations are likewise immutable after execution. The administrator-only **Reverse Operation** action creates new reversing stock moves linked to the original moves; it never edits a completed move in place. Optional recipe/yield master data, localization-specific accounting matrices for the new model, and browser/mobile regression evidence remain follow-up work before presenting the addon as a fully Apps-Store-complete recycling suite.
