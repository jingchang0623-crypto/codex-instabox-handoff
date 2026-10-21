import importlib.util
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('installer', ROOT/'scripts/install_skill.py')
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


class InstallerTests(unittest.TestCase):
    def test_guard_upgrade_backup_and_unrelated_data(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)/'codex'
            unrelated = home/'other-profile/keep'
            unrelated.parent.mkdir(parents=True)
            unrelated.write_text('keep')
            source = ROOT/'skills/instabox-handoff'
            destination, backup = installer.install(source, home)
            self.assertIsNone(backup)
            (destination/'local-note').write_text('old')
            with self.assertRaises(FileExistsError):
                installer.install(source, home)
            destination, backup = installer.install(source, home, upgrade=True)
            self.assertEqual((backup/'local-note').read_text(), 'old')
            self.assertNotIn(home/'skills', backup.parents)
            self.assertFalse((destination/'local-note').exists())
            self.assertEqual(unrelated.read_text(), 'keep')
            self.assertEqual((destination/'SKILL.md').read_bytes(), (source/'SKILL.md').read_bytes())
