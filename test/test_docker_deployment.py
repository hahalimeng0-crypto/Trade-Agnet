from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]


def test_root_compose_is_a_safe_single_command_application_stack():
    compose = yaml.safe_load((ROOT / "compose.yaml").read_text(encoding="utf-8"))
    app = compose["services"]["app"]

    assert app["build"]["dockerfile"] == "Dockerfile"
    assert app["restart"] == "unless-stopped"
    assert app["environment"]["NANOCLAW_WEB_HOST"] == "0.0.0.0"
    assert app["environment"]["NANOCLAW_CUSTOMER_PORTAL_HOST"] == "0.0.0.0"
    assert all("127.0.0.1" in published for published in app["ports"])
    assert app["volumes"] == [
        "nanoclaw_workspace:/app/workspace",
        "nanoclaw_data:/app/data",
    ]
    assert app["healthcheck"]["test"][1] == "/app/.venv/bin/python"
    assert app["security_opt"] == ["no-new-privileges:true"]
    assert app["cap_drop"] == ["ALL"]


def test_docker_context_excludes_secrets_and_runtime_data_but_keeps_ocr_models():
    dockerignore = (ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()

    assert ".env" in dockerignore
    assert "deploy/docker/.env" in dockerignore
    assert "workspace" in dockerignore
    assert "data" in dockerignore
    assert "!.paddlex/official_models/**" in dockerignore

    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert dockerfile.startswith("FROM python:3.11.9-slim-bookworm")
    assert "USER 10001:10001" in dockerfile
    assert 'CMD ["/app/.venv/bin/python", "main.py"]' in dockerfile
