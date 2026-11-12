# Advanced Disassembly User Guide

This guide describes the user-facing workflow in Odoo 20 Community. The module
keeps the standard Odoo vocabulary wherever possible: Unbuild Orders, internal
locations, stock moves, valuation, lots, serials, and journal entries.

## Choose the right document

| Situation | Use |
|---|---|
| Components should be returned from a finished product using its MO or BoM | Advanced Unbuild |
| Only some component quantity is retained as a new residual assembly | Partial Advanced Unbuild |
| The output is a different SKU or a recycling result | Recovery Operation |
| A repeatable output mix is used often | Recovery Recipe, then Apply Recipe |

## Advanced Unbuild screen

The primary screen is intentionally focused on the decisions the operator must
make:

- **Source Product Location**: where the finished product is consumed.
- **Source Lot / Serial**: shown only when the source product uses lot or serial
  tracking. The selector is filtered to the selected product's lots/serials
  with available quantity in the source location, so unrelated products and
  empty lots cannot be selected.
- **Disassembly Type**: Full or Partial.
- **Output Cost Value**: one company-currency amount for the whole operation.
  This is the total value assigned to the recovered output products; it is not
  repeated or entered on every output line.
- **Expected Cost Difference**: a read-only estimate of the unrecovered source
  value (`source carrying value - output cost value`).
- **Component Inspection**: the editable component/output table.

When the product and a completed Manufacturing Order or BoM are selected, the
component snapshot appears automatically. The operator then edits the actual
output product, output quantity, and storage destination. If one component
becomes two different outputs, open the component line and add a result line.

## Status flow

```text
Draft → Inspection → Ready → Executing → Done
                                      ↘ Reversed
```

- **Draft**: select the product, source, MO/BoM, and operation type.
- **Inspection**: review the automatically loaded component snapshot.
- **Ready**: inspection passed all quantity, tracking, location, and accounting
  checks.
- **Executing**: stock moves are being claimed and completed.
- **Done**: stock and valuation records are posted and the document is locked.
- **Reversed**: an administrator created linked reversing stock/accounting
  records.

## Result conditions

- **Good**: usable output at the recovered destination.
- **Repairable**: output is physically recovered but the operation's output cost
  value leaves a valuation difference.
- **Scrap**: physically recovered scrap handled through a native stock move.
- **Missing**: expected quantity not physically recovered; no receiving
  destination is allowed.
- **Retained**: component remains in a residual assembly and is valid only for
  Partial disassembly.

## Recovery and Recycling Operation

Recovery Operations are designed for a controlled transformation rather than a
strict BoM return. The operator records source inputs and actual outputs, then
chooses the value policy before validation.

The processing location is automatically derived from the warehouse's standard
Production location. This is an internal technical location used so the stock
quantity change is visible; it is not an accounting account.

## Accounting explanation

The source carrying value is taken from Odoo's stock valuation. Recoverable value
is allocated across outputs using automatic reference weights. Any remaining
value is the expected valuation difference. The company may explicitly choose a
shared disassembly valuation-difference account; otherwise the source product
category's Stock Variation Account is used.

The operation creates one balanced journal entry for the advanced disassembly
valuation effect. Reversal creates a new reversing entry and never edits the
original posted entry.

## Operator checklist

Before clicking **Validate Inspection** or **Validate**:

1. Source location is internal and belongs to the company.
2. Every physically recovered output has an internal destination.
3. Output quantities fully account for each component line.
4. Lots/serials match the selected product and quantity.
5. The source category has valuation and stock-variation accounts for real-time
   valuation.
6. Partial retained results have a different residual product and internal
   destination.

## Administrator checklist

- Review the company Advanced Disassembly settings.
- Decide whether a shared valuation-difference account is required.
- Grant Cost Viewer only to users who need monetary valuation details.
- Grant Administrator only to users who can reverse operations or configure
  controlled financial actions.
- Test the workflow on a duplicated database before production use.
