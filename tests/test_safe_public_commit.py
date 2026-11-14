"""Real local-git concurrency regression tests for public archive persistence.

Uses isolated bare Git repositories; no network, credentials, account tokens
or actual user data. Production never force-pushes main.
"""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "safe_commit_public_data.sh"
DIR = "data/market_backfill_pilot"
NAME = "2026-11-10.json.gz"


def git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, check=True,
                          capture_output=True, text=True).stdout.strip()


@unittest.skipUnless(shutil.which("git") and shutil.which("bash"),
                     "Requires git and bash")
class PublicArchiveCommitTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.remote = self.root / "remote.git"
        self.seed = self.root / "seed"
        self.worker = self.root / "worker"
        self.racer = self.root / "racer"
        git(self.root, "init", "--bare", "--initial-branch=main", str(self.remote))
        git(self.root, "clone", str(self.remote), str(self.seed))
        self.identity(self.seed)
        (self.seed / "README.md").write_text("source\n", encoding="utf-8")
        initial = self.seed / DIR
        initial.mkdir(parents=True)
        (initial / NAME).write_text("baseline\n", encoding="utf-8")
        git(self.seed, "add", "--", "README.md", DIR)
        git(self.seed, "commit", "-m", "initial")
        git(self.seed, "push", "origin", "HEAD:main")
        git(self.root, "clone", str(self.remote), str(self.worker))
        git(self.root, "clone", str(self.remote), str(self.racer))
        self.identity(self.worker)
        self.identity(self.racer)

    def tearDown(self):
        self.temp.cleanup()

    @staticmethod
    def identity(root):
        git(root, "config", "user.name", "Git Test")
        git(root, "config", "user.email", "git-test@example.invalid")

    def helper(self, directory=DIR):
        return subprocess.run(["bash", str(SCRIPT), directory, "data: safe test"],
                              cwd=self.worker, capture_output=True, text=True)

    def test_concurrent_unrelated_main_update_is_safely_rebased(self):
        (self.worker / DIR / "2026-11-09.json.gz").write_text("new validated\n")
        (self.racer / "README.md").write_text("concurrent main edit\n")
        git(self.racer, "add", "README.md")
        git(self.racer, "commit", "-m", "concurrent README update")
        git(self.racer, "push", "origin", "HEAD:main")
        result = self.helper()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("Committed validated public archives", result.stdout)
        reader = self.root / "reader"
        git(self.root, "clone", str(self.remote), str(reader))
        self.assertEqual((reader / "README.md").read_text(), "concurrent main edit\n")
        self.assertEqual((reader / DIR / "2026-11-09.json.gz").read_text(),
                         "new validated\n")

    def test_concurrent_same_file_edit_fails_closed(self):
        (self.worker / DIR / NAME).write_text("local validated\n")
        (self.racer / DIR / NAME).write_text("remote different content\n")
        git(self.racer, "add", "--", DIR)
        git(self.racer, "commit", "-m", "concurrent same filename")
        git(self.racer, "push", "origin", "HEAD:main")
        result = self.helper()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("refusing to overwrite", result.stderr)
        reader = self.root / "reader"
        git(self.root, "clone", str(self.remote), str(reader))
        self.assertEqual((reader / DIR / NAME).read_text(),
                         "remote different content\n")

    def test_wrong_path_rejected(self):
        result = self.helper("config")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("allowlist", result.stderr)

    def test_non_gzip_artifact_rejected(self):
        (self.worker / DIR / "secret.txt").write_text("not a quote archive")
        result = self.helper()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Unexpected staged file", result.stderr)

    def test_no_change_idempotent(self):
        result = self.helper()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("No changes", result.stdout)

    def test_deletion_refused(self):
        (self.worker / DIR / NAME).unlink()
        result = self.helper()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Deletion", result.stderr)


if __name__ == "__main__":
    unittest.main()
