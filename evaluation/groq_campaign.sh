#!/usr/bin/env bash
# One pass of the Groq evaluation campaign: every Groq model on every domain pack, current code
# and data, investigation + QA (the other suites call no model and run locally).
#
# Each pass resumes the same result folders: it skips what already succeeded and stops a model
# as soon as its 200,000-tokens-per-day free-tier quota is spent. A systemd user timer
# (deploy/systemd/groq-eval.timer) repeats it every 28 hours; when every folder is complete
# the timer disables itself. Models run in parallel (the quota is per model), packs one after
# the other, each model in its own evaluation database.
#
#   evaluation/groq_campaign.sh            # one pass now
#   journalctl --user -u groq-eval -f      # follow a timer-started pass
set -uo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CAMPAIGN="${GROQ_CAMPAIGN:-2026-11-13-groq-18m}"
LOGS="$ROOT/evaluation/results/.logs"
PACKS=(insurance_claims procure_to_pay)
# model | database suffix | extra environment
MODELS=(
  "groq:openai/gpt-oss-120b|eval_groq_120b|"
  "groq:openai/gpt-oss-20b|eval_groq_20b|"
  # Groq caps qwen3.8-27b at 1,000 output tokens per minute and refuses any request whose
  # max_tokens exceeds it, so this model runs with a smaller output cap than the default 4,096.
  "groq:qwen/qwen3.8-27b|eval_groq_qwen|LLM_MAX_OUTPUT_TOKENS=1000"
)
export PATH="$HOME/.local/bin:$PATH"
mkdir -p "$LOGS"

log() { echo "[$(date '+%F %T')] $*"; }

# The evaluation databases live in the development Postgres.
(cd "$ROOT" && docker compose up -d --wait postgres) >/dev/null || { log "postgres not up"; exit 1; }

run_model() {
  local model="$1" suffix="$2" extra="$3" status=0 name pack out
  name="${model#groq:}"; name="${name#*/}"
  for pack in "${PACKS[@]}"; do
    out="$ROOT/evaluation/results/$CAMPAIGN-$pack-$name"
    if [[ -f "$out/meta.json" ]] && grep -q '"finished"' "$out/meta.json"; then
      continue
    fi
    log "$model · $pack: pass starts"
    (cd "$ROOT/backend" && env $extra uv run python -m watchdog_backend.evaluation run \
      --resume --domain "$pack" --models "$model" --suites investigation,qa \
      --pause 10 --db-suffix "$suffix" --out "$out") \
      >>"$LOGS/$CAMPAIGN-$pack-$name.log" 2>&1
    local rc=$?
    log "$model · $pack: pass ended (exit $rc)"
    # Exit 3: quota spent, work left. The next pack would hit the same spent quota.
    if [[ $rc -ne 0 ]]; then status=1; break; fi
  done
  return $status
}

pids=()
for entry in "${MODELS[@]}"; do
  IFS='|' read -r model suffix extra <<<"$entry"
  run_model "$model" "$suffix" "$extra" &
  pids+=($!)
done
incomplete=0
for pid in "${pids[@]}"; do wait "$pid" || incomplete=1; done

if [[ $incomplete -eq 0 ]]; then
  log "campaign $CAMPAIGN complete: every model and pack has finished"
  systemctl --user disable --now groq-eval.timer 2>/dev/null || true
else
  log "campaign $CAMPAIGN: work remains for the next pass"
fi
