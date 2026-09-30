from pathlib import Path


def test_dockerfile_uses_port_environment_for_production_runtime():
    dockerfile = Path(__file__).resolve().parents[1] / "Dockerfile"
    content = dockerfile.read_text(encoding="utf-8")

    assert "--port" in content
    assert "${PORT:-8000}" in content
