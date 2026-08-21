import json
import os
import sys
from decimal import Decimal

sys.path.insert(0, os.path.abspath('src'))

from credit_audit.profiles.generate import read_profiles_jsonl
from credit_audit.policy.oracle import evaluate

def decimal_default(obj):
    if isinstance(obj, Decimal):
        return float(obj)
    raise TypeError

def main():
    apps = read_profiles_jsonl()
    app = apps[0]
    
    decision = evaluate(app.facts)
    
    fixtures = {
        "outcome": decision.outcome.value,
        "counteroffer_available": decision.counteroffer_available,
        "evaluations": [
            {
                "rule_id": e.rule_id,
                "breached": e.breached,
                "margin": float(e.margin),
                "slack": float(e.slack),
                "observed_display": e.observed_display,
            }
            for e in decision.evaluations
        ]
    }
    
    with open("web/tests/fixtures/oracle.json", "w") as f:
        json.dump(fixtures, f, indent=2, default=decimal_default)
        
    print("Fixtures generated successfully.")

if __name__ == "__main__":
    main()
