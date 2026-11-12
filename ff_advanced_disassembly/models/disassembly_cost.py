from odoo import fields, models


class DisassemblyCost(models.Model):
    _name = "ff.disassembly.cost"
    _description = "Disassembly Cost Allocation"
    _order = "id"

    unbuild_id = fields.Many2one("mrp.unbuild", required=True, ondelete="cascade", index=True)
    company_id = fields.Many2one(related="unbuild_id.company_id", store=True, index=True)
    currency_id = fields.Many2one(related="company_id.currency_id")
    source_move_id = fields.Many2one("stock.move", check_company=True)
    source_carrying_value = fields.Monetary(currency_field="currency_id")
    reference_weight_total = fields.Monetary(currency_field="currency_id")
    result_id = fields.Many2one("ff.disassembly.result", ondelete="set null")
    allocation_weight = fields.Monetary(currency_field="currency_id")
    allocation_ratio = fields.Float(digits=(16, 8))
    allocated_amount = fields.Monetary(currency_field="currency_id")
    actual_valuation_amount = fields.Monetary(currency_field="currency_id")
    variance = fields.Monetary(currency_field="currency_id")
    loss_amount = fields.Monetary(currency_field="currency_id")
    valuation_reference = fields.Char()


class DisassemblyResidual(models.Model):
    _name = "ff.disassembly.residual"
    _description = "Residual Assembly"
    _order = "id"

    unbuild_id = fields.Many2one("mrp.unbuild", required=True, ondelete="cascade", index=True)
    company_id = fields.Many2one(related="unbuild_id.company_id", store=True)
    original_product_id = fields.Many2one(related="unbuild_id.product_id", store=True)
    original_lot_id = fields.Many2one("stock.lot", check_company=True)
    residual_product_id = fields.Many2one("product.product", required=True, check_company=True)
    residual_lot_id = fields.Many2one("stock.lot", check_company=True)
    quantity = fields.Float(required=True, digits="Product Unit")
    retained_components_snapshot = fields.Json(default=dict)
    allocated_value = fields.Monetary(currency_field="currency_id")
    currency_id = fields.Many2one(related="company_id.currency_id")
    destination_location_id = fields.Many2one("stock.location", required=True, check_company=True)
    stock_move_id = fields.Many2one("stock.move", check_company=True)

