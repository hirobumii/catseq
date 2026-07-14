from pathlib import Path


ROOT = Path(__file__).parents[1]


def test_catseq_does_not_depend_on_consumer_repositories() -> None:
    """Keep application repositories downstream of CatSeq, including in tests."""
    forbidden = (
        "rb1" + "-next",
        "rb1" + "-rtmq",
        "catseq_" + "rb1",
    )
    roots = (
        ROOT / ".github",
        ROOT / "catseq",
        ROOT / "tests",
        ROOT / "rust",
    )
    violations: list[str] = []
    paths = {ROOT / "pyproject.toml", ROOT / "uv.lock"}

    for root in roots:
        paths.update(
            path
            for path in root.rglob("*")
            if path.is_file()
            and "target" not in path.parts
            and "__pycache__" not in path.parts
        )

    for path in paths:
        try:
            text = path.read_text(encoding="utf-8").lower()
        except UnicodeDecodeError:
            continue
        if any(token in text for token in forbidden):
            violations.append(str(path.relative_to(ROOT)))

    assert not violations, (
        "CatSeq build, source, tests, and CI must not reference consumer "
        f"repositories: {sorted(violations)}"
    )
