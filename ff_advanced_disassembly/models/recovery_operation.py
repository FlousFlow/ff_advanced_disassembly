from odoo import Command, _, api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.tools import float_compare


class RecoveryOperation(models.Model):
    _name = "ff.recovery.operation"
    _description = "Recovery and Recycling Operation"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "id desc"

    name = fields.Char(default=lambda self: self.env._("New"), copy=False, readonly=True)
    operation_type = fields.Selection(
        [("recycling", "Recycling"), ("hybrid", "Disassembly and Recycling")],
        required=True,
        default="recycling",
        tracking=True,
    )
    recipe_id = fields.Many2one(
        "ff.recovery.recipe", string="Optional Recovery Recipe", check_company=True,
        domain="[('company_id', '=', company_id), ('active', '=', True)]",
    )
    company_id = fields.Many2one(
        "res.company", required=True, default=lambda self: self.env.company, index=True
    )
    source_location_id = fields.Many2one(
        "stock.location",
        required=True,
        check_company=True,
        domain="[('usage', '=', 'internal')]",
        default=lambda self: self._default_stock_location(),
    )
    processing_location_id = fields.Many2one(
        "stock.location",
        required=True,
        check_company=True,
        domain="[('usage', 'in', ['internal', 'production'])]",
        compute="_compute_processing_location_id",
        store=True,
        readonly=False,
    )
    source_line_ids = fields.One2many("ff.recovery.input", "operation_id")
    output_line_ids = fields.One2many("ff.recovery.output", "operation_id")
    state = fields.Selection(
        [("draft", "Draft"), ("ready", "Ready"), ("executing", "Executing"),
         ("done", "Done"), ("reversed", "Reversed"), ("cancelled", "Cancelled")],
        default="draft", tracking=True, index=True,
    )
    recoverable_value_mode = fields.Selection(
        [("percentage", "Percentage of carrying value"), ("amount", "Target amount")],
        default="percentage", required=True,
    )
    recoverable_value_percentage = fields.Float(default=100.0, digits=(16, 4))
    recoverable_target_amount = fields.Monetary(currency_field="currency_id")
    eligible_recycling_costs = fields.Monetary(currency_field="currency_id")
    loss_account_id = fields.Many2one(
        "account.account", string="Loss / Expense Account", check_company=True,
        domain="[('company_ids', 'parent_of', company_id)]",
    )
    loss_recognition = fields.Selection(
        [("deferred", "Deferred for accounting review"), ("recognize", "Recognize documented loss")],
        default="deferred", required=True,
    )
    loss_evidence = fields.Text(help="Required evidence when a loss is explicitly recognized.")
    input_carrying_value = fields.Monetary(currency_field="currency_id", readonly=True, copy=False)
    recoverable_value = fields.Monetary(currency_field="currency_id", readonly=True, copy=False)
    allocated_output_value = fields.Monetary(currency_field="currency_id", readonly=True, copy=False)
    normal_loss_value = fields.Monetary(currency_field="currency_id", readonly=True, copy=False)
    abnormal_loss_value = fields.Monetary(currency_field="currency_id", readonly=True, copy=False)
    actual_output_value = fields.Monetary(currency_field="currency_id", readonly=True, copy=False)
    valuation_difference = fields.Monetary(currency_field="currency_id", readonly=True, copy=False)
    currency_id = fields.Many2one(related="company_id.currency_id")
    execution_key = fields.Char(copy=False, readonly=True, index=True)
    executed_at = fields.Datetime(copy=False, readonly=True)
    executed_by = fields.Many2one("res.users", copy=False, readonly=True)
    source_move_ids = fields.Many2many(
        "stock.move", "ff_recovery_operation_source_move_rel", "operation_id", "move_id",
        readonly=True, copy=False,
    )
    output_move_ids = fields.Many2many(
        "stock.move", "ff_recovery_operation_output_move_rel", "operation_id", "move_id",
        readonly=True, copy=False,
    )
    account_move_id = fields.Many2one("account.move", readonly=True, copy=False)
    reversal_account_move_id = fields.Many2one("account.move", readonly=True, copy=False)
    reverse_move_ids = fields.Many2many(
        "stock.move", "ff_recovery_operation_reverse_move_rel", "operation_id", "move_id",
        readonly=True, copy=False,
    )
    reversed_at = fields.Datetime(readonly=True, copy=False)
    reversed_by = fields.Many2one("res.users", readonly=True, copy=False)
    notes = fields.Text()

    @api.depends("company_id")
    def _compute_processing_location_id(self):
        for operation in self:
            if not operation.processing_location_id or operation.processing_location_id.company_id not in (False, operation.company_id):
                operation.processing_location_id = operation._default_processing_location(operation.company_id)

    @api.model
    def _default_stock_location(self, company=None):
        """Return the company's warehouse stock location without relying on a non-standard company field."""
        company = company or self.env.company
        warehouse = self.env["stock.warehouse"].search([("company_id", "=", company.id)], limit=1)
        return warehouse.lot_stock_id

    @api.model
    def _default_processing_location(self, company=None):
        """Use Odoo's production location so source and output moves change stock quantities."""
        company = company or self.env.company
        warehouse = self.env["stock.warehouse"].search([("company_id", "=", company.id)], limit=1)
        return warehouse._get_production_location() or warehouse.lot_stock_id

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get("name") or vals["name"] == self.env._("New"):
                vals["name"] = self.env["ir.sequence"].next_by_code("ff.recovery.operation") or self.env._("New")
        return super().create(vals_list)

    def write(self, vals):
        if any(operation.state in ("executing", "done", "reversed") for operation in self):
            protected = set(vals) - {"message_follower_ids", "activity_ids"}
            if protected and not self.env.context.get("ff_internal_write"):
                raise UserError(_("Completed recovery operations are immutable."))
        return super().write(vals)

    @api.constrains("source_location_id", "processing_location_id", "company_id")
    def _check_locations(self):
        for operation in self:
            for location in (operation.source_location_id, operation.processing_location_id):
                allowed_usages = ("internal", "production") if location == operation.processing_location_id else ("internal",)
                if location and (location.usage not in allowed_usages or location.company_id not in (False, operation.company_id)):
                    raise ValidationError(_("Recovery source and destination locations must be internal; the processing location may also be the standard production location."))

    @api.constrains("recoverable_value_percentage", "recoverable_target_amount", "eligible_recycling_costs")
    def _check_policy_values(self):
        for operation in self:
            if not 0 <= operation.recoverable_value_percentage <= 100:
                raise ValidationError(_("Recoverable value percentage must be between 0 and 100."))
            if operation.recoverable_target_amount < 0 or operation.eligible_recycling_costs < 0:
                raise ValidationError(_("Recoverable value and recycling costs cannot be negative."))
            if operation.loss_recognition == "recognize" and not operation.loss_evidence:
                raise ValidationError(_("Documented valuation evidence is required to recognize a loss."))

    def action_prepare(self):
        for operation in self:
            operation._check_operational_access()
            operation._validate_operation()
            operation.write({"state": "ready"})
        return True

    def action_apply_recipe(self):
        self.ensure_one()
        self._check_operational_access()
        if self.state != "draft":
            raise UserError(_("A recovery recipe can only be applied to a draft operation."))
        if not self.recipe_id:
            raise UserError(_("Select a recovery recipe first."))
        self.output_line_ids.unlink()
        self.env["ff.recovery.output"].create([
            {
                "operation_id": self.id,
                "sequence": line.sequence,
                "product_id": line.product_id.id,
                "quantity": line.expected_quantity,
                "expected_quantity": line.expected_quantity,
                "uom_id": line.uom_id.id,
                "output_type": line.output_type,
                "loss_class": line.loss_class,
                "allocation_weight": line.allocation_weight,
                "destination_location_id": line.destination_location_id.id,
            }
            for line in self.recipe_id.line_ids
        ])
        return True

    def action_execute(self):
        self.ensure_one()
        self._check_operational_access()
        self._claim_execution()
        self._validate_operation()
        source_moves = self._consume_inputs()
        input_value = self.company_id.currency_id.round(sum(abs(move.value) for move in source_moves))
        if self.company_id.currency_id.is_zero(input_value):
            input_value = self.company_id.currency_id.round(sum(
                line.uom_id._compute_quantity(line.quantity, line.product_id.uom_id)
                * line.product_id.with_company(self.company_id).standard_price
                for line in self.source_line_ids
            ))
        recoverable_value = self._get_recoverable_value(input_value)
        output_moves, actual_output = self._create_outputs(recoverable_value)
        accounting_move = self._create_accounting_entry(source_moves | output_moves)
        currency = self.company_id.currency_id
        difference = currency.round(actual_output - recoverable_value)
        if not currency.is_zero(difference):
            self.message_post(body=_(
                "Native output valuation differs from the allocated recoverable value by %s; "
                "the difference is recorded for review and is not silently capitalized.", difference,
            ))
        normal_loss = currency.round(input_value - recoverable_value)
        if normal_loss < 0 and not currency.is_zero(normal_loss):
            raise UserError(_("Recoverable value cannot exceed the input carrying value."))
        abnormal_loss = currency.round(sum(line.allocated_loss_value for line in self.output_line_ids if line.loss_class == "abnormal"))
        self.with_context(ff_internal_write=True).write({
            "state": "done", "input_carrying_value": input_value,
            "recoverable_value": recoverable_value,
            "allocated_output_value": recoverable_value,
            "actual_output_value": actual_output,
            "normal_loss_value": normal_loss,
            "abnormal_loss_value": abnormal_loss,
            "valuation_difference": difference,
            "source_move_ids": [Command.set(source_moves.ids)],
            "output_move_ids": [Command.set(output_moves.ids)],
            "account_move_id": accounting_move.id if accounting_move else False,
            "executed_at": fields.Datetime.now(), "executed_by": self.env.user.id,
        })
        if self.loss_recognition == "recognize":
            self.action_recognize_loss()
        return True

    def _create_accounting_entry(self, moves):
        """Post the valuation entry for an internal disassembly transformation.

        Odoo's native stock accounting intentionally skips internal-to-internal
        moves when neither location has a valuation account.  A recovery operation
        still changes the composition and value of inventory, so we post one
        balanced entry: source inventory is credited, recovered inventory is
        debited, and any valuation gap is posted to the stock variation account.
        """
        self.ensure_one()
        moves = moves.filtered(lambda move: not move.account_move_id and not self.currency_id.is_zero(move.value))
        if not moves:
            return self.env["account.move"]
        journal = self.company_id.account_stock_journal_id
        if not journal:
            raise UserError(_("Configure a stock valuation journal before completing a recovery operation."))

        lines = []
        debit_total = 0.0
        credit_total = 0.0
        for move in moves:
            account = move.product_id.with_company(self.company_id)._get_product_accounts().get("stock_valuation")
            if not account:
                raise UserError(_("Product %s has no stock valuation account configured.", move.product_id.display_name))
            value = abs(move.value)
            if move in self.source_move_ids or move.location_dest_id == self.processing_location_id:
                lines.append(Command.create({
                    "account_id": account.id, "credit": value, "debit": 0.0,
                    "name": "%s - %s" % (self.name, move.product_id.display_name),
                    "product_id": move.product_id.id,
                }))
                credit_total += value
            else:
                lines.append(Command.create({
                    "account_id": account.id, "debit": value, "credit": 0.0,
                    "name": "%s - %s" % (self.name, move.product_id.display_name),
                    "product_id": move.product_id.id,
                }))
                debit_total += value

        difference = self.currency_id.round(credit_total - debit_total)
        if not self.currency_id.is_zero(difference):
            source_product = self.source_line_ids[:1].product_id
            variation_account = self.company_id._ff_get_disassembly_variance_account(source_product)
            if not variation_account:
                raise UserError(_(
                    "Configure the Stock Valuation Account and its Stock Variation Account "
                    "on the source product category before completing a recovery operation."
                ))
            lines.append(Command.create({
                "account_id": variation_account.id,
                "debit": max(difference, 0.0),
                "credit": max(-difference, 0.0),
                "name": _("%s - Valuation difference", self.name),
            }))
        move = self.env["account.move"].sudo().create({
            "ref": self.name,
            "journal_id": journal.id,
            "line_ids": lines,
        })
        move._post()
        return move

    def action_recognize_loss(self):
        self.ensure_one()
        if not self._has_financial_access():
            raise UserError(_("Only disassembly administrators can recognize documented losses."))
        if self.state != "done":
            raise UserError(_("Only completed operations can recognize a documented loss."))
        if self.account_move_id:
            raise UserError(_("The documented loss has already been recognized."))
        if not self.loss_account_id or not self.loss_evidence:
            raise UserError(_("Select a loss account and document the valuation evidence first."))
        amount = self.company_id.currency_id.round(self.normal_loss_value)
        if self.company_id.currency_id.is_zero(amount):
            return True
        stock_account = self.source_line_ids[:1].product_id.with_company(self.company_id)._get_product_accounts().get("stock_valuation")
        if not stock_account:
            raise UserError(_("The source product has no stock valuation account configured."))
        move = self.env["account.move"].sudo().create({
            "ref": self.name, "journal_id": self.company_id.account_stock_journal_id.id,
            "line_ids": [
                Command.create({"account_id": self.loss_account_id.id, "debit": amount, "credit": 0, "name": self.name}),
                Command.create({"account_id": stock_account.id, "debit": 0, "credit": amount, "name": self.name}),
            ],
        })
        move._post()
        self.with_context(ff_internal_write=True).write({"account_move_id": move.id})
        return True

    def action_reverse(self):
        """Create a controlled stock reversal; never edit a completed move in place."""
        self.ensure_one()
        self._check_operational_access()
        if not self._has_manager_access():
            raise UserError(_("Only disassembly administrators can reverse completed operations."))
        if self.state != "done":
            raise UserError(_("Only completed recovery operations can be reversed."))
        if self.reverse_move_ids:
            raise UserError(_("This recovery operation already has a reversal."))
        reversal_moves = self.env["stock.move"]
        originals = self.output_move_ids | self.source_move_ids
        for original in originals:
            if original.state != "done":
                raise UserError(_("All original stock moves must be completed before reversal."))
            reverse = self.env["stock.move"].create({
                "origin": _("Reversal of %s", self.name),
                "reference": _("Reversal of %s", self.name),
                "product_id": original.product_id.id,
                "product_uom_qty": original.quantity,
                "uom_id": original.uom_id.id,
                "location_id": original.location_dest_id.id,
                "location_dest_id": original.location_id.id,
                "company_id": original.company_id.id,
                "origin_returned_move_id": original.id,
            })
            reverse._action_confirm()
            self.env["stock.move.line"].create({
                "move_id": reverse.id,
                "product_id": original.product_id.id,
                "uom_id": original.uom_id.id,
                "quantity": original.quantity,
                "lot_id": original.move_line_ids[:1].lot_id.id,
                "location_id": original.location_dest_id.id,
                "location_dest_id": original.location_id.id,
            })
            reverse.picked = True
            reverse._action_done()
            reversal_moves |= reverse
        reversal_account_move = self.env["account.move"]
        if self.account_move_id:
            reversal_account_move = self.account_move_id._reverse_moves(
                default_values_list=[{
                    "ref": _("Reversal of %s", self.name),
                    "date": fields.Date.context_today(self),
                }],
                cancel=True,
            )
        self.with_context(ff_internal_write=True).write({
            "state": "reversed",
            "reverse_move_ids": [Command.set(reversal_moves.ids)],
            "reversal_account_move_id": reversal_account_move.id if reversal_account_move else False,
            "reversed_at": fields.Datetime.now(),
            "reversed_by": self.env.user.id,
        })
        return True

    def _has_operational_access(self):
        return any(self.env.user.has_group(group) for group in (
            "mrp.group_mrp_user",
            "ff_advanced_disassembly.group_ff_disassembly_user",
        ))

    def _has_manager_access(self):
        return any(self.env.user.has_group(group) for group in (
            "mrp.group_mrp_manager",
            "ff_advanced_disassembly.group_ff_disassembly_administrator",
        ))

    def _has_financial_access(self):
        return any(self.env.user.has_group(group) for group in (
            "account.group_account_user",
            "account.group_account_manager",
            "mrp.group_mrp_manager",
            "ff_advanced_disassembly.group_ff_disassembly_cost_viewer",
            "ff_advanced_disassembly.group_ff_disassembly_administrator",
        ))

    def _check_operational_access(self):
        if not self._has_operational_access():
            raise UserError(_("You are not allowed to operate recovery operations."))

    def _validate_operation(self):
        self.ensure_one()
        if self.state in ("done", "reversed"):
            raise UserError(_("This recovery operation is already completed."))
        if self.source_location_id == self.processing_location_id:
            raise ValidationError(_("The processing location must be different from the source location so stock quantities can change."))
        if not self.source_line_ids:
            raise ValidationError(_("Add at least one input product."))
        if not self.output_line_ids:
            raise ValidationError(_("Add at least one output product."))
        precision = self.env["decimal.precision"].precision_get("Product Unit")
        for line in self.source_line_ids:
            if line.quantity <= 0:
                raise ValidationError(_("Input quantities must be greater than zero."))
            if line.product_id.tracking == "serial" and line.quantity != 1:
                raise ValidationError(_("Serial-tracked inputs must be entered one serial per line."))
            if line.product_id.tracking in ("lot", "serial") and not line.lot_id:
                raise ValidationError(_("A lot or serial is required for tracked inputs."))
            available = self.env["stock.quant"]._get_available_quantity(line.product_id, self.source_location_id, line.lot_id, strict=bool(line.lot_id))
            wanted = line.uom_id._compute_quantity(line.quantity, line.product_id.uom_id)
            if float_compare(available, wanted, precision_digits=precision) < 0:
                raise UserError(_("Insufficient stock for input %s.", line.product_id.display_name))
        allocatable_outputs = self.output_line_ids.filtered(lambda output: output.output_type != "waste")
        for line in self.output_line_ids:
            if line.quantity <= 0:
                raise ValidationError(_("Output quantities must be greater than zero."))
            if not line.destination_location_id and line.output_type != "waste":
                raise ValidationError(_("Select a destination for every usable output."))
            if line.output_type != "waste" and line.destination_location_id.usage != "internal":
                raise ValidationError(_("Output destinations must be internal locations."))
            if line.product_id.tracking in ("lot", "serial") and not line.lot_id:
                raise ValidationError(_("A lot or serial is required for tracked outputs."))
            if line.product_id.tracking == "serial" and line.quantity != 1:
                raise ValidationError(_("Serial-tracked outputs must be entered one serial per line."))
            if line.output_type != "waste" and line.allocation_weight <= 0:
                if len(allocatable_outputs) == 1:
                    line.with_context(ff_internal_write=True).allocation_weight = 1.0
                    continue
                fallback_weight = line.uom_id._compute_quantity(
                    line.quantity, line.product_id.uom_id
                ) * line.product_id.with_company(self.company_id).standard_price
                if fallback_weight <= 0:
                    raise ValidationError(_("Usable outputs require a positive allocation weight."))
                line.allocation_weight = fallback_weight
        if self.recoverable_value_mode == "amount" and self.recoverable_target_amount <= 0:
            raise ValidationError(_("Enter a positive recoverable target amount."))

    def _claim_execution(self):
        self.env.cr.execute("SELECT id FROM ff_recovery_operation WHERE id = %s FOR UPDATE", [self.id])
        self.invalidate_recordset()
        if self.execution_key or self.state == "done":
            raise UserError(_("This recovery operation already has an execution record."))
        self.with_context(ff_internal_write=True).write({"state": "executing", "execution_key": self.env["ir.sequence"].next_by_code("ff.recovery.execution")})

    def _consume_inputs(self):
        moves = self.env["stock.move"]
        for line in self.source_line_ids:
            product_uom_qty = line.uom_id._compute_quantity(line.quantity, line.product_id.uom_id)
            move = self.env["stock.move"].create({
                "origin": self.name, "reference": self.name, "product_id": line.product_id.id,
                "product_uom_qty": product_uom_qty, "uom_id": line.product_id.uom_id.id,
                "location_id": self.source_location_id.id, "location_dest_id": self.processing_location_id.id,
                "company_id": self.company_id.id,
            })
            move._action_confirm()
            if line.lot_id:
                reserved = move._update_reserved_quantity(product_uom_qty, self.source_location_id, lot_id=line.lot_id, strict=True)
            else:
                move._action_assign()
                reserved = sum(move.move_line_ids.mapped("quantity_product_uom"))
            if line.product_id.uom_id.compare(reserved, product_uom_qty) < 0:
                raise UserError(_("Insufficient stock for input %s.", line.product_id.display_name))
            move.picked = True
            move._action_done()
            moves |= move
        return moves

    def _get_recoverable_value(self, input_value):
        if self.recoverable_value_mode == "amount":
            value = self.recoverable_target_amount
        else:
            value = input_value * self.recoverable_value_percentage / 100.0
        return self.company_id.currency_id.round(value)

    def _create_outputs(self, recoverable_value):
        currency = self.company_id.currency_id
        allocatable = self.output_line_ids.filtered(lambda line: line.output_type != "waste")
        total_weight = sum(allocatable.mapped("allocation_weight"))
        if total_weight <= 0:
            raise ValidationError(_("At least one usable output requires a positive allocation weight."))
        moves = self.env["stock.move"]
        actual_output = 0.0
        allocated = 0.0
        allocation_index = 0
        for line in self.output_line_ids:
            value = 0.0
            if line in allocatable:
                allocation_index += 1
                value = recoverable_value - allocated if allocation_index == len(allocatable) else currency.round(recoverable_value * line.allocation_weight / total_weight)
                allocated += value
            destination = line.destination_location_id or self.company_id.scrap_location_id
            move = self.env["stock.move"].create({
                "origin": self.name, "reference": self.name, "product_id": line.product_id.id,
                "product_uom_qty": line.uom_id._compute_quantity(line.quantity, line.product_id.uom_id),
                "uom_id": line.product_id.uom_id.id, "location_id": self.processing_location_id.id,
                "location_dest_id": destination.id, "company_id": self.company_id.id,
            })
            self.env["product.value"].sudo().create({"move_id": move.id, "value": value, "description": _("Recovery allocation from %s", self.name)})
            move._action_confirm()
            self.env["stock.move.line"].create({
                "move_id": move.id, "product_id": line.product_id.id, "uom_id": line.product_id.uom_id.id,
                "quantity": move.product_uom_qty, "lot_id": line.lot_id.id,
                "location_id": self.processing_location_id.id, "location_dest_id": destination.id,
            })
            move.picked = True
            move._action_done()
            line.with_context(ff_internal_write=True).write({"allocated_value": value, "allocated_loss_value": 0.0, "stock_move_id": move.id})
            moves |= move
            actual_output += abs(move.value) if move.product_id.with_company(self.company_id).valuation == "real_time" else value
            if line.output_type == "waste":
                line.with_context(ff_internal_write=True).write({"allocated_loss_value": line.allocated_value})
        return moves, currency.round(actual_output)


class RecoveryInput(models.Model):
    _name = "ff.recovery.input"
    _description = "Recovery Operation Input"
    _order = "sequence, id"

    sequence = fields.Integer(default=10)
    operation_id = fields.Many2one("ff.recovery.operation", required=True, ondelete="cascade", index=True)
    company_id = fields.Many2one(related="operation_id.company_id", store=True, index=True)
    product_id = fields.Many2one("product.product", required=True, check_company=True)
    quantity = fields.Float(required=True, digits="Product Unit")
    uom_id = fields.Many2one("uom.uom", required=True)
    lot_id = fields.Many2one("stock.lot", check_company=True)
    notes = fields.Text()

    @api.onchange("product_id")
    def _onchange_product_id(self):
        if self.product_id:
            self.uom_id = self.product_id.uom_id

    def write(self, vals):
        if any(line.operation_id.state != "draft" for line in self) and not self.env.context.get("ff_internal_write"):
            raise UserError(_("Inputs cannot be changed after validation."))
        return super().write(vals)

    def unlink(self):
        if any(line.operation_id.state != "draft" for line in self):
            raise UserError(_("Inputs cannot be deleted after validation."))
        return super().unlink()


class RecoveryOutput(models.Model):
    _name = "ff.recovery.output"
    _description = "Recovery Operation Output"
    _order = "sequence, id"

    sequence = fields.Integer(default=10)
    operation_id = fields.Many2one("ff.recovery.operation", required=True, ondelete="cascade", index=True)
    company_id = fields.Many2one(related="operation_id.company_id", store=True, index=True)
    product_id = fields.Many2one("product.product", required=True, check_company=True)
    quantity = fields.Float(required=True, digits="Product Unit")
    expected_quantity = fields.Float(digits="Product Unit")
    uom_id = fields.Many2one("uom.uom", required=True)
    output_type = fields.Selection(
        [("usable", "Usable"), ("secondary", "Secondary output"), ("waste", "Waste / Scrap")],
        string="Output Destination",
        default="usable", required=True,
        help="Choose whether this line returns usable stock, records a secondary output, or sends material to scrap.",
    )
    loss_class = fields.Selection(
        [("normal", "Normal process loss"), ("abnormal", "Abnormal waste")],
        string="Loss Class",
        default="normal", required=True,
        help="Use only for waste lines: normal loss is expected in the process; abnormal waste needs review.",
    )
    allocation_weight = fields.Monetary(
        string="Value Allocation Weight", currency_field="currency_id",
        help="Advanced: controls how recoverable value is split between multiple non-waste outputs.",
    )
    allocated_value = fields.Monetary(currency_field="currency_id", readonly=True)
    allocated_loss_value = fields.Monetary(currency_field="currency_id", readonly=True)
    currency_id = fields.Many2one(related="company_id.currency_id")
    lot_id = fields.Many2one("stock.lot", check_company=True)
    destination_location_id = fields.Many2one("stock.location", check_company=True, domain="[('usage', '=', 'internal')]")
    stock_move_id = fields.Many2one("stock.move", readonly=True, check_company=True)
    notes = fields.Text()

    @api.onchange("product_id")
    def _onchange_product_id(self):
        if self.product_id:
            self.uom_id = self.product_id.uom_id
            if not self.allocation_weight:
                self.allocation_weight = self.product_id.standard_price

    def write(self, vals):
        if any(line.operation_id.state != "draft" for line in self) and not self.env.context.get("ff_internal_write"):
            raise UserError(_("Outputs cannot be changed after validation."))
        return super().write(vals)

    def unlink(self):
        if any(line.operation_id.state != "draft" for line in self):
            raise UserError(_("Outputs cannot be deleted after validation."))
        return super().unlink()


class RecoveryRecipe(models.Model):
    _name = "ff.recovery.recipe"
    _description = "Recovery Recipe"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "name, id"

    name = fields.Char(required=True, tracking=True)
    code = fields.Char(copy=False)
    active = fields.Boolean(default=True)
    company_id = fields.Many2one(
        "res.company", required=True, default=lambda self: self.env.company, index=True,
    )
    input_product_id = fields.Many2one("product.product", check_company=True)
    expected_yield = fields.Float(default=100.0, digits=(16, 4), help="Informational expected yield percentage.")
    line_ids = fields.One2many("ff.recovery.recipe.line", "recipe_id", copy=True)
    notes = fields.Text()

    @api.constrains("expected_yield")
    def _check_expected_yield(self):
        for recipe in self:
            if not 0 <= recipe.expected_yield <= 100:
                raise ValidationError(_("Expected yield must be between 0 and 100."))


class RecoveryRecipeLine(models.Model):
    _name = "ff.recovery.recipe.line"
    _description = "Recovery Recipe Output"
    _order = "sequence, id"

    sequence = fields.Integer(default=10)
    recipe_id = fields.Many2one("ff.recovery.recipe", required=True, ondelete="cascade", index=True)
    company_id = fields.Many2one(related="recipe_id.company_id", store=True, index=True)
    product_id = fields.Many2one("product.product", required=True, check_company=True)
    expected_quantity = fields.Float(required=True, digits="Product Unit")
    uom_id = fields.Many2one("uom.uom", required=True)
    output_type = fields.Selection(
        [("usable", "Usable"), ("secondary", "Secondary output"), ("waste", "Waste / Scrap")],
        string="Output Destination",
        default="usable", required=True,
        help="Choose whether this recipe line returns usable stock, records a secondary output, or sends material to scrap.",
    )
    loss_class = fields.Selection(
        [("normal", "Normal process loss"), ("abnormal", "Abnormal waste")],
        string="Loss Class",
        default="normal", required=True,
        help="Use only for waste lines: normal loss is expected in the process; abnormal waste needs review.",
    )
    allocation_weight = fields.Monetary(
        string="Value Allocation Weight", currency_field="currency_id",
        help="Advanced: controls how recoverable value is split between multiple non-waste outputs.",
    )
    currency_id = fields.Many2one(related="company_id.currency_id")
    destination_location_id = fields.Many2one("stock.location", check_company=True, domain="[('usage', '=', 'internal')]")
    notes = fields.Text()

    @api.onchange("product_id")
    def _onchange_product_id(self):
        if self.product_id:
            self.uom_id = self.product_id.uom_id
            if not self.allocation_weight:
                self.allocation_weight = self.product_id.standard_price

    @api.constrains("expected_quantity", "allocation_weight")
    def _check_recipe_line(self):
        for line in self:
            if line.expected_quantity <= 0:
                raise ValidationError(_("Expected recipe quantities must be greater than zero."))
            if line.output_type != "waste" and line.allocation_weight <= 0:
                raise ValidationError(_("Usable recipe outputs require a positive allocation weight."))

