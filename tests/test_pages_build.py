import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_pages_build_contains_only_public_assets():
    subprocess.run(
        [sys.executable, str(ROOT / "tools" / "build_pages.py")],
        cwd=ROOT,
        check=True,
    )

    output = ROOT / "dist"
    for relative_path in (
        "index.html",
        "contact.html",
        "resources.html",
        "data.json",
        "logs.json",
        "site-config.json",
        "css/style.css",
        "js/app.js",
    ):
        assert (output / relative_path).is_file()

    for private_path in ("scores", "imports", "backup", "templates", "tools"):
        assert not (output / private_path).exists()

    assert all(
        path.stat().st_size <= 25 * 1024 * 1024
        for path in output.rglob("*")
        if path.is_file()
    )
