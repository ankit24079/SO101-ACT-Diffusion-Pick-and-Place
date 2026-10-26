#!/usr/bin/env bash
# Reuse the working CUDA Python as the base; install extras in a separate venv.
set -euo pipefail
base_activation="${SO101_ACT_BASE_ACTIVATION:-$HOME/activate-lerobot-gpu.sh}"
base_python="${SO101_ACT_BASE_PYTHON:-$HOME/so101/envs/lerobot-act/bin/python}"
diffusion_env="${SO101_DIFFUSION_VENV:-$HOME/so101/venvs/lerobot-diffusion}"
code_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
if [[ ! -x "$base_python" ]]; then
  source "$base_activation"
  base_python="$(command -v python)"
fi
if [[ ! -f "$diffusion_env/bin/activate" ]]; then
  "$base_python" -m venv --system-site-packages "$diffusion_env"
fi
source "$diffusion_env/bin/activate"
export PYTHONNOUSERSITE=1
python -m pip install -r "$code_dir/requirements.txt"
python -m pip check
python - "$diffusion_env" <<'PY'
from pathlib import Path
import shlex
import sys
venv=sys.argv[1]
p=Path.home()/'activate-lerobot-diffusion.sh'
content='#!/usr/bin/env bash\nsource '+shlex.quote(venv+'/bin/activate')+'\nexport PYTHONNOUSERSITE=1\nexport HF_HUB_DISABLE_TELEMETRY=1\n'
if p.exists() and p.read_text()!=content:
    raise RuntimeError(f'Refusing to overwrite an existing different activation script: {p}')
p.write_text(content)
print('Diffusion activation:',p)
PY
