import sqlite3
import os

DB_PATH = "al.db"   # adjust if your DB lives elsewhere

def add_epic_column():
    if not os.path.exists(DB_PATH):
        print(f"Database not found: {DB_PATH}")
        return

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    # Check if column already exists
    cur.execute("PRAGMA table_info(modules)")
    cols = [row[1] for row in cur.fetchall()]

    if "epic" in cols:
        print("Column 'epic' already exists. No changes made.")
        conn.close()
        return

    # Add the new column (SQLite uses INTEGER for booleans)
    print("Adding column 'epic' to modules...")
    cur.execute("""
        ALTER TABLE modules
        ADD COLUMN epic INTEGER NOT NULL DEFAULT 0;
    """)

    conn.commit()
    conn.close()
    print("Column 'epic' added successfully.")

if __name__ == "__main__":
    add_epic_column()
