#!/usr/bin/env bash
# One-command setup for macOS / Linux:   bash scripts/setup.sh
set -euo pipefail
cd "$(dirname "$0")/.."

PY="${PYTHON:-python3}"
"$PY" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' \
  || { echo "Python 3.11+ is required (https://www.python.org/downloads/)"; exit 1; }

echo "→ Creating virtual environment (.venv)"
"$PY" -m venv .venv
# shellcheck disable=SC1091
source .venv/bin/activate
pip install -q --upgrade pip
echo "→ Installing (about a minute)"
pip install -q -e .

[ -f .env ] || { cp .env.example .env; echo "→ Created .env (add your Telegram token later)"; }

echo; echo "→ Quick demo with an example plan:"; echo
pda demo --extra 0 | head -32
echo "   … (run 'pda demo' for the full tour)"; echo

if [ ! -f config/strategy.yaml ]; then
  echo "→ Now let's create YOUR plan:"
  pda init
fi

echo; pda doctor --offline || true
cat <<'EOF'

Done. Next:
  source .venv/bin/activate
  pda plan                      # this month's buy list with live prices
  pda import <positions.csv>    # optional: load what you already own
  # add TELEGRAM_BOT_TOKEN to .env, then:
  pda bot
EOF
