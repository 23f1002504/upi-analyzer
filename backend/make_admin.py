"""
Run once to make a user admin.
Place at E:\ProjectR\backend\make_admin.py
Run: python make_admin.py your@email.com
"""
import sys, sqlite3, os

email = sys.argv[1] if len(sys.argv) > 1 else input("Email to make admin: ").strip()
db_path = "./data/upi.db"

if not os.path.exists(db_path):
    print("DB not found")
    exit()

conn = sqlite3.connect(db_path)
cur  = conn.cursor()

# Add is_admin column if missing
try:
    cur.execute("ALTER TABLE users ADD COLUMN is_admin BOOLEAN DEFAULT 0")
    conn.commit()
except: pass

cur.execute("UPDATE users SET is_admin = 1 WHERE email = ?", (email,))
conn.commit()
rows = cur.rowcount
print(f"Updated {rows} user(s). '{email}' is now admin.")

cur.execute("SELECT id, email, name, is_admin FROM users")
for r in cur.fetchall():
    print(f"  id={r[0]} email={r[1]} name={r[2]} admin={r[3]}")

conn.close()
