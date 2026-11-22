import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

exec(compile(
    (ROOT / "integration" / "diagnose_body.py").read_text(encoding="utf-8"),
    "diagnose_body.py",
    "exec"
))
