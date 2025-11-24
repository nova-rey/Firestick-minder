import compileall
from pathlib import Path


def test_compile_all():
    # Compile all Python sources under the repo root to ensure there are
    # no syntax errors and all modules are importable.
    root = Path(__file__).resolve().parents[1]
    assert compileall.compile_dir(str(root), quiet=1)
