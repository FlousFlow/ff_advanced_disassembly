# Quality Gates

| Gate | Status | Evidence |
|---|---|---|
| G0 Source audit | PASS | Odoo 20 revision `17ff827a18248397342e73bb2bcac48e2b8e1027`; inspected native Unbuild, Manufacturing, stock move/line, product value, stock accounting, and relevant MRP accounting extensions. Odoo 20 uses `product.value` and does not provide the legacy `stock.scrap` model in this checkout. |
| G1 Foundation | PASS | Addon upgrade/install loaded security and views on dedicated database `ff_advanced_disassembly_test`; native Unbuild regression included in the suite. |
| G2 Full disassembly | PASS (covered scenarios) | BOM-backed full execution reconciles source consumption and exact recovered component quantities; MO-linked component resolution and missing/recovered-scrap scenarios also pass. This is not a claim of exhaustive traceability coverage. |
| G3 Cost/accounting | PASS (tested matrix) | Dedicated accounting tests cover Standard/FIFO/AVCO crossed with periodic and real-time valuation (6 cases), checking allocated-loss reconciliation and generated real-time journal entries. Uses the configured Odoo test chart; other localization/chart configurations remain unverified. |
| G4 Partial disassembly | PASS (covered scenario) | Partial execution creates one residual asset and checks the resulting stock/valuation on the dedicated database. Alternative UOM/tracked residual cases remain unverified. |
| G5 Security/reliability | PASS (covered scenarios) | Cost-field access denial, completed-order immutability, audit visibility, transaction rollback, cross-company record isolation, lot/serial component traceability, controlled recovery reversal, and a two-transaction execution-claim race pass. This is not an exhaustive role or multi-company matrix. |
| G6 Source lot/serial UX | PASS (targeted test) | A tracked product exposes only its positive-availability source lot; an untracked product exposes no source lot list. The inherited Odoo field remains conditionally visible and required only for lot/serial tracking. |
| Arabic translation | PASS (coverage/load) | `i18n/ar_001.po` contains 190/190 non-empty, non-fuzzy entries. Odoo loaded Arabic and `fields_get` returned translated labels for `ff_advanced_mode`, `ff_disassembly_type`, and `ff_workflow_state`. Human review of every translated sentence is not certified. |

## Test run

```sh
./odoo20-venv/bin/python odoo-bin -d ff_advanced_disassembly_test \
  --db_host=localhost --db_port=5432 --db_user=mohamedgamal \
  --addons-path=/Users/mohamedgamal/Desktop/odoo20/addons \
  -u ff_advanced_disassembly --test-enable \
  --test-tags /ff_advanced_disassembly --stop-after-init --no-http \
  --log-level=test --logfile=/tmp/ff_advanced_disassembly_final.log
```

Observed result: `0 failed, 0 error(s) of 19 post-tests` (29 Odoo-reported tests including inherited/framework tests). The accounting matrix has six subcases. A separate concurrent-transaction shell smoke test returned exactly one `claimed` and one `duplicate`; PostgreSQL serialization retry was exercised. Database: `ff_advanced_disassembly_test`, not production.

## Release status

The addon is packaged as a dedicated public GitHub repository at
`FlousFlow/ff_advanced_disassembly`, with the addon at repository root on the
`20.0` branch and version tag `20.0.1.0.2`. The cover image and expanded Apps
description are included in `static/description/`. A clean clone of the GitHub
branch was installed successfully on a disposable Odoo 20 database.

The tested matrix passes on the local test chart; do not generalize that result
to other localization charts or custom account setups. Odoo Apps marketplace
approval, automated review, customer-specific accounting, production load, and
physical warehouse execution remain external validation boundaries.
