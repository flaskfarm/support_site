import urllib.parse
from datetime import datetime
from http.cookies import SimpleCookie

import requests
from lxml import etree, html

from .entity_base import EntityExtra, EntitySearchItemTvDaum
from .setup import *
from .site_util import SiteUtil


class SiteDaum(object):
    _daum_cookie = None
    _use_proxy = None
    _proxy_url = None

    site_name = 'daum'
    default_headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
        'Accept' : 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8',
        'Accept-Language' : 'ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7'
    }

    REDIS_KEY_DAUM = f'{REDIS_KEY_PLUGIN}:daum'

    @classmethod
    def initialize(cls, daum_cookie, use_proxy=False, proxy_url=None):
        cookies = SimpleCookie()
        cookies.load(daum_cookie)
        cls._daum_cookie = {key:morsel.value for key, morsel in cookies.items()}
        cls._use_proxy = use_proxy
        if cls._use_proxy:
            cls._proxy_url = proxy_url
        else:
            cls._proxy_url = None

    @classmethod
    def get_tree(cls, url):
        doc = SiteUtil.get_tree(url, proxy_url=cls._proxy_url, headers=cls.default_headers, cookies=cls._daum_cookie)
        captcha_scripts = doc.xpath('//script[contains(text(), "captcha")]')
        if captcha_scripts:
            logger.warning(f'url="{url}"\nbody="{etree.tostring(doc, encoding=str)}"')
        return doc

    @classmethod
    def get_show_info_on_home(cls, root):
        try:
            entity = EntitySearchItemTvDaum(cls.site_name)

            # 제목 및 코드
            title_elements = root.xpath('//div[@id="tvpColl"]//div[@class="inner_header"]/strong/a')
            if title_elements:
                entity.title = title_elements[0].text.strip()
                query = dict(urllib.parse.parse_qsl(title_elements[0].attrib['href']))
                entity.code = f'{cls.module_char}{cls.site_char}{query.get("spId", "").strip()}'
            else:
                html_titles = root.xpath('//title/text()')
                if html_titles:
                    html_titles_text = ' '.join(html_titles).strip()
                    logger.warning(f'검색 실패: {html_titles_text}')
                else:
                    logger.warning(f'검색 실패: {etree.tostring(root, encoding=str)}')
                return

            # 에피소드 번호 초기화
            entity.episode = -1

            '''
            중국드라마 | 50부작 | 10.06.24. ~ 10. | 완결
            예능 | 10.07.11. ~
            영국드라마 | 10부작 | 24.11.15. ~
            뉴스 | 70.10.05. ~
            '''
            sub_headers = root.xpath('//div[@id="tvpColl"]//div[@class="sub_header"]/span/span')
            # 장르
            if sub_headers:
                entity.genre = sub_headers[0].xpath('string()').strip()
                del sub_headers[0]

            # 방송 상태 및 방영일
            '''
            status:
                0: 방송예정
                1: 방송중
                2: 방송종료
            '''
            entity.status = 1
            entity.year = 0
            regex_term = re.compile(r'(.+)\s~(\s.+)?')
            premired: datetime = None
            for h in sub_headers:
                t = h.xpath('string()').strip()
                if not t:
                    continue
                if t in ['방송종료', '완결']:
                    entity.status = 2
                    continue
                elif t in ['방송예정']:
                    entity.status = 0
                    continue
                match = regex_term.search(t)
                if match:
                    entity.broadcast_term = match.group(1)
                    premired = cls.parse_date_text(entity.broadcast_term)
                    entity.year = premired.year if premired else 1900

            # 포스터
            try:
                poster_elements = root.xpath('//*[@id="tvpColl"]//*[@class="c-item-exact"]//*[@class="thumb_bf"]/img')
                if poster_elements:
                    entity.image_url = cls.process_image_url(poster_elements[0])
            except:
                logger.error(traceback.format_exc())
                entity.image_url = None

            # 스튜디오
            studio_elements = root.xpath('//div[@id="tvpColl"]//dd[@class="program"]//span[@class="inner"]')
            if studio_elements:
                studio_element_a = studio_elements[0].xpath('a')
                if studio_element_a:
                    entity.studio = studio_element_a[0].text.strip()

            # 설명
            desc_elements = root.xpath('//div[@id="tvpColl"]//*[contains(@class, "desc_story")]')
            if desc_elements:
                entity.desc = desc_elements[0].text.strip()

            # 시리즈
            entity.series = []
            '''
            entity.series.append({
                'title': entity.title,
                'code': entity.code,
                'year': entity.year,
                'status': entity.status,
                'date': premired.strftime('%Y-%m-%d') if premired else entity.year
            })
            '''
            series_root = cls.get_info_tab('시리즈', root)
            if series_root is not None:
                series_elements = series_root.xpath('//div[@id="tvpColl"]//strong[contains(text(), "시리즈")]/following-sibling::div/ul/li')
                #compact_title_show = cls.parse_compact_title(entity.title)
                for series_element in series_elements:
                    series = {}
                    series_info_element = series_element.xpath('div/div[2]')[0]
                    a_element = series_info_element.xpath('div[1]//a')[0]
                    series['title'] = a_element.text.strip()
                    """
                    compact_title_series = cls.parse_compact_title(series['title'])
                    if compact_title_show not in compact_title_series:
                        '''
                        미스트롯
                        미스터트롯

                        KBS 드라마 스페셜 2024
                        KBS 드라마 스페셜 2023
                        KBS 드라마 스페셜 2018
                        2017 KBS 드라마 스페셜
                        2016 KBS 드라마 스페셜
                        KBS 드라마 스페셜 단막 2015
                        KBS 드라마 스페셜 시즌5
                        KBS 드라마 스페셜 시즌1

                        골든일레븐: 라리가 원정대
                        골든일레븐: 언리미티드
                        골든일레븐3
                        골든일레븐2
                        골든일레븐

                        로드 투 킹덤 : ACE OF ACE
                        퀸덤 퍼즐

                        텐트 밖은 유럽 남프랑스 편
                        텐트 밖은 유럽 스페인 편
                        텐트 밖은 유럽 - 로맨틱 이탈리아

                        좀비버스: 뉴 블러드
                        좀비버스

                        title로 구분 시도 하려 했으나 변칙이 많음
                        '''
                        logger.debug(f'"{entity.title}" does not seem to match "{series["title"]}"')
                        continue
                    """
                    query = dict(urllib.parse.parse_qsl(a_element.attrib['href']))
                    series['code'] = f'{cls.module_char}{cls.site_char}{query.get("spId", "").strip()}'
                    series['year'] = 1900
                    date_element = series_info_element.xpath('div[2]/span')[0]
                    if date_element.text:
                        date: datetime = cls.parse_date_text(date_element.text.strip())
                        series['year'] = date.year if date else 1900
                        series['date'] = date.strftime('%Y-%m-%d') if date else date_element.text.strip()
                    entity.series.append(series)
                entity.series = sorted(entity.series, key=lambda k: (int(k['year']), int(k['code'][2:])))

            # 동명프로그램
            entity.equal_name = []
            similar_elements = root.xpath('//strong[@class="screen_out" and contains(text(), "동명프로그램")]/following-sibling::div')
            if similar_elements:
                # 한 개 이상일 경우는?
                equal_program = {}
                e_div = similar_elements[0]
                e_a = e_div.xpath('.//div[@class="item-title"]//a')
                query = dict(urllib.parse.parse_qsl(e_a[0].attrib['href']))
                if e_a:
                    equal_program['title'] = e_a[0].text.strip()
                    equal_program['code'] = f'{cls.module_char}{cls.site_char}{query.get("spId", "").strip()}'
                e_dd = e_div.xpath('.//dd[@class="program"]')
                if e_dd:
                    studio_and_year = e_dd[0].xpath('string()')
                    sy = [t.strip() for t in studio_and_year.split(',')]
                    equal_program['studio'] = sy[0]
                    if len(sy) > 1:
                        year = sy[1][:4]
                        equal_program['year'] = int(year) if year.isdigit() else 1900
                entity.equal_name.append(equal_program)

            #logger.debug(entity)

            '''
            https://github.com/soju6jan/SjvaAgent.bundle/blob/55eeacd759a14d8651a41b5e8cdabc5dd1cd3219/Contents/Code/module_ktv.py#L137
            tmp = data['extra_info'] + ' '
            if data['status'] == 0:
                tmp = tmp + u'방송예정'
            elif data['status'] == 1:
                tmp = tmp + u'방송중'
            elif data['status'] == 2:
                tmp = tmp + u'방송종료'
            tmp = tmp + self.search_result_line() + data['desc']
            '''
            entity.extra_info = f'Daum {entity.studio}'
            # broadcast_info?
            entity.broadcast_info = ''

            return entity.as_dict()
        except Exception:
            logger.error(traceback.format_exc())

    # 2024.06.05 둘중 하나로..
    @classmethod
    def process_image_url(cls, img_tag):
        url = img_tag.attrib.get('data-original-src') or img_tag.attrib.get('src')
        tmps = url.split('fname=')
        if len(tmps) == 2:
            return urllib.parse.unquote(tmps[1])
        else:
            return 'https' + url

    @classmethod
    def get_kakao_play_url(cls, url):
        try:
            content_id = url.split('/')[-1]
            url = 'https://tv.kakao.com/katz/v2/ft/cliplink/{}/readyNplay?player=monet_html5&profile=HIGH&service=kakao_tv&section=channel&fields=seekUrl,abrVideoLocationList&startPosition=0&tid=&dteType=PC&continuousPlay=false&contentType=&{}'.format(content_id, int(time.time()))
            data = requests.get(url).json()
            return data['videoLocation']['url']
        except Exception as exception:
            logger.debug('Exception : %s', exception)
            logger.debug(traceback.format_exc())

    @classmethod
    def get_kakao_play_url2(cls, data_id: str) -> str | None:
        url = f'https://kakaotv.daum.net/katz/v3/ft/cliplink/{data_id}/videoLocation?service=daum_searchview&section=TVP&player=monet_html5&profile=HIGH4&dteType=PC&contentType=MP4'
        try:
            json_ = SiteUtil.get_response(url, proxy_url=cls._proxy_url, headers=cls.default_headers, cookies=cls._daum_cookie).json()
            return json_['videoLocation']['url']
        except Exception as e:
            logger.warning(repr(e))
            logger.warning(f'{url=}')

    @classmethod
    def change_date(cls, text):
        try:
            match = re.compile(r'(?P<year>\d{4})\.(?P<month>\d{1,2})\.(?P<day>\d{1,2})').search(text)
            if match:
                return match.group('year') + '-' + match.group('month').zfill(2) + '-'+ match.group('day').zfill(2)
        except Exception as exception:
            logger.debug('Exception : %s', exception)
            logger.debug(traceback.format_exc())
        #return text
        return datetime.now().strftime('%Y-%m-%d')

    @classmethod
    def get_kakao_video(cls, kakao_id, sort='CreateTime', size=20):
        #sort : CreateTime PlayCount
        ret = []
        try:
            url = 'https://tv.kakao.com/api/v1/ft/channels/{kakao_id}/videolinks?sort={sort}&fulllevels=clipLinkList%2CliveLinkList&fields=ccuCount%2CisShowCcuCount%2CthumbnailUrl%2C-user%2C-clipChapterThumbnailList%2C-tagList&size=20&page=1&_={timestamp}'.format(kakao_id=kakao_id, sort=sort, timestamp=int(time.time()))
            data = requests.get(url).json()

            for item in data['clipLinkList']:
                ret.append(EntityExtra('Featurette', item['clip']['title'], 'kakao', item['id'], premiered=item['createTime'].split(' ')[0], thumb=item['clip']['thumbnailUrl']).as_dict())
            return ret
        except Exception as exception:
            logger.debug('Exception : %s', exception)
            logger.debug(traceback.format_exc())
        return ret

    @classmethod
    def parse_date_text(cls, date_text: str) -> datetime | None:
        '''
        98. 1. 31.
        2015. 12. 2.
        25. 9.
        '''
        if '-' in date_text:
            delimiter = '-'
        else:
            delimiter = '.'
        date_numbers: list[str] = [d.strip() for d in date_text.split(delimiter) if d.isdigit()]
        date_formats = [
            '%y-%m-%d',
            '%Y-%m-%d',
            '%y-%m',
            '%Y-%m',
        ]
        test_str = '-'.join(date_numbers)
        for f in date_formats:
            try:
                return datetime.strptime(test_str, f)
            except:
                pass

    @classmethod
    def parse_compact_title(cls, title: str) -> str:
        compact = title.replace('시즌', '').strip()
        for d in ['-', ':']:
            compact = compact.split(d)[0]
        compact = ''.join([t for t in compact if not t.isdigit()])
        # remove trailing season number
        #match = re.compile('^(.+\D)\d$').search(compact)
        #if match:
        #    compact = match.group(1).strip()
        return compact.strip()

    @classmethod
    def get_request_url(cls, scheme: str = 'https', netloc: str = 'search.daum.net', path: str = 'search', params: dict = None, query: dict = None, fragment: str = None) -> str:
        return urllib.parse.urlunparse([scheme, netloc, path, urllib.parse.urlencode(params) if params else None, urllib.parse.urlencode(query) if query else None, fragment])

    @classmethod
    def get_info_tab(cls, tab_name: str, document: html.HtmlElement) -> html.HtmlElement | None:
        tab_elements: list = document.xpath('//ul[@class="grid_xscroll"]/li/a')
        target = None
        for e in tab_elements:
            if e.text and e.text.strip() == tab_name:
                target = e
                break
        if target is not None:
            tab_url = urllib.parse.urljoin(cls.get_request_url(), target.attrib['href'])
            return SiteDaum.get_tree(tab_url)
