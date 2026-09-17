#!/usr/bin/env bash
# hermes-setup.sh — one-command Hermes Agent MCP setup for kindle-gazette
#
# Usage:
#   chmod +x scripts/hermes-setup.sh
#   ./scripts/hermes-setup.sh [profile ...]
#
# What it does:
#   1. Ensures `uv` is installed as a standalone binary (required — pip-installed uv
#      is NOT in Hermes' PATH)
#   2. Pre-resolves dependencies (`uv sync`) so the first real spawn is fast
#   3. Creates a wrapper script at ~/.local/bin/kindle-gazette
#      (Hermes may misparse `command` + `args` in config.yaml — the wrapper bundles
#      the `cd` + `exec uv run` into one executable, bypassing this)
#   4. Writes the MCP server config to ~/.hermes/config.yaml (merges, doesn't replace)
#   5. Verifies the server starts and tools are discoverable
#
# Optionally, for each Hermes profile named as an argument, copies the repo's
# `gazette` publishing skill (../skills/gazette/) into that profile's skills
# directory (~/.hermes/profiles/<name>/skills/gazette/). With no arguments,
# no skill is copied — same behavior as before.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
LOCAL_BIN="$HOME/.local/bin"
WRAPPER="$LOCAL_BIN/kindle-gazette"
YELLOW='\033[1;33m'
GREEN='\033[1;32m'
RED='\033[1;31m'
NC='\033[0m'

echo "============================================"
echo " kindle-gazette — Hermes Agent Setup"
echo "============================================"
echo ""

# ── Step 1: Install uv standalone ──────────────────────────────────────────
echo -e "${YELLOW}[1/5]${NC} Ensuring uv is installed (standalone binary)..."
if [ -x "$LOCAL_BIN/uv" ]; then
    echo "  ✓ uv already at $LOCAL_BIN/uv"
else
    echo "  Installing uv standalone..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    echo "  ✓ uv installed"
fi
echo ""

# ── Step 2: Pre-resolve dependencies ───────────────────────────────────────
echo -e "${YELLOW}[2/5]${NC} Resolving dependencies (uv sync)..."
(cd "$REPO_DIR" && "$LOCAL_BIN/uv" sync) >/dev/null
echo "  ✓ Dependencies ready — first spawn under Hermes will be fast"
echo ""

# ── Step 3: Create wrapper script ─────────────────────────────────────────
echo -e "${YELLOW}[3/5]${NC} Creating wrapper script..."
mkdir -p "$LOCAL_BIN"
cat > "$WRAPPER" << WRAPPER_EOF
#!/usr/bin/env bash
# Wrapper for kindle-gazette MCP server
# Hermes Agent may not parse \`command\` + \`args\` in config.yaml correctly.
# This wrapper bundles the cd + exec into a single executable.
cd "$REPO_DIR"
exec "$LOCAL_BIN/uv" run kindle-gazette
WRAPPER_EOF
chmod +x "$WRAPPER"
echo "  ✓ Wrapper created at $WRAPPER"
echo ""

# ── Step 4: Write Hermes config ────────────────────────────────────────────
echo -e "${YELLOW}[4/5]${NC} Writing Hermes MCP config..."
CONFIG="$HOME/.hermes/config.yaml"

"$LOCAL_BIN/uv" run --with pyyaml python3 -c "
import yaml

p = '$CONFIG'
with open(p) as f:
    c = yaml.safe_load(f)

# Preserve existing MCP servers, add/update kindle-gazette
if 'mcp_servers' not in c:
    c['mcp_servers'] = {}

c['mcp_servers']['kindle-gazette'] = {
    'command': '$WRAPPER',
}

with open(p, 'w') as f:
    yaml.safe_dump(c, f, default_flow_style=False, allow_unicode=True, sort_keys=False)
print('  ✓ Config updated')
" 2>&1
echo ""

# ── Step 5: Verify ─────────────────────────────────────────────────────────
echo -e "${YELLOW}[5/5]${NC} Verifying server connection..."
if hermes mcp test kindle-gazette 2>&1 | grep -q "✓ Connected"; then
    echo -e "  ${GREEN}✓ Server connected successfully${NC}"
else
    echo -e "  ${RED}✗ mcp test failed${NC}"
    echo "  Try /reload-mcp in Hermes chat, then: hermes mcp test kindle-gazette"
fi

echo ""

# ── Optional: install the gazette publishing skill into named profiles ────
if [ "$#" -gt 0 ]; then
    SKILL_SRC="$REPO_DIR/../skills/gazette"
    echo -e "${YELLOW}[+]${NC} Installing the gazette skill into profile(s): $*"
    if [ ! -d "$SKILL_SRC" ]; then
        echo -e "  ${RED}✗ Skill source not found at $SKILL_SRC — skipping${NC}"
    else
        for profile in "$@"; do
            dest="$HOME/.hermes/profiles/$profile/skills/gazette"
            if [ ! -d "$HOME/.hermes/profiles/$profile" ]; then
                echo -e "  ${RED}✗ No profile at ~/.hermes/profiles/$profile — skipping${NC}"
                continue
            fi
            mkdir -p "$dest"
            cp -R "$SKILL_SRC/." "$dest/"
            echo "  ✓ gazette skill → $dest"
        done
    fi
fi

echo ""
echo "============================================"
echo -e " ${GREEN}Setup complete!${NC}"
echo ""
echo " Next step: type /reload-mcp in your Hermes chat"
echo " Then test: call get_status to verify"
echo ""
echo " MCP server config:"
echo "   command: $WRAPPER"
echo "============================================"
