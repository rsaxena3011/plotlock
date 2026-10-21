import sys
from pathlib import Path

ORACLE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ORACLE_DIR))
