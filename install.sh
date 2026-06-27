#!/usr/bin/env bash
#
# Install Claude Code Vision Hook.
#
# - Copies image-vision.py to ~/.claude/hooks/
# - Merges the UserPromptSubmit hook into ~/.claude/settings.json (idempotent)
# - Does NOT overwrite any existing API key / env var you've already set
#
# Configure your provider by exporting VISION_* env vars in your shell
# (or by editing ~/.claude/settings.json -> env), then run this script.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC="${SCRIPT_DIR}/image-vision.py"
DEST_DIR="${HOME}/.claude/hooks"
DEST="${DEST_DIR}/image-vision.py"
SETTINGS="${HOME}/.claude/settings.json"

mkdir -p "${DEST_DIR}"
cp "${SRC}" "${DEST}"
echo "✓ Installed ${DEST}"

# Initialize settings.json if missing
if [[ ! -f "${SETTINGS}" ]]; then
  mkdir -p "$(dirname "${SETTINGS}")"
  echo '{}' > "${SETTINGS}"
  echo "✓ Created ${SETTINGS}"
fi

# Validate JSON
if ! python3 -c 'import json,sys; json.load(open(sys.argv[1]))' "${SETTINGS}" >/dev/null 2>&1; then
  echo "✗ ${SETTINGS} is not valid JSON. Fix it manually, then re-run this script."
  exit 1
fi

# Merge the UserPromptSubmit hook entry using Python (idempotent)
python3 - "${SETTINGS}" <<'PY'
import json, sys, os, pathlib
settings_path = pathlib.Path(sys.argv[1])
data = json.loads(settings_path.read_text(encoding="utf-8"))
hooks = data.setdefault("hooks", {})
ups = hooks.setdefault("UserPromptSubmit", [])

cmd = "python3 ~/.claude/hooks/image-vision.py"
already = any(
    any(h.get("type") == "command" and h.get("command") == cmd for h in entry.get("hooks", []))
    for entry in ups
)
if already:
    print(f"✓ Hook already registered in {settings_path}")
else:
    ups.append({
        "hooks": [{
            "type": "command",
            "command": cmd,
            "timeout": 60,
            "statusMessage": "解析图片中..."
        }]
    })
    settings_path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"✓ Registered UserPromptSubmit hook in {settings_path}")
PY

cat <<EOF

Done. Next steps:

1. Set your API key (and optionally provider/model) in your shell or in
   ${SETTINGS} -> env. Example:

     export VISION_PROVIDER=openai
     export VISION_API_KEY=sk-...
     export VISION_MODEL=gpt-4o

   See README.md for the full list of provider presets.

2. Verify the config with a standalone test:

     python3 ${DEST} --test-image /path/to/some/screenshot.png

3. Restart Claude Code (or open /hooks once) to load the new hook.

4. Paste a screenshot into Claude Code and send any message — the main
   model should now "see" the image.
EOF
