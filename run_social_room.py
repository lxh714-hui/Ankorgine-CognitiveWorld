"""Run the local source checkout without relying on an installed package copy."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from cognitive_world.examples.social_room import main

if __name__ == "__main__":
    main()
