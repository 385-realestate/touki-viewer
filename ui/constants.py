"""
UI共通定数（app.py と SpotResultWindow で共有）
"""

# ---- カラーパレット（登記情報提供サービス準拠） ----
C: dict = {
    # 基本背景
    "bg":         "#EEF0F4",
    "surface":    "#FFFFFF",
    "surface2":   "#F4F6F9",
    "border":     "#C8CDD8",

    # テキスト
    "text":       "#1C1F2E",
    "subtext":    "#4D5568",
    "muted":      "#8E97AA",

    # ヘッダー（濃紺）
    "header_bg":  "#0D2461",
    "header_text":"#FFFFFF",

    # アクセント（サイトの青）
    "accent":     "#1255B8",
    "accent_h":   "#1A6FD8",

    # 緑（アクティブタブ・成功）
    "green":      "#2B6B2B",
    "green_h":    "#3A8A3A",
    "success":    "#2E7D32",
    "success_bg": "#E8F5E9",

    # 警告・エラー
    "warning":    "#E65100",
    "error":      "#C62828",
    "error_bg":   "#FFEBEE",

    # テーブル行
    "row_even":   "#FFFFFF",
    "row_odd":    "#F4F6F9",
    "row_sel":    "#BBDEFB",

    # ステップバー（グレー）
    "step_bg":    "#4A5060",
    "step_text":  "#FFFFFF",
    "step_active":"#1C2E5A",
}

TAB_IMPORT  = "📂  PDF取り込み"
TAB_PROCESS = "▶   解析"

SEP = "；"   # パーサーと同じ区切り文字
