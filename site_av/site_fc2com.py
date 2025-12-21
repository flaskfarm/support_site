# -*- coding: utf-8 -*-
import re
import os
import time
import sqlite3
from threading import Lock
from lxml import html
from urllib.parse import urljoin
from io import BytesIO 
from PIL import Image   

from ..entity_av import EntityAVSearch
from ..entity_base import EntityMovie, EntityActor, EntityThumb, EntityExtra, EntityRatings
from ..setup import P, logger, path_data
from .site_av_base import SiteAvBase

try:
    from selenium.webdriver.common.by import By
except ImportError:
    pass

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

    WAIT_LOCATOR = (By.XPATH, '//div[contains(@class, "items_article_headerInfo")] | //div[contains(@class, "items_notfound_header")]')


    @classmethod
    def set_config(cls, db):
        super().set_config(db)
        cls.config.update({
            "use_javten_db": db.get_bool(f"jav_uncensored_{cls.site_name}_use_javten_db"),
            "javten_db_path": os.path.join(path_data, 'db', 'javten.db'),
            "javten_local_image_path": db.get(f"jav_uncensored_{cls.site_name}_local_image_path"),
            "use_javten_image_server": db.get_bool(f"jav_uncensored_{cls.site_name}_use_image_server_url"),
            
            # 메인 이미지 서버 설정 가져오기
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
    def _query_javten_db(cls, product_id):
        """로컬 SQLite DB에서 품번으로 데이터 조회"""
        db_path = cls.config.get('javten_db_path')
        if not cls.config.get('use_javten_db') or not db_path or not os.path.exists(db_path):
            return None

        try:
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            # 가능한 ID 패턴: 'FC2-PPV-{id}', 'FC2-{id}', '{id}'(숫자만)
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
    def _get_javten_image_url(cls, db_data, img_type, target_size='w1280'):
        """
        로컬 경로 확인 -> (이미지 서버 모드면) 서버 URL 생성 -> 실패 시 원격 URL (리사이징) 반환
        """
        final_url = None
        source_type = "Remote"

        # 1. 이미지 서버 사용 옵션 체크
        if cls.config.get('use_javten_image_server'):
            local_root = cls.config.get('javten_local_image_path')
            rel_path_key = f"{img_type}_relative_path"
            
            # 2. 로컬 파일 확인
            if db_data.get(rel_path_key) and local_root:
                rel_path = db_data[rel_path_key].strip('/')
                local_path = os.path.join(local_root, rel_path)
                
                if os.path.exists(local_path):
                    # 3. URL 생성
                    # 3-1. 전용 웹 URL
                    web_url_base = cls.config.get('javten_local_image_url')
                    if web_url_base:
                        final_url = f"{web_url_base.rstrip('/')}/{rel_path}"
                        source_type = "Local(CustomURL)"
                    
                    # 3-2. 메인 이미지 서버 URL
                    else:
                        main_url_base = cls.config.get('main_image_server_url')
                        if main_url_base and cls.config.get('main_image_mode') == 'image_server':
                            final_url = f"{main_url_base.rstrip('/')}/javten/{rel_path}"
                            source_type = "Local(MainServer)"

        # 4. 원격 URL (로컬 실패 또는 미사용 시)
        if not final_url:
            final_url = cls._process_fc2_image_url(db_data.get(f"{img_type}_url"), target_size=target_size)
            source_type = "Remote"

        if final_url:
            logger.debug(f"[{cls.site_name}] Javten Image ({img_type}): {source_type} -> {final_url}")
        
        return final_url


    @classmethod
    def _process_fc2_image_url(cls, url, base_url=None, target_size='w1280'):
        """
        FC2 이미지 URL을 정규화하고 리사이징합니다.
        :param url: 원본 이미지 URL (상대 경로 또는 절대 경로)
        :param base_url: 상대 경로일 경우 기준이 되는 URL (선택 사항)
        :param target_size: 목표 해상도 (예: 'w1280', 'w360'). None이면 리사이징 안 함.
        :return: 정규화 및 리사이징된 URL
        """
        if not url: return None
        
        # 1. URL 정규화 (절대 경로 변환)
        normalized_url = url
        if normalized_url.startswith('//'):
            normalized_url = 'https:' + normalized_url
        elif base_url and not normalized_url.startswith('http'):
            normalized_url = urljoin(base_url, normalized_url)
            
        # 2. 리사이징 (target_size가 지정된 경우)
        if target_size:
            # /w숫자/ 패턴을 찾아 target_size로 치환
            # 예: /w1280/ -> /w360/ 또는 /w300/ -> /w1280/
            normalized_url = re.sub(r'/w\d+/', f'/{target_size}/', normalized_url)
            
        return normalized_url

    @classmethod
    def search(cls, keyword, manual=False):
        match = re.search(r'(\d{6,7})', keyword)
        if not match:
            return {'ret': 'success', 'data': []}
        code_part = match.group(1)

        # 1. [DB 검색] 우선 시도
        db_data = cls._query_javten_db(code_part)
        if db_data:
            logger.info(f"[{cls.site_name}] Found in Javten DB: {code_part}")
            
            item = EntityAVSearch(cls.site_name)
            item.code = cls.module_char + cls.site_char + code_part
            item.ui_code = f'FC2-{code_part}'
            item.score = 100
            
            item.title = db_data.get('tagline') or item.ui_code
            
            # 연도 추출
            item.year = 1900
            if db_data.get('release_date'):
                try:
                    # YYYY-MM-DD 형식 가정
                    item.year = int(db_data['release_date'][:4])
                except: pass
            
            if item.year == 1900: # release_date 없거나 파싱 실패 시 URL에서 추정
                detail_url = db_data.get('detail_page_url', '')
                if detail_url:
                    match_year = re.search(r'/video/(\d{4})', detail_url)
                    if match_year: item.year = int(match_year.group(1))

            # 이미지 URL (Search용 - 작은 이미지 w360)
            img_url = db_data.get('landscape_url')
            if img_url:
                item.image_url = cls._process_fc2_image_url(img_url, target_size='w360')

            if manual:
                item.title_ko = item.title
            
            return {'ret': 'success', 'data': [item.as_dict()]}

        # 2. [Selenium 검색] DB에 없으면 기존 로직 실행
        if not cls.config.get('selenium_url'):
            logger.warning(f"[{cls.site_name}] Selenium URL is not configured. FC2 search disabled.")
            return {'ret': 'no_match', 'data': []}

        driver = None
        try:
            driver = cls._get_selenium_driver()

            cls._add_fc2_cookies(driver)

            search_url = f'{cls.site_base_url}/article/{code_part}/{cls._dynamic_suffix}'
            tree, page_source_text = cls._get_page_content_selenium(driver, search_url, wait_for_locator=cls.WAIT_LOCATOR)

            if tree is None:
                return {'ret': 'no_match', 'data': []}

            # 실패 요소 확인 (404 / 국가 제한)
            if tree.xpath('//div[contains(@class, "items_notfound_header")]'):
                logger.warning(f"[{cls.site_name}] Product not found or not available (Search): {code_part}")
                return {'ret': 'no_match', 'data': []}

            if page_source_text:
                with cls._cache_lock:
                    cls._page_source_cache[code_part] = (page_source_text, time.time())
                # logger.debug(f"[{cls.site_name}] Page source for '{code_part}' cached.")

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
                # Search용 이미지는 항상 w360으로 리사이징, base_url은 search_url
                item.image_url = cls._process_fc2_image_url(img_src[0], base_url=search_url, target_size='w360')

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
        use_selenium = bool(cls.config.get('selenium_url'))
        use_db = cls.config.get('use_javten_db')

        if not use_selenium and not use_db:
            return {'ret': 'error', 'data': 'No data source available (Selenium URL not set and Javten DB disabled).'}

        try:
            entity = cls.__info(code, fp_meta_mode)
            return {'ret': 'success', 'data': entity.as_dict()} if entity else {'ret': 'error'}
        except Exception as e:
            logger.exception(f"[{cls.site_name} info] Unhandled exception in info: {e}")
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

        # ---------------------------------------------------------
        # 1. DB 조회 시도
        # ---------------------------------------------------------
        db_data = cls._query_javten_db(code_part)
        
        if db_data:
            logger.info(f"[{cls.site_name}] Info from Javten DB: {code_part}")
            is_data_found = True
            
            # 메타데이터 매핑
            if db_data.get('tagline'):
                cleaned_tagline = cls.A_P(db_data['tagline'])
                entity.original['tagline'] = cleaned_tagline
                entity.tagline = cls.trans(cleaned_tagline)
            
            if db_data.get('plot'):
                cleaned_plot = cls.A_P(db_data['plot'])
                entity.original['plot'] = cleaned_plot
                entity.plot = cls.trans(cleaned_plot)

            if db_data.get('seller'):
                entity.director = db_data['seller']
                entity.studio = db_data['seller']
                entity.tag.append(db_data['seller'])
            
            if db_data.get('genres'):
                genres = [g.strip() for g in db_data['genres'].split(',')] 
                for g in genres:
                    if g:
                        trans_genre = cls.trans(g)
                        entity.genre.append(trans_genre)

            detail_url = db_data.get('detail_page_url', '')
            if detail_url:
                match_year = re.search(r'/video/(\d{4})', detail_url)
                if match_year: entity.year = int(match_year.group(1))

            entity.year = 1900
            if db_data.get('release_date'):
                entity.premiered = db_data['release_date']
                try:
                    entity.year = int(entity.premiered[:4])
                except: pass
            
            if entity.year == 1900: # release_date 없거나 파싱 실패 시
                detail_url = db_data.get('detail_page_url', '')
                if detail_url:
                    match_year = re.search(r'/video/(\d{4})', detail_url)
                    if match_year: 
                        entity.year = int(match_year.group(1))

            entity.tag.append('FC2')

            # 이미지 처리 (DB)
            # PL (Landscape)
            pl_url = cls._get_javten_image_url(db_data, 'landscape', target_size='w1280')
            raw_image_urls['pl'] = pl_url
            
            # 스마트 크롭용 로컬 경로 확보 (이미지 서버 URL 사용 여부와 무관하게 로컬 파일 있으면 확보)
            local_root = cls.config.get('javten_local_image_path')
            if cls.config.get('use_javten_image_server') and local_root and db_data.get('landscape_relative_path'):
                temp_path = os.path.join(local_root, db_data['landscape_relative_path'].strip('/'))
                if os.path.exists(temp_path):
                    local_pl_path_for_crop = temp_path

            # Arts (Sample)
            art_url = cls._get_javten_image_url(db_data, 'sample', target_size='w1280')
            if art_url: raw_image_urls['arts'].append(art_url)


        # ---------------------------------------------------------
        # 2. Selenium 조회 시도 (DB 실패 시)
        # ---------------------------------------------------------
        if not is_data_found:
            if not cls.config.get('selenium_url'):
                return None # Selenium 없으면 중단

            tree = None
            driver = None

            # 캐시 확인
            with cls._cache_lock:
                if code_part in cls._page_source_cache:
                    cached_source, timestamp = cls._page_source_cache[code_part]
                    if (time.time() - timestamp) < cls.CACHE_EXPIRATION_SECONDS:
                        tree = html.fromstring(cached_source)
                        del cls._page_source_cache[code_part]
                    else:
                        del cls._page_source_cache[code_part]

            # 웹 요청
            if tree is None:
                try:
                    driver = cls._get_selenium_driver()
                    cls._add_fc2_cookies(driver)

                    info_url = f'{cls.site_base_url}/article/{code_part}/{cls._dynamic_suffix}'
                    detail_page_wait_locator = (By.XPATH, '//div[contains(@class, "items_article_headerInfo")]')
                    tree, _ = cls._get_page_content_selenium(driver, info_url, wait_for_locator=cls.WAIT_LOCATOR)
                finally:
                    cls._quit_selenium_driver(driver)

            if tree.xpath('//div[contains(@class, "items_notfound_header")]'):
                logger.warning(f"[{cls.site_name}] Product not found or not available (Info): {code_part}")
                return None

            is_data_found = True

            # 메타데이터 파싱 (Selenium)
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

            # 이미지 URL 추출 (Selenium)
            if poster_src := tree.xpath('//div[contains(@class, "items_article_MainitemThumb")]//img/@src | //div[contains(@class, "items_article_MainitemThumb")]//img/@data-src'):
                raw_image_urls['pl'] = cls._process_fc2_image_url(poster_src[0], base_url=cls.site_base_url, target_size='w1280')

            gallery_urls = []
            for href in tree.xpath('//a[@data-fancybox="gallery"]/@href'):
                gallery_urls.append(cls._process_fc2_image_url(href, base_url=cls.site_base_url, target_size='w1280'))
            if not gallery_urls:
                for href in tree.xpath('//section[contains(@class, "items_article_SampleImages")]//a/@href'):
                    gallery_urls.append(cls._process_fc2_image_url(href, base_url=cls.site_base_url, target_size='w1280'))
            
            raw_image_urls['arts'] = gallery_urls

            # 예고편 처리 (Selenium인 경우에만)
            if cls.config['use_extras']:
                if video_src := tree.xpath('//video[contains(@id, "sample_video")]/@src'):
                    trailer_url = cls._process_fc2_image_url(video_src[0], base_url=cls.site_base_url, target_size=None)
                    if url := cls.make_video_url(trailer_url):
                        trailer_title = entity.tagline if (fp_meta_mode or not entity.tagline) else cls.trans(entity.tagline)
                        entity.extras.append(EntityExtra("trailer", trailer_title, "mp4", url))


        # ---------------------------------------------------------
        # 3. 공통 이미지 처리 (스마트 크롭 및 최종 처리)
        # ---------------------------------------------------------
        if is_data_found:
            # 스마트 크롭 (PL -> Poster)
            use_smart = cls.config.get('use_smart_crop')
            if use_smart and raw_image_urls['pl'] and not raw_image_urls['poster']:
                try:
                    img_pl = None
                    # 1순위: DB 로직에서 찾은 로컬 파일 사용 (가장 빠름)
                    if local_pl_path_for_crop:
                        img_pl = Image.open(local_pl_path_for_crop)
                    # 2순위: URL 다운로드 (Selenium 결과 또는 DB 로컬 파일 없음)
                    else:
                        img_pl = cls.imopen(raw_image_urls['pl'])
                    
                    if img_pl:
                        cropped = cls._smart_crop_image(img_pl)
                        if cropped:
                            temp_path = cls.save_pil_to_temp(cropped)
                            if temp_path:
                                raw_image_urls['poster'] = temp_path
                                logger.debug(f"[{cls.site_name}] Smart Crop success. Temp Poster: {temp_path}")
                except Exception as e:
                    logger.error(f"[{cls.site_name}] Smart Crop Error: {e}")

            # 이미지 서버 경로 설정
            image_mode = cls.MetadataSetting.get('jav_censored_image_mode')
            if image_mode == 'image_server':
                try:
                    num_part = code_part
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

            # 최종 이미지 처리 위임
            entity = cls.process_image_data(entity, raw_image_urls, ps_url_from_cache=None)
            
            return entity

        return None


    @staticmethod
    def _extract_fc2com_title(h3_element):
        return ' '.join(h3_element.xpath(".//text()")).strip() if h3_element is not None else ""

