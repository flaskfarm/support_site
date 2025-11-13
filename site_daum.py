import re
import urllib.parse
from datetime import datetime
from http.cookies import SimpleCookie
from typing import Sequence

import requests
from lxml.html import HtmlElement

from support.base.string import SupportString

from .entity_base import EntityExtra
from .setup import *
from .site_util import SiteUtil, get_default_headers


class SiteDaum(object):
    _daum_cookie = None
    _use_proxy = None
    _proxy_url = None

    site_name = 'daum'
    default_headers = {}
    default_timeout = 5

    site_base_url = 'https://search.daum.net'
    site_char = 'D'
    module_char = '_'

    cache_enable = False
    cache_expiry = 60

    @classmethod
    def initialize(cls, daum_cookie: str, use_proxy: bool = False, proxy_url: str = None, cache_enable: bool = False, cache_expiry: int = 60, headers: str = None, common_headers: str = None) -> None:
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
        cls.cache_enable = cache_enable
        cls.cache_expiry = cache_expiry
        cls.default_headers = get_default_headers(headers, common_headers)

    @classmethod
    def get_tree(cls, url: str) -> HtmlElement:
        doc = SiteUtil.get_tree(url, proxy_url=cls._proxy_url, headers=cls.default_headers, cookies=cls._daum_cookie, timeout=cls.default_timeout)
        cls.is_duam_captcha(doc)
        return doc

    redirect_pattern = re.compile(r"location\.(replace|assign|href\s?=).?[\"'](.+?)[\"'].?")

    @classmethod
    def is_duam_captcha(cls, doc: HtmlElement) -> bool:
        script_text = doc.xpath("string(//head//script)")
        match = cls.redirect_pattern.search(script_text)
        if redirect := match.group(2) if match else None:
            logger.warning(f"{redirect=}")
            if 'captcha' in redirect:
                return True
        return False

    # 2024.06.05 둘중 하나로..
    @classmethod
    def process_image_url(cls, img_tag: HtmlElement) -> str:
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
        return urllib.parse.urlunparse((scheme, netloc, path, urllib.parse.urlencode(params) if params else None, urllib.parse.urlencode(query) if query else None, fragment))

    @classmethod
    def get_info_tab(cls, tab_name: str, document: HtmlElement) -> HtmlElement | None:
        tab_elements: list = document.xpath('//ul[@class="grid_xscroll"]/li/a')
        target = None
        for e in tab_elements:
            if e.text and e.text.strip() == tab_name:
                target = e
                break
        if target is not None:
            tab_url = urllib.parse.urljoin(cls.get_request_url(), target.get('href'))
            return SiteDaum.get_tree(tab_url)

    @classmethod
    def iter_text(cls, element: HtmlElement, excludes: Sequence = (",", "|", "/")) -> tuple:
        return tuple(stripped for text in element.itertext() if (stripped := text.strip()) and stripped not in excludes)

    @classmethod
    def parse_thumb_and_bundle(cls, item_thumb: HtmlElement) -> dict:
        data = {}
        for a_tag in item_thumb.xpath(".//a"):
            href = a_tag.get('href') or ""
            url_splits = urllib.parse.urlsplit(href)
            query = dict(urllib.parse.parse_qsl(url_splits.query))
            data['query'] = query or {}
            data['link'] = href if url_splits.netloc else cls.get_request_url(query=query)
            for img_tag in a_tag.xpath(".//img"):
                data['thumb'] = img_tag.get('data-original-src') or img_tag.get('src') or ""
                img_query = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(data['thumb']).query))
                if fname := img_query.get('fname'):
                    data['image'] = fname
                break
            break
        if (bundle_div := item_thumb.getnext()) is not None:
            data['labels'] = cls.iter_text(bundle_div)
            if (desc_list := bundle_div.xpath(".//dl")):
                data['descs'] = cls.parse_description_list(desc_list[0])
            if (bundle_a := bundle_div.xpath(".//div[@class='item-contents']//a")):
                href = bundle_a[0].get('href') or ""
                url_splits = urllib.parse.urlsplit(href)
                query = dict(urllib.parse.parse_qsl(url_splits.query))
                data['query'] = query or {}
                data['link'] = href if url_splits.netloc else cls.get_request_url(query=query)
        return data

    @classmethod
    def parse_card_title(cls, container: HtmlElement) -> dict:
        data = {}
        if (c_tit_exact := container.find(".//div[@class='c-tit-exact']")) is None:
            logger.warning("No c-tit-exact found...")
            return data
        if (a_tag := c_tit_exact.find("./div/div[@class='inner_header']//a")) is not None and a_tag.get('href'):
            query = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(a_tag.get('href')).query))
            if query.get("spId"):
                data['code'] = query.get("spId")
            data['title'] = a_tag.text_content().strip()
            query['q'] = data['title']
            match query.get('DA') or '':
                case 'TVP':
                    query['w'] = 'tv'
                case 'EM1':
                    query['w'] = 'cin'
            data['link'] = cls.get_request_url(query=query)
        if (sub_header := c_tit_exact.find("./div/div[@class='sub_header']")) is not None:
            data['sub_title'] = sub_header.text_content().strip()
        return data

    @classmethod
    def parse_card_tab(cls, container: HtmlElement) -> dict:
        data = {}
        if (c_section_tab := container.find(".//div[@class='c-section-tab']")) is None:
            logger.warning("No c-section-tab found...")
            return data
        for a_tag in c_section_tab.xpath(".//li/a"):
            label = a_tag.text_content().strip()
            try:
                if a_tag.get('href') and label:
                    data[label] = urllib.parse.urljoin(cls.get_request_url(), a_tag.get('href'))
            except Exception:
                logger.exception(f"Failed to parse: text='{label}'")
        return data

    @classmethod
    def parse_card_section_info(cls, container: HtmlElement) -> dict:
        data = {}
        if not (cont_info := container.xpath(".//div[contains(@class, 'cont_info')]")):
            logger.warning("No cont_info found...")
            return data
        if tags := cont_info[0].xpath("*[contains(@class, 'desc_story')]"):
            data['줄거리'] = tags[0].text_content().strip()
        if (c_item_exact := cont_info[0].find("./div[@class='c-item-exact']")) is not None:
            data.update(cls.parse_item_exact(c_item_exact))
        return data

    @classmethod
    def parse_description_list(cls, description_list: HtmlElement) -> dict:
        data = {}
        for dt_tag in description_list.xpath(".//dt"):
            if not (label := dt_tag.text_content().strip()):
                continue
            if (dd_tag := dt_tag.getnext()) is None:
                continue
            texts = cls.iter_text(dd_tag, excludes=(",", "|", "더보기", "(재)"))
            if not texts:
                continue
            try:
                match label:
                    case "줄거리" | "소개":
                        data[label] = texts[1] if texts[0] == "줄거리" else texts[0]
                    # show
                    case "편성":
                        """
                        NHK 월~토
                        니혼TV 일
                        SBS 수, 목
                        Netflix
                        CH W 수 오후 10:00
                        일본 Amazon
                        웹드라마, 2022.
                        """
                        data['studio'] = texts[0]
                        data['편성'] = ''
                        if len(texts) > 1:
                            data['편성'] = texts[1]
                        for pattern in (r'\s(?=[월화수목금토일])', ','):
                            parts = re.split(pattern, texts[0], maxsplit=1)
                            if len(parts) > 1:
                                data['studio'] = parts[0].strip()
                                data['편성'] = parts[1].strip()
                                break
                    # movie
                    case "개봉":
                        release_date = cls.parse_date_text(texts[0])
                        data[label] = release_date.strftime("%Y-%m-%d")
                    case "국가":
                        data[label] = tuple(texts)
                    case "장르":
                        data[label] = tuple(stripped for genre in texts[0].split("/") if (stripped := genre.strip()))
                    case "시간" | "등급":
                        numbers = re.findall(r'\d+', texts[0])
                        if numbers:
                            if label == "시간":
                                data[label] = int(numbers[0])
                            elif label == "등급":
                                data[label] = f"kr/{numbers[0]}"
                    case "평점":
                        ratings = []
                        for idx, item in enumerate(texts):
                            if idx + 1 > len(texts):
                                continue
                            if item not in ("전문가", "네티즌"):
                                continue
                            rating = {
                                "default": True,
                                "image_url": "",
                                "max": 10,
                                "name": "",
                                "value": float(texts[idx + 1]),
                                "votes": 0
                            }
                            if item == "전문가":
                                rating['default'] = True
                                rating['name'] = "cine21-expert"
                            elif item == "네티즌":
                                rating['default'] = False
                                rating['name'] = "cine21-netizen"
                            ratings.append(rating)
                        data[label] = tuple(ratings)
                    case "관객수":
                        numbers = re.sub(r'[^\d]', '', texts[0])
                        if numbers:
                            data[label] = int(numbers[0])
                    case _:
                        data[label] = texts
            except Exception:
                logger.exception(f"Failed to parse '{label}'")
        return data

    @classmethod
    def parse_item_exact(cls, html: HtmlElement) -> dict:
        data = {}
        if (img_tag := html.find("./div[@class='item-thumb']//img")) is not None:
            data['thumb'] = img_tag.get('data-original-src') or img_tag.get('src') or ""
            img_query = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(data['thumb']).query))
            if fname := img_query.get('fname'):
                data['image'] = fname
        if (description_list := html.find("./div[@class='item-content']/dl")) is not None:
            data.update(cls.parse_description_list(description_list))
        return data

    @classmethod
    def parse_people(cls, container: HtmlElement) -> list:
        data = []

        def __get_person_data(thumb: HtmlElement) -> dict:
            person = {}
            thumb_data = cls.parse_thumb_and_bundle(thumb)
            if labels := thumb_data.get('labels'):
                person['name'] = labels[0]
                if len(labels) > 1:
                    person['role'] = re.sub(r'\s역$', '', labels[1])
                person['labels'] = labels
            if thumb_data.get('thumb'):
                person['thumb'] = thumb_data.get('image') or thumb_data.get('thumb')
            if thumb_data.get('link'):
                person['link'] = thumb_data.get('link')
            return person

        # movie
        for section_title in container.xpath(".//div[@slot='panel']/div[@class='c-tit-section']"):
            match section_title.text_content():
                case '제작진':
                    category = 'staff'
                case '감독':
                    category = 'director'
                case '주연' | '출연':
                    category = 'actor'
                case _:
                    continue
            if (panel_content := section_title.getnext()) is None:
                continue
            if panel_content.tag == 'ul':
                for thumb in panel_content.xpath(".//div[@class='item-thumb']"):
                    person = __get_person_data(thumb)
                    person['category'] = category
                    data.append(person)
            elif panel_content.tag == 'div':
                panel_data = cls.parse_item_exact(panel_content)
                for key in panel_data:
                    match key:
                        case '제작':
                            category = 'producer'
                        case '각본':
                            category = 'writer'
                        case _:
                            category = 'staff'
                    for name in panel_data.get(key) or ():
                        person = {
                            'category': category,
                            'name': name,
                            'role': key,
                        }
                        data.append(person)
        # TV
        for data_tab in container.xpath(".//div[@data-tab]"):
            for item_thumb in data_tab.xpath(".//ul/li//div[@class='item-thumb']"):
                person = __get_person_data(item_thumb)
                person['category'] = data_tab.get('data-tab')
                if '관계도' in (person.get('name') or ''):
                    continue
                if len(labels := person.get('labels')) > 2:
                    person['name'] = labels[2]
                    person['role'] = labels[0]
                data.append(person)
        return data

    @classmethod
    def get_request_query(cls, **kwds: dict[str, str]) -> dict:
        query = getattr(cls, 'default_query', {}).copy()
        if kwds:
            query.update(kwds)
        return query

    @classmethod
    def score_search_results(cls, results: list[dict], keyword: str, year: int) -> None:
        for idx, sr in enumerate(results):
            if not SiteUtil.compare(keyword.lower(), sr['title'].lower()):
                sr['score'] = max(80 - idx, 0)
                continue
            if not year or year <= 1900 or not sr.get('year') or sr['year'] <= 1900:
                sr['score'] = max(89 - idx, 0)
                continue
            discrepancy = abs(sr['year'] - year)
            if discrepancy == 0:
                sr['score'] = max(105 - idx, 0)
            elif discrepancy < 2:
                sr['score'] = max(100 - idx, 0)
            else:
                sr['score'] = max(95 - idx, 0)

    @classmethod
    def parse_clips(cls, container: HtmlElement) -> list[EntityExtra]:
        clips = []
        for li_tag in container.xpath(".//ul/li"):
            try:
                item = {}
                if item_thumbs := li_tag.xpath('.//div[contains(@class, "item-thumb")]'):
                    item.update(cls.parse_thumb_and_bundle(item_thumbs[0]))
                if item.get('labels'):
                    item['title'] = SupportString.remove_emoji(item['labels'][0]).strip()
                    try:
                        date = cls.parse_date_text(item['labels'][1])
                        item['premiered'] = date.strftime('%Y-%m-%d') if date else ''
                    except Exception:
                        pass
                    item['content_type'] = 'Trailer' if item['title'].find('예고') > -1 else 'Featurette'
                '''
                metadata 플러그인에서 data_id만 입력받아 video_url을 따로 처리중

                video_url = cls.get_kakao_play_url2(data_id)
                if not video_url:
                    continue

                영화는 data_id 속성이 없고, TV 쇼는 url이 없음
                '''
                if (div_tag := li_tag.find('.//div[@data-id]')) is not None and (data_id := div_tag.get('data-id')):
                    item['data_id'] = data_id
                if item.get('link'):
                    item['data_id'] = item['link'].rsplit('/')[-1]
                if item:
                    clips.append(EntityExtra(
                        item['content_type'] or 'Clip',
                        item['title'] or '',
                        'kakao',
                        item['data_id'] or item['link'] or '',
                        premiered=item['premiered'] or '',
                        thumb=item['image'] or item['thumb'] or ''
                    ))
            except Exception:
                logger.exception(f"Failed to parse a clip...")
        return clips

    @classmethod
    def refine_keyword(cls, keyword: str) -> str:
        for remove in ('일일연속극', '특별기획드라마', ' | 시리즈'):
            keyword = keyword.replace(remove, '').strip()
        for channel in ('채널 A', '채널A'):
            if keyword.startswith(channel):
                keyword = keyword.replace(channel, '').strip()
        for pattern in (r'\[.*?\]', r'^.{2,3}드라마', r'^.{1,3}특집'):
            keyword = re.sub(pattern, '', keyword).strip()
        for remove in ('.',):
            keyword = keyword.replace(remove, ' ').strip()
        # 애플 오리지널 타이틀
        quotes = re.compile(r"'(.+?)'").findall(keyword)
        if quotes:
            keyword = quotes[0]
        return keyword
