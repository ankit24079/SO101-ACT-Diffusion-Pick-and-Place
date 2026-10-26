#!/bin/bash -l
#SBATCH --job-name=so101-act
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=8
#SBATCH --mem=32G
#SBATCH --time=12:00:00
#SBATCH --output=so101-act-%j.out
#SBATCH --error=so101-act-%j.err
# Supply your authorized --account, --partition and --gres when submitting.
set -euo pipefail
: "${SO101_PACKAGE_DIR:?Set SO101_PACKAGE_DIR to the extracted package directory}"
: "${SO101_ACTIVATE_SCRIPT:?Set SO101_ACTIVATE_SCRIPT to your GPU environment activation script}"
source "$SO101_ACTIVATE_SCRIPT"
export OMP_NUM_THREADS="${SLURM_CPUS_PER_TASK:-8}"
bash "$SO101_PACKAGE_DIR/train_act.sh"
