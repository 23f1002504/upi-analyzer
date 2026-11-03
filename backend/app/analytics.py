import pandas as pd
from typing import List
from .models import Transaction
from .pdf_parser import UPIPDFParser

_parser = UPIPDFParser()
DOW = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']


class AnalyticsEngine:
    def __init__(self, transactions: List[Transaction]):
        self.transactions = transactions
        self.df = pd.DataFrame([t.model_dump() for t in transactions]) if transactions else pd.DataFrame()
        if not self.df.empty:
            self.df['date'] = pd.to_datetime(self.df['date'])
            self.df['note'] = self.df['note'].fillna('').astype(str)
            self.df['cashback'] = self.df['cashback'].fillna(0.0)
            self.df['category'] = self.df.apply(
                lambda r: r['category'] if isinstance(r['category'], str) and r['category']
                else _parser._categorize_merchant(str(r['merchant'])), axis=1)
            self.df['month'] = self.df['date'].dt.strftime('%Y-%m')
            self.df['week'] = self.df['date'].dt.strftime('%G-W%V')
            self.df['dow'] = self.df['date'].dt.day_name()

    @staticmethod
    def _sum(df, col):
        return {str(k): float(v) for k, v in df.groupby(col)['amount'].sum().items()} if not df.empty else {}

    def get_analytics(self) -> dict:
        if self.df.empty:
            return {}
        df = self.df
        failed_df = df[df['note'].str.upper() == 'FAILED']
        ok = df[df['note'].str.upper() != 'FAILED']          # failed payments never moved money
        sent = ok[ok['transaction_type'] == 'sent']
        recv = ok[ok['transaction_type'] == 'received']

        total_spent = float(sent['amount'].sum())
        total_received = float(recv['amount'].sum())
        days_active = max((df['date'].max() - df['date'].min()).days, 1)

        monthly_spent = dict(sorted(self._sum(sent, 'month').items()))
        monthly_recv = dict(sorted(self._sum(recv, 'month').items()))
        months = sorted(set(monthly_spent) | set(monthly_recv))

        merch = sent.groupby('merchant')['amount'].agg(['sum', 'count']).sort_values('sum', ascending=False)
        top_merchants = [{'name': k, 'spent': float(r['sum']), 'count': int(r['count'])}
                         for k, r in merch.head(8).iterrows()]
        rsrc = recv.groupby('merchant')['amount'].agg(['sum', 'count']).sort_values('sum', ascending=False)
        top_received = [{'name': k, 'received': float(r['sum']), 'count': int(r['count'])}
                        for k, r in rsrc.head(5).iterrows()]

        rec = sent.groupby('merchant')['amount'].agg(['count', 'sum', 'mean'])
        recurring = [{'merchant': k, 'count': int(r['count']), 'total': float(r['sum']), 'avg': float(r['mean'])}
                     for k, r in rec[rec['count'] >= 3].sort_values('count', ascending=False).iterrows()]

        largest = [{'merchant': r['merchant'], 'amount': float(r['amount']),
                    'date': str(r['date'].date()), 'category': r['category']}
                   for _, r in sent.nlargest(5, 'amount').iterrows()]

        failed = [{'merchant': r['merchant'], 'amount': float(r['amount']), 'date': str(r['date'].date())}
                  for _, r in failed_df.head(5).iterrows()]

        dow_sp = self._sum(sent, 'dow')
        return {
            'total_spent': total_spent,
            'total_received': total_received,
            'net_flow': total_received - total_spent,
            'total_cashback': float(df['cashback'].sum()),
            'transaction_count': int(len(sent)),
            'received_count': int(len(recv)),
            'total_transactions': int(len(df)),
            'failed_count': int(len(failed_df)),
            'average_transaction': float(sent['amount'].mean()) if not sent.empty else 0.0,
            'avg_per_day': round(total_spent / days_active, 2),
            'days_active': days_active,
            'category_breakdown': self._sum(sent, 'category'),
            'received_category': self._sum(recv, 'category'),
            'monthly_trend': monthly_spent,
            'monthly_received': monthly_recv,
            'monthly_combined': [{'month': m, 'spent': monthly_spent.get(m, 0.0),
                                  'received': monthly_recv.get(m, 0.0)} for m in months],
            'weekly_trend': dict(sorted(self._sum(sent, 'week').items())),
            'dow_spending': {d: dow_sp.get(d, 0.0) for d in DOW},
            'top_merchants': top_merchants,
            'top_received_sources': top_received,
            'largest_transactions': largest,
            'recurring_merchants': recurring,
            'failed_transactions': failed,
        }
