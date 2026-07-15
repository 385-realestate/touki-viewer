import sqlite3
from pathlib import Path

db = Path(r'C:\Users\kamakei-t\Documents\claudecode\pipeline\toukireader\database\touki.db')
conn = sqlite3.connect(str(db))

# テーブル一覧
tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
for (tbl,) in tables:
    schema = conn.execute(f"PRAGMA table_info({tbl})").fetchall()
    pk_cols = [r[1] for r in schema if r[5] > 0]
    count = conn.execute(f"SELECT COUNT(*) FROM {tbl}").fetchone()[0]
    print(f"[{tbl}] {count}件 / PK={pk_cols}")

print()

# processed_files サンプル
print("=== processed_files (先頭5件) ===")
for r in conn.execute("SELECT file_path, doc_type FROM processed_files LIMIT 5").fetchall():
    print(" ", r)

# touki_tochi の不動産番号確認
print()
print("=== touki_tochi ===")
for r in conn.execute("SELECT * FROM touki_tochi LIMIT 3").fetchall():
    print(" ", r[:5])

conn.close()
