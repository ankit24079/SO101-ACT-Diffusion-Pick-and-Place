import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from common import check_package
from train_diffusion import training_command
from validate_diffusion import execution_targets,masked_sums,select_indices


class DiffusionWorkflowTest(unittest.TestCase):
    def test_execution_targets_skip_past_action_and_mask_episode_end_padding(self):
        import torch
        target=torch.arange(16).reshape(1,16,1).repeat(1,1,6).float()
        pad=torch.zeros(1,16,dtype=torch.bool);pad[:,8:]=True
        aligned,mask=execution_targets(target,pad,2,8)
        self.assertEqual(aligned[0,:,0].tolist(),list(range(1,9)))
        prediction=aligned+1;prediction[:,7]=1e6
        sums,count=masked_sums(prediction,aligned,mask)
        self.assertEqual(count,7)
        self.assertEqual(sums.tolist(),[7]*6)

    def test_selection_covers_all_12_episodes_and_uses_fewer_than_all_frames(self):
        import numpy as np
        episodes=np.repeat(np.arange(12),100)
        selected=select_indices(episodes,256)
        self.assertEqual(len(selected),256)
        self.assertEqual(set(episodes[selected]),set(range(12)))

    def test_native_training_uses_train_only_and_keeps_temporal_geometry(self):
        args=SimpleNamespace(resume=False,device='cuda',steps=100000,batch_size=8,workers=4,
            save_freq=10000,output_dir=Path('/tmp/diffusion'),no_pretrained_backbone=False)
        cmd=training_command(args,Path('/data'))
        self.assertIn('--dataset.root=/data/datasets/train',cmd)
        self.assertNotIn('/data/datasets/validation',' '.join(cmd))
        for x in ['--policy.type=diffusion','--policy.horizon=16','--policy.n_obs_steps=2',
                  '--policy.n_action_steps=8','--policy.push_to_hub=false']:
            self.assertIn(x,cmd)

    def test_resume_rejects_act_checkpoint(self):
        with tempfile.TemporaryDirectory() as directory:
            args=SimpleNamespace(resume=True,output_dir=Path(directory),device='cuda')
            p=args.output_dir/'checkpoints/010000/pretrained_model/train_config.json'
            p.parent.mkdir(parents=True);p.write_text(json.dumps({'policy':{'type':'act'}}))
            with self.assertRaises(RuntimeError):training_command(args,Path('/data'))

    def test_overlapping_train_validation_split_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            (root/'splits.json').write_text(json.dumps({'train':list(range(64)),'validation':list(range(12))}))
            with self.assertRaises(RuntimeError):check_package(root)


if __name__=='__main__':unittest.main()
