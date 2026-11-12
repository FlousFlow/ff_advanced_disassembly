from odoo import fields, models, _
from odoo.exceptions import UserError


class DisassemblyEvent(models.Model):
    _name = "ff.disassembly.event"
    _description = "Disassembly Audit Event"
    _order = "create_date desc, id desc"

    unbuild_id = fields.Many2one("mrp.unbuild", required=True, ondelete="cascade", index=True)
    company_id = fields.Many2one(related="unbuild_id.company_id", store=True, index=True)
    event_type = fields.Selection([
        ("created", "Created"), ("inspection", "Inspection"), ("quantity", "Quantity Changed"),
        ("location", "Destination Changed"), ("executed", "Executed"), ("reversed", "Reversed"),
        ("valuation", "Valuation Reconciled"),
    ], required=True)
    description = fields.Text(required=True)
    user_id = fields.Many2one("res.users", required=True, default=lambda self: self.env.user)

    def write(self, vals):
        raise UserError(_("Disassembly audit events are immutable."))

    def unlink(self):
        raise UserError(_("Disassembly audit events cannot be deleted."))

