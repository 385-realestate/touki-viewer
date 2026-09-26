"""Xserver VPS向けの登記簿PDF解析Webアプリ。"""
from __future__ import annotations

import csv
import hashlib
import io
import os
import tempfile
from pathlib import Path

from flask import Flask, Response, jsonify, render_template, request
from werkzeug.utils import secure_filename

SCRIPTS_DIR = Path(__file__).parent / "scripts"
import sys
sys.path.insert(0, str(SCRIPTS_DIR))

from agents.tatemono_agent import TatemonoAgent
from agents.tochi_agent import TochiAgent
from touki_parser import CSV_FIELDS_TATEMONO, CSV_FIELDS_TOCHI, detect_type, extract_text

PREFIX = os.environ.get("TOUKI_URL_PREFIX", "/touki").rstrip("/")
MAX_FILES = int(os.environ.get("TOUKI_MAX_FILES", "20"))

app = Flask(__name__, template_folder="web/templates")
app.config.update(
    MAX_CONTENT_LENGTH=int(os.environ.get("TOUKI_MAX_UPLOAD_MB", "50")) * 1024 * 1024,
    JSON_AS_ASCII=False,
)


def _json_safe(value):
    if isinstance(value, Path):
        return value.name
    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items() if not str(k).startswith("_")}
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

    results = []
    pdf_files = []
    for upload in files:
        if not (upload.filename or "").lower().endswith(".pdf"):
            results.append({"filename": upload.filename, "error": "PDFのみ対応しています"})
        else:
            pdf_files.append(upload)
    if not pdf_files:
        return jsonify(results=results)

    with tempfile.TemporaryDirectory(prefix="touki-") as tmp:
        for index, upload in enumerate(pdf_files):
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


@app.errorhandler(413)
def too_large(_error):
    return jsonify(error="アップロード上限を超えています"), 413


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(os.environ.get("PORT", "8510")))
