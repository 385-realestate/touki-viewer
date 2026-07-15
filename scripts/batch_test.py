"""
登記簿パーサー 全件バッチテスト
- 登記簿/ 以下の全PDFをパース
- 問題検出: 空フィールド・持分合計不一致・文字化け
"""
import sys, re, json
from pathlib import Path
from fractions import Fraction
from datetime import datetime

BASE = Path(__file__).parent.parent
sys.path.insert(0, str(Path(__file__).parent))

from agents.tochi_agent import TochiAgent
from agents.tatemono_agent import TatemonoAgent
from touki_parser import extract_text, zen2han, detect_type, file_md5

INPUT_DIR = BASE / "登記簿公図データ" / "登記簿"
REPORT_PATH = BASE / "output_csv" / f"batch_test_{datetime.now().strftime('%Y%m%d_%H%M')}.json"
REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)

_FRAC_RE = re.compile(r'([0-9]+)分の([0-9]+)')


def check_share_total(owner_str):
    if not owner_str or '；' not in owner_str:
        return True, ""
    parts = [s.strip() for s in owner_str.split('；') if s.strip()]
    fracs = []
    for p in parts:
        m = _FRAC_RE.search(p)
        if m:
            fracs.append(Fraction(int(m.group(2)), int(m.group(1))))
    if not fracs:
        return True, ""
    total = sum(fracs)
    if total == Fraction(1):
        return True, ""
    return False, f"合計={float(total):.4f}({total}) [{owner_str[:60]}]"


def check_record(record, doc_type):
    issues = []
    # 必須フィールド空
    for f in (['所在', '所有者氏名', '地番'] if doc_type == 'tochi'
               else ['所在', '所有者氏名', '家屋番号']):
        if not record.get(f, '').strip():
            issues.append({'type': 'empty_field', 'field': f, 'value': ''})
    # 持分合計
    ok, detail = check_share_total(record.get('所有者氏名', ''))
    if not ok:
        issues.append({'type': 'share_mismatch', 'field': '所有者氏名', 'value': detail})
    # フラグ整合
    owner = record.get('所有者氏名', '')
    flag  = record.get('現在の所有者', '')
    if owner and flag != 'O' and flag != '○':
        issues.append({'type': 'flag_mismatch', 'field': '現在の所有者',
                       'value': f'owner={owner[:30]} flag={flag!r}'})
    if not owner and flag == '○':
        issues.append({'type': 'flag_mismatch', 'field': '現在の所有者',
                       'value': '所有者空なのにflag=○'})
    return issues


def run():
    all_pdfs = sorted(INPUT_DIR.rglob('*.[Pp][Dd][Ff]'))
    total = len(all_pdfs)
    print(f"対象: {total} 件")
    print("=" * 60)

    results = []
    ok_count = ng_count = fail_count = 0
    issue_summary = {}

    for i, pdf in enumerate(all_pdfs, 1):
        try:
            text = extract_text(pdf)
            t = zen2han(text)
            doc_type = detect_type(pdf.name, t)
            if doc_type == 'other':
                print(f"[{i:4d}/{total}] SKIP (法人登記簿等): {pdf.name[:60]}")
                continue
            fhash = file_md5(pdf)
            agent = TochiAgent() if doc_type == 'tochi' else TatemonoAgent()
            result = agent.run(pdf, fhash)
            if result is None:
                fail_count += 1
                results.append({'file': pdf.name, 'status': 'parse_failed', 'issues': []})
                print(f"[{i:4d}/{total}] FAIL: {pdf.name[:65]}")
                continue
            record = result['record']
            issues = check_record(record, doc_type)
            entry = {'file': pdf.name, 'status': 'ng' if issues else 'ok',
                     'doc_type': doc_type,
                     'owner': record.get('所有者氏名', ''),
                     'location': record.get('所在', ''),
                     'issues': issues}
            results.append(entry)
            if issues:
                ng_count += 1
                for iss in issues:
                    issue_summary[iss['type']] = issue_summary.get(iss['type'], 0) + 1
                print(f"[{i:4d}/{total}] NG  {pdf.name[:60]}")
                for iss in issues:
                    print(f"        [{iss['type']}] {iss['field']}: {iss['value'][:70]}")
            else:
                ok_count += 1
                if i % 100 == 0 or i == total:
                    print(f"[{i:4d}/{total}] OK... {ok_count}件正常")
        except Exception as e:
            fail_count += 1
            results.append({'file': pdf.name, 'status': 'error', 'error': str(e), 'issues': []})
            print(f"[{i:4d}/{total}] ERR: {pdf.name[:55]} -- {e}")

    print()
    print("=" * 60)
    print(f"結果: 正常={ok_count} / NG={ng_count} / 失敗={fail_count} / 計={total}")
    print("問題種別:")
    for k, v in sorted(issue_summary.items(), key=lambda x: -x[1]):
        print(f"  {k}: {v}件")

    with open(REPORT_PATH, 'w', encoding='utf-8') as f:
        json.dump({'summary': {'ok': ok_count, 'ng': ng_count, 'fail': fail_count,
                               'total': total, 'issue_types': issue_summary},
                   'results': results}, f, ensure_ascii=False, indent=2)
    print(f"\nレポート: {REPORT_PATH}")
    return results

if __name__ == '__main__':
    run()
