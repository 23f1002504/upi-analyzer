from pydantic import BaseModel
from datetime import datetime
from typing import Optional

class Transaction(BaseModel):
    date: datetime
    time: str = "00:00"
    amount: float
    transaction_type: str
    merchant: str
    note: Optional[str] = ""
    cashback: float = 0.0
    category: Optional[str] = None
