import argparse
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common import CAMERAS, JOINTS, check_package
from train_act import training_command
from validate_act import masked_sums


class WorkflowTest(unittest.TestCase):
    def test_padded_errors_do_not_affect_score(self):
        import torch
        target = torch.zeros(1, 3, 6)
        pred = torch.ones(1, 3, 6)
        pred[:, 2] = 10000
        sums, count = masked_sums(pred, target, torch.tensor([[False, False, True]]))
        self.assertEqual(count, 2)
        self.assertEqual(sums.tolist(), [2]*6)

    def test_rejects_nonfinite_predictions(self):
        import torch
        with self.assertRaises(RuntimeError):
            masked_sums(torch.full((1, 1, 6), float('nan')), torch.zeros(1, 1, 6), torch.zeros(1, 1, dtype=torch.bool))

    def test_training_uses_only_training_root_and_no_hub_push(self):
        args = argparse.Namespace(device='cuda', steps=100000, batch_size=8, workers=4,
                                  save_freq=10000, output_dir=Path('/tmp/out'),
                                  no_pretrained_backbone=False, smoke_test=False)
        command = training_command(args, Path('/data'))
        self.assertIn('--dataset.root=/data/datasets/train', command)
        self.assertIn('--policy.push_to_hub=false', command)
        self.assertIn('--policy.n_decoder_layers=4', command)
        self.assertNotIn('/data/datasets/validation', ' '.join(command))

    def test_split_overlap_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root/'splits.json').write_text(json.dumps({'train': list(range(64)), 'validation': list(range(12))}))
            with self.assertRaises(RuntimeError):
                check_package(root)

    def test_resume_requires_and_uses_latest_native_checkpoint(self):
        with tempfile.TemporaryDirectory() as directory:
            args = argparse.Namespace(resume=True, output_dir=Path(directory), device='cuda')
            with self.assertRaises(RuntimeError):
                training_command(args, Path('/data'))
            for number in ('010000', '020000'):
                path = args.output_dir/'checkpoints'/number/'pretrained_model/train_config.json'
                path.parent.mkdir(parents=True)
                path.write_text('{}')
            command = training_command(args, Path('/data'))
            self.assertIn('--resume=true', command)
            self.assertTrue(any('020000/pretrained_model/train_config.json' in item for item in command))


if __name__ == '__main__':
    unittest.main()
