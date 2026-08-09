import pandas as pd
from typing import List
from .models import Transaction
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
        self.df['month']   = self.df['date'].dt.to_period('M').astype(str)
        self.df['week']    = self.df['date'].dt.to_period('W').astype(str)
        self.df['dow']     = self.df['date'].dt.day_name()
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

        total_spent    = float(sent['amount'].sum())     if not sent.empty     else 0.0
        total_received = float(received['amount'].sum()) if not received.empty else 0.0

        # Sent breakdown
        category_breakdown = {}
        if not sent.empty:
            category_breakdown = {k: float(v) for k,v in sent.groupby('category')['amount'].sum().items()}

        monthly_trend = {}
        if not sent.empty:
            monthly_trend = {str(k): float(v) for k,v in sorted(sent.groupby('month')['amount'].sum().items())}

        # Received monthly breakdown
        monthly_received = {}
        if not received.empty:
            monthly_received = {str(k): float(v) for k,v in sorted(received.groupby('month')['amount'].sum().items())}

        # Combined monthly (sent + received per month)
        all_months = sorted(set(list(monthly_trend.keys()) + list(monthly_received.keys())))
        monthly_combined = [
            {
                "month": m,
                "spent":    monthly_trend.get(m, 0),
                "received": monthly_received.get(m, 0),
            }
            for m in all_months
        ]

        top_merchants = []
        if not sent.empty:
            top_merchants = [
                {'name': k, 'spent': float(v), 'count': int(sent[sent['merchant']==k].shape[0])}
                for k,v in sent.groupby('merchant')['amount'].sum().nlargest(8).items()
            ]

        # Top received sources
        top_received_sources = []
        if not received.empty:
            top_received_sources = [
                {'name': k, 'received': float(v), 'count': int(received[received['merchant']==k].shape[0])}
                for k,v in received.groupby('merchant')['amount'].sum().nlargest(5).items()
            ]

        # Received category breakdown
        received_category = {}
        if not received.empty:
            received_category = {k: float(v) for k,v in received.groupby('category')['amount'].sum().items()}

        dow_order = ['Monday','Tuesday','Wednesday','Thursday','Friday','Saturday','Sunday']
        dow_spending = {}
        if not sent.empty:
            dow_spending = {d: float(sent[sent['dow']==d]['amount'].sum()) for d in dow_order}

        weekly_trend = {}
        if not sent.empty:
            weekly_trend = {str(k): float(v) for k,v in sorted(sent.groupby('week')['amount'].sum().items())}

        # Largest transactions
        largest = []
        if not sent.empty:
            for _, row in sent.nlargest(5,'amount').iterrows():
                largest.append({'merchant': row['merchant'], 'amount': float(row['amount']),
                                'date': str(row['date'].date()), 'category': row['category']})

        # Recurring
        recurring = []
        if not sent.empty:
            counts = sent.groupby('merchant').agg(count=('amount','count'),total=('amount','sum'),avg=('amount','mean'))
            for k,v in counts[counts['count']>=3].sort_values('count',ascending=False).iterrows():
                recurring.append({'merchant':k,'count':int(v['count']),'total':float(v['total']),'avg':float(v['avg'])})

        # Failed
        failed_list = []
        failed_df = self.df[self.df['note'].str.upper()=='FAILED'] if 'note' in self.df.columns else pd.DataFrame()
        if not failed_df.empty:
            for _,row in failed_df.head(5).iterrows():
                failed_list.append({'merchant':row['merchant'],'amount':float(row['amount']),'date':str(row['date'].date())})

        days_active = max((self.df['date'].max()-self.df['date'].min()).days, 1)

        return {
            'total_spent':          total_spent,
            'total_received':       total_received,
            'net_flow':             total_received - total_spent,
            'total_cashback':       float(self.df['cashback'].sum()),
            'transaction_count':    len(sent),
            'received_count':       len(received),
            'total_transactions':   len(self.df),
            'failed_count':         len(failed_df),
            'average_transaction':  float(sent['amount'].mean()) if not sent.empty else 0.0,
            'avg_per_day':          round(total_spent / days_active, 2),
            'days_active':          days_active,
            'category_breakdown':   category_breakdown,
            'received_category':    received_category,
            'monthly_trend':        monthly_trend,
            'monthly_received':     monthly_received,
            'monthly_combined':     monthly_combined,
            'weekly_trend':         weekly_trend,
            'dow_spending':         dow_spending,
            'top_merchants':        top_merchants,
            'top_received_sources': top_received_sources,
            'largest_transactions': largest,
            'recurring_merchants':  recurring,
            'failed_transactions':  failed_list,
        }
