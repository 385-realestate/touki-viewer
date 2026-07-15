# -*- coding: utf-8 -*-
"""
touki_viewer アイコン生成
建物（正面）＋地図ピン　青系カラー
"""
from PIL import Image, ImageDraw
import math

def draw_icon(size: int) -> Image.Image:
    s = size
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    # --- カラー定義 ---
    BG       = (18,  85, 184, 255)   # #1255B8 アクセントブルー
    BLDG     = (255, 255, 255, 255)  # 建物：白
    BLDG_S   = (180, 210, 255, 255)  # 建物影・窓枠
    WIN      = (18,  85, 184, 255)   # 窓：青（背景色）
    PIN_OUT  = (255, 255, 255, 255)  # ピン外縁：白
    PIN_IN   = (255,  90,  50, 255)  # ピン内側：オレンジレッド（差し色）

    # --- 背景：丸角四角形 ---
    r = s // 7
    d.rounded_rectangle([0, 0, s-1, s-1], radius=r, fill=BG)

    # --- 建物（左下 60% 幅） ---
    bx1 = int(s * 0.10)
    bx2 = int(s * 0.62)
    by1 = int(s * 0.38)
    by2 = int(s * 0.86)
    # 本体
    d.rectangle([bx1, by1, bx2, by2], fill=BLDG)
    # 屋根（台形風）
    roof_pts = [
        (bx1 - int(s*0.02), by1),
        (bx2 + int(s*0.02), by1),
        (bx2 - int(s*0.04), int(s*0.28)),
        (bx1 + int(s*0.04), int(s*0.28)),
    ]
    d.polygon(roof_pts, fill=BLDG)
    # 屋根ライン（影）
    d.polygon(roof_pts, outline=BLDG_S, width=max(1, s//64))

    # 窓（3×2 グリッド）
    cols, rows = 3, 2
    wpad_x = int(s * 0.04)
    wpad_y = int(s * 0.04)
    w_area_w = (bx2 - bx1) - wpad_x * 2
    w_area_h = (by2 - by1) - wpad_y * 2
    ww = w_area_w // (cols * 2 - 1)
    wh = w_area_h // (rows * 2 - 1)
    ww = max(ww, 1); wh = max(wh, 1)
    for row in range(rows):
        for col in range(cols):
            wx1 = bx1 + wpad_x + col * (ww * 2)
            wy1 = by1 + wpad_y + row * (wh * 2)
            wx2 = wx1 + ww
            wy2 = wy1 + wh
            d.rectangle([wx1, wy1, wx2, wy2], fill=WIN, outline=BLDG_S, width=max(1, s//128))

    # 扉
    door_w = int(s * 0.10)
    door_h = int(s * 0.14)
    door_x = (bx1 + bx2) // 2 - door_w // 2
    door_y = by2 - door_h
    d.rectangle([door_x, door_y, door_x + door_w, by2], fill=BLDG_S)

    # --- 地図ピン（右上） ---
    px_c  = int(s * 0.74)   # ピン中心X
    py_t  = int(s * 0.08)   # ピン上端Y
    pr    = int(s * 0.17)   # 円半径
    py_c  = py_t + pr        # 円中心Y
    # 外縁（白）
    pw = max(2, s // 32)
    d.ellipse([px_c-pr-pw, py_c-pr-pw, px_c+pr+pw, py_c+pr+pw], fill=PIN_OUT)
    # 内側（オレンジレッド）
    d.ellipse([px_c-pr, py_c-pr, px_c+pr, py_c+pr], fill=PIN_IN)
    # ピン先端（三角形）
    tip_y = py_c + pr + int(s * 0.14)
    tri = [
        (px_c - int(s*0.09), py_c + int(s*0.08)),
        (px_c + int(s*0.09), py_c + int(s*0.08)),
        (px_c, tip_y),
    ]
    d.polygon(tri, fill=PIN_IN)
    d.polygon(tri, outline=PIN_OUT, width=max(1, s//64))
    # ピン中心ドット（白）
    dot_r = max(2, pr // 3)
    d.ellipse([px_c-dot_r, py_c-dot_r, px_c+dot_r, py_c+dot_r], fill=PIN_OUT)

    return img


if __name__ == "__main__":
    from pathlib import Path
    out = Path(__file__).parent / "touki_viewer.ico"
    sizes = [16, 24, 32, 48, 64, 128, 256]
    frames = [draw_icon(s) for s in sizes]
    frames[0].save(
        str(out),
        format="ICO",
        append_images=frames[1:],
        sizes=[(s, s) for s in sizes],
    )
    print(f"アイコン作成完了: {out}")

    # プレビュー用PNG（256px）
    png_out = Path(__file__).parent / "touki_viewer_icon_preview.png"
    draw_icon(256).save(str(png_out))
    print(f"プレビューPNG: {png_out}")
