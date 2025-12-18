# -*- coding: utf-8 -*-
import re
import os
import time
from threading import Lock
from lxml import html
from urllib.parse import urljoin

from ..entity_av import EntityAVSearch
from ..entity_base import EntityMovie, EntityActor, EntityThumb, EntityExtra, EntityRatings
from ..setup import P, logger
from .site_av_base import SiteAvBase

class SiteFc2com(SiteAvBase):
    site_name = 'fc2com'
    site_char = 'F'
    module_char = 'E'

    CACHE_EXPIRATION_SECONDS = 120

    site_base_url = 'https://adult.contents.fc2.com'
    default_headers = SiteAvBase.base_default_headers.copy()
    default_headers['Referer'] = site_base_url + "/"

    _dynamic_suffix = "?dref=search_id"
    _page_source_cache = {}
    _cache_lock = Lock()


    @classmethod
    def _add_fc2_cookies(cls, driver):
        """FC2 성인 인증 쿠키 추가"""
        try:
            # 쿠키를 설정하려면 먼저 해당 도메인에 접속해야 함 (가벼운 페이지나 404 페이지 활용)
            driver.get(cls.site_base_url + '/404') 
            driver.add_cookie({'name': 'wei6H', 'value': '1', 'domain': '.fc2.com', 'path': '/'})
            # logger.debug(f"[{cls.site_name}] Added adult cookie: wei6H=1")
        except Exception as e:
            logger.warning(f"[{cls.site_name}] Failed to add cookies: {e}")


    @classmethod
    def search(cls, keyword, manual=False):
        # Selenium 필수 체크
        if not cls.config.get('selenium_url'):
            logger.warning(f"[{cls.site_name}] Selenium URL is not configured. FC2 search disabled.")
            return {'ret': 'no_match', 'data': []}

        driver = None
        try:
            from selenium.webdriver.common.by import By
            driver = cls._get_selenium_driver()

            # cls._add_fc2_cookies(driver)

            match = re.search(r'(\d{6,7})', keyword)
            if not match:
                return {'ret': 'success', 'data': []}

            code_part = match.group(1)
            search_url = f'{cls.site_base_url}/article/{code_part}/{cls._dynamic_suffix}'

            detail_page_wait_locator = (By.XPATH, '//div[contains(@class, "items_article_headerInfo")]')
            # 공용 메서드 호출
            tree, page_source_text = cls._get_page_content_selenium(driver, search_url, wait_for_locator=detail_page_wait_locator)

            if page_source_text:
                with cls._cache_lock:
                    cls._page_source_cache[code_part] = (page_source_text, time.time())
                logger.debug(f"[{cls.site_name}] Page source for '{code_part}' cached.")

            if tree is None:
                return {'ret': 'no_match', 'data': []}

            item = EntityAVSearch(cls.site_name)
            item.code = cls.module_char + cls.site_char + code_part

            item.ui_code = cls._parse_ui_code_uncensored(keyword)
            if not item.ui_code or 'FC2' not in item.ui_code.upper():
                item.ui_code = f'FC2-{code_part}'

            if 'fc2' in keyword.lower():
                item.score = 100
            elif manual:
                item.score = 100
            else:
                item.score = 90

            if h3_title := tree.xpath('//div[contains(@class, "items_article_headerInfo")]/h3'):
                item.title = cls._extract_fc2com_title(h3_title[0])
            else:
                item.title = item.ui_code

            if manual:
                item.title_ko = item.title

            if date_text := tree.xpath('//p[contains(text(), "Sale Day")]/text()'):
                if match_year := re.search(r'(\d{4})/\d{2}/\d{2}', date_text[0]):
                    item.year = int(match_year.group(1))

            if img_src := tree.xpath('//div[contains(@class, "items_article_MainitemThumb")]//img/@src | //div[contains(@class, "items_article_MainitemThumb")]//img/@data-src'):
                item.image_url = cls._normalize_url(img_src[0], search_url, upgrade_size=False)

            if manual and item.image_url and cls.config.get('use_proxy'):
                item.image_url = cls.make_image_url(item.image_url)

            title_for_log = (item.title[:77] + '...') if len(item.title) > 80 else item.title
            logger.info(f"FC2.com: 검색 성공: [{item.ui_code}] {title_for_log}")

            return {'ret': 'success', 'data': [item.as_dict()]}
        except Exception as e:
            logger.error(f'[{cls.site_name} Search] Exception: {e}')
            return {'ret': 'exception', 'data': str(e)}
        finally:
            cls._quit_selenium_driver(driver)


    @classmethod
    def info(cls, code, fp_meta_mode=False):
        if not cls.config.get('selenium_url'):
            return {'ret': 'error', 'data': 'Selenium URL is not set.'}

        try:
            entity = cls.__info(code, fp_meta_mode)
            return {'ret': 'success', 'data': entity.as_dict()} if entity else {'ret': 'error'}
        except Exception as e:
            logger.exception(f"[{cls.site_name} info] Unhandled exception in info: {e}")
            return {'ret': 'exception', 'data': str(e)}


    @classmethod
    def __info(cls, code, fp_meta_mode=False):
        code_part = code[len(cls.module_char) + len(cls.site_char):]
        tree = None
        driver = None

        with cls._cache_lock:
            if code_part in cls._page_source_cache:
                cached_source, timestamp = cls._page_source_cache[code_part]
                if (time.time() - timestamp) < cls.CACHE_EXPIRATION_SECONDS:
                    logger.debug(f"[{cls.site_name} Info] Using valid cache for '{code_part}'.")
                    tree = html.fromstring(cached_source)
                    del cls._page_source_cache[code_part]
                else:
                    logger.debug(f"[{cls.site_name} Info] Cache for '{code_part}' has expired.")
                    del cls._page_source_cache[code_part]

        if tree is None:
            try:
                from selenium.webdriver.common.by import By
                driver = cls._get_selenium_driver()

                cls._add_fc2_cookies(driver)

                info_url = f'{cls.site_base_url}/article/{code_part}/{cls._dynamic_suffix}'
                detail_page_wait_locator = (By.XPATH, '//div[contains(@class, "items_article_headerInfo")]')
                tree, _ = cls._get_page_content_selenium(driver, info_url, wait_for_locator=detail_page_wait_locator)
            finally:
                cls._quit_selenium_driver(driver)

        if tree is None: return None

        entity = EntityMovie(cls.site_name, code)
        entity.country = ['일본']; entity.mpaa = '청소년 관람불가'
        entity.thumb = []; entity.fanart = []; entity.extras = []; entity.tag = []; entity.genre = []
        entity.original = {}

        entity.ui_code = cls._parse_ui_code_uncensored(f'fc2-{code_part}')
        entity.title = entity.originaltitle = entity.sorttitle = entity.ui_code.upper()
        entity.label = "FC2"

        if h3_title := tree.xpath('//div[contains(@class, "items_article_headerInfo")]/h3'):
            raw_title = cls._extract_fc2com_title(h3_title[0])
            cleaned_text = cls.A_P(raw_title)
            entity.original['tagline'] = cleaned_text
            entity.original['plot'] = cleaned_text
            text_to_assign = cls.trans(cleaned_text)
            entity.tagline = text_to_assign
            entity.plot = text_to_assign

        if date_text := tree.xpath('//p[contains(text(), "Sale Day")]/text()'):
            if match_date := re.search(r'(\d{4})/(\d{2})/(\d{2})', date_text[0]):
                entity.premiered = f"{match_date.group(1)}-{match_date.group(2)}-{match_date.group(3)}"
                entity.year = int(match_date.group(1))

        if seller := tree.xpath('//a[contains(@href, "/users/")]/text()'):
            studio_director_text = seller[0].strip()
            entity.original['studio'] = studio_director_text
            entity.original['director'] = studio_director_text
            entity.studio = studio_director_text
            entity.director = studio_director_text

        if 'genre' not in entity.original: entity.original['genre'] = []
        for genre_name in tree.xpath('//section[contains(@class, "items_article_TagArea")]//a/text()'):
            genre_strip = genre_name.strip()
            entity.original['genre'].append(genre_strip)
            entity.genre.append(cls.trans(genre_strip))

        entity.tag.append('FC2')
        if entity.studio and entity.studio not in entity.tag:
            entity.tag.append(entity.studio)

        # === 이미지 처리 로직 변경 ===
        raw_image_urls = {'poster': None, 'pl': None, 'arts': []}
        
        # 1. 메인 포스터(썸네일) 추출
        if poster_src := tree.xpath('//div[contains(@class, "items_article_MainitemThumb")]//img/@src | //div[contains(@class, "items_article_MainitemThumb")]//img/@data-src'):
            raw_image_urls['poster'] = cls._normalize_url(poster_src[0], cls.site_base_url, upgrade_size=True)

        # 2. 갤러리 이미지 추출
        gallery_urls = []
        for href in tree.xpath('//a[@data-fancybox="gallery"]/@href'):
            gallery_urls.append(cls._normalize_url(href, cls.site_base_url, upgrade_size=True))

        if not gallery_urls:
            for href in tree.xpath('//section[contains(@class, "items_article_SampleImages")]//a/@href'):
                gallery_urls.append(cls._normalize_url(href, cls.site_base_url, upgrade_size=True))

        # 3. PL 및 Arts 할당 (갤러리 첫번째 = PL, 나머지 = Arts)
        if gallery_urls:
            raw_image_urls['pl'] = gallery_urls[0]
            raw_image_urls['arts'] = gallery_urls[1:]

        # 4. 포스터 Fallback (포스터가 없으면 PL을 포스터로 사용)
        if not raw_image_urls['poster'] and raw_image_urls['pl']:
            raw_image_urls['poster'] = raw_image_urls['pl']
            logger.debug(f"[{cls.site_name}] Poster not found. Using first gallery image (PL) as Poster.")

        image_mode = cls.MetadataSetting.get('jav_censored_image_mode')
        if image_mode == 'image_server':
            try:
                code_match = re.search(r'(\d+)$', entity.ui_code)
                if code_match:
                    num_part = code_match.group(1)
                    padded_num = num_part.zfill(7)
                    sub_folder = padded_num[:3]
                    local_path = cls.MetadataSetting.get('jav_censored_image_server_local_path')
                    server_url = cls.MetadataSetting.get('jav_censored_image_server_url')
                    base_save_format = cls.MetadataSetting.get('jav_uncensored_image_server_save_format')
                    base_path_part = base_save_format.format(label=entity.label) 
                    final_relative_folder_path = os.path.join(base_path_part.strip('/\\'), sub_folder)
                    entity.image_server_target_folder = os.path.join(local_path, final_relative_folder_path)
                    entity.image_server_url_prefix = f"{server_url.rstrip('/')}/{final_relative_folder_path.replace(os.path.sep, '/')}"
            except Exception as e:
                logger.error(f"[{cls.site_name}] Failed to set custom image server path: {e}")

        # Base 클래스의 이미지 처리 로직 위임 (스마트 크롭 등 적용)
        # raw_image_urls['poster']가 가로 이미지(PL)인 경우, use_smart_crop 설정에 따라 자동으로 크롭
        entity = cls.process_image_data(entity, raw_image_urls, ps_url_from_cache=None)

        if cls.config['use_extras']:
            if video_src := tree.xpath('//video[contains(@id, "sample_video")]/@src'):
                trailer_url = cls._normalize_url(video_src[0], cls.site_base_url, upgrade_size=False)
                if url := cls.make_video_url(trailer_url):
                    trailer_title = entity.tagline if (fp_meta_mode or not entity.tagline) else cls.trans(entity.tagline)
                    entity.extras.append(EntityExtra("trailer", trailer_title, "mp4", url))

        return entity


    @staticmethod
    def _extract_fc2com_title(h3_element):
        return ' '.join(h3_element.xpath(".//text()")).strip() if h3_element is not None else ""


    @classmethod
    def _normalize_url(cls, src, base_url, upgrade_size=True):
        if not src: return None
        normalized_src = src
        if upgrade_size:
            if match := re.search(r'/w(\d+)/', src):
                if int(match.group(1)) < 1280:
                    normalized_src = src.replace(f'/w{match.group(1)}/', '/w1280/')
        if normalized_src.startswith('//'): return 'https:' + normalized_src
        if normalized_src.startswith('/'): return urljoin(base_url, src)
        return normalized_src


    @classmethod
    def set_config(cls, db):
        super().set_config(db)
