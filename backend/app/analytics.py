import pandas as pd
from typing import List
from .models import Transaction, AnalyticsResponse
from .pdf_parser import UPIPDFParser

_parser = UPIPDFParser()

class AnalyticsEngine:

    def __init__(self, transactions: List[Transaction]):
        self.transactions = transactions
        if transactions:
            self.df = pd.DataFrame([t.model_dump() for t in transactions])
            self._add_features()
        else:
            self.df = pd.DataFrame()

    def _add_features(self):
        self.df['month'] = self.df['date'].dt.to_period('M').astype(str)
        self.df['week']  = self.df['date'].dt.to_period('W').astype(str)
        self.df['dow']   = self.df['date'].dt.day_name()
        self.df['day']   = self.df['date'].dt.day
        mask = self.df['category'].isna()
        if mask.any():
            self.df.loc[mask,'category'] = self.df.loc[mask,'merchant'].apply(
                lambda x: _parser._categorize_merchant(str(x))
            )

    def get_analytics(self) -> dict:
        if not self.transactions:
            return {}

        sent     = self.df[self.df['transaction_type'] == 'sent']
        received = self.df[self.df['transaction_type'] == 'received']
        failed   = self.df[self.df['note'].str.upper() == 'FAILED'] if 'note' in self.df.columns else pd.DataFrame()

        total_spent    = float(sent['amount'].sum())     if not sent.empty else 0.0
        total_received = float(received['amount'].sum()) if not received.empty else 0.0

        # Category breakdown
        category_breakdown = {}
        if not sent.empty:
            category_breakdown = {k: float(v) for k, v in sent.groupby('category')['amount'].sum().items()}

        # Monthly trend
        monthly_trend = {}
        if not sent.empty:
            monthly_trend = {str(k): float(v) for k, v in sorted(sent.groupby('month')['amount'].sum().items())}

        # Top merchants
        top_merchants = []
        if not sent.empty:
            top_merchants = [
                {'name': k, 'spent': float(v), 'count': int(sent[sent['merchant']==k].shape[0])}
                for k, v in sent.groupby('merchant')['amount'].sum().nlargest(8).items()
            ]

        # Day of week spending
        dow_order = ['Monday','Tuesday','Wednesday','Thursday','Friday','Saturday','Sunday']
        dow_spending = {}
        if not sent.empty:
            dow_spending = {k: float(v) for k, v in sent.groupby('dow')['amount'].sum().items()}
            dow_spending = {d: dow_spending.get(d, 0) for d in dow_order}

        # Weekly trend
        weekly_trend = {}
        if not sent.empty:
            weekly_trend = {str(k): float(v) for k, v in sorted(sent.groupby('week')['amount'].sum().items())}

        # Largest transactions
        largest = []
        if not sent.empty:
            top5 = sent.nlargest(5, 'amount')
            largest = [
                {'merchant': row['merchant'], 'amount': float(row['amount']),
                 'date': str(row['date'].date()), 'category': row['category']}
                for _, row in top5.iterrows()
            ]

        # Recurring merchants (appear 3+ times)
        recurring = []
        if not sent.empty:
            counts = sent.groupby('merchant').agg(
                count=('amount','count'), total=('amount','sum'), avg=('amount','mean')
            )
            recurring = [
                {'merchant': k, 'count': int(v['count']), 'total': float(v['total']), 'avg': float(v['avg'])}
                for k, v in counts[counts['count'] >= 3].sort_values('count', ascending=False).iterrows()
            ]

        # Failed transactions
        failed_list = []
        if not failed.empty:
            failed_list = [
                {'merchant': row['merchant'], 'amount': float(row['amount']), 'date': str(row['date'].date())}
                for _, row in failed.head(5).iterrows()
            ]

        # Avg per day
        days_active = max((self.df['date'].max() - self.df['date'].min()).days, 1) if not self.df.empty else 1
        avg_per_day = total_spent / days_active

        return {
            'total_spent':        total_spent,
            'total_received':     total_received,
            'net_flow':           total_received - total_spent,
            'total_cashback':     float(self.df['cashback'].sum()),
            'transaction_count':  len(sent),
            'total_transactions': len(self.df),
            'failed_count':       len(failed),
            'average_transaction': float(sent['amount'].mean()) if not sent.empty else 0.0,
            'avg_per_day':        round(avg_per_day, 2),
            'days_active':        days_active,
            'category_breakdown': category_breakdown,
            'monthly_trend':      monthly_trend,
            'weekly_trend':       weekly_trend,
            'dow_spending':       dow_spending,
            'top_merchants':      top_merchants,
            'largest_transactions': largest,
            'recurring_merchants':  recurring,
            'failed_transactions':  failed_list,
        }
