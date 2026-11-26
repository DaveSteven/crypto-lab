from crypto_lab.api import __main__ as api_main


def test_api_defaults_to_loopback_and_single_worker(monkeypatch) -> None:
    captured = {}
    monkeypatch.delenv("CRYPTO_LAB_API_HOST", raising=False)
    monkeypatch.delenv("CRYPTO_LAB_API_PORT", raising=False)
    monkeypatch.setattr(api_main, "create_app", lambda: "app")
    monkeypatch.setattr(api_main.uvicorn, "run", lambda *args, **kwargs: captured.update(kwargs))
    api_main.main()
    assert captured == {"host": "127.0.0.1", "port": 8642, "workers": 1}


def test_api_host_and_port_are_explicitly_configurable_for_internal_container_network(
    monkeypatch,
) -> None:
    captured = {}
    monkeypatch.setenv("CRYPTO_LAB_API_HOST", "0.0.0.0")
    monkeypatch.setenv("CRYPTO_LAB_API_PORT", "9000")
    monkeypatch.setattr(api_main, "create_app", lambda: "app")
    monkeypatch.setattr(api_main.uvicorn, "run", lambda *args, **kwargs: captured.update(kwargs))
    api_main.main()
    assert captured == {"host": "0.0.0.0", "port": 9000, "workers": 1}
