# -*- coding: utf-8 -*-
import re
import traceback
import time
from urllib.parse import urljoin, urlparse
from threading import Lock
import base64
import zipfile
import socket
from io import BytesIO

try:
    from selenium import webdriver
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.common.exceptions import TimeoutException, WebDriverException, InvalidSessionIdException
    is_selenium_available = True
except ImportError:
    is_selenium_available = False

from lxml import html
from ..entity_av import EntityAVSearch
from ..entity_base import (EntityActor, EntityExtra, EntityMovie, EntityRatings, EntityThumb)
from ..setup import P, logger
from .site_av_base import SiteAvBase

class SiteFc2com(SiteAvBase):
    site_name = 'fc2com'
    site_char = 'F'
    module_char = 'E'

    SELENIUM_TIMEOUT = 5
    CACHE_EXPIRATION_SECONDS = 120

    site_base_url = 'https://adult.contents.fc2.com'
    default_headers = SiteAvBase.base_default_headers.copy()
    default_headers['Referer'] = site_base_url + "/"

    _dynamic_suffix = "?dref=search_id"
    _page_source_cache = {}
    _cache_lock = Lock() # 캐시 딕셔너리 접근을 보호하기 위한 Lock

    @classmethod
    def search(cls, keyword, manual=False):
        if not is_selenium_available:
            logger.warning(f"[{cls.site_name}] Selenium 라이브러리가 설치되지 않아 비활성화되었습니다. (pip install 'selenium<4.10')")
            return {'ret': 'no_match', 'data': []}
        if not cls.config.get('selenium_url'):
            logger.warning(f"[{cls.site_name}] Selenium URL이 설정되지 않아 비활성화되었습니다.")
            return {'ret': 'no_match', 'data': []}

        driver = None
        try:
            driver = cls._get_selenium_driver()

            match = re.search(r'(\d{6,7})', keyword)
            if not match:
                return {'ret': 'success', 'data': []}

            code_part = match.group(1)
            search_url = f'{cls.site_base_url}/article/{code_part}/{cls._dynamic_suffix}'

            detail_page_wait_locator = (By.XPATH, '//div[contains(@class, "items_article_headerInfo")]')
            tree, page_source_text = cls._get_page_content(driver, search_url, wait_for_locator=detail_page_wait_locator)

            if page_source_text:
                with cls._cache_lock:
                    cls._page_source_cache[code_part] = (page_source_text, time.time())
                logger.debug(f"[{cls.site_name}] Page source for '{code_part}' cached.")

            if tree is None:
                return {'ret': 'no_match', 'data': []}

            item = EntityAVSearch(cls.site_name)
            item.code = cls.module_char + cls.site_char + code_part
            item.ui_code = cls._parse_ui_code_uncensored(keyword)
            item.score = 100

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
            logger.error(traceback.format_exc())
            return {'ret': 'exception', 'data': str(e)}
        finally:
            if driver:
                cls._quit_selenium_driver(driver)


    @classmethod
    def info(cls, code, fp_meta_mode=False):
        if not is_selenium_available:
            return {'ret': 'error', 'data': 'Selenium library is not installed.'}
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
                driver = cls._get_selenium_driver()
                info_url = f'{cls.site_base_url}/article/{code_part}/{cls._dynamic_suffix}'
                detail_page_wait_locator = (By.XPATH, '//div[contains(@class, "items_article_headerInfo")]')
                tree, _ = cls._get_page_content(driver, info_url, wait_for_locator=detail_page_wait_locator)
            finally:
                if driver:
                    cls._quit_selenium_driver(driver)

        if tree is None: return None

        entity = EntityMovie(cls.site_name, code)
        entity.country = ['일본']; entity.mpaa = '청소년 관람불가'
        entity.thumb = []; entity.fanart = []; entity.extras = []; entity.tag = []; entity.genre = []
        entity.ui_code = cls._parse_ui_code_uncensored(f'fc2-{code_part}')
        entity.title = entity.originaltitle = entity.sorttitle = entity.ui_code.upper()
        entity.label = "FC2"

        if h3_title := tree.xpath('//div[contains(@class, "items_article_headerInfo")]/h3'):
            raw_title = cls._extract_fc2com_title(h3_title[0])
            entity.tagline = entity.plot = cls.trans(raw_title)

        if date_text := tree.xpath('//p[contains(text(), "Sale Day")]/text()'):
            if match_date := re.search(r'(\d{4})/(\d{2})/(\d{2})', date_text[0]):
                entity.premiered = f"{match_date.group(1)}-{match_date.group(2)}-{match_date.group(3)}"
                entity.year = int(match_date.group(1))

        if seller := tree.xpath('//a[contains(@href, "/users/")]/text()'):
            entity.studio = entity.director = seller[0].strip()

        for genre_name in tree.xpath('//section[contains(@class, "items_article_TagArea")]//a/text()'):
            entity.genre.append(cls.trans(genre_name.strip()))

        entity.tag.append('FC2')
        if entity.studio and entity.studio not in entity.tag:
            entity.tag.append(entity.studio)

        raw_image_urls = {'poster': None, 'arts': []}
        if poster_src := tree.xpath('//div[contains(@class, "items_article_MainitemThumb")]//img/@src | //div[contains(@class, "items_article_MainitemThumb")]//img/@data-src'):
            raw_image_urls['poster'] = cls._normalize_url(poster_src[0], cls.site_base_url, upgrade_size=True)

        for art_src in tree.xpath('//section[contains(@class, "items_article_SampleImages")]//a/@href'):
            raw_image_urls['arts'].append(cls._normalize_url(art_src, cls.site_base_url, upgrade_size=True))

        if not fp_meta_mode:
            entity = cls.process_image_data(entity, raw_image_urls, ps_url_from_cache=None)
        else:
            if raw_image_urls.get('poster'):
                entity.thumb.append(EntityThumb(aspect="poster", value=raw_image_urls['poster']))
            entity.fanart = raw_image_urls.get('arts', [])

        if not fp_meta_mode and cls.config['use_extras']:
            if video_src := tree.xpath('//video[contains(@id, "sample_video")]/@src'):
                trailer_url = cls._normalize_url(video_src[0], cls.site_base_url, upgrade_size=False)
                if url := cls.make_video_url(trailer_url):
                    entity.extras.append(EntityExtra("trailer", entity.tagline, "mp4", url))

        return entity


    @classmethod
    def _get_selenium_driver(cls):
        if not is_selenium_available:
            raise ImportError("Selenium 라이브러리가 설치되어 있지 않습니다. (pip install 'selenium<4.10')")

        selenium_url = cls.config.get('selenium_url')
        if not selenium_url:
            raise Exception("Selenium 서버 URL이 설정되지 않았습니다.")

        options = webdriver.ChromeOptions()
        options.add_argument('--headless=new')
        options.add_argument('--no-sandbox')
        options.add_argument('--disable-dev-shm-usage')
        options.add_argument('--disable-gpu')
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option('useAutomationExtension', False)
        user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
        options.add_argument(f'user-agent={user_agent}')
        options.add_argument("--disable-infobars")
        options.add_argument('--disable-blink-features=AutomationControlled')

        if cls.config.get('use_proxy') and cls.config.get('proxy_url'):
            proxy_url = cls.config["proxy_url"]
            # logger.debug(f"[{cls.site_name}] Selenium using proxy: {proxy_url}")
            if '@' in proxy_url:
                try:
                    parsed_proxy = urlparse(proxy_url)
                    proxy_host, proxy_port = parsed_proxy.hostname, parsed_proxy.port
                    proxy_user, proxy_pass = parsed_proxy.username, parsed_proxy.password
                    proxy_scheme = parsed_proxy.scheme or 'http'

                    manifest_json = """
                    {
                        "version": "1.0.0", "manifest_version": 2, "name": "Chrome Proxy",
                        "permissions": [ "proxy", "tabs", "unlimitedStorage", "storage", "<all_urls>", "webRequest", "webRequestBlocking" ],
                        "background": { "scripts": ["background.js"] }
                    }
                    """
                    background_js = f"""
                    var config = {{
                        mode: "fixed_servers",
                        rules: {{
                            singleProxy: {{
                                scheme: "{proxy_scheme}", host: "{proxy_host}", port: parseInt({proxy_port})
                            }},
                            bypassList: ["localhost", "127.0.0.1", "{urlparse(selenium_url).hostname}"]
                        }}
                    }};
                    chrome.proxy.settings.set({{value: config, scope: "regular"}}, function() {{}});
                    function callbackFn(details) {{
                        return {{ authCredentials: {{ username: "{proxy_user}", password: "{proxy_pass}" }} }};
                    }}
                    chrome.webRequest.onAuthRequired.addListener(callbackFn,{{urls: ["<all_urls>"]}},['blocking']);
                    """

                    zip_buffer = BytesIO()
                    with zipfile.ZipFile(zip_buffer, 'w') as zp:
                        zp.writestr("manifest.json", manifest_json)
                        zp.writestr("background.js", background_js)

                    extension_b64 = base64.b64encode(zip_buffer.getvalue()).decode('utf-8')
                    options.add_encoded_extension(extension_b64)
                except Exception as e:
                    logger.error(f"[{cls.site_name}] Failed to create proxy auth extension, falling back: {e}")
                    options.add_argument(f'--proxy-server={proxy_url}')
            else:
                options.add_argument(f'--proxy-server={proxy_url}')

        original_timeout = socket.getdefaulttimeout()
        try:
            socket.setdefaulttimeout(10)
            logger.debug(f"[{cls.site_name}] Connecting to Selenium at: {selenium_url} (10s timeout)")
            driver = webdriver.Remote(command_executor=selenium_url, options=options)
            driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
            return driver
        except (socket.timeout, TimeoutError) as e:
            logger.error(f"[{cls.site_name}] Selenium 드라이버 생성 시간이 10초를 초과했습니다: {e}")
            raise WebDriverException("Selenium 서버 연결 시간 초과") from e
        except WebDriverException as e:
            logger.error(f"[{cls.site_name}] Selenium 드라이버 생성 실패: {e}")
            raise
        finally:
            socket.setdefaulttimeout(original_timeout)


    @classmethod
    def _quit_selenium_driver(cls, driver):
        if driver:
            try:
                driver.quit()
            except Exception as e:
                logger.warning(f"[{cls.site_name}] Exception during driver.quit(): {e}")


    @classmethod
    def _get_page_content(cls, driver, url, wait_for_locator):
        driver.get(url)
        WebDriverWait(driver, cls.SELENIUM_TIMEOUT).until(EC.presence_of_element_located(wait_for_locator))
        page_source = driver.page_source
        if "お探しのページは見つかりませんでした。" in page_source:
            return None, page_source
        return html.fromstring(page_source), page_source


    @staticmethod
    def _extract_fc2com_title(h3_element):
        return ' '.join(h3_element.xpath(".//text()")).strip() if h3_element is not None else ""


    @classmethod
    def _normalize_url(cls, src, base_url, upgrade_size=True):
        if not src: return None
        normalized_src = src

        if upgrade_size:
            if match := re.search(r'/w(\d+)/', src):
                if int(match.group(1)) < 600:
                    normalized_src = src.replace(f'/w{match.group(1)}/', '/w600/')

        if normalized_src.startswith('//'): return 'https:' + normalized_src
        if normalized_src.startswith('/'): return urljoin(base_url, src)
        return normalized_src


    @classmethod
    def set_config(cls, db):
        super().set_config(db)
