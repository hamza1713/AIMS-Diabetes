"""
DiaDoc AI — Root Application Runner
====================================
Allows starting the backend directly from the project root directory:
    python run.py
"""

import os
import sys
from pathlib import Path

# Add backend directory to sys.path
ROOT_DIR = Path(__file__).resolve().parent
BACKEND_DIR = ROOT_DIR / "backend"

sys.path.insert(0, str(BACKEND_DIR))
os.chdir(BACKEND_DIR)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=False)
