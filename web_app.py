"""Xserver VPS向けの登記簿PDF解析Webアプリ。"""
from __future__ import annotations

import csv
import hashlib
import io
import os
import re
import tempfile
from pathlib import Path

from flask import Flask, Response, jsonify, render_template, request
from werkzeug.utils import secure_filename

SCRIPTS_DIR = Path(__file__).parent / "scripts"
import sys
sys.path.insert(0, str(SCRIPTS_DIR))

from agents.tatemono_agent import TatemonoAgent
from agents.tochi_agent import TochiAgent
from touki_parser import CSV_FIELDS_TATEMONO, CSV_FIELDS_TOCHI, detect_type, extract_text, split_sections

PREFIX = os.environ.get("TOUKI_URL_PREFIX", "/touki").rstrip("/")
MAX_FILES = int(os.environ.get("TOUKI_MAX_FILES", "20"))

app = Flask(__name__, template_folder="web/templates", static_folder="web/static",
            static_url_path=f"{PREFIX}/static")
app.config.update(
    MAX_CONTENT_LENGTH=int(os.environ.get("TOUKI_MAX_UPLOAD_MB", "50")) * 1024 * 1024,
    JSON_AS_ASCII=False,
)


def _json_safe(value):
    if isinstance(value, Path):
        return value.name
    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items()
                if not str(k).startswith("_") or k == "_is_fuki"}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    return value


def _analyze(path: Path) -> dict:
    text = extract_text(path)
    doc_type = detect_type(path.name, text)
    if doc_type not in {"tochi", "tatemono"}:
        raise ValueError("土地・建物の登記簿として判定できませんでした")
    digest = hashlib.md5(path.read_bytes()).hexdigest()
    agent = TochiAgent() if doc_type == "tochi" else TatemonoAgent()
    result = agent.run(path, digest)
    if result is None:
        raise ValueError("PDFの解析に失敗しました")
    sections = split_sections(text)
    history = result.get("history", {})
    warnings = []
    if re.search(r"抵当|地上権|賃借権|質権|差押|地役権|永小作権", sections["otsuku"]) and not history.get("otsuku"):
        warnings.append("乙区に権利の記載がありますが、明細を抽出できませんでした。原本を確認してください。")
    if re.search(r"土地|建物|区分建物", sections["tanpo"]) and not history.get("tanpo"):
        warnings.append("共同担保目録に記載がありますが、明細を抽出できませんでした。原本を確認してください。")
    result["warnings"] = warnings
    return _json_safe(result)


@app.get(f"{PREFIX}/")
def index():
    return render_template("index.html", prefix=PREFIX)


@app.get(f"{PREFIX}/healthz")
def healthz():
    return jsonify(status="ok")


@app.post(f"{PREFIX}/api/analyze")
def analyze():
    files = request.files.getlist("files")
    if not files or not any(item.filename for item in files):
        return jsonify(error="PDFを選択してください"), 400
    if len(files) > MAX_FILES:
        return jsonify(error=f"一度に解析できるのは{MAX_FILES}件までです"), 400

    if not any((upload.filename or "").lower().endswith(".pdf") for upload in files):
        return jsonify(results=[{"filename": upload.filename, "error": "PDFのみ対応しています"}
                                for upload in files])
    results = []
    with tempfile.TemporaryDirectory(prefix="touki-",
                                     dir=os.environ.get("TOUKI_TMP_DIR")) as tmp:
        for index, upload in enumerate(files):
            if not (upload.filename or "").lower().endswith(".pdf"):
                results.append({"filename": upload.filename, "error": "PDFのみ対応しています"})
                continue
            filename = secure_filename(upload.filename or "document.pdf")
            path = Path(tmp) / f"{index:03d}-{filename}"
            upload.save(path)
            try:
                result = _analyze(path)
                result["filename"] = upload.filename
                results.append(result)
            except Exception as exc:
                results.append({"filename": upload.filename, "error": str(exc)})
    return jsonify(results=results)


@app.post(f"{PREFIX}/api/export.csv")
def export_csv():
    payload = request.get_json(silent=True) or {}
    results = payload.get("results", [])
    records = [item.get("record", {}) for item in results if item.get("record")]
    fields = list(dict.fromkeys(CSV_FIELDS_TOCHI + CSV_FIELDS_TATEMONO))
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=fields, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(records)
    body = "\ufeff" + out.getvalue()
    return Response(body, mimetype="text/csv; charset=utf-8", headers={
        "Content-Disposition": "attachment; filename=touki_results.csv"
    })


@app.post(f"{PREFIX}/api/export-history.csv")
def export_history_csv():
    """甲区・乙区・共同担保の全明細を、項目の欠落なく縦持ちCSVにする。"""
    payload = request.get_json(silent=True) or {}
    rows = []
    for item in payload.get("results", []):
        for section, entries in (item.get("history") or {}).items():
            for entry in entries:
                row = {"ファイル名": item.get("filename", ""), "区分": section}
                row.update({key: value for key, value in entry.items()
                            if not key.startswith("_")})
                rows.append(row)
    fields = list(dict.fromkeys(key for row in rows for key in row))
    if not fields:
        fields = ["ファイル名", "区分"]
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=fields, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    return Response("\ufeff" + out.getvalue(), mimetype="text/csv; charset=utf-8",
                    headers={"Content-Disposition": "attachment; filename=touki_history.csv"})


@app.errorhandler(413)
def too_large(_error):
    return jsonify(error="アップロード上限を超えています"), 413


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(os.environ.get("PORT", "8510")))
