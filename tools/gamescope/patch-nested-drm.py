#!/usr/bin/env python3
from pathlib import Path
import sys

path = Path(sys.argv[1] if len(sys.argv) > 1 else "src/rendervulkan.cpp")
s = path.read_text()

needle = "\tif ( !hasDrmProps ) {"
if needle not in s:
    raise SystemExit("gamescope DRM identity anchor not found")

replacement = (
    "\tif ( !GetBackend()->IsSessionBased() ) {\n"
    "\t\tvk_log.infof( \"skipping DRM node identity for non-session backend\" );\n"
    "\t} else if ( !hasDrmProps ) {"
)
s = s.replace(needle, replacement, 1)
path.write_text(s)
print("DroidDeck: nested Wayland DRM identity check patched in", path)
