"""
PDAX enumerated accepted values (all case-sensitive).

These back the validation on fiat deposit / withdrawal payloads. `source_of_funds`
also accepts a free-text "Others: <text>" form, handled separately by callers.
"""
from __future__ import annotations

SOURCE_OF_FUNDS: frozenset[str] = frozenset(
    {
        "Compensation",
        "Sale/Income from Property",
        "Business Income",
        "Pension/Benefit from the Government",
        "Gift/Donation",
        "Sale/Income from Investment",
        "Inheritance/Insurance",
    }
)  # plus free-text "Others: <text>"

PURPOSE: frozenset[str] = frozenset(
    {
        "Business Expense/Employee Remittance",
        "Business Transaction",
        "Gift",
        "Loan",
        "Donation of Financial Aid",
        "Investments/Savings",
        "Purchase of Goods",
        "Education and Training",
        "Travel Expense",
        "Family Support",
        "Legal Obligation",
    }
)

RELATIONSHIP: frozenset[str] = frozenset(
    {"Spouse/Partner", "Family", "Acquaintance", "Colleague", "Business", "Myself"}
)

FEE_TYPE: frozenset[str] = frozenset({"Sender", "Beneficiary"})

SEX: frozenset[str] = frozenset({"Male", "Female"})

# Fiat deposit method → source wallet (cash-in channels).
FIAT_DEPOSIT_METHODS: dict[str, str] = {
    "paymaya_pay": "Maya",
    "grabpay_cashin": "Grab",
    "instapay_upay_cashin": "All banks / e-wallets with QRPh",
    "ub_online_upay_cashin": "UnionBank",
}

FIAT_WITHDRAWAL_METHODS: frozenset[str] = frozenset(
    {"PAY-TO-ACCOUNT-REAL-TIME", "PAY-TO-ACCOUNT-NON-REAL-TIME"}
)

# Travel-rule threshold: amounts ≥ this (PHP) require extra sender KYC.
TRAVEL_RULE_THRESHOLD_PHP = 50_000


def is_source_of_funds(value: str) -> bool:
    return value in SOURCE_OF_FUNDS or value.startswith("Others:")
