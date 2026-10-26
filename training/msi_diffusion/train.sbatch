#!/bin/bash -l
#SBATCH --job-name=so101-diffusion
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=8
#SBATCH --mem=48G
#SBATCH --time=24:00:00
#SBATCH --output=so101-diffusion-%j.out
#SBATCH --error=so101-diffusion-%j.err
# Supply authorized account, partition and GPU request when submitting.
set -euo pipefail
: "${SO101_CODE_DIR:?Set diffusion-code directory}"
: "${SO101_DATA_DIR:?Set the existing 76-episode val12 package}"
: "${SO101_OUTPUT_DIR:?Set a fresh diffusion run directory}"
: "${SO101_ACTIVATE_SCRIPT:?Set the diffusion GPU environment activation script}"
source "$SO101_ACTIVATE_SCRIPT"
export OMP_NUM_THREADS="${SLURM_CPUS_PER_TASK:-8}"
python -u "$SO101_CODE_DIR/gpu_check.py" \
  --data-root "$SO101_DATA_DIR" --output "${SO101_OUTPUT_DIR}-setup.json"
python -u "$SO101_CODE_DIR/train_diffusion.py" \
  --data-root "$SO101_DATA_DIR" --output-dir "$SO101_OUTPUT_DIR" "$@"
