{
    "name": "Advanced Disassembly",
    "version": "20.0.1.0.0",
    "summary": "Traceable component recovery and residual stock handling for manufacturing unbuild orders",
    "description": """
Advanced Disassembly for Odoo 20 Community.

Inspect and control component recovery during manufacturing unbuild operations,
assign output destinations, support partial disassembly, and keep stock and
valuation changes traceable through standard Odoo records.
""",
    "category": "Manufacturing/Operations",
    "author": "Flous Flow",
    "website": "https://github.com/FlousFlow/ff_advanced_disassembly",
    "license": "LGPL-3",
    "images": ["static/description/cover.png"],
    "depends": ["mrp", "stock_account", "mail"],
    "data": [
        "data/sequence.xml",
        "security/security.xml",
        "security/ir.access.csv",
        "views/mrp_unbuild_views.xml",
        "views/recovery_operation_views.xml",
        "views/res_config_settings_views.xml",
    ],
    "installable": True,
    "application": True,
}
