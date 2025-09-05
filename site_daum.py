import re
import urllib.parse
from datetime import datetime
from http.cookies import SimpleCookie

import requests
import lxml.etree
import lxml.html

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
    def initialize(cls, daum_cookie: str, use_proxy: bool = False, proxy_url: str = None) -> None:
        cookies = SimpleCookie()
        try:
            cookies.load(daum_cookie)
        except Exception:
            logger.exception('입력한 쿠키 값을 확인해 주세요.')
        cls._daum_cookie = {key:morsel.value for key, morsel in cookies.items()}
        cls._use_proxy = use_proxy
        if cls._use_proxy:
            cls._proxy_url = proxy_url
        else:
            cls._proxy_url = None

    @classmethod
    def get_tree(cls, url: str) -> lxml.html.HtmlElement:
        doc = SiteUtil.get_tree(url, proxy_url=cls._proxy_url, headers=cls.default_headers, cookies=cls._daum_cookie)
        cls.is_duam_captcha(doc)
        return doc

    redirect_pattern = re.compile(r"location\.(replace|assign|href\s?=).?[\"'](.+?)[\"'].?")

    @classmethod
    def is_duam_captcha(cls, doc: lxml.html.HtmlElement) -> bool:
        script_text = doc.xpath("string(//head//script)")
        match = cls.redirect_pattern.search(script_text)
        if redirect := match.group(2) if match else None:
            logger.warning(f"{redirect=}")
            if 'captcha' in redirect:
                return True
        return False

    @classmethod
    def get_show_info_on_home(cls, root: lxml.html.HtmlElement) -> dict | None:
        entity = EntitySearchItemTvDaum(cls.site_name)
        try:
            # 제목 및 코드
            title = code = None
            strong_tags = root.xpath("//div[@id='tvpColl']//div[@class='inner_header']/strong")
            if strong_tags:
                title = strong_tags[0].xpath("normalize-space(string(.))")
                last_a_tag_href = strong_tags[0].xpath("./a[last()]/@href")
                if last_a_tag_href:
                    query = dict(urllib.parse.parse_qsl(last_a_tag_href[0]))
                    code = query.get("spId")
            if not (code and title):
                title_text = root.xpath("normalize-space(//title)")
                logger.warning(f"검색 실패: {title_text if title_text else lxml.etree.tostring(root, encoding=str)}")
                return
            entity.title = title
            entity.code = cls.module_char + cls.site_char + code

            # 에피소드 번호 초기화
            entity.episode = -1

            """
            중국드라마 | 50부작 | 10.06.24. ~ 10. | 완결
            예능 | 10.07.11. ~
            영국드라마 | 10부작 | 24.11.15. ~
            뉴스 | 70.10.05. ~
            12부작 | 25.01.06. ~ 02.11. | 완결
            18.11.24. ~
            드라마 | 1부작 | 21.07.23. | 완결
            """
            entity.status = 1
            entity.year = 0
            for header in root.xpath("//div[@id='tvpColl']//div[@class='sub_header']/span/span"):
                text = header.xpath("normalize-space(string(.))")
                if not text:
                    continue
                # 0: 방송예정, 1: 방송중, 2: 방송종료
                if any(word in text for word in ("종료", "완결")):
                    entity.status = 2
                    continue
                elif any(word in text for word in ("예정",)):
                    entity.status = 0
                    continue
                # 부작
                elif re.fullmatch(r"\d+\s*부작", text):
                    # broadcast_info?
                    entity.broadcast_info = text
                    continue
                else:
                    parts = tuple(part.strip() for part in text.rsplit("~", 1) if part)
                    # 방영일
                    premired: datetime | None = cls.parse_date_text(parts[0])
                    if premired:
                        entity.broadcast_term = "~".join(parts)
                        entity.year = premired.year
                        entity.premiered = premired.strftime("%Y-%m-%d")
                    else:
                        # 나머지 장르 취급
                        entity.genre = text

            # 포스터
            try:
                poster_elements = root.xpath('//*[@id="tvpColl"]//*[@class="c-item-exact"]//*[@class="thumb_bf"]/img')
                if poster_elements:
                    entity.image_url = cls.process_image_url(poster_elements[0])
            except Exception:
                logger.exception(f"{entity.title}")
                entity.image_url = None

            # 스튜디오
            schedule_elements = root.xpath("//div[@id='tvpColl']//div[@class='item-content']//dt[normalize-space(.)='편성']/following-sibling::dd[1]//span")
            if schedule_elements:
                span_tag = schedule_elements[0]
                a_tags = span_tag.xpath("a")
                if a_tags:
                    entity.studio = a_tags[0].xpath("normalize-space(.)")
                else:
                    schedule_text = span_tag.xpath("normalize-space(.)")
                    parts = re.split(r'(?=\s?[월화수목금토일])', schedule_text, maxsplit=1)
                    if len(parts) > 1:
                        entity.studio = parts[0].strip()
                        schedule = parts[1].strip()
                        entity.broadcast_info = entity.broadcast_info + ', ' + schedule if entity.broadcast_info else schedule
                    else:
                        entity.studio = schedule_text

            # 설명
            desc_elements = root.xpath('//div[@id="tvpColl"]//*[contains(@class, "desc_story")]')
            if desc_elements:
                entity.desc = desc_elements[0].text.strip()

            # 시리즈
            entity.series = []
            series_root = cls.get_info_tab('시리즈', root)
            if series_root is not None:
                li_elements = series_root.xpath("//div[@id='tvpColl']//strong[contains(text(), '시리즈')]/following-sibling::div/ul/li")
                for li_tag in li_elements:
                    a_tags = li_tag.xpath("./div/div[2]/div[1]//a")
                    span_tags = li_tag.xpath("./div/div[2]/div[2]/span")
                    if not a_tags or not span_tags:
                        continue
                    a_tag, span_tag = a_tags[0], span_tags[0]
                    series_code = series_title = series_year = series_date = series_status = None
                    try:
                        if href := a_tag.get("href"):
                            query = dict(urllib.parse.parse_qsl(href))
                            series_code = query.get("spId")
                            if search_query := query.get("q"):
                                series_title = urllib.parse.unquote(search_query)
                            elif a_tag.text:
                                series_title = a_tag.text.strip()
                        if not (series_code and series_title):
                            continue
                    except Exception:
                        logger.exception(f"{entity.title}")
                        continue
                    try:
                        if span_tag.text:
                            raw_date_text = span_tag.text.strip()
                            date = cls.parse_date_text(raw_date_text)
                            if date:
                                series_year = date.year
                                series_date = date.strftime("%Y-%m-%d")
                            else:
                                series_date = raw_date_text
                    except Exception:
                        logger.exception(f"{entity.title}")
                    entity.series.append(
                        {
                            "code": cls.module_char + cls.site_char + series_code,
                            "title": series_title,
                            "year": series_year or 1900,
                            "date": series_date or "1900-01-01",
                            "status": series_status or -1
                        }
                    )
                if entity.series:
                    try:
                        entity.series = sorted(entity.series, key=lambda k: (int(k['year']), int(k['code'][2:])))
                    except Exception:
                        logger.exception(f"{entity.title}")

            # 동명프로그램
            entity.equal_name = []
            equal_xpaths = (
                # 기본
                "//strong[@class='screen_out' and contains(text(), '동명프로그램')]/following-sibling::div",
                # 트리거
                "//div[contains(@class, 'c-header') and .//*[contains(text(), '동명프로그램')]]/following-sibling::div[contains(@class, 'bundle_basic')]",
            )
            for equal_xpath in equal_xpaths:
                if not (elements := root.xpath(equal_xpath)):
                    continue
                a_tags = elements[0].xpath(".//div[@class='item-thumb']//a")
                dd_tags = elements[0].xpath(".//dd[@class='program']")
                if len(a_tags) != len(dd_tags):
                    continue
                for a_tag, dd_tag in zip(a_tags, dd_tags):
                    equal_code = equal_title = equal_thumb = equal_year = equal_studio = None
                    img_tags = a_tag.xpath(".//img")
                    try:
                        if href := a_tag.get("href"):
                            query = dict(urllib.parse.parse_qsl(href))
                            equal_code = query.get("spId")
                            if search_query := query.get("q"):
                                equal_title = urllib.parse.unquote(search_query)
                        if not equal_title and img_tags and (alt_title := img_tags[0].get("alt")):
                            equal_title = alt_title
                        if not (equal_code and equal_title):
                            continue
                    except Exception:
                        logger.exception(f"{entity.title}")
                        continue
                    try:
                        if img_tags:
                            equal_thumb = cls.process_image_url(img_tags[0])
                        combined_text = dd_tag.xpath("string()")
                        if "," in combined_text:
                            studio_year = tuple(t.strip() for t in combined_text.rsplit(",", 1))
                            year_text = re.sub("\D", "", studio_year[1])
                            if year_text:
                                equal_year = int(year_text)
                                equal_studio = studio_year[0]
                            else:
                                equal_studio = combined_text.strip()
                    except Exception:
                        logger.exception(f"{entity.title}")
                    entity.equal_name.append(
                        {
                            "code": cls.module_char + cls.site_char + equal_code,
                            "title": equal_title,
                            "year": equal_year or 1900,
                            "studio": equal_studio or "",
                            "thumb": equal_thumb or "",
                        }
                    )
                if entity.equal_name:
                    break
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
            return entity.as_dict()
        except Exception:
            logger.exception(f"{entity.title=} {entity.code=}")

    # 2024.06.05 둘중 하나로..
    @classmethod
    def process_image_url(cls, img_tag: lxml.html.HtmlElement) -> str:
        url = img_tag.attrib.get('data-original-src') or img_tag.attrib.get('src')
        tmps = url.split('fname=')
        if len(tmps) == 2:
            return urllib.parse.unquote(tmps[1])
        else:
            return 'https' + url

    @classmethod
    def get_kakao_play_url(cls, url: str) -> str | None:
        try:
            content_id = url.split('/')[-1]
            url = 'https://tv.kakao.com/katz/v2/ft/cliplink/{}/readyNplay?player=monet_html5&profile=HIGH&service=kakao_tv&section=channel&fields=seekUrl,abrVideoLocationList&startPosition=0&tid=&dteType=PC&continuousPlay=false&contentType=&{}'.format(content_id, int(time.time()))
            data = requests.get(url).json()
            return data['videoLocation']['url']
        except Exception:
            logger.exception(f"{url=}")

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
    def change_date(cls, text: str) -> str:
        try:
            match = re.compile(r'(?P<year>\d{4})\.(?P<month>\d{1,2})\.(?P<day>\d{1,2})').search(text)
            if match:
                return match.group('year') + '-' + match.group('month').zfill(2) + '-'+ match.group('day').zfill(2)
        except Exception:
            logger.exception(f"{text=}")
        #return text
        return datetime.now().strftime('%Y-%m-%d')

    @classmethod
    def get_kakao_video(cls, kakao_id: str, sort: str ='CreateTime', size: int = 20) -> list[dict]:
        #sort : CreateTime PlayCount
        ret = []
        try:
            url = 'https://tv.kakao.com/api/v1/ft/channels/{kakao_id}/videolinks?sort={sort}&fulllevels=clipLinkList%2CliveLinkList&fields=ccuCount%2CisShowCcuCount%2CthumbnailUrl%2C-user%2C-clipChapterThumbnailList%2C-tagList&size=20&page=1&_={timestamp}'.format(kakao_id=kakao_id, sort=sort, timestamp=int(time.time()))
            data = requests.get(url).json()

            for item in data['clipLinkList']:
                ret.append(EntityExtra('Featurette', item['clip']['title'], 'kakao', item['id'], premiered=item['createTime'].split(' ')[0], thumb=item['clip']['thumbnailUrl']).as_dict())
            return ret
        except Exception:
            logger.exception(f"{kakao_id=}")
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
        date_numbers = tuple(d.strip() for d in date_text.split(delimiter) if d.isdigit())
        date_formats = (
            '%y-%m-%d',
            '%Y-%m-%d',
            '%y-%m',
            '%Y-%m',
            '%y',
            '%Y',
        )
        test_str = '-'.join(date_numbers)
        for format in date_formats:
            try:
                return datetime.strptime(test_str, format)
            except Exception:
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
    def get_info_tab(cls, tab_name: str, document: lxml.html.HtmlElement) -> lxml.html.HtmlElement | None:
        tab_elements: list = document.xpath('//ul[@class="grid_xscroll"]/li/a')
        target = None
        for e in tab_elements:
            if e.text and e.text.strip() == tab_name:
                target = e
                break
        if target is not None:
            tab_url = urllib.parse.urljoin(cls.get_request_url(), target.get('href'))
            return SiteDaum.get_tree(tab_url)
