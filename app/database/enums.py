import enum


class PaymentMethod(str, enum.Enum):
    MANUAL = "MANUAL"
    # DBS PayLah — only DBS offers PayLah, so the values stay bank-agnostic
    PAYLAH_DEBIT = "PAYLAH_DEBIT"
    PAYLAH_CREDIT = "PAYLAH_CREDIT"
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
