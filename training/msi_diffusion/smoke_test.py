"""One real CPU trainer update, checkpoint reload and held-out diffusion prediction."""
import argparse
import json
import os
from pathlib import Path
import subprocess
from types import SimpleNamespace

from common import check_package, check_version
from train_diffusion import training_command


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--data-root',type=Path,required=True)
    p.add_argument('--output-dir',type=Path,required=True)
    args=p.parse_args()
    check_version();root=check_package(args.data_root)
    if args.output_dir.exists():raise RuntimeError('Choose a fresh smoke output directory')
    command=training_command(SimpleNamespace(resume=False,device='cpu',steps=1,batch_size=1,
        workers=0,save_freq=1,output_dir=args.output_dir,no_pretrained_backbone=True),root)
    replacements={'--policy.down_dims':'[32,64,128]','--policy.resize_shape':'[64,64]',
        '--policy.num_train_timesteps':'8','--policy.num_inference_steps':'2'}
    command=[x.split('=',1)[0]+'='+replacements[x.split('=',1)[0]]
        if x.split('=',1)[0] in replacements else x for x in command]
    env=dict(os.environ,OMP_NUM_THREADS='4',MKL_NUM_THREADS='4')
    subprocess.run(command,check=True,env=env)
    checkpoints=sorted(args.output_dir.glob('checkpoints/*/pretrained_model'))
    checkpoints=[p for p in checkpoints if p.parent.name.isdigit()]
    if not checkpoints:raise RuntimeError('Trainer did not save checkpoint')
    from validate_diffusion import evaluate
    result=evaluate(checkpoints[-1],root,device='cpu',batch_size=1,workers=0,max_samples=2,
        output=args.output_dir/'smoke-validation.json')
    report=dict(test_only_not_a_trained_policy=True,hardware_accessed=False,
        native_trainer_completed=True,checkpoint_reloaded=True,validation=result)
    (args.output_dir/'smoke-test.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2),flush=True)


if __name__=='__main__':main()
