"""The real data-backup command must use the built image, even if the old image ID vanished."""
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parent.parent


class BackupImageTests(unittest.TestCase):
    def test_data_backup_does_not_require_the_previous_image(self):
        git=shutil.which('git');candidate=Path(git).parent.parent/'bin/bash.exe' if git else Path('/none')
        bash=str(candidate) if candidate.is_file() else shutil.which('bash')
        if not bash:self.skipTest('Bash unavailable')
        script=(ROOT/'tools/deploy_current_release.sh').read_text(encoding='utf-8')
        command=script.split('docker run --rm --volumes-from',1)[1].split('\ndocker compose --profile review up',1)[0]
        command='docker run --rm --volumes-from'+command
        prelude='''set -e
old_app=retained-container
old_image=sha256:unavailable-old-image
image_name=space-news-app
evidence=/unused-backup
docker() {
 while [[ $# -gt 0 ]];do
  if [[ "$1" == --entrypoint ]];then
   [[ "$2" == python && "$3" == space-news-app ]] || return 125
   echo CURRENT_IMAGE_BACKUP_OK;return 0
  fi
  shift
 done
 return 1
}
'''
        result=subprocess.run([bash,'-c',prelude+command],capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn('CURRENT_IMAGE_BACKUP_OK',result.stdout)


if __name__=='__main__':unittest.main()
