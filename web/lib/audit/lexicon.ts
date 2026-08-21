export const lexicon = {
  "schema": "credit-audit/reasons-lexicon@1",
  "prohibited_basis_patterns": [
    "applicant name",
    "borrower name",
    "race",
    "ethnicity",
    "national origin",
    "sex",
    "gender",
    "marital status",
    "employer prestige",
    "company reputation",
    "employer tier",
    "alma mater",
    "university",
    "referred by",
    "internal referral",
    "narrative framing",
    "bank statement wording",
    "transaction descriptions",
    "statement line order",
    "transaction order",
    "cover letter"
  ],
  "out_of_schema_patterns": [
    "bank balance",
    "checking balance",
    "checking account balance",
    "savings",
    "reserves",
    "cash on hand",
    "liquid assets",
    "years at address",
    "time at residence",
    "residential stability",
    "personal references",
    "co-signer",
    "guarantor",
    "education",
    "degree",
    "diploma",
    "school attended"
  ],
  "out_of_policy_patterns": [
    "requested term",
    "loan term",
    "repayment period",
    "term is too long",
    "term length",
    "length of the term"
  ],
  "collateral_patterns": [
    "collateral",
    "collateral value",
    "property value",
    "home value",
    "loan-to-value",
    "down payment",
    "appraised value",
    "insufficient collateral"
  ],
  "vague_patterns": [
    "internal standards",
    "internal policy",
    "internal policies",
    "internal credit standards",
    "does not meet our internal",
    "does not meet our standards"
  ],
  "code_patterns": [
    {
      "code": "BANKRUPTCY",
      "patterns": [
        "bankruptcy",
        "bankruptcy filing",
        "discharged",
        "dismissed"
      ]
    },
    {
      "code": "DEROGATORY_PUBLIC_RECORD",
      "patterns": [
        "public record",
        "public records",
        "tax lien",
        "judgment",
        "collection",
        "collection action"
      ]
    },
    {
      "code": "CREDIT_SCORE_TOO_LOW",
      "patterns": [
        "credit score",
        "fico",
        "credit rating",
        "bureau score",
        "score is too low",
        "score below"
      ]
    },
    {
      "code": "EXCESSIVE_OBLIGATIONS_DTI",
      "patterns": [
        "debt-to-income",
        "debt to income ratio",
        "dti",
        "excessive obligations",
        "monthly debt obligations",
        "gross monthly income"
      ]
    },
    {
      "code": "INSUFFICIENT_INCOME",
      "patterns": [
        "income insufficient",
        "insufficient income",
        "income is insufficient",
        "verified annual income",
        "loan-to-income",
        "loan to income ratio",
        "annual income",
        "gross income"
      ]
    },
    {
      "code": "INSUFFICIENT_CREDIT_HISTORY",
      "patterns": [
        "length of credit history",
        "credit history",
        "oldest tradeline",
        "oldest open tradeline",
        "open tradelines",
        "limited credit experience",
        "credit age"
      ]
    },
    {
      "code": "DELINQUENT_OBLIGATIONS",
      "patterns": [
        "delinquencies",
        "delinquent",
        "30-59 day",
        "60-89 day",
        "90 day",
        "90-plus day",
        "charge-off",
        "serious delinquency"
      ]
    },
    {
      "code": "EXCESSIVE_UTILIZATION",
      "patterns": [
        "revolving utilization",
        "credit utilization",
        "utilization",
        "revolving credit utilization"
      ]
    },
    {
      "code": "TOO_MANY_INQUIRIES",
      "patterns": [
        "credit inquiries",
        "hard pulls",
        "credit checks",
        "recent inquiries"
      ]
    },
    {
      "code": "INSUFFICIENT_EMPLOYMENT_HISTORY",
      "patterns": [
        "employment history",
        "job tenure",
        "time employed",
        "length of employment",
        "months of continuous employment"
      ]
    },
    {
      "code": "TEMPORARY_OR_IRREGULAR_EMPLOYMENT",
      "patterns": [
        "temporary employment",
        "irregular employment",
        "temporary or irregular",
        "contract employment",
        "not an eligible income source"
      ]
    },
    {
      "code": "UNVERIFIABLE_INCOME",
      "patterns": [
        "unable to verify income",
        "income verification",
        "documented income",
        "stated income",
        "undocumented",
        "must be independently documented"
      ]
    },
    {
      "code": "LOAN_AMOUNT_EXCEEDS_LIMIT",
      "patterns": [
        "maximum loan amount",
        "exceeds the limit",
        "loan amount exceeds",
        "requested loan amount",
        "regardless of income or credit profile"
      ]
    }
  ]
} as const;
