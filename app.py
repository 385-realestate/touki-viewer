"""
登記簿PDFパーサー — デスクトップアプリ (customtkinter版)
"""
import sys
import os
import shutil
import threading
import queue
import json
import tempfile
import subprocess
import zipfile
import urllib.request
from datetime import datetime
from pathlib import Path

APP_VERSION  = "1.7"
GITHUB_REPO  = "hattav4192/touki-viewer"
GITHUB_API   = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"

import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import customtkinter as ctk
from tkinterdnd2 import DND_FILES, TkinterDnD

# ---- パス設定 ----
# PyInstaller frozen時 __file__ は _internal/ を指すため sys.executable を使う
# scripts は _MEIPASS/_internal/ 下に配置されるため frozen 時は _MEIPASS を参照する
if getattr(sys, 'frozen', False):
    BASE_DIR    = Path(sys.executable).parent
    SCRIPTS_DIR = Path(sys._MEIPASS) / "scripts"
else:
    BASE_DIR    = Path(__file__).parent
    SCRIPTS_DIR = BASE_DIR / "scripts"
INPUT_DIR   = BASE_DIR / "登記簿公図データ"
DOWNLOADS   = Path.home() / "Downloads"
CSV_OUT_DIR = BASE_DIR / "output_csv"

sys.path.insert(0, str(SCRIPTS_DIR))
if sys.stdout and hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
if sys.stderr and hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8')

ctk.set_appearance_mode("light")
ctk.set_default_color_theme("blue")

# ---- UI共通定数 ----
from ui.constants import C, SEP, TAB_IMPORT, TAB_PROCESS, TAB_KOUZU


# ---- stdout をキューに流すラッパー ----
class _QueueWriter:
    def __init__(self, q: queue.Queue, original):
        self._q        = q
        self._original = original

    def write(self, text: str):
        if text:
            self._q.put(text)
        if self._original:
            self._original.write(text)

    def flush(self):
        if self._original:
            self._original.flush()



# ---- スポット解析結果ウィンドウ（ui サブパッケージ） ----
from ui.spot_result_window import SpotResultWindow



# ================================================================
#  メインウィンドウ
# ================================================================
class App(TkinterDnD.Tk):

    def __init__(self):
        super().__init__()
        self.title("登記簿 PDF パーサー")
        self.minsize(800, 660)
        self.configure(bg=C["bg"])

        self.update_idletasks()
        w, h = 900, 760
        x = (self.winfo_screenwidth()  - w) // 2
        y = (self.winfo_screenheight() - h) // 2
        self.geometry(f"{w}x{h}+{x}+{y}")

        self._log_queue        = queue.Queue()
        self._kouzu_log_queue  = queue.Queue()
        self._running          = False
        self._orig_stdout      = sys.stdout
        self._orig_stderr      = sys.stderr
        self._kouzu_pdf_paths  = []

        self._build_ui()
        self._poll_log()
        self._poll_kouzu_log()
        self._refresh_pdf_list()

        self.drop_target_register(DND_FILES)
        self.dnd_bind("<<Drop>>", self._on_drop)
        self.after(800, self._register_all_drop_targets)

        # 起動3秒後にバックグラウンドでアップデート確認
        self._pending_update = None
        self.after(3000, lambda: threading.Thread(target=self._check_for_update, daemon=True).start())

        # デスクトップショートカットが未存在なら自動作成
        self.after(500, self._ensure_shortcut)

    # ----------------------------------------------------------------
    #  全ウィジェットにドロップターゲットを再帰登録（CTK対応）
    # ----------------------------------------------------------------
    def _register_all_drop_targets(self):
        def walk(widget):
            try:
                widget.drop_target_register(DND_FILES)
                widget.dnd_bind("<<Drop>>", self._on_drop)
            except Exception:
                pass
            try:
                for child in widget.winfo_children():
                    walk(child)
            except Exception:
                pass
        walk(self)

    # ----------------------------------------------------------------
    #  自動アップデート
    # ----------------------------------------------------------------
    def _check_for_update(self):
        try:
            req = urllib.request.Request(GITHUB_API, headers={"User-Agent": "touki-viewer"})
            with urllib.request.urlopen(req, timeout=6) as r:
                data = json.loads(r.read())
            tag = data.get("tag_name", "").lstrip("v")
            if tag and tuple(int(x) for x in tag.split(".")) > tuple(int(x) for x in APP_VERSION.split(".")):
                asset = next((a for a in data.get("assets", []) if a["name"].endswith(".zip")), None)
                if asset:
                    self._pending_update = {"tag": tag, "url": asset["browser_download_url"]}
                    self.after(0, self._show_update_banner)
        except Exception:
            pass

    def _show_update_banner(self):
        if not self._pending_update:
            return
        tag = self._pending_update["tag"]
        self._update_lbl.configure(text=f"  新しいバージョン v{tag} が公開されています")
        self._update_frame.configure(height=36)

    def _do_update(self):
        if not self._pending_update:
            return
        url  = self._pending_update["url"]
        tag  = self._pending_update["tag"]
        self._update_btn.configure(text="ダウンロード中...", state="disabled")
        self.update_idletasks()

        def _download_and_install():
            try:
                install_dir = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).parent
                tmp_dir  = Path(tempfile.mkdtemp())
                zip_path = tmp_dir / f"touki_viewer_v{tag}.zip"
                new_dir  = tmp_dir / "touki_viewer_new"

                # ダウンロード
                self.after(0, lambda: self._update_lbl.configure(text="  ダウンロード中..."))
                urllib.request.urlretrieve(url, zip_path)

                # 解凍
                self.after(0, lambda: self._update_lbl.configure(text="  解凍中..."))
                new_dir.mkdir()
                with zipfile.ZipFile(zip_path, "r") as zf:
                    zf.extractall(new_dir)

                # updater.bat を作成して実行 → アプリ終了後にファイルを差し替え
                bat = tmp_dir / "updater.bat"
                exe = install_dir / "touki_viewer.exe"
                bat.write_text(
                    f'@echo off\r\n'
                    f'timeout /t 3 /noisy >nul\r\n'
                    f'robocopy "{new_dir}" "{install_dir}" /E /IS /IT /IM /COPYALL /NJH /NJS\r\n'
                    f'start "" "{exe}"\r\n'
                    f'del "%~0"\r\n',
                    encoding="mbcs"
                )
                subprocess.Popen(["cmd", "/c", str(bat)], creationflags=subprocess.CREATE_NO_WINDOW)
                self.after(0, self.destroy)
            except Exception as e:
                self.after(0, lambda: self._update_lbl.configure(text=f"  エラー: {e}"))
                self.after(0, lambda: self._update_btn.configure(text="今すぐアップデート", state="normal"))

        threading.Thread(target=_download_and_install, daemon=True).start()

    # ----------------------------------------------------------------
    #  UI 構築
    # ----------------------------------------------------------------
    def _build_ui(self):
        # ===== ヘッダーバー =====
        header = ctk.CTkFrame(self, corner_radius=0, fg_color=C["header_bg"])
        header.pack(fill="x")
        left_bar = ctk.CTkFrame(header, width=6, corner_radius=0, fg_color=C["green"])
        left_bar.pack(side="left", fill="y")
        left_bar.pack_propagate(False)
        ctk.CTkLabel(
            header, text="登記簿 PDF パーサー",
            font=ctk.CTkFont("Yu Gothic UI", 19, "bold"),
            text_color=C["header_text"],
        ).pack(side="left", padx=16, pady=(12, 4))
        ctk.CTkLabel(
            header, text="不動産登記簿PDFを自動解析 → SQLite / CSV 出力",
            font=ctk.CTkFont("Yu Gothic UI", 13),
            text_color="#A8BEE0",
        ).pack(side="left", padx=(0, 16), pady=(12, 4))
        # バージョン表示
        ctk.CTkLabel(
            header, text=f"v{APP_VERSION}",
            font=ctk.CTkFont("Yu Gothic UI", 11),
            text_color="#6A8EC2",
        ).pack(side="right", padx=16, pady=(12, 4))

        # ===== アップデートバナー（初期非表示）=====
        self._update_frame = ctk.CTkFrame(self, corner_radius=0, fg_color="#1B4D35", height=0)
        self._update_frame.pack(fill="x")
        self._update_frame.pack_propagate(False)
        self._update_lbl = ctk.CTkLabel(
            self._update_frame, text="",
            font=ctk.CTkFont("Yu Gothic UI", 12),
            text_color="#FFFFFF",
        )
        self._update_lbl.pack(side="left", padx=16, pady=5)
        self._update_btn = ctk.CTkButton(
            self._update_frame, text="今すぐアップデート",
            font=ctk.CTkFont("Yu Gothic UI", 12, "bold"),
            fg_color=C["green"], hover_color="#276749",
            height=26, corner_radius=4,
            command=self._do_update,
        )
        self._update_btn.pack(side="right", padx=16, pady=5)

        # ===== ステップバー（グレー帯）=====
        step_bar = ctk.CTkFrame(self, corner_radius=0, fg_color=C["step_bg"], height=32)
        step_bar.pack(fill="x")
        step_bar.pack_propagate(False)
        for i, (label, active) in enumerate([
            ("PDF取り込み", False), ("解析実行", False), ("CSV出力", False)
        ]):
            bg = C["step_active"] if active else "transparent"
            ctk.CTkLabel(
                step_bar, text=f"  {i+1}. {label}  ",
                font=ctk.CTkFont("Yu Gothic UI", 12, "bold" if active else "normal"),
                text_color=C["step_text"],
                fg_color=bg, corner_radius=4,
            ).pack(side="left", padx=(12 if i == 0 else 2, 2), pady=4)

        # ===== タブ =====
        self._tabs = ctk.CTkTabview(
            self, corner_radius=0,
            fg_color=C["bg"],
            segmented_button_fg_color=C["surface"],
            segmented_button_selected_color=C["green"],
            segmented_button_selected_hover_color=C["green_h"],
            segmented_button_unselected_color=C["surface"],
            segmented_button_unselected_hover_color=C["surface2"],
            text_color=C["subtext"],
            text_color_disabled=C["muted"],
        )
        self._tabs.pack(fill="both", expand=True, padx=0, pady=0)
        self._tabs.add(TAB_IMPORT)
        self._tabs.add(TAB_PROCESS)
        self._tabs.add(TAB_KOUZU)

        self._build_tab_import(self._tabs.tab(TAB_IMPORT))
        self._build_tab_process(self._tabs.tab(TAB_PROCESS))
        self._build_tab_kouzu(self._tabs.tab(TAB_KOUZU))

        # ===== フッター =====
        footer = ctk.CTkFrame(self, corner_radius=0, fg_color=C["header_bg"], height=30)
        footer.pack(fill="x", side="bottom")
        footer.pack_propagate(False)
        self._footer_var = ctk.StringVar(value="準備完了")
        ctk.CTkLabel(
            footer, textvariable=self._footer_var,
            font=ctk.CTkFont("Yu Gothic UI", 12),
            text_color="#A8BEE0",
        ).pack(side="left", padx=16, pady=4)

    # ----------------------------------------------------------------
    #  タブ1: PDF取り込み
    # ----------------------------------------------------------------
    def _build_tab_import(self, parent):

        # ===== 水平コンテナ（左: PDF一覧、右: ドロップ＋操作）=====
        container = tk.Frame(parent, bg=C["bg"])
        container.pack(fill="both", expand=True, padx=4, pady=(6, 4))

        # ===== 右ペイン: ドロップゾーン ＋ 操作ボタン（固定幅260px）=====
        right_pane = tk.Frame(container, bg=C["bg"], width=260)
        right_pane.pack(side="right", fill="y", padx=(8, 0))
        right_pane.pack_propagate(False)

        # ---- ドロップゾーン ----
        drop_outer = ctk.CTkFrame(right_pane, corner_radius=8, fg_color=C["surface"],
                                  border_width=2, border_color=C["border"])
        drop_outer.pack(fill="x", pady=(0, 8))

        self._drop_frame = tk.Frame(drop_outer, bg=C["surface"])
        self._drop_frame.pack(fill="x", padx=2, pady=2)

        self._drop_label = tk.Label(
            self._drop_frame,
            text="📄\nここにPDFを\nドロップ",
            font=("Yu Gothic UI", 13, "bold"),
            bg=C["surface"], fg=C["subtext"],
            justify="center",
        )
        self._drop_label.pack(pady=(14, 8))

        select_btn = tk.Button(
            self._drop_frame,
            text="  PDFを選択  ",
            font=("Yu Gothic UI", 12, "bold"),
            bg=C["accent"], fg="#FFFFFF",
            activebackground=C["accent_h"], activeforeground="#FFFFFF",
            relief="flat", cursor="hand2", bd=0, padx=10, pady=6,
            command=self._select_files,
        )
        select_btn.pack(pady=(0, 12))

        def _on_enter(_):
            drop_outer.configure(border_color=C["green"], fg_color="#EBF4EB")
            self._drop_label.configure(bg="#EBF4EB", fg=C["green"])
            self._drop_frame.configure(bg="#EBF4EB")

        def _on_leave(_):
            drop_outer.configure(border_color=C["border"], fg_color=C["surface"])
            self._drop_label.configure(bg=C["surface"], fg=C["subtext"])
            self._drop_frame.configure(bg=C["surface"])

        for w in (self._drop_frame, self._drop_label):
            w.drop_target_register(DND_FILES)
            w.dnd_bind("<<Drop>>",      self._on_drop)
            w.dnd_bind("<<DragEnter>>", _on_enter)
            w.dnd_bind("<<DragLeave>>", _on_leave)

        # ---- 操作ボタン ----
        action_frame = ctk.CTkFrame(right_pane, corner_radius=8, fg_color=C["surface2"],
                                    border_width=1, border_color=C["border"])
        action_frame.pack(fill="x")

        ctk.CTkLabel(
            action_frame,
            text="ダウンロードフォルダから取り込む",
            font=ctk.CTkFont("Yu Gothic UI", 11),
            text_color=C["subtext"],
        ).pack(anchor="w", padx=10, pady=(8, 4))

        ctk.CTkButton(
            action_frame,
            text="📋  コピーして取り込む",
            font=ctk.CTkFont("Yu Gothic UI", 13, "bold"),
            height=36, corner_radius=6,
            fg_color=C["surface"], hover_color=C["border"],
            border_width=1, border_color=C["border"],
            text_color=C["text"],
            command=lambda: self._import_from_downloads(move=False),
        ).pack(fill="x", padx=10, pady=(0, 4))

        ctk.CTkButton(
            action_frame,
            text="✂️  移動して取り込む",
            font=ctk.CTkFont("Yu Gothic UI", 13, "bold"),
            height=36, corner_radius=6,
            fg_color=C["surface"], hover_color=C["border"],
            border_width=1, border_color=C["border"],
            text_color=C["subtext"],
            command=lambda: self._import_from_downloads(move=True),
        ).pack(fill="x", padx=10, pady=(0, 8))

        ctk.CTkButton(
            action_frame,
            text="📁  フォルダをスキャン",
            font=ctk.CTkFont("Yu Gothic UI", 13, "bold"),
            height=36, corner_radius=6,
            fg_color=C["green"], hover_color=C["green_h"],
            text_color="#FFFFFF",
            command=self._scan_folder,
        ).pack(fill="x", padx=10, pady=(0, 8))

        self._auto_analyze_var = ctk.BooleanVar(value=True)
        ctk.CTkCheckBox(
            action_frame,
            text="取り込み後に自動解析",
            variable=self._auto_analyze_var,
            font=ctk.CTkFont("Yu Gothic UI", 12),
            text_color=C["text"],
            fg_color=C["green"], hover_color=C["green_h"],
            checkmark_color="#FFFFFF",
            border_color=C["border"],
        ).pack(anchor="w", padx=10, pady=(0, 8))

        ctk.CTkButton(
            action_frame,
            text="🖥  ショートカット作成",
            font=ctk.CTkFont("Yu Gothic UI", 12),
            height=30, corner_radius=6,
            fg_color=C["surface2"], hover_color=C["border"],
            border_width=1, border_color=C["border"],
            text_color=C["subtext"],
            command=self._create_desktop_shortcut,
        ).pack(fill="x", padx=10, pady=(0, 10))

        # ===== 左ペイン: 取り込み済みPDF一覧 =====
        left_pane = tk.Frame(container, bg=C["bg"])
        left_pane.pack(side="left", fill="both", expand=True)

        # 一覧ヘッダー
        list_hdr = ctk.CTkFrame(left_pane, fg_color="transparent")
        list_hdr.pack(fill="x", pady=(0, 2))

        ctk.CTkLabel(
            list_hdr, text="取り込み済みPDF一覧",
            font=ctk.CTkFont("Yu Gothic UI", 14, "bold"),
            text_color=C["header_bg"],
        ).pack(side="left")

        self._pdf_count_var = ctk.StringVar(value="")
        ctk.CTkLabel(
            list_hdr, textvariable=self._pdf_count_var,
            font=ctk.CTkFont("Yu Gothic UI", 13),
            text_color=C["subtext"],
        ).pack(side="left", padx=10)

        ctk.CTkButton(
            list_hdr, text="⟳ 更新",
            font=ctk.CTkFont("Yu Gothic UI", 12),
            width=80, height=30, corner_radius=4,
            fg_color="transparent", border_width=1,
            border_color=C["border"], text_color=C["subtext"],
            hover_color=C["surface2"],
            command=self._refresh_pdf_list,
        ).pack(side="right", padx=(4, 0))

        self._btn_spot = ctk.CTkButton(
            list_hdr, text="🔍 個別解析",
            font=ctk.CTkFont("Yu Gothic UI", 13, "bold"),
            width=120, height=30, corner_radius=4,
            fg_color=C["accent"], hover_color=C["accent_h"],
            text_color="#FFFFFF",
            state="disabled",
            command=self._open_spot_window,
        )
        self._btn_spot.pack(side="right", padx=(0, 6))

        # treeview（ttk）ライトスタイル
        style = ttk.Style(parent)
        style.theme_use("default")
        style.configure("Gov.Treeview",
            background=C["surface"], foreground=C["text"],
            fieldbackground=C["surface"],
            rowheight=26, font=("Yu Gothic UI", 13),
            borderwidth=0, relief="flat",
        )
        style.configure("Gov.Treeview.Heading",
            background=C["header_bg"], foreground="#FFFFFF",
            font=("Yu Gothic UI", 12, "bold"),
            borderwidth=0, relief="flat",
            padding=(6, 4),
        )
        style.map("Gov.Treeview",
            background=[("selected", C["row_sel"])],
            foreground=[("selected", C["header_bg"])],
        )

        tv_frame = tk.Frame(left_pane, bg=C["border"], highlightthickness=0)
        tv_frame.pack(fill="both", expand=True)

        self._tree = ttk.Treeview(
            tv_frame,
            style="Gov.Treeview",
            columns=("name", "type", "size", "mtime"),
            show="headings",
            selectmode="browse",
        )
        self._tree.heading("name",  text="ファイル名")
        self._tree.heading("type",  text="種別")
        self._tree.heading("size",  text="サイズ")
        self._tree.heading("mtime", text="更新日時")
        self._tree.column("name",  width=340, minwidth=180, stretch=True)
        self._tree.column("type",  width=70,  minwidth=60,  stretch=False, anchor="center")
        self._tree.column("size",  width=80,  minwidth=60,  stretch=False, anchor="e")
        self._tree.column("mtime", width=140, minwidth=110, stretch=False, anchor="center")

        vsb = ttk.Scrollbar(tv_frame, orient="vertical", command=self._tree.yview)
        self._tree.configure(yscrollcommand=vsb.set)
        self._tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")

        self._tree.tag_configure("even", background=C["row_even"])
        self._tree.tag_configure("odd",  background=C["row_odd"])

        self._tree.bind("<<TreeviewSelect>>", self._on_tree_select)
        self._tree.bind("<Double-1>", lambda e: self._open_spot_window())

    # ----------------------------------------------------------------
    #  PDF 一覧の更新
    # ----------------------------------------------------------------
    def _refresh_pdf_list(self):
        for item in self._tree.get_children():
            self._tree.delete(item)

        if not INPUT_DIR.exists():
            self._pdf_count_var.set("")
            return

        pdfs = sorted(INPUT_DIR.rglob("*.pdf"), key=lambda p: p.stat().st_mtime, reverse=True)
        pdfs += sorted(INPUT_DIR.rglob("*.PDF"), key=lambda p: p.stat().st_mtime, reverse=True)

        # 重複除去
        seen = set()
        unique = []
        for p in pdfs:
            if p.name.lower() not in seen:
                seen.add(p.name.lower())
                unique.append(p)

        from touki_parser import detect_type
        for i, p in enumerate(unique):
            stat = p.stat()
            size = f"{stat.st_size // 1024} KB"
            mtime = datetime.fromtimestamp(stat.st_mtime).strftime("%Y/%m/%d %H:%M")
            try:
                doc_type = detect_type(p.name, "")
                label = "土地" if doc_type == "tochi" else "建物" if doc_type == "tatemono" else "不明"
            except Exception:
                label = "不明"
            tag = "even" if i % 2 == 0 else "odd"
            self._tree.insert("", "end", iid=str(p),
                              values=(p.name, label, size, mtime), tags=(tag,))

        self._pdf_count_var.set(f"{len(unique)} 件")
        self._btn_spot.configure(state="disabled")

    def _on_tree_select(self, _event=None):
        selected = self._tree.selection()
        self._btn_spot.configure(state="normal" if selected else "disabled")

    def _open_spot_window(self):
        selected = self._tree.selection()
        if not selected:
            return
        pdf_path = Path(selected[0])
        SpotResultWindow(self, pdf_path)

    # ----------------------------------------------------------------
    #  タブ2: 解析
    # ----------------------------------------------------------------
    def _build_tab_process(self, parent):

        # 完了バナー（初期は非表示）
        self._banner = ctk.CTkFrame(parent, corner_radius=6, fg_color=C["success_bg"],
                                    border_width=1, border_color=C["success"])
        self._banner_label = ctk.CTkLabel(
            self._banner, text="",
            font=ctk.CTkFont("Yu Gothic UI", 14, "bold"),
            text_color=C["success"],
        )
        self._banner_label.pack(side="left", padx=16, pady=10)
        ctk.CTkButton(
            self._banner, text="✕",
            width=28, height=28, corner_radius=4,
            fg_color="transparent", hover_color=C["border"],
            text_color=C["subtext"], command=self._hide_banner,
        ).pack(side="right", padx=8)

        # コントロール行
        ctrl = ctk.CTkFrame(parent, corner_radius=0, fg_color=C["surface"],
                            border_width=1, border_color=C["border"])
        ctrl.pack(fill="x", pady=(8, 6), padx=4)

        self._btn_start = ctk.CTkButton(
            ctrl,
            text="▶  解析を開始",
            font=ctk.CTkFont("Yu Gothic UI", 15, "bold"),
            width=200, height=42, corner_radius=4,
            fg_color=C["green"], hover_color=C["green_h"],
            text_color="#FFFFFF",
            command=self._on_start,
        )
        self._btn_start.pack(side="left", padx=12, pady=10)

        workers_f = ctk.CTkFrame(ctrl, fg_color="transparent")
        workers_f.pack(side="left", padx=(12, 0))
        ctk.CTkLabel(
            workers_f, text="並列数:",
            font=ctk.CTkFont("Yu Gothic UI", 14),
            text_color=C["subtext"],
        ).pack(side="left", padx=(0, 6))

        self._workers_var  = ctk.IntVar(value=min(4, os.cpu_count() or 2))
        self._workers_menu = ctk.CTkOptionMenu(
            workers_f,
            values=["1", "2", "3", "4", "6", "8"],
            variable=self._workers_var,
            width=80, height=36,
            fg_color=C["surface2"], button_color=C["accent"],
            button_hover_color=C["accent_h"],
            dropdown_fg_color=C["surface"],
            text_color=C["text"],
            font=ctk.CTkFont("Yu Gothic UI", 14),
            command=lambda v: self._workers_var.set(int(v)),
        )
        self._workers_menu.pack(side="left")

        ctk.CTkButton(
            ctrl, text="📂 CSV出力フォルダを開く",
            font=ctk.CTkFont("Yu Gothic UI", 13),
            width=200, height=36, corner_radius=4,
            fg_color=C["accent"], hover_color=C["accent_h"],
            text_color="#FFFFFF",
            command=self._open_csv_folder,
        ).pack(side="right", padx=(4, 4))

        ctk.CTkButton(
            ctrl, text="ログクリア",
            font=ctk.CTkFont("Yu Gothic UI", 13),
            width=100, height=36, corner_radius=4,
            fg_color="transparent", border_width=1,
            border_color=C["border"], text_color=C["muted"],
            hover_color=C["surface2"],
            command=self._clear_log,
        ).pack(side="right", padx=(0, 4))

        # プログレスバー
        self._progress = ctk.CTkProgressBar(
            parent, mode="indeterminate", height=8,
            progress_color=C["green"], fg_color=C["border"],
        )
        self._progress.pack(fill="x", padx=4, pady=(0, 4))
        self._progress.set(0)

        # ステータス
        self._status_var = ctk.StringVar(value="待機中  —  「▶ 解析を開始」を押してください")
        ctk.CTkLabel(
            parent, textvariable=self._status_var,
            font=ctk.CTkFont("Yu Gothic UI", 14),
            text_color=C["subtext"],
        ).pack(anchor="w", padx=4, pady=(0, 4))

        # ログ見出し（左端にアクセントバー）
        log_hdr = ctk.CTkFrame(parent, corner_radius=0, fg_color=C["surface"],
                               border_width=1, border_color=C["border"], height=34)
        log_hdr.pack(fill="x", padx=4, pady=(4, 0))
        log_hdr.pack_propagate(False)
        ctk.CTkFrame(log_hdr, width=5, corner_radius=0, fg_color=C["accent"]).pack(side="left", fill="y")
        ctk.CTkLabel(
            log_hdr, text="  処理ログ",
            font=ctk.CTkFont("Yu Gothic UI", 13, "bold"),
            text_color=C["header_bg"],
        ).pack(side="left", padx=8, pady=6)

        self._log_box = ctk.CTkTextbox(
            parent,
            font=ctk.CTkFont("Cascadia Mono", 12),
            fg_color=C["surface"], text_color=C["text"],
            scrollbar_button_color=C["border"],
            scrollbar_button_hover_color=C["accent"],
            border_width=1, border_color=C["border"],
            state="disabled",
        )
        self._log_box.pack(fill="both", expand=True, padx=4, pady=(0, 4))

    # ----------------------------------------------------------------
    #  バナー制御
    # ----------------------------------------------------------------
    def _show_banner(self, text: str, kind: str = "success"):
        bg  = C["success_bg"] if kind == "success" else C["error_bg"]
        clr = C["success"]    if kind == "success" else C["error"]
        txt = C["success"]    if kind == "success" else C["error"]
        self._banner.configure(fg_color=bg, border_color=clr)
        self._banner_label.configure(text=text, text_color=txt)
        self._banner.pack(fill="x", padx=4, pady=(6, 2), before=self._progress)

    def _hide_banner(self):
        self._banner.pack_forget()

    # ----------------------------------------------------------------
    #  ドロップ処理
    # ----------------------------------------------------------------
    def _on_drop(self, event):
        if self._tabs.get() == TAB_KOUZU:
            self._on_kouzu_drop(event)
            return
        self._tabs.set(TAB_IMPORT)
        self.update_idletasks()

        raw = event.data.strip()
        try:
            paths = self.tk.splitlist(raw)
        except Exception:
            paths = raw.split()

        paths = [Path(p) for p in paths if str(p).strip()]
        pdfs  = self._collect_pdfs(paths)

        if pdfs:
            self._copy_pdfs_to_input(pdfs, move=False, auto_analyze=False)
            self._open_spot_auto(pdfs)
        else:
            self._status_msg(f"PDFが見つかりませんでした（ドロップ内容: {raw[:60]}）")

    def _select_files(self):
        files = filedialog.askopenfilenames(
            title="PDFを選択してください",
            filetypes=[("PDFファイル", "*.pdf *.PDF")],
            initialdir=DOWNLOADS if DOWNLOADS.exists() else Path.home(),
        )
        if not files:
            return
        pdfs = [Path(f) for f in files]
        self._copy_pdfs_to_input(pdfs, move=False, auto_analyze=False)
        self._open_spot_auto(pdfs)

    def _open_spot_auto(self, src_pdfs: list):
        """PDFを取り込んだ直後に個別解析ウィンドウを自動表示（最大3件）"""
        for src in src_pdfs[:3]:
            dest = INPUT_DIR / src.name
            target = dest if dest.exists() else src
            self.after(300, lambda t=target: SpotResultWindow(self, t))

    def _collect_pdfs(self, paths) -> list:
        pdfs = []
        for p in paths:
            p = Path(p)
            if p.is_dir():
                pdfs.extend(p.rglob("*.pdf"))
                pdfs.extend(p.rglob("*.PDF"))
            elif p.suffix.lower() == ".pdf":
                pdfs.append(p)
        return pdfs

    # ----------------------------------------------------------------
    #  ダウンロードフォルダからインポート
    # ----------------------------------------------------------------
    def _import_from_downloads(self, move: bool):
        if not DOWNLOADS.exists():
            messagebox.showerror("エラー", f"ダウンロードフォルダが見つかりません:\n{DOWNLOADS}")
            return
        all_pdfs = list(DOWNLOADS.glob("*.pdf")) + list(DOWNLOADS.glob("*.PDF"))
        pdfs     = [f for f in all_pdfs if "不動産登記" in f.name]
        skipped  = len(all_pdfs) - len(pdfs)
        if skipped:
            self._status_msg(f"除外: 登記簿以外のPDF {skipped}件")
        if not pdfs:
            messagebox.showinfo("情報", "ダウンロードフォルダに登記簿PDFが見つかりませんでした")
            return
        self._copy_pdfs_to_input(pdfs, move=move)

    # ----------------------------------------------------------------
    #  PDF を INPUT_DIR にコピー/移動
    # ----------------------------------------------------------------
    def _copy_pdfs_to_input(self, pdfs: list, move: bool, auto_analyze: bool = None):
        INPUT_DIR.mkdir(parents=True, exist_ok=True)
        action = "移動" if move else "コピー"
        ok, skip, err = 0, 0, 0

        for src in pdfs:
            dest = INPUT_DIR / src.name
            if dest.exists():
                skip += 1
                continue
            try:
                if move:
                    shutil.move(str(src), dest)
                else:
                    shutil.copy2(src, dest)
                ok += 1
            except Exception as e:
                self._status_msg(f"エラー: {src.name}: {e}")
                err += 1

        msg = f"✓ {action}完了: {ok}件 / スキップ(重複): {skip}件" + (f" / エラー: {err}件" if err else "")
        self._status_msg(msg)
        self._refresh_pdf_list()

        should_analyze = auto_analyze if auto_analyze is not None else self._auto_analyze_var.get()
        if ok > 0 and should_analyze and not self._running:
            self._footer_var.set(f"✓ {ok}件を{action}  →  自動解析を開始します...")
            self._tabs.set(TAB_PROCESS)
            self.after(300, self._on_start)
        else:
            self._footer_var.set(
                f"✓ {ok}件を{action}  →  「{TAB_PROCESS}」タブで解析を開始してください"
            )

    # ----------------------------------------------------------------
    #  フォルダスキャン
    # ----------------------------------------------------------------
    def _scan_folder(self):
        folder = filedialog.askdirectory(
            title="スキャンするフォルダを選択",
            initialdir=DOWNLOADS if DOWNLOADS.exists() else Path.home(),
        )
        if not folder:
            return
        folder = Path(folder)
        all_pdfs = list(folder.rglob("*.pdf")) + list(folder.rglob("*.PDF"))
        if not all_pdfs:
            messagebox.showinfo("情報", "PDFが見つかりませんでした")
            return

        # 既にINPUT_DIRにある名前を除外
        existing = {p.name.lower() for p in INPUT_DIR.rglob("*") if p.is_file()} if INPUT_DIR.exists() else set()
        new_pdfs = [p for p in all_pdfs if p.name.lower() not in existing]

        if not new_pdfs:
            messagebox.showinfo("情報", f"新規PDFはありませんでした（既存: {len(all_pdfs)}件）")
            return

        ans = messagebox.askyesno(
            "確認",
            f"新規PDF {len(new_pdfs)}件を取り込みます。\n"
            f"（既存スキップ: {len(all_pdfs) - len(new_pdfs)}件）\n\n"
            f"取り込み後に自動解析しますか？",
        )
        # yesでも自動解析、noでも取り込みは実行（解析なし）
        self._copy_pdfs_to_input(new_pdfs, move=False, auto_analyze=ans)

    # ----------------------------------------------------------------
    #  デスクトップショートカット作成
    # ----------------------------------------------------------------
    def _ensure_shortcut(self):
        """起動時に一度だけサイレントで作成する"""
        desktop = Path.home() / "Desktop"
        if not desktop.exists():
            desktop = Path.home() / "OneDrive" / "Desktop"
        if not (desktop / "登記簿パーサー.lnk").exists():
            self._create_desktop_shortcut(silent=True)

    def _create_desktop_shortcut(self, silent: bool = False):
        import subprocess
        desktop = Path.home() / "Desktop"
        if not desktop.exists():
            desktop = Path.home() / "OneDrive" / "Desktop"
        lnk = desktop / "登記簿パーサー.lnk"
        target = Path(__file__).resolve()
        # pythonw.exe で起動するとコンソールウィンドウが出ない
        ps = (
            f'$ws = New-Object -ComObject WScript.Shell; '
            f'$s = $ws.CreateShortcut("{lnk}"); '
            f'$s.TargetPath = "pythonw.exe"; '
            f'$s.Arguments = \'"{target}"\'; '
            f'$s.WorkingDirectory = "{target.parent}"; '
            f'$s.Description = "登記簿PDFパーサー"; '
            f'$s.Save()'
        )
        try:
            subprocess.run(
                ["powershell", "-NoProfile", "-Command", ps],
                capture_output=True, timeout=10,
            )
            if not silent:
                messagebox.showinfo("完了", f"デスクトップにショートカットを作成しました:\n{lnk}")
        except Exception as e:
            if not silent:
                messagebox.showerror("エラー", f"ショートカット作成に失敗しました:\n{e}")

    def _open_csv_folder(self):
        import subprocess
        CSV_OUT_DIR.mkdir(parents=True, exist_ok=True)
        subprocess.Popen(["explorer", str(CSV_OUT_DIR)])

    def _status_msg(self, text: str):
        self._footer_var.set(text)

    # ----------------------------------------------------------------
    #  解析ログ書き込み
    # ----------------------------------------------------------------
    def _append_log(self, text: str):
        self._log_box.configure(state="normal")
        self._log_box.insert("end", text)
        self._log_box.see("end")
        self._log_box.configure(state="disabled")

    def _clear_log(self):
        self._log_box.configure(state="normal")
        self._log_box.delete("1.0", "end")
        self._log_box.configure(state="disabled")

    def _poll_log(self):
        try:
            while True:
                text = self._log_queue.get_nowait()
                self._append_log(text)
        except queue.Empty:
            pass
        self.after(100, self._poll_log)

    # ----------------------------------------------------------------
    #  一括解析処理
    # ----------------------------------------------------------------
    def _on_start(self):
        if self._running:
            return
        self._hide_banner()
        self._running = True
        self._btn_start.configure(state="disabled", text="⏳  解析中...")
        self._workers_menu.configure(state="disabled")
        self._status_var.set("解析中 — PDFを読み込んでいます...")
        self._footer_var.set("解析中...")
        self._progress.start()

        sys.stdout = _QueueWriter(self._log_queue, self._orig_stdout)  # type: ignore
        sys.stderr = _QueueWriter(self._log_queue, self._orig_stderr)  # type: ignore

        workers = self._workers_var.get()
        threading.Thread(target=self._run_worker, args=(workers,), daemon=True).start()

    def _run_worker(self, workers: int):
        start_time = datetime.now()
        try:
            from router import process_all_parallel
            process_all_parallel(workers=workers)
            elapsed = (datetime.now() - start_time).seconds
            self.after(0, self._on_done, True, elapsed)
        except Exception:
            import traceback
            traceback.print_exc()
            self.after(0, self._on_done, False, 0)

    def _on_done(self, success: bool, elapsed: int):
        sys.stdout = self._orig_stdout
        sys.stderr = self._orig_stderr
        self._running = False
        self._progress.stop()
        self._progress.set(0)
        self._btn_start.configure(state="normal", text="▶  解析を開始")
        self._workers_menu.configure(state="normal")

        if success:
            self._status_var.set(f"完了（{elapsed}秒）")
            self._footer_var.set(f"✓ 解析完了  {datetime.now().strftime('%Y-%m-%d %H:%M')}")
            self._show_banner(f"✓ 解析が完了しました（{elapsed}秒）", "success")
        else:
            self._status_var.set("エラーが発生しました — ログを確認してください")
            self._footer_var.set("✗ エラー — ログを確認してください")
            self._show_banner("✗ エラーが発生しました。ログを確認してください。", "error")

        self._append_log(
            f"\n{'─'*60}\n"
            f"{'処理完了' if success else 'エラー終了'}  "
            f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        )
        self._refresh_pdf_list()  # 一括解析後も一覧を更新


    # ----------------------------------------------------------------
    #  タブ3: 公図変換
    # ----------------------------------------------------------------
    def _build_tab_kouzu(self, parent):
        container = tk.Frame(parent, bg=C["bg"])
        container.pack(fill="both", expand=True, padx=4, pady=(6, 4))

        # ===== 左ペイン: 制御パネル (260px) =====
        left_pane = tk.Frame(container, bg=C["bg"], width=260)
        left_pane.pack(side="left", fill="y", padx=(0, 8))
        left_pane.pack_propagate(False)

        panel = ctk.CTkFrame(left_pane, corner_radius=8, fg_color=C["surface"])
        panel.pack(fill="both", expand=True)

        ctk.CTkLabel(
            panel, text="公図 → JWC / DXF 変換",
            font=ctk.CTkFont("Yu Gothic UI", 14, "bold"),
            text_color=C["header_bg"],
        ).pack(anchor="w", padx=14, pady=(14, 8))

        # ドロップゾーン（DnD は tk.Frame/Label が必要）
        drop_outer = ctk.CTkFrame(panel, corner_radius=6, fg_color=C["surface2"],
                                  border_width=2, border_color=C["border"])
        drop_outer.pack(fill="x", padx=10, pady=(0, 8))

        self._kouzu_drop_frame = tk.Frame(drop_outer, bg=C["surface2"])
        self._kouzu_drop_frame.pack(fill="x", padx=2, pady=2)

        self._kouzu_drop_label = tk.Label(
            self._kouzu_drop_frame,
            text="🗺\n公図PDFを\nここにドロップ",
            font=("Yu Gothic UI", 13, "bold"),
            bg=C["surface2"], fg=C["subtext"],
            justify="center",
        )
        self._kouzu_drop_label.pack(pady=(12, 6))

        ctk.CTkButton(
            self._kouzu_drop_frame,
            text="PDFを選択",
            font=ctk.CTkFont("Yu Gothic UI", 12, "bold"),
            height=30, corner_radius=4,
            fg_color=C["accent"], hover_color=C["accent_h"],
            text_color="#FFFFFF",
            command=self._kouzu_select_file,
        ).pack(fill="x", padx=10, pady=(0, 10))

        def _drop_enter(_):
            drop_outer.configure(border_color=C["green"], fg_color="#EBF4EB")
            self._kouzu_drop_label.configure(bg="#EBF4EB", fg=C["green"])
            self._kouzu_drop_frame.configure(bg="#EBF4EB")

        def _drop_leave(_):
            drop_outer.configure(border_color=C["border"], fg_color=C["surface2"])
            self._kouzu_drop_label.configure(bg=C["surface2"], fg=C["subtext"])
            self._kouzu_drop_frame.configure(bg=C["surface2"])

        for w in (self._kouzu_drop_frame, self._kouzu_drop_label):
            w.drop_target_register(DND_FILES)
            w.dnd_bind("<<Drop>>",      self._on_kouzu_drop)
            w.dnd_bind("<<DragEnter>>", _drop_enter)
            w.dnd_bind("<<DragLeave>>", _drop_leave)

        # 縮尺設定
        ctk.CTkLabel(
            panel, text="縮尺",
            font=ctk.CTkFont("Yu Gothic UI", 12, "bold"),
            text_color=C["subtext"],
        ).pack(anchor="w", padx=14, pady=(0, 2))

        self._kouzu_scale_var = ctk.StringVar(value="auto（自動検出）")
        ctk.CTkOptionMenu(
            panel,
            values=["auto（自動検出）", "1:500", "1:250", "1:1000", "1:200", "1:100"],
            variable=self._kouzu_scale_var,
            font=ctk.CTkFont("Yu Gothic UI", 12),
            height=30, corner_radius=4,
            fg_color=C["surface2"],
            text_color=C["text"],
        ).pack(fill="x", padx=14, pady=(0, 8))

        # 出力形式
        ctk.CTkLabel(
            panel, text="出力形式",
            font=ctk.CTkFont("Yu Gothic UI", 12, "bold"),
            text_color=C["subtext"],
        ).pack(anchor="w", padx=14, pady=(0, 2))

        self._kouzu_fmt_var = ctk.StringVar(value="jwc")
        fmt_frame = ctk.CTkFrame(panel, fg_color="transparent")
        fmt_frame.pack(fill="x", padx=14, pady=(0, 10))

        for val, label in [("jwc", "JWC (Jw_cad)"), ("dxf", "DXF (AutoCAD互換)")]:
            ctk.CTkRadioButton(
                fmt_frame, text=label, variable=self._kouzu_fmt_var, value=val,
                font=ctk.CTkFont("Yu Gothic UI", 12),
                fg_color=C["green"], hover_color=C["green_h"],
                text_color=C["text"],
            ).pack(anchor="w", pady=2)

        # 変換ボタン
        self._kouzu_btn = ctk.CTkButton(
            panel, text="🔄  変換開始",
            font=ctk.CTkFont("Yu Gothic UI", 13, "bold"),
            height=40, corner_radius=6,
            fg_color=C["green"], hover_color=C["green_h"],
            text_color="#FFFFFF",
            state="disabled",
            command=self._kouzu_start,
        )
        self._kouzu_btn.pack(fill="x", padx=14, pady=(0, 8))

        ctk.CTkButton(
            panel, text="📁  出力先フォルダを開く",
            font=ctk.CTkFont("Yu Gothic UI", 12),
            height=30, corner_radius=4,
            fg_color=C["surface2"], hover_color=C["border"],
            border_width=1, border_color=C["border"],
            text_color=C["subtext"],
            command=self._kouzu_open_output,
        ).pack(fill="x", padx=14, pady=(0, 12))

        # ===== 右ペイン: ログ =====
        right_pane = tk.Frame(container, bg=C["bg"])
        right_pane.pack(side="left", fill="both", expand=True)

        log_hdr = ctk.CTkFrame(right_pane, fg_color="transparent")
        log_hdr.pack(fill="x", pady=(0, 4))

        ctk.CTkLabel(
            log_hdr, text="変換ログ",
            font=ctk.CTkFont("Yu Gothic UI", 14, "bold"),
            text_color=C["header_bg"],
        ).pack(side="left")

        self._kouzu_status_var = ctk.StringVar(value="PDFをドロップして変換を開始してください")
        ctk.CTkLabel(
            log_hdr, textvariable=self._kouzu_status_var,
            font=ctk.CTkFont("Yu Gothic UI", 12),
            text_color=C["subtext"],
        ).pack(side="left", padx=12)

        ctk.CTkButton(
            log_hdr, text="クリア",
            font=ctk.CTkFont("Yu Gothic UI", 11),
            width=60, height=26, corner_radius=4,
            fg_color="transparent", border_width=1,
            border_color=C["border"], text_color=C["subtext"],
            hover_color=C["surface2"],
            command=self._kouzu_clear_log,
        ).pack(side="right")

        log_frame = tk.Frame(right_pane, bg=C["border"])
        log_frame.pack(fill="both", expand=True)

        self._kouzu_log_box = ctk.CTkTextbox(
            log_frame,
            font=ctk.CTkFont("Consolas", 12),
            text_color=C["text"],
            fg_color=C["surface"],
            border_width=0,
            state="disabled",
            wrap="none",
        )
        self._kouzu_log_box.pack(fill="both", expand=True, padx=1, pady=1)

    # ----------------------------------------------------------------
    #  公図変換: 操作ハンドラー
    # ----------------------------------------------------------------
    def _on_kouzu_drop(self, event):
        raw = event.data.strip()
        try:
            paths = self.tk.splitlist(raw)
        except Exception:
            paths = raw.split()
        pdfs = [p for p in paths if str(p).lower().endswith('.pdf')]
        if pdfs:
            self._kouzu_pdf_paths = pdfs
            names = ", ".join(Path(p).name for p in pdfs)
            self._kouzu_drop_label.configure(text=f"📄 {names[:36]}…" if len(names) > 38 else f"📄 {names}")
            self._kouzu_btn.configure(state="normal")
            self._kouzu_status_var.set(f"{len(pdfs)} 件 選択済み — 変換を開始してください")
        else:
            self._kouzu_status_var.set("PDFが見つかりませんでした")

    def _kouzu_select_file(self):
        files = filedialog.askopenfilenames(
            title="公図PDFを選択",
            filetypes=[("PDFファイル", "*.pdf *.PDF"), ("全ファイル", "*.*")],
            initialdir=Path.home() / "Downloads",
        )
        if files:
            self._kouzu_pdf_paths = list(files)
            names = ", ".join(Path(p).name for p in files)
            self._kouzu_drop_label.configure(text=f"📄 {names[:36]}…" if len(names) > 38 else f"📄 {names}")
            self._kouzu_btn.configure(state="normal")
            self._kouzu_status_var.set(f"{len(files)} 件 選択済み — 変換を開始してください")

    def _kouzu_start(self):
        if not self._kouzu_pdf_paths:
            return

        scale_str = self._kouzu_scale_var.get()
        if scale_str.startswith("auto"):
            scale = None
        else:
            scale = int(scale_str.split(":")[1])

        fmt  = self._kouzu_fmt_var.get()
        pdfs = list(self._kouzu_pdf_paths)

        self._kouzu_btn.configure(state="disabled", text="⏳  変換中...")
        self._kouzu_status_var.set("変換中...")
        self._kouzu_clear_log()

        def _worker():
            sys.stdout = _QueueWriter(self._kouzu_log_queue, self._orig_stdout)
            sys.stderr = _QueueWriter(self._kouzu_log_queue, self._orig_stderr)
            ok, ng = 0, 0
            try:
                from kouzu_to_jwc import convert
                for pdf in pdfs:
                    pdf_path = Path(pdf)
                    print(f"処理中: {pdf_path.name}")
                    try:
                        text, scale_used, n_lines, n_texts = convert(pdf_path, scale, fmt)
                        out_path = pdf_path.with_suffix('.' + fmt)
                        enc = 'cp932' if fmt == 'jwc' else 'utf-8'
                        out_path.write_text(text, encoding=enc, errors='replace')
                        print(f"  ✓ {out_path.name}")
                        print(f"     縮尺 1:{scale_used} / 線分 {n_lines} / テキスト {n_texts}\n")
                        ok += 1
                    except Exception as e:
                        import traceback
                        print(f"  ✗ エラー: {e}")
                        traceback.print_exc()
                        ng += 1
            finally:
                sys.stdout = self._orig_stdout
                sys.stderr = self._orig_stderr
            self.after(0, self._kouzu_on_done, ok, ng, pdfs)

        threading.Thread(target=_worker, daemon=True).start()

    def _kouzu_on_done(self, ok: int, ng: int, pdfs: list):
        self._kouzu_btn.configure(state="normal", text="🔄  変換開始")
        if ng == 0:
            msg = f"✓  {ok} 件 変換完了"
            self._kouzu_status_var.set(msg)
            self._footer_var.set(f"✓ 公図変換完了 {ok}件  {datetime.now().strftime('%H:%M')}")
        else:
            self._kouzu_status_var.set(f"✓ {ok}件 / ✗ {ng}件 エラー")

    def _kouzu_open_output(self):
        import subprocess
        if self._kouzu_pdf_paths:
            folder = Path(self._kouzu_pdf_paths[0]).parent
        else:
            folder = INPUT_DIR / "公図"
            folder.mkdir(parents=True, exist_ok=True)
        subprocess.Popen(["explorer", str(folder)])

    def _kouzu_clear_log(self):
        self._kouzu_log_box.configure(state="normal")
        self._kouzu_log_box.delete("1.0", "end")
        self._kouzu_log_box.configure(state="disabled")

    def _kouzu_append_log(self, text: str):
        self._kouzu_log_box.configure(state="normal")
        self._kouzu_log_box.insert("end", text)
        self._kouzu_log_box.see("end")
        self._kouzu_log_box.configure(state="disabled")

    def _poll_kouzu_log(self):
        try:
            while True:
                text = self._kouzu_log_queue.get_nowait()
                self._kouzu_append_log(text)
        except queue.Empty:
            pass
        self.after(100, self._poll_kouzu_log)


# ================================================================
#  エントリーポイント
# ================================================================
if __name__ == "__main__":
    app = App()
    app.mainloop()
