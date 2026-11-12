# Architecture

`mrp.unbuild` remains the operational document. `ff.disassembly.line` snapshots expected components; `ff.disassembly.result` records dispositions and per-result destinations; `ff.disassembly.residual` identifies the separately stocked remainder; `ff.disassembly.cost` stores allocation provenance; and `ff.disassembly.event` records order creation, inspection, and execution events.

Component resolution reads actual completed raw moves when an MO is linked, otherwise it explodes the selected BoM. The first implementation uses company product cost as the documented fallback weight. Inspection results are editable before execution and are checked against expected quantities with Odoo's product-unit precision.

Execution locks the unbuild row, validates source quantity, consumes the finished assembly with a native `stock.move`, receives recovered outputs using native stock moves, and records supported manual move values through `product.value`. Partial execution creates a distinct residual-product move and retained-component snapshot. Stock valuation is compared to the allocation before the order is marked done; exceptions roll the transaction back.

Security uses Odoo 20 `ir.access` company domains and separate operational/cost/admin groups. Native Unbuild delegates to Odoo unchanged unless advanced mode is enabled.

## Current limits

Missing and recovered-scrap outcomes execute and reconcile stock move values; when real-time valuation creates accounting moves, their posted entries are checked against the allocated loss. Recovery operations use the same native stock lifecycle and provide an administrator-only controlled reversal that creates linked reversing moves. Automated coverage currently exercises the default test valuation configuration and a rollback on recovered-scrap valuation mismatch. The Standard/FIFO/AVCO and periodic/perpetual accounting matrix for the new recovery model, tracked lots/serials on recovery lines, and browser/mobile regression remain unverified.
