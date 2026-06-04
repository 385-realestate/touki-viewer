# -*- coding: utf-8 -*-
"""
登記簿データ分析用 Excel テンプレート生成スクリプト
Power Query（CSVフォルダ結合）+ ピボットテーブル付き
"""
import os, sys, time
from pathlib import Path

BASE = Path(__file__).parent
OUT  = BASE / "登記簿分析.xlsx"

COLUMNS = [
    '物件フォルダ','PDFファイル名','不動産番号','種別','地目種類',
    '所在','地番_家屋番号','地積_床面積',
    '区分','順位','登記の目的','受付年月日','受付番号',
    '所有者_関係者名','住所','持分','持分数値',
    '状態','名称変更後','元の氏名',
    '債権額','債務者','共担目録番号',
    'リスクフラグ','確認済','備考',
]

# Power Query M コード（output_csv フォルダを結合）
M_CODE = r"""let
    FolderPath = Text.From(Excel.CurrentWorkbook(){[Name="CSVフォルダパス"]}[Content]{0}[パス]),
    Source = Folder.Files(FolderPath),
    FilterCSV = Table.SelectRows(Source, each Text.EndsWith([Name], ".csv")),
    LoadEach = Table.AddColumn(FilterCSV, "Data", each
        Table.PromoteHeaders(
            Csv.Document([Content],[Delimiter=",",Encoding=65001,QuoteStyle=QuoteStyle.None]),
            [PromoteAllScalars=true]
        )
    ),
    OnlyData = Table.SelectColumns(LoadEach, {"Data"}),
    Combined = Table.Combine(OnlyData[Data]),
    TypedCols = Table.TransformColumnTypes(Combined,{
        {"持分数値", type number},
        {"受付年月日", type text},
        {"リスクフラグ", type text}
    })
in
    TypedCols"""

try:
    import win32com.client as win32
except ImportError:
    print("pywin32 が必要です: pip install pywin32")
    sys.exit(1)

print("Excel を起動中...")
xl = win32.Dispatch("Excel.Application")
xl.Visible = False
xl.DisplayAlerts = False

wb = xl.Workbooks.Add()

# ── シート構成 ──────────────────────────────────────────

# Sheet1: 登記データ（Power Query が書き込む先）
ws_data = wb.Worksheets(1)
ws_data.Name = "登記データ"
for i, col in enumerate(COLUMNS, 1):
    ws_data.Cells(1, i).Value = col
# ヘッダー書式
hdr_range = ws_data.Range(ws_data.Cells(1,1), ws_data.Cells(1, len(COLUMNS)))
hdr_range.Font.Bold = True
hdr_range.Interior.Color = 0x1F4E79  # 濃紺
hdr_range.Font.Color = 0xFFFFFF
ws_data.Rows(1).RowHeight = 20
ws_data.Columns.AutoFit()

# Sheet2: ピボット（後で設定）
ws_pivot = wb.Worksheets.Add(After=wb.Worksheets(wb.Worksheets.Count))
ws_pivot.Name = "ピボット"

# Sheet3: 設定
ws_cfg = wb.Worksheets.Add(After=wb.Worksheets(wb.Worksheets.Count))
ws_cfg.Name = "設定"
ws_cfg.Cells(1,1).Value = "CSVフォルダ パス（変更可）"
ws_cfg.Cells(1,1).Font.Bold = True

# デフォルトパス = このExcelと同じフォルダの output_csv
default_path = str(BASE / "output_csv") + "\\"
ws_cfg.Cells(2,1).Value = "パス"  # 列ヘッダー（Power Query が参照）
ws_cfg.Cells(2,2).Value = default_path

# テーブルに変換（Power Query が名前で参照できるように）
tbl_rng = ws_cfg.Range("A2:B2")
tbl = ws_cfg.ListObjects.Add(1, tbl_rng, None, 1)  # xlSrcRange=1, xlYes=1
tbl.Name = "CSVフォルダパス"
ws_cfg.Columns("A:B").AutoFit()

ws_cfg.Cells(4,1).Value = "※ B2セルのパスを output_csv フォルダの場所に合わせて変更してください"
ws_cfg.Cells(4,1).Font.Color = 0x808080

# ── Power Query 接続を追加 ────────────────────────────────
print("Power Query を設定中...")

conn_str = (
    "OLEDB;Provider=Microsoft.Mashup.OleDb.1;"
    "Data Source=$Workbook$;"
    "Location=登記データ;"
    "Extended Properties=\"\""
)
cmd_text = "SELECT * FROM [登記データ]"

try:
    conn = wb.Connections.Add2(
        "Query - 登記データ",
        "登記簿CSVフォルダを結合するクエリ",
        conn_str,
        cmd_text,
        6,   # xlConnectionTypeOLEDB
    )
    conn.OLEDBConnection.BackgroundQuery = False

    # ListObject（テーブル）としてシートに結果を出力
    lo_dest = ws_data.Range("A1")
    qt = ws_data.ListObjects.Add(
        SourceType=0,  # xlSrcExternal
        Source=conn_str,
        Destination=lo_dest,
    )
    qt.Name = "登記データテーブル"
    qt.QueryTable.Connection = conn_str
    qt.QueryTable.CommandText = cmd_text
except Exception as e:
    print(f"  [INFO] COM接続追加: {e}（後でExcelから手動設定可）")

# M コードをシートに記録（参照用）
ws_m = wb.Worksheets.Add(After=wb.Worksheets(wb.Worksheets.Count))
ws_m.Name = "Mコード参照"
ws_m.Cells(1,1).Value = "以下のMコードをPower Queryエディタに貼り付けてください"
ws_m.Cells(1,1).Font.Bold = True
ws_m.Cells(2,1).Value = M_CODE
ws_m.Columns("A").ColumnWidth = 120
ws_m.Rows("2:2").RowHeight = 400
ws_m.Cells(2,1).WrapText = True

# ── ピボットテーブル作成 ──────────────────────────────────
print("ピボットテーブルを作成中...")
try:
    pc = wb.PivotCaches().Create(
        SourceType=1,   # xlDatabase
        SourceData="登記データ!A:Z",
        Version=6,
    )
    pt = pc.CreatePivotTable(
        TableDestination=ws_pivot.Range("A3"),
        TableName="登記ピボット",
    )
    # 行フィールド
    for field_name in ["種別", "状態", "登記の目的"]:
        try:
            f = pt.PivotFields(field_name)
            f.Orientation = 1   # xlRowField
        except:
            pass
    # 列フィールド
    try:
        f = pt.PivotFields("リスクフラグ")
        f.Orientation = 2  # xlColumnField
    except:
        pass
    # 値フィールド
    try:
        f = pt.PivotFields("物件フォルダ")
        f.Orientation = 4  # xlDataField
        f.Function   = -4112  # xlCount
        f.Name = "件数"
    except:
        pass

    ws_pivot.Cells(1,1).Value = "登記ピボットテーブル"
    ws_pivot.Cells(1,1).Font.Bold = True
    ws_pivot.Cells(1,1).Font.Size = 14
    ws_pivot.Cells(2,1).Value = "※ データ更新後に「すべて更新」してください"
    ws_pivot.Cells(2,1).Font.Color = 0x808080
except Exception as e:
    print(f"  [INFO] ピボット作成エラー（後で手動設定可）")

# ── 保存 ────────────────────────────────────────────────
print(f"保存中: {OUT}")
wb.SaveAs(str(OUT), 51)  # xlOpenXMLWorkbook
wb.Close(False)
xl.Quit()

print(f"\n完了: {OUT}")
print("使い方:")
print("  1. 設定シートのB2セルにoutput_csvフォルダのパスを入力")
print("  2. データタブ → すべて更新")
print("  3. ピボットシートも自動更新されます")
