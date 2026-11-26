from fastapi.testclient import TestClient
from test_restart_recovery_postgres import World, start_app


def test_lists_existing_environments_newest_first_and_honours_limit(engine, clock) -> None:
    world = World(engine, clock)
    ids = []
    for index, name in enumerate(["first", "second", "third"]):
        clock.now = 1_000 + index * 10
        ids.append(world.environment(name)[0])
    with TestClient(start_app(engine, clock)) as client:
        body = client.get("/api/v1/environments").json()
        limited = client.get("/api/v1/environments", params={"limit": 2}).json()
        invalid = client.get("/api/v1/environments", params={"limit": 0})
    assert [item["environment_id"] for item in body["items"]] == list(reversed(ids))
    assert [item["name"] for item in limited["items"]] == ["third", "second"]
    assert invalid.status_code == 422
