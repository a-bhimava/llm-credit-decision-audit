import json
import os
import sys

sys.path.insert(0, os.path.abspath('src'))

from credit_audit.profiles.generate import read_profiles_jsonl
from credit_audit.render import packet, json_
from credit_audit.types import RenderMode
from credit_audit.policy.loader import load_policy

def main():
    policy = load_policy()
    apps = read_profiles_jsonl()
    app = apps[0]
    
    p = packet.build_application_packet(app)
    
    json_str_sorted = json_.render(app, RenderMode.JSON, policy=policy)
    json_str_shuffled = json_.render(app, RenderMode.JSON, policy=policy, options=packet.RenderOptions(json_field_order_seed=42))
    
    fixtures = {
        "packet": {
            "application_reference": p.application_reference,
            "identity": {
                "applicant_name": p.identity.applicant_name,
                "employer_name": p.identity.employer_name,
                "school": p.identity.school,
                "referral_note": p.identity.referral_note,
                "pronouns": p.identity.pronouns,
                "graduation_year": p.identity.graduation_year,
            },
            "loan_request": {
                "amount_cents": p.loan_request.amount_cents,
                "term_months": p.loan_request.term_months,
            },
            "income": {
                "annual_income_cents": p.income.annual_income_cents,
                "monthly_debt_cents": p.income.monthly_debt_cents,
                "debt_to_income_ratio": p.income.debt_to_income_ratio,
                "income_documented": p.income.income_documented,
            },
            "credit_file": {
                "credit_score": p.credit_file.credit_score,
                "tradelines": {
                    "open_count": p.credit_file.tradelines.open_count,
                    "oldest_age_months": p.credit_file.tradelines.oldest_age_months,
                },
                "revolving": {
                    "balance_cents": p.credit_file.revolving.balance_cents,
                    "limit_cents": p.credit_file.revolving.limit_cents,
                    "utilization": p.credit_file.revolving.utilization,
                },
                "delinquencies": {
                    "days_30_59_24mo": p.credit_file.delinquencies.days_30_59_24mo,
                    "days_60_89_24mo": p.credit_file.delinquencies.days_60_89_24mo,
                    "days_90_plus_24mo": p.credit_file.delinquencies.days_90_plus_24mo,
                },
                "inquiries_6m": p.credit_file.inquiries_6m,
                "public_records": [
                    {"kind": r.kind.value, "months_ago": r.months_ago, "amount_cents": r.amount_cents}
                    for r in p.credit_file.public_records
                ]
            },
            "employment": {
                "status": p.employment.status,
                "months": p.employment.months,
            },
            "statement_lines": [
                {"day": t.day, "description": t.description, "amount_cents": t.amount_cents}
                for t in p.statement_lines
            ],
            "notes": list(p.notes),
        },
        "json_str_sorted": json_str_sorted,
        "json_str_shuffled": json_str_shuffled,
    }
    
    with open("web/tests/fixtures/render.json", "w") as f:
        json.dump(fixtures, f, indent=2)
        
    print("Fixtures generated successfully.")

if __name__ == "__main__":
    main()
