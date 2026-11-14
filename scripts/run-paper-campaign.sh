#!/usr/bin/env bash
# One campaign for every number in the paper's evaluation (current code).
#   gpt-4o-mini : main table (Flat, Retrieval, HyperMCP session-stateful and stateless,
#                 stateless catalog only) + HyperMCP ablations, 4 x 10 tasks;
#                 scaling subset (3 tasks); both mappings over MCP, 2 x 10 tasks.
#   gpt-6.1-sol : stateless catalog-only row (the rest of its block comes from
#                 scripts/run-frontier-campaign.sh).
# Writes results/shop-*.jsonl; DONE/FAILED marker in $MARK.
set -u
cd "$(dirname "$0")/.."
MARK=${MARK:-campaign.status}
rm -f "$MARK"
R=".venv/bin/python -m hypermcp.run --max-steps 12 --out results"
MINI="--agent openai --model gpt-4o-mini"
SOL="--agent openai-responses --model gpt-6.1-sol"
S3="--tasks cancel_and_return,return_window_trap,buy_hoodie"
status=0
for i in 1 2 3 4; do
  $R $MINI --interfaces flat,retrieval-emb,hyper,hyper-stateless,hyper-stateless-noenv --ablations || status=1
done
$R $MINI --interfaces flat,hyper --distractors 100 $S3 || status=1
for n in 500 1000; do $R $MINI --interfaces hyper --distractors $n $S3 || status=1; done
for i in 1 2; do $R $MINI --interfaces hyper,hyper-stateless --transport mcp || status=1; done
for i in 1 2 3 4; do $R $SOL --interfaces hyper-stateless-noenv || status=1; done
if [ $status -eq 0 ]; then echo DONE > "$MARK"; else echo FAILED > "$MARK"; fi
