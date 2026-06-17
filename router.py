"""
登記簿PDFパーサー ルーター
起動ポイント: python router.py [--workers N]

処理フロー:
1. PDF収集 + 差分チェック
2. extract_text + detect_type で土地 / 建物に仕分け
3. ThreadPoolExecutor で TochiAgent / TatemonoAgent を並列起動
4. 結果をDBに書き込み → CSV + レポート出力
"""
import sys
import os
import argparse
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

SCRIPTS_DIR = Path(__file__).parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from touki_parser import (
    extract_text, zen2han, detect_type, file_md5,
    INPUT_DIR, MAP_DIR,
)
from db_writer import DbWriter
from agents.tochi_agent    import TochiAgent
from agents.tatemono_agent import TatemonoAgent


def collect_pdfs(db_writer: DbWriter) -> tuple[list, list, int]:
    """
    INPUT_DIR以下のPDFを収集し、種別判定して仕分ける。
    戻り値: (tochi_queue, tatemono_queue, skip_count)
    """
    seen_keys = set()
    pdf_files = []
    for p in sorted(INPUT_DIR.rglob("*")):
        if p.suffix.lower() != ".pdf":
            continue
        if MAP_DIR in p.parents:
            continue
        key = str(p).lower()
        if key not in seen_keys:
            seen_keys.add(key)
            pdf_files.append(p)

    print(f"PDFファイル検出: {len(pdf_files)}件（サブフォルダ含む）")

    tochi_queue, tatemono_queue = [], []
    skip_count = 0

    for pdf_path in pdf_files:
        fhash = file_md5(pdf_path)

        if db_writer.is_processed(pdf_path, fhash):
            skip_count += 1
            continue

        try:
            text = extract_text(pdf_path)
            t    = zen2han(text)

            # 表題部・不動産番号がなければ地図PDFとして除外
            if not re.search(r'表\s*題\s*部|不動産番号', t):
                dest = MAP_DIR / pdf_path.name
                if dest.exists():
                    dest.unlink()
                pdf_path.rename(dest)
                print(f"  [地図/非対応→移動] {pdf_path.name} → map/")
                continue

            doc_type = detect_type(pdf_path.name, text)

            if doc_type == "tochi":
                tochi_queue.append((pdf_path, fhash))
            elif doc_type == "tatemono":
                tatemono_queue.append((pdf_path, fhash))
            else:
                print(f"  [スキップ] 種別不明: {pdf_path.name}")

        except Exception as e:
            import traceback
            print(f"  [ERROR 収集フェーズ] {pdf_path.name}: {e}")
            traceback.print_exc()

    print(f"  土地: {len(tochi_queue)}件 / 建物: {len(tatemono_queue)}件 / スキップ: {skip_count}件")
    return tochi_queue, tatemono_queue, skip_count


def process_all_parallel(workers: int = None):
    if workers is None:
        workers = min(4, (os.cpu_count() or 2))

    db_writer      = DbWriter()
    tochi_agent    = TochiAgent()
    tatemono_agent = TatemonoAgent()

    tochi_queue, tatemono_queue, skip_count = collect_pdfs(db_writer)

    new_tochi    = []
    new_tatemono = []

    total = len(tochi_queue) + len(tatemono_queue)
    if total == 0:
        print("処理対象なし")
        db_writer.close()
        return

    print(f"\n並列処理開始（workers={workers}）")

    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {}

        for pdf_path, fhash in tochi_queue:
            f = executor.submit(tochi_agent.run, pdf_path, fhash)
            futures[f] = pdf_path

        for pdf_path, fhash in tatemono_queue:
            f = executor.submit(tatemono_agent.run, pdf_path, fhash)
            futures[f] = pdf_path

        for future in as_completed(futures):
            pdf_path = futures[future]
            try:
                result = future.result()
            except Exception as e:
                import traceback
                print(f"  [ERROR 解析フェーズ] {pdf_path.name}: {e}")
                traceback.print_exc()
                continue
            if result is None:
                continue

            print(f"  [完了] {pdf_path.name}")
            db_writer.write_record(
                result["record"],
                result["doc_type"],
                result["pdf_path"],
                result["fhash"],
            )

            if result["doc_type"] == "tochi":
                new_tochi.append(result["record"])
            else:
                new_tatemono.append(result["record"])

    today = datetime.now().strftime("%Y%m%d")
    db_writer.write_csv(new_tochi,    "tochi",    today)
    db_writer.write_csv(new_tatemono, "tatemono", today)
    db_writer.write_report(new_tochi, new_tatemono, skip_count, today)
    db_writer.close()

    print(f"\n処理完了 — 土地: {len(new_tochi)}件 / 建物: {len(new_tatemono)}件 / スキップ: {skip_count}件")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description="登記簿PDFパーサー ルーター")
    parser.add_argument("--workers", type=int, default=None,
                        help="並列ワーカー数（デフォルト: CPUコア数上限4）")
    args = parser.parse_args()
    process_all_parallel(workers=args.workers)
