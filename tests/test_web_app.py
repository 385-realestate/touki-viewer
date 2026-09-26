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
