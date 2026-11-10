"""Each visitor works in their own workspace.

Before workspaces, a quantity corrected by one visitor was corrected for
everyone, and an upload appeared in every visitor's list. These pin that a
correction stays in the workspace that made it, that the shared project is
never touched, and that a token cannot be forged.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from ecarbon.api import main
from ecarbon.api.main import app

LINE = "ln-slab-main"


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def _guest(client) -> dict[str, str]:
    token = client.post("/auth/guest").json()["token"]
    return {"X-Ecarbon-Session": token}


def _qty(client, headers, line=LINE):
    lines = client.get("/projects/demo/takeoff", headers=headers).json()["lines"]
    line = next(x for x in lines if x["id"] == line)
    return line["user_override"], line["quantity"]


def test_a_correction_stays_in_its_workspace(client):
    alice, bob = _guest(client), _guest(client)
    shared_total = client.get("/projects/demo/carbon").json()["total_kg_co2e"]

    r = client.post(f"/projects/demo/lines/{LINE}", json={"quantity": 99.0}, headers=alice)
    assert r.status_code == 200
    alice_total = r.json()["total_kg_co2e"]
    assert alice_total != shared_total

    assert _qty(client, alice)[0] == 99.0
    # Bob, and anyone without a token, still see the drawing's figure.
    assert _qty(client, bob)[0] is None
    assert _qty(client, {})[0] is None
    assert client.get("/projects/demo/carbon", headers=bob).json()["total_kg_co2e"] == shared_total
    # The shared project itself was never written to.
    assert main._PROJECTS["demo"].takeoff.line(LINE).user_override is None

    # Clearing it in Alice's workspace restores the shared figure for her.
    client.post(f"/projects/demo/lines/{LINE}", json={"quantity": None}, headers=alice)
    assert client.get("/projects/demo/carbon", headers=alice).json()["total_kg_co2e"] == shared_total


def test_a_forged_or_tampered_token_is_the_public_workspace(client):
    alice = _guest(client)
    client.post(f"/projects/demo/lines/{LINE}", json={"quantity": 77.0}, headers=alice)
    token = alice["X-Ecarbon-Session"]
    workspace = token.rpartition(".")[0]

    forged = {"X-Ecarbon-Session": f"{workspace}.{'0' * 40}"}
    assert _qty(client, forged)[0] is None
    assert client.get("/auth/me", headers=forged).json() is None
    # The same token in the query string works, for <img src> and downloads.
    assert client.get(f"/auth/me?session={token}").json()["guest"] is True


def test_accounts_sign_up_and_in(client):
    name = "judge-" + main.secrets.token_hex(3)
    r = client.post("/auth/signup", json={"username": name, "password": "landmark"})
    assert r.status_code == 201 and r.json()["name"] == name
    assert client.post("/auth/signup", json={"username": name, "password": "x" * 8}).status_code == 409
    assert client.post("/auth/login", json={"username": name, "password": "wrong!"}).status_code == 401
    ok = client.post("/auth/login", json={"username": name, "password": "landmark"})
    assert ok.status_code == 200
    me = client.get("/auth/me", headers={"X-Ecarbon-Session": ok.json()["token"]}).json()
    assert me == {"token": ok.json()["token"], "name": name, "guest": False}


def test_bad_account_details_are_refused(client):
    assert client.post("/auth/signup", json={"username": "a", "password": "longenough"}).status_code == 422
    assert client.post("/auth/signup", json={"username": "fine-name", "password": "123"}).status_code == 422


def test_an_upload_is_visible_only_to_its_owner(client):
    alice, bob = _guest(client), _guest(client)
    # Registered the way the upload endpoint registers one, without a PDF.
    held = main._PROJECTS["demo"]
    main._PROJECTS["upload-test-x"] = main.Project(
        id="upload-test-x", takeoff=held.takeoff.model_copy(deep=True)
    )
    main._OWNER["upload-test-x"] = alice["X-Ecarbon-Session"].rpartition(".")[0]
    try:
        assert client.get("/projects/upload-test-x/takeoff", headers=alice).status_code == 200
        assert client.get("/projects/upload-test-x/takeoff", headers=bob).status_code == 404
        assert client.get("/projects/upload-test-x/takeoff").status_code == 404
        ids = lambda h: {p["id"] for p in client.get("/projects", headers=h).json()}  # noqa: E731
        assert "upload-test-x" in ids(alice)
        assert "upload-test-x" not in ids(bob)
    finally:
        main._PROJECTS.pop("upload-test-x", None)
        main._OWNER.pop("upload-test-x", None)
