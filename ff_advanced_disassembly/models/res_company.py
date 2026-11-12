from odoo import fields, models


class ResCompany(models.Model):
    _inherit = "res.company"

    ff_partial_disassembly_enabled = fields.Boolean(default=True)
    ff_require_manager_approval = fields.Boolean(default=False)
    ff_require_financial_loss_approval = fields.Boolean(default=False)
    ff_disassembly_cost_policy = fields.Selection([("allocated", "Allocated")], default="allocated", required=True)
    ff_disassembly_destination_policy = fields.Selection([("manual", "Manual")], default="manual", required=True)
    ff_disassembly_variance_account_id = fields.Many2one(
        "account.account",
        string="Disassembly Valuation Difference Account",
        check_company=True,
        domain="[('company_ids', 'parent_of', id)]",
        help=(
            "Optional company-wide override for advanced disassembly valuation "
            "differences. If empty, the source product category's Stock Variation "
            "Account is used."
        ),
    )

    def _ff_get_disassembly_variance_account(self, product):
        """Return the configured company account, falling back to the category."""
        self.ensure_one()
        return self.ff_disassembly_variance_account_id or product.with_company(self)._get_product_accounts().get("stock_variation")


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    ff_partial_disassembly_enabled = fields.Boolean(related="company_id.ff_partial_disassembly_enabled", readonly=False)
    ff_require_manager_approval = fields.Boolean(related="company_id.ff_require_manager_approval", readonly=False)
    ff_require_financial_loss_approval = fields.Boolean(related="company_id.ff_require_financial_loss_approval", readonly=False)
    ff_disassembly_cost_policy = fields.Selection(related="company_id.ff_disassembly_cost_policy", readonly=False)
    ff_disassembly_destination_policy = fields.Selection(related="company_id.ff_disassembly_destination_policy", readonly=False)
    ff_disassembly_variance_account_id = fields.Many2one(
        related="company_id.ff_disassembly_variance_account_id", readonly=False,
    )

