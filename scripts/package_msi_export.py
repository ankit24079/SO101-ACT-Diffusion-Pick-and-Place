"""Create and verify a portable archive of a completed MSI dataset export."""
import argparse
import hashlib
import json
import tarfile
from pathlib import Path


def digest(stream):
    result = hashlib.sha256()
    for chunk in iter(lambda: stream.read(1024*1024), b''):
        result.update(chunk)
    return result.hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('root', type=Path)
    root = parser.parse_args().root
    verified = json.loads((root/'verification.json').read_text())
    assert verified['total_episodes'] == 76
    split = json.loads((root/'splits.json').read_text())
    assert not set(split['train']).intersection(split['validation'])
    assert len(split['train']) == verified['train_episodes']
    assert len(split['validation']) == verified['validation_episodes']
    expected = {}
    for path in sorted(root.rglob('*')):
        assert not path.is_symlink(), path
        if path.is_file() and path.name != 'SHA256SUMS':
            with path.open('rb') as stream:
                expected[path.relative_to(root).as_posix()] = digest(stream)
    (root/'SHA256SUMS').write_text(''.join(f'{sha}  {name}\n' for name, sha in expected.items()))
    archive = root.with_suffix('.tar.gz')
    if archive.exists():
        raise RuntimeError(f'Refusing to overwrite archive: {archive}')
    with tarfile.open(archive, 'w:gz', compresslevel=1) as tar:
        tar.add(root, arcname=root.name)
    with archive.open('rb') as stream:
        checksum = digest(stream)
    archive.with_name(archive.name+'.sha256').write_text(f'{checksum}  {archive.name}\n')
    checked = set()
    with tarfile.open(archive, 'r:gz') as tar:
        for member in tar:
            if not member.isfile() or member.name == root.name+'/SHA256SUMS':
                continue
            name = member.name.removeprefix(root.name+'/')
            assert digest(tar.extractfile(member)) == expected[name], name
            checked.add(name)
    assert checked == set(expected)
    print(f'Archive verified: {archive}; {archive.stat().st_size} bytes; {len(checked)} checksummed files')
    print(f"Split: {verified['train_episodes']} train / {verified['validation_episodes']} validation")


if __name__ == '__main__':
    main()
