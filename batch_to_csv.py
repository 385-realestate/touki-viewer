# -*- coding: utf-8 -*-
"""
登記簿PDF → 縦持ちCSV 一括変換スクリプト

使い方:
  python batch_to_csv.py --batch           # 全PDF → output/reports/touki_hist_all.csv（上書き）
  python batch_to_csv.py --add <PATH>      # PDF/フォルダ → output/csv/<名前>.csv に蓄積

CSV列構成:
  物件識別 / 登記エントリ（甲区・乙区） / リスクフラグ / 確認済・備考
  甲区: 所有者1人1行（共有名義も縦持ち）
  乙区: 抵当権等エントリ1件1行

Excel Power Query 接続:
  --batch 結果 → output/reports/touki_hist_all.csv を「テキスト/CSV」で接続
  --add 蓄積結果 → output/csv/ フォルダを「フォルダー」コネクタで結合
"""
import sys
import re
import csv
import argparse
from pathlib import Path
from datetime import datetime

# ── パス設定 ──────────────────────────────────────────
BASE_DIR = Path(__file__).parent
SCRIPTS  = BASE_DIR / 'scripts'
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(SCRIPTS / 'agents'))
sys.stdout.reconfigure(encoding='utf-8')

from touki_parser import extract_text, zen2han, detect_type, file_md5
from agents.tochi_agent    import TochiAgent
from agents.tatemono_agent import TatemonoAgent

DATA_ROOT = BASE_DIR / '登記簿公図データ'
OUT_BATCH = BASE_DIR / 'output' / 'reports' / 'touki_hist_all.csv'
OUT_INCR  = BASE_DIR / 'output' / 'csv'

RISK_YEAR = 1965  # 昭和40年：個人名義がこの年以前 → 相続未登記リスク
SEP = '；'        # touki_parser が使う複数値区切り

# ── CSV列定義 ──────────────────────────────────────────
COLUMNS = [
    # 物件識別
    '物件フォルダ', 'PDFファイル名', '不動産番号', '種別', '地目種類',
    '所在', '地番_家屋番号', '地積_床面積',
    # 登記エントリ
    '区分', '順位', '登記の目的', '受付年月日', '受付番号',
    # 所有者 / 関係者
    '所有者_関係者名', '住所', '持分', '持分数値',
    # 状態・名称変更
    '状態', '名称変更後', '元の氏名',
    # 乙区固有
    '債権額', '債務者', '共担目録番号',
    # 管理用
    'リスクフラグ', '確認済', '備考',
]

# ── ヘルパー ───────────────────────────────────────────
_HOUJIN_RE = re.compile(
    r'株式会社|有限会社|合同会社|合資会社|合名会社'
    r'|一般財団|公益財団|一般社団|公益社団'
    r'|学校法人|社会福祉法人|医療法人|宗教法人'
    r'|独立行政法人|地方公共団体|国$|県$|市$|町$|村$'
    r'|銀行|信用金庫|農業協同組合|農協|漁業協同'
)

def _is_houjin(name: str) -> bool:
    return bool(_HOUJIN_RE.search(name))


def _parse_year(date_str: str):
    """日付文字列から西暦年を返す（取得できなければ None）"""
    if not date_str:
        return None
    m = re.search(r'(19|20)(\d{2})', date_str)
    if m:
        return int(m.group(0))
    for era, base in [('明治', 1867), ('大正', 1911), ('昭和', 1925),
                      ('平成', 1988), ('令和', 2018)]:
        m = re.search(era + r'([0-9]+)', date_str)
        if m:
            return base + int(m.group(1))
    return None


def _risk_flag(name: str, date_str: str, status: str) -> str:
    """甲区個人名義の相続未登記リスクを判定して文字列を返す"""
    if status in ('抹消済み', '移転前', '変更', '参考'):
        return ''
    if _is_houjin(name):
        return ''
    year = _parse_year(date_str)
    if year is None:
        return '登記日不明'
    if year < RISK_YEAR:
        return '相続未登記リスク'
    if datetime.now().year - year >= 30:
        return '要確認（長期未変動）'
    return ''


def _parse_mochi(name_raw: str):
    """
    "田中太郎(4分の1)"  → (clean_name, "4分の1", 0.25)
    "持分2分の1 田中太郎" → (clean_name, "2分の1", 0.5)
    括弧なし・持分なし    → (name_raw,   "",       "")
    """
    # 括弧付き: "田中太郎(4分の1)"
    m = re.search(r'[(（]([^)）]*\d+分の\d+[^)）]*)[)）]', name_raw)
    if m:
        frac_str = m.group(1)
        clean    = re.sub(r'[(（][^)）]*[)）]', '', name_raw).strip()
        fm       = re.search(r'(\d+)分の(\d+)', frac_str)
        f_val    = round(int(fm.group(2)) / int(fm.group(1)), 6) if fm else ''
        return clean, frac_str, f_val
    # 「持分X分のY」プレフィックス形式
    m2 = re.search(r'持分\s*(\d+分の\d+)', name_raw)
    if m2:
        frac_str = m2.group(1)
        clean    = re.sub(r'持分\s*\d+分の\d+', '', name_raw).strip()
        fm       = re.search(r'(\d+)分の(\d+)', frac_str)
        f_val    = round(int(fm.group(2)) / int(fm.group(1)), 6) if fm else ''
        return clean or name_raw.strip(), frac_str, f_val
    return name_raw.strip(), '', ''


# ── PDF 1件処理 ────────────────────────────────────────
def _process_pdf(pdf_path: Path) -> list:
    rows = []
    try:
        fhash    = file_md5(pdf_path)
        raw      = extract_text(pdf_path)
        doc_type = detect_type(pdf_path.name, raw)
        agent    = TochiAgent() if doc_type == 'tochi' else TatemonoAgent()
        result   = agent.run(pdf_path, fhash)
    except Exception as e:
        print(f'[エラー] {pdf_path.name}: {e}')
        return rows

    if result is None:
        return rows

    record  = result['record']
    history = result['history']

    # 物件共通フィールド
    base = {
        '物件フォルダ':  pdf_path.parent.name,
        'PDFファイル名': pdf_path.name,
        '不動産番号':    record.get('不動産番号', ''),
        '種別':          '土地' if doc_type == 'tochi' else '建物',
        '地目種類':      record.get('地目', '') or record.get('種類', ''),
        '所在':          record.get('所在', ''),
        '地番_家屋番号': record.get('地番', '') or record.get('家屋番号', ''),
        '地積_床面積':   record.get('地積_m2', '') or record.get('床面積_m2', ''),
        '確認済':        '',
        '備考':          '',
    }

    # ── 甲区（所有権履歴）──
    for b in history['kouku']:
        owners_raw = b.get('所有者氏名', '')
        addrs_raw  = b.get('所有者住所', '')
        status     = b.get('状態', '')
        toroku_dt  = b.get('取得日', '') or b.get('受付年月日', '')

        owner_list = [o for o in owners_raw.split(SEP) if o.strip()]
        addr_list  = [a.strip() for a in addrs_raw.split(SEP)]

        if not owner_list:
            owner_list = ['']

        for i, owner_raw in enumerate(owner_list):
            name, mochi_str, mochi_f = _parse_mochi(owner_raw)
            addr = addr_list[i] if i < len(addr_list) else ''
            rows.append({
                **base,
                '区分':           '甲区',
                '順位':           b.get('順位', ''),
                '登記の目的':     b.get('登記の目的', ''),
                '受付年月日':     b.get('受付年月日', ''),
                '受付番号':       b.get('受付番号', ''),
                '所有者_関係者名': name,
                '住所':           addr,
                '持分':           mochi_str,
                '持分数値':       mochi_f,
                '状態':           status,
                '名称変更後':     b.get('名称変更後', ''),
                '元の氏名':       b.get('元の氏名', ''),
                '債権額':         '',
                '債務者':         '',
                '共担目録番号':   '',
                'リスクフラグ':   _risk_flag(name, toroku_dt, status),
            })

    # ── 乙区（抵当権・地上権等）──
    for e in history['otsuku']:
        rows.append({
            **base,
            '区分':           '乙区',
            '順位':           e.get('順位', ''),
            '登記の目的':     e.get('登記の目的', ''),
            '受付年月日':     e.get('受付日', ''),
            '受付番号':       e.get('受付番号', ''),
            '所有者_関係者名': e.get('抵当権者', ''),
            '住所':           '',
            '持分':           '',
            '持分数値':       '',
            '状態':           e.get('状態', ''),
            '名称変更後':     '',
            '元の氏名':       '',
            '債権額':         e.get('債権額', ''),
            '債務者':         e.get('債務者', ''),
            '共担目録番号':   e.get('共担目録番号', ''),
            'リスクフラグ':   '',
        })

    return rows


# ── CSV 書き出し ───────────────────────────────────────
def _write_csv(path: Path, rows: list):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, 'w', newline='', encoding='utf-8-sig') as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS, extrasaction='ignore')
        w.writeheader()
        w.writerows(rows)


def _find_pdfs(root: Path) -> list:
    return sorted(p for p in root.rglob('*') if p.suffix.lower() == '.pdf')


# ── モード処理 ─────────────────────────────────────────
def batch_mode():
    """全PDFを処理して touki_hist_all.csv を上書き出力"""
    pdfs = _find_pdfs(DATA_ROOT)
    print(f'対象PDF: {len(pdfs)}件\n')
    all_rows = []
    for pdf in pdfs:
        print(f'  {pdf.parent.name}/{pdf.name} ... ', end='', flush=True)
        rows = _process_pdf(pdf)
        all_rows.extend(rows)
        print(f'{len(rows)}行')
    _write_csv(OUT_BATCH, all_rows)
    print(f'\n完了 → {OUT_BATCH}  （計 {len(all_rows)} 行）')


def add_mode(target_str: str):
    """指定PDF / フォルダを処理して output/csv/ に蓄積"""
    target = Path(target_str)
    if target.is_file() and target.suffix.lower() == '.pdf':
        pdfs = [target]
    elif target.is_dir():
        pdfs = _find_pdfs(target)
    else:
        print(f'エラー: {target} が見つかりません（PDF または フォルダ を指定してください）')
        return

    OUT_INCR.mkdir(parents=True, exist_ok=True)
    for pdf in pdfs:
        print(f'  {pdf.parent.name}/{pdf.name} ... ', end='', flush=True)
        rows = _process_pdf(pdf)
        csv_name = f"{pdf.parent.name}_{pdf.stem}.csv"
        _write_csv(OUT_INCR / csv_name, rows)
        print(f'{len(rows)}行 → {csv_name}')
    print(f'\n完了 → {OUT_INCR}/')


# ── エントリポイント ──────────────────────────────────
if __name__ == '__main__':
    ap = argparse.ArgumentParser(
        description='登記簿PDF → 縦持ちCSV変換',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            '例:\n'
            '  python batch_to_csv.py --batch\n'
            '      → 全PDF処理・output/reports/touki_hist_all.csv を上書き\n'
            '  python batch_to_csv.py --add 登記簿公図データ\\湖東町\n'
            '      → 指定フォルダのPDFを output/csv\\ に追加\n'
            '  python batch_to_csv.py --add 登記簿公図データ\\湖東町\\xxx.pdf\n'
            '      → 1ファイルのみ処理\n'
        )
    )
    grp = ap.add_mutually_exclusive_group(required=True)
    grp.add_argument('--batch', action='store_true',
                     help='全PDFを一括処理→ touki_hist_all.csv（上書き）')
    grp.add_argument('--add', metavar='PATH',
                     help='PDF/フォルダ → output/csv/ に追加出力（蓄積）')
    args = ap.parse_args()

    if args.batch:
        batch_mode()
    else:
        add_mode(args.add)
