# -*- coding: utf-8 -*-
import re
import os
import time
import sqlite3
import html as html_module
from threading import Lock
from lxml import html
from urllib.parse import urljoin, urlencode
from io import BytesIO 
from PIL import Image

try:
    from selenium.webdriver.common.by import By
except ImportError:
    By = None

from ..entity_av import EntityAVSearch
from ..entity_base import EntityMovie, EntityActor, EntityThumb, EntityExtra, EntityRatings
from ..setup import P, logger, path_data
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
    
    # 캐시 관련
    _page_source_cache = {} # Selenium HTML 소스 캐시
    _search_result_cache = {} # 통합 검색 결과 캐시 {code_part: {'source': str, 'data': any, 'timestamp': float}}
    _cache_lock = Lock()

    WAIT_LOCATOR = None
    if By:
        WAIT_LOCATOR = (By.XPATH, '//div[contains(@class, "items_article_headerInfo")] | //div[contains(@class, "items_notfound_header")]')


    @classmethod
    def set_config(cls, db):
        super().set_config(db)
        cls.config.update({
            "use_fc2_com": db.get_bool(f"jav_uncensored_{cls.site_name}_use_fc2_com"),

            "use_javten_web": db.get_bool(f"jav_uncensored_{cls.site_name}_use_javten_web"),
            "use_javten_proxy": db.get_bool(f"jav_uncensored_{cls.site_name}_use_javten_proxy"),
            "javten_proxy_url": db.get(f"jav_uncensored_{cls.site_name}_javten_proxy_url"),

            "use_javten_db": db.get_bool(f"jav_uncensored_{cls.site_name}_use_javten_db"),
            "javten_db_path": os.path.join(path_data, 'db', 'javten.db'),

            "javten_local_image_path": db.get(f"jav_uncensored_{cls.site_name}_local_image_path"),
            "use_javten_image_server": db.get_bool(f"jav_uncensored_{cls.site_name}_use_image_server_url"),
            "javten_local_image_url": db.get(f"jav_uncensored_{cls.site_name}_local_image_url"),
            
            "main_image_server_url": db.get("jav_censored_image_server_url"),
            "main_image_mode": db.get("jav_censored_image_mode"),
        })


    @classmethod
    def _add_fc2_cookies(cls, driver):
        """FC2 성인 인증 쿠키 추가 (메인 페이지 경유)"""
        try:
            driver.get(cls.site_base_url + '/')
            time.sleep(3)

            try:
                yes_btn = driver.find_elements(By.XPATH, '//a[@data-button="yes"]')
                if yes_btn:
                    driver.execute_script("arguments[0].click();", yes_btn[0])
                    time.sleep(3)
            except: pass

            driver.add_cookie({'name': 'wei6H', 'value': '1', 'path': '/'})
            driver.add_cookie({'name': 'GDPRCHECK', 'value': 'true', 'path': '/'})
        except Exception as e:
            logger.warning(f"[{cls.site_name}] Failed to prepare cookies: {e}")


    @classmethod
    def _get_javten_proxies(cls):
        if cls.config.get('use_javten_proxy'):
            proxy_url = cls.config.get('javten_proxy_url')
            if proxy_url:
                return {"http": proxy_url, "https": proxy_url}
        
        return None


    @classmethod
    def _query_javten_db(cls, product_id):
        """로컬 SQLite DB에서 품번으로 데이터 조회"""
        db_path = cls.config.get('javten_db_path')
        if not cls.config.get('use_javten_db') or not db_path or not os.path.exists(db_path):
            return None

        try:
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            target_ids = [f"FC2-PPV-{product_id}", f"FC2-{product_id}", product_id]
            placeholders = ','.join('?' * len(target_ids))

            cursor.execute(f"SELECT * FROM movies WHERE product_id IN ({placeholders})", target_ids)
            row = cursor.fetchone()

            conn.close()
            
            if row: return dict(row)
        except Exception as e:
            logger.error(f"[{cls.site_name}] DB Query Error: {e}")
        return None


    @classmethod
    def _process_fc2_image_url(cls, url, base_url=None, target_size='w1280'):
        if not url: return None
        
        normalized_url = url
        if normalized_url.startswith('//'):
            normalized_url = 'https:' + normalized_url
        elif base_url and not normalized_url.startswith('http'):
            normalized_url = urljoin(base_url, normalized_url)
            
        # CDN 직결 URL(storage...)인 경우 리사이징 패스하고 반환
        if 'storage' in normalized_url and 'contents-thumbnail' not in normalized_url:
            return normalized_url

        # 썸네일 서버 URL인 경우 리사이징 적용
        if target_size == 'original':
            match = re.search(r'contents-thumbnail\d*\.fc2\.com/w\d+/(.*)', normalized_url)
            if match: return f"https://{match.group(1)}"
            return normalized_url

        if target_size:
            normalized_url = re.sub(r'/w\d+/', f'/{target_size}/', normalized_url)
            
        return normalized_url


    @classmethod
    def _get_javten_image_url(cls, db_data, img_type, target_size='w1280'):
        if not cls.config.get('use_javten_image_server'):
            return cls._process_fc2_image_url(db_data.get(f"{img_type}_url"), target_size=target_size)

        local_root = cls.config.get('javten_local_image_path')
        rel_path_key = f"{img_type}_relative_path"
        
        if db_data.get(rel_path_key) and local_root:
            rel_path = db_data[rel_path_key].strip('/')
            local_path = os.path.join(local_root, rel_path)
            if os.path.exists(local_path):
                web_url_base = cls.config.get('javten_local_image_url')
                if web_url_base: return f"{web_url_base.rstrip('/')}/{rel_path}"
                main_url_base = cls.config.get('main_image_server_url')
                if main_url_base and cls.config.get('main_image_mode') == 'image_server':
                    return f"{main_url_base.rstrip('/')}/javten/{rel_path}"
                return local_path 

        return cls._process_fc2_image_url(db_data.get(f"{img_type}_url"), target_size=target_size)


    # 이미지 유효성 검사
    @classmethod
    def _check_image_validity(cls, url):
        if not url: return False
        try:
            res = cls.get_response(url, method='GET', stream=True, timeout=5, allow_redirects=True)
            
            if not res:
                logger.debug(f"[{cls.site_name}] Image check failed: No response for {url}")
                return False
            
            if res.status_code != 200:
                logger.debug(f"[{cls.site_name}] Image check failed: Status {res.status_code} for {url}")
                return False
            
            if 'error.fc2.com' in res.url or 'noimage' in res.url:
                logger.debug(f"[{cls.site_name}] Image check failed: Redirected to error page ({res.url}) for {url}")
                return False
            
            content_type = res.headers.get('Content-Type', '').lower()
            if not content_type.startswith('image/'):
                logger.debug(f"[{cls.site_name}] Image check failed: Invalid Content-Type ({content_type}) for {url}")
                return False
                
            return True
        except Exception as e:
            logger.debug(f"[{cls.site_name}] Image check exception for {url}: {e}")
            return False


    @classmethod
    def _fetch_fc2_embed_poster(cls, embed_url):
        if not embed_url: return None
        if embed_url.startswith('//'): embed_url = 'https:' + embed_url
        
        logger.debug(f"[{cls.site_name}] Fetching embed poster from: {embed_url}")
        
        headers = cls.default_headers.copy()
        headers['Referer'] = 'https://javten.com/'
        proxies = cls._get_javten_proxies()

        # 1. HTML 파싱 / 정규식 시도
        try:
            res = cls.get_response(embed_url, headers=headers, proxies=proxies)
            if res and res.status_code == 200:
                # 1-1. HTML 파싱
                try:
                    tree = html.fromstring(res.text)
                    poster = tree.xpath('//video[@poster]/@poster')
                    if poster:
                        candidate = cls._process_fc2_image_url(poster[0], target_size='original')
                        logger.debug(f"[{cls.site_name}] Found poster in embed (XPath): {candidate}")
                        return candidate
                except: pass

                # 1-2. 정규식 추출
                match = re.search(r'poster=["\'](https?://[^"\']+)["\']', res.text)
                if match:
                    candidate = cls._process_fc2_image_url(match.group(1), target_size='original')
                    logger.debug(f"[{cls.site_name}] Found poster in embed (Regex): {candidate}")
                    return candidate
        except Exception as e:
            logger.debug(f"[{cls.site_name}] Embed HTML fetch failed: {e}")

        # 2. API 호출 시도 (Fallback)
        try:
            match_id = re.search(r'/embed/(\d+)', embed_url)
            if match_id:
                content_id = match_id.group(1)
                api_url = f"https://adult.contents.fc2.com/api/v2/videos/{content_id}/sample"
                
                # API 호출용 헤더 (Referer를 임베드 URL로)
                api_headers = headers.copy()
                api_headers['Referer'] = embed_url
                
                res_api = cls.get_response(api_url, headers=api_headers, proxies=proxies)
                if res_api and res_api.status_code == 200:
                    data = res_api.json()
                    poster_path = data.get('poster_image_path')
                    if poster_path:
                        candidate = cls._process_fc2_image_url(poster_path, target_size='original')
                        logger.debug(f"[{cls.site_name}] Found poster via API: {candidate}")
                        return candidate
        except Exception as e:
            logger.debug(f"[{cls.site_name}] Embed API fetch failed: {e}")

        logger.debug(f"[{cls.site_name}] No poster found in embed page.")
        return None


    @classmethod
    def _get_javten_web_content(cls, code_part):
        """Javten.com에서 품번으로 검색하고 상세 정보를 파싱합니다."""
        if not cls.config.get('use_javten_web'): return None

        search_url = f"https://javten.com/search?kw={code_part}"
        proxies = cls._get_javten_proxies()

        detail_url = None
        tree = None

        try:
            # 1. 검색 요청 (리디렉션 자동 처리)
            res = cls.get_response(search_url, allow_redirects=True, proxies=proxies)
            if not res or res.status_code != 200:
                return None

            # 리디렉션된 최종 URL이 상세 페이지인지 확인
            # 성공 시 URL 예: https://javten.com/video/2032177/id4823969/...
            if '/video/' in res.url and f"id{code_part}" in res.url:
                detail_url = res.url
                tree = html.fromstring(res.text)
            else:
                # 리디렉션 안 됨 -> 검색 결과 목록 페이지일 가능성
                # 여기서 정확한 품번을 다시 찾아야 함
                temp_tree = html.fromstring(res.text)
                # 검색 결과 아이템 중 제목에 품번이 포함된 링크 찾기 (card-title 등)
                # 예: <h4 class="card-title">FC2-PPV-4823969</h4>
                for item in temp_tree.xpath('//div[contains(@class, "padding-item")]'):
                    title_el = item.xpath('.//h4[contains(@class, "card-title")]')
                    if title_el and code_part in title_el[0].text_content():
                        link_el = item.xpath('.//a[contains(@class, "stretched-link")]/@href')
                        if link_el:
                            detail_url = urljoin("https://javten.com", link_el[0])
                            # 상세 페이지 재요청
                            res_detail = cls.get_response(detail_url, proxies=proxies)
                            if res_detail and res_detail.status_code == 200:
                                tree = html.fromstring(res_detail.text)
                            break
        except Exception as e:
            logger.error(f"[{cls.site_name}] Javten Web Search Error: {e}")
            return None

        if tree is None: return None

        # 2. 상세 페이지 파싱
        ret = {'source': 'javten_web', 'detail_url': detail_url}
        try:
            # Tagline & Seller
            meta_desc = tree.xpath('//meta[@name="description"]/@content')
            if meta_desc:
                parts = [p.strip() for p in meta_desc[0].split('|')]
                if len(parts) > 1: ret['tagline'] = parts[1]
                if len(parts) > 2: ret['seller'] = parts[2].replace('By ', '').strip()

            # Genres
            meta_keys = tree.xpath('//meta[@name="keywords"]/@content')
            if meta_keys:
                ret['genres'] = [g.strip() for g in meta_keys[0].split(',') if g.strip()]

            # Release Date
            meta_pub = tree.xpath('//meta[@property="videos:published_time"]/@content')
            if meta_pub: ret['release_date'] = meta_pub[0].split('T')[0]

            # Images 처리 (검증 및 Iframe 백업)
            landscape_url = None
            
            # 1. 메타 태그 이미지
            meta_og_img = tree.xpath('//meta[@property="og:image"]/@content')
            if meta_og_img:
                candidate_url = cls._process_fc2_image_url(meta_og_img[0], target_size='original')
                logger.debug(f"[{cls.site_name}] Checking Meta Image: {candidate_url}")
                
                if cls._check_image_validity(candidate_url):
                    landscape_url = candidate_url
                    logger.debug(f"[{cls.site_name}] Meta Image is VALID.")
                else:
                    logger.warning(f"[{cls.site_name}] Meta Image INVALID. Trying fallback...")

            # 2. Iframe 포스터 시도
            if not landscape_url:
                embed_url = None
                iframe_el = tree.xpath('//div[contains(@class, "card-img-top")]//iframe/@src') or \
                            tree.xpath('//div[contains(@class, "card-img-top")]//iframe/@data-src')
                
                if iframe_el:
                    embed_url = iframe_el[0]
                    logger.debug(f"[{cls.site_name}] Found Embed URL: {embed_url}")
                    
                    poster_candidate = cls._fetch_fc2_embed_poster(embed_url)
                    if poster_candidate:
                        if cls._check_image_validity(poster_candidate):
                            landscape_url = poster_candidate
                            logger.debug(f"[{cls.site_name}] Embed Poster is VALID: {landscape_url}")
                        else:
                            logger.debug(f"[{cls.site_name}] Embed Poster INVALID: {poster_candidate}")
                else:
                    logger.debug(f"[{cls.site_name}] No Embed URL found on page.")

            if landscape_url:
                ret['landscape_url'] = landscape_url
            else:
                logger.warning(f"[{cls.site_name}] Failed to find any valid landscape image.")

            # Sample (Gallery) - 첫 번째 이미지 검증
            gallery_el = tree.xpath('//a[@data-fancybox="gallery"]/@href')
            if gallery_el:
                sample_url = cls._process_fc2_image_url(gallery_el[0], target_size='original')
                if cls._check_image_validity(sample_url):
                    ret['sample_url'] = sample_url
                else:
                    logger.debug(f"[{cls.site_name}] Invalid Sample Image: {sample_url}")

            # Plot
            plot_divs = tree.xpath('//div[contains(@class, "col") and contains(@class, "des")]')
            if plot_divs:
                # 불필요 태그 제거 로직은 복잡하니 text_content()로 단순화하거나 필요한 경우 html string 처리
                # 여기서는 간단히 text_content 사용 후 정제
                raw_plot = plot_divs[0].text_content()
                ret['plot'] = cls.A_P(raw_plot)

            return ret

        except Exception as e:
            logger.error(f"[{cls.site_name}] Javten Web Parse Error: {e}")
            return None


    @classmethod
    def search(cls, keyword, manual=False):
        match = re.search(r'(\d{6,7})', keyword)
        if not match: return {'ret': 'success', 'data': []}
        code_part = match.group(1)
        
        item = None
        cache_source = None
        cache_data = None

        # 1. [Selenium 검색] (FC2 공식)
        if cls.config.get('use_fc2_com') and cls.config.get('selenium_url'):
            driver = None
            try:
                driver = cls._get_selenium_driver()
                cls._add_fc2_cookies(driver)
                search_url = f'{cls.site_base_url}/article/{code_part}/{cls._dynamic_suffix}'
                
                tree, page_source_text = cls._get_page_content_selenium(driver, search_url, wait_for_locator=cls.WAIT_LOCATOR)

                if tree and not tree.xpath('//div[contains(@class, "items_notfound_header")]'):
                    # 캐시 저장
                    if page_source_text:
                        with cls._cache_lock:
                            cls._page_source_cache[code_part] = (page_source_text, time.time())
                            cache_source = 'official'
                            cache_data = True

                    item = EntityAVSearch(cls.site_name)
                    item.code = cls.module_char + cls.site_char + code_part
                    item.ui_code = cls._parse_ui_code_uncensored(keyword)
                    if not item.ui_code or 'FC2' not in item.ui_code.upper(): item.ui_code = f'FC2-{code_part}'
                    
                    # 메타 태그 파싱 우선
                    head_meta = {}
                    for meta in tree.xpath('//meta'):
                        name = meta.get('name') or meta.get('property')
                        content = meta.get('content')
                        if name and content: head_meta[name] = content

                    # Title
                    if 'og:title' in head_meta:
                        item.title = head_meta['og:title'].split('|')[0].strip()
                    elif h3_title := tree.xpath('//div[contains(@class, "items_article_headerInfo")]/h3'):
                        item.title = cls._extract_fc2com_title(h3_title[0])
                    else:
                        item.title = item.ui_code

                    # Year
                    if date_text := tree.xpath('//p[contains(text(), "Sale Day")]/text()'):
                        if match_year := re.search(r'(\d{4})/\d{2}/\d{2}', date_text[0]):
                            item.year = int(match_year.group(1))
                    else:
                        item.year = 1900

                    # Image (og:image 우선 -> 없으면 본문 파싱)
                    if 'og:image' in head_meta:
                        # og:image는 보통 원본 CDN 주소임. Search용이라도 고화질 사용해도 무방 (또는 w360으로 변환 시도)
                        # _process_fc2_image_url이 storage URL은 리사이징 안하고 원본 반환하므로 OK
                        item.image_url = cls._process_fc2_image_url(head_meta['og:image'], target_size='w360')
                    elif img_src := tree.xpath('//div[contains(@class, "items_article_MainitemThumb")]//img/@src | //div[contains(@class, "items_article_MainitemThumb")]//img/@data-src'):
                        item.image_url = cls._process_fc2_image_url(img_src[0], base_url=search_url, target_size='w360')
                    
                    item.score = 100
                    logger.info(f"[{cls.site_name} - Official] Search Success: {item.ui_code}")
            except Exception as e:
                logger.error(f"[{cls.site_name} - Official] Search Exception: {e}")
            finally:
                cls._quit_selenium_driver(driver)

        # 2. [Javten Web 검색] (FC2 실패 시)
        if not item:
            web_data = cls._get_javten_web_content(code_part)
            if web_data:
                cache_source = 'web'
                cache_data = web_data

                item = EntityAVSearch(cls.site_name)
                item.code = cls.module_char + cls.site_char + code_part
                item.ui_code = f'FC2-{code_part}'
                item.score = 100
                item.title = web_data.get('tagline') or item.ui_code
                
                if web_data.get('release_date'):
                    try: item.year = int(web_data['release_date'][:4])
                    except: pass
                elif web_data.get('detail_url'):
                    match_year = re.search(r'/video/(\d{4})', web_data['detail_url'])
                    if match_year: item.year = int(match_year.group(1))
                else: item.year = 1900

                if web_data.get('landscape_url'):
                    item.image_url = cls._process_fc2_image_url(web_data['landscape_url'], target_size='w1280')
                
                logger.info(f"[{cls.site_name} - JavtenWeb] Search Success: {item.ui_code}")

        # 3. [DB 검색] (모두 실패 시)
        if not item:
            db_data = cls._query_javten_db(code_part)
            if db_data:
                cache_source = 'db'
                cache_data = db_data

                item = EntityAVSearch(cls.site_name)
                item.code = cls.module_char + cls.site_char + code_part
                item.ui_code = f'FC2-{code_part}'
                item.score = 100
                item.title = db_data.get('tagline') or item.ui_code
                
                item.year = 1900
                if db_data.get('release_date'):
                    try: item.year = int(db_data['release_date'][:4])
                    except: pass
                if item.year == 1900 and (detail_url := db_data.get('detail_page_url')):
                    if match_year := re.search(r'/video/(\d{4})', detail_url):
                        item.year = int(match_year.group(1))

                # Search용 이미지는 w1280 (로컬일 경우 Proxy 변환)
                img_url = cls._get_javten_image_url(db_data, 'landscape', target_size='w1280')
                if img_url and not img_url.startswith('http'):
                    param = {'site': 'system', 'path': img_url}
                    module_prefix = 'jav_image' if cls.module_char == 'C' else 'jav_image_un'
                    item.image_url = f"{F.SystemModelSetting.get('ddns')}/metadata/normal/{module_prefix}?{urlencode(param)}"
                else:
                    item.image_url = img_url
                
                logger.info(f"[{cls.site_name} - JavtenDB] Search Success: {item.ui_code}")

        # [통합 캐시 저장]
        if item and cache_source:
            with cls._cache_lock:
                cls._search_result_cache[code_part] = {
                    'source': cache_source,
                    'data': cache_data,
                    'timestamp': time.time()
                }
            logger.debug(f"[{cls.site_name}] Search result cached for '{code_part}' (Source: {cache_source})")

        if item:
            if manual: item.title_ko = item.title
            # 원격 URL이고 Proxy 사용 시 변환
            if manual and cls.config.get('use_proxy') and item.image_url and item.image_url.startswith('http') and 'fc2.com' in item.image_url:
                item.image_url = cls.make_image_url(item.image_url)
            return {'ret': 'success', 'data': [item.as_dict()]}

        return {'ret': 'no_match', 'data': []}


    @classmethod
    def info(cls, code, fp_meta_mode=False):
        # 가용 소스 확인
        has_official = cls.config.get('use_fc2_com') and cls.config.get('selenium_url')
        has_web = cls.config.get('use_javten_web')
        has_db = cls.config.get('use_javten_db')

        if not (has_official or has_web or has_db):
            return {'ret': 'error', 'data': 'No data source available/enabled.'}

        try:
            entity = cls.__info(code, fp_meta_mode)
            return {'ret': 'success', 'data': entity.as_dict()} if entity else {'ret': 'error'}
        except Exception as e:
            logger.exception(f"[{cls.site_name}] Info Exception: {e}")
            return {'ret': 'exception', 'data': str(e)}


    @classmethod
    def __info(cls, code, fp_meta_mode=False):
        code_part = code[len(cls.module_char) + len(cls.site_char):]
        
        entity = EntityMovie(cls.site_name, code)
        entity.country = ['일본']; entity.mpaa = '청소년 관람불가'
        entity.thumb = []; entity.fanart = []; entity.extras = []; entity.tag = []; entity.genre = []
        entity.original = {}
        entity.ui_code = f'FC2-{code_part}'
        entity.title = entity.originaltitle = entity.sorttitle = entity.ui_code.upper()
        entity.label = "FC2"

        raw_image_urls = {'poster': None, 'pl': None, 'arts': []}
        local_pl_path_for_crop = None
        is_data_found = False
        
        # [캐시 확인 및 우선순위 결정]
        cached_source = None
        cached_data = None
        
        with cls._cache_lock:
            if code_part in cls._search_result_cache:
                cache_entry = cls._search_result_cache[code_part]
                if (time.time() - cache_entry['timestamp']) < cls.CACHE_EXPIRATION_SECONDS:
                    cached_source = cache_entry['source']
                    cached_data = cache_entry['data']
                    logger.debug(f"[{cls.site_name}] Info: Using search cache for '{code_part}' (Source: {cached_source})")

        # 1. [Selenium 조회] (Official)
        should_try_official = (cached_source == 'official') or (not cached_source and cls.config.get('use_fc2_com') and cls.config.get('selenium_url'))
        
        if should_try_official:
            tree = None
            driver = None
            
            # 페이지 소스 캐시 확인
            with cls._cache_lock:
                if code_part in cls._page_source_cache:
                    cached_page, timestamp = cls._page_source_cache[code_part]
                    if (time.time() - timestamp) < cls.CACHE_EXPIRATION_SECONDS:
                        tree = html.fromstring(cached_page)
                        # del cls._page_source_cache[code_part] # 캐시 유지
                    else:
                        del cls._page_source_cache[code_part]

            # 캐시 없으면 웹 요청
            if tree is None:
                try:
                    driver = cls._get_selenium_driver()
                    cls._add_fc2_cookies(driver)
                    info_url = f'{cls.site_base_url}/article/{code_part}/{cls._dynamic_suffix}'
                    tree, _ = cls._get_page_content_selenium(driver, info_url, wait_for_locator=cls.WAIT_LOCATOR)
                finally:
                    cls._quit_selenium_driver(driver)

            # 정상 페이지 확인
            if tree and not tree.xpath('//div[contains(@class, "items_notfound_header")]'):
                is_data_found = True
                logger.info(f"[{cls.site_name} - Official] Info Success: {code_part}")
                
                # 메타 태그 파싱 우선
                head_meta = {}
                for meta in tree.xpath('//meta'):
                    name = meta.get('name') or meta.get('property')
                    content = meta.get('content')
                    if name and content: head_meta[name] = content

                # 1. Title
                if 'og:title' in head_meta:
                    raw_title = head_meta['og:title'].split('|')[0].strip()
                elif h3_title := tree.xpath('//div[contains(@class, "items_article_headerInfo")]/h3'):
                    raw_title = cls._extract_fc2com_title(h3_title[0])
                else:
                    raw_title = entity.ui_code
                
                cleaned_text = cls.A_P(raw_title)
                entity.original['tagline'] = cleaned_text; entity.tagline = cls.trans(cleaned_text)
                
                # 2. Plot (본문 우선 -> 없으면 Tagline)
                plot_el = tree.xpath('//div[contains(@class, "items_article_Contents")]')
                if plot_el:
                    plot_text = plot_el[0].text_content().strip()
                    if plot_text:
                        entity.original['plot'] = cls.A_P(plot_text)
                        entity.plot = cls.trans(entity.original['plot'])
                
                if not entity.plot: # Plot 못 찾았으면 Tagline 복사
                    entity.original['plot'] = entity.original['tagline']
                    entity.plot = entity.tagline

                # 3. Date
                if date_text := tree.xpath('//p[contains(text(), "Sale Day")]/text()'):
                    if match_date := re.search(r'(\d{4})/(\d{2})/(\d{2})', date_text[0]):
                        entity.premiered = f"{match_date.group(1)}-{match_date.group(2)}-{match_date.group(3)}"
                        entity.year = int(match_date.group(1))
                else:
                    entity.year = 1900

                # 4. Seller / Studio
                if seller := tree.xpath('//a[contains(@href, "/users/")]/text()'):
                    val = seller[0].strip()
                    entity.original['studio'] = val; entity.studio = val
                    entity.original['director'] = val; entity.director = val

                # 5. Genre
                if 'genre' not in entity.original: entity.original['genre'] = []
                for genre_name in tree.xpath('//section[contains(@class, "items_article_TagArea")]//a'):
                    g = genre_name.text_content().strip()
                    if g:
                        entity.original['genre'].append(g)
                        entity.genre.append(cls.trans(g))

                # 6. Image (PL)
                # og:image 우선 -> 없으면 본문
                if 'og:image' in head_meta:
                    raw_image_urls['pl'] = cls._process_fc2_image_url(head_meta['og:image'], target_size='original')
                elif poster_src := tree.xpath('//div[contains(@class, "items_article_MainitemThumb")]//img/@src | //div[contains(@class, "items_article_MainitemThumb")]//img/@data-src'):
                    raw_image_urls['pl'] = cls._process_fc2_image_url(poster_src[0], base_url=cls.site_base_url, target_size='w1280')

                # 7. Arts (Gallery)
                # 메타 태그에는 갤러리가 없으므로 본문 파싱
                for href in tree.xpath('//a[@data-fancybox="gallery"]/@href') or tree.xpath('//section[contains(@class, "items_article_SampleImages")]//a/@href'):
                    raw_image_urls['arts'].append(cls._process_fc2_image_url(href, base_url=cls.site_base_url, target_size='w1280'))

                # 8. Trailer (Video Tag)
                if cls.config['use_extras']:
                    if video_src := tree.xpath('//video[contains(@id, "sample_video")]/@src'):
                        trailer_url = cls._process_fc2_image_url(video_src[0], base_url=cls.site_base_url, target_size=None)
                        if url := cls.make_video_url(trailer_url):
                            entity.extras.append(EntityExtra("trailer", entity.tagline, "mp4", url))

        # 2. [Javten Web 조회]
        should_try_web = (cached_source == 'web') or (not is_data_found and not cached_source and cls.config.get('use_javten_web'))
        
        if not is_data_found and should_try_web:
            javten_web_data = cached_data if cached_source == 'web' else cls._get_javten_web_content(code_part)
            
            if javten_web_data:
                logger.info(f"[{cls.site_name} - JavtenWeb] Info Success: {code_part}")
                is_data_found = True
                
                if javten_web_data.get('tagline'):
                    val = cls.A_P(javten_web_data['tagline'])
                    entity.original['tagline'] = val; entity.tagline = cls.trans(val)
                if javten_web_data.get('plot'):
                    val = cls.A_P(javten_web_data['plot'])
                    entity.original['plot'] = val; entity.plot = cls.trans(val)
                if javten_web_data.get('seller'):
                    val = javten_web_data['seller']
                    entity.director = val; entity.studio = cls.trans(val); entity.tag.append(val)
                if javten_web_data.get('genres'):
                    for g in javten_web_data['genres']:
                        entity.genre.append(cls.trans(g))

                entity.year = 1900
                if javten_web_data.get('release_date'):
                    entity.premiered = javten_web_data['release_date']
                    try: entity.year = int(entity.premiered[:4])
                    except: pass
                elif javten_web_data.get('detail_url'):
                    match_year = re.search(r'/video/(\d{4})', javten_web_data['detail_url'])
                    if match_year: entity.year = int(match_year.group(1))

                # 이미지
                raw_image_urls['pl'] = cls._process_fc2_image_url(javten_web_data.get('landscape_url'), target_size='w1280')
                if javten_web_data.get('sample_url'):
                    raw_image_urls['arts'].append(cls._process_fc2_image_url(javten_web_data.get('sample_url'), target_size='w1280'))

        # 3. [DB 조회]
        should_try_db = (cached_source == 'db') or (not is_data_found and not cached_source)
        
        if not is_data_found and should_try_db:
            db_data = cached_data if cached_source == 'db' else cls._query_javten_db(code_part)
            if db_data:
                logger.info(f"[{cls.site_name} - JavtenDB] Info Success: {code_part}")
                is_data_found = True
                
                if db_data.get('tagline'):
                    val = cls.A_P(db_data['tagline'])
                    entity.original['tagline'] = val; entity.tagline = cls.trans(val)
                if db_data.get('plot'):
                    val = cls.A_P(db_data['plot'])
                    entity.original['plot'] = val; entity.plot = cls.trans(val)
                if db_data.get('seller'):
                    val = db_data['seller']
                    entity.director = val; entity.studio = cls.trans(val); entity.tag.append(val)
                if db_data.get('genres'):
                    for g in [x.strip() for x in db_data['genres'].split(',')]:
                        if g: entity.genre.append(cls.trans(g))

                entity.year = 1900
                if db_data.get('release_date'):
                    entity.premiered = db_data['release_date']
                    try: entity.year = int(entity.premiered[:4])
                    except: pass
                if entity.year == 1900 and (detail_url := db_data.get('detail_page_url')):
                    if match_year := re.search(r'/video/(\d{4})', detail_url):
                        entity.year = int(match_year.group(1))

                # 이미지
                raw_image_urls['pl'] = cls._get_javten_image_url(db_data, 'landscape', target_size='w1280')
                local_root = cls.config.get('javten_local_image_path')
                if local_root and db_data.get('landscape_relative_path'):
                    temp_path = os.path.join(local_root, db_data['landscape_relative_path'].strip('/'))
                    if os.path.exists(temp_path): local_pl_path_for_crop = temp_path

                art_url = cls._get_javten_image_url(db_data, 'sample', target_size='w1280')
                if art_url: raw_image_urls['arts'].append(art_url)

        # 4. [공통 이미지 처리] (오리지널 확인 + 스마트 크롭)
        if is_data_found:
            entity.tag.append('FC2')
            
            # PL 이미지 오리지널 URL 검증 (원격 URL인 경우에만)
            if raw_image_urls['pl'] and raw_image_urls['pl'].startswith('http'):
                base_pl_url = raw_image_urls['pl']
                original_pl_url = cls._process_fc2_image_url(base_pl_url, target_size='original')
                if original_pl_url != base_pl_url:
                    try:
                        res = cls.get_response(original_pl_url, method='HEAD', timeout=3)
                        if res and res.status_code == 200:
                            raw_image_urls['pl'] = original_pl_url
                    except: pass

            # 스마트 크롭 (PL -> Poster)
            if cls.config.get('use_smart_crop') and raw_image_urls['pl'] and not raw_image_urls['poster']:
                try:
                    img_pl = None
                    if local_pl_path_for_crop: # DB 로컬 파일
                        img_pl = Image.open(local_pl_path_for_crop)
                    else: # 원격 URL
                        res_pl = cls.get_response(raw_image_urls['pl'], stream=True, timeout=5)
                        if res_pl and res_pl.status_code == 200:
                            img_pl = Image.open(BytesIO(res_pl.content))
                    
                    if img_pl:
                        cropped = cls._smart_crop_image(img_pl)
                        if cropped:
                            if temp_path := cls.save_pil_to_temp(cropped):
                                raw_image_urls['poster'] = temp_path
                                logger.debug(f"[{cls.site_name}] Smart Crop success.")
                except Exception as e:
                    logger.error(f"[{cls.site_name}] Smart Crop Error: {e}")

            entity = cls.process_image_data(entity, raw_image_urls, ps_url_from_cache=None)
            return entity

        return None


    @staticmethod
    def _extract_fc2com_title(h3_element):
        return ' '.join(h3_element.xpath(".//text()")).strip() if h3_element is not None else ""

