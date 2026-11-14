"""Run management commands using workspace-only tooling dependencies, if installed."""
import runpy
import sys
from pathlib import Path

root = Path(__file__).resolve().parent.parent
workspace_tools = root.parents[1] / ".tools"
sys.path.insert(0, str(root))
# An installed environment takes precedence over historical tooling packages,
# which may contain binary extensions for a different Python version.
sys.path.extend([str(root / ".tools"), str(workspace_tools)])
sys.argv[0] = str(root / "manage.py")
runpy.run_path(sys.argv[0], run_name="__main__")
