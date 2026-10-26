#!/bin/bash -l
#SBATCH --job-name=so101-act
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=8
#SBATCH --mem=32G
#SBATCH --time=12:00:00
#SBATCH --output=so101-act-%j.out
#SBATCH --error=so101-act-%j.err
# Provide --account, --partition and --gres on the sbatch command line.
set -euo pipefail
: "${SO101_CODE_DIR:?Set SO101_CODE_DIR to the extracted training-code directory}"
: "${SO101_DATA_DIR:?Set SO101_DATA_DIR to the extracted val12 dataset package}"
: "${SO101_OUTPUT_DIR:?Set SO101_OUTPUT_DIR to a new output directory}"
: "${SO101_ACTIVATE_SCRIPT:?Set SO101_ACTIVATE_SCRIPT to your GPU environment activation script}"
source "$SO101_ACTIVATE_SCRIPT"
export OMP_NUM_THREADS="${SLURM_CPUS_PER_TASK:-8}"
python "$SO101_CODE_DIR/train_act.py" \
  --data-root "$SO101_DATA_DIR" \
  --output-dir "$SO101_OUTPUT_DIR" "$@"
