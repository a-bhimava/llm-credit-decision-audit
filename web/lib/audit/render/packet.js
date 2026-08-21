"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.buildApplicationPacket = buildApplicationPacket;
const reference_1 = require("./reference");
const random_1 = require("../random");
const ids_1 = require("../ids");
function realizedStatementOrder(applicant) {
    let lines = [...applicant.presentation.bank_statement_lines];
    if (lines.length < 2 || applicant.presentation.line_order_seed === 0) {
        return lines;
    }
    const original = [...lines];
    const seed = (0, ids_1.deriveSeed)(applicant.presentation.line_order_seed, applicant.applicant_id, "bank-statement-order");
    const rng = new random_1.PythonRandom(seed);
    rng.shuffle(lines);
    let same = true;
    for (let i = 0; i < lines.length; i++) {
        if (lines[i] !== original[i]) {
            same = false;
            break;
        }
    }
    if (same) {
        const first = lines.shift();
        lines.push(first);
    }
    return lines;
}
function buildApplicationPacket(applicant) {
    return Object.freeze({
        application_reference: (0, reference_1.applicantReferenceFor)(applicant),
        identity: Object.freeze({
            applicant_name: applicant.presentation.applicant_name,
            employer_name: applicant.presentation.employer_name,
            school: applicant.presentation.school,
            referral_note: applicant.presentation.referral_note,
            pronouns: applicant.presentation.pronouns,
            graduation_year: applicant.presentation.graduation_year,
        }),
        loan_request: Object.freeze({
            amount_cents: applicant.facts.loan_amount_cents,
            term_months: applicant.facts.loan_term_months,
        }),
        income: Object.freeze({
            annual_income_cents: applicant.facts.annual_income_cents,
            monthly_debt_cents: applicant.facts.monthly_debt_cents,
            debt_to_income_ratio: applicant.dti.toString(),
            income_documented: applicant.facts.income_documented,
        }),
        credit_file: Object.freeze({
            credit_score: applicant.facts.credit_score,
            tradelines: Object.freeze({
                open_count: applicant.facts.open_tradelines,
                oldest_age_months: applicant.facts.oldest_tradeline_months,
            }),
            revolving: Object.freeze({
                balance_cents: applicant.facts.revolving_balance_cents,
                limit_cents: applicant.facts.revolving_limit_cents,
                utilization: applicant.utilization.toString(),
            }),
            delinquencies: Object.freeze({
                days_30_59_24mo: applicant.facts.delinq_30d_24m,
                days_60_89_24mo: applicant.facts.delinq_60d_24m,
                days_90_plus_24mo: applicant.facts.delinq_90p_24m,
            }),
            inquiries_6m: applicant.facts.inquiries_6m,
            public_records: Object.freeze(applicant.facts.public_records.map(r => Object.freeze({
                kind: r.kind,
                months_ago: r.months_ago,
                amount_cents: r.amount_cents,
            }))),
        }),
        employment: Object.freeze({
            status: applicant.facts.employment_status,
            months: applicant.facts.employment_months,
        }),
        statement_lines: Object.freeze(realizedStatementOrder(applicant).map(t => Object.freeze({
            day: t.day,
            description: t.description,
            amount_cents: t.amount_cents,
        }))),
        notes: Object.freeze([...applicant.presentation.free_text_notes]),
    });
}
