"""
公図PDF → GeoJSON 変換スクリプト
- ベクターPDF: パスを直接GeoJSONに変換
- ラスターPDF（スキャン）: OpenCVで境界線を検出してGeoJSON化
- 出力座標: PDFピクセル座標（地理座標変換は--gcpオプションで別途可能）
"""
import fitz
import cv2
import numpy as np
import json
import argparse
from pathlib import Path
from datetime import datetime

_SCRIPT_DIR = Path(__file__).resolve().parent
_BASE_DIR = next(
    (p for p in [_SCRIPT_DIR.parent, _SCRIPT_DIR.parent.parent, _SCRIPT_DIR.parent.parent.parent]
     if (p / "登記簿公図データ").exists()),
    _SCRIPT_DIR.parent,
)
OUTPUT_DIR = _BASE_DIR / "output_geojson"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


# ---- ベクターPDF処理 ----

def vector_to_geojson(pdf_path: Path) -> dict:
    """
    1つのdrawing内の独立したitem（line/curve/rect/quad）を単一のcoordsに
    連結すると、無関係な線分の間に存在しない接続線が生まれてしまう
    （旧実装のバグ）。item単位で個別のFeatureとして出力する。
    """
    pdf = fitz.open(str(pdf_path))
    features = []
    for page_num, page in enumerate(pdf):
        drawings = page.get_drawings()
        for i, d in enumerate(drawings):
            props = {
                "page": page_num + 1,
                "index": i,
                "color": d.get("color"),
                "fill": d.get("fill"),
                "width": d.get("width"),
            }
            for item in d["items"]:
                coords = None
                if item[0] == "l":       # line
                    coords = [list(item[1]), list(item[2])]
                elif item[0] == "re":    # rectangle
                    r = item[1]
                    coords = [
                        [r.x0, r.y0], [r.x1, r.y0],
                        [r.x1, r.y1], [r.x0, r.y1], [r.x0, r.y0]
                    ]
                elif item[0] == "qu":    # quad
                    q = item[1]
                    coords = [list(pt) for pt in [q.ul, q.ur, q.lr, q.ll, q.ul]]
                elif item[0] == "c":     # curve (始点・終点の2点で近似)
                    coords = [list(item[1]), list(item[4])]

                if coords and len(coords) >= 2:
                    geom_type = "Polygon" if coords[0] == coords[-1] else "LineString"
                    coords_val = [coords] if geom_type == "Polygon" else coords
                    features.append({
                        "type": "Feature",
                        "geometry": {"type": geom_type, "coordinates": coords_val},
                        "properties": dict(props),
                    })
    pdf.close()
    return {
        "type": "FeatureCollection",
        "features": features,
        "_meta": {
            "source": pdf_path.name,
            "coordinate_system": "pdf_points (origin: top-left)",
            "feature_count": len(features),
            "generated": datetime.now().isoformat(timespec="seconds"),
        }
    }


# ---- ラスターPDF処理 ----

def raster_to_geojson(pdf_path: Path, dpi: int = 200,
                      min_area: int = 1000, epsilon_ratio: float = 0.005) -> dict:
    pdf = fitz.open(str(pdf_path))
    page = pdf[0]
    pix = page.get_pixmap(dpi=dpi)
    img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
    pdf.close()

    # グレースケール変換
    if img.shape[2] == 4:
        gray = cv2.cvtColor(img, cv2.COLOR_RGBA2GRAY)
    elif img.shape[2] == 3:
        gray = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)
    else:
        gray = img[:, :, 0]

    # 二値化（Otsu法）
    _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)

    # ノイズ除去（細い点状ノイズ）
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (2, 2))
    binary = cv2.morphologyEx(binary, cv2.MORPH_OPEN, kernel, iterations=1)

    # 輪郭検出（外側・内側含む）
    contours, hierarchy = cv2.findContours(binary, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE)

    features = []
    scale = 72.0 / dpi  # ピクセル→PDFポイント変換係数

    for i, cnt in enumerate(contours):
        area = cv2.contourArea(cnt)
        if area < min_area:
            continue

        # 輪郭を近似（折れ線を簡略化）
        epsilon = epsilon_ratio * cv2.arcLength(cnt, True)
        approx = cv2.approxPolyDP(cnt, epsilon, True)

        if len(approx) < 3:
            continue

        # ピクセル座標 → PDFポイント座標
        pts = [[float(p[0][0] * scale), float(p[0][1] * scale)] for p in approx]
        pts.append(pts[0])  # ポリゴンを閉じる

        # バウンディングボックス
        x, y, w, h = cv2.boundingRect(cnt)
        cx = (x + w / 2) * scale
        cy = (y + h / 2) * scale

        # 親コンター判定（穴かどうか）
        is_hole = bool((hierarchy[0][i][3] >= 0) if hierarchy is not None else False)

        features.append({
            "type": "Feature",
            "geometry": {
                "type": "Polygon",
                "coordinates": [pts]
            },
            "properties": {
                "id": i,
                "area_px": round(area, 1),
                "is_hole": is_hole,
                "center_x": round(cx, 2),
                "center_y": round(cy, 2),
                "bbox": [round(x * scale, 2), round(y * scale, 2),
                         round((x + w) * scale, 2), round((y + h) * scale, 2)],
            }
        })

    features.sort(key=lambda f: f["properties"]["area_px"], reverse=True)

    return {
        "type": "FeatureCollection",
        "features": features,
        "_meta": {
            "source": pdf_path.name,
            "dpi": dpi,
            "img_size": [pix.width, pix.height],
            "coordinate_system": "pdf_points (origin: top-left)",
            "feature_count": len(features),
            "generated": datetime.now().isoformat(timespec="seconds"),
        }
    }


# ---- 地理参照（GCP変換） ----

def apply_gcp(geojson: dict, gcps: list) -> dict:
    """
    GCP（地上基準点）を使って座標変換。
    gcps: [{"px": [x, y], "ll": [lon, lat]}, ...]  最低3点
    変換後はWGS84座標（EPSG:4326）になる。
    """
    if len(gcps) < 3:
        print("[WARN] GCPは最低3点必要です。スキップ。")
        return geojson

    src_pts = np.float32([[g["px"][0], g["px"][1]] for g in gcps])
    dst_pts = np.float32([[g["ll"][0], g["ll"][1]] for g in gcps])

    if len(gcps) >= 4:
        M, _ = cv2.findHomography(src_pts, dst_pts)
    else:
        M = cv2.getAffineTransform(src_pts[:3], dst_pts[:3])
        M = np.vstack([M, [0, 0, 1]])

    def transform(x, y):
        pt = M @ np.array([x, y, 1.0])
        return [round(pt[0] / pt[2], 8), round(pt[1] / pt[2], 8)]

    for feat in geojson["features"]:
        geom = feat["geometry"]
        if geom["type"] == "LineString":
            # LineStringはPolygonと違いring(入れ子)構造ではなく点の平坦なリスト
            geom["coordinates"] = [transform(x, y) for x, y in geom["coordinates"]]
        elif geom["type"] == "Polygon":
            geom["coordinates"] = [
                [transform(x, y) for x, y in ring] for ring in geom["coordinates"]
            ]

    # vector_to_geojson()の出力にも_metaを付与しているが、念のため欠落時も落ちないようにする
    geojson.setdefault("_meta", {})
    geojson["_meta"]["coordinate_system"] = "WGS84 (EPSG:4326)"
    geojson["_meta"]["gcps"] = gcps
    return geojson


# ---- エントリポイント ----

def main():
    parser = argparse.ArgumentParser(description="公図PDF → GeoJSON 変換")
    parser.add_argument("pdf", nargs="?", help="対象PDFパス（省略時: 公図/フォルダ内を一括処理）")
    parser.add_argument("--dpi", type=int, default=200, help="ラスター化解像度 (default: 200)")
    parser.add_argument("--min-area", type=int, default=500,
                        help="最小面積（ピクセル^2）。ノイズ除去（default: 500）")
    parser.add_argument("--epsilon", type=float, default=0.005,
                        help="輪郭近似精度 0.001（精細）〜0.02（粗め）(default: 0.005)")
    parser.add_argument("--gcp", nargs="+", metavar="FILE",
                        help="GCPファイル（JSON）を指定して地理座標に変換")
    args = parser.parse_args()

    gcps = None
    if args.gcp:
        with open(args.gcp[0], encoding="utf-8") as f:
            gcps = json.load(f)

    base = _BASE_DIR

    if args.pdf:
        targets = [Path(args.pdf)]
    else:
        kouzu_dir = base / "登記簿公図データ" / "公図"
        targets = list(kouzu_dir.glob("**/*.PDF"))
        targets += list(kouzu_dir.glob("**/*.pdf"))
        print(f"{len(targets)} 件の公図PDFを処理します")

    ok, ng = 0, 0
    for pdf_path in targets:
        print(f"\n処理中: {pdf_path.name}")
        try:
            pdf = fitz.open(str(pdf_path))
            page = pdf[0]
            drawings = page.get_drawings()
            is_vector = len(drawings) > 0
            pdf.close()

            if is_vector:
                print("  → ベクターPDF: パスを直接変換")
                result = vector_to_geojson(pdf_path)
            else:
                print("  → ラスターPDF: 画像解析で境界検出")
                result = raster_to_geojson(
                    pdf_path, dpi=args.dpi,
                    min_area=args.min_area, epsilon_ratio=args.epsilon
                )

            if gcps:
                result = apply_gcp(result, gcps)

            out_path = OUTPUT_DIR / (pdf_path.stem + ".geojson")
            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(result, f, ensure_ascii=False, indent=2)

            n = len(result["features"])
            print(f"  → 出力: {out_path} ({n} フィーチャー)")
            ok += 1
        except Exception as e:
            print(f"  [ERROR] {e}")
            ng += 1

    print(f"\n完了: 成功 {ok} 件 / 失敗 {ng} 件")


if __name__ == "__main__":
    main()
