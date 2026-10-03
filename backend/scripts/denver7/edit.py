"""Append one tile's manual review decisions to data/manual_edits.json.

usage: python edit.py '{"remove":[1,2], "add":[[x,y,r],...], "polys":[{"label":"store","kind":"flat","polygon":[[x,y],...]}]}'
All coordinates are mosaic pixels at 0.5 m/px, read off the labelled grid of the review tiles.
"""

import json
import sys
from pathlib import Path

PATH = Path(__file__).resolve().parent / "data" / "manual_edits.json"
data = json.loads(PATH.read_text(encoding="utf-8"))
new = json.loads(sys.argv[1])
for key in ("remove", "add", "polys"):
    data.setdefault(key, [])
    for item in new.get(key, []):
        if item not in data[key]:
            data[key].append(item)
PATH.write_text(json.dumps(data, indent=0), encoding="utf-8")
print({k: len(v) for k, v in data.items()})
