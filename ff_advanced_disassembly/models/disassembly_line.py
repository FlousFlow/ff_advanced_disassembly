from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError


class DisassemblyLine(models.Model):
    _name = "ff.disassembly.line"
    _description = "Disassembly Component"
    _order = "sequence, id"

    sequence = fields.Integer(default=10)
    unbuild_id = fields.Many2one("mrp.unbuild", required=True, ondelete="cascade", index=True)
    company_id = fields.Many2one(related="unbuild_id.company_id", store=True, index=True)
    product_id = fields.Many2one("product.product", required=True, check_company=True, index=True)
    uom_id = fields.Many2one("uom.uom", required=True)
    bom_line_id = fields.Many2one("mrp.bom.line", check_company=True)
    source_move_id = fields.Many2one("stock.move", check_company=True)
    source_type = fields.Selection([
        ("mo", "Manufacturing Order"), ("bom", "Bill of Materials"), ("manual", "Manual"),
    ], required=True, default="bom")
    # Kept as an internal source-quantity snapshot for validation and valuation.
    # Users enter the output quantity; new manual lines receive a safe default.
    expected_qty = fields.Float(default=1.0, digits="Product Unit")
    result_ids = fields.One2many("ff.disassembly.result", "line_id")
    output_product_id = fields.Many2one("product.product", string="Output Product", check_company=True, compute="_compute_primary_output", inverse="_inverse_primary_output", store=True)
    output_quantity = fields.Float(string="Output Quantity", digits="Product Unit", compute="_compute_primary_output", inverse="_inverse_primary_output", store=True)
    output_recovery_factor = fields.Float(string="Recovered Value %", digits=(16, 6), compute="_compute_primary_output", inverse="_inverse_primary_output", store=True)
    output_destination_location_id = fields.Many2one("stock.location", string="Output Destination", check_company=True, compute="_compute_primary_output", inverse="_inverse_primary_output", store=True)
    qty_good = fields.Float(compute="_compute_result_qty", digits="Product Unit")
    qty_repairable = fields.Float(compute="_compute_result_qty", digits="Product Unit")
    qty_scrap = fields.Float(compute="_compute_result_qty", digits="Product Unit")
    qty_missing = fields.Float(compute="_compute_result_qty", digits="Product Unit")
    qty_retained = fields.Float(compute="_compute_result_qty", digits="Product Unit")
    qty_unresolved = fields.Float(compute="_compute_result_qty", digits="Product Unit")
    reference_unit_cost = fields.Monetary(currency_field="currency_id")
    currency_id = fields.Many2one(related="company_id.currency_id")
    reference_cost_source = fields.Char()
    discrepancy_reason = fields.Text()

    @api.model_create_multi
    def create(self, vals_list):
        order_ids = [vals.get("unbuild_id") for vals in vals_list if vals.get("unbuild_id")]
        locked_orders = self.env["mrp.unbuild"].browse(order_ids).filtered(lambda order: order.ff_workflow_state in ("executing", "done", "reversed"))
        if locked_orders:
            raise UserError(_("Completed or executing orders cannot receive component lines."))
        records = super().create(vals_list)
        for line in records:
            order = line.unbuild_id
            if order.ff_advanced_mode:
                order._ff_log("quantity", _("Component line for %(product)s was added.", product=line.product_id.display_name))
        return records

    def write(self, vals):
        if not self.env.context.get("ff_internal_write") and any(line.unbuild_id.ff_workflow_state in ("executing", "done", "reversed") for line in self):
            raise UserError(_("Component inspection is locked during and after execution."))
        result = super().write(vals)
        if not self.env.context.get("ff_internal_write"):
            for line in self:
                if line.unbuild_id.ff_advanced_mode:
                    line.unbuild_id._ff_log("quantity", _("Component inspection line %s changed.", line.product_id.display_name))
        return result

    @api.depends("result_ids.product_id", "result_ids.quantity", "result_ids.recovery_factor", "result_ids.destination_location_id")
    def _compute_primary_output(self):
        for line in self:
            result = line.result_ids[:1]
            if result:
                line.output_product_id = result.product_id
                line.output_quantity = result.quantity
                line.output_recovery_factor = result.recovery_factor
                line.output_destination_location_id = result.destination_location_id
            else:
                line.output_product_id = line.product_id
                line.output_quantity = line.expected_qty
                line.output_recovery_factor = 1.0
                line.output_destination_location_id = line.unbuild_id.location_dest_id

    def _inverse_primary_output(self):
        self._sync_primary_result_from_output()

    def _sync_primary_result_from_output(self):
        Result = self.env["ff.disassembly.result"]
        for line in self:
            values = {
                "product_id": (line.output_product_id or line.product_id).id,
                "quantity": line.output_quantity or line.expected_qty,
                "recovery_factor": line.output_recovery_factor,
                "destination_location_id": (line.output_destination_location_id or line.unbuild_id.location_dest_id).id,
            }
            result = line.result_ids[:1]
            if result:
                result.with_context(ff_internal_write=True).write(values)
            elif values["product_id"] and values["quantity"]:
                Result.with_context(ff_internal_write=True).create(dict(values, line_id=line.id, condition="good"))

    def unlink(self):
        if any(line.unbuild_id.ff_workflow_state in ("executing", "done", "reversed") for line in self):
            raise UserError(_("Completed or executing component lines cannot be deleted."))
        return super().unlink()

    @api.depends("result_ids.quantity", "result_ids.condition")
    def _compute_result_qty(self):
        for line in self:
            results = line.result_ids
            line.qty_good = sum(results.filtered(lambda result: result.condition == "good").mapped("quantity"))
            line.qty_repairable = sum(results.filtered(lambda result: result.condition == "repairable").mapped("quantity"))
            line.qty_scrap = sum(results.filtered(lambda result: result.condition == "scrap").mapped("quantity"))
            line.qty_missing = sum(results.filtered(lambda result: result.condition == "missing").mapped("quantity"))
            line.qty_retained = sum(results.filtered(lambda result: result.condition == "retained").mapped("quantity"))
            line.qty_unresolved = max(line.expected_qty - sum(results.mapped("quantity")), 0.0)

    @api.constrains("expected_qty", "product_id", "uom_id")
    def _check_component(self):
        for line in self:
            if line.expected_qty <= 0:
                raise ValidationError(_("Expected component quantity must be greater than zero."))
            if self._uom_root(line.uom_id) != self._uom_root(line.product_id.uom_id):
                raise ValidationError(_("The component unit must belong to the product's unit category."))

    @staticmethod
    def _uom_root(unit):
        while unit.relative_uom_id:
            unit = unit.relative_uom_id
        return unit

    @api.constrains("unbuild_id", "source_type", "discrepancy_reason")
    def _check_manual_evidence(self):
        for line in self:
            if line.source_type == "manual" and not line.discrepancy_reason:
                raise ValidationError(_("Manual component lines require a documented source reason."))

