"""
Pre-flight validation against PDAX accepted values.

Fiat deposit/withdraw payloads carry enum-constrained fields (country, bank
code, method, source of funds, purpose, relationship, fee type, sex) and a
travel-rule requirement for amounts ≥ 50,000 PHP. Validating here — before the
network call — turns a slow round-trip 400 into an instant, specific error.
"""
from __future__ import annotations

from . import constants as c
from .errors import PdaxError
from .models.funding import FiatDepositRequest
from .models.withdrawals import FiatWithdrawRequest


def _bad(message: str) -> None:
    raise PdaxError(message, code="PAP0002", name="FieldValidationError", http_status=400)


def _country(field: str, value: str | None) -> None:
    if value and not c.is_accepted_country(value):
        _bad(f"{field} '{value}' is not an accepted country")


def _common(req: FiatDepositRequest | FiatWithdrawRequest) -> None:
    if not c.is_source_of_funds(req.source_of_funds):
        _bad("source_of_funds is not valid")
    if req.purpose not in c.PURPOSE:
        _bad("purpose is not valid")
    if req.relationship_of_sender_to_beneficiary not in c.RELATIONSHIP:
        _bad("relationship_of_sender_to_beneficiary is not valid")
    _country("sender_country_origin", req.sender_country_origin)
    _country("sender_nationality", getattr(req, "sender_nationality", None))
    _country("sender_country", getattr(req, "sender_country", None))
    _country("beneficiary_country", getattr(req, "beneficiary_country", None))
    _country("beneficiary_nationality", getattr(req, "beneficiary_nationality", None))
    sex = getattr(req, "beneficiary_sex", None)
    if sex and sex not in c.SEX:
        _bad("beneficiary_sex must be Male or Female")


def _travel_rule(req: FiatDepositRequest | FiatWithdrawRequest) -> None:
    try:
        amount = float(req.amount)
    except (TypeError, ValueError):
        _bad("amount must be a number")
        return
    if amount < c.TRAVEL_RULE_THRESHOLD_PHP:
        return
    has_address = bool(
        getattr(req, "sender_address_line_one", None)
        and getattr(req, "sender_city", None)
        and getattr(req, "sender_country", None)
    )
    has_nid = bool(getattr(req, "sender_national_identity_number", None))
    has_dob = bool(
        getattr(req, "sender_dob", None) and getattr(req, "sender_place_of_birth", None)
    )
    if not (has_address or has_nid or has_dob):
        _bad(
            "amount >= 50,000 PHP requires sender address, national ID, "
            "or date + place of birth (travel rule)"
        )


def validate_fiat_deposit(req: FiatDepositRequest) -> None:
    if req.currency != "PHP":
        _bad("currency must be PHP")
    if req.method not in c.FIAT_DEPOSIT_METHODS:
        _bad(f"method '{req.method}' is not a supported deposit channel")
    _common(req)
    _travel_rule(req)


def validate_fiat_withdraw(req: FiatWithdrawRequest) -> None:
    if req.currency != "PHP":
        _bad("currency must be PHP")
    if req.method not in c.FIAT_WITHDRAWAL_METHODS:
        _bad(f"method '{req.method}' is not a supported withdrawal method")
    if req.fee_type not in c.FEE_TYPE:
        _bad("fee_type must be Sender or Beneficiary")
    if not c.is_valid_bank_code(req.beneficiary_bank_code):
        _bad(f"bank code '{req.beneficiary_bank_code}' is not valid")
    _common(req)
    _travel_rule(req)
