from __future__ import annotations
from dotenv import load_dotenv

import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(PROJECT_ROOT / ".env.local")
load_dotenv(PROJECT_ROOT / ".env")

APP_NAME = os.getenv("APP_NAME", "MaiThuyLaw AI")

# Final strict dataset:
# - Vietnam-related only
# - 2025 onward only
# - Neutral metadata, no personal/team prefixes
DATASET_PATH = Path(
    os.getenv(
        "MAITHUYLAW_RAG_CHUNKS",
        PROJECT_ROOT / "data" / "maithuylaw_dataset" / "data" / "index" / "rag_chunks.json",
    )
)

TOP_K = int(os.getenv("TOP_K", "6"))
MIN_SCORE = float(os.getenv("MIN_SCORE", "0.08"))
