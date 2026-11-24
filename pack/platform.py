#!/usr/bin/env python3
"""Prepare a small, private Kubernetes test environment for the Builder pack."""
import argparse
import base64
import json
import os
from pathlib import Path
import secrets
import subprocess


INFRA = 'collab-builder-infra'
HUB = 'collab-builder'


def command(*args):
    return subprocess.run(args, check=True, capture_output=True, text=True).stdout


def apply(document):
    subprocess.run(['kubectl', 'apply', '-f', '-'],
                   input=json.dumps(document), text=True, check=True)


def resource(kind, name, namespace=INFRA, **fields):
    return {'apiVersion': 'v1', 'kind': kind,
            'metadata': {'name': name, 'namespace': namespace}, **fields}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--hostname', required=True)
    parser.add_argument('--port', type=int, default=8443)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if not os.environ.get('KUBECONFIG'):
        parser.error('Set KUBECONFIG to the intended disposable test cluster.')
    origin = f'https://{args.hostname}:{args.port}'
    for namespace in (INFRA, HUB):
        apply({'apiVersion': 'v1', 'kind': 'Namespace', 'metadata': {
            'name': namespace, 'labels': {'nebari.dev/managed': 'true'}}})
    found = subprocess.run(['kubectl', '-n', INFRA, 'get', 'secret', 'builder-credentials', '-o', 'json'],
                           capture_output=True, text=True)
    if found.returncode:
        if 'NotFound' not in found.stderr:
            raise RuntimeError(found.stderr)
        credentials = {key: secrets.token_urlsafe(32) for key in (
            'postgres-password', 'admin-password', 'client-secret')}
        apply(resource('Secret', 'builder-credentials', stringData=credentials))
    else:
        credentials = {key: base64.b64decode(value).decode()
                       for key, value in json.loads(found.stdout)['data'].items()}
    apply(resource('Secret', 'builder-database', HUB, stringData={
        'DATABASE_URL': f"postgresql://collab:{credentials['postgres-password']}@postgres.{INFRA}.svc:5432/collab"}))
    apply(resource('Secret', 'builder-proof', HUB, stringData={
        'client-secret': credentials['client-secret']}))
    for name, size in (('postgres', '5Gi'), ('keycloak', '1Gi')):
        apply(resource('PersistentVolumeClaim', name, spec={
            'accessModes': ['ReadWriteOnce'], 'resources': {'requests': {'storage': size}}}))
    apply({'apiVersion': 'cert-manager.io/v1', 'kind': 'ClusterIssuer',
           'metadata': {'name': 'builder-selfsigned'}, 'spec': {'selfSigned': {}}})
    apply({'apiVersion': 'cert-manager.io/v1', 'kind': 'Certificate',
           'metadata': {'name': 'builder-ca', 'namespace': 'cert-manager'},
           'spec': {'isCA': True, 'commonName': 'Builder test CA', 'secretName': 'builder-ca',
                    'privateKey': {'algorithm': 'ECDSA', 'size': 256},
                    'issuerRef': {'name': 'builder-selfsigned', 'kind': 'ClusterIssuer'}}})
    command('kubectl', '-n', 'cert-manager', 'wait', '--for=condition=Ready',
            'certificate/builder-ca', '--timeout=120s')
    apply({'apiVersion': 'cert-manager.io/v1', 'kind': 'ClusterIssuer',
           'metadata': {'name': 'builder-ca'}, 'spec': {'ca': {'secretName': 'builder-ca'}}})
    apply({'apiVersion': 'cert-manager.io/v1', 'kind': 'Certificate',
           'metadata': {'name': 'keycloak', 'namespace': INFRA}, 'spec': {
               'secretName': 'keycloak-tls', 'dnsNames': [
                   args.hostname, 'keycloak', f'keycloak.{INFRA}.svc', f'keycloak.{INFRA}.svc.cluster.local'],
               'issuerRef': {'name': 'builder-ca', 'kind': 'ClusterIssuer'}}})
    realm = {
        'realm': 'builder', 'enabled': True, 'sslRequired': 'external',
        'clients': [{
            'clientId': 'builder-proof', 'enabled': True, 'protocol': 'openid-connect',
            'publicClient': False, 'secret': credentials['client-secret'],
            'serviceAccountsEnabled': True, 'standardFlowEnabled': False,
            'protocolMappers': [{
                'name': 'hub-audience', 'protocol': 'openid-connect', 'protocolMapper': 'oidc-audience-mapper',
                'config': {'included.custom.audience': 'collab-hub', 'access.token.claim': 'true'}}],
        }],
    }
    apply(resource('Secret', 'builder-realm', stringData={'builder.json': json.dumps(realm)}))
    workloads = [
        ('postgres', 'postgres:16.15-alpine', [], [
            {'name': 'POSTGRES_USER', 'value': 'collab'},
            {'name': 'POSTGRES_DB', 'value': 'collab'},
            {'name': 'POSTGRES_PASSWORD', 'valueFrom': {'secretKeyRef': {
                'name': 'builder-credentials', 'key': 'postgres-password'}}}],
         [{'name': 'data', 'mountPath': '/var/lib/postgresql/data', 'subPath': 'pgdata'}],
         [{'name': 'data', 'persistentVolumeClaim': {'claimName': 'postgres'}}],
         [{'port': 5432, 'targetPort': 5432}],
         {'exec': {'command': ['pg_isready', '-U', 'collab']}}),
        ('keycloak', 'quay.io/keycloak/keycloak:26.8', ['start-dev', '--import-realm'], [
            {'name': 'KC_BOOTSTRAP_ADMIN_USERNAME', 'value': 'admin'},
            {'name': 'KC_BOOTSTRAP_ADMIN_PASSWORD', 'valueFrom': {'secretKeyRef': {
                'name': 'builder-credentials', 'key': 'admin-password'}}},
            {'name': 'KC_HOSTNAME', 'value': origin + '/auth'},
            {'name': 'KC_HTTP_RELATIVE_PATH', 'value': '/auth'},
            {'name': 'KC_PROXY_HEADERS', 'value': 'xforwarded'},
            {'name': 'KC_HTTP_ENABLED', 'value': 'true'},
            {'name': 'KC_HTTPS_CERTIFICATE_FILE', 'value': '/tls/tls.crt'},
            {'name': 'KC_HTTPS_CERTIFICATE_KEY_FILE', 'value': '/tls/tls.key'},
            {'name': 'JAVA_OPTS_APPEND', 'value': '-Xms128m -Xmx512m'}],
         [{'name': 'data', 'mountPath': '/opt/keycloak/data'},
          {'name': 'realm', 'mountPath': '/opt/keycloak/data/import', 'readOnly': True},
          {'name': 'tls', 'mountPath': '/tls', 'readOnly': True}],
         [{'name': 'data', 'persistentVolumeClaim': {'claimName': 'keycloak'}},
          {'name': 'realm', 'secret': {'secretName': 'builder-realm'}},
          {'name': 'tls', 'secret': {'secretName': 'keycloak-tls'}}],
         [{'name': 'http', 'port': 8080, 'targetPort': 8080},
          {'name': 'https', 'port': 8443, 'targetPort': 8443}],
         {'httpGet': {'path': '/auth/realms/builder', 'port': 8080}}),
    ]
    for name, image, arguments, environment, mounts, volumes, ports, probe in workloads:
        apply(resource('Service', name, spec={'selector': {'app': name}, 'ports': ports}))
        apply({'apiVersion': 'apps/v1', 'kind': 'Deployment',
               'metadata': {'name': name, 'namespace': INFRA}, 'spec': {
                   'replicas': 1, 'strategy': {'type': 'Recreate'},
                   'selector': {'matchLabels': {'app': name}}, 'template': {
                       'metadata': {'labels': {'app': name}}, 'spec': {
                           'automountServiceAccountToken': False,
                           'securityContext': {'fsGroup': 1000} if name == 'keycloak' else {},
                           'containers': [{'name': name, 'image': image, 'args': arguments,
                                           'env': environment, 'volumeMounts': mounts,
                                           'resources': {'requests': {'cpu': '100m', 'memory': '128Mi'},
                                                         'limits': {'cpu': '1', 'memory': '1Gi'}},
                                           'readinessProbe': {**probe, 'periodSeconds': 5},
                                           'startupProbe': {**probe, 'periodSeconds': 5, 'failureThreshold': 60}}],
                           'volumes': volumes}}}})
    apply({'apiVersion': 'gateway.envoyproxy.io/v1alpha1', 'kind': 'EnvoyProxy',
           'metadata': {'name': 'builder', 'namespace': 'envoy-gateway-system'},
           'spec': {'provider': {'type': 'Kubernetes', 'kubernetes': {
               'envoyService': {'type': 'ClusterIP'}}}}})
    apply({'apiVersion': 'gateway.networking.k8s.io/v1', 'kind': 'GatewayClass',
           'metadata': {'name': 'envoy-gateway'},
           'spec': {'controllerName': 'gateway.envoyproxy.io/gatewayclass-controller',
                    'parametersRef': {'group': 'gateway.envoyproxy.io', 'kind': 'EnvoyProxy',
                                      'name': 'builder', 'namespace': 'envoy-gateway-system'}}})
    apply({'apiVersion': 'gateway.networking.k8s.io/v1', 'kind': 'Gateway',
           'metadata': {'name': 'nebari-gateway', 'namespace': 'envoy-gateway-system'}, 'spec': {
               'gatewayClassName': 'envoy-gateway', 'listeners': [{
                   'name': 'http', 'protocol': 'HTTP', 'port': 80,
                   'allowedRoutes': {'namespaces': {'from': 'All'}}}]}})
    apply({'apiVersion': 'gateway.networking.k8s.io/v1beta1', 'kind': 'ReferenceGrant',
           'metadata': {'name': 'keycloak-route', 'namespace': INFRA}, 'spec': {
               'from': [{'group': 'gateway.networking.k8s.io', 'kind': 'HTTPRoute', 'namespace': HUB}],
               'to': [{'group': '', 'kind': 'Service', 'name': 'keycloak'}]}})
    apply({'apiVersion': 'gateway.networking.k8s.io/v1', 'kind': 'HTTPRoute',
           'metadata': {'name': 'keycloak', 'namespace': HUB}, 'spec': {
               'parentRefs': [{'name': 'nebari-gateway', 'namespace': 'envoy-gateway-system'}],
               'hostnames': [args.hostname], 'rules': [{
                   'matches': [{'path': {'type': 'PathPrefix', 'value': '/auth'}}],
                   'backendRefs': [{'name': 'keycloak', 'namespace': INFRA, 'port': 8080}]}]}})
    command('kubectl', '-n', INFRA, 'rollout', 'status', 'deployment/postgres', '--timeout=300s')
    command('kubectl', '-n', INFRA, 'rollout', 'status', 'deployment/keycloak', '--timeout=300s')
    ca = json.loads(command('kubectl', '-n', 'cert-manager', 'get', 'secret', 'builder-ca', '-o', 'json'))
    certificate = base64.b64decode(ca['data']['tls.crt']).decode()
    apply(resource('ConfigMap', 'builder-ca', HUB, data={'ca.crt': certificate}))
    jwks = f'https://keycloak.{INFRA}.svc:8443/auth/realms/builder/protocol/openid-connect/certs'
    args.output.write_text(json.dumps({
        'fullnameOverride': 'collab-hub',
        'namespace': {'create': False},
        'api': {'nebariapp': {'enabled': True, 'hostname': args.hostname,
                             'auth': {'enabled': False},
                             'routing': {'publicRoutes': []},
                             'landingPage': {'displayName': 'Collab Builder test Hub'}},
                'deployment': {'image': {'repository': 'collab-builder/worker', 'tag': 'step1', 'pullPolicy': 'Never'},
                               'extraEnv': [{'name': 'SSL_CERT_FILE', 'value': '/etc/collab-hub/cogs-ca/ca.crt'}],
                               'resources': {'requests': {'cpu': '100m', 'memory': '256Mi'},
                                             'limits': {'cpu': '1', 'memory': '768Mi'}}}},
        'security': {'enforce': True},
        'frames': {'auth': {'bearer': {'jwksUrl': jwks, 'issuer': origin + '/auth/realms/builder',
                                       'audience': 'collab-hub'},
                            'identityClaim': 'sub', 'orgSource': 'claims',
                            'defaults': {'orgId': 'builder-test', 'workspaceId': 'default'}},
                   'postgres': {'existingSecret': 'builder-database', 'autoMigrate': True},
                   'storage': {'persistence': {'enabled': True, 'size': '2Gi'}}},
        'cogs': {'caBundle': {'configMap': 'builder-ca'}},
        'runs': {'controller': {'enabled': True, 'location': 'remote', 'environment': 'pixi',
                                 'id': 'builder-test', 'workerStartSeconds': 120,
                                 'worker': {'resources': {'requests': {'cpu': '100m', 'memory': '128Mi'},
                                                          'limits': {'cpu': '1', 'memory': '1Gi'}}}}},
    }, indent=2) + '\n')
    print('Platform ready. Hub values written to ' + str(args.output))


if __name__ == '__main__':
    main()
