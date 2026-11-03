"""
Run once to add missing columns to existing DB.
Place at E:\ProjectR\backend\migrate_db.py
Run: python migrate_db.py
"""
import sqlite3, os

db_path = "./data/upi.db"
if not os.path.exists(db_path):
    print("DB not found — will be created fresh on next startup")
    exit()

conn = sqlite3.connect(db_path)
cur  = conn.cursor()

# Check existing columns
cur.execute("PRAGMA table_info(transactions)")
cols = [r[1] for r in cur.fetchall()]
print("Existing columns:", cols)

# Add missing columns
to_add = [
    ("included",        "BOOLEAN DEFAULT 1"),
    ("custom_category", "VARCHAR"),
    ("source_file",     "VARCHAR"),
]

for col_name, col_def in to_add:
    if col_name not in cols:
        cur.execute(f"ALTER TABLE transactions ADD COLUMN {col_name} {col_def}")
        print(f"Added column: {col_name}")
    else:
        print(f"Already exists: {col_name}")

# Check users table
cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
tables = [r[0] for r in cur.fetchall()]
print("Tables:", tables)

if 'users' not in tables:
    print("Creating users table...")
    cur.execute("""
        CREATE TABLE users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email VARCHAR UNIQUE NOT NULL,
            name VARCHAR NOT NULL,
            hashed_pw VARCHAR NOT NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            is_active BOOLEAN DEFAULT 1
        )
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS ix_users_email ON users(email)")
    print("users table created")

conn.commit()
conn.close()
print("Migration complete!")
