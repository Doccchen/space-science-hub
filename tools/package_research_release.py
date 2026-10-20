"""Package only the reviewed research-workspace files against captured live baselines."""
import hashlib
import io
import json
import shutil
import tarfile
from tools.prepare_research_release import ROOT, OUT, GROUPS


def sha(blob):
    return hashlib.sha256(blob).hexdigest()


def main():
    state = json.loads((OUT/'preflight.json').read_text())
    checks = [
        ('app','web/index.html', [('<a href="/reader/">论文查找</a><a href="/#page/home" data-page="home">知识问答</a>', '<a href="/assets/research.html">研究助手</a>'), ('/assets/news-reader.js?v=20261019-stable-nav','/assets/news-reader.js?v=20261020-research-1')]),
        ('app','web/news-reader.js', [("'/reader/?news='", "'/assets/research.html?news='")]),
        ('app','web/resource-navigation.html', [('<a href="/reader/">论文查找</a><a href="/#page/home">知识问答</a>', '<a href="/assets/research.html">研究助手</a>')]),
        ('reader','reader_web/index.html', [('<a href="/reader/" class="active" aria-current="page">论文查找</a><a href="/#page/home">知识问答</a>', '<a href="/assets/research.html">研究助手</a>')]),
    ]
    for service, name, replacements in checks:
        before = (OUT/'baseline'/service/name).read_text(encoding='utf-8-sig')
        for old,new in replacements:
            assert before.count(old) == 1, 'Unexpected live baseline: ' + name
            before = before.replace(old,new)
        assert before.rstrip() == (ROOT/name).read_text(encoding='utf-8-sig').rstrip(), 'Unrelated change: ' + name
    files = {}
    for name in ['web/research.html','web/research.css','web/research.js']:
        assert state['baselines']['app'][name] is None, 'Unexpected existing workspace'
    names = sorted({n for group in GROUPS.values() for n in group})
    with tarfile.open(OUT/'release.tar.gz','w:gz') as archive:
        for name in names:
            blob=(ROOT/name).read_bytes();files[name]=sha(blob)
            member=tarfile.TarInfo(name);member.size=len(blob);member.mode=0o644
            archive.addfile(member,io.BytesIO(blob))
    manifest={**state,'groups':GROUPS,'files':files,'archive_sha256':sha((OUT/'release.tar.gz').read_bytes())}
    (OUT/'manifest.json').write_text(json.dumps(manifest,indent=2))
    # Reuse the audited static deployer: verifies unchanged settings, builds durable
    # image layers, preserves runtime/source backups, and rolls back on failures.
    deploy=(ROOT/'tools/deploy_design_audit.py').read_text(encoding='utf-8')
    deploy=deploy.replace('design-audit','research-workspace')
    (OUT/'deploy_research.py').write_text(deploy,encoding='utf-8')
    shutil.copy2(ROOT/'tools/deploy_news_switch.py',OUT/'deploy_news_switch.py')
    print(json.dumps({'files':len(files),'bytes':(OUT/'release.tar.gz').stat().st_size,'reviewed_navigation_changes':len(checks)}))


if __name__ == '__main__':
    main()
