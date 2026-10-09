"""Build the Teams app package (appPackage/nda-reviewer.zip) to upload in Teams.

    python appPackage/build_package.py <bot-app-id>
"""

import json
import sys
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent


def main() -> None:
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    bot_id = sys.argv[1]
    manifest = (HERE / "manifest.json").read_text().replace("${{BOT_ID}}", bot_id)
    json.loads(manifest)  # fail fast on a broken manifest
    out = HERE / "nda-reviewer.zip"
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("manifest.json", manifest)
        zf.write(HERE / "color.png", "color.png")
        zf.write(HERE / "outline.png", "outline.png")
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
