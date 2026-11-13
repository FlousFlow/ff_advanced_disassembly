from types import SimpleNamespace

from odoo.tests import Form, TransactionCase, tagged
from odoo.exceptions import AccessError, UserError
from odoo.addons.mrp.tests.common import TestMrpCommon
from odoo.addons.mrp_account.tests.common import TestBomPriceCommon

from odoo import Command


@tagged("post_install", "-at_install")
class TestAdvancedDisassembly(TransactionCase):
    def test_module_models_and_approved_defaults(self):
        self.assertTrue(self.env["ir.model"].search_count([("model", "=", "ff.disassembly.line")]))
        self.assertTrue(self.env["ir.model"].search_count([("model", "=", "ff.disassembly.result")]))
        company = self.env.company
        self.assertTrue(company.ff_partial_disassembly_enabled)
        self.assertFalse(company.ff_require_manager_approval)
        self.assertFalse(company.ff_require_financial_loss_approval)
        self.assertEqual(company.ff_disassembly_cost_policy, "allocated")
        self.assertEqual(company.ff_disassembly_destination_policy, "manual")

    def test_available_source_lots_are_limited_to_tracked_products_and_stock(self):
        warehouse = self.env["stock.warehouse"].search(
            [("company_id", "=", self.env.company.id)], limit=1,
        )
        stock_location = warehouse.lot_stock_id
        tracked = self.env["product.product"].create({
            "name": "Tracked Disassembly Source",
            "type": "consu",
            "is_storable": True,
            "tracking": "lot",
            "standard_price": 25.0,
        })
        lot = self.env["stock.lot"].create({
            "name": "DIS-SOURCE-LOT",
            "product_id": tracked.id,
            "company_id": self.env.company.id,
        })
        self.env["stock.quant"]._update_available_quantity(
            tracked, stock_location, 2.0, lot_id=lot,
        )
        order = self.env["mrp.unbuild"].create({
            "product_id": tracked.id,
            "product_qty": 1.0,
            "company_id": self.env.company.id,
            "location_id": stock_location.id,
            "location_dest_id": stock_location.id,
            "ff_advanced_mode": True,
        })
        self.assertEqual(order.has_tracking, "lot")
        self.assertIn(lot, order.ff_available_lot_ids)

        untracked = self.env["product.product"].create({"name": "Untracked Disassembly Source"})
        untracked_order = self.env["mrp.unbuild"].create({
            "product_id": untracked.id,
            "product_qty": 1.0,
            "company_id": self.env.company.id,
            "location_id": stock_location.id,
            "location_dest_id": stock_location.id,
            "ff_advanced_mode": True,
        })
        self.assertFalse(untracked_order.ff_available_lot_ids)

    def test_numeric_output_cost_value_drives_difference_and_legacy_fallback(self):
        product = self.env["product.product"].create({
            "name": "Numeric Output Value Source",
            "type": "consu",
            "is_storable": True,
            "standard_price": 15.0,
        })
        stock_location = self.env["stock.warehouse"].search(
            [("company_id", "=", self.env.company.id)], limit=1,
        ).lot_stock_id
        order = self.env["mrp.unbuild"].create({
            "product_id": product.id,
            "product_qty": 1.0,
            "company_id": self.env.company.id,
            "location_id": stock_location.id,
            "location_dest_id": stock_location.id,
            "ff_advanced_mode": True,
            "ff_output_cost_value": 10.0,
        })
        currency = self.env.company.currency_id
        self.assertTrue(currency.is_zero(order.ff_output_cost_value - 10.0))
        self.assertTrue(currency.is_zero(order.ff_expected_cost_difference - 5.0))
        self.assertTrue(currency.is_zero(order._ff_output_value_for_source(15.0) - 10.0))

        legacy_order = self.env["mrp.unbuild"].create({
            "product_id": product.id,
            "product_qty": 1.0,
            "company_id": self.env.company.id,
            "location_id": stock_location.id,
            "location_dest_id": stock_location.id,
            "ff_advanced_mode": True,
        })
        self.assertTrue(currency.is_zero(legacy_order._ff_output_value_for_source(15.0) - 15.0))

    def test_accounting_reference_identifies_disassembly_operation(self):
        product = self.env["product.product"].create({"name": "Reference Test Product"})
        order = self.env["mrp.unbuild"].create({
            "product_id": product.id,
            "product_qty": 2.0,
            "company_id": self.env.company.id,
            "location_id": self.env["stock.warehouse"].search(
                [("company_id", "=", self.env.company.id)], limit=1,
            ).lot_stock_id.id,
            "location_dest_id": self.env["stock.warehouse"].search(
                [("company_id", "=", self.env.company.id)], limit=1,
            ).lot_stock_id.id,
            "ff_advanced_mode": True,
        })
        reference = order._ff_accounting_reference()
        reversal_reference = order._ff_accounting_reference(reversal=True)
        self.assertIn(order.name, reference)
        self.assertIn(product.display_name, reference)
        self.assertIn("2.00", reference)
        self.assertIn("Advanced Disassembly", reference)
        self.assertIn("Reversal of Advanced Disassembly", reversal_reference)

    def test_allocation_includes_assets_residual_and_losses(self):
        currency = self.env.company.currency_id
        good = SimpleNamespace(condition="good", reference_weight=400.0, recovery_factor=1.0)
        repair = SimpleNamespace(condition="repairable", reference_weight=200.0, recovery_factor=0.5)
        retained = SimpleNamespace(condition="retained", reference_weight=200.0, recovery_factor=1.0)
        scrap = SimpleNamespace(condition="scrap", reference_weight=100.0, recovery_factor=1.0)
        missing = SimpleNamespace(condition="missing", reference_weight=100.0, recovery_factor=1.0)
        line = SimpleNamespace(result_ids=[good, repair, retained, scrap, missing])
        order = SimpleNamespace(company_id=SimpleNamespace(currency_id=currency), ff_line_ids=[line])
        result = self.env["ff.disassembly.allocation"]._allocate(order, 1000.0)
        self.assertEqual(currency.round(sum(amount for _result, amount in result["assets"].values())), 500.0)
        self.assertEqual(currency.round(result["residual"]), 200.0)
        self.assertEqual(currency.round(result["loss"]), 300.0)
        self.assertEqual(currency.round(sum(amount for _result, amount in result["assets"].values()) + result["residual"] + result["loss"]), 1000.0)


@tagged("post_install", "-at_install")
class TestDisassemblyStockExecution(TestMrpCommon):
    _test_user_groups = TestMrpCommon._test_user_groups + (
        "ff_advanced_disassembly.group_ff_disassembly_user",
    )

    def _produce_one(self):
        mo, bom, finished, component_a, component_b = self.generate_mo()
        component_a.standard_price = 20.0
        component_b.standard_price = 10.0
        for product, unit_cost in ((component_a, 20.0), (component_b, 10.0)):
            receipt = self.env["stock.move"].create({
                "product_id": product.id, "product_uom_qty": 50.0,
                "uom_id": product.uom_id.id, "price_unit": unit_cost,
                "location_id": self.supplier_location.id,
                "location_dest_id": self.stock_location.id,
                "picking_type_id": self.picking_type_in.id,
                "company_id": self.env.company.id,
            })
            receipt._action_confirm()
            receipt._action_assign()
            if product.uom_id.compare(receipt.quantity, 50.0) == 0:
                receipt.picked = True
                receipt._action_done()
            else:
                raise AssertionError("Test fixture could not receive the full component quantity through stock moves.")
        mo.action_assign()
        form = Form(mo)
        form.qty_producing = mo.product_qty
        mo = form.save()
        mo.button_mark_done()
        self.assertEqual(mo.state, "done")
        self.assertTrue(mo.move_raw_ids.filtered(lambda move: move.state == "done"))
        return mo, bom, finished, component_a, component_b

    def test_full_advanced_disassembly_moves_stock_once(self):
        _mo, bom, finished, component_a, component_b = self._produce_one()
        finished.standard_price = 100.0
        order = self.env["mrp.unbuild"].create({
            "product_id": finished.id, "bom_id": bom.id,
            "product_qty": 1.0, "company_id": self.env.company.id,
            "location_id": self.stock_location.id, "location_dest_id": self.stock_location.id,
            "ff_advanced_mode": True,
        })
        order.product_qty = 1.0
        source_qty_before = self.env["stock.quant"]._get_available_quantity(finished, self.stock_location)
        component_a_before = self.env["stock.quant"]._get_available_quantity(component_a, self.stock_location)
        component_b_before = self.env["stock.quant"]._get_available_quantity(component_b, self.stock_location)
        order.ff_load_components()
        order.action_validate()
        order.ff_execute_disassembly()
        self.assertEqual(order.state, "done")
        self.assertEqual(order.ff_workflow_state, "done")
        self.assertEqual(self.env["stock.quant"]._get_available_quantity(finished, self.stock_location), source_qty_before - 1.0)
        self.assertEqual(self.env["stock.quant"]._get_available_quantity(component_a, self.stock_location), component_a_before + 4.0)
        self.assertEqual(self.env["stock.quant"]._get_available_quantity(component_b, self.stock_location), component_b_before + 1.0)
        self.assertTrue(order.consume_line_ids.filtered(lambda move: move.product_id == finished and move.state == "done"))
        self.assertEqual(self.env["ff.disassembly.cost"].sudo().search_count([("unbuild_id", "=", order.id)]), 2)
        self.assertTrue(self.env.company.currency_id.is_zero(order.sudo().ff_valuation_difference))
        self.assertTrue(self.env.company.currency_id.is_zero(order.sudo().ff_allocated_loss_value))

    def test_partial_disassembly_creates_one_residual_asset(self):
        _mo, bom, finished, component_a, component_b = self._produce_one()
        finished.standard_price = 100.0
        order = self.env["mrp.unbuild"].create({
            "product_id": finished.id, "bom_id": bom.id, "product_qty": 1.0,
            "company_id": self.env.company.id, "location_id": self.stock_location.id,
            "location_dest_id": self.stock_location.id, "ff_advanced_mode": True,
            "ff_disassembly_type": "partial", "ff_residual_product_id": component_a.id,
            "ff_residual_destination_id": self.stock_location.id,
        })
        source_qty_before = self.env["stock.quant"]._get_available_quantity(finished, self.stock_location)
        component_a_before = self.env["stock.quant"]._get_available_quantity(component_a, self.stock_location)
        order.ff_load_components()
        order.ff_line_ids.result_ids.write({"condition": "retained", "destination_location_id": False})
        order.action_validate()
        order.action_unbuild()
        self.assertEqual(order.state, "done")
        self.assertEqual(self.env["stock.quant"]._get_available_quantity(finished, self.stock_location), source_qty_before - 1.0)
        self.assertEqual(
            self.env["stock.quant"]._get_available_quantity(component_a, self.stock_location), component_a_before + 1.0,
            f"moves={self.env['stock.move'].search([('unbuild_id', '=', order.id)]).read(['product_id', 'product_uom_qty', 'quantity', 'location_id', 'location_dest_id', 'state'])}; residual={order.ff_residual_ids.quantity}",
        )
        self.assertEqual(len(order.ff_residual_ids), 1)
        self.assertEqual(order.ff_residual_ids.quantity, 1.0)
        self.assertTrue(self.env.company.currency_id.is_zero(order.sudo().ff_valuation_difference))

    def test_missing_component_creates_documented_loss_without_stock(self):
        _mo, bom, finished, component_a, component_b = self._produce_one()
        finished.standard_price = 90.0
        order = self.env["mrp.unbuild"].create({
            "product_id": finished.id, "bom_id": bom.id, "product_qty": 1.0,
            "company_id": self.env.company.id, "location_id": self.stock_location.id,
            "location_dest_id": self.stock_location.id, "ff_advanced_mode": True,
        })
        component_b_before = self.env["stock.quant"]._get_available_quantity(component_b, self.stock_location)
        order.ff_load_components()
        missing_line = order.ff_line_ids.filtered(lambda line: line.product_id == component_b)
        missing_line.result_ids.write({"condition": "missing", "destination_location_id": False})
        order.action_validate()
        order.action_unbuild()
        self.assertTrue(self.env.company.currency_id.is_zero(order.sudo().ff_allocated_loss_value - 10.0))
        self.assertTrue(self.env.company.currency_id.is_zero(order.sudo().ff_valuation_difference))
        self.assertEqual(
            self.env["stock.quant"]._get_available_quantity(component_b, self.stock_location), component_b_before,
        )
        self.assertFalse(order.produce_line_ids.filtered(lambda move: move.product_id == component_b))

    def test_recovered_scrap_is_received_then_disposed_with_native_move(self):
        _mo, bom, finished, component_a, component_b = self._produce_one()
        finished.standard_price = 90.0
        order = self.env["mrp.unbuild"].create({
            "product_id": finished.id, "bom_id": bom.id, "product_qty": 1.0,
            "company_id": self.env.company.id, "location_id": self.stock_location.id,
            "location_dest_id": self.stock_location.id, "ff_advanced_mode": True,
        })
        component_b_before = self.env["stock.quant"]._get_available_quantity(component_b, self.stock_location)
        order.ff_load_components()
        scrap_line = order.ff_line_ids.filtered(lambda line: line.product_id == component_b)
        scrap_line.result_ids.write({"condition": "scrap"})
        order.action_validate()
        order.action_unbuild()
        scrap_moves = scrap_line.result_ids.stock_move_ids.filtered("is_scrap")
        self.assertEqual(len(scrap_moves), 1)
        self.assertEqual(scrap_moves.state, "done")
        self.assertEqual(
            self.env["stock.quant"]._get_available_quantity(component_b, self.stock_location), component_b_before,
            f"moves={scrap_line.result_ids.stock_move_ids.read(['product_id', 'product_uom_qty', 'quantity', 'location_id', 'location_dest_id', 'state', 'is_scrap'])}; lines={scrap_line.result_ids.stock_move_ids.move_line_ids.read(['quantity', 'location_id', 'location_dest_id', 'lot_id'])}",
        )
        self.assertTrue(self.env.company.currency_id.is_zero(order.sudo().ff_allocated_loss_value - 10.0))
        self.assertTrue(self.env.company.currency_id.is_zero(order.sudo().ff_actual_loss_value - 10.0))


    def test_scrap_valuation_mismatch_rolls_back_all_stock_moves(self):
        _mo, bom, finished, _component_a, component_b = self._produce_one()
        finished.standard_price = 90.0
        order = self.env["mrp.unbuild"].create({
            "product_id": finished.id, "bom_id": bom.id, "product_qty": 1.0,
            "company_id": self.env.company.id, "location_id": self.stock_location.id,
            "location_dest_id": self.stock_location.id, "ff_advanced_mode": True,
        })
        source_before = self.env["stock.quant"]._get_available_quantity(finished, self.stock_location)
        component_before = self.env["stock.quant"]._get_available_quantity(component_b, self.stock_location)
        order.ff_load_components()
        scrap_line = order.ff_line_ids.filtered(lambda line: line.product_id == component_b)
        scrap_line.result_ids.write({"condition": "scrap"})
        scrap_line.reference_unit_cost = 10.0
        scrap_line.result_ids.reference_weight = 10.0
        component_b.standard_price = 9.0
        order.action_validate()
        with self.assertRaises(UserError), self.cr.savepoint():
            order.action_unbuild()
        self.assertEqual(self.env["stock.quant"]._get_available_quantity(finished, self.stock_location), source_before)
        self.assertEqual(self.env["stock.quant"]._get_available_quantity(component_b, self.stock_location), component_before)
        self.assertFalse(order.ff_execution_key)
        self.assertNotEqual(order.ff_workflow_state, "done")

    def test_lot_and_serial_tracked_components_keep_traceability(self):
        mo, bom, finished, component_a, component_b = self.generate_mo(qty_final=1, qty_base_1=4, qty_base_2=1)
        component_a.tracking = "serial"
        component_b.tracking = "lot"
        component_a.standard_price = 20.0
        component_b.standard_price = 10.0
        serials = self.env["stock.lot"].create([
            {"name": "DIS-SN-%02d" % index, "product_id": component_a.id, "company_id": self.env.company.id}
            for index in range(1, 5)
        ])
        lot = self.env["stock.lot"].create({
            "name": "DIS-LOT-01", "product_id": component_b.id, "company_id": self.env.company.id,
        })
        for product, quantity, lots, cost in (
            (component_a, 4.0, serials, 20.0), (component_b, 1.0, lot, 10.0),
        ):
            receipt = self.env["stock.move"].create({
                "product_id": product.id, "product_uom_qty": quantity, "uom_id": product.uom_id.id,
                "price_unit": cost, "location_id": self.supplier_location.id,
                "location_dest_id": self.stock_location.id, "picking_type_id": self.picking_type_in.id,
                "company_id": self.env.company.id,
            })
            receipt._action_confirm()
            receipt.move_line_ids.unlink()
            lots = lots if isinstance(lots, (list, tuple)) or lots._name == "stock.lot" else [lots]
            for tracked_lot in lots:
                self.env["stock.move.line"].create({
                    "move_id": receipt.id, "product_id": product.id, "uom_id": product.uom_id.id,
                    "quantity": quantity / len(lots), "lot_id": tracked_lot.id,
                    "location_id": self.supplier_location.id, "location_dest_id": self.stock_location.id,
                })
            receipt.picked = True
            receipt._action_done()
        mo.action_assign()
        form = Form(mo)
        form.qty_producing = mo.product_qty
        mo = form.save()
        mo.button_mark_done()
        finished.standard_price = 90.0
        order = self.env["mrp.unbuild"].create({
            "product_id": finished.id, "bom_id": bom.id, "mo_id": mo.id, "product_qty": 1.0,
            "company_id": self.env.company.id, "location_id": self.stock_location.id,
            "location_dest_id": self.stock_location.id, "ff_advanced_mode": True,
        })
        order.ff_load_components()
        serial_line = order.ff_line_ids.filtered(lambda line: line.product_id == component_a)
        serial_line.result_ids.unlink()
        for serial in serials:
            self.env["ff.disassembly.result"].create({
                "line_id": serial_line.id, "quantity": 1.0, "condition": "good",
                "destination_location_id": self.stock_location.id, "lot_id": serial.id,
                "reference_weight": 20.0,
            })
        lot_line = order.ff_line_ids.filtered(lambda line: line.product_id == component_b)
        lot_line.result_ids.lot_id = lot
        order.action_validate()
        order.action_unbuild()
        self.assertEqual(set(order.ff_line_ids.filtered(lambda line: line.product_id == component_a).result_ids.mapped("lot_id").ids), set(serials.ids))
        self.assertEqual(order.ff_line_ids.filtered(lambda line: line.product_id == component_b).result_ids.lot_id, lot)
        for serial in serials:
            self.assertEqual(self.env["stock.quant"]._get_available_quantity(component_a, self.stock_location, serial, strict=True), 1.0)
        self.assertEqual(self.env["stock.quant"]._get_available_quantity(component_b, self.stock_location, lot, strict=True), 1.0)

    def test_other_company_orders_and_lines_are_isolated(self):
        _mo, bom, finished, component_a, _component_b = self._produce_one()
        company_b = self.env["res.company"].sudo().create({"name": "Disassembly Isolation Company"})
        location_b = self.env["stock.location"].sudo().create({
            "name": "Disassembly Isolation Stock", "usage": "internal", "company_id": company_b.id,
        })
        foreign_order = self.env["mrp.unbuild"].sudo().with_company(company_b).create({
            "product_id": finished.id, "bom_id": bom.id, "product_qty": 1.0,
            "company_id": company_b.id, "location_id": location_b.id, "location_dest_id": location_b.id,
            "ff_advanced_mode": True,
        })
        foreign_line = self.env["ff.disassembly.line"].sudo().create({
            "unbuild_id": foreign_order.id, "product_id": component_a.id,
            "uom_id": component_a.uom_id.id, "expected_qty": 1.0,
            "source_type": "manual", "discrepancy_reason": "Company isolation regression",
        })
        self.user_mrp_user.sudo().write({
            "company_id": self.company.id,
            "company_ids": [Command.set([self.company.id])],
            "group_ids": [Command.link(self.env.ref("ff_advanced_disassembly.group_ff_disassembly_user").id)],
        })
        restricted_env = self.env(user=self.user_mrp_user.id, context={"allowed_company_ids": [self.company.id]})
        with self.assertRaises(AccessError):
            foreign_order.with_env(restricted_env).read(["name"])
        self.assertFalse(restricted_env["ff.disassembly.line"].search([("id", "=", foreign_line.id)]))

    def test_completed_order_is_immutable_and_audit_is_readable(self):
        _mo, bom, finished, component_a, _component_b = self._produce_one()
        finished.standard_price = 100.0
        order = self.env["mrp.unbuild"].create({
            "product_id": finished.id, "bom_id": bom.id, "product_qty": 1.0,
            "company_id": self.env.company.id, "location_id": self.stock_location.id,
            "location_dest_id": self.stock_location.id, "ff_advanced_mode": True,
        })
        order.ff_load_components()
        order.action_validate()
        order.action_unbuild()
        self.assertTrue(order.ff_event_ids)
        with self.assertRaises(UserError):
            self.env["ff.disassembly.line"].create({
                "unbuild_id": order.id, "product_id": component_a.id,
                "uom_id": component_a.uom_id.id, "expected_qty": 1.0,
                "source_type": "manual", "discrepancy_reason": "Regression test",
            })
        with self.assertRaises(UserError):
            order.with_context(ff_internal_write=False).write({"ff_workflow_state": "draft"})
        with self.assertRaises(UserError):
            order.action_unbuild()

    def test_cost_fields_are_not_readable_by_standard_mrp_user(self):
        _mo, bom, finished, _component_a, _component_b = self._produce_one()
        finished.standard_price = 100.0
        order = self.env["mrp.unbuild"].create({
            "product_id": finished.id, "bom_id": bom.id, "product_qty": 1.0,
            "company_id": self.env.company.id, "location_id": self.stock_location.id,
            "location_dest_id": self.stock_location.id, "ff_advanced_mode": True,
        })
        order.ff_load_components()
        order.action_validate()
        order.action_unbuild()
        with self.assertRaises(AccessError):
            order.with_user(self.user_mrp_user).ff_source_carrying_value

    def test_mo_resolution_uses_actual_completed_raw_moves(self):
        mo, bom, finished, component_a, component_b = self._produce_one()
        finished.standard_price = 100.0
        order = self.env["mrp.unbuild"].create({
            "product_id": finished.id, "bom_id": bom.id, "mo_id": mo.id,
            "product_qty": 1.0, "company_id": self.env.company.id,
            "location_id": self.stock_location.id, "location_dest_id": self.stock_location.id,
            "ff_advanced_mode": True,
        })
        order.ff_load_components()
        line_a = order.ff_line_ids.filtered(lambda line: line.product_id == component_a)
        line_b = order.ff_line_ids.filtered(lambda line: line.product_id == component_b)
        self.assertEqual(line_a.source_type, "mo")
        self.assertEqual(line_b.source_type, "mo")
        self.assertTrue(line_a.source_move_id)
        self.assertTrue(line_b.source_move_id)
        self.assertEqual(line_a.expected_qty, 4.0)
        self.assertEqual(line_b.expected_qty, 1.0)

    def test_native_unbuild_stays_on_standard_path(self):
        _mo, bom, finished, component_a, component_b = self._produce_one()
        order = self.env["mrp.unbuild"].create({
            "product_id": finished.id, "bom_id": bom.id, "product_qty": 1.0,
            "company_id": self.env.company.id, "location_id": self.stock_location.id,
            "location_dest_id": self.stock_location.id,
        })
        order.action_unbuild()
        self.assertEqual(order.state, "done")
        self.assertEqual(order.ff_advanced_mode, False)
        self.assertGreater(self.env["stock.quant"]._get_available_quantity(component_a, self.stock_location), 0.0)
        self.assertGreater(self.env["stock.quant"]._get_available_quantity(component_b, self.stock_location), 0.0)



@tagged("post_install", "-at_install")
class TestDisassemblyAccounting(TestBomPriceCommon):
    _test_user_groups = TestBomPriceCommon._test_user_groups + (
        "stock.group_stock_user",
        "mrp.group_mrp_user",
        "mrp.group_mrp_manager",
        "product.group_product_manager",
        "account.group_account_manager",
        "stock.group_stock_manager",
        "ff_advanced_disassembly.group_ff_disassembly_user",
    )

    def _run_accounting_case(self, cost_method, valuation):
        category = self.category_standard_auto.copy({
            "name": "Disassembly %s %s" % (cost_method, valuation),
            "property_cost_method": cost_method,
            "property_valuation": valuation,
        })
        component = self._create_product("Disassembly Component %s %s" % (cost_method, valuation), 20.0, quantity=0, category=category)
        missing_component = self._create_product("Missing Component %s %s" % (cost_method, valuation), 10.0, quantity=0, category=category)
        finished = self._create_product("Disassembly Finished %s %s" % (cost_method, valuation), 0.0, quantity=0, category=category)
        self._make_in_move(component, 10.0, unit_cost=20.0)
        self._make_in_move(missing_component, 10.0, unit_cost=10.0)
        bom = self.env["mrp.bom"].create({
            "product_tmpl_id": finished.product_tmpl_id.id,
            "product_id": finished.id,
            "product_qty": 1.0,
            "uom_id": finished.uom_id.id,
            "type": "normal",
            "bom_line_ids": [
                Command.create({"product_id": component.id, "product_qty": 2.0, "uom_id": component.uom_id.id}),
                Command.create({"product_id": missing_component.id, "product_qty": 1.0, "uom_id": missing_component.uom_id.id}),
            ],
        })
        finished.standard_price = 50.0
        self._make_in_move(finished, 1.0, unit_cost=50.0)
        order = self.env["mrp.unbuild"].create({
            "product_id": finished.id,
            "bom_id": bom.id,
            "product_qty": 1.0,
            "company_id": self.company.id,
            "location_id": self.stock_location.id,
            "location_dest_id": self.stock_location.id,
            "ff_advanced_mode": True,
        })
        order.ff_load_components()
        missing_line = order.ff_line_ids.filtered(lambda line: line.product_id == missing_component)
        missing_line.result_ids.write({"condition": "missing", "destination_location_id": False})
        order.action_validate()
        order.action_unbuild()
        self.assertEqual(order.state, "done")
        self.assertTrue(self.company.currency_id.is_zero(order.sudo().ff_valuation_difference))
        self.assertTrue(self.company.currency_id.is_zero(order.sudo().ff_allocated_loss_value - 10.0))
        native_moves = order.consume_line_ids | order.produce_line_ids
        self.assertTrue(native_moves.filtered(lambda move: move.product_id == finished))
        if valuation == "real_time":
            account_moves = native_moves.account_move_id.filtered(lambda move: move.state == "posted")
            self.assertTrue(account_moves)
            self.assertEqual(len(account_moves), 1)
            journal_entry = account_moves[0]
            self.assertIn(order.name, journal_entry.ref)
            self.assertIn(finished.display_name, journal_entry.ref)
            self.assertIn("50.00", journal_entry.ref)
            self.assertTrue(all(order.name in line.name for line in journal_entry.line_ids))

    def test_real_time_and_periodic_standard_fifo_avco_loss_reconciliation(self):
        for cost_method in ("standard", "fifo", "average"):
            for valuation in ("periodic", "real_time"):
                with self.subTest(cost_method=cost_method, valuation=valuation):
                    self._run_accounting_case(cost_method, valuation)

