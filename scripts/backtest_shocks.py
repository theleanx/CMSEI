"""Re-run the back-test against data/shocks.json and write data/validation_result.json.

  python3 -I scripts/backtest_shocks.py          # rewrite the result file
  python3 -I scripts/backtest_shocks.py --check  # fail if the stored file is out of date (CI runs this through pytest)
"""
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from app.engine import validation  # noqa: E402

OUT = ROOT / "data" / "validation_result.json"


def main(argv):
    res = json.loads(json.dumps(validation.run()))
    if "--check" in argv:
        same = OUT.exists() and json.loads(OUT.read_text()) == res
        print("up to date" if same else "OUT OF DATE: run scripts/backtest_shocks.py")
        return 0 if same else 1
    OUT.write_text(json.dumps(res, indent=1))
    print(res["reading"])
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
