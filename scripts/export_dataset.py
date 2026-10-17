"""Export inspectable JSON from the authoritative shared workbook."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from agentcheck.dataset import ROOT, load_dataset

destination = ROOT / "data" / "bank_data.json"
destination.write_text(json.dumps(load_dataset(), indent=2) + "\n", encoding="utf-8")
print(destination)
