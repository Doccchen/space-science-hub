"""Package the news reader against live baselines, using the established rollback flow."""
import prepare_guides_release as release


if __name__ == '__main__':
    release.OUT = release.ROOT/'artifacts/news-reader-release-20261023'
    release.GROUPS = {
        'app': ['backend/reading.py', 'backend/review_capture.py',
                'web/index.html', 'web/news-reader.js', 'web/article-renderer.js',
                'web/article.css', 'web/styles/pages.css', 'web/guides.html', 'web/research.html',
                'tests/test_news_links.py'],
        'admin': ['backend/reading.py', 'backend/review_capture.py'],
    }
    release.SOURCE_ONLY = ['tools/build_styles.py']
    release.main()
    script = (release.ROOT/'tools/deploy_guides.py').read_text(encoding='utf-8').replace('guides', 'news-reader')
    old = '''run('docker','run','--rm','--network','none',images[s],'python','-c',"from backend import reading;assert 'markdown' in __import__('inspect').getsource(reading.validate)")'''
    new = '''run('docker','run','--rm','--network','none',images[s],'python','-c',"from backend import reading,review_capture;assert hasattr(reading,'validate_links') and hasattr(review_capture,'text_and_links')")
        if s == 'app':
            run('docker','run','--rm','--network','none',images[s],'python','-m','unittest','discover','-s','tests','-p','test_news_links.py')'''
    assert old in script
    script = script.replace(old, new)
    (release.OUT/'deploy_news_reader.py').write_text(script, encoding='utf-8')
