#!/usr/bin/env bash
# Reproduces every published measurement (CONTRACT §4): fetch, measure, mutate, blueprint and
# summarize. Honours LAZARILLO_WORK (default: <repo>/work).
set -euo pipefail

repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo"
export LAZARILLO_WORK="${LAZARILLO_WORK:-$repo/work}"
work="$LAZARILLO_WORK"

corpora=(pfr zeta23 zetalab poincare ns rh)

lazarillo() { python3 -m lazarillo "$@"; }

# PROJECT_DIR of a corpus, as recorded by fetch.
project_dir() {
    python3 -c 'import json, sys; print(json.load(open(sys.argv[1]))["project_dir"])' \
        "$work/corpora/$1.fetch.json"
}

lazarillo fetch --model "${corpora[@]}"

for corpus in "${corpora[@]}"; do
    lazarillo measure "$corpus"
done

for corpus in pfr zeta23; do
    lazarillo mutate --run "$work/runs/$corpus" --project "$(project_dir "$corpus")" \
        --out "$work/results/$corpus/mutations"
done

pfr="$(project_dir pfr)"
lazarillo blueprint --tex-dir "$pfr/blueprint/src" --run "$work/runs/pfr" --root-label pfr \
    --root-decl PFR_conjecture --out "$work/results/pfr/calibration.json"

lazarillo summarize
