"""
登記簿PDFパース確認スクリプト
- pdfplumber でテキスト・テーブルを抽出してファイルに保存する
"""
import pdfplumber
from pathlib import Path

PDF_PATH = Path("c:/Users/kamakei-t/Documents/touki_db/input_pdf/浜松市中央区新橋町１１４０－１不動産登記（土地全部事項）2026012900140662.PDF")
OUT_PATH = Path("c:/Users/kamakei-t/Documents/touki_db/reports/parse_result.txt")

OUT_PATH.parent.mkdir(parents=True, exist_ok=True)

with pdfplumber.open(PDF_PATH) as pdf, open(OUT_PATH, "w", encoding="utf-8") as out:
    out.write(f"ファイル: {PDF_PATH.name}\n")
    out.write(f"総ページ数: {len(pdf.pages)}\n\n")

    for i, page in enumerate(pdf.pages):
        out.write(f"\n{'='*60}\n")
        out.write(f"ページ {i+1}\n")
        out.write(f"{'='*60}\n")

        text = page.extract_text()
        if text:
            out.write("[テキスト抽出結果]\n")
            out.write(text + "\n")
        else:
            out.write("[テキスト抽出結果] なし（スキャンPDFの可能性あり）\n")

        tables = page.extract_tables()
        if tables:
            out.write(f"\n[テーブル検出: {len(tables)}個]\n")
            for j, table in enumerate(tables):
                out.write(f"テーブル {j+1}:\n")
                for row in table:
                    out.write(f"  {row}\n")
        else:
            out.write("\n[テーブル] 検出なし\n")

print(f"完了: {OUT_PATH}")
