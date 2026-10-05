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
GEOGRAPHIC_REGIONS = {
    'north_america': '北美', 'europe': '欧洲', 'east_asia': '东亚',
    'south_asia': '南亚', 'oceania': '大洋洲',
}
# Publisher/headquarters geography, not launch-site or all operational regions.
for source_id, geography, country in (
    ('nasa', 'north_america', 'US'), ('esa', 'europe', None),
    ('cnsa', 'east_asia', 'CN'), ('cmse', 'east_asia', 'CN'),
    ('cas_space', 'east_asia', 'CN'), ('landspace', 'east_asia', 'CN'),
):
    SOURCES[source_id].update(geographic_region=geography, country_code=country)

INTERNATIONAL_BATCH_ONE = ('spacex', 'blue_origin', 'arianespace', 'ispace')
INTERNATIONAL_BATCH_TWO = ('skyroot', 'gilmour')
INTERNATIONAL_COMPANIES = INTERNATIONAL_BATCH_ONE + INTERNATIONAL_BATCH_TWO
SOURCES.update({
    'spacex': dict(name='SpaceX', url='https://www.spacex.com/updates/', domain='spacex.com',
                  collector_kind='html', region='international', publisher_kind='company', enabled=False,
                  geographic_region='north_america', country_code='US',
                  availability_note='2026-10-05服务器返回Cloudflare 1009：限制CN访问；未自动接入'),
    'blue_origin': dict(name='Blue Origin（蓝色起源）', url='https://www.blueorigin.com/news', domain='blueorigin.com',
                       collector_kind='html', region='international', publisher_kind='company', enabled=False,
                       geographic_region='north_america', country_code='US', availability_note='2026-10-05服务器遇Vercel安全检查，尚未取得新闻载荷'),
    'arianespace': dict(name='Arianespace', url='https://www.arianespace.com/updates-en/', domain='arianespace.com',
                       collector_kind='html', region='international', publisher_kind='company', enabled=False,
                       geographic_region='europe', country_code='FR', availability_note='等待服务器采集验证'),
    'ispace': dict(name='ispace（日本）', url='https://www.ispace-inc.com/news/', domain='ispace-inc.com',
                  collector_kind='html', region='international', publisher_kind='company', enabled=False,
                  geographic_region='east_asia', country_code='JP', availability_note='等待服务器采集验证'),
    'skyroot': dict(name='Skyroot Aerospace', url='https://www.skyroot.in/newsroom', domain='skyroot.in',
                   collector_kind='html', region='international', publisher_kind='company', enabled=False,
                   geographic_region='south_asia', country_code='IN', availability_note='2026-10-05官网新闻页仅发现政府、合作方或媒体外链；未自动接入公司自发稿'),
    'gilmour': dict(name='Gilmour Space', url='https://www.gspace.com/update', domain='gspace.com',
                   collector_kind='html', region='international', publisher_kind='company', enabled=False,
                   geographic_region='oceania', country_code='AU', availability_note='等待服务器采集验证'),
})
CATEGORIES = {
    'domestic_agency': ('domestic', 'agency'),
    'commercial': (None, 'company'),
    'international_agency': ('international', 'agency'),
}
