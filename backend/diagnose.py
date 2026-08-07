import sys, os
sys.path.insert(0, os.path.dirname(__file__))
 
def test_pdf(path):
    import pdfplumber
    print(f"\n=== PDF: {path} ===")
    with pdfplumber.open(path) as pdf:
        for i, page in enumerate(pdf.pages):
            print(f"\n--- Page {i+1} ---")
            # raw text
            t = page.extract_text()
            print(f"Text ({len(t) if t else 0} chars): {repr(t[:300]) if t else 'NONE'}")
            # tables default
            tables = page.extract_tables()
            print(f"Tables (default): {len(tables)}")
            for j,tbl in enumerate(tables[:2]):
                print(f"  Table {j+1} ({len(tbl)} rows x {len(tbl[0]) if tbl else 0} cols):")
                for row in tbl[:4]: print(f"    {row}")
            # tables line strategy
            tables2 = page.extract_tables({"vertical_strategy":"lines","horizontal_strategy":"lines"})
            print(f"Tables (lines): {len(tables2)}")
            for j,tbl in enumerate(tables2[:2]):
                print(f"  Table {j+1} ({len(tbl)} rows):")
                for row in tbl[:4]: print(f"    {row}")
 
def test_csv(path):
    import pandas as pd
    print(f"\n=== CSV: {path} ===")
    for skip in [0,1,2,3]:
        try:
            df = pd.read_csv(path, skiprows=skip)
            print(f"skiprows={skip}: {df.shape} | columns: {list(df.columns)}")
            print(df.head(3).to_string())
            print()
        except Exception as e:
            print(f"skiprows={skip}: ERROR {e}")
 
if __name__ == "__main__":
    pdf_path = input("PDF path (or blank to skip): ").strip().strip('"')
    if pdf_path:
        test_pdf(pdf_path)
    csv_path = input("CSV path (or blank to skip): ").strip().strip('"')
    if csv_path:
        test_csv(csv_path)