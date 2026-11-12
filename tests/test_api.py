import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient  # noqa: E402

from invoiceiq.api import app  # noqa: E402
from invoiceiq.synth import COMPANY, generate, render  # noqa: E402


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("INVOICEIQ_API_KEYS", "k1")
    return TestClient(app)


def pdfs(n=2):
    return [("files", (d.file, render(d), "application/pdf")) for d in generate(n, 6, 0)]


def test_health(client):
    assert client.get("/health").json()["status"] == "ok"


def test_requires_key(client):
    assert client.post("/v1/invoices/check", files=pdfs()).status_code == 401


def test_check_returns_invoices_and_summary(client):
    r = client.post("/v1/invoices/check", files=pdfs(), data={"company_gstin": COMPANY[1]},
                    headers={"X-API-Key": "k1"})  # fmt: skip
    body = r.json()
    assert r.status_code == 200 and body["summary"]["invoices"] == 2


def test_rejects_non_pdf(client):
    r = client.post("/v1/invoices/check", files=[("files", ("x.pdf", b"hello", "text/plain"))],
                    headers={"X-API-Key": "k1"})  # fmt: skip
    assert r.status_code == 415
