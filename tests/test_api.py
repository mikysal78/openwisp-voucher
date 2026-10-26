"""API con un server finto: si controlla cosa viene inviato e come si leggono le risposte."""

import json
from datetime import date

import pytest
import requests

from openwisp_voucher.api import BATCH_SYNC_MAX, ApiError, OpenWispApi, normalize_server


class FakeResponse:
    def __init__(self, status, data=None):
        self.status_code = status
        self._data = data
        self.content = b"" if data is None else json.dumps(data).encode()
        self.reason = "reason"

    def json(self):
        if self._data is None:
            raise ValueError
        return self._data


class FakeServer:
    def __init__(self):
        self.calls = []
        self.routes = {}

    def add(self, method, url, status, data=None):
        self.routes[(method, url)] = FakeResponse(status, data)

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        try:
            return self.routes[(method, url)]
        except KeyError:
            return FakeResponse(404, {"detail": "Not found."})


@pytest.fixture
def server(monkeypatch):
    fake = FakeServer()
    monkeypatch.setattr(requests.Session, "request", lambda self, m, u, **kw: fake.request(m, u, **kw))
    return fake


BASE = "https://ow.example.org/api/v1/"


def test_normalize_server():
    assert normalize_server("ow.example.org/") == "https://ow.example.org"
    assert normalize_server("https://ow.example.org/admin/") == "https://ow.example.org"
    with pytest.raises(ApiError):
        normalize_server("http://ow.example.org")
    with pytest.raises(ApiError):
        normalize_server("  ")


def test_token_and_bearer(server):
    server.add("POST", BASE + "users/token/", 200, {"token": "abc"})
    server.add("GET", BASE + "users/organization/", 200, {"count": 1, "next": None, "results": [{"slug": "o"}]})
    api = OpenWispApi("ow.example.org")
    assert api.obtain_token("u", "p") == "abc"
    method, url, kwargs = server.calls[0]
    assert kwargs["json"] == {"username": "u", "password": "p"}
    assert "Authorization" not in kwargs["headers"]
    assert api.organizations() == [{"slug": "o"}]
    assert server.calls[1][2]["headers"]["Authorization"] == "Bearer abc"


def test_pagination_stays_on_server(server):
    server.add("GET", BASE + "users/organization/", 200,
               {"next": BASE + "users/organization/?page=2", "results": [{"slug": "a"}]})
    server.add("GET", BASE + "users/organization/?page=2", 200, {"next": None, "results": [{"slug": "b"}]})
    api = OpenWispApi("ow.example.org", "t")
    assert [o["slug"] for o in api.organizations()] == ["a", "b"]

    server.add("GET", BASE + "users/organization/", 200,
               {"next": "https://evil.example.com/x", "results": []})
    with pytest.raises(ApiError):
        api.organizations()


def test_current_user_exact_match(server):
    server.add("GET", BASE + "users/user/", 200, {"next": None, "results": [
        {"username": "admin2", "is_superuser": False},
        {"username": "admin", "is_superuser": True},
    ]})
    api = OpenWispApi("ow.example.org", "t")
    assert api.current_user("admin")["is_superuser"] is True
    assert server.calls[0][2]["params"] == {"search": "admin"}


def test_radius_groups_filtered_by_org(server):
    server.add("GET", BASE + "radius/group/", 200, {"next": None, "results": [
        {"id": "1", "name": "a-users", "organization": "A"},
        {"id": "2", "name": "b-users", "organization": "B"},
    ]})
    api = OpenWispApi("ow.example.org", "t")
    assert [g["id"] for g in api.radius_groups("B")] == ["2"]


def test_create_series(server):
    server.add("POST", BASE + "radius/batch/", 201, {
        "users": [{"id": "u1", "username": "ospite1"}, {"id": "u2", "username": "ospite2"}],
        "user_credentials": [["ospite1", "pw1"], ["ospite2", "pw2"]],
    })
    api = OpenWispApi("ow.example.org", "t")
    creds = api.create_series("hotel", "b1", "ospite", 2, date(2026, 10, 28), "g1", "camera 3")
    assert [(c.username, c.password, c.user_id) for c in creds] == [
        ("ospite1", "pw1", "u1"), ("ospite2", "pw2", "u2")]
    body = server.calls[0][2]["json"]
    assert body["strategy"] == "prefix"
    assert body["organization_slug"] == "hotel"
    assert body["number_of_users"] == 2
    assert body["expiration_date"] == "2026-10-28"
    assert body["group"] == "g1"
    with pytest.raises(ValueError):
        api.create_series("hotel", "b", "x", BATCH_SYNC_MAX + 1, date(2026, 10, 28))


def test_create_user_uses_cleartext_csv(server):
    server.add("POST", BASE + "radius/batch/", 201, {"users": [{"id": "u9", "username": "pippo1"}]})
    api = OpenWispApi("ow.example.org", "t")
    cred = api.create_user("hotel", "b2", "pippo", "segreta9", "p@example.org", date(2026, 10, 28), "Pippo", "Rossi")
    # nome già preso: il server ha aggiunto un numero
    assert (cred.username, cred.password, cred.user_id) == ("pippo1", "segreta9", "u9")
    kwargs = server.calls[0][2]
    assert kwargs["data"]["strategy"] == "csv"
    name, content, mime = kwargs["files"]["csvfile"]
    assert content.decode().strip() == "pippo,cleartext$segreta9,p@example.org,Pippo,Rossi"


def test_errors_are_readable(server):
    server.add("POST", BASE + "radius/batch/", 400, {"expiration_date": ["Expiration date cannot be in the past."]})
    api = OpenWispApi("ow.example.org", "t")
    with pytest.raises(ApiError) as error:
        api.create_series("hotel", "b", "x", 1, date(2026, 10, 28))
    assert "expiration_date" in str(error.value)
    assert error.value.status == 400

    server.add("GET", BASE + "users/user/x/", 401, {"detail": "Invalid token."})
    with pytest.raises(ApiError) as error:
        api.user("x")
    assert error.value.status == 401


def test_set_active(server):
    server.add("PATCH", BASE + "users/user/u1/", 200, {"is_active": False})
    api = OpenWispApi("ow.example.org", "t")
    api.set_active("u1", False)
    assert server.calls[0][2]["json"] == {"is_active": False}
