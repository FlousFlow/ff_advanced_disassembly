from odoo import api, models, _
from odoo.exceptions import ValidationError


class DisassemblyAllocation(models.AbstractModel):
    _name = "ff.disassembly.allocation"
    _description = "Disassembly Cost Allocation Engine"

    @api.model
    def _allocate(self, unbuild, source_value):
        currency = unbuild.company_id.currency_id
        buckets = []
        for line in unbuild.ff_line_ids:
            for result in line.result_ids:
                reference = result.reference_weight
                if reference <= 0:
                    raise ValidationError(_("Every result requires a positive documented allocation weight."))
                if result.condition == "good":
                    buckets.append(("asset", result, reference))
                elif result.condition == "repairable":
                    recoverable = reference * result.recovery_factor
                    if recoverable:
                        buckets.append(("asset", result, recoverable))
                    if reference > recoverable:
                        buckets.append(("loss", result, reference - recoverable))
                elif result.condition == "retained":
                    buckets.append(("residual", result, reference))
                elif result.condition == "scrap":
                    buckets.append(("scrap_loss", result, reference))
                else:
                    buckets.append(("loss", result, reference))
        total = sum(weight for _kind, _result, weight in buckets)
        if total <= 0:
            raise ValidationError(_("Allocation requires positive, documented eligible reference weights."))
        values = {"assets": {}, "residual": 0.0, "loss": 0.0, "loss_details": {}, "scrap_loss": {}}
        allocated = 0.0
        for index, (kind, result, weight) in enumerate(buckets):
            amount = source_value - allocated if index == len(buckets) - 1 else currency.round(source_value * weight / total)
            allocated += amount
            if kind == "asset":
                key = id(result)
                if key not in values["assets"]:
                    values["assets"][key] = [result, 0.0]
                values["assets"][key][1] += amount
            elif kind == "scrap_loss":
                key = id(result)
                values["scrap_loss"][key] = [result, amount]
                values["loss"] += amount
                values["loss_details"].setdefault(key, [result, 0.0])[1] += amount
            else:
                values[kind] += amount
                if kind == "loss":
                    key = id(result)
                    values["loss_details"].setdefault(key, [result, 0.0])[1] += amount
        values["total_weight"] = total
        return values

