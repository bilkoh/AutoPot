# Add project root to sys.path so pytest can import the autopot package
import sys
from pathlib import Path

# Insert project root (parent of this tests/ directory) at front of sys.path
# This makes `import autopot` work when running `pytest` from the repo root.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))