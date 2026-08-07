import re
from datetime import datetime
from typing import List, Optional
from .models import Transaction
import pdfplumber
import pandas as pd
import io

class UPIPDFParser:

    def parse_pdf(self, pdf_file) -> List[Transaction]:
        """Parse PDF files (both text-based and scanned)"""
        transactions = []
        try:
            pdf_file.seek(0)
            with pdfplumber.open(pdf_file) as pdf:
                full_text = ""
                for page_num, page in enumerate(pdf.pages, 1):
                    # Try word-level extraction first
                    words = page.extract_words(keep_blank_chars=False)
                    if words:
                        found = self._parse_words_by_row(words)
                        if found:
                            print(f"Page {page_num}: {len(found)} txns (word method)")
                            transactions += found
                            continue

                    # Fallback: raw text
                    text = page.extract_text(layout=True) or page.extract_text() or ""
                    if text:
                        full_text += text + "\n"
                        found = self._parse_text_lines(text)
                        print(f"Page {page_num}: {len(found)} txns (text method)")
                        transactions += found

        except Exception as e:
            print(f"PDF error: {e}")
            raise

        # If word/text methods failed, try GPay format on full text
        if not transactions:
            print("Trying GPay format...")
            pdf_file.seek(0)
            with pdfplumber.open(pdf_file) as pdf:
                full_text = ""
                for page in pdf.pages:
                    full_text += (page.extract_text() or "") + "\n"
            transactions = self._parse_gpay_text(full_text)

        print(f"Total: {len(transactions)}")
        return transactions

    # ── GPay CSV Parser ──────────────────────────────────────────────────────
    def parse_gpay_csv(self, csv_content: bytes) -> List[Transaction]:
        """
        Parse GPay CSV export format:
        
        Transaction statement period,,,Sent,Received
        01 December 2025 - 31 May 2026,,,"₹22,219.84","₹7,482.06"
        Date & time,Transaction details,,Amount,
        "02 Dec, 2025",Paid to Google Play,,,₹2
        11:13 AM,UPI Transaction ID: 675002253365,,,
        ,Paid by State Bank of India 9299,,,
        "02 Dec, 2025",Received from Google Play,,,₹2
        11:14 AM,UPI Transaction ID: 675056293365,,,
        ,Paid to State Bank of India 9299,,,
        """
        transactions = []
        
        try:
            # Read CSV with pandas, skip first few rows
            df = pd.read_csv(io.BytesIO(csv_content), header=None)
            
            # Find where the actual data starts (looking for "Date & time" row)
            start_row = None
            for idx, row in df.iterrows():
                if isinstance(row[0], str) and 'Date & time' in row[0]:
                    start_row = idx
                    break
            
            if start_row is None:
                print("Could not find data header in CSV")
                return transactions
            
            # Process rows after the header
            i = start_row + 1
            while i < len(df):
                try:
                    row = df.iloc[i]
                    
                    # Check if this is a date row (first column has date like "02 Dec, 2025")
                    date_cell = str(row[0]) if pd.notna(row[0]) else ""
                    is_date_row = re.search(r'\d{1,2}\s+[A-Za-z]{3,9},\s+\d{4}', date_cell)
                    
                    if is_date_row:
                        # This is a transaction start row
                        date_str = date_cell.strip()
                        date_obj = self._parse_gpay_date(date_str)
                        if not date_obj:
                            i += 1
                            continue
                        
                        # Get description from second column
                        description = str(row[1]) if pd.notna(row[1]) else ""
                        
                        # Determine transaction type
                        txn_type = "sent"
                        merchant = description
                        if re.match(r'paid to', description, re.I):
                            txn_type = "sent"
                            merchant = re.sub(r'^paid to\s+', '', description, flags=re.I).strip()
                        elif re.match(r'received from', description, re.I):
                            txn_type = "received"
                            merchant = re.sub(r'^received from\s+', '', description, flags=re.I).strip()
                        elif re.match(r'refund from', description, re.I):
                            txn_type = "received"
                            merchant = re.sub(r'^refund from\s+', '', description, flags=re.I).strip()
                        
                        # Look for amount in the same row (column 4)
                        amount = 0
                        if len(row) > 4 and pd.notna(row[4]):
                            amount_str = str(row[4]).replace('₹', '').replace(',', '')
                            try:
                                amount = float(amount_str)
                            except:
                                pass
                        
                        # If amount not found, check next row (GPay sometimes puts amount on next line)
                        if amount == 0 and i + 1 < len(df):
                            next_row = df.iloc[i + 1]
                            if pd.notna(next_row[0]) and isinstance(next_row[0], str) and '₹' in str(next_row[0]):
                                amount_str = str(next_row[0]).replace('₹', '').replace(',', '')
                                try:
                                    amount = float(amount_str)
                                except:
                                    pass
                            elif pd.notna(next_row[4]) and isinstance(next_row[4], str) and '₹' in str(next_row[4]):
                                amount_str = str(next_row[4]).replace('₹', '').replace(',', '')
                                try:
                                    amount = float(amount_str)
                                except:
                                    pass
                        
                        # Look for time in next row
                        time_str = ""
                        if i + 1 < len(df):
                            next_row = df.iloc[i + 1]
                            if pd.notna(next_row[0]) and isinstance(next_row[0], str):
                                time_match = re.search(r'(\d{1,2}:\d{2}\s*(?:AM|PM))', str(next_row[0]))
                                if time_match:
                                    time_str = time_match.group(1)
                        
                        if amount > 0 and merchant and len(merchant) > 2:
                            print(f"  GPay CSV ✓ {merchant[:35]} | {txn_type} | ₹{amount} | {date_str}")
                            
                            transaction = Transaction(
                                date=date_obj,
                                time=time_str,
                                amount=amount,
                                transaction_type=txn_type,
                                merchant=merchant[:100],
                                note="SUCCESS",
                                cashback=0.0,
                                category=self._categorize_merchant(merchant)
                            )
                            transactions.append(transaction)
                        
                        i += 2  # Skip time row
                        continue
                    
                    i += 1
                    
                except Exception as e:
                    print(f"Row parsing error: {e}")
                    i += 1
                    continue
                    
        except Exception as e:
            print(f"CSV parsing error: {e}")
        
        print(f"Total GPay CSV transactions: {len(transactions)}")
        return transactions

    # ── Google Pay PDF format ────────────────────────────────────────────────
    def _parse_gpay_text(self, text: str) -> List[Transaction]:
        """
        GPay PDF format:
          02 Dec, 2025
          Paid to Google Play
          ₹2
          11:13 AM
          UPI Transaction ID: 675002253365
          Paid by State Bank of India 9299
        """
        transactions = []
        lines = [l.strip() for l in text.split('\n') if l.strip()]

        i = 0
        while i < len(lines):
            # Look for date line: "02 Dec, 2025" or "02 December 2025"
            date_obj = self._parse_gpay_date(lines[i])
            if not date_obj:
                i += 1
                continue

            # Next line should be time "11:13 AM"
            time_str = ""
            if i+1 < len(lines) and re.match(r'\d{1,2}:\d{2}\s*(AM|PM)', lines[i+1], re.I):
                time_str = lines[i+1]
                i += 2
            else:
                i += 1

            # Next: transaction description "Paid to X" or "Received from X"
            if i >= len(lines):
                break
            desc_line = lines[i]
            i += 1

            # Determine direction
            txn_type = "sent"
            merchant = desc_line
            if re.match(r'paid to', desc_line, re.I):
                txn_type = "sent"
                merchant = re.sub(r'^paid to\s+', '', desc_line, flags=re.I).strip()
            elif re.match(r'received from', desc_line, re.I):
                txn_type = "received"
                merchant = re.sub(r'^received from\s+', '', desc_line, flags=re.I).strip()

            # Skip UPI Transaction ID and bank lines
            while i < len(lines) and not re.match(r'^[₹\d]', lines[i]):
                i += 1

            # Amount line: "₹2" or "₹2,250.00"
            if i >= len(lines):
                break
            amount_line = lines[i]
            i += 1

            amount_match = re.search(r'[\d,]+\.?\d*', amount_line.replace('₹',''))
            if not amount_match:
                continue
            try:
                amount = float(amount_match.group().replace(',',''))
            except:
                continue

            if amount == 0 or not merchant:
                continue

            transactions.append(Transaction(
                date=date_obj, time=time_str, amount=amount,
                transaction_type=txn_type, merchant=merchant[:100],
                note="SUCCESS", cashback=0.0,
                category=self._categorize_merchant(merchant)
            ))
            print(f"  GPay ✓ {merchant[:35]} | {txn_type} | ₹{amount} | {date_obj.date()}")

        return transactions

    def _parse_gpay_date(self, s: str) -> Optional[datetime]:
        """Parse '02 Dec, 2025' or '02 December 2025'"""
        s = s.replace(',','').strip()
        m = re.match(r'(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})$', s)
        if not m:
            return None
        month_map = {'jan':1,'feb':2,'mar':3,'apr':4,'may':5,'jun':6,
                     'jul':7,'aug':8,'sep':9,'oct':10,'nov':11,'dec':12}
        month = month_map.get(m.group(2).lower()[:3])
        if not month:
            return None
        try:
            return datetime(int(m.group(3)), month, int(m.group(1)))
        except:
            return None

    # ── Word-level extraction (SuperMoney / generic) ──────────────────────────
    def _parse_words_by_row(self, words: list) -> List[Transaction]:
        if not words:
            return []
        rows: dict[int, list] = {}
        for w in words:
            y = round(w['top'] / 3) * 3
            rows.setdefault(y, []).append(w)

        transactions = []
        for y in sorted(rows.keys()):
            row_words = sorted(rows[y], key=lambda w: w['x0'])
            line = " ".join(w['text'] for w in row_words)
            t = self._parse_line(line)
            if t:
                transactions.append(t)
        return transactions

    def _parse_text_lines(self, text: str) -> List[Transaction]:
        return [t for t in (self._parse_line(l.strip()) for l in text.split('\n') if l.strip()) if t]

    def _parse_line(self, line: str) -> Optional[Transaction]:
        am = re.search(r'([-+]?\d{1,7}\.\d{2})', line)
        dm = re.search(r'(\d{1,2}\s+[A-Za-z]{3,9}\s+\d{4})', line)
        if not am or not dm:
            return None
        amount = float(am.group(1))
        date_obj = self._parse_date(dm.group(1))
        if not date_obj or amount == 0:
            return None
        merchant = re.sub(r'\s+', ' ', line[:line.find(am.group(1))]).replace('|','').strip()
        merchant = re.sub(r'\b(SBI|HDFC|ICICI|AXIS|PNB|BOI)\s*[\dX]+\b', '', merchant, re.I).strip()
        if len(merchant) < 2:
            return None
        return Transaction(
            date=date_obj, time="00:00", amount=abs(amount),
            transaction_type="sent" if amount < 0 else "received",
            merchant=merchant[:100], note="", cashback=0.0,
            category=self._categorize_merchant(merchant)
        )

    # ── Shared ────────────────────────────────────────────────────────────────
    def _parse_date(self, date_str: str) -> Optional[datetime]:
        if not date_str:
            return None
        date_str = date_str.strip()
        month_map = {'jan':1,'feb':2,'mar':3,'apr':4,'may':5,'jun':6,
                     'jul':7,'aug':8,'sep':9,'oct':10,'nov':11,'dec':12}
        m = re.search(r'(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})', date_str, re.IGNORECASE)
        if m:
            month = month_map.get(m.group(2).lower()[:3], 0)
            if month:
                return datetime(int(m.group(3)), month, int(m.group(1)))
        for fmt in ('%d/%m/%Y','%Y-%m-%d','%d-%m-%Y','%d-%b-%Y'):
            try: return datetime.strptime(date_str.strip(), fmt)
            except: pass
        return None

    def _categorize_merchant(self, merchant: str) -> str:
        m = merchant.lower()
        if any(x in m for x in ['repayment','supercard','credit card','loan']): 
            return 'Credit Card'
        elif any(x in m for x in ['medical','hospital','pharmacy','clinic','health','apollo','medlife']): 
            return 'Healthcare'
        elif any(x in m for x in ['humsafar','eht','travel','hotel','flight','irctc','railway','bus','msrtc']): 
            return 'Travel'
        elif any(x in m for x in ['amazon','flipkart','myntra','meesho','ajio','nykaa']): 
            return 'Shopping'
        elif any(x in m for x in ['zomato','swiggy','restaurant','cafe','food','blinkit','zepto','instamart']): 
            return 'Food & Grocery'
        elif any(x in m for x in ['uber','ola','rapido','metro','petrol','fuel','auto']): 
            return 'Transport'
        elif any(x in m for x in ['electricity','water','gas','broadband','jio','airtel','vi','bsnl','bill','recharge']): 
            return 'Utilities'
        elif any(x in m for x in ['google play','netflix','spotify','hotstar','prime','youtube']): 
            return 'Entertainment'
        elif any(x in m for x in ['school','college','academy','tuition','fees','salaf']): 
            return 'Education'
        elif any(x in m for x in ['nf','transfer','self','wallet']): 
            return 'Transfer'
        else: 
            return 'Other'