"""Reviewed publishers and paths; visitors cannot add fetch URLs."""
SOURCES = {
    'nasa': dict(name='NASA', url='https://www.nasa.gov/news-release/feed/', domain='nasa.gov',
                 collector_kind='rss', region='international', publisher_kind='agency', enabled=True),
    'esa': dict(name='ESA', url='https://www.esa.int/rssfeed/Our_Activities/Space_News', domain='esa.int',
                collector_kind='rss', region='international', publisher_kind='agency', enabled=True),
    'cnsa': dict(name='国家航天局', url='https://www.cnsa.gov.cn/n6758823/n6758838/index.html', domain='cnsa.gov.cn',
                 collector_kind='html', region='domestic', publisher_kind='agency', enabled=False,
                 detail_pattern=r'/n6758823/n6758838/c\d+/content\.html'),
    'cmse': dict(name='中国载人航天', url='https://www.cmse.gov.cn/xwzx/zhxw/', domain='cmse.gov.cn',
                 collector_kind='html', region='domestic', publisher_kind='agency', enabled=False,
                 detail_pattern=r'/xwzx/(?:zhxw/)?\d{6}/t\d+_\d+\.html'),
    'cas_space': dict(name='中科宇航', url='https://www.cas-space.com/list/6.html', domain='cas-space.com',
                      collector_kind='html', region='domestic', publisher_kind='company', enabled=False,
                      detail_pattern=r'/article/\d+\.html'),
    'landspace': dict(name='蓝箭航天', url='https://www.landspace.com/news.html?catid=1&mao=1', domain='landspace.com',
                      collector_kind='html', region='domestic', publisher_kind='company', enabled=False,
                      detail_pattern=r'/news-detail\.html'),
}
CATEGORIES = {
    'domestic_agency': ('domestic', 'agency'),
    'commercial': (None, 'company'),
    'international_agency': ('international', 'agency'),
}
