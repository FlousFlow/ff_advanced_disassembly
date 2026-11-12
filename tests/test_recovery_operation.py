from odoo import Command
from odoo.exceptions import UserError, ValidationError
from odoo.tests import TransactionCase, tagged
from odoo.addons.mrp_account.tests.common import TestBomPriceCommon


@tagged("post_install", "-at_install", "ff_recovery")
class TestRecoveryOperation(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.env.user.write({"group_ids": [
            Command.link(cls.env.ref("ff_advanced_disassembly.group_ff_disassembly_user").id),
            Command.link(cls.env.ref("ff_advanced_disassembly.group_ff_disassembly_administrator").id),
        ]})
        cls.warehouse = cls.env["stock.warehouse"].search([("company_id", "=", cls.company.id)], limit=1)
        cls.stock = cls.warehouse.lot_stock_id
        cls.supplier = cls.env.ref("stock.stock_location_suppliers")
        cls.product_category = cls.env["product.category"].create({
            "name": "Recovery Test Category",
            "property_cost_method": "standard",
            "property_valuation": "periodic",
        })
        cls.source = cls.env["product.product"].create({
            "name": "Recovery Source",
            "is_storable": True,
            "categ_id": cls.product_category.id,
            "standard_price": 100.0,
        })
        cls.output_a = cls.env["product.product"].create({
            "name": "Recovered Output A",
            "is_storable": True,
            "categ_id": cls.product_category.id,
            "standard_price": 10.0,
        })
        cls.output_b = cls.env["product.product"].create({
            "name": "Recovered Output B",
            "is_storable": True,
            "categ_id": cls.product_category.id,
            "standard_price": 10.0,
        })

    def _receive(self, product, quantity=1.0):
        move = self.env["stock.move"].create({
            "product_id": product.id,
            "product_uom_qty": quantity,
            "uom_id": product.uom_id.id,
            "location_id": self.supplier.id,
            "location_dest_id": self.stock.id,
            "picking_type_id": self.warehouse.in_type_id.id,
            "company_id": self.company.id,
        })
        move._action_confirm()
        move._action_assign()
        move.picked = True
        move._action_done()
        return move

    def test_recycling_one_output_uses_native_moves_and_allocates_value(self):
        self._receive(self.source)
        operation = self.env["ff.recovery.operation"].create({
            "operation_type": "recycling",
            "source_location_id": self.stock.id,
            "processing_location_id": self.warehouse._get_production_location().id,
            "recoverable_value_percentage": 60.0,
            "source_line_ids": [Command.create({
                "product_id": self.source.id, "quantity": 1.0, "uom_id": self.source.uom_id.id,
            })],
            "output_line_ids": [Command.create({
                "product_id": self.output_a.id, "quantity": 2.0, "uom_id": self.output_a.uom_id.id,
                "destination_location_id": self.stock.id, "allocation_weight": 1.0,
            })],
        })
        operation.action_prepare()
        operation.action_execute()
        self.assertEqual(operation.state, "done")
        self.assertEqual(len(operation.source_move_ids), 1)
        self.assertEqual(len(operation.output_move_ids), 1)
        self.assertNotEqual(operation.source_move_ids.location_id, operation.source_move_ids.location_dest_id)
        self.assertEqual(operation.output_move_ids.location_dest_id, self.stock)
        self.assertAlmostEqual(operation.recoverable_value, 60.0, places=2)
        self.assertAlmostEqual(operation.actual_output_value, 60.0, places=2)
        self.assertAlmostEqual(operation.normal_loss_value, 40.0, places=2)
        self.assertEqual(self.env["ff.recovery.operation"].search_count([("name", "=", operation.name)]), 1)

    def test_single_usable_output_auto_allocates_without_manual_weight(self):
        self._receive(self.source)
        output = self.env["product.product"].create({
            "name": "Recovered Output Without Standard Price",
            "is_storable": True,
            "categ_id": self.product_category.id,
            "standard_price": 0.0,
        })
        operation = self.env["ff.recovery.operation"].create({
            "source_location_id": self.stock.id,
            "processing_location_id": self.warehouse._get_production_location().id,
            "recoverable_value_percentage": 60.0,
            "source_line_ids": [Command.create({"product_id": self.source.id, "quantity": 1.0, "uom_id": self.source.uom_id.id})],
            "output_line_ids": [Command.create({"product_id": output.id, "quantity": 1.0, "uom_id": output.uom_id.id, "destination_location_id": self.stock.id})],
        })
        operation.action_prepare()
        self.assertEqual(operation.output_line_ids.allocation_weight, 1.0)

    def test_multiple_outputs_and_policy_require_evidence_for_loss_recognition(self):
        self._receive(self.source)
        operation = self.env["ff.recovery.operation"].create({
            "operation_type": "hybrid",
            "source_location_id": self.stock.id,
            "processing_location_id": self.warehouse._get_production_location().id,
            "recoverable_value_mode": "amount",
            "recoverable_target_amount": 80.0,
            "loss_recognition": "deferred",
            "source_line_ids": [Command.create({
                "product_id": self.source.id, "quantity": 1.0, "uom_id": self.source.uom_id.id,
            })],
            "output_line_ids": [
                Command.create({"product_id": self.output_a.id, "quantity": 1.0, "uom_id": self.output_a.uom_id.id, "destination_location_id": self.stock.id, "allocation_weight": 2.0}),
                Command.create({"product_id": self.output_b.id, "quantity": 1.0, "uom_id": self.output_b.uom_id.id, "destination_location_id": self.stock.id, "allocation_weight": 1.0}),
            ],
        })
        operation.action_prepare()
        operation.action_execute()
        self.assertEqual(operation.state, "done")
        self.assertEqual(len(operation.output_move_ids), 2)
        self.assertAlmostEqual(operation.actual_output_value, 80.0, places=2)
        self.assertTrue(operation.account_move_id)
        self.assertEqual(operation.account_move_id.state, "posted")
        self.assertAlmostEqual(sum(operation.account_move_id.line_ids.mapped("debit")), sum(operation.account_move_id.line_ids.mapped("credit")), places=2)

    def test_completed_operation_uses_new_moves_for_controlled_reversal(self):
        self._receive(self.source)
        operation = self.env["ff.recovery.operation"].create({
            "source_location_id": self.stock.id,
            "processing_location_id": self.warehouse._get_production_location().id,
            "source_line_ids": [Command.create({"product_id": self.source.id, "quantity": 1.0, "uom_id": self.source.uom_id.id})],
            "output_line_ids": [Command.create({"product_id": self.output_a.id, "quantity": 1.0, "uom_id": self.output_a.uom_id.id, "destination_location_id": self.stock.id, "allocation_weight": 1.0})],
        })
        operation.action_prepare()
        operation.action_execute()
        original_move_ids = (operation.source_move_ids | operation.output_move_ids).ids
        operation.action_reverse()
        self.assertEqual(operation.state, "reversed")
        self.assertEqual(len(operation.reverse_move_ids), len(original_move_ids))
        self.assertTrue(all(move.state == "done" for move in operation.reverse_move_ids))
        self.assertTrue(all(move.origin_returned_move_id.id in original_move_ids for move in operation.reverse_move_ids))
        if operation.account_move_id:
            self.assertEqual(operation.reversal_account_move_id.state, "posted")
            self.assertEqual(operation.reversal_account_move_id.reversed_entry_id, operation.account_move_id)

    def test_recipe_applies_expected_outputs_but_keeps_actual_quantity_editable(self):
        recipe = self.env["ff.recovery.recipe"].create({
            "name": "Two Output Yield",
            "input_product_id": self.source.id,
            "expected_yield": 80.0,
            "line_ids": [Command.create({
                "product_id": self.output_a.id, "expected_quantity": 2.0,
                "uom_id": self.output_a.uom_id.id, "allocation_weight": 2.0,
                "destination_location_id": self.stock.id,
            })],
        })
        operation = self.env["ff.recovery.operation"].create({
            "recipe_id": recipe.id,
            "source_location_id": self.stock.id,
            "processing_location_id": self.warehouse._get_production_location().id,
            "source_line_ids": [Command.create({"product_id": self.source.id, "quantity": 1.0, "uom_id": self.source.uom_id.id})],
        })
        operation.action_apply_recipe()
        self.assertEqual(operation.output_line_ids.expected_quantity, 2.0)
        operation.output_line_ids.quantity = 1.25
        self.assertEqual(operation.output_line_ids.quantity, 1.25)


@tagged("post_install", "-at_install", "ff_recovery_accounting")
class TestRecoveryAccounting(TestBomPriceCommon):
    _test_user_groups = TestBomPriceCommon._test_user_groups + (
        "stock.group_stock_user",
        "mrp.group_mrp_user",
        "account.group_account_manager",
        "stock.group_stock_manager",
        "ff_advanced_disassembly.group_ff_disassembly_user",
    )

    def _run_recovery_accounting_case(self, cost_method, valuation):
        category = self.category_standard_auto.sudo().copy({
            "name": "Recovery %s %s" % (cost_method, valuation),
            "property_cost_method": cost_method,
            "property_valuation": valuation,
            "property_stock_valuation_account_id": self.company.account_stock_valuation_id.id,
        })
        source = self._create_product("Recovery Source %s %s" % (cost_method, valuation), 50.0, quantity=0, category=category)
        output = self._create_product("Recovery Output %s %s" % (cost_method, valuation), 10.0, quantity=0, category=category)
        self._make_in_move(source, 2.0, unit_cost=50.0)
        operation = self.env["ff.recovery.operation"].create({
            "source_location_id": self.stock_location.id,
            "processing_location_id": self.warehouse._get_production_location().id,
            "recoverable_value_percentage": 60.0,
            "source_line_ids": [Command.create({"product_id": source.id, "quantity": 1.0, "uom_id": source.uom_id.id})],
            "output_line_ids": [Command.create({"product_id": output.id, "quantity": 1.0, "uom_id": output.uom_id.id, "destination_location_id": self.stock_location.id, "allocation_weight": 1.0})],
        })
        operation.action_prepare()
        operation.action_execute()
        self.assertEqual(operation.state, "done")
        self.assertAlmostEqual(operation.input_carrying_value, 50.0, places=2)
        self.assertAlmostEqual(operation.recoverable_value, 30.0, places=2)
        self.assertAlmostEqual(operation.normal_loss_value, 20.0, places=2)
        self.assertEqual(len(operation.source_move_ids), 1)
        self.assertEqual(len(operation.output_move_ids), 1)
        if valuation == "real_time":
            valuation_layers = operation.source_move_ids.product_value_ids | operation.output_move_ids.product_value_ids
            self.assertTrue(valuation_layers)
            if valuation_layers.account_move_id:
                self.assertTrue(valuation_layers.account_move_id.filtered(lambda move: move.state == "posted"))

    def test_recycling_standard_fifo_avco_periodic_and_real_time(self):
        for cost_method in ("standard", "fifo", "average"):
            for valuation in ("periodic", "real_time"):
                with self.subTest(cost_method=cost_method, valuation=valuation):
                    self._run_recovery_accounting_case(cost_method, valuation)
