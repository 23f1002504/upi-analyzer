from pydantic import BaseModel
from datetime import datetime
from typing import Optional, List, Dict

class Transaction(BaseModel):
    date: datetime
    time: str
    amount: float
    transaction_type: str
    merchant: str
    note: Optional[str] = ""
    cashback: float = 0.0
    category: Optional[str] = None

class AnalyticsResponse(BaseModel):
    total_spent: float
    total_received: float
    net_flow: float
    total_cashback: float
    category_breakdown: Dict[str, float]
    monthly_trend: Dict[str, float]
    top_merchants: List[Dict]
    transaction_count: int
    average_transaction: float
