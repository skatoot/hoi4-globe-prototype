"""Explicit local configuration; machine paths are never source defaults."""
import os
from pathlib import Path

ROOT=Path(__file__).resolve().parent.parent
OUT=ROOT/'build/hoi4-globe-prototype'
game=os.environ.get('HOI4_GAME_DIR')
if not game:
    raise SystemExit('Set HOI4_GAME_DIR to your local HOI4 installation, or use Build.ps1 -GameDirectory.')
GAME=Path(game).expanduser().resolve()
if not (GAME/'hoi4.exe').is_file():
    raise SystemExit('HOI4_GAME_DIR must contain hoi4.exe.')
