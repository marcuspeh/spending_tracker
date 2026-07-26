import enum


class PaymentMethod(str, enum.Enum):
    MANUAL = "MANUAL"

    # DBS PayLah — debit only; PayLah does not send emails for incoming transfers
    PAYLAH_DEBIT = "PAYLAH_DEBIT"

    # PayNow (bank-specific)
    DBS_PAYNOW_DEBIT = "DBS_PAYNOW_DEBIT"
    DBS_PAYNOW_CREDIT = "DBS_PAYNOW_CREDIT"
    UOB_PAYNOW_DEBIT = "UOB_PAYNOW_DEBIT"
    UOB_PAYNOW_CREDIT = "UOB_PAYNOW_CREDIT"

    # Credit cards
    UOB_CC = "UOB_CC"
    UOB_CC_REFUND = "UOB_CC_REFUND"
    DBS_CC = "DBS_CC"
    DBS_CC_REFUND = "DBS_CC_REFUND"


class ImportStatus(str, enum.Enum):
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"
