"""
公図PDF → JWC / DXF 直接変換
PyMuPDF (fitz) でベクターパスを直接抽出。スキャンPDFはOpenCVで輪郭検出。
"""
import re
import sys
import fitz
from pathlib import Path

PT_MM = 25.4 / 72.0   # PDF point → mm（1pt = 0.3528mm）
COMMON_SCALES = {100, 200, 250, 300, 500, 600, 1000, 2500}


# ─────────────────────────────────────────────
#  縮尺自動検出
# ─────────────────────────────────────────────
def _detect_scale(page) -> int:
    text = page.get_text()
    # 全角→半角
    text = text.translate(str.maketrans('０１２３４５６７８９：／', '0123456789:/'))
    m = re.search(r'1\s*[:\/]\s*(\d{2,4})', text)
    if m:
        val = int(m.group(1))
        if val in COMMON_SCALES:
            return val
        # 最近傍の標準縮尺
        return min(COMMON_SCALES, key=lambda x: abs(x - val))
    return 500  # 公図標準


# ─────────────────────────────────────────────
#  外枠判定（ページ面積の50%超を占める矩形系）
# ─────────────────────────────────────────────
def _is_frame(drawing, pw_pt, ph_pt) -> bool:
    r = drawing.get('rect')
    if r is None:
        return False
    ratio = (r.width * r.height) / max(pw_pt * ph_pt, 1)
    return ratio > 0.50


# ─────────────────────────────────────────────
#  ベクターPDF: drawing → 線分リスト
# ─────────────────────────────────────────────
def _drawing_to_lines(drawing, scale, ph_mm):
    """items を線分 (x1,y1,x2,y2) のリストに展開。Y軸を上向きに変換。"""
    lines = []
    first_pt = None   # サブパスの始点（closepath用）
    cur_pt   = None

    def mm(pt):
        return (pt.x * scale, ph_mm - pt.y * scale)

    for item in drawing['items']:
        t = item[0]

        if t == 'm':
            cur_pt   = mm(item[1])
            first_pt = cur_pt

        elif t == 'l':
            p1 = mm(item[1])
            p2 = mm(item[2])
            lines.append((p1[0], p1[1], p2[0], p2[1]))
            cur_pt = p2
            if first_pt is None:
                first_pt = p1

        elif t == 'c':           # ベジェ曲線 → 端点のみで近似
            p1 = mm(item[1])     # 始点
            p2 = mm(item[4])     # 終点
            lines.append((p1[0], p1[1], p2[0], p2[1]))
            cur_pt = p2
            if first_pt is None:
                first_pt = p1

        elif t == 're':
            r = item[1]
            c = [
                mm(fitz.Point(r.x0, r.y0)), mm(fitz.Point(r.x1, r.y0)),
                mm(fitz.Point(r.x1, r.y1)), mm(fitz.Point(r.x0, r.y1)),
                mm(fitz.Point(r.x0, r.y0)),
            ]
            for i in range(len(c) - 1):
                lines.append((c[i][0], c[i][1], c[i+1][0], c[i+1][1]))

        elif t == 'qu':
            q = item[1]
            c = [mm(q.ul), mm(q.ur), mm(q.lr), mm(q.ll), mm(q.ul)]
            for i in range(len(c) - 1):
                lines.append((c[i][0], c[i][1], c[i+1][0], c[i+1][1]))

        elif t == 'h':           # closepath
            if cur_pt and first_pt:
                dx = abs(cur_pt[0] - first_pt[0])
                dy = abs(cur_pt[1] - first_pt[1])
                if dx > 0.01 or dy > 0.01:
                    lines.append((cur_pt[0], cur_pt[1], first_pt[0], first_pt[1]))
            cur_pt   = None
            first_pt = None

    return lines


# ─────────────────────────────────────────────
#  ラスターPDF フォールバック（OpenCV輪郭検出）
# ─────────────────────────────────────────────
def _raster_extract(pdf_path, scale_denom, dpi=200):
    try:
        import cv2
        import numpy as np
    except ImportError:
        return [], [], 0, 0

    pdf  = fitz.open(str(pdf_path))
    page = pdf[0]
    mat  = fitz.Matrix(dpi / 72, dpi / 72)
    pix  = page.get_pixmap(matrix=mat)
    pdf.close()

    img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
    gray = (img[:, :, 0] if pix.n == 1
            else __import__('cv2').cvtColor(img,
                __import__('cv2').COLOR_RGBA2GRAY if pix.n == 4
                else __import__('cv2').COLOR_RGB2GRAY))

    _, binary = cv2.threshold(gray, 0, 255,
                              cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (2, 2))
    binary = cv2.morphologyEx(binary, cv2.MORPH_OPEN, kernel, iterations=1)

    contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL,
                                   cv2.CHAIN_APPROX_SIMPLE)

    px_scale = PT_MM * scale_denom * (72 / dpi)   # px → 実寸mm
    ph_mm    = pix.height * px_scale
    pw_mm    = pix.width  * px_scale

    border_lines, frame_lines = [], []
    for cnt in contours:
        area = cv2.contourArea(cnt)
        if area < 100:
            continue
        eps   = 0.005 * cv2.arcLength(cnt, True)
        approx = cv2.approxPolyDP(cnt, eps, True)
        if len(approx) < 2:
            continue

        pts      = [(p[0][0] * px_scale, ph_mm - p[0][1] * px_scale)
                    for p in approx]
        x, y, w, h = cv2.boundingRect(cnt)
        is_frame = (w * h) / max(pix.width * pix.height, 1) > 0.50

        segs = [(pts[i][0], pts[i][1], pts[i+1][0], pts[i+1][1])
                for i in range(len(pts) - 1)]
        if len(pts) > 2:
            segs.append((pts[-1][0], pts[-1][1], pts[0][0], pts[0][1]))

        (frame_lines if is_frame else border_lines).extend(segs)

    return border_lines, frame_lines, pw_mm, ph_mm


# ─────────────────────────────────────────────
#  メイン変換
# ─────────────────────────────────────────────
def convert(pdf_path: Path, scale_denom: int = None, fmt: str = 'jwc') -> tuple:
    """
    Returns: (output_text: str, scale_denom: int, n_lines: int, n_texts: int)
    """
    pdf  = fitz.open(str(pdf_path))
    page = pdf[0]

    if scale_denom is None:
        scale_denom = _detect_scale(page)

    pw_pt = page.rect.width
    ph_pt = page.rect.height
    scale = PT_MM * scale_denom   # pt → 実寸mm
    ph_mm = ph_pt * scale
    pw_mm = pw_pt * scale

    # ── テキスト抽出（地番）─────────────────────
    text_items = []
    y_bot = ph_mm * 0.27   # 下27%（表）除外
    y_top = ph_mm * 0.93   # 上 7%（ヘッダー）除外

    try:
        for block in page.get_text("dict")["blocks"]:
            if block["type"] != 0:
                continue
            for line in block["lines"]:
                for span in line["spans"]:
                    txt = span["text"].strip()
                    if not txt:
                        continue
                    ox, oy = span["origin"]
                    x  = ox * scale
                    y  = ph_mm - oy * scale
                    h  = max(1.0, span["size"] * scale)
                    if y_bot <= y <= y_top:
                        text_items.append({"t": txt, "x": x, "y": y, "h": h})
    except Exception:
        pass

    # ── 図形抽出（ベクター）──────────────────────
    drawings = page.get_drawings()
    pdf.close()

    border_lines, frame_lines = [], []

    if drawings:
        for d in drawings:
            segs = _drawing_to_lines(d, scale, ph_mm)
            if not segs:
                continue
            if _is_frame(d, pw_pt, ph_pt):
                frame_lines.extend(segs)
            else:
                border_lines.extend(segs)
        print(f"  ベクター: 境界線 {len(border_lines)} 線分 / 外枠 {len(frame_lines)} 線分")
    else:
        print("  ラスターPDF: OpenCV輪郭検出にフォールバック...")
        border_lines, frame_lines, pw_mm, ph_mm = _raster_extract(
            pdf_path, scale_denom)
        print(f"  ラスター: 境界線 {len(border_lines)} 線分 / 外枠 {len(frame_lines)} 線分")

    n_lines = len(border_lines) + len(frame_lines)
    n_texts = len(text_items)

    if fmt == 'dxf':
        text = _to_dxf(border_lines, frame_lines, text_items, pw_mm, ph_mm)
    else:
        text = _to_jwc(border_lines, frame_lines, text_items, pw_mm, ph_mm, scale_denom)

    return text, scale_denom, n_lines, n_texts


# ─────────────────────────────────────────────
#  JWC 出力
# ─────────────────────────────────────────────
def _paper_code(pw_mm, ph_mm, scale):
    wp = pw_mm / scale
    hp = ph_mm / scale
    if wp <= 297 and hp <= 210: return '12 0'
    if wp <= 420 and hp <= 297: return '16 0'
    if wp <= 594 and hp <= 420: return '21 0'
    return '22 0'


def _to_jwc(border, frame, texts, pw_mm, ph_mm, scale):
    L = ['# Jw_cad Data', 'HST']
    L.append('P' + _paper_code(pw_mm, ph_mm, scale))
    L.append(f'S {scale}')
    L.append('ST 1 1 1 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0')
    L.append('L 0 2 0')   # 境界線 黄
    L.append('L 1 3 0')   # 地番  緑
    L.append('L 2 7 0')   # 外枠  白
    L.append('HED')

    if border:
        L.append('WL 0')
        for x1, y1, x2, y2 in border:
            L.append(f'l {x1:.3f} {y1:.3f} {x2:.3f} {y2:.3f}')

    if frame:
        L.append('WL 2')
        for x1, y1, x2, y2 in frame:
            L.append(f'l {x1:.3f} {y1:.3f} {x2:.3f} {y2:.3f}')

    if texts:
        L.append('WL 1')
        for t in texts:
            L.append(f"TJ {t['x']:.3f} {t['y']:.3f} 0 {t['h']:.3f} 0 0 0 0 0 0")
            L.append(t['t'])

    return '\n'.join(L)


# ─────────────────────────────────────────────
#  DXF 出力（JWCAD互換 R12/AC1009）
# ─────────────────────────────────────────────
def _to_dxf(border, frame, texts, pw_mm, ph_mm):
    L = []
    w = lambda *a: L.extend(str(x) for x in a)

    w('  0','SECTION','  2','HEADER')
    w('  9','$ACADVER','  1','AC1009')
    w('  9','$EXTMIN',' 10','0.000',' 20','0.000',' 30','0.000')
    w('  9','$EXTMAX',' 10',f'{pw_mm:.3f}',' 20',f'{ph_mm:.3f}',' 30','0.000')
    w('  0','ENDSEC')

    w('  0','SECTION','  2','TABLES')
    w('  0','TABLE','  2','LTYPE',' 70','1')
    w('  0','LTYPE','  2','CONTINUOUS',' 70','0','  3','Solid line',
      ' 72','65',' 73','0',' 40','0.0')
    w('  0','ENDTAB')
    w('  0','TABLE','  2','LAYER',' 70','3')
    for lname, col in [('kouzu_border','2'),('kouzu_frame','7'),('kouzu_label','3')]:
        w('  0','LAYER','  2',lname,' 70','0',' 62',col,'  6','CONTINUOUS')
    w('  0','ENDTAB')
    w('  0','ENDSEC')

    w('  0','SECTION','  2','BLOCKS','  0','ENDSEC')
    w('  0','SECTION','  2','ENTITIES')

    for segs, lyr in [(border, 'kouzu_border'), (frame, 'kouzu_frame')]:
        for x1, y1, x2, y2 in segs:
            w('  0','LINE','  8',lyr,'  6','CONTINUOUS')
            w(' 10',f'{x1:.3f}',' 20',f'{y1:.3f}',' 30','0.000')
            w(' 11',f'{x2:.3f}',' 21',f'{y2:.3f}',' 31','0.000')

    for t in texts:
        w('  0','TEXT','  8','kouzu_label','  6','CONTINUOUS')
        w(' 10',f"{t['x']:.3f}",' 20',f"{t['y']:.3f}",' 30','0.000')
        w(' 40',f"{t['h']:.3f}",'  1',t['t'])

    w('  0','ENDSEC','  0','EOF')
    return '\r\n'.join(L)


# ─────────────────────────────────────────────
#  CLI エントリポイント
# ─────────────────────────────────────────────
def main():
    import argparse
    ap = argparse.ArgumentParser(
        description='公図PDF → JWC/DXF 直接変換 (PyMuPDF使用)',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用例:
  python kouzu_to_jwc.py 公図.pdf
  python kouzu_to_jwc.py 公図.pdf --scale 500
  python kouzu_to_jwc.py 公図.pdf --format dxf -o 出力.dxf
  python kouzu_to_jwc.py                 ← 公図フォルダを一括処理
        """
    )
    ap.add_argument('pdf', nargs='?', help='公図PDFパス（省略時: 登記簿公図データ/公図/ を一括処理）')
    ap.add_argument('--scale', type=int, default=None,
                    help='縮尺分母（省略時: PDFから自動検出、見つからなければ500）')
    ap.add_argument('--format', choices=['jwc', 'dxf'], default='jwc',
                    help='出力形式 (default: jwc)')
    ap.add_argument('-o', '--output',
                    help='出力先ファイル（省略時: 入力と同名・拡張子のみ変更）')
    args = ap.parse_args()

    script_dir = Path(__file__).resolve().parent
    base_dir   = next(
        (p for p in [script_dir.parent, script_dir.parent.parent]
         if (p / '登記簿公図データ').exists()),
        script_dir.parent,
    )

    if args.pdf:
        targets = [Path(args.pdf)]
    else:
        kouzu_dir = base_dir / '登記簿公図データ' / '公図'
        if not kouzu_dir.exists():
            print(f"フォルダが見つかりません: {kouzu_dir}")
            sys.exit(1)
        targets = list(kouzu_dir.glob('**/*.PDF')) + list(kouzu_dir.glob('**/*.pdf'))
        if not targets:
            print(f"公図PDFが見つかりません: {kouzu_dir}")
            sys.exit(1)
        print(f"{len(targets)} 件の公図PDFを処理します\n")

    ok, ng = 0, 0
    for pdf_path in targets:
        pdf_path = Path(pdf_path)
        print(f"処理中: {pdf_path.name}")
        try:
            output_text, scale_used, n_lines, n_texts = convert(
                pdf_path, args.scale, args.format)

            if args.output and len(targets) == 1:
                out_path = Path(args.output)
            else:
                out_path = pdf_path.with_suffix('.' + args.format)

            enc = 'cp932' if args.format == 'jwc' else 'utf-8'
            out_path.write_text(output_text, encoding=enc, errors='replace')

            print(f"  → 完了: {out_path.name}")
            print(f"     縮尺 1:{scale_used} / {n_lines} 線分 / {n_texts} テキスト\n")
            ok += 1

        except Exception as e:
            import traceback
            print(f"  [ERROR] {e}")
            traceback.print_exc()
            ng += 1

    print(f"完了: 成功 {ok} 件 / 失敗 {ng} 件")


if __name__ == '__main__':
    main()
