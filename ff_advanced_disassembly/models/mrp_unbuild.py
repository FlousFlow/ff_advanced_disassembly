import uuid

from odoo import api, fields, models, _, Command
from odoo.exceptions import UserError, ValidationError
from odoo.tools import float_compare


class MrpUnbuild(models.Model):
    _inherit = "mrp.unbuild"

    ff_advanced_mode = fields.Boolean(string="Advanced Disassembly")
    ff_disassembly_type = fields.Selection([("full", "Full"), ("partial", "Partial")], default="full")
    ff_recovery_percentage = fields.Float(
        string="Recovered Value Percentage", default=100.0, digits=(16, 4),
        help="One percentage for the whole operation. The remaining percentage is allocated as valuation loss.",
    )
    ff_output_cost_value = fields.Monetary(
        string="Output Cost Value",
        currency_field="company_currency_id",
        default=0.0,
        copy=False,
        help=(
            "Total value to assign to the physically recovered output products. "
            "The remaining source carrying value is posted as the disassembly valuation difference."
        ),
    )
    ff_output_cost_value_manual = fields.Boolean(copy=False, default=False)
    ff_expected_cost_difference = fields.Monetary(
        string="Expected Cost Difference",
        compute="_compute_ff_expected_cost_difference",
        currency_field="company_currency_id",
        readonly=True,
        help=(
            "Estimated valuation difference based on the current source carrying "
            "value and the recovered value percentage."
        ),
    )
    ff_workflow_state = fields.Selection([
        ("draft", "Draft"), ("inspection", "Inspection"), ("ready", "Ready"),
        ("executing", "Executing"), ("done", "Done"), ("reversed", "Reversed"),
        ("cancelled", "Cancelled"),
    ], default="draft", copy=False, index=True)
    ff_line_ids = fields.One2many("ff.disassembly.line", "unbuild_id", copy=False)
    ff_return_picking_id = fields.Many2one("stock.picking", check_company=True)
    ff_residual_product_id = fields.Many2one("product.product", check_company=True)
    ff_cost_policy = fields.Selection([("allocated", "Allocated")], default="allocated", readonly=True)
    ff_available_lot_ids = fields.Many2many(
        "stock.lot",
        string="Available Lots / Serials",
        compute="_compute_ff_available_lot_ids",
        help="Lots or serials with available stock for the selected product and source location.",
    )
    ff_source_carrying_value = fields.Monetary(currency_field="company_currency_id", copy=False, readonly=True, groups="ff_advanced_disassembly.group_ff_disassembly_cost_viewer,ff_advanced_disassembly.group_ff_disassembly_administrator")
    ff_allocated_asset_value = fields.Monetary(currency_field="company_currency_id", copy=False, readonly=True, groups="ff_advanced_disassembly.group_ff_disassembly_cost_viewer,ff_advanced_disassembly.group_ff_disassembly_administrator")
    ff_allocated_loss_value = fields.Monetary(currency_field="company_currency_id", copy=False, readonly=True, groups="ff_advanced_disassembly.group_ff_disassembly_cost_viewer,ff_advanced_disassembly.group_ff_disassembly_administrator")
    ff_actual_output_value = fields.Monetary(currency_field="company_currency_id", copy=False, readonly=True, groups="ff_advanced_disassembly.group_ff_disassembly_cost_viewer,ff_advanced_disassembly.group_ff_disassembly_administrator")
    ff_actual_loss_value = fields.Monetary(currency_field="company_currency_id", copy=False, readonly=True, groups="ff_advanced_disassembly.group_ff_disassembly_cost_viewer,ff_advanced_disassembly.group_ff_disassembly_administrator")
    ff_valuation_difference = fields.Monetary(currency_field="company_currency_id", copy=False, readonly=True, groups="ff_advanced_disassembly.group_ff_disassembly_cost_viewer,ff_advanced_disassembly.group_ff_disassembly_administrator")
    company_currency_id = fields.Many2one(related="company_id.currency_id")
    ff_cost_ids = fields.One2many("ff.disassembly.cost", "unbuild_id", readonly=True, groups="ff_advanced_disassembly.group_ff_disassembly_cost_viewer,ff_advanced_disassembly.group_ff_disassembly_administrator")
    ff_event_ids = fields.One2many("ff.disassembly.event", "unbuild_id", readonly=True)
    ff_execution_key = fields.Char(copy=False, readonly=True, index=True)
    ff_executed_at = fields.Datetime(copy=False, readonly=True)
    ff_executed_by = fields.Many2one("res.users", copy=False, readonly=True)
    ff_residual_lot_id = fields.Many2one("stock.lot", check_company=True)
    ff_residual_destination_id = fields.Many2one("stock.location", check_company=True)
    ff_residual_ids = fields.One2many("ff.disassembly.residual", "unbuild_id", readonly=True)
    ff_reverse_move_ids = fields.Many2many(
        "stock.move", "ff_disassembly_reverse_move_rel", "unbuild_id", "move_id",
        string="Reversal Stock Moves", readonly=True, copy=False,
    )
    ff_reversal_account_move_ids = fields.Many2many(
        "account.move", "ff_disassembly_reversal_account_move_rel", "unbuild_id", "move_id",
        string="Reversal Journal Entries", readonly=True, copy=False,
    )
    ff_reversed_at = fields.Datetime(readonly=True, copy=False)
    ff_reversed_by = fields.Many2one("res.users", readonly=True, copy=False)

    def write(self, vals):
        if "ff_advanced_mode" in vals and not self._ff_has_operational_access():
            raise UserError(_("You are not allowed to enable advanced disassembly."))
        protected_fields = {
            "ff_workflow_state", "ff_execution_key", "ff_executed_at", "ff_executed_by",
            "ff_source_carrying_value", "ff_allocated_asset_value", "ff_allocated_loss_value",
            "ff_actual_output_value", "ff_actual_loss_value", "ff_valuation_difference",
        }
        if protected_fields.intersection(vals) and not self.env.context.get("ff_internal_write"):
            raise UserError(_("Execution and valuation fields can only be changed by the disassembly engine."))
        if any(order.ff_workflow_state in ("done", "reversed") for order in self) and not self.env.context.get("ff_internal_write"):
            protected = set(vals) - {"message_follower_ids", "activity_ids"}
            if protected:
                raise UserError(_("Completed advanced disassembly records are immutable."))
        mark_output_value_manual = "ff_output_cost_value" in vals and not self.env.context.get("ff_internal_write")
        result = super().write(vals)
        if mark_output_value_manual:
            for order in self.filtered(lambda record: not record.ff_output_cost_value_manual):
                if not order.company_id.currency_id.is_zero(
                    order.ff_output_cost_value - order._ff_estimated_source_value()
                ):
                    order.with_context(ff_internal_write=True).write({"ff_output_cost_value_manual": True})
        return result

    @api.depends("product_id", "location_id", "company_id")
    def _compute_ff_available_lot_ids(self):
        """Expose only tracked lots/serials that can be selected at the source."""
        Quant = self.env["stock.quant"]
        for order in self:
            order.ff_available_lot_ids = False
            if not order.product_id or not order.location_id or order.product_id.tracking == "none":
                continue
            quants = Quant.search([
                ("product_id", "=", order.product_id.id),
                ("location_id", "child_of", order.location_id.id),
                ("company_id", "in", [False, order.company_id.id]),
                ("lot_id", "!=", False),
            ])
            precision = self.env["decimal.precision"].precision_get("Product Unit")
            available_lots = quants.filtered(
                lambda quant: float_compare(
                    quant.quantity - quant.reserved_quantity,
                    0.0,
                    precision_digits=precision,
                ) > 0
            ).mapped("lot_id")
            order.ff_available_lot_ids = available_lots

    def action_validate(self):
        advanced = self.filtered("ff_advanced_mode")
        if not advanced:
            return super().action_validate()
        self.ensure_one()
        self._ff_check_operational_access()
        self._ff_validate_operation()
        self.with_context(ff_internal_write=True).write({"ff_workflow_state": "ready"})
        return True

    def action_unbuild(self):
        advanced = self.filtered("ff_advanced_mode")
        if not advanced:
            return super().action_unbuild()
        return advanced.ff_execute_disassembly()

    @api.onchange("ff_advanced_mode", "product_id", "product_qty", "bom_id", "mo_id")
    def _onchange_ff_auto_load_components(self):
        """Show the BoM/MO component snapshot as soon as advanced mode is selected."""
        for order in self:
            if not order.ff_advanced_mode or order.ff_line_ids or not (order.mo_id or order.bom_id):
                continue
            commands = order._ff_component_commands()
            if commands:
                order.ff_line_ids = commands

    @api.onchange("product_id", "product_qty", "uom_id", "company_id")
    def _onchange_ff_output_cost_value_default(self):
        """Show a safe full-value default until the user enters an explicit amount."""
        for order in self:
            if not order.ff_output_cost_value_manual:
                order.ff_output_cost_value = order._ff_estimated_source_value()

    def _ff_estimated_source_value(self):
        self.ensure_one()
        if not self.product_id:
            return 0.0
        quantity = self.product_qty or 0.0
        if self.uom_id and self.product_id.uom_id:
            quantity = self.uom_id._compute_quantity(quantity, self.product_id.uom_id)
        return max(0.0, quantity * self.product_id.with_company(self.company_id).standard_price)

    def _ff_output_value_for_source(self, source_value):
        """Return the explicit output value, with a legacy percentage fallback."""
        self.ensure_one()
        if self.ff_output_cost_value_manual:
            return self.company_id.currency_id.round(max(self.ff_output_cost_value, 0.0))
        # Existing records created before the numeric field was introduced keep
        # their original percentage semantics until a user enters an amount.
        return self.company_id.currency_id.round(
            max(source_value, 0.0) * min(max(self.ff_recovery_percentage, 0.0), 100.0) / 100.0
        )

    @api.constrains("ff_recovery_percentage", "ff_output_cost_value")
    def _check_ff_value_inputs(self):
        for order in self:
            if not 0.0 <= order.ff_recovery_percentage <= 100.0:
                raise ValidationError(_("Recovered value percentage must be between 0 and 100."))
            if order.ff_output_cost_value < 0.0:
                raise ValidationError(_("Output cost value cannot be negative."))
            source_value = order.ff_source_carrying_value or order._ff_estimated_source_value()
            if source_value and order.ff_output_cost_value_manual and order.ff_output_cost_value > source_value:
                raise ValidationError(_("Output cost value cannot exceed the source carrying value."))

    @api.depends(
        "product_id", "product_qty", "uom_id", "ff_recovery_percentage",
        "ff_output_cost_value", "ff_output_cost_value_manual",
        "ff_source_carrying_value", "ff_workflow_state",
    )
    def _compute_ff_expected_cost_difference(self):
        for order in self:
            # Once execution has captured the source carrying value, keep the
            # preview tied to that accounting value. Draft orders use the
            # current product standard cost as a transparent estimate.
            source_value = order.ff_source_carrying_value
            if not source_value and order.ff_workflow_state != "done" and order.product_id:
                quantity = order.product_qty
                if order.uom_id and order.product_id.uom_id:
                    quantity = order.uom_id._compute_quantity(quantity, order.product_id.uom_id)
                source_value = quantity * order.product_id.with_company(order.company_id).standard_price
            output_value = order._ff_output_value_for_source(source_value)
            order.ff_expected_cost_difference = order.company_id.currency_id.round(
                max(0.0, source_value - output_value)
            )

    def _ff_apply_output_cost_value(self, source_value):
        self.ensure_one()
        if self.company_id.currency_id.is_zero(source_value):
            raise UserError(_("The source finished-product move has no carrying value; allocation cannot proceed."))
        output_value = self._ff_output_value_for_source(source_value)
        if output_value > source_value and not self.company_id.currency_id.is_zero(output_value - source_value):
            raise ValidationError(_("Output cost value cannot exceed the source carrying value."))
        percentage = min(max(output_value / source_value, 0.0), 1.0)
        results = self.ff_line_ids.mapped("result_ids")
        if results:
            for result in results.filtered(lambda r: r.condition in ("good", "repairable")):
                result.with_context(ff_internal_write=True).write({
                    "recovery_factor": percentage,
                    "condition": "repairable" if percentage < 1.0 else "good",
                })

    def _ff_apply_reference_weights(self):
        """Derive technical allocation weights; users should not enter them."""
        self.ensure_one()
        for line in self.ff_line_ids:
            for result in line.result_ids:
                product_cost = result.product_id.with_company(self.company_id).standard_price
                fallback_cost = line.reference_unit_cost or product_cost or 1.0
                weight = result.quantity * (product_cost or fallback_cost)
                result.with_context(ff_internal_write=True).write({
                    "reference_weight": max(weight, 0.000001),
                })

    def ff_load_components(self):
        for order in self:
            order.ensure_one()
            order._ff_check_operational_access()
            if not order.ff_advanced_mode or order.state == "done" or order.ff_workflow_state not in ("draft", "inspection"):
                raise UserError(_("Component loading is only available on a draft advanced disassembly."))
            order.ff_line_ids.unlink()
            components = order._ff_component_items()
            if not components:
                raise UserError(_("Select a completed manufacturing order or a valid BoM before loading components."))
            for item in components.values():
                product = item["product"]
                unit_cost = product.with_company(order.company_id).standard_price
                line = self.env["ff.disassembly.line"].create({
                    "unbuild_id": order.id,
                    "product_id": product.id,
                    "uom_id": product.uom_id.id,
                    "expected_qty": item["qty"],
                    "source_type": "mo" if order.mo_id else "bom",
                    "source_move_id": item.get("move") and item["move"].id,
                    "bom_line_id": item.get("bom_line") and item["bom_line"].id,
                    "reference_unit_cost": unit_cost,
                    "reference_cost_source": "Company product cost snapshot",
                    "output_product_id": product.id,
                    "output_quantity": item["qty"],
                    "output_destination_location_id": order.location_dest_id.id,
                })
                self.env["ff.disassembly.result"].create({
                    "line_id": line.id,
                    "product_id": product.id,
                    "quantity": item["qty"],
                    "condition": "good",
                    "destination_location_id": order.location_dest_id.id,
                    "reference_weight": item["qty"] * unit_cost,
                })
            order.with_context(ff_internal_write=True).write({"ff_workflow_state": "inspection"})
            order._ff_log("inspection", _("Component snapshot loaded from %s.", order.mo_id.display_name if order.mo_id else order.bom_id.display_name))
        return True

    def _ff_component_items(self):
        self.ensure_one()
        components = {}
        if self.mo_id:
            mo_qty = self.mo_id.uom_id._compute_quantity(self.mo_id.qty_produced, self.uom_id)
            factor = self.product_qty / mo_qty if mo_qty else 0
            for move in self.mo_id.move_raw_ids.filtered(lambda m: m.state == "done"):
                qty = move.uom_id._compute_quantity(move.quantity, move.product_id.uom_id) * factor
                key = (move.product_id.id, move.product_id.uom_id.id)
                entry = components.setdefault(key, {"product": move.product_id, "qty": 0.0, "move": move})
                entry["qty"] += qty
        elif self.bom_id and self.product_id:
            factor = self.uom_id._compute_quantity(self.product_qty, self.bom_id.uom_id) / self.bom_id.product_qty
            _bom, exploded = self.bom_id.explode(self.product_id, factor, picking_type=self.bom_id.picking_type_id)
            for bom_line, values in exploded:
                product = bom_line.product_id
                qty = bom_line.uom_id._compute_quantity(values["qty"], product.uom_id)
                key = (product.id, product.uom_id.id)
                entry = components.setdefault(key, {"product": product, "qty": 0.0, "bom_line": bom_line})
                entry["qty"] += qty
        return components

    def _ff_component_commands(self):
        self.ensure_one()
        commands = []
        for item in self._ff_component_items().values():
            product = item["product"]
            qty = item["qty"]
            commands.append(Command.create({
                "product_id": product.id,
                "uom_id": product.uom_id.id,
                "expected_qty": qty,
                "source_type": "mo" if item.get("move") else "bom",
                "source_move_id": item.get("move") and item["move"].id,
                "bom_line_id": item.get("bom_line") and item["bom_line"].id,
                "reference_unit_cost": product.with_company(self.company_id).standard_price,
                "reference_cost_source": "Company product cost snapshot",
                "result_ids": [Command.create({
                    "product_id": product.id,
                    "quantity": qty,
                    "condition": "good",
                    "destination_location_id": self.location_dest_id.id,
                    "reference_weight": qty * product.with_company(self.company_id).standard_price,
                })],
            }))
        return commands

    def _ff_validate_operation(self, allow_executing=False):
        self.ensure_one()
        self._ff_apply_reference_weights()
        if self.state == "done" or self.ff_workflow_state in ("done", "reversed") or (self.ff_workflow_state == "executing" and not allow_executing):
            raise UserError(_("This disassembly is already completed or executing."))
        if self.ff_disassembly_type == "partial" and not self.company_id.ff_partial_disassembly_enabled:
            raise UserError(_("Partial disassembly is disabled for this company."))
        if not self.ff_line_ids:
            raise ValidationError(_("Load or add component lines before validating."))
        precision = self.env["decimal.precision"].precision_get("Product Unit")
        currency = self.company_id.currency_id
        for line in self.ff_line_ids:
            result_qty = sum(line.result_ids.mapped("quantity"))
            if float_compare(result_qty, line.expected_qty, precision_digits=precision) != 0:
                raise ValidationError(_("Component %(product)s must be fully accounted for by result quantities.", product=line.product_id.display_name))
            if self.ff_disassembly_type == "full" and line.qty_retained:
                raise ValidationError(_("Retained results are only valid for partial disassembly."))
            for result in line.result_ids:
                if result.condition in ("good", "repairable", "scrap") and not result.destination_location_id:
                    raise ValidationError(_("Select a destination for each physically recovered result."))
                if result.condition in ("good", "repairable", "scrap") and result.product_id.tracking in ("lot", "serial") and not result.lot_id:
                    raise ValidationError(_("A lot or serial is required for tracked recovered products."))
                if result.reference_weight <= 0 and result.quantity:
                    raise ValidationError(_("Every result requires an explicit positive reference allocation weight."))
                if result.product_id.tracking == "serial" and result.quantity != 1:
                    raise ValidationError(_("Each recovered serial must be entered as an individual result quantity of one."))
                if result.condition in ("good", "repairable", "scrap") and result.destination_location_id:
                    if result.destination_location_id.usage != "internal" or result.destination_location_id.company_id not in (False, self.company_id):
                        raise ValidationError(_("Recovered result destinations must be company-compatible internal locations."))
            if not currency.is_zero(line.reference_unit_cost) and not line.reference_cost_source:
                raise ValidationError(_("Document the source of each reference unit cost."))
        # A partial order can now be completed through the same component/result
        # table as a full order. A residual assembly is only required when the
        # user explicitly marks a component result as retained.
        has_retained_result = any(
            result.condition == "retained"
            for line in self.ff_line_ids
            for result in line.result_ids
        )
        if self.ff_disassembly_type == "partial" and has_retained_result:
            if not self.ff_residual_product_id or not self.ff_residual_destination_id:
                raise ValidationError(_("Select a residual assembly product and destination."))
            if self.ff_residual_product_id == self.product_id:
                raise ValidationError(_("The residual assembly must use a distinct product SKU."))
            if self.ff_residual_destination_id.usage != "internal" or self.ff_residual_destination_id.company_id not in (False, self.company_id):
                raise ValidationError(_("Residual destination must be a company-compatible internal location."))
            if self.env["ff.disassembly.line"]._uom_root(self.ff_residual_product_id.uom_id) != self.env["ff.disassembly.line"]._uom_root(self.uom_id):
                raise ValidationError(_("Residual product unit must be compatible with the original product unit."))
            if self.ff_residual_product_id.tracking in ("lot", "serial") and not self.ff_residual_lot_id:
                raise ValidationError(_("A residual lot or serial is required for the selected tracked residual product."))
        if self.product_id.tracking in ("lot", "serial") and not self.lot_ids:
            raise ValidationError(_("Select source lot or serial numbers before validating."))
        if self.product_id.tracking == "serial" and (self.product_qty != 1 or len(self.lot_ids) != 1):
            raise ValidationError(_("Serial-tracked finished products must be disassembled one serial per operation."))
        available = self.env["stock.quant"]._get_available_quantity(self.product_id, self.location_id, self.lot_ids[:1], strict=bool(self.lot_ids)) if len(self.lot_ids) <= 1 else sum(
            self.env["stock.quant"]._get_available_quantity(self.product_id, self.location_id, lot, strict=True) for lot in self.lot_ids
        )
        if self.location_id.usage != "internal" or self.location_id.company_id not in (False, self.company_id):
            raise ValidationError(_("The source must be a company-compatible internal stock location."))
        wanted = self.uom_id._compute_quantity(self.product_qty, self.product_id.uom_id)
        if self.ff_return_picking_id:
            picking = self.ff_return_picking_id
            if picking.state != "done" or picking.company_id != self.company_id:
                raise ValidationError(_("The linked return picking must be completed and belong to the same company."))
            returned_qty = sum(picking.move_line_ids.filtered(
                lambda ml: ml.product_id == self.product_id and ml.location_dest_id == self.location_id
            ).mapped("quantity_product_uom"))
            if returned_qty < wanted:
                raise ValidationError(_("The linked return picking does not contain the requested quantity in the selected source location."))
        if float_compare(available, wanted, precision_digits=precision) < 0:
            raise UserError(_("Insufficient finished-product quantity in the selected source location."))
        production_location = self.product_id.with_company(self.company_id).property_stock_production
        real_time_products = self.ff_line_ids.mapped("product_id") | self.product_id
        if self.ff_disassembly_type == "partial":
            real_time_products |= self.ff_residual_product_id
        if any(product.with_company(self.company_id).valuation == "real_time" for product in real_time_products):
            # Odoo's stock-accounting engine needs an account on the production
            # location for moves crossing that location. A company-wide account
            # may override the source category; otherwise standard category
            # Stock Variation Account behaviour is preserved.
            product_accounts = self.product_id.with_company(self.company_id)._get_product_accounts()
            source_account = product_accounts.get("stock_valuation")
            production_account = self.company_id._ff_get_disassembly_variance_account(self.product_id)
            if not production_account:
                raise ValidationError(_(
                    "Configure the Stock Valuation Account and its Stock Variation Account "
                    "on the source product category before using real-time disassembly valuation."
                ))
            if production_account == source_account:
                raise ValidationError(_(
                    "The source product category must use a Stock Variation Account "
                    "different from its Stock Valuation Account."
                ))
            if production_location.valuation_account_id != production_account:
                production_location.sudo().write({"valuation_account_id": production_account.id})
            if any(result.condition == "scrap" for result in self.ff_line_ids.mapped("result_ids")):
                scrap_location = self.company_id.scrap_location_id
                if not scrap_location or not scrap_location.valuation_account_id:
                    raise ValidationError(_("Configure a valuation account on the company scrap location before processing recovered scrap."))
        return True

    def ff_execute_disassembly(self):
        self.ensure_one()
        self._ff_check_operational_access()
        if not self.ff_advanced_mode:
            raise UserError(_("Enable Advanced Disassembly to use this action."))
        self._ff_claim_execution()
        self._ff_validate_operation(allow_executing=True)
        # Odoo 20 records move-level manual values as product.value records before valuation.
        # Actual stock/accounting reconciliation remains a hard postcondition below.
        source_move = self._ff_consume_source()
        source_value = abs(source_move.value)
        self._ff_apply_output_cost_value(source_value)
        allocation = self.env["ff.disassembly.allocation"]._allocate(self, source_value)
        output_moves = self._ff_create_outputs(allocation)
        residual_move = self._ff_create_residual(allocation)
        scrap_moves = self._ff_create_scrap_losses(allocation)
        actual_output = sum(abs(move.value) for move in output_moves) + (abs(residual_move.value) if residual_move else 0.0)
        asset_value = sum(amount for _result, amount in allocation["assets"].values()) + allocation["residual"]
        difference = self.company_id.currency_id.round(actual_output - asset_value)
        if not self.company_id.currency_id.is_zero(difference):
            raise UserError(_("Actual output stock valuation differs from planned allocation by %s.", difference))
        loss = self.company_id.currency_id.round(source_value - actual_output)
        if loss < 0 and not self.company_id.currency_id.is_zero(loss):
            raise UserError(_("Allocated output value exceeds source carrying value."))
        actual_scrap_loss = sum(abs(move.value) for move in scrap_moves.filtered("is_scrap"))
        planned_scrap_loss = sum(amount for _result, amount in allocation["scrap_loss"].values())
        if not self.company_id.currency_id.is_zero(actual_scrap_loss - planned_scrap_loss):
            raise UserError(_("The actual native scrap valuation differs from the allocated scrap loss by %s.", actual_scrap_loss - planned_scrap_loss))
        all_execution_moves = source_move | output_moves | residual_move | scrap_moves
        # Native stock valuation still creates valuation layers per move, but
        # one account move is posted for the complete disassembly.
        all_execution_moves.with_context(
            ff_consolidate_disassembly_accounting=True,
        )._create_account_move()
        self._ff_check_accounting_reconciliation(all_execution_moves, allocation["loss"])
        self.sudo().with_context(ff_internal_write=True).write({
            "ff_source_carrying_value": source_value,
            "ff_allocated_asset_value": asset_value,
            "ff_allocated_loss_value": loss,
            "ff_actual_output_value": actual_output,
            "ff_actual_loss_value": loss,
            "ff_valuation_difference": difference,
        })
        self.with_context(ff_internal_write=True).write({
            "ff_executed_at": fields.Datetime.now(),
            "ff_executed_by": self.env.user.id,
            "ff_workflow_state": "done",
            "state": "done",
        })
        for result, amount in allocation["assets"].values():
            move = result.stock_move_ids.filtered(lambda m: m.state == "done")[:1]
            self.env["ff.disassembly.cost"].sudo().create({
                "unbuild_id": self.id, "source_move_id": source_move.id, "source_carrying_value": source_value,
                "reference_weight_total": allocation["total_weight"], "result_id": result.id,
                "allocation_weight": result.reference_weight * (result.recovery_factor if result.condition == "repairable" else 1.0),
                "allocation_ratio": amount / source_value if source_value else 0.0,
                "allocated_amount": amount, "actual_valuation_amount": abs(move.value) if move else 0.0,
                "variance": (abs(move.value) if move else 0.0) - amount,
                "loss_amount": allocation["loss_details"].get(id(result), [False, 0.0])[1],
                "valuation_reference": move.reference if move else self.name,
            })
        if allocation["residual"]:
            move = self.ff_residual_ids.stock_move_id
            self.env["ff.disassembly.cost"].sudo().create({
                "unbuild_id": self.id, "source_move_id": source_move.id, "source_carrying_value": source_value,
                "reference_weight_total": allocation["total_weight"], "allocation_weight": allocation["residual"],
                "allocation_ratio": allocation["residual"] / source_value if source_value else 0.0,
                "allocated_amount": allocation["residual"], "actual_valuation_amount": abs(move.value),
                "variance": abs(move.value) - allocation["residual"], "valuation_reference": move.reference,
            })
        for result, amount in allocation["loss_details"].values():
            if id(result) in allocation["assets"]:
                continue
            scrap_move = result.stock_move_ids.filtered("is_scrap")[:1]
            actual_loss_move_value = abs(scrap_move.value) if scrap_move else 0.0
            self.env["ff.disassembly.cost"].sudo().create({
                "unbuild_id": self.id, "source_move_id": source_move.id, "source_carrying_value": source_value,
                "reference_weight_total": allocation["total_weight"], "result_id": result.id,
                "allocation_weight": result.reference_weight * (1 - result.recovery_factor if result.condition == "repairable" else 1.0),
                "allocation_ratio": amount / source_value if source_value else 0.0,
                "allocated_amount": 0.0, "actual_valuation_amount": actual_loss_move_value,
                "variance": actual_loss_move_value - amount if scrap_move else 0.0,
                "loss_amount": amount,
                "valuation_reference": scrap_move.reference if scrap_move else source_move.reference,
            })
        self._ff_log("executed", _("Executed. Source value %(source)s; output value %(output)s; allocated loss %(loss)s.", source=source_value, output=actual_output, loss=loss))
        return True

    def action_reverse(self):
        """Create stock and accounting reversals without editing posted records."""
        self.ensure_one()
        self._ff_check_operational_access()
        if not self._ff_has_manager_access():
            raise UserError(_("Only disassembly administrators can reverse completed operations."))
        if self.state != "done" or self.ff_workflow_state != "done":
            raise UserError(_("Only completed advanced disassembly operations can be reversed."))
        if self.ff_reverse_move_ids:
            raise UserError(_("This disassembly already has a reversal."))

        original_moves = (
            self.consume_line_ids
            | self.produce_line_ids
            | self.ff_line_ids.mapped("result_ids.stock_move_ids")
            | self.ff_residual_ids.mapped("stock_move_id")
        ).filtered(lambda move: move.state == "done")
        if not original_moves:
            raise UserError(_("No completed stock moves were found for this disassembly."))

        reversal_moves = self.env["stock.move"]
        # Reverse the latest moves first: outputs/scrap are returned before the
        # original finished product is put back into the source location.
        for original in original_moves.sorted(key=lambda move: move.id, reverse=True):
            quantity = original.quantity
            if original.uom_id.is_zero(quantity):
                continue
            reverse = self.env["stock.move"].create({
                "origin": _("Reversal of %s", self.name),
                "reference": _("Reversal of %s", self.name),
                "product_id": original.product_id.id,
                "product_uom_qty": quantity,
                "uom_id": original.uom_id.id,
                "location_id": original.location_dest_id.id,
                "location_dest_id": original.location_id.id,
                "company_id": original.company_id.id,
                "origin_returned_move_id": original.id,
            })
            reverse._action_confirm()
            reverse.move_line_ids.unlink()
            source_lines = original.move_line_ids.filtered(lambda line: line.quantity)
            if source_lines:
                for source_line in source_lines:
                    self.env["stock.move.line"].create({
                        "move_id": reverse.id,
                        "product_id": original.product_id.id,
                        "uom_id": source_line.uom_id.id,
                        "quantity": source_line.quantity,
                        "lot_id": source_line.lot_id.id,
                        "owner_id": source_line.owner_id.id,
                        "location_id": original.location_dest_id.id,
                        "location_dest_id": original.location_id.id,
                    })
            else:
                self.env["stock.move.line"].create({
                    "move_id": reverse.id,
                    "product_id": original.product_id.id,
                    "uom_id": original.uom_id.id,
                    "quantity": quantity,
                    "location_id": original.location_dest_id.id,
                    "location_dest_id": original.location_id.id,
                })
            reverse.picked = True
            reverse.with_context(ff_defer_disassembly_accounting=True)._action_done()
            reversal_moves |= reverse

        # Native stock valuation still creates valuation layers per move, but
        # one account move is posted for the complete reversal.
        reversal_moves.with_context(
            ff_consolidate_disassembly_accounting=True,
        )._create_account_move()
        reversal_account_moves = reversal_moves.mapped("account_move_id").filtered(lambda move: move.state == "posted")
        original_account_moves = original_moves.mapped("account_move_id").filtered(lambda move: move.state == "posted")
        if original_account_moves and not reversal_account_moves:
            raise UserError(_("Odoo did not create the reversing accounting entries for this disassembly."))

        self.with_context(ff_internal_write=True).write({
            "ff_workflow_state": "reversed",
            "ff_reverse_move_ids": [Command.set(reversal_moves.ids)],
            "ff_reversal_account_move_ids": [Command.set(reversal_account_moves.ids)],
            "ff_reversed_at": fields.Datetime.now(),
            "ff_reversed_by": self.env.user.id,
        })
        self._ff_log("reversed", _("Reversed. Stock quantities and native valuation entries were reversed."))
        return True

    def _ff_claim_execution(self):
        """Atomically claim an advanced order before any stock side effect."""
        self.ensure_one()
        self.env.cr.execute("SELECT id FROM mrp_unbuild WHERE id = %s FOR UPDATE", [self.id])
        self.invalidate_recordset()
        if self.ff_execution_key or self.state == "done":
            raise UserError(_("This disassembly already has an execution record."))
        self.with_context(ff_internal_write=True).write({
            "ff_workflow_state": "executing",
            "ff_execution_key": str(uuid.uuid4()),
        })
        return True

    def _ff_has_operational_access(self):
        """Use the explicit Advanced Disassembly operator role."""
        return self.env.user.has_group("ff_advanced_disassembly.group_ff_disassembly_user")

    def _ff_has_manager_access(self):
        """Reverse/configure actions require the explicit module administrator role."""
        return self.env.user.has_group("ff_advanced_disassembly.group_ff_disassembly_administrator")

    def _ff_check_operational_access(self):
        if not self._ff_has_operational_access():
            raise UserError(_("You are not allowed to operate advanced disassembly orders."))

    def _ff_consume_source(self):
        self.ensure_one()
        production_location = self.product_id.with_company(self.company_id).property_stock_production
        move = self.env["stock.move"].create({
            "origin": self.name,
            "reference": self.name,
            "product_id": self.product_id.id,
            "product_uom_qty": self.uom_id._compute_quantity(self.product_qty, self.product_id.uom_id),
            "uom_id": self.product_id.uom_id.id,
            "location_id": self.location_id.id,
            "location_dest_id": production_location.id,
            "company_id": self.company_id.id,
            "consume_unbuild_id": self.id,
            "origin_returned_move_id": self.mo_id.move_finished_ids.filtered(lambda m: m.product_id == self.product_id)[:1].id if self.mo_id else False,
        })
        move._action_confirm()
        lots = self.lot_ids
        if lots:
            move.move_line_ids.unlink()
        if self.product_id.tracking == "serial" and len(lots) != int(self.product_qty):
            raise ValidationError(_("For serial-tracked products, select exactly one serial per unit."))
        remaining = move.product_uom_qty
        if lots:
            for lot in lots:
                requested = 1.0 if self.product_id.tracking == "serial" else remaining
                taken = move._update_reserved_quantity(requested, self.location_id, lot_id=lot, strict=True)
                remaining -= taken
                if self.product_id.uom_id.is_zero(remaining):
                    break
            if not self.product_id.uom_id.is_zero(remaining):
                raise ValidationError(_("Selected serial/lot quantities do not cover the requested source quantity."))
        else:
            move._action_assign()
            reserved = sum(move.move_line_ids.mapped("quantity_product_uom"))
            precision = self.env["decimal.precision"].precision_get("Product Unit")
            if float_compare(reserved, move.product_uom_qty, precision_digits=precision) < 0:
                raise UserError(_("Insufficient finished-product quantity in the selected source location."))
        move.picked = True
        move.with_context(ff_defer_disassembly_accounting=True)._action_done()
        return move

    def _ff_create_scrap_losses(self, allocation):
        self.ensure_one()
        moves = self.env["stock.move"]
        if not allocation["scrap_loss"]:
            return moves
        production_location = self.product_id.with_company(self.company_id).property_stock_production
        scrap_location = self.company_id.scrap_location_id
        for result, value in allocation["scrap_loss"].values():
            product = result.product_id
            quantity = result.line_id.uom_id._compute_quantity(result.quantity, product.uom_id)
            receipt = self.env["stock.move"].create({
                "origin": self.name, "reference": self.name, "product_id": product.id, "product_uom_qty": quantity,
                "uom_id": product.uom_id.id, "location_id": production_location.id,
                "location_dest_id": result.destination_location_id.id, "company_id": self.company_id.id,
            })
            self.env["product.value"].sudo().create({
                "move_id": receipt.id, "value": value,
                "description": _("Allocated recovered-scrap value from %s", self.name),
                "user_id": self.env.user.id,
            })
            receipt._action_confirm()
            receipt.move_line_ids.unlink()
            self.env["stock.move.line"].create({
                "move_id": receipt.id, "product_id": product.id, "uom_id": product.uom_id.id,
                "quantity": quantity, "lot_id": result.lot_id.id,
                "location_id": production_location.id, "location_dest_id": result.destination_location_id.id,
            })
            receipt.picked = True
            receipt.with_context(ff_defer_disassembly_accounting=True)._action_done()
            scrap_move = self.env["stock.move"].create({
                "origin": self.name, "reference": self.name, "product_id": product.id, "product_uom_qty": quantity,
                "uom_id": product.uom_id.id, "location_id": result.destination_location_id.id,
                "location_dest_id": scrap_location.id, "company_id": self.company_id.id,
            })
            scrap_move._action_confirm()
            scrap_move.move_line_ids.unlink()
            self.env["stock.move.line"].create({
                "move_id": scrap_move.id, "product_id": product.id, "uom_id": product.uom_id.id,
                "quantity": quantity, "lot_id": result.lot_id.id,
                "location_id": result.destination_location_id.id, "location_dest_id": scrap_location.id,
            })
            scrap_move.picked = True
            scrap_move.with_context(ff_defer_disassembly_accounting=True)._action_scrap()
            result.with_context(ff_internal_write=True).write({"stock_move_ids": [Command.link(receipt.id), Command.link(scrap_move.id)]})
            moves |= receipt | scrap_move
        return moves

    def _ff_check_accounting_reconciliation(self, moves, allocated_loss):
        self.ensure_one()
        currency = self.company_id.currency_id
        real_time_moves = moves.filtered(lambda move: move.product_id.with_company(self.company_id).valuation == "real_time")
        if not real_time_moves:
            return True
        missing_entries = real_time_moves.filtered(lambda move: move._should_create_account_move() and (not move.account_move_id or move.account_move_id.state != "posted"))
        if missing_entries:
            raise UserError(_("Odoo did not create posted stock-accounting entries for every valued disassembly movement."))
        journal_entries = real_time_moves.account_move_id
        production_account = self.product_id.with_company(self.company_id).property_stock_production.valuation_account_id
        recognized_loss = sum(journal_entries.line_ids.filtered(lambda line: line.account_id == production_account).mapped("balance"))
        recognized_loss = currency.round(recognized_loss)
        if not currency.is_zero(recognized_loss - allocated_loss):
            raise UserError(_("Native stock-accounting loss differs from the planned allocation by %s.", recognized_loss - allocated_loss))
        return True

    def _ff_create_outputs(self, allocation):
        self.ensure_one()
        production_location = self.product_id.with_company(self.company_id).property_stock_production
        moves = self.env["stock.move"]
        for result, value in allocation["assets"].values():
            product = result.product_id
            destination = result.destination_location_id
            move = self.env["stock.move"].create({
                "origin": self.name, "reference": self.name, "product_id": product.id,
                "product_uom_qty": result.line_id.uom_id._compute_quantity(result.quantity, product.uom_id),
                "uom_id": product.uom_id.id, "location_id": production_location.id,
                "location_dest_id": destination.id, "company_id": self.company_id.id,
                "unbuild_id": self.id, "origin_returned_move_id": result.line_id.source_move_id.id,
            })
            self.env["product.value"].sudo().create({
                "move_id": move.id, "value": value,
                "description": _("Allocated disassembly value from %s", self.name),
                "user_id": self.env.user.id,
            })
            move._action_confirm()
            move.move_line_ids.unlink()
            self.env["stock.move.line"].create({"move_id": move.id, "product_id": product.id,
                "uom_id": product.uom_id.id, "quantity": move.product_uom_qty,
                "lot_id": result.lot_id.id, "location_id": production_location.id, "location_dest_id": destination.id})
            move.picked = True
            move.with_context(ff_defer_disassembly_accounting=True)._action_done()
            result.with_context(ff_internal_write=True).write({
                "stock_move_ids": [Command.link(move.id)], "allocated_value": value,
            })
            moves |= move
            if result.condition == "scrap":
                scrap_move = self.env["stock.move"].create({
                    "origin": self.name, "reference": self.name, "product_id": product.id,
                    "product_uom_qty": move.quantity, "uom_id": product.uom_id.id,
                    "location_id": destination.id, "location_dest_id": self.company_id.scrap_location_id.id,
                    "company_id": self.company_id.id,
                })
                self.env["stock.move.line"].create({"move_id": scrap_move.id, "product_id": product.id,
                    "uom_id": product.uom_id.id, "quantity": move.quantity, "lot_id": result.lot_id.id,
                    "location_id": destination.id, "location_dest_id": self.company_id.scrap_location_id.id})
                scrap_move.with_context(ff_defer_disassembly_accounting=True)._action_scrap()
                result.with_context(ff_internal_write=True).write({"stock_move_ids": [Command.link(scrap_move.id)]})
        return moves

    def _ff_create_residual(self, allocation):
        self.ensure_one()
        if self.company_id.currency_id.is_zero(allocation["residual"]):
            return self.env["stock.move"]
        product = self.ff_residual_product_id
        production_location = self.product_id.with_company(self.company_id).property_stock_production
        quantity = self.uom_id._compute_quantity(self.product_qty, product.uom_id)
        move = self.env["stock.move"].create({
            "origin": self.name, "reference": self.name, "product_id": product.id,
            "product_uom_qty": quantity, "uom_id": product.uom_id.id,
            "location_id": production_location.id, "location_dest_id": self.ff_residual_destination_id.id,
            "company_id": self.company_id.id, "unbuild_id": self.id,
        })
        self.env["product.value"].sudo().create({
            "move_id": move.id, "value": allocation["residual"],
            "description": _("Residual assembly allocation from %s", self.name),
            "user_id": self.env.user.id,
        })
        move._action_confirm()
        move.move_line_ids.unlink()
        self.env["stock.move.line"].create({"move_id": move.id, "product_id": product.id,
            "uom_id": product.uom_id.id, "quantity": move.product_uom_qty,
            "lot_id": self.ff_residual_lot_id.id, "location_id": production_location.id,
            "location_dest_id": self.ff_residual_destination_id.id})
        move.picked = True
        move.with_context(ff_defer_disassembly_accounting=True)._action_done()
        retained = [{"product": result.product_id.display_name, "quantity": result.quantity,
                     "uom": result.line_id.uom_id.name, "lot": result.lot_id.name or False}
                    for line in self.ff_line_ids for result in line.result_ids if result.condition == "retained"]
        self.env["ff.disassembly.residual"].sudo().create({
            "unbuild_id": self.id, "original_lot_id": self.lot_ids[:1].id,
            "residual_product_id": product.id, "residual_lot_id": self.ff_residual_lot_id.id,
            "quantity": quantity, "retained_components_snapshot": retained,
            "allocated_value": allocation["residual"], "destination_location_id": self.ff_residual_destination_id.id,
            "stock_move_id": move.id,
        })
        return move

    def _ff_log(self, event_type, description):
        self.env["ff.disassembly.event"].create({"unbuild_id": self.id, "event_type": event_type, "description": description})

    @api.model_create_multi
    def create(self, vals_list):
        vals_list = [dict(vals) for vals in vals_list]
        records = super().create(vals_list)
        if not self.env.context.get("ff_internal_write"):
            for record, vals in zip(records, vals_list):
                if "ff_output_cost_value" in vals and not record.ff_output_cost_value_manual:
                    if not record.company_id.currency_id.is_zero(
                        record.ff_output_cost_value - record._ff_estimated_source_value()
                    ):
                        record.with_context(ff_internal_write=True).write({"ff_output_cost_value_manual": True})
        for record in records.filtered("ff_advanced_mode"):
            record._ff_log("created", _("Advanced disassembly order created."))
        return records

