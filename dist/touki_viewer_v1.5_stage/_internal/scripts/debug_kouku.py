"""甲区セクションの生テキストを確認"""
import pdfplumber, re
from pathlib import Path

PDF_PATH = Path("c:/Users/kamakei-t/Documents/touki_db/input_pdf/浜松市中央区新橋町１１４０－１不動産登記（土地全部事項）2026012900140662.PDF")

def zen2han(text):
    result = []
    for ch in text:
        code = ord(ch)
        if 0xFF01 <= code <= 0xFF5E:
            result.append(chr(code - 0xFEE0))
        elif ch == '\u3000':
            result.append(' ')
        else:
            result.append(ch)
    return "".join(result)

with pdfplumber.open(PDF_PATH) as pdf:
    text = "\n".join(p.extract_text() or "" for p in pdf.pages)

t = zen2han(text)

# 甲区セクション抽出
kouku_match = re.search(r'権\s*利\s*部.*?甲\s*区(.*?)(?:下線のある|\*)', t, re.DOTALL)
if kouku_match:
    kouku = kouku_match.group(1)
    print("=== 甲区セクション（生テキスト） ===")
    for i, line in enumerate(kouku.split('\n')):
        print(f"{i:3d}: {repr(line)}")
else:
    print("甲区セクションが見つかりません")
    print("全テキスト（最後の30行）:")
    lines = t.split('\n')
    for i, line in enumerate(lines[-30:]):
        print(f"{i:3d}: {repr(line)}")
