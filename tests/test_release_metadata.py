"""Windows-generated release metadata must remain valid Linux deployment arguments."""
import io
import shutil
import subprocess
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from tools import package_current_release

ROOT=Path(__file__).resolve().parent.parent


class ReleaseMetadataTests(unittest.TestCase):
    def test_packaged_metadata_uses_lf_only(self):
        with redirect_stdout(io.StringIO()):
            package_current_release.main()
        for suffix in ('revision','sha256'):
            data=(ROOT/'artifacts/packages'/('space-unified-release-20261007.'+suffix)).read_bytes()
            self.assertNotIn(b'\r',data)
            self.assertTrue(data.endswith(b'\n'))

    def test_deployment_accepts_crlf_revision_argument(self):
        git=shutil.which('git')
        git_bash=Path(git).parent.parent/'bin/bash.exe' if git else Path('/nonexistent')
        bash=str(git_bash) if git_bash.is_file() else shutil.which('bash')
        if not bash:self.skipTest('Bash unavailable')
        script=(ROOT/'tools/deploy_current_release.sh').read_text(encoding='utf-8')
        prefix=script.split('test -f "$archive"',1)[0]
        # Only exercise the real argument checks; no host directory or Docker access.
        for ending in ('',r'\r'):
            arguments='set -- unused '+('a'*64)+' "$(printf \''+('b'*40)+ending+'\')"\n'
            probe='cd() { :; };\n'+arguments+prefix+'\necho ARGUMENTS_OK\n'
            result=subprocess.run([bash,'-c',probe],capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertIn('ARGUMENTS_OK',result.stdout)


if __name__=='__main__':unittest.main()
