#!/bin/bash -l
#SBATCH --job-name=so101-validation
#SBATCH --account=hongj
#SBATCH --partition=msismall
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=8
#SBATCH --mem=32G
#SBATCH --time=02:00:00
set -euo pipefail
source "$HOME/activate-lerobot-gpu.sh"
export OMP_NUM_THREADS="${SLURM_CPUS_PER_TASK:-8}"
run_dir="${1:-$(cat "$HOME/so101/setup-logs/training-output-dir")}"
checkpoint=$(python - "$run_dir" <<'PY'
import sys
from pathlib import Path
paths = sorted(p for p in Path(sys.argv[1]).glob('checkpoints/*/pretrained_model')
               if p.parent.name.isdigit() and (p/'config.json').is_file()
               and (p/'model.safetensors').is_file())
if not paths:
    sys.exit('No saved checkpoint yet. Retry after training reaches step 10,000.')
print(paths[-1])
PY
)
step=$(basename "$(dirname "$checkpoint")")
python "$HOME/so101/so101-act-training-code/validate_act.py" \
  --checkpoint "$checkpoint" \
  --data-root "$HOME/so101/so101-cube-cup-msi-76-val12" \
  --device cpu --batch-size 4 --workers 2 \
  --output "$run_dir/validation-progress/$step.json"
