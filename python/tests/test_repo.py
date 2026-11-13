from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_gitignore_keeps_data_and_venv_out():
    rules = (ROOT / ".gitignore").read_text().splitlines()
    assert "data/" in rules
    assert ".venv/" in rules


def test_requirements_are_pinned():
    lines = (ROOT / "python" / "requirements.txt").read_text(encoding="utf-8-sig").splitlines()
    for line in lines:
        if line.strip():
            assert "==" in line, f"Not pinned to an exact version: {line}"