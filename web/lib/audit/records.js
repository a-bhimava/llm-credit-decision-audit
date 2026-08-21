"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.buildApplicant = buildApplicant;
const money_1 = require("./money");
function buildApplicant(applicant_id, facts, presentation, provenance) {
    const applicant = {
        applicant_id,
        facts: Object.freeze({ ...facts, public_records: Object.freeze([...facts.public_records.map(r => Object.freeze({ ...r }))]) }),
        presentation: Object.freeze({
            ...presentation,
            bank_statement_lines: Object.freeze(presentation.bank_statement_lines.map(t => Object.freeze({ ...t }))),
            demographic_tags: Object.freeze({ ...presentation.demographic_tags }),
            free_text_notes: Object.freeze([...presentation.free_text_notes])
        }),
        provenance: Object.freeze({
            ...provenance,
            intervention_lineage: Object.freeze([...provenance.intervention_lineage])
        }),
    };
    Object.defineProperty(applicant, "dti", {
        enumerable: false,
        get: function () {
            const monthlyIncomeCents = Math.floor(this.facts.annual_income_cents / 12);
            if (monthlyIncomeCents <= 0)
                return money_1.Ratio.fromNumber(1);
            return money_1.Ratio.fromFraction(this.facts.monthly_debt_cents, monthlyIncomeCents);
        }
    });
    Object.defineProperty(applicant, "cltv", {
        enumerable: false,
        get: function () {
            if (this.facts.property_value_cents <= 0)
                return money_1.Ratio.fromNumber(0);
            return money_1.Ratio.fromFraction(this.facts.loan_amount_cents, this.facts.property_value_cents);
        }
    });
    Object.defineProperty(applicant, "utilization", {
        enumerable: false,
        get: function () {
            if (this.facts.revolving_limit_cents <= 0)
                return money_1.Ratio.fromNumber(0);
            return money_1.Ratio.fromFraction(this.facts.revolving_balance_cents, this.facts.revolving_limit_cents);
        }
    });
    return Object.freeze(applicant);
}
