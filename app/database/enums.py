import enum


class PaymentMethod(str, enum.Enum):
    MANUAL = "MANUAL"
    PAYNOW = "PAYNOW"
    PAYLAH = "PAYLAH"
    UOB_CARD = "UOB_CARD"
    DBS_CARD = "DBS_CARD"


class ImportStatus(str, enum.Enum):
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"
