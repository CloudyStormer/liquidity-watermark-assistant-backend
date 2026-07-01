from io import BytesIO
from uuid import uuid4

from fastapi.testclient import TestClient
from PIL import Image

from app.core.config import settings
from app.db import init_db
from app.main import app

settings.database_path = "storage/test_app.db"
settings.storage_dir = "storage/test_files"
init_db()

client = TestClient(app)


class FakeWeappResponse:
    def __init__(self, payload: dict):
        self.payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self.payload


def test_health_check() -> None:
    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_login_profile_rating_feedback_and_logs() -> None:
    openid = f"openid_test_user_{uuid4().hex}"

    login_response = client.post(
        "/api/users/login",
        json={"openid": openid, "nickname": "tester"},
    )
    assert login_response.status_code == 200
    assert login_response.json()["openid"] == openid

    rating_response = client.post(
        "/api/ratings",
        json={"openid": openid, "score": 5, "comment": "很好用"},
    )
    assert rating_response.status_code == 201
    assert rating_response.json()["score"] == 5

    invalid_rating_response = client.post(
        "/api/ratings",
        json={"openid": openid, "score": 6},
    )
    assert invalid_rating_response.status_code == 422

    feedback_response = client.post(
        "/api/feedback",
        json={"openid": openid, "type": "suggestion", "content": "希望支持框选水印区域"},
    )
    assert feedback_response.status_code == 201

    profile_response = client.get(f"/api/users/{openid}/profile")
    assert profile_response.status_code == 200
    assert profile_response.json()["ratings_count"] == 1
    assert profile_response.json()["feedback_count"] == 1

    logs_response = client.get(f"/api/users/{openid}/logs")
    assert logs_response.status_code == 200
    actions = {item["action"] for item in logs_response.json()}
    assert "user_login" in actions
    assert "rating_created" in actions
    assert "feedback_created" in actions


def test_weapp_login_exchanges_code_and_upserts_user(monkeypatch) -> None:
    openid = f"weapp_openid_{uuid4().hex}"
    monkeypatch.setattr(settings, "weapp_appid", "wx_test_appid")
    monkeypatch.setattr(settings, "weapp_secret", "wx_test_secret")

    def fake_get(url, *, params, timeout):
        assert url == settings.weapp_code2session_url
        assert params["appid"] == "wx_test_appid"
        assert params["secret"] == "wx_test_secret"
        assert params["js_code"] == "code_123"
        assert params["grant_type"] == "authorization_code"
        assert timeout == settings.weapp_login_timeout_seconds
        return FakeWeappResponse(
            {
                "openid": openid,
                "session_key": "session_key_value",
                "unionid": "unionid_value",
            }
        )

    monkeypatch.setattr("app.services.weapp_auth.httpx.get", fake_get)

    response = client.post(
        "/api/users/weapp-login",
        json={"code": "code_123", "nickname": "微信用户"},
    )

    assert response.status_code == 200
    assert response.json()["openid"] == openid
    profile_response = client.get(f"/api/users/{openid}/profile")
    assert profile_response.status_code == 200


def test_weapp_login_requires_backend_config(monkeypatch) -> None:
    monkeypatch.setattr(settings, "weapp_appid", "")
    monkeypatch.setattr(settings, "weapp_secret", "")

    response = client.post("/api/users/weapp-login", json={"code": "code_123"})

    assert response.status_code == 503


def test_daily_quota_defaults_to_three_and_can_grant() -> None:
    openid = f"openid_quota_{uuid4().hex}"
    login_response = client.post("/api/users/login", json={"openid": openid})
    assert login_response.status_code == 200

    quota_response = client.get(f"/api/users/{openid}/quota")
    assert quota_response.status_code == 200
    quota = quota_response.json()
    assert quota["total"] == 3
    assert quota["used"] == 0
    assert quota["remaining"] == 3

    grant_response = client.post(f"/api/users/{openid}/quota/grant", json={"extra": 2})
    assert grant_response.status_code == 200
    assert grant_response.json()["total"] == 5
    assert grant_response.json()["remaining"] == 5


def test_upload_requires_login() -> None:
    image_buffer = BytesIO()
    Image.new("RGB", (64, 64), color="white").save(image_buffer, format="PNG")
    image_buffer.seek(0)

    response = client.post(
        "/api/media/jobs/upload",
        data={
            "openid": f"openid_not_logged_in_{uuid4().hex}",
            "rights_confirmed": "true",
            "method": "blur",
        },
        files={"file": ("sample.png", image_buffer, "image/png")},
    )

    assert response.status_code == 401


def test_upload_requires_rights_confirmation() -> None:
    image_buffer = BytesIO()
    Image.new("RGB", (64, 64), color="white").save(image_buffer, format="PNG")
    image_buffer.seek(0)

    openid = f"openid_upload_reject_{uuid4().hex}"
    client.post("/api/users/login", json={"openid": openid})

    response = client.post(
        "/api/media/jobs/upload",
        data={
            "openid": openid,
            "rights_confirmed": "false",
            "method": "blur",
        },
        files={"file": ("sample.png", image_buffer, "image/png")},
    )

    assert response.status_code == 422


def test_image_upload_job_returns_result_md5() -> None:
    image_buffer = BytesIO()
    Image.new("RGB", (96, 80), color="white").save(image_buffer, format="PNG")
    image_buffer.seek(0)
    openid = f"openid_upload_success_{uuid4().hex}"
    client.post("/api/users/login", json={"openid": openid})

    response = client.post(
        "/api/media/jobs/upload",
        data={
            "openid": openid,
            "rights_confirmed": "true",
            "method": "blur",
            "regions_json": '[{"x": 0, "y": 0, "width": 32, "height": 24}]',
        },
        files={"file": ("sample.png", image_buffer, "image/png")},
    )

    assert response.status_code == 202
    job = response.json()
    job_response = client.get(f"/api/media/jobs/{job['id']}?openid={openid}")

    assert job_response.status_code == 200
    stored_job = job_response.json()
    assert stored_job["status"] == "succeeded"
    assert stored_job["result_url"]
    assert len(stored_job["result_md5"]) == 32

    quota_response = client.get(f"/api/users/{openid}/quota")
    assert quota_response.status_code == 200
    assert quota_response.json()["used"] == 1
    assert quota_response.json()["remaining"] == 2


def test_md5_upload_creates_unique_download() -> None:
    openid = f"openid_md5_{uuid4().hex}"
    client.post("/api/users/login", json={"openid": openid})
    video_buffer = BytesIO(b"fake mp4 payload")

    response = client.post(
        "/api/media/md5/upload",
        data={"openid": openid, "rights_confirmed": "true"},
        files={"file": ("demo.mp4", video_buffer, "video/mp4")},
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["original_md5"] != payload["unique_md5"]
    assert len(payload["original_md5"]) == 32
    assert len(payload["unique_md5"]) == 32

    download_response = client.get(payload["result_url"])
    assert download_response.status_code == 200
    assert download_response.content.endswith(b"\n")
