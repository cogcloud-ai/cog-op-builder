import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

SPEC = importlib.util.spec_from_file_location('check_workspace', Path(__file__).resolve().parents[1] / 'scripts/check_workspace.py')
checker = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(checker)


class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.workspace = Path(self.temp.name)
        self.suite = self.workspace / 'cog-op-builder'
        self.component = self.workspace / 'cog-example'
        for root in [self.suite, self.component]:
            root.mkdir()
            self.git(root, 'init', '-q')
            self.git(root, 'config', 'user.email', 'test@example.invalid')
            self.git(root, 'config', 'user.name', 'Test')
            (root / 'README.md').write_text('Public component\n')
            self.commit(root)
        revision = self.git(self.component, 'rev-parse', 'HEAD')
        (self.suite / 'repositories.json').write_text(json.dumps({'repositories': [{'name': self.component.name, 'revision': revision}]}))
        (self.suite / 'workspace-exceptions.json').write_text('{"exceptions": []}')
        self.commit(self.suite)

    def git(self, root, *args):
        return subprocess.check_output(['git', '-C', str(root), *args], stderr=subprocess.DEVNULL).decode().strip()

    def commit(self, root):
        self.git(root, 'add', '.')
        self.git(root, 'commit', '-qm', 'Fixture')

    def scan(self):
        return checker.scan(self.workspace, self.suite)

    def test_clean_pins_pass(self):
        self.assertEqual(checker.check(self.workspace, self.suite, True), [])

    def test_dirty_and_revision_drift(self):
        (self.component / 'new.txt').write_text('change')
        self.assertTrue(any('dirty' in x for x in checker.checkout_errors(self.workspace, self.suite, True)))
        self.commit(self.component)
        self.assertTrue(any('HEAD differs' in x for x in checker.checkout_errors(self.workspace, self.suite, True)))

    def test_untracked_private_reference_and_machine_path(self):
        (self.component / 'new.md').write_text('../' + 'cog-private/input.txt\n/' + 'Users/alice/private.txt\n')
        self.assertEqual({x['rule'] for x in self.scan()}, {'undeclared-sibling', 'machine-path'})

    def test_public_sibling_link_passes_missing_link_fails(self):
        (self.component / 'guide.md').write_text('[suite](../cog-op-builder/README.md)\n[missing](missing.md)\n')
        findings = self.scan()
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0]['rule'], 'local-link')

    def test_symlink_escape_and_valid_sibling(self):
        (self.component / 'outside').symlink_to(self.workspace.parent)
        (self.component / 'inside').symlink_to(self.suite / 'README.md')
        self.assertEqual([x['rule'] for x in self.scan()], ['symlink'])

    def test_undeclared_toml_path(self):
        (self.component / 'pixi.toml').write_text('[pypi-dependencies]\nprivate = {path = "../../private"}\n')
        self.assertEqual([x['rule'] for x in self.scan()], ['local-dependency'])

    def test_exception_counts_and_staleness(self):
        file = self.component / 'old.md'
        reference = '../' + 'cog-private/input.txt\n'
        file.write_text(reference)
        item = self.scan()[0]
        item.update(count=1, reason='Test fixture')
        (self.suite / 'workspace-exceptions.json').write_text(json.dumps({'exceptions': [item]}))
        self.assertEqual(checker.check(self.workspace, self.suite), [])
        file.write_text(reference * 2)
        self.assertTrue(checker.check(self.workspace, self.suite))
        file.unlink()
        self.assertTrue(any('stale' in x for x in checker.check(self.workspace, self.suite)))

    def test_constructed_private_sibling_is_rejected(self):
        (self.component / 'caller.py').write_text("CALLER = ROOT.parent / '" + 'cog-' + "issue-classifier'\n")
        self.assertEqual([x['rule'] for x in self.scan()], ['private-reference'])

    def test_missing_checkout(self):
        self.component.rename(self.workspace / 'elsewhere')
        self.assertTrue(any('missing Git checkout' in x for x in checker.check(self.workspace, self.suite)))


if __name__ == '__main__':
    unittest.main()
