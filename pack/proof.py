"""Run the real smoke Op through the authenticated Hub API and save evidence."""
import json
import os
from pathlib import Path
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request


def main():
    context = ssl.create_default_context(cafile=os.environ['BUILDER_CA_FILE'])
    hub = os.environ['BUILDER_HUB_URL'].rstrip('/')
    form = urllib.parse.urlencode({
        'grant_type': 'client_credentials', 'client_id': 'builder-proof',
        'client_secret': os.environ['BUILDER_CLIENT_SECRET'],
    }).encode()
    token_request = urllib.request.Request(os.environ['BUILDER_TOKEN_URL'], data=form)
    with urllib.request.urlopen(token_request, context=context, timeout=30) as response:
        token = json.load(response)['access_token']

    def request(path, body=None, authenticated=True):
        headers = {'Authorization': 'Bearer ' + token} if authenticated else {}
        data = None
        if body is not None:
            headers['Content-Type'] = 'application/json'
            data = json.dumps(body).encode()
        req = urllib.request.Request(hub + path, data=data, headers=headers)
        try:
            with urllib.request.urlopen(req, context=context, timeout=30) as response:
                return response.status, json.load(response)
        except urllib.error.HTTPError as error:
            return error.code, json.load(error)

    code, _ = request('/v1/runs', authenticated=False)
    assert code == 401, f'Unauthenticated run listing answered {code}'
    code, submitted = request('/v1/runs', {
        'name': 'Builder packaging smoke',
        'steps': [{'name': 'smoke', 'cog': 'builder-smoke', 'entry_point': 'run', 'input': {}}],
    })
    assert code == 201, (code, submitted)
    run_id = submitted['id']
    print('Submitted ' + run_id, flush=True)
    deadline = time.monotonic() + 240
    view = submitted
    while not view['ended'] and time.monotonic() < deadline:
        time.sleep(2)
        code, view = request('/v1/runs/' + run_id)
        assert code == 200, (code, view)
    assert view['status'] == 'COMPLETED', view
    assert view['location'] == 'remote', view
    code, payload = request(f'/v1/runs/{run_id}/steps/smoke/payload')
    assert code == 200, (code, payload)
    output = payload['payload']
    assert output['status'] == 'completed', output
    assert output['outputs']['first_tally']['total_words'] == 21
    assert output['outputs']['accumulated_tally']['total_words'] == 31
    assert 'track.json' in output['artifacts']
    code, events = request(f'/v1/runs/{run_id}/events')
    assert code == 200, (code, events)
    assert events['next_after'] is None, events
    assert any(event['type'] == 'worker_started' and event['payload']['location'] == 'remote'
               for event in events['items']), events
    assert any(event['type'] == 'completed' for event in events['items']), events
    evidence = {'run': view, 'payload': payload, 'events': events,
                'unauthenticated_status': 401}
    target = Path(os.environ.get('BUILDER_EVIDENCE_DIR', '/evidence'))
    target.mkdir(parents=True, exist_ok=True)
    path = target / (run_id + '.json')
    path.write_text(json.dumps(evidence, indent=2) + '\n')
    print(json.dumps({'status': 'PASS', 'run_id': run_id, 'evidence': str(path),
                      'first_total': 21, 'accumulated_total': 31}), flush=True)


if __name__ == '__main__':
    main()
