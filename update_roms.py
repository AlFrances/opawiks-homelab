#!/usr/bin/env python3
"""Run this after adding or removing ROMs: python3 update_roms.py
It scans the roms/ folders and rewrites roms/roms-data.js, which the ROMs page reads."""
import json
from pathlib import Path

ROMS = Path(__file__).resolve().parent / "roms"
IGNORED = {"systeminfo.txt"}


def read_info(info_file):
    """Reads the console's full name and accepted file types from systeminfo.txt."""
    lines = info_file.read_text(encoding="utf-8").splitlines()
    name = lines[lines.index("Full system name:") + 1].strip()
    extensions = lines[lines.index("Supported file extensions:") + 1].split()
    return name, sorted({ext.lower() for ext in extensions})


consoles = []
for folder in sorted(ROMS.iterdir()):
    info_file = folder / "systeminfo.txt"
    if not info_file.is_file():
        continue
    name, extensions = read_info(info_file)
    games = [
        {"path": file.relative_to(folder).as_posix(), "size": file.stat().st_size}
        for file in sorted(folder.rglob("*"))
        if file.is_file() and file.name not in IGNORED and not file.name.startswith(".")
    ]
    consoles.append({"id": folder.name, "name": name, "extensions": extensions, "games": games})

consoles.sort(key=lambda console: console["name"].lower())
data = json.dumps(consoles, ensure_ascii=False, indent=1)
(ROMS / "roms-data.js").write_text(f"window.ROMS_DATA = {data};\n", encoding="utf-8")
total = sum(len(console["games"]) for console in consoles)
print(f"Found {total} games across {len(consoles)} consoles.")
