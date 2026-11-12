from odoo import api, fields, models, _, Command
from odoo.exceptions import UserError, ValidationError


class DisassemblyResult(models.Model):
    _name = "ff.disassembly.result"
    _description = "Disassembly Component Result"
    _order = "id"

    line_id = fields.Many2one("ff.disassembly.line", required=True, ondelete="cascade", index=True)
    unbuild_id = fields.Many2one(related="line_id.unbuild_id", store=True, index=True)
    company_id = fields.Many2one(related="line_id.company_id", store=True, index=True)
    product_id = fields.Many2one("product.product", required=True, check_company=True, index=True)
    quantity = fields.Float(required=True, digits="Product Unit")
    condition = fields.Selection([
        ("good", "Good"), ("repairable", "Repairable"), ("scrap", "Scrap"),
        ("missing", "Missing"), ("retained", "Retained"),
    ], required=True, default="good")
    lot_id = fields.Many2one("stock.lot", check_company=True)
    destination_location_id = fields.Many2one("stock.location", check_company=True)
    recovery_factor = fields.Float(default=1.0, digits=(16, 6))
    reference_weight = fields.Monetary(currency_field="currency_id")
    allocated_value = fields.Monetary(currency_field="currency_id", readonly=True)
    currency_id = fields.Many2one(related="company_id.currency_id")
    stock_move_ids = fields.Many2many("stock.move", "ff_disassembly_result_move_rel", "result_id", "move_id", readonly=True)
    notes = fields.Text()

    @api.onchange("product_id", "quantity")
    def _onchange_output_value_weight(self):
        """Keep allocation automatic when the user changes the output SKU/quantity."""
        for result in self:
            if result.product_id and result.quantity:
                result.reference_weight = result.quantity * result.product_id.with_company(
                    result.company_id or self.env.company
                ).standard_price

    @api.onchange("recovery_factor")
    def _onchange_recovery_factor_condition(self):
        """A recovery percentage below 100% represents a repairable loss."""
        for result in self:
            if result.recovery_factor < 1.0 and result.condition == "good":
                result.condition = "repairable"
            elif result.recovery_factor >= 1.0 and result.condition == "repairable":
                result.condition = "good"

    @api.onchange("line_id")
    def _onchange_line_id(self):
        if self.line_id and not self.product_id:
            self.product_id = self.line_id.product_id

    @api.model_create_multi
    def create(self, vals_list):
        line_ids = [vals.get("line_id") for vals in vals_list if vals.get("line_id")]
        locked_lines = self.env["ff.disassembly.line"].browse(line_ids).filtered(lambda line: line.unbuild_id.ff_workflow_state in ("executing", "done", "reversed"))
        if locked_lines:
            raise UserError(_("Completed or executing orders cannot receive component results."))
        records = super().create(vals_list)
        for result in records:
            if result.unbuild_id.ff_advanced_mode:
                result.unbuild_id._ff_log("quantity", _("Result for %(product)s was added.", product=result.product_id.display_name))
        return records

    def write(self, vals):
        if not self.env.context.get("ff_internal_write") and any(result.unbuild_id.ff_workflow_state in ("executing", "done", "reversed") for result in self):
            raise UserError(_("Component results are locked during and after execution."))
        result = super().write(vals)
        if not self.env.context.get("ff_internal_write"):
            event_type = "location" if "destination_location_id" in vals else "valuation" if {"reference_weight", "recovery_factor"}.intersection(vals) else "quantity"
            for item in self:
                item.unbuild_id._ff_log(event_type, _("Result for %(product)s changed.", product=item.product_id.display_name))
        return result

    def unlink(self):
        if any(result.unbuild_id.ff_workflow_state in ("executing", "done", "reversed") for result in self):
            raise UserError(_("Completed or executing component results cannot be deleted."))
        return super().unlink()

    @api.constrains("quantity", "recovery_factor", "lot_id", "destination_location_id")
    def _check_result(self):
        for result in self:
            if result.quantity <= 0:
                raise ValidationError(_("Result quantity must be greater than zero."))
            if not 0 <= result.recovery_factor <= 1:
                raise ValidationError(_("Recovery factor must be between 0 and 1."))
            if result.lot_id and result.lot_id.product_id != result.product_id:
                raise ValidationError(_("The selected lot belongs to a different product."))
            if result.lot_id and result.lot_id.company_id and result.lot_id.company_id != result.company_id:
                raise ValidationError(_("The selected lot belongs to a different company."))

    @api.constrains("condition", "destination_location_id", "unbuild_id")
    def _check_destination(self):
        for result in self:
            if result.condition in ("good", "repairable", "scrap") and result.destination_location_id:
                location = result.destination_location_id
                if location.usage != "internal" or location.company_id not in (False, result.company_id):
                    raise ValidationError(_("Recovered result destinations must be company-compatible internal locations."))
            if result.condition == "missing" and result.destination_location_id:
                raise ValidationError(_("Missing components cannot have a receiving destination."))
            if result.condition == "retained" and result.destination_location_id:
                raise ValidationError(_("Retained components are represented by the residual assembly."))

