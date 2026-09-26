import csv
import io

from web_app import app


def test_healthz():
    client = app.test_client()
    response = client.get("/touki/healthz")
    assert response.status_code == 200
    assert response.get_json() == {"status": "ok"}


def test_rejects_non_pdf():
    client = app.test_client()
    response = client.post(
        "/touki/api/analyze",
        data={"files": (io.BytesIO(b"plain text"), "note.txt")},
        content_type="multipart/form-data",
    )
    assert response.status_code == 200
    assert response.get_json()["results"][0]["error"] == "PDFのみ対応しています"


def test_csv_export_has_bom():
    client = app.test_client()
    response = client.post("/touki/api/export.csv", json={"results": [{"record": {"所在": "浜松市"}}]})
    assert response.status_code == 200
    assert response.data.startswith(b"\xef\xbb\xbf")


def test_index_loads_full_viewer_assets():
    client = app.test_client()
    response = client.get("/touki/")
    assert response.status_code == 200
    assert b"/touki/static/app.js" in response.data
    script = client.get("/touki/static/app.js")
    assert script.status_code == 200
    for label in ("甲区", "乙区", "共同担保目録"):
        assert label.encode("utf-8") in script.data


def test_full_history_csv_includes_all_sections_and_fields():
    client = app.test_client()
    response = client.post("/touki/api/export-history.csv", json={"results": [{
        "filename": "sample.pdf", "history": {
            "kouku": [{"順位": "1", "所有者氏名": "甲"}],
            "otsuku": [{"順位": "2", "抵当権者": "乙", "共担目録番号": "第123号"}],
            "tanpo": [{"記号及び番号": "第123号", "内容": "土地"}],
        },
    }]})
    assert response.status_code == 200
    rows = list(csv.DictReader(io.StringIO(response.get_data(as_text=True).lstrip("\ufeff"))))
    assert [row["区分"] for row in rows] == ["kouku", "otsuku", "tanpo"]
    assert rows[1]["共担目録番号"] == "第123号"
    assert rows[2]["内容"] == "土地"
