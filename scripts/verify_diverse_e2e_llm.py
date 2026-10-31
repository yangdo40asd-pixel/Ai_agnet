"""Execution shim forwarding to scripts/e2e_eval/verify_diverse_e2e_llm.py."""
import runpy
from pathlib import Path

if __name__ == "__main__":
    target = Path(__file__).parent / "e2e_eval" / "verify_diverse_e2e_llm.py"
    runpy.run_path(str(target), run_name="__main__")
