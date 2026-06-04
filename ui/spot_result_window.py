"""
個別解析結果ウィンドウ（SpotResultWindow）
app.py から分離して管理性を向上させたモジュール
"""
import sys
import csv
import threading
from datetime import datetime
from pathlib import Path

import tkinter as tk
from tkinter import messagebox, filedialog
import customtkinter as ctk

from ui.constants import C, SEP


# ================================================================
#  スポット解析結果ウィンドウ
# ================================================================
class SpotResultWindow(ctk.CTkToplevel):

    # フォントサイズ定数
    F_SECTION = ("Yu Gothic UI", 13, "bold")
    F_LABEL   = ("Yu Gothic UI", 14)
    F_VALUE   = ("Yu Gothic UI", 15)
    F_SMALL   = ("Yu Gothic UI", 13)

    def __init__(self, master, pdf_path: Path):
        super().__init__(master)
        self.title(f"個別解析  —  {pdf_path.name[:60]}")
        self.geometry("760x700")
        self.minsize(620, 520)
        self.configure(fg_color=C["bg"])
        self.grab_set()

        self._pdf_path = pdf_path
        self._result   = None
        self._doc_type = None

        self._build_ui()
        self.after(120, self._run_parse)

    # ---- UI骨格 ----
    def _build_ui(self):
        # ヘッダーバー（濃紺）
        hdr = ctk.CTkFrame(self, corner_radius=0, fg_color=C["header_bg"])
        hdr.pack(fill="x")
        ctk.CTkLabel(
            hdr, text="個別解析",
            font=ctk.CTkFont("Yu Gothic UI", 17, "bold"),
            text_color=C["header_text"],
        ).pack(side="left", padx=16, pady=10)
        ctk.CTkLabel(
            hdr, text=self._pdf_path.name,
            font=ctk.CTkFont(*self.F_SMALL),
            text_color="#A8BEE0",
        ).pack(side="left")

        # ステータスバー（グレー）
        status_bar = ctk.CTkFrame(self, corner_radius=0, fg_color=C["step_bg"], height=30)
        status_bar.pack(fill="x")
        status_bar.pack_propagate(False)
        self._status_var = ctk.StringVar(value="解析中...")
        ctk.CTkLabel(
            status_bar, textvariable=self._status_var,
            font=ctk.CTkFont(*self.F_SMALL),
            text_color=C["step_text"],
        ).pack(side="left", padx=14, pady=4)

        self._prog = ctk.CTkProgressBar(
            self, mode="indeterminate", height=5,
            progress_color=C["green"], fg_color=C["border"],
        )
        self._prog.pack(fill="x")
        self._prog.start()

        self._scroll = ctk.CTkScrollableFrame(
            self, fg_color=C["bg"],
            scrollbar_button_color=C["border"],
            scrollbar_button_hover_color=C["accent"],
        )
        self._scroll.pack(fill="both", expand=True, padx=10, pady=6)

        btn_bar = ctk.CTkFrame(self, corner_radius=0, fg_color=C["surface2"],
                               border_width=1, border_color=C["border"])
        btn_bar.pack(fill="x", side="bottom")
        self._btn_csv = ctk.CTkButton(
            btn_bar, text="📄  CSVに出力",
            font=ctk.CTkFont("Yu Gothic UI", 14, "bold"),
            height=38, corner_radius=6,
            fg_color=C["accent"], hover_color=C["accent_h"],
            state="disabled",
            command=self._export_csv,
        )
        self._btn_csv.pack(pady=8, padx=16, anchor="e")

    # ---- 解析スレッド ----
    def _run_parse(self):
        def worker():
            try:
                from touki_parser import (
                    extract_text, zen2han, detect_type, file_md5,
                )
                from agents.tochi_agent    import TochiAgent
                from agents.tatemono_agent import TatemonoAgent

                fhash    = file_md5(self._pdf_path)
                raw      = extract_text(self._pdf_path)
                text_han = zen2han(raw)
                doc_type = detect_type(self._pdf_path.name, raw)

                agent  = TochiAgent() if doc_type == "tochi" else TatemonoAgent()
                result = agent.run(self._pdf_path, fhash)

                self.after(0, self._on_done, result, doc_type)
            except Exception as e:
                import traceback
                traceback.print_exc()
                self.after(0, self._on_error, str(e))

        threading.Thread(target=worker, daemon=True).start()

    # ---- 結果表示 ----
    def _on_done(self, result, doc_type: str):
        self._prog.stop()
        self._prog.set(1)

        if result is None:
            self._status_var.set("解析に失敗しました")
            return

        self._result   = result
        self._doc_type = doc_type
        record = result["record"]
        label  = "土地" if doc_type == "tochi" else "建物"
        self._status_var.set(f"解析完了  ―  {label}")

        # ======== 表題部 ========
        self._section_header("表題部")
        if doc_type == "tochi":
            self._row("所在",     record.get("所在", ""))
            self._row("地番",     record.get("地番", ""))
            self._row("地目",     record.get("地目", ""))
            self._row("地積（㎡）", record.get("地積_m2", ""))
        else:
            self._row("所在",     record.get("所在", ""))
            self._row("家屋番号", record.get("家屋番号", ""))
            self._row("種類",     record.get("種類", ""))
            self._row("構造",     record.get("構造", ""))
            self._row("床面積", record.get("床面積_m2", ""))

        history    = result.get("history", {})
        kouku_hist = history.get("kouku",  [])
        otsuku_hist= history.get("otsuku", [])

        # ======== 甲区（所有権） ========
        self._section_header("甲区（所有権）")

        # 現在の所有者サマリー
        # タイムラインと同一ソース（最後の "現在" ブロックの _cumulative）で整合性を保つ
        import re as _re2
        from math import gcd as _gcd2
        _cur_blk_top = next((b for b in reversed(kouku_hist) if b.get("状態") == "現在"), None)
        if _cur_blk_top and _cur_blk_top.get("_cumulative"):
            _cum_top = _cur_blk_top["_cumulative"]
            _denom_top = 1
            for _, (_tn_v, _td_v) in _cum_top.items():
                _denom_top = _denom_top * _td_v // _gcd2(_denom_top, _td_v)
            _parts_top = []
            for _nm_t, (_tn_v, _td_v) in _cum_top.items():
                _n_norm_t = _tn_v * (_denom_top // _td_v)
                if _denom_top == 1:
                    _parts_top.append(_nm_t)
                else:
                    _parts_top.append(f"{_nm_t}({_denom_top}分の{_n_norm_t})")
            cur_owners_raw = SEP.join(_parts_top)
            cur_addrs_raw  = _cur_blk_top.get("所有者住所", "")
        else:
            cur_owners_raw = record.get("所有者氏名", "")
            cur_addrs_raw  = record.get("所有者住所", "")
        if cur_owners_raw:

            # ── 持分合計を先に計算してカードスタイルを決定 ──
            _owners_list = [o.strip() for o in cur_owners_raw.split(SEP) if o.strip()]
            _tn, _td, _has_frac = 0, 1, False
            for _o in _owners_list:
                _fm = _re2.search(r'\(([0-9]+)分の([0-9]+)\)', _o)
                if _fm:
                    _has_frac = True
                    _fd = int(_fm.group(1))   # 分母 X
                    _fn = int(_fm.group(2))   # 分子 Y
                    _lcm = _td * _fd // _gcd2(_td, _fd)
                    _tn = _tn * (_lcm // _td) + _fn * (_lcm // _fd)
                    _td = _lcm
            _is_full = (not _has_frac) or (_tn == _td)

            # 確定 or 要精査 でカラースキームを切替
            if _is_full:
                _card_bg, _card_border = "#F0FFF4", "#2B6B2B"
                _title_text  = "現在の所有者（確定）"
                _title_color = "#276749"
                _addr_color  = "#276749"
            else:
                _card_bg, _card_border = "#FFF8F0", "#C0580A"
                _title_text  = "現在の所有者（要精査）"
                _title_color = "#C0580A"
                _addr_color  = "#8B4000"

            sum_card = self._bordered_card(
                self._scroll, fg_color=_card_bg, border_color=_card_border,
                corner_radius=6, fill="x", padx=(24, 28), pady=(0, 10),
            )
            ctk.CTkLabel(
                sum_card, text=_title_text,
                font=ctk.CTkFont("Yu Gothic UI", 11, "bold"),
                text_color=_title_color, anchor="w",
            ).pack(anchor="w", padx=12, pady=(8, 4), fill="x")

            # 所有者を 1行ずつ「住所　氏名（持分）」形式で表示
            _addr_list  = [a.strip() for a in cur_addrs_raw.split(SEP)] if cur_addrs_raw else []
            for _idx, _o in enumerate(_owners_list):
                _row = ctk.CTkFrame(sum_card, fg_color="transparent")
                _row.pack(fill="x", padx=12, pady=(1, 1))
                # 番号バッジ
                ctk.CTkLabel(
                    _row, text=f"  {_idx + 1}  ",
                    font=ctk.CTkFont("Yu Gothic UI", 11),
                    fg_color=_card_border, text_color="#FFFFFF", corner_radius=3, width=26,
                ).pack(side="left", padx=(0, 6))
                # 住所
                _oa = _addr_list[_idx].strip() if _idx < len(_addr_list) else ""
                if _oa:
                    ctk.CTkLabel(
                        _row, text=_oa,
                        font=ctk.CTkFont("Yu Gothic UI", 11),
                        text_color=_addr_color, anchor="w", wraplength=260,
                    ).pack(side="left", padx=(0, 8))
                # 氏名（持分付き）
                ctk.CTkLabel(
                    _row, text=_o.strip(),
                    font=ctk.CTkFont("Yu Gothic UI", 14, "bold"),
                    text_color="#1C1F2E", anchor="w",
                ).pack(side="left", fill="x", expand=True)

            # 持分合計バッジ
            if _has_frac:
                _g = _gcd2(_tn, _td)
                _frac_str = f"{_td // _g}分の{_tn // _g}"
                if _is_full:
                    _chk_text  = f"持分合計:  {_frac_str}  ✓ 100%確認済み"
                    _chk_color, _chk_bg = "#276749", "#D4F5E0"
                else:
                    _missing_n = _td - _tn
                    _chk_text  = (f"持分合計:  {_frac_str}  ⚠ 100%未満"
                                  f"（{_td // _g}分の{_missing_n // _g}が未特定）"
                                  f"  → 要精査・差し戻し")
                    _chk_color, _chk_bg = "#C0392B", "#FCE8E8"
                _chk_frame = ctk.CTkFrame(sum_card, fg_color=_chk_bg, corner_radius=4)
                _chk_frame.pack(fill="x", padx=12, pady=(6, 10))
                ctk.CTkLabel(
                    _chk_frame, text=_chk_text,
                    font=ctk.CTkFont("Yu Gothic UI", 12, "bold"),
                    text_color=_chk_color, anchor="w",
                ).pack(anchor="w", padx=8, pady=4, fill="x")
            else:
                ctk.CTkFrame(sum_card, height=8, fg_color="transparent").pack()

        kouku_entries = [e for e in kouku_hist if e.get("状態") not in ("参考",)]
        if kouku_entries:
            cancel_map, paired_ids = self._build_sashiosae_pairs(kouku_entries)
            for entry in kouku_entries:   # 古い順（順位1→2→3…）
                if id(entry) in paired_ids:
                    continue  # 対応する差押カードの直後にインライン描画する
                rank = entry.get("順位", "")
                has_pair = (entry.get("状態") == "差押" and rank in cancel_map)
                self._kouku_card(entry, compact_bottom=has_pair)
                if has_pair:
                    self._kouku_card(cancel_map[rank], paired_matsusho=True)
        elif kouku_hist:
            for entry in kouku_hist:     # 古い順
                self._kouku_card(entry)
        else:
            # 履歴取得できなかった場合のフォールバック
            self._row("取得日",     record.get("取得日", ""))
            self._row("所有者住所", record.get("所有者住所", ""))
            self._row("所有者氏名", record.get("所有者氏名", ""))

        # ── 持分タイムライン表 ──
        _own_entries = [e for e in kouku_hist
                        if e.get("状態") in ("現在", "移転前")
                        and e.get("所有者氏名")]
        if len(_own_entries) >= 2:
            self._kouku_timeline(_own_entries)

        # ======== 乙区（抵当権） ========
        tanpo_hist  = history.get("tanpo", [])
        tanpo_raw   = record.get("共同担保一覧", "")

        import re as _re
        def _extract_no(s: str) -> str:
            """'（そ）第1053/0810号' → '1053/0810' のように第〜号の中身を取り出す"""
            m = _re.search(r'第([0-9][0-9/]*)号', s or "")
            return m.group(1) if m else ""

        # 数字部分でマッピング（プレフィックス差異を吸収）
        otsuku_by_no_digits: dict = {}
        for e in otsuku_hist:
            digits = _extract_no(e.get("共担目録番号", ""))
            if digits:
                otsuku_by_no_digits[digits] = e

        # 共担目録を先にグループ化（乙区カード内にインライン表示するため）
        tanpo_groups: dict = {}
        for e in tanpo_hist:
            k = e.get("記号及び番号", "") or "（番号不明）"
            tanpo_groups.setdefault(k, []).append(e)
        shown_kigou: set = set()

        self._section_header("乙区（抵当権）")
        if otsuku_hist:
            for entry in otsuku_hist:
                # 対応する共担目録を特定（フォールバック：1対1の場合は自動マッチ）
                tanpo_digits = _extract_no(entry.get("共担目録番号", ""))
                matched_kigou = ""
                if tanpo_digits:
                    for kigou in tanpo_groups:
                        if _extract_no(kigou) == tanpo_digits:
                            matched_kigou = kigou
                            break
                elif len(otsuku_hist) == 1 and len(tanpo_groups) == 1:
                    matched_kigou = next(iter(tanpo_groups))
                self._otsuku_card(entry, matched_kigou)
                if matched_kigou and not entry.get("_is_fuki"):
                    self._tanpo_inline_block(matched_kigou, tanpo_groups[matched_kigou], entry)
                    shown_kigou.add(matched_kigou)
        else:
            kensu = record.get("抵当権件数", "0")
            if kensu == "0":
                self._empty_row("抵当権なし（または抹消済み）")
            else:
                def _split(v): return [s.strip() for s in v.split(SEP) if s.strip()]
                banks   = _split(record.get("抵当権者",    ""))
                amounts = _split(record.get("抵当権債権額", ""))
                debtors = _split(record.get("抵当権債務者", ""))
                n = int(kensu)
                for idx in range(n):
                    card = self._bordered_card(
                        self._scroll, fg_color=C["surface2"], border_color=C["border"],
                        corner_radius=6, border_size=1,
                        fill="x", padx=(24, 28), pady=(0, 6),
                    )
                    bank = banks[idx] if idx < len(banks) else "（銀行名不明）"
                    ctk.CTkLabel(
                        card, text=f"  {bank}",
                        font=ctk.CTkFont("Yu Gothic UI", 14, "bold"),
                        text_color=C["accent"], anchor="w",
                    ).pack(fill="x", padx=12, pady=(8, 4))
                    if idx < len(amounts) and amounts[idx]:
                        self._card_row(card, "借入金額", amounts[idx])
                    if idx < len(debtors) and debtors[idx]:
                        self._card_row(card, "債務者",   debtors[idx])
                    ctk.CTkFrame(card, height=1, fg_color=C["border"]).pack(
                        fill="x", padx=10, pady=(4, 8))

        # ======== 共同担保目録（乙区にリンクされていないものを残す） ========
        remaining = {k: v for k, v in tanpo_groups.items() if k not in shown_kigou}
        if remaining:
            self._section_header("共同担保目録")
            for kigou, entries in remaining.items():
                matched = otsuku_by_no_digits.get(_extract_no(kigou))
                self._tanpo_group_card(kigou, entries, matched)
        elif tanpo_raw and not shown_kigou:
            self._section_header("共同担保目録")
            items = [s.strip() for s in tanpo_raw.split(SEP) if s.strip()]
            self._tanpo_group_card("（番号不明）", [{"内容": i, "状態": "現在"} for i in items], None)

        self._btn_csv.configure(state="normal")
        self.after(100, self._fix_scroll_width)
        self.after(600, self._fix_scroll_width)   # 2回目: レイアウト確定後の保険

    def _fix_scroll_width(self):
        """CTkScrollableFrameの内部canvasに正しい幅を強制セット (_create_window_id 使用)"""
        try:
            canvas = self._scroll._parent_canvas
            self.update_idletasks()
            w = canvas.winfo_width()
            if w > 100:
                canvas.itemconfigure(self._scroll._create_window_id, width=w)
                self.update_idletasks()
                bbox = canvas.bbox("all")
                if bbox:
                    canvas.configure(scrollregion=(0, 0, max(w, bbox[2]) + 4, bbox[3] + 4))
            else:
                self.after(150, self._fix_scroll_width)
        except Exception:
            pass

    # ---- UI部品ヘルパー ----
    def _bordered_card(self, parent, fg_color, border_color, corner_radius=6, border_size=2, **pack_kw):
        outer = ctk.CTkFrame(parent, corner_radius=corner_radius, fg_color=border_color, border_width=0)
        outer.pack(**pack_kw)
        inner = ctk.CTkFrame(outer, corner_radius=max(0, corner_radius - border_size), fg_color=fg_color, border_width=0)
        inner.pack(fill="x", padx=border_size, pady=border_size)
        return inner

    def _section_header(self, title: str):
        bar_frame = ctk.CTkFrame(self._scroll, corner_radius=4, fg_color=C["surface"],
                                 border_width=1, border_color=C["border"])
        bar_frame.pack_propagate(False)
        bar_frame.configure(height=30)
        bar_frame.pack(fill="x", pady=(4, 2), padx=(4, 8))
        accent = ctk.CTkFrame(bar_frame, width=5, corner_radius=0, fg_color=C["green"])
        accent.pack_propagate(False)
        accent.pack(side="left", fill="y")
        ctk.CTkLabel(
            bar_frame, text=title,
            font=ctk.CTkFont(*self.F_SECTION),
            text_color=C["header_bg"],
        ).pack(side="left", anchor="w", padx=12)

        self._current_section_outer = ctk.CTkFrame(
            self._scroll, fg_color=C["border"], border_width=0, corner_radius=4,
        )
        self._current_section = ctk.CTkFrame(
            self._current_section_outer, fg_color=C["surface"], border_width=0, corner_radius=3,
        )
        self._current_section.pack(fill="x", padx=1, pady=1)
        self._section_content_packed = False

    def _ensure_content_packed(self):
        if not self._section_content_packed:
            self._current_section_outer.pack(fill="x", padx=(4, 8), pady=(0, 4))
            self._section_content_packed = True

    def _row(self, label: str, value: str):
        if not value:
            return
        self._ensure_content_packed()
        f = ctk.CTkFrame(self._current_section, fg_color="transparent")
        f.pack(fill="x", padx=14, pady=3)
        ctk.CTkLabel(
            f, text=label,
            font=ctk.CTkFont(*self.F_LABEL),
            text_color=C["subtext"],
            width=130, anchor="w",
        ).pack(side="left")
        ctk.CTkLabel(
            f, text=value,
            font=ctk.CTkFont(*self.F_VALUE),
            text_color=C["text"],
            anchor="w", wraplength=520,
        ).pack(side="left", fill="x", expand=True, pady=(0, 4))

    def _empty_row(self, text: str):
        self._ensure_content_packed()
        ctk.CTkLabel(
            self._current_section, text=f"  {text}",
            font=ctk.CTkFont(*self.F_SMALL),
            text_color=C["muted"],
        ).pack(anchor="w", padx=14, pady=(0, 8))

    def _card_row(self, parent, label: str, value: str, text_color: str = ""):
        f = ctk.CTkFrame(parent, fg_color="transparent")
        f.pack(fill="x", padx=12, pady=2)
        ctk.CTkLabel(
            f, text=label,
            font=ctk.CTkFont(*self.F_LABEL),
            text_color=C["subtext"],
            width=90, anchor="w",
        ).pack(side="left")
        ctk.CTkLabel(
            f, text=value,
            font=ctk.CTkFont(*self.F_VALUE),
            text_color=text_color or C["text"],
            anchor="w",
        ).pack(side="left")

    # ---- 差押ペア構築ヘルパー ----
    @staticmethod
    def _build_sashiosae_pairs(entries: list) -> tuple:
        import re as _re
        sashiosae_rank_set = {e.get("順位") for e in entries if e.get("状態") == "差押"}
        cancel_map: dict = {}
        paired_ids: set  = set()
        for e in entries:
            if e.get("状態") != "差押抹消":
                continue
            ranks = _re.findall(r'([0-9]+)番', e.get("登記の目的", ""))
            valid = [r for r in ranks if r in sashiosae_rank_set]
            if not valid:
                continue
            trigger = max(valid, key=int)
            if trigger not in cancel_map:
                cancel_map[trigger] = e
                paired_ids.add(id(e))
        return cancel_map, paired_ids

    # ---- 持分タイムライン表 ----
    def _kouku_timeline(self, entries: list):
        import re as _re
        from math import gcd as _gcd

        def _parse_frac(s: str):
            m = _re.search(r'\(([0-9]+)分の([0-9]+)\)', s)
            return (int(m.group(2)), int(m.group(1))) if m else None

        def _frac_add(a, b):
            n1, d1 = a; n2, d2 = b
            lcm = d1 * d2 // _gcd(d1, d2)
            return (n1 * (lcm // d1) + n2 * (lcm // d2), lcm)

        def _frac_str(n, d):
            g = _gcd(n, d)
            return f"{d//g}分の{n//g}"

        def _bare(s):
            return _re.sub(r'[(（][^)）]*[)）]', '', s).strip()

        all_persons: list = []
        for e in entries:
            _cum = e.get("_cumulative", {})
            src_names = list(_cum.keys()) if _cum else [
                _bare(o.strip()) for o in e.get("所有者氏名", "").split(SEP) if o.strip()
            ]
            for name in src_names:
                if name and name not in all_persons:
                    all_persons.append(name)

        if not all_persons:
            return

        global_d = 1
        for e in entries:
            _c = e.get("_cumulative", {})
            for frac in _c.values():
                global_d = global_d * frac[1] // _gcd(global_d, frac[1])
            if not _c:
                for o in e.get("所有者氏名", "").split(SEP):
                    frac = _parse_frac(o.strip())
                    if frac:
                        global_d = global_d * frac[1] // _gcd(global_d, frac[1])

        outer = self._bordered_card(
            self._scroll, fg_color="#F4F5F8", border_color="#C8CBD8",
            corner_radius=6, border_size=1,
            fill="x", padx=(24, 28), pady=(4, 8),
        )

        title_row = ctk.CTkFrame(outer, fg_color="transparent")
        title_row.pack(fill="x", padx=10, pady=(6, 3))
        ctk.CTkLabel(
            title_row, text="持分タイムライン",
            font=ctk.CTkFont("Yu Gothic UI", 13, "bold"),
            text_color=C["muted"],
        ).pack(side="left")

        tbl = ctk.CTkFrame(outer, fg_color="transparent")
        tbl.pack(anchor="w", padx=10, pady=(0, 6))

        COL0_W, COL_W = 100, 120
        ROW_H  = 88
        HDR_FG, HDR_TC = "#E2E4EE", C["muted"]
        CUR_FG  = "#EAF9EF"
        DATA_FG = "#FAFBFE"

        def _shorten_date_tl(s: str) -> str:
            if not s: return s
            era = {'明治': 'M', '大正': 'T', '昭和': 'S', '平成': 'H', '令和': 'R'}
            m = _re.search(r'(明治|大正|昭和|平成|令和)([0-9]+)年([0-9]+)月([0-9]+)日', s)
            if m:
                return f"{era.get(m.group(1), m.group(1))}{m.group(2)}.{m.group(3)}.{m.group(4)}"
            return s

        def _shorten_moku(s: str) -> str:
            s2 = _re.sub(r'^.+?(?=持分|所有権|抵当権|差押|合体|合筆|換地)', '', s)
            return (s2 or s)[:10]

        def _cell(parent, text, width, bold=False, fg="#FFFFFF", tc="#1C1F2E",
                  anchor="center", row_idx=0, height=36):
            bg = CUR_FG if row_idx == 1 else (DATA_FG if row_idx == 2 else HDR_FG)
            f = ctk.CTkFrame(parent, fg_color=fg if fg != "#FFFFFF" else bg,
                             corner_radius=0, width=width, height=height)
            f.pack_propagate(False)
            f.pack(side="left", padx=1, pady=1)
            ctk.CTkLabel(
                f, text=text,
                font=ctk.CTkFont("Yu Gothic UI", 15, "bold" if bold else "normal"),
                text_color=tc, anchor=anchor,
            ).pack(fill="both", expand=True, padx=2)

        def _rank_cell(parent, entry, row_idx):
            bg = CUR_FG if row_idx == 1 else DATA_FG
            rank_tc = C["muted"]
            f = ctk.CTkFrame(parent, fg_color=bg, corner_radius=0,
                             width=COL0_W, height=ROW_H)
            f.pack_propagate(False)
            f.pack(side="left", padx=1, pady=1)
            ctk.CTkLabel(f, text=f"{entry.get('順位', '')}番",
                font=ctk.CTkFont("Yu Gothic UI", 14, "bold"),
                text_color=rank_tc, anchor="center",
            ).pack(fill="x", padx=2, pady=(4, 0))
            moku_s = _shorten_moku(entry.get("登記の目的", ""))
            ctk.CTkLabel(f, text=moku_s,
                font=ctk.CTkFont("Yu Gothic UI", 11),
                text_color=rank_tc, anchor="center", wraplength=COL0_W - 4,
            ).pack(fill="x", padx=2)
            recv = _shorten_date_tl(entry.get("受付年月日", ""))
            ctk.CTkLabel(f, text=recv,
                font=ctk.CTkFont("Yu Gothic UI", 12),
                text_color=C["muted"], anchor="center",
            ).pack(fill="x", padx=2, pady=(0, 4))

        hdr_row = ctk.CTkFrame(tbl, fg_color="transparent")
        hdr_row.pack(fill="x")
        _cell(hdr_row, "順位 / 登記目的", COL0_W, bold=True, fg=HDR_FG, tc=HDR_TC)
        for p in all_persons:
            _cell(hdr_row, p[:8], COL_W, bold=True, fg=HDR_FG, tc=HDR_TC)
        _cell(hdr_row, "合計", 100, bold=True, fg=HDR_FG, tc=HDR_TC)

        for e in entries:
            row_f = ctk.CTkFrame(tbl, fg_color="transparent")
            row_f.pack(fill="x")

            _rank_cell(row_f, e, 2)

            owner_map: dict = {}
            _cum = e.get("_cumulative", {})
            if _cum:
                owner_map = dict(_cum)
            else:
                for o in e.get("所有者氏名", "").split(SEP):
                    o = o.strip()
                    if not o:
                        continue
                    name = _bare(o)
                    frac = _parse_frac(o)
                    if frac:
                        owner_map[name] = frac

            total_n = 0
            has_frac = False
            for p in all_persons:
                frac = owner_map.get(p)
                if frac:
                    has_frac = True
                    n_norm    = frac[0] * (global_d // frac[1])
                    cell_text = f"{global_d}分の{n_norm}"
                    cell_tc   = C["text"]
                    total_n  += n_norm
                else:
                    cell_text = "—"
                    cell_tc   = "#AAAACC"
                _cell(row_f, cell_text, COL_W, row_idx=2,
                      tc=cell_tc, bold=False, height=ROW_H)

            if has_frac:
                is_100   = (total_n == global_d)
                tot_text = f"{global_d}分の{total_n}"
                tot_tc   = C["text"] if is_100 else "#C0392B"
            else:
                tot_text, tot_tc = "—", C["muted"]
            _cell(row_f, tot_text, 100, row_idx=2,
                  tc=tot_tc, bold=False, height=ROW_H)

        cur_e = next((e for e in reversed(entries) if e.get("状態") == "現在"), None)
        if cur_e:
            ctk.CTkFrame(tbl, height=3, fg_color=C["green"]).pack(
                fill="x", padx=1, pady=(8, 2))

            sum_row = ctk.CTkFrame(tbl, fg_color="#EAF9EF", corner_radius=0)
            sum_row.pack(fill="x", pady=(0, 4))

            lbl_f = ctk.CTkFrame(sum_row, fg_color="#2B6B2B",
                                  corner_radius=0, width=COL0_W, height=ROW_H)
            lbl_f.pack_propagate(False)
            lbl_f.pack(side="left", padx=1, pady=1)
            ctk.CTkLabel(lbl_f, text="現在\n所有者",
                font=ctk.CTkFont("Yu Gothic UI", 13, "bold"),
                text_color="#FFFFFF", anchor="center",
            ).pack(fill="both", expand=True)

            cur_cum = cur_e.get("_cumulative", {})
            total_cur = 0
            has_cur_frac = False
            for p in all_persons:
                frac = cur_cum.get(p)
                if frac:
                    has_cur_frac = True
                    n_norm = frac[0] * (global_d // frac[1])
                    cell_t = f"{global_d}分の{n_norm}"
                    total_cur += n_norm
                    _cell(sum_row, cell_t, COL_W, row_idx=1,
                          tc="#1A6E35", bold=True, height=ROW_H)
                else:
                    _cell(sum_row, "—", COL_W, row_idx=1,
                          tc="#AAAACC", bold=False, height=ROW_H)

            if has_cur_frac:
                is_100c = (total_cur == global_d)
                tot_t   = f"{global_d}分の{total_cur}"
                tot_c   = "#1A6E35" if is_100c else "#C0392B"
            else:
                tot_t, tot_c = "—", C["muted"]
            _cell(sum_row, tot_t, 100, row_idx=1,
                  tc=tot_c, bold=True, height=ROW_H)

    # ---- 甲区カード（全履歴用） ----
    def _kouku_card(self, entry: dict, compact_bottom: bool = False,
                    paired_matsusho: bool = False):
        import re as _re

        def _shorten_date(s: str) -> str:
            if not s:
                return s
            era = {'明治': 'M', '大正': 'T', '昭和': 'S', '平成': 'H', '令和': 'R'}
            m = _re.search(r'(明治|大正|昭和|平成|令和)([0-9]+)年([0-9]+)月([0-9]+)日', s)
            if m:
                return f"{era.get(m.group(1), m.group(1))}{m.group(2)}.{m.group(3)}.{m.group(4)}"
            return s

        status     = entry.get("状態", "")
        is_current = (status == "現在")
        is_change  = (status == "変更")
        is_sashiosae          = (status == "差押")
        is_sashiosae_matsusho = (status == "差押抹消")
        is_past    = (status == "移転前")

        ORANGE = "#E07000"; PURPLE = "#7B4EA0"

        _moku = entry.get("登記の目的", "")
        fg     = "#F8F9FC"
        border = "#D0D5E0"
        tc     = C["subtext"]
        bar_color = "#D0D5E0"

        import tkinter as _tk

        _pady_b = 1 if compact_bottom else 2
        _padx   = (36, 28) if paired_matsusho else (24, 28)
        card = self._bordered_card(
            self._scroll, fg_color=fg, border_color=border,
            corner_radius=4, border_size=2 if is_current else 1,
            fill="x", padx=_padx, pady=(0, _pady_b),
        )

        _bw = 1
        row = _tk.Frame(card, bg=fg)
        row.pack(fill="x", padx=_bw, pady=(_bw, _bw))

        _tk.Frame(row, width=5, bg=bar_color).pack(side="left", fill="y")

        inner = _tk.Frame(row, bg=fg)
        inner.pack(side="left", fill="x", expand=True, padx=(6, 8), pady=(3, 3))

        hdr = _tk.Frame(inner, bg=fg)
        hdr.pack(fill="x")

        _rank_raw = entry.get('順位', '?')
        ctk.CTkLabel(
            hdr, text=f"{_rank_raw}番",
            font=ctk.CTkFont("Yu Gothic UI", 14, "normal"),
            text_color=C["muted"], width=54, anchor="w", fg_color="transparent",
        ).pack(side="left")

        if _moku:
            ctk.CTkLabel(
                hdr, text=_moku,
                font=ctk.CTkFont("Yu Gothic UI", 14),
                text_color=C["subtext"], anchor="w", fg_color="transparent",
            ).pack(side="left", padx=(4, 0))

        if is_current:
            badge_text, badge_fg = "現在", C["green"]
        elif is_change:
            badge_text, badge_fg = "変更", C["accent"]
        elif is_sashiosae:
            badge_text, badge_fg = "差押", ORANGE
        elif is_sashiosae_matsusho:
            badge_text, badge_fg = "差押抹消", PURPLE
        elif is_past:
            badge_text = "持分移転" if _re.search(r'持分', _moku) else ("合併/更生" if _re.search(r'合併|更生', _moku) else "所有権移転")
            badge_fg = "#7A8AA0"
        else:
            badge_text, badge_fg = "完了", "#A8AEBB"
        ctk.CTkLabel(
            hdr, text=f"  {badge_text}  ",
            font=ctk.CTkFont("Yu Gothic UI", 12),
            text_color="#FFFFFF", fg_color=badge_fg, corner_radius=3,
        ).pack(side="right")

        _recv_date = _shorten_date(entry.get("受付年月日", ""))
        _recv_no   = entry.get("受付番号", "")
        _recv_disp = f"{_recv_date} {_recv_no}".strip()

        if is_sashiosae or is_sashiosae_matsusho:
            _meigi      = entry.get("差押名義人", "")
            _cause_date = _shorten_date(entry.get("取得日", ""))
            _cause_text = entry.get("取得原因", "")
            _cause_disp = f"{_cause_date} {_cause_text}".strip() if (_cause_date or _cause_text) else ""

            if _meigi or _cause_disp or _recv_disp:
                info = _tk.Frame(inner, bg=fg)
                info.pack(fill="x")
                if _meigi:
                    ctk.CTkLabel(info, text=_meigi,
                        font=ctk.CTkFont("Yu Gothic UI", 13, "bold"),
                        text_color=tc, anchor="w", fg_color="transparent",
                    ).pack(side="left", padx=(0, 10))
                if _cause_disp:
                    ctk.CTkLabel(info, text=_cause_disp,
                        font=ctk.CTkFont("Yu Gothic UI", 12),
                        text_color=C["muted"], anchor="w", fg_color="transparent",
                    ).pack(side="left", padx=(0, 8))
                if _recv_disp:
                    ctk.CTkLabel(info, text=_recv_disp,
                        font=ctk.CTkFont("Yu Gothic UI", 12),
                        text_color=C["muted"], anchor="w", fg_color="transparent",
                    ).pack(side="left")
        else:
            _names_raw  = entry.get("所有者氏名", "")
            _addrs_raw  = entry.get("所有者住所", "")
            _addr1      = _addrs_raw.split(SEP)[0].strip() if _addrs_raw else ""
            _name_list  = [n.strip() for n in _names_raw.split(SEP) if n.strip()]
            _names_disp = "  /  ".join(_name_list) if _name_list else ""
            _cause_date = _shorten_date(entry.get("取得日", ""))
            _cause_text = entry.get("取得原因", "")
            _cause_disp = f"{_cause_date} {_cause_text}".strip() if (_cause_date or _cause_text) else ""

            if _addr1 or _names_disp or _cause_disp or _recv_disp:
                info = _tk.Frame(inner, bg=fg)
                info.pack(fill="x")
                if _addr1:
                    ctk.CTkLabel(info, text=_addr1,
                        font=ctk.CTkFont("Yu Gothic UI", 12),
                        text_color=C["muted"], anchor="w", wraplength=240,
                        fg_color="transparent",
                    ).pack(side="left", padx=(0, 8))
                if _names_disp:
                    ctk.CTkLabel(info, text=_names_disp,
                        font=ctk.CTkFont("Yu Gothic UI", 13, "bold" if is_current else "normal"),
                        text_color=tc, anchor="w", fg_color="transparent",
                    ).pack(side="left", padx=(0, 10))
                if _cause_disp:
                    ctk.CTkLabel(info, text=_cause_disp,
                        font=ctk.CTkFont("Yu Gothic UI", 12),
                        text_color=C["muted"], anchor="w", fg_color="transparent",
                    ).pack(side="left", padx=(0, 8))
                if _recv_disp:
                    ctk.CTkLabel(info, text=_recv_disp,
                        font=ctk.CTkFont("Yu Gothic UI", 12),
                        text_color=C["muted"], anchor="w", fg_color="transparent",
                    ).pack(side="left")

    # ---- 乙区カード（全履歴用） ----
    def _otsuku_card(self, entry: dict, tanpo_kigou: str = ""):
        is_fuki    = entry.get("_is_fuki", False)
        is_current = (entry.get("状態") == "現在")

        if is_fuki:
            fg     = "#F0F4FF" if is_current else "#EAECF4"
            border = "#8AA4D0" if is_current else "#B0B8CC"
            tc     = C["accent"] if is_current else C["muted"]
            card = self._bordered_card(
                self._scroll, fg_color=fg, border_color=border,
                corner_radius=4, border_size=1,
                fill="x", padx=(44, 48), pady=(0, 4),
            )
            hdr = ctk.CTkFrame(card, fg_color="transparent")
            hdr.pack(fill="x", padx=10, pady=(6, 2))
            rank_lbl = f"↳ 付記 {entry.get('順位', '')}"
            ctk.CTkLabel(hdr, text=rank_lbl,
                font=ctk.CTkFont("Yu Gothic UI", 11, "bold"),
                text_color=border, anchor="w",
            ).pack(side="left")
            mokuteki = entry.get("登記の目的", "")
            if mokuteki:
                ctk.CTkLabel(hdr, text=f"  {mokuteki}",
                    font=ctk.CTkFont("Yu Gothic UI", 12, "bold"),
                    text_color=tc, anchor="w",
                ).pack(side="left")
            if entry.get("抵当権者"):
                ctk.CTkLabel(hdr, text=f"  →  {entry['抵当権者']}",
                    font=ctk.CTkFont("Yu Gothic UI", 11),
                    text_color=tc, anchor="w",
                ).pack(side="left", padx=(4, 0))
            if is_current:
                ctk.CTkLabel(hdr, text="  移転済み  ",
                    font=ctk.CTkFont("Yu Gothic UI", 10),
                    text_color="#FFFFFF", fg_color="#8AA4D0", corner_radius=4,
                ).pack(side="right")
            recv_f = f"{entry.get('受付日','')} {entry.get('受付番号','')}".strip()
            if recv_f:
                self._card_row(card, "受付日", recv_f, tc)
            ctk.CTkFrame(card, height=1, fg_color=border).pack(
                fill="x", padx=8, pady=(2, 6))
            return

        fg     = "#FFFFFF"    if is_current else "#D8DCE8"
        border = C["accent"]  if is_current else "#A8AEBB"
        tc     = C["text"]    if is_current else C["muted"]

        card = self._bordered_card(
            self._scroll, fg_color=fg, border_color=border,
            corner_radius=6, border_size=2 if is_current else 1,
            fill="x", padx=(24, 28), pady=(0, 6),
        )

        hdr = ctk.CTkFrame(card, fg_color="transparent")
        hdr.pack(fill="x", padx=12, pady=(8, 4))

        bank_color = C["accent"] if is_current else C["muted"]
        _rank_o = entry.get('順位', '')
        if _rank_o:
            ctk.CTkLabel(hdr, text=f"順位 {_rank_o}番",
                font=ctk.CTkFont("Yu Gothic UI", 12, "bold"),
                text_color=bank_color, width=80, anchor="w",
            ).pack(side="left")
        main_label = entry.get('抵当権者') or entry.get('登記の目的') or '（詳細不明）'
        ctk.CTkLabel(hdr, text=f"  {main_label}",
            font=ctk.CTkFont("Yu Gothic UI", 14, "bold"),
            text_color=bank_color, anchor="w",
        ).pack(side="left")
        if entry.get('抵当権者') and entry.get('登記の目的'):
            ctk.CTkLabel(hdr, text=f"（{entry['登記の目的']}）",
                font=ctk.CTkFont("Yu Gothic UI", 11),
                text_color=C["subtext"] if is_current else C["muted"], anchor="w",
            ).pack(side="left", padx=(4, 0))

        status = entry.get("状態", "")
        if status == "抹消済み":
            badge_text, badge_fg = "抹消済み（完了）", C["warning"]
        else:
            badge_text, badge_fg = "現在（有効）", C["success"]
        ctk.CTkLabel(hdr, text=f"  {badge_text}  ",
            font=ctk.CTkFont("Yu Gothic UI", 11),
            text_color="#FFFFFF", fg_color=badge_fg, corner_radius=4,
        ).pack(side="right")

        if entry.get("債権額"):
            self._card_row(card, "借入金額", entry["債権額"], tc)
        if entry.get("債務者"):
            self._card_row(card, "債務者",   entry["債務者"], tc)
        recv = f"{entry.get('受付日','')} {entry.get('受付番号','')}".strip()
        if recv:
            self._card_row(card, "受付日", recv, tc)
        if not is_current:
            matsusho_str = f"{entry.get('抹消日', '')} {entry.get('抹消番号', '')}".strip()
            if matsusho_str:
                self._card_row(card, "抹消日", matsusho_str, tc)
        tanpo_ref = entry.get("共担目録番号", "") or tanpo_kigou
        if tanpo_ref:
            import re as _re2
            m_no = _re2.search(r'第([0-9][0-9/]*)号', tanpo_ref)
            display_no = f"第{m_no.group(1)}号" if m_no else tanpo_ref
            self._card_row(card, "共担目録", display_no, C["accent"])

        ctk.CTkFrame(card, height=1, fg_color=border).pack(
            fill="x", padx=10, pady=(4, 8))

    # ---- 共同担保グループカード ----
    def _tanpo_group_card(self, kigou: str, entries: list, otsuku_entry: dict = None):
        has_current = any(e.get("状態") == "現在" for e in entries)
        fg     = "#FFFFFF"   if has_current else "#D8DCE8"
        border = C["green"]  if has_current else "#A8AEBB"
        tc     = C["text"]   if has_current else C["muted"]

        card = self._bordered_card(
            self._scroll, fg_color=fg, border_color=border,
            corner_radius=6, border_size=2 if has_current else 1,
            fill="x", padx=(24, 28), pady=(0, 8),
        )

        hdr = ctk.CTkFrame(card, fg_color="transparent")
        hdr.pack(fill="x", padx=12, pady=(8, 4))
        hdr_color = C["header_bg"] if has_current else C["muted"]
        ctk.CTkLabel(hdr, text=kigou,
            font=ctk.CTkFont("Yu Gothic UI", 13, "bold"),
            text_color=hdr_color, anchor="w",
        ).pack(side="left")
        if otsuku_entry and otsuku_entry.get("抵当権者"):
            ctk.CTkLabel(hdr, text=f"  ←  {otsuku_entry['抵当権者']}（乙区）",
                font=ctk.CTkFont("Yu Gothic UI", 11),
                text_color=C["accent"] if has_current else C["muted"], anchor="w",
            ).pack(side="left", padx=(8, 0))
        badge_text = "有効" if has_current else "抹消済み"
        badge_fg   = C["success"] if has_current else C["warning"]
        ctk.CTkLabel(hdr, text=f"  {badge_text}  ",
            font=ctk.CTkFont("Yu Gothic UI", 11),
            text_color="#FFFFFF", fg_color=badge_fg, corner_radius=4,
        ).pack(side="right")

        ctk.CTkFrame(card, height=1, fg_color=border).pack(fill="x", padx=10, pady=(0, 4))

        for e in entries:
            row = ctk.CTkFrame(card, fg_color="transparent")
            row.pack(fill="x", padx=10, pady=2)
            ctk.CTkLabel(row, text=e.get("内容", ""),
                font=ctk.CTkFont(*self.F_SMALL),
                text_color=tc, anchor="w", wraplength=540,
            ).pack(side="left", fill="x", expand=True)

        ctk.CTkFrame(card, height=6, fg_color="transparent").pack()

    # ---- 共同担保目録インラインブロック ----
    def _tanpo_inline_block(self, kigou: str, entries: list, otsuku_entry: dict = None):
        is_current = (otsuku_entry.get("状態") == "現在") if otsuku_entry else False
        tc     = C["text"]   if is_current else C["muted"]
        border = C["accent"] if is_current else C["border"]
        bg     = C["surface2"] if is_current else "#EAECF3"

        block = self._bordered_card(
            self._scroll, fg_color=bg, border_color=border,
            corner_radius=4, border_size=1,
            fill="x", padx=(40, 44), pady=(0, 8),
        )

        hdr = ctk.CTkFrame(block, fg_color="transparent")
        hdr.pack(fill="x", padx=10, pady=(6, 2))
        ctk.CTkLabel(hdr, text="▸ 共同担保目録",
            font=ctk.CTkFont("Yu Gothic UI", 10, "bold"),
            text_color=C["muted"], anchor="w",
        ).pack(side="left")
        ctk.CTkLabel(hdr, text=f"  {kigou}",
            font=ctk.CTkFont("Yu Gothic UI", 10),
            text_color=C["accent"] if is_current else C["muted"], anchor="w",
        ).pack(side="left")

        ctk.CTkFrame(block, height=1, fg_color=border).pack(fill="x", padx=8, pady=(2, 3))

        for e in entries:
            row = ctk.CTkFrame(block, fg_color="transparent")
            row.pack(fill="x", padx=8, pady=1)
            ctk.CTkLabel(row, text=e.get("内容", ""),
                font=ctk.CTkFont(*self.F_SMALL),
                text_color=tc, anchor="w", wraplength=520,
            ).pack(side="left", fill="x", expand=True)

        ctk.CTkFrame(block, height=4, fg_color="transparent").pack()

    def _on_error(self, msg: str):
        self._prog.stop()
        self._prog.set(0)
        self._status_var.set(f"エラー: {msg[:80]}")

    # ---- CSV出力 ----
    def _export_csv(self):
        if not self._result:
            return
        import re
        record   = self._result["record"]
        doc_type = self._result["doc_type"]
        history  = self._result.get("history", {})
        pdf_path = self._result.get("pdf_path")

        default  = f"spot_{doc_type}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        _csv_dir = Path(sys.executable).parent / "output_csv" if getattr(sys, "frozen", False) else Path(__file__).parent.parent / "output_csv"
        _csv_dir.mkdir(exist_ok=True)
        path = filedialog.asksaveasfilename(
            title="CSVを保存",
            defaultextension=".csv",
            filetypes=[("CSV", "*.csv")],
            initialfile=default,
            initialdir=str(_csv_dir),
        )
        if not path:
            return

        COLUMNS = [
            '物件フォルダ', 'PDFファイル名', '不動産番号', '種別', '地目種類',
            '所在', '地番_家屋番号', '地積_床面積',
            '区分', '順位', '登記の目的', '受付年月日', '受付番号',
            '所有者_関係者名', '住所', '持分', '持分数値',
            '状態', '名称変更後', '元の氏名',
            '債権額', '債務者', '共担目録番号',
            'リスクフラグ', '確認済', '備考',
        ]

        RISK_YEAR = 1965

        _HOUJIN_RE = re.compile(
            r'株式会社|有限会社|合同会社|合資会社|合名会社'
            r'|一般財団|公益財団|一般社団|公益社団'
            r'|学校法人|社会福祉法人|医療法人|宗教法人'
            r'|独立行政法人|地方公共団体|国$|県$|市$|町$|村$'
            r'|銀行|信用金庫|農業協同組合|農協|漁業協同'
        )

        def _is_houjin(name):
            return bool(_HOUJIN_RE.search(name))

        def _parse_year(date_str):
            if not date_str:
                return None
            m = re.search(r'(19|20)(\d{2})', date_str)
            if m:
                return int(m.group(0))
            for era, base in [('明治', 1867), ('大正', 1911), ('昭和', 1925),
                               ('平成', 1988), ('令和', 2018)]:
                m2 = re.search(era + r'([0-9]+)', date_str)
                if m2:
                    return base + int(m2.group(1))
            return None

        def _risk_flag(name, date_str, status):
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

        def _parse_mochi(name_raw):
            m = re.search(r'[(（]([^)）]*\d+分の\d+[^)）]*)[)）]', name_raw)
            if m:
                frac_str = m.group(1)
                clean    = re.sub(r'[(（][^)）]*[)）]', '', name_raw).strip()
                fm       = re.search(r'(\d+)分の(\d+)', frac_str)
                f_val    = round(int(fm.group(2)) / int(fm.group(1)), 6) if fm else ''
                return clean, frac_str, f_val
            m2 = re.search(r'持分\s*(\d+分の\d+)', name_raw)
            if m2:
                frac_str = m2.group(1)
                clean    = re.sub(r'持分\s*\d+分の\d+', '', name_raw).strip()
                fm       = re.search(r'(\d+)分の(\d+)', frac_str)
                f_val    = round(int(fm.group(2)) / int(fm.group(1)), 6) if fm else ''
                return clean or name_raw.strip(), frac_str, f_val
            return name_raw.strip(), '', ''

        base = {
            '物件フォルダ':  pdf_path.parent.name if pdf_path else '',
            'PDFファイル名': pdf_path.name if pdf_path else record.get('ファイル名', ''),
            '不動産番号':    record.get('不動産番号', ''),
            '種別':          '土地' if doc_type == 'tochi' else '建物',
            '地目種類':      record.get('地目', '') or record.get('種類', ''),
            '所在':          record.get('所在', ''),
            '地番_家屋番号': record.get('地番', '') or record.get('家屋番号', ''),
            '地積_床面積':   record.get('地積_m2', '') or record.get('床面積_m2', ''),
            '確認済':        '',
            '備考':          '',
        }

        rows = []

        for b in history.get('kouku', []):
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

        for e in history.get('otsuku', []):
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

        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=COLUMNS, extrasaction='ignore')
            w.writeheader()
            w.writerows(rows)

        messagebox.showinfo("保存完了", f"CSVを保存しました:\n{path}\n（{len(rows)}行）")
