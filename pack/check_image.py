"""Exercise the adapter and packaged smoke Op without a network or model."""
import json
import sys

sys.path.insert(0, '/opt/collab-hub/cogs/builder-smoke')

from collab_hub_cog_worker import Task
from collab_hub_cog_worker.envelope import WorkerError
from serve import run


try:
    run(Task('run', {'command': 'anything'}), None)
except WorkerError as error:
    assert error.code == 'invalid-input'
else:
    raise AssertionError('The smoke adapter accepted an arbitrary input.')

result = run(Task('run', {}), None)
assert result['status'] == 'completed'
assert result['outputs']['first_tally']['total_words'] == 21
assert result['outputs']['accumulated_tally']['total_words'] == 31
assert 'track.json' in result['artifacts']
print(json.dumps({'status': 'PASS', 'first_total': 21, 'accumulated_total': 31,
                  'artifacts': sorted(result['artifacts'])}))
