"""Cria uma base demonstrativa local sem versionar dados de usuário."""
from pathlib import Path
import os
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("EDITALOS_DATA", str(ROOT / "data-demo"))
import app

with app.db() as conn:
    if not conn.execute("SELECT 1 FROM exams LIMIT 1").fetchone():
        app.seed(conn)
print(f"Base demonstrativa pronta em {app.DB_PATH}")
