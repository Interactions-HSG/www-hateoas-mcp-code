#!/usr/bin/env bash
# Frontier-model replication of the shop table: gpt-6.1-sol via the Responses API
# (default reasoning effort). 4 runs x 10 tasks per interface.
# The 2026-11-13 logs also contain a BM25 retrieval row ('retrieval'); that baseline was
# removed from the code and the paper afterwards.
# Writes results/shop-openai-responses-*.jsonl; DONE/FAILED marker in $MARK.
set -u
cd "$(dirname "$0")/.."
MARK=${MARK:-campaign.status}
rm -f "$MARK"
status=0
for i in 1 2 3 4; do
  .venv/bin/python -m hypermcp.run --agent openai-responses --model gpt-6.1-sol \
    --max-steps 12 --out results \
    --interfaces flat,retrieval-emb,hyper,hyper-stateless || status=1
done
if [ $status -eq 0 ]; then echo DONE > "$MARK"; else echo FAILED > "$MARK"; fi
