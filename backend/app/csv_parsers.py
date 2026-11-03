import io, re, csv as _csv
from datetime import datetime
import numpy as np
import pandas as pd
from .pdf_parser import UPIPDFParser

_parser = UPIPDFParser()

def _s(x):
    return str(x).strip() if (x is not None and str(x).strip() not in ('nan', 'None', '')) else ''

def _parse_supermoney_df(df):
    results = []
    for _, row in df.iterrows():
        v = list(row)
        while len(v) < 8: v.append(None)
        merchant = (_s(v[0]) + (' ' + _s(v[1]) if _s(v[1]) else '')).strip()
        if not merchant: continue
        try: amount = float(str(v[4]).replace(',','').replace('+',''))
        except: continue
        d5,d6,d7 = _s(v[5]),_s(v[6]),_s(v[7])
        date_raw = f"{d5} {d6}" if re.match(r'^\d{4}$', d6) else d5
        status   = d7 if re.match(r'^\d{4}$', d6) else (d6 if d6 else d7)
        date_obj = _parser._parse_date(date_raw)
        if not date_obj: continue
        results.append({
            'date': date_obj.isoformat(), 'time': '00:00', 'amount': abs(amount),
            'transaction_type': 'sent' if amount < 0 else 'received',
            'merchant': merchant[:100], 'note': status, 'cashback': 0.0,
            'category': _parser._categorize_merchant(merchant),
        })
    return results


def _parse_gpay_csv(content: bytes) -> list[dict]:
    """
    GPay CSV format:
      col0: date ("02 Dec, 2025") or time or blank
      col1: description ("Paid to X" / "Received from X" / UPI ID / bank)
      col3 or col4: amount (₹2)
    Header rows at top are skipped automatically.
    """
    import csv as _csv, io as _io
    results = []

    def _pd(s):
        s = re.sub(r'[",]', '', s).strip()
        mm = {'jan':1,'feb':2,'mar':3,'apr':4,'may':5,'jun':6,
              'jul':7,'aug':8,'sep':9,'oct':10,'nov':11,'dec':12}
        m = re.match(r'(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})$', s)
        if not m: return None
        month = mm.get(m.group(2).lower()[:3])
        if not month: return None
        try: return datetime(int(m.group(3)), month, int(m.group(1)))
        except: return None

    def _amt(s):
        s = re.sub(r'[₹,\'\s]', '', str(s))
        try: return float(s)
        except: return None

    lines = content.decode('utf-8', errors='ignore').splitlines()
    i = 0
    while i < len(lines):
        try:
            row = next(_csv.reader([lines[i]]))
        except:
            row = lines[i].split(',')
        row = [c.strip() for c in row]
        while len(row) < 5: row.append('')

        date_obj = _pd(row[0])
        if date_obj:
            desc = row[1].strip()
            if any(x in desc.lower() for x in ['date', 'transaction detail', 'upi transaction']):
                i += 1; continue

            amount_raw = row[3] if row[3] else row[4]
            amount = _amt(amount_raw)

            txn_type = 'sent'
            merchant = desc
            if re.match(r'paid to', desc, re.I):
                txn_type = 'sent'
                merchant = re.sub(r'^paid to\s+', '', desc, flags=re.I).strip()
            elif re.match(r'received from', desc, re.I):
                txn_type = 'received'
                merchant = re.sub(r'^received from\s+', '', desc, flags=re.I).strip()

            # peek next line for time
            time_str = '00:00'
            if i + 1 < len(lines):
                next_row = lines[i+1].split(',')
                t = next_row[0].strip()
                if re.match(r'\d{1,2}:\d{2}\s*(AM|PM)', t, re.I):
                    time_str = t

            if amount and merchant:
                results.append({
                    'date': date_obj.isoformat(), 'time': time_str,
                    'amount': abs(amount),
                    'transaction_type': txn_type,
                    'merchant': merchant[:100], 'note': 'SUCCESS',
                    'cashback': 0.0,
                    'category': _parser._categorize_merchant(merchant),
                })
        i += 1
    return results


def _parse_phonepay_csv(content: bytes) -> list[dict]:
    """
    PhonePe CSV/TSV:
      Tab or comma separated
      Headers: Date, Time, Transaction Details, Transaction ID, UTR, Transaction Type, Credit/debit instrument, Amount
      Date format: "Jun 15, 2026"
      Transaction Type: CREDIT / DEBIT
    """
    import csv as _csv
    lines = content.decode('utf-8', errors='ignore').splitlines()
    results = []
    header_found = False
    month_map = {'jan':1,'feb':2,'mar':3,'apr':4,'may':5,'jun':6,
                 'jul':7,'aug':8,'sep':9,'oct':10,'nov':11,'dec':12}

    def _pd(s):
        s = re.sub(r'[",]', '', str(s)).strip()
        m = re.match(r'([A-Za-z]+)\s+(\d{1,2}),?\s+(\d{4})', s)
        if not m: return None
        month = month_map.get(m.group(1).lower()[:3])
        if not month: return None
        try: return datetime(int(m.group(3)), month, int(m.group(2)))
        except: return None

    for raw_line in lines:
        # Try tab first, then csv
        if '\t' in raw_line:
            cols = [c.strip() for c in raw_line.split('\t')]
        else:
            try: cols = [c.strip().strip('"') for c in next(_csv.reader([raw_line]))]
            except: cols = [c.strip() for c in raw_line.split(',')]

        if not cols or not cols[0]: continue

        # Detect header row
        if cols[0].strip().lower() == 'date':
            header_found = True
            continue
        if not header_found: continue
        if len(cols) < 6: continue

        date_obj = _pd(cols[0])
        if not date_obj: continue

        time_str     = cols[1].strip() if len(cols) > 1 else '00:00'
        desc         = cols[2].strip() if len(cols) > 2 else ''
        txn_type_raw = cols[5].strip() if len(cols) > 5 else ''
        # Amount is last non-empty column (col 7, sometimes col 3)
        amount_raw = ''
        for i in [7, 6, 3]:
            if len(cols) > i and cols[i].strip():
                amount_raw = cols[i].strip()
                break

        # Skip header-like rows
        if desc.lower() in ['transaction details', 'date', '']: continue
        if 'upi transaction' in desc.lower(): continue

        try: amount = float(re.sub(r'[₹,\s]', '', amount_raw))
        except: continue
        if amount <= 0: continue

        txn_type = 'received' if 'credit' in txn_type_raw.lower() else 'sent'
        merchant = desc
        for prefix in ['received from ', 'paid to ', 'sent to ', 'payment to ', 'transferred to ', 'refund from ']:
            if desc.lower().startswith(prefix):
                merchant = desc[len(prefix):].strip()
                break

        if not merchant or merchant.lower() == 'nan': continue

        results.append({
            'date': date_obj.isoformat(), 'time': time_str,
            'amount': amount, 'transaction_type': txn_type,
            'merchant': merchant[:100], 'note': 'SUCCESS',
            'cashback': 0.0, 'category': _parser._categorize_merchant(merchant),
        })
    return results




def _parse_generic(content: bytes) -> list:
    rows = []
    for skip in (0, 1, 2):
        try:
            df = pd.read_csv(io.BytesIO(content), skiprows=skip)
            df.columns = [str(c).strip().lower() for c in df.columns]
            df = df.replace({np.nan: None})
            nc = next((c for c in df.columns if any(x in c for x in ('name', 'merchant', 'description'))), None)
            ac = next((c for c in df.columns if 'amount' in c or 'amt' in c), None)
            dc = next((c for c in df.columns if 'date' in c), None)
            sc = next((c for c in df.columns if 'status' in c), None)
            if not all([nc, ac, dc]):
                continue
            for _, row in df.iterrows():
                try:
                    m = str(row[nc]).strip()
                    a = float(str(row[ac]).replace(',', '').replace('+', ''))
                    d = _parser._parse_date(str(row[dc]))
                    if not m or not d or m == 'nan':
                        continue
                    rows.append({'date': d.isoformat(), 'time': '00:00', 'amount': abs(a),
                                 'transaction_type': 'sent' if a < 0 else 'received',
                                 'merchant': m[:100], 'note': str(row[sc]) if sc else '',
                                 'cashback': 0.0, 'category': _parser._categorize_merchant(m)})
                except Exception:
                    continue
            if rows:
                break
        except Exception:
            continue
    return rows


def parse_any_csv(content: bytes):
    """Try each known statement format in turn. Returns (rows, format_name)."""
    attempts = [
        ("PhonePe", _parse_phonepay_csv),
        ("GPay", _parse_gpay_csv),
        ("SuperMoney", lambda c: _parse_supermoney_df(pd.read_csv(io.BytesIO(c), skiprows=1, header=None))),
        ("Generic", _parse_generic),
    ]
    for name, fn in attempts:
        try:
            rows = fn(content)
            if rows:
                return rows, name
        except Exception as e:
            print(f"{name} parser failed: {e}")
    return [], None
