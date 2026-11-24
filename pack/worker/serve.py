"""Expose the published model-free smoke Op through the Hub worker SDK."""
import json
import os
from pathlib import Path
import subprocess
import tempfile

from collab_hub_cog_worker import Worker
from collab_hub_cog_worker.envelope import WorkerError


SUITE = Path('/opt/builder-suite')
PACKAGE = SUITE / 'op-builder-smoke'
worker = Worker('builder-smoke', '0.1.0')


@worker.task('run')
def run(task, harness):
    if task.input not in (None, {}):
        raise WorkerError('invalid-input', 'This smoke entry point takes an empty object.')
    environment = {key: value for key, value in os.environ.items()
                   if not key.startswith(('COLLAB_', 'PIXI_'))}
    environment.update(PIXI_HOME='/opt/builder-pixi-config',
                       PIXI_CACHE_DIR='/tmp/builder-pixi-cache')
    with tempfile.TemporaryDirectory(prefix='builder-smoke-') as directory:
        result = subprocess.run(
            [str(PACKAGE / '.pixi/envs/default/bin/python'), 'src/op_runner.py',
             '--request', 'examples/request.json', '--runs-dir', directory],
            cwd=PACKAGE,
            env=environment,
            capture_output=True, text=True, timeout=120,
        )
        if result.returncode:
            raise WorkerError('smoke-failed', result.stderr[-4096:] + result.stdout[-4096:])
        summary = json.loads(result.stdout)
        run_directory = Path(summary['run_dir'])
        artifacts = {
            str(path.relative_to(run_directory)): json.loads(path.read_text())
            for path in sorted(run_directory.rglob('*.json'))
        }
        return {
            'status': summary['status'],
            'outputs': summary['outputs'],
            'native_track': artifacts['track.json'],
            'artifacts': artifacts,
            'sources': json.loads((Path(__file__).parent / 'sources.json').read_text()),
            'components': json.loads((SUITE / 'cog-op-builder/repositories.json').read_text()),
        }


if __name__ == '__main__':
    worker.serve()
