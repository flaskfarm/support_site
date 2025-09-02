# -*- coding: utf-8 -*-
import re
import traceback
from urllib.parse import urljoin, urlparse

# 병렬 처리를 위한 threading 라이브러리 임포트
from threading import get_ident, Lock

# Selenium 라이브러리가 있을 경우에만 관련 기능을 활성화
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

    SELENIUM_TIMEOUT = 30
    site_base_url = 'https://adult.contents.fc2.com'
    default_headers = SiteAvBase.base_default_headers.copy()
    default_headers['Referer'] = site_base_url + "/"

    # 스레드별 드라이버와 접미사를 관리하기 위한 딕셔너리 및 Lock
    _drivers = {}
    _dynamic_suffixes = {}
    _lock = Lock()

    @classmethod
    def search(cls, keyword, manual=False):
        if not is_selenium_available:
            logger.warning(f"[{cls.site_name}] Selenium 라이브러리가 설치되지 않아 비활성화되었습니다. (pip install 'selenium<4.10')")
            return {'ret': 'no_match', 'data': []}
        if not cls.config.get('selenium_url'):
            logger.warning(f"[{cls.site_name}] Selenium URL이 설정되지 않아 비활성화되었습니다.")
            return {'ret': 'no_match', 'data': []}

        thread_id = get_ident() # 현재 스레드의 고유 ID 획득
        driver = None
        try:
            driver = cls._get_selenium_driver(thread_id)
            dynamic_suffix = cls._ensure_dynamic_suffix(driver)

            match = re.search(r'(\d{6,7})', keyword)
            if not match:
                return {'ret': 'success', 'data': []}

            code_part = match.group(1)
            search_url = f'{cls.site_base_url}/article/{code_part}/{dynamic_suffix}'

            detail_page_wait_locator = (By.XPATH, '//div[contains(@class, "items_article_headerInfo")]')
            tree, _ = cls._get_page_content(driver, search_url, wait_for_locator=detail_page_wait_locator)

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
                item.title_ko = "(UI 테스트에서는 번역을 제공하지 않습니다) " + item.title

            if date_text := tree.xpath('//p[contains(text(), "Sale Day")]/text()'):
                if match_year := re.search(r'(\d{4})/\d{2}/\d{2}', date_text[0]):
                    item.year = int(match_year.group(1))

            if img_src := tree.xpath('//div[contains(@class, "items_article_MainitemThumb")]//img/@src | //div[contains(@class, "items_article_MainitemThumb")]//img/@data-src'):
                item.image_url = cls._normalize_url(img_src[0], search_url, upgrade_size=False)

            if manual and item.image_url and cls.config.get('use_proxy'):
                item.image_url = cls.make_image_url(item.image_url)

            title_for_log = (item.title[:57] + '...') if len(item.title) > 60 else item.title
            logger.info(f"FC2.com: 검색 성공: [FC2-{item.ui_code}] {title_for_log}")

            return {'ret': 'success', 'data': [item.as_dict()]}

        except Exception as e:
            logger.error(f'[{cls.site_name} Search] Exception: {e}')
            logger.error(traceback.format_exc())
            return {'ret': 'exception', 'data': str(e)}
        finally:
            cls._quit_selenium_driver(thread_id)

    @classmethod
    def info(cls, code, fp_meta_mode=False):
        if not is_selenium_available:
            return {'ret': 'error', 'data': 'Selenium library is not installed.'}
        if not cls.config.get('selenium_url'):
            return {'ret': 'error', 'data': 'Selenium URL is not set.'}

        thread_id = get_ident()
        try:
            driver = cls._get_selenium_driver(thread_id)
            entity = cls.__info(driver, code, fp_meta_mode)
            return {'ret': 'success', 'data': entity.as_dict()} if entity else {'ret': 'error'}
        except Exception as e:
            logger.exception(f"[{cls.site_name} info] error: {e}")
            return {'ret': 'exception', 'data': str(e)}
        finally:
            cls._quit_selenium_driver(thread_id)

    @classmethod
    def __info(cls, driver, code, fp_meta_mode=False):
        dynamic_suffix = cls._ensure_dynamic_suffix(driver)
        code_part = code[len(cls.module_char) + len(cls.site_char):]
        info_url = f'{cls.site_base_url}/article/{code_part}/{dynamic_suffix}'

        detail_page_wait_locator = (By.XPATH, '//div[contains(@class, "items_article_headerInfo")]')
        tree, _ = cls._get_page_content(driver, info_url, wait_for_locator=detail_page_wait_locator)

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
            raw_image_urls['poster'] = cls._normalize_url(poster_src[0], info_url, upgrade_size=True)

        for art_src in tree.xpath('//section[contains(@class, "items_article_SampleImages")]//a/@href'):
            raw_image_urls['arts'].append(cls._normalize_url(art_src, info_url, upgrade_size=True))

        if not fp_meta_mode:
            entity = cls.process_image_data(entity, raw_image_urls, ps_url_from_cache=None)
        else:
            if raw_image_urls.get('poster'):
                entity.thumb.append(EntityThumb(aspect="poster", value=raw_image_urls['poster']))
            entity.fanart = raw_image_urls.get('arts', [])

        if not fp_meta_mode and cls.config['use_extras']:
            if video_src := tree.xpath('//video[contains(@id, "sample_video")]/@src'):
                trailer_url = cls._normalize_url(video_src[0], info_url, upgrade_size=False)
                if url := cls.make_video_url(trailer_url):
                    entity.extras.append(EntityExtra("trailer", entity.tagline, "mp4", url))

        return entity


    #
    # --- Selenium 및 헬퍼 메서드 ---
    #
    @classmethod
    def _get_selenium_driver(cls, thread_id):
        with cls._lock:
            if thread_id in cls._drivers:
                return cls._drivers[thread_id]

        if not is_selenium_available:
            raise Exception("Selenium 라이브러리가 설치되어 있지 않습니다.")
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
            logger.debug(f"[{cls.site_name}] Selenium using proxy: {proxy_url}")
            if '@' in proxy_url:
                try:
                    import base64, zipfile
                    from io import BytesIO
                    parsed_proxy = urlparse(proxy_url)
                    proxy_host = parsed_proxy.hostname
                    proxy_port = parsed_proxy.port
                    proxy_user = parsed_proxy.username
                    proxy_pass = parsed_proxy.password
                    proxy_scheme = parsed_proxy.scheme if parsed_proxy.scheme else 'http'

                    manifest_json = """
                    {
                        "version": "1.0.0",
                        "manifest_version": 2,
                        "name": "Chrome Proxy",
                        "permissions": [
                            "proxy",
                            "tabs",
                            "unlimitedStorage",
                            "storage",
                            "<all_urls>",
                            "webRequest",
                            "webRequestBlocking"
                        ],
                        "background": {
                            "scripts": ["background.js"]
                        }
                    }
                    """
                    background_js = f"""
                    var config = {{
                        mode: "fixed_servers",
                        rules: {{
                            singleProxy: {{
                                scheme: "{proxy_scheme}",
                                host: "{proxy_host}",
                                port: parseInt({proxy_port})
                            }},
                            bypassList: ["localhost", "127.0.0.1", "{selenium_url.split(':')[1].strip('//')}"]
                        }}
                    }};
                    chrome.proxy.settings.set({{value: config, scope: "regular"}}, function() {{}});
                    function callbackFn(details) {{
                        return {{
                            authCredentials: {{
                                username: "{proxy_user}",
                                password: "{proxy_pass}"
                            }}
                        }};
                    }}
                    chrome.webRequest.onAuthRequired.addListener(
                        callbackFn,
                        {{urls: ["<all_urls>"]}},
                        ['blocking']
                    );
                    """

                    zip_buffer = BytesIO()
                    with zipfile.ZipFile(zip_buffer, 'w') as zp:
                        zp.writestr("manifest.json", manifest_json)
                        zp.writestr("background.js", background_js)

                    extension_b64 = base64.b64encode(zip_buffer.getvalue()).decode('utf-8')
                    options.add_encoded_extension(extension_b64)
                    logger.debug(f"[{cls.site_name}] Proxy authentication extension created and added.")

                except Exception as e:
                    logger.error(f"[{cls.site_name}] Failed to create proxy auth extension, falling back: {e}")
                    options.add_argument(f'--proxy-server={proxy_url}')
            else:
                options.add_argument(f'--proxy-server={proxy_url}')

        try:
            logger.debug(f"[{cls.site_name}] Creating new Selenium driver for thread ID: {thread_id}")
            driver = webdriver.Remote(command_executor=selenium_url, options=options)
            driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")

            with cls._lock:
                cls._drivers[thread_id] = driver
            return driver
        except Exception as e:
            logger.error(f"[{cls.site_name}] Selenium 드라이버 생성 실패 (thread: {thread_id}): {e}")
            raise

    @classmethod
    def _quit_selenium_driver(cls, thread_id):
        with cls._lock:
            driver = cls._drivers.pop(thread_id, None)
            cls._dynamic_suffixes.pop(thread_id, None)

        if driver:
            logger.debug(f"[{cls.site_name}] Quitting Selenium driver for thread ID: {thread_id}")
            try:
                driver.quit()
            except Exception as e:
                logger.warning(f"[{cls.site_name}] Exception during driver.quit(): {e}")

    @classmethod
    def _get_page_content(cls, driver, url, wait_for_locator):
        timeout = cls.SELENIUM_TIMEOUT
        driver.get(url)
        WebDriverWait(driver, timeout).until(EC.presence_of_element_located(wait_for_locator))
        return html.fromstring(driver.page_source), driver.page_source

    @classmethod
    def _ensure_dynamic_suffix(cls, driver):
        thread_id = driver.session_id
        with cls._lock:
            if thread_id in cls._dynamic_suffixes:
                return cls._dynamic_suffixes[thread_id]

        logger.debug(f"[{cls.site_name}] Fetching dynamic suffix for session: {thread_id[:8]}...")

        # 연령 확인 자동화
        #if not driver.get_cookie('wei6H'):
        #    driver.get(cls.site_base_url)
        #    try:
        #        age_button = WebDriverWait(driver, 10).until(EC.element_to_be_clickable((By.XPATH, '//a[@data-button="yes"]')))
        #        age_button.click()
        #        WebDriverWait(driver, 5).until(lambda d: d.get_cookie('wei6H') is not None)
        #        logger.debug(f"[{cls.site_name}] Age verification successful for session: {thread_id[:8]}.")
        #    except TimeoutException:
        #        logger.debug(f"[{cls.site_name}] Age confirmation button not found.")

        list_page_wait_locator = (By.XPATH, '//section[contains(@class, "c-neoItem-1000")]')
        tree, _ = cls._get_page_content(driver, cls.site_base_url, wait_for_locator=list_page_wait_locator)

        suffix = "?dref=search_id" # 기본값
        if tree is not None:
            for href in tree.xpath('//a[starts-with(@href, "/article/")]/@href'):
                if '?dref=' in href:
                    suffix = f"?{urlparse(href).query}"; break
            if suffix == "?dref=search_id": # dref 못 찾았으면 tag 찾기
                for href in tree.xpath('//a[starts-with(@href, "/article/")]/@href'):
                    if '?tag=' in href:
                        suffix = f"?{urlparse(href).query}"; break

        logger.debug(f"[{cls.site_name}] Found suffix '{suffix}' for session: {thread_id[:8]}.")
        with cls._lock:
            cls._dynamic_suffixes[thread_id] = suffix
        return suffix

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
                    logger.debug(f"[{cls.site_name}] Image URL width upgraded: {src} -> {normalized_src}")

        if normalized_src.startswith('//'): return 'https:' + normalized_src
        if normalized_src.startswith('/'): return urljoin(base_url, normalized_src)
        return normalized_src

    @classmethod
    def set_config(cls, db):
        super().set_config(db)
