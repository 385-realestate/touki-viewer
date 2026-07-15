import sqlite3
from pathlib import Path

db = Path(r'C:\Users\kamakei-t\Documents\claudecode\pipeline\toukireader\database\touki.db')
conn = sqlite3.connect(str(db))
conn.isolation_level = None  # autocommit

for tbl in ['touki_tochi', 'touki_tatemono', 'processed_files']:
    n = conn.execute(f"SELECT COUNT(*) FROM {tbl}").fetchone()[0]
    conn.execute(f"DELETE FROM {tbl}")
    print(f"{tbl}: {n}件削除")

conn.execute("VACUUM")
conn.close()
print("完了")
