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
            
        if target_size == 'original':
            # w 경로 제거 시도
            match = re.search(r'contents-thumbnail\d*\.fc2\.com/w\d+/(.*)', normalized_url)
            if match:
                return f"https://{match.group(1)}"
            return normalized_url # 패턴 안 맞으면 원본 리턴

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


    @classmethod
    def search(cls, keyword, manual=False):
        match = re.search(r'(\d{6,7})', keyword)
        if not match: return {'ret': 'success', 'data': []}
        code_part = match.group(1)
        item = None

        # 1. [Selenium 검색]
        if cls.config.get('selenium_url'):
            driver = None
            try:
                driver = cls._get_selenium_driver()
                cls._add_fc2_cookies(driver)
                search_url = f'{cls.site_base_url}/article/{code_part}/{cls._dynamic_suffix}'
                tree, page_source_text = cls._get_page_content_selenium(driver, search_url, wait_for_locator=cls.WAIT_LOCATOR)

                # 실패(404 등)가 아니고 정상 페이지인 경우
                if tree is not None and len(tree.xpath('//div[contains(@class, "items_notfound_header")]')) == 0:
                    if page_source_text:
                        with cls._cache_lock:
                            cls._page_source_cache[code_part] = (page_source_text, time.time())
                    
                    item = EntityAVSearch(cls.site_name)
                    item.code = cls.module_char + cls.site_char + code_part
                    item.ui_code = cls._parse_ui_code_uncensored(keyword)
                    if not item.ui_code or 'FC2' not in item.ui_code.upper(): item.ui_code = f'FC2-{code_part}'
                    
                    if h3_title := tree.xpath('//div[contains(@class, "items_article_headerInfo")]/h3'):
                        item.title = cls._extract_fc2com_title(h3_title[0])
                    else: item.title = item.ui_code

                    if date_text := tree.xpath('//p[contains(text(), "Sale Day")]/text()'):
                        if match_year := re.search(r'(\d{4})/\d{2}/\d{2}', date_text[0]):
                            item.year = int(match_year.group(1))
                    
                    if img_src := tree.xpath('//div[contains(@class, "items_article_MainitemThumb")]//img/@src | //div[contains(@class, "items_article_MainitemThumb")]//img/@data-src'):
                        item.image_url = cls._process_fc2_image_url(img_src[0], base_url=search_url, target_size='w360')
                    
                    item.score = 100
                    logger.info(f"[{cls.site_name}] Search Success (Selenium): {item.ui_code}")
            except Exception as e:
                logger.error(f"[{cls.site_name}] Selenium Search Exception: {e}")
            finally:
                cls._quit_selenium_driver(driver)

        # 2. [DB 검색] Selenium 실패/미사용 시
        if not item:
            db_data = cls._query_javten_db(code_part)
            if db_data:
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

                # Search용 이미지는 항상 w360 (로컬일 경우 Proxy 변환 필요)
                img_url = cls._get_javten_image_url(db_data, 'landscape', target_size='w360')
                if img_url and not img_url.startswith('http'):
                    param = {'site': 'system', 'path': img_url}
                    module_prefix = 'jav_image' if cls.module_char == 'C' else 'jav_image_un'
                    item.image_url = f"{F.SystemModelSetting.get('ddns')}/metadata/normal/{module_prefix}?{urlencode(param)}"
                else:
                    item.image_url = img_url
                
                logger.info(f"[{cls.site_name}] Search Success (DB): {item.ui_code}")

        if item:
            if manual: item.title_ko = item.title
            if manual and cls.config.get('use_proxy') and item.image_url and 'fc2.com' in item.image_url:
                item.image_url = cls.make_image_url(item.image_url)
            return {'ret': 'success', 'data': [item.as_dict()]}

        return {'ret': 'no_match', 'data': []}


    @classmethod
    def info(cls, code, fp_meta_mode=False):
        if not cls.config.get('selenium_url') and not cls.config.get('use_javten_db'):
            return {'ret': 'error', 'data': 'No data source available.'}
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

        # 1. [Selenium 조회]
        if cls.config.get('selenium_url'):
            tree = None
            # 캐시 확인
            with cls._cache_lock:
                if code_part in cls._page_source_cache:
                    cached_source, timestamp = cls._page_source_cache[code_part]
                    if (time.time() - timestamp) < cls.CACHE_EXPIRATION_SECONDS:
                        tree = html.fromstring(cached_source)
                        del cls._page_source_cache[code_part]
                    else: del cls._page_source_cache[code_part]

            if tree is None:
                driver = None
                try:
                    driver = cls._get_selenium_driver()
                    cls._add_fc2_cookies(driver)
                    info_url = f'{cls.site_base_url}/article/{code_part}/{cls._dynamic_suffix}'
                    tree, _ = cls._get_page_content_selenium(driver, info_url, wait_for_locator=cls.WAIT_LOCATOR)
                finally:
                    cls._quit_selenium_driver(driver)

            # 정상 페이지 확인
            if tree is not None and len(tree.xpath('//div[contains(@class, "items_notfound_header")]')) == 0:
                is_data_found = True
                
                # 메타데이터
                if h3_title := tree.xpath('//div[contains(@class, "items_article_headerInfo")]/h3'):
                    raw_title = cls._extract_fc2com_title(h3_title[0])
                    cleaned_text = cls.A_P(raw_title)
                    entity.original['tagline'] = cleaned_text; entity.tagline = cls.trans(cleaned_text)
                    entity.original['plot'] = cleaned_text; entity.plot = cls.trans(cleaned_text)

                if date_text := tree.xpath('//p[contains(text(), "Sale Day")]/text()'):
                    if match_date := re.search(r'(\d{4})/(\d{2})/(\d{2})', date_text[0]):
                        entity.premiered = f"{match_date.group(1)}-{match_date.group(2)}-{match_date.group(3)}"
                        entity.year = int(match_date.group(1))

                if seller := tree.xpath('//a[contains(@href, "/users/")]/text()'):
                    val = seller[0].strip()
                    entity.original['studio'] = val; entity.studio = val
                    entity.original['director'] = val; entity.director = val

                for genre_name in tree.xpath('//section[contains(@class, "items_article_TagArea")]//a'):
                    g = genre_name.text_content().strip()
                    if g:
                        entity.original['genre'] = entity.original.get('genre', []) + [g]
                        entity.genre.append(cls.trans(g))

                # 이미지
                if poster_src := tree.xpath('//div[contains(@class, "items_article_MainitemThumb")]//img/@src | //div[contains(@class, "items_article_MainitemThumb")]//img/@data-src'):
                    raw_image_urls['pl'] = cls._process_fc2_image_url(poster_src[0], base_url=cls.site_base_url, target_size='w1280')

                for href in tree.xpath('//a[@data-fancybox="gallery"]/@href') or tree.xpath('//section[contains(@class, "items_article_SampleImages")]//a/@href'):
                    raw_image_urls['arts'].append(cls._process_fc2_image_url(href, base_url=cls.site_base_url, target_size='w1280'))

                # 예고편
                if cls.config['use_extras']:
                    if video_src := tree.xpath('//video[contains(@id, "sample_video")]/@src'):
                        if url := cls.make_video_url(cls._process_fc2_image_url(video_src[0], base_url=cls.site_base_url, target_size=None)):
                            entity.extras.append(EntityExtra("trailer", entity.tagline, "mp4", url))

        # 2. [DB 조회] Selenium 실패 시
        if not is_data_found:
            db_data = cls._query_javten_db(code_part)
            if db_data:
                logger.info(f"[{cls.site_name}] Info from Javten DB: {code_part}")
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

        # 3. [공통 이미지 처리] (오리지널 확인 + 스마트 크롭)
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

