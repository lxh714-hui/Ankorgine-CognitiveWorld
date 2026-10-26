"""Run the JSON object demo from this source checkout."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))
from cognitive_world.examples.json_objects import main
if __name__ == "__main__":
    main()
