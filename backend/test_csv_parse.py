import pandas as pd
import re
from datetime import datetime
 
path = r"C:\Users\Iqra2\Downloads\test1.csv"
 
# Read with skiprows=1, no header
df = pd.read_csv(path, skiprows=1, header=None)
print("Shape:", df.shape)
print("All rows:")
for i, row in df.iterrows():
    print(f"  row {i}: {list(row)}")
 