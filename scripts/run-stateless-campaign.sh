#!/usr/bin/env bash
# LLM campaign for the stateless realization (MCP 2026-07-28), shop environment.
#   in process : hyper (session realization, same-day reference), hyper-stateless,
#                hyper-stateless-noenv (= SEP-2567 catalog-only server); 4 x 10 tasks
#   over MCP   : hyper@mcp (2025-11-25 sessions), hyper-stateless@mcp (2026-07-28);
#                2 x 10 tasks
# Writes results/shop-openai-*.jsonl; DONE/FAILED marker in $MARK.
set -u
cd "$(dirname "$0")/.."
MARK=${MARK:-campaign.status}
rm -f "$MARK"
run() { .venv/bin/python -m hypermcp.run --env shop --agent openai --model gpt-4o-mini \
          --max-steps 12 --out results "$@"; }
status=0
for i in 1 2 3 4; do
  run --interfaces hyper,hyper-stateless,hyper-stateless-noenv || status=1
done
for i in 1 2; do
  run --interfaces hyper,hyper-stateless --transport mcp || status=1
done
if [ $status -eq 0 ]; then echo DONE > "$MARK"; else echo FAILED > "$MARK"; fi
