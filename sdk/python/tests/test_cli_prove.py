"""CLI prove path for README ServicesHealthy against mock OpenAPI."""

from pathlib import Path

from gluless.cli import main

REPO_ROOT = Path(__file__).resolve().parents[3]
CONTRACT = REPO_ROOT / "pack" / "contracts" / "services-healthy.glu"
OPENAPI = REPO_ROOT / "api" / "openapi.yaml"


def test_cli_prove_services_healthy_mock(capsys):
    code = main(
        [
            "prove",
            "--contract",
            str(CONTRACT),
            "--openapi",
            str(OPENAPI),
            "--mock",
        ]
    )
    captured = capsys.readouterr().out
    assert code == 0
    assert "PARSE=PASS" in captured
    assert "AUTHORIZE=PASS" in captured
    assert "HTTP_EXECUTION=PASS" in captured
    assert "GOAL_EVALUATION=PASS" in captured
    assert "PROVEN=YES" in captured
