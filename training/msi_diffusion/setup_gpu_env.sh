#!/usr/bin/env bash
# Reuse the working CUDA Python as the base; install extras in a separate venv.
set -euo pipefail
base_activation="${SO101_ACT_BASE_ACTIVATION:-$HOME/activate-lerobot-gpu.sh}"
diffusion_env="${SO101_DIFFUSION_VENV:-$HOME/so101/venvs/lerobot-diffusion}"
code_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "$base_activation"
if [[ ! -f "$diffusion_env/bin/activate" ]]; then
  python -m venv --system-site-packages "$diffusion_env"
fi
source "$diffusion_env/bin/activate"
python -m pip install -r "$code_dir/requirements.txt"
python -m pip check
python - "$base_activation" "$diffusion_env" <<'PY'
from pathlib import Path
import shlex
import sys
base,venv=sys.argv[1:]
p=Path.home()/'activate-lerobot-diffusion.sh'
content='#!/usr/bin/env bash\nsource '+shlex.quote(base)+'\nsource '+shlex.quote(venv+'/bin/activate')+'\n'
if p.exists() and p.read_text()!=content:
    raise RuntimeError(f'Refusing to overwrite an existing different activation script: {p}')
p.write_text(content)
print('Diffusion activation:',p)
PY
