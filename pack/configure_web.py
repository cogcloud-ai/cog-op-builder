#!/usr/bin/env python3
"""Enable the pinned Hub's existing Keycloak browser sign-in surface."""
import argparse
import base64
import json
import os
from pathlib import Path
import secrets
import ssl
import subprocess
import sys
import urllib.parse
import urllib.request


INFRA = 'collab-builder-infra'
HUB = 'collab-builder'


def kube(*arguments):
    return json.loads(subprocess.check_output(['kubectl', *arguments, '-o', 'json']))


def apply(document):
    subprocess.run(['kubectl', 'apply', '-f', '-'], input=json.dumps(document),
                   text=True, check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--origin', required=True)
    parser.add_argument('--values', type=Path, required=True)
    parser.add_argument('--username', default='trent')
    parser.add_argument('--password-stdin', action='store_true')
    args = parser.parse_args()
    if not os.environ.get('KUBECONFIG'):
        parser.error('Set KUBECONFIG to the intended test cluster.')
    origin = args.origin.rstrip('/')
    if not origin.startswith('https://'):
        parser.error('The browser origin requires HTTPS.')
    values = json.loads(args.values.read_text())
    if values['frames']['auth']['bearer']['issuer'] != origin + '/auth/realms/builder':
        parser.error('The origin must match the configured Hub bearer issuer.')
    password = sys.stdin.read().rstrip('\r\n') if args.password_stdin else None
    if args.password_stdin and not password:
        parser.error('The account password cannot be empty.')
    stored = kube('-n', INFRA, 'get', 'secret', 'builder-credentials')['data']
    credentials = {key: base64.b64decode(value).decode() for key, value in stored.items()}
    additions = {key: secrets.token_urlsafe(32) for key in ('web-secret', 'session-secret')
                 if key not in credentials}
    if additions:
        subprocess.run(['kubectl', '-n', INFRA, 'patch', 'secret', 'builder-credentials',
                        '--type=merge', '--patch-file=/dev/stdin'],
                       input=json.dumps({'stringData': additions}), text=True, check=True)
        credentials.update(additions)
    ca = kube('-n', HUB, 'get', 'configmap', 'builder-ca')['data']['ca.crt']
    context = ssl.create_default_context(cadata=ca)
    form = urllib.parse.urlencode({
        'grant_type': 'password', 'client_id': 'admin-cli', 'username': 'admin',
        'password': credentials['admin-password'],
    }).encode()
    token_request = urllib.request.Request(
        origin + '/auth/realms/master/protocol/openid-connect/token', data=form)
    with urllib.request.urlopen(token_request, context=context, timeout=30) as response:
        token = json.load(response)['access_token']

    def admin(method, path, document=None):
        headers = {'Authorization': 'Bearer ' + token}
        body = None
        if document is not None:
            headers['Content-Type'] = 'application/json'
            body = json.dumps(document).encode()
        request = urllib.request.Request(origin + '/auth/admin/realms/builder/' + path,
                                         headers=headers, data=body, method=method)
        with urllib.request.urlopen(request, context=context, timeout=30) as response:
            content = response.read()
            return json.loads(content) if content else None

    clients = admin('GET', 'clients?clientId=builder-web')
    client = {
        'clientId': 'builder-web', 'enabled': True, 'protocol': 'openid-connect',
        'publicClient': False, 'secret': credentials['web-secret'],
        'standardFlowEnabled': True, 'directAccessGrantsEnabled': False,
        'serviceAccountsEnabled': False,
        'redirectUris': [origin + '/web/oidc/callback'], 'webOrigins': [origin],
        'defaultClientScopes': ['basic', 'email', 'profile', 'roles'],
        'attributes': {
            'pkce.code.challenge.method': 'S256',
            'post.logout.redirect.uris': origin + '/web/signed-out',
            'backchannel.logout.url': origin + '/web/oidc/backchannel-logout',
            'backchannel.logout.session.required': 'true',
        },
    }
    if clients:
        admin('PUT', 'clients/' + clients[0]['id'], client)
    else:
        admin('POST', 'clients', client)
    users = admin('GET', 'users?' + urllib.parse.urlencode({'username': args.username, 'exact': 'true'}))
    if not users:
        if password is None:
            parser.error('Creating an account requires --password-stdin.')
        admin('POST', 'users', {
            'username': args.username, 'enabled': True,
            'firstName': args.username, 'requiredActions': [],
            'credentials': [{'type': 'password', 'value': password, 'temporary': False}],
        })
    elif password is not None:
        admin('PUT', 'users/' + users[0]['id'] + '/reset-password',
              {'type': 'password', 'value': password, 'temporary': False})
    apply({'apiVersion': 'v1', 'kind': 'Secret',
           'metadata': {'name': 'builder-web', 'namespace': HUB},
           'stringData': {'client-secret': credentials['web-secret'],
                          'session-secret': credentials['session-secret']}})
    entries = {
        'COLLAB_HUB_API__WEB__CLIENT_ID': {'value': 'builder-web'},
        'COLLAB_HUB_API__WEB__CLIENT_SECRET': {'valueFrom': {'secretKeyRef': {
            'name': 'builder-web', 'key': 'client-secret'}}},
        'COLLAB_HUB_API__WEB__SESSION_SECRET': {'valueFrom': {'secretKeyRef': {
            'name': 'builder-web', 'key': 'session-secret'}}},
        'COLLAB_HUB_API__WEB__PUBLIC_BASE_URL': {'value': origin},
    }
    environment = values['api']['deployment']['extraEnv']
    environment[:] = [entry for entry in environment if entry['name'] not in entries]
    environment.extend({'name': name, **value} for name, value in entries.items())
    args.values.write_text(json.dumps(values, indent=2) + '\n')
    # Cluster traffic must not hairpin through the host's blocked Tailscale
    # interface. Keep the public TLS name and port, using an internal gateway
    # Service for the API's server-side OIDC requests.
    gateway_namespace = 'envoy-gateway-system'
    gateways = kube('-n', gateway_namespace, 'get', 'service', '-l',
                    'app.kubernetes.io/managed-by=envoy-gateway,'
                    'gateway.envoyproxy.io/owning-gateway-name=nebari-gateway')['items']
    if len(gateways) != 1:
        parser.error('Expected one Envoy service for nebari-gateway.')
    tls_port = next(port for port in gateways[0]['spec']['ports'] if port['port'] == 443)
    apply({'apiVersion': 'v1', 'kind': 'Service',
           'metadata': {'name': 'builder-web-internal', 'namespace': gateway_namespace},
           'spec': {'selector': gateways[0]['spec']['selector'], 'ports': [{
               'name': 'https', 'port': urllib.parse.urlsplit(origin).port or 443,
               'targetPort': tls_port['targetPort'], 'protocol': 'TCP'}]}})
    internal_ip = kube('-n', gateway_namespace, 'get', 'service',
                       'builder-web-internal')['spec']['clusterIP']
    hostname = urllib.parse.urlsplit(origin).hostname
    deployment = kube('-n', HUB, 'get', 'deployment', 'collab-hub-api')
    aliases = deployment['spec']['template']['spec'].get('hostAliases', [])
    aliases = [{'ip': entry['ip'], 'hostnames': [name for name in entry['hostnames']
                                               if name != hostname]} for entry in aliases]
    aliases = [entry for entry in aliases if entry['hostnames']]
    aliases.append({'ip': internal_ip, 'hostnames': [hostname]})
    subprocess.run(['kubectl', '-n', HUB, 'patch', 'deployment', 'collab-hub-api',
                    '--type=merge', '--patch-file=/dev/stdin'],
                   input=json.dumps({'spec': {'template': {'spec': {'hostAliases': aliases}}}}),
                   text=True, check=True)
    apply({'apiVersion': 'gateway.networking.k8s.io/v1', 'kind': 'HTTPRoute',
           'metadata': {'name': 'builder-home', 'namespace': HUB}, 'spec': {
               'parentRefs': [{'name': 'nebari-gateway', 'namespace': 'envoy-gateway-system'}],
               'hostnames': [urllib.parse.urlsplit(origin).hostname], 'rules': [{
                   'matches': [{'path': {'type': 'Exact', 'value': '/'}}],
                   'filters': [{'type': 'RequestRedirect', 'requestRedirect': {
                       'path': {'type': 'ReplaceFullPath', 'replaceFullPath': '/web/home'},
                       'port': urllib.parse.urlsplit(origin).port or 443, 'statusCode': 302}}]}]}})
    print('Browser client configured for ' + args.username + '. Apply the updated Hub values.')


if __name__ == '__main__':
    main()
