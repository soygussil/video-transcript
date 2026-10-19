"""Lanzador del ejecutable. freeze_support() se llama dentro de ui.app.main()."""

import sys

from analizador_video.ui.app import main

if __name__ == "__main__":
    sys.exit(main())
