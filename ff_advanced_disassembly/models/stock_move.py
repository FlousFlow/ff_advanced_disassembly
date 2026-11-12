from collections import defaultdict

from odoo import Command, fields, models


class StockMove(models.Model):
    _inherit = "stock.move"

    def _should_create_account_move(self):
        """Allow one advanced-disassembly journal for all of its stock moves."""
        if self.env.context.get("ff_defer_disassembly_accounting"):
            return False
        return super()._should_create_account_move()

    def _create_account_move(self):
        """Create one net journal for an advanced disassembly operation.

        Native stock accounting creates two lines per move (source movement and
        recovered output).  The disassembly engine defers those move-level
        journals and calls this method once for the complete operation.  In
        that mode, lines are netted by account so the journal shows the actual
        accounting result instead of duplicate gross legs.
        """
        if not self.env.context.get("ff_consolidate_disassembly_accounting"):
            return super()._create_account_move()

        aml_by_account = defaultdict(lambda: {"debit": 0.0, "credit": 0.0})
        move_to_link = set()
        for move in self:
            if not move._should_create_account_move():
                continue
            for aml_vals in move._get_account_move_line_vals():
                account_id = aml_vals["account_id"]
                aml_by_account[account_id]["debit"] += aml_vals.get("debit", 0.0)
                aml_by_account[account_id]["credit"] += aml_vals.get("credit", 0.0)
            move_to_link.add(move.id)

        if not aml_by_account:
            return self.env["account.move"]

        currency = self.company_id.currency_id
        aml_vals_list = []
        reference = ", ".join(sorted(set(self.mapped("reference"))))
        if len(reference) > 43:
            reference = reference[:40] + "..."
        for account_id, totals in aml_by_account.items():
            net_balance = currency.round(totals["debit"] - totals["credit"])
            if currency.is_zero(net_balance):
                continue
            aml_vals_list.append({
                "account_id": account_id,
                "name": reference or self[0].origin or self[0].product_id.display_name,
                "debit": max(net_balance, 0.0),
                "credit": max(-net_balance, 0.0),
            })

        if not aml_vals_list:
            return self.env["account.move"]

        account_move = self.env["account.move"].sudo().create({
            "ref": reference,
            "partner_id": self._get_partner_id_for_valuation_lines(),
            "journal_id": self.company_id.account_stock_journal_id.id,
            "line_ids": [Command.create(aml_vals) for aml_vals in aml_vals_list],
            "date": self.env.context.get("force_period_date") or fields.Date.context_today(self),
        })
        self.env["stock.move"].browse(move_to_link).account_move_id = account_move.id
        account_move._post()
        return account_move
