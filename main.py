"""Punto de entrada heredado. Conservado durante la transición: usa `analizador-video analizar`.

Equivalente a la CLI original (`python main.py --video ... --transcript ... --sin-ia`).
Si existe ./config.yaml y no se indica --config, se usa ese archivo como antes.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from analizador_video.cli.legacy import main

if __name__ == "__main__":
    sys.exit(main())
