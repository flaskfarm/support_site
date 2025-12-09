import re
import os
import traceback
from io import BytesIO
from PIL import Image
from lxml import html
from ..entity_av import EntityAVSearch
from ..entity_base import (EntityActor, EntityExtra, EntityMovie, EntityRatings, EntityThumb)
from ..setup import P, logger
from .site_av_base import SiteAvBase

SITE_BASE_URL = 'https://www.caribbeancom.com'

class SiteCarib(SiteAvBase):
    site_name = 'carib'
    site_char = 'C'    
    module_char = 'E'
    default_headers = SiteAvBase.base_default_headers.copy()

    _info_cache = {}

    @classmethod
    def search(cls, keyword, manual=False):
        try:
            ret = {}
            match = re.search(r'(\d{6}-\d{3})', keyword, re.I)
            if not match:
                return {'ret': 'success', 'data': []}

            code = match.group(1)

            url = f'{SITE_BASE_URL}/moviepages/{code}/index.html'
            res = cls.get_response(url)
            if res.status_code != 200:
                return {'ret': 'success', 'data': []}

            html_text = res.text
            if html_text:
                cls._info_cache[code] = html_text

            tree = html.fromstring(html_text)

            item = EntityAVSearch(cls.site_name)
            item.code = cls.module_char + cls.site_char + code

            item.ui_code = cls._parse_ui_code_uncensored(keyword)
            if not item.ui_code: # 파싱 실패 시 폴백
                item.ui_code = f'CARIB-{code}'

            title_node = tree.xpath('//div[@id="moviepages"]//h1[@itemprop="name"]/text()')
            item.title = title_node[0].strip() if title_node else ""

            item.image_url = f'https://www.caribbeancom.com/moviepages/{code}/images/l_l.jpg'
            if manual:
                item.title_ko = item.title
                item.image_url = cls.make_image_url(item.image_url)
            else:
                item.title_ko = cls.trans(item.title)

            try: 
                item.year = int("20" + code[4:6])
            except (ValueError, IndexError): 
                item.year = 0

            item.score = 100

            ret['data'] = [item.as_dict()]
            ret['ret'] = 'success'

        except Exception as e: 
            logger.error(f"Exception:{str(e)}")
            logger.error(traceback.format_exc())
            ret['ret'] = 'exception'
            ret['data'] = str(e)
        return ret


    @classmethod
    def info(cls, code, fp_meta_mode=False):
        ret = {}
        entity_result_val_final = None
        try:
            entity_result_val_final = cls.__info(code, fp_meta_mode=fp_meta_mode).as_dict()
            if entity_result_val_final:
                ret['ret'] = 'success'
                ret['data'] = entity_result_val_final
            else:
                ret['ret'] = 'error'
                ret["data"] = f"Failed to get carib info for {code}"
        except Exception as e:
            ret['ret'] = 'exception'
            ret['data'] = str(e)
            logger.exception(f"carib info error: {e}")
        return ret


    @classmethod
    def __info(cls, code, fp_meta_mode=False):
        code_part = code[2:]
        tree = None

        # 1. 캐시 확인
        if code_part in cls._info_cache:
            logger.debug(f"Using cached HTML data for carib code: {code_part}")
            html_text = cls._info_cache[code_part]
            tree = html.fromstring(html_text)
            del cls._info_cache[code_part]
        
        # 2. 캐시 없으면 네트워크 호출
        if tree is None:
            logger.debug(f"Cache miss for carib code: {code_part}. Calling API.")
            url = f'{SITE_BASE_URL}/moviepages/{code_part}/index.html'
            tree = cls.get_tree(url)

        if tree is None: return None

        entity = EntityMovie(cls.site_name, code)

        entity.country = [u'일본']; entity.mpaa = u'청소년 관람불가'
        entity.thumb = []; entity.fanart = []; entity.extras = []; entity.ratings = []
        entity.tag = []; entity.genre = []; entity.actor = []
        entity.original = {}

        # ui_code 및 title 설정
        entity.ui_code = cls._parse_ui_code_uncensored(f'carib-{code_part}')
        if not entity.ui_code: entity.ui_code = f'carib-{code_part}'
        
        entity.title = entity.originaltitle = entity.sorttitle = entity.ui_code.upper()
        entity.label = "CARIB"

        try:
            entity.year = int("20" + code_part[4:6])
            entity.premiered = f"{entity.year}-{code_part[0:2]}-{code_part[2:4]}"
        except (ValueError, IndexError): 
            entity.year = 0
            entity.premiered = None

        # === 이미지 처리 섹션 ===
        poster_url = None
        landscape_url = f'https://www.caribbeancom.com/moviepages/{code_part}/images/l_l.jpg'
        jacket_url = f'https://www.caribbeancom.com/moviepages/{code_part}/images/jacket.jpg'

        # 1. 갤러리 이미지 URL 추출 (Arts 후보)
        # HTML 구조: div.gallery > div.grid > div.gallery-ratio > a.gallery-item[href="..."][data-is_sample="1"]
        arts_urls = []
        gallery_nodes = tree.xpath('//div[contains(@class, "gallery")]//a[contains(@class, "gallery-item")]')
        for node in gallery_nodes:
            is_sample = node.get('data-is_sample')
            href = node.get('href')
            
            # 샘플(무료공개)이고 href가 유효한 경우만
            if is_sample == '1' and href and not href.startswith('javascript'):
                full_url = f"{SITE_BASE_URL}{href}" if href.startswith('/') else href
                arts_urls.append(full_url)

        # 2. 포스터 결정 로직
        
        # [1순위] Jacket 이미지 (가장 확실한 세로 포스터)
        try:
            res_jacket = cls.get_response(jacket_url)
            if res_jacket and res_jacket.status_code == 200:
                poster_url = jacket_url
                logger.debug(f"[{cls.site_name}] Found Jacket image: {poster_url}")
        except Exception as e:
            logger.warning(f"[{cls.site_name}] Failed to check jacket.jpg: {e}")

        # [2순위] 갤러리 세로 이미지 (Jacket 없을 시)
        if not poster_url:
            for curr_url in arts_urls[:12]:
                try:
                    res = cls.get_response(curr_url, stream=True, timeout=3)
                    if not res or res.status_code != 200: continue
                    
                    img_bytes = BytesIO(res.content)
                    with Image.open(img_bytes) as img:
                        w, h = img.size
                        if h > w:
                            poster_url = curr_url
                            logger.debug(f"[{cls.site_name}] Found portrait poster in gallery: {poster_url}")
                            break
                except Exception:
                    continue

        # [3순위] PL (Jacket도 갤러리 세로도 없을 시)
        if not poster_url:
            poster_url = landscape_url
            logger.debug(f"[{cls.site_name}] Fallback to PL(l_l.jpg).")

        # 이미지 서버 경로 설정
        image_mode = cls.MetadataSetting.get('jav_censored_image_mode')
        if image_mode == 'image_server':
            try:
                local_path = cls.MetadataSetting.get('jav_censored_image_server_local_path')
                server_url = cls.MetadataSetting.get('jav_censored_image_server_url')
                base_save_format = cls.MetadataSetting.get('jav_uncensored_image_server_save_format')
                base_path_part = base_save_format.format(label=entity.label)
                year_part = str(entity.year) if entity.year else "0000"
                final_relative_folder_path = os.path.join(base_path_part.strip('/\\'), year_part)
                entity.image_server_target_folder = os.path.join(local_path, final_relative_folder_path)
                entity.image_server_url_prefix = f"{server_url.rstrip('/')}/{final_relative_folder_path.replace(os.path.sep, '/')}"
            except Exception as e:
                logger.error(f"[{cls.site_name}] Failed to set custom image server path: {e}")

        try:
            raw_image_urls = {
                'poster': poster_url,
                'pl': landscape_url,
                'arts': arts_urls
            }
            # process_image_data 내부에서 poster_url이 가로형(PL)이면 자동으로 크롭 수행
            entity = cls.process_image_data(entity, raw_image_urls, ps_url_from_cache=None)
        except Exception as e:
            logger.exception(f"[{cls.site_name}] Error during image processing delegation for {code}: {e}")

        # 나머지 메타데이터 파싱
        title_node = tree.xpath('//div[@id="moviepages"]//h1[@itemprop="name"]/text()')
        if title_node:
            cleaned_tagline = cls.A_P(title_node[0].strip())
            entity.original['tagline'] = cleaned_tagline
            entity.tagline = cls.trans(cleaned_tagline)

        for actor in tree.xpath('//div[@class="movie-info section"]//li[@class="movie-spec"]//span[@itemprop="name"]/text()'):
            entity.actor.append(EntityActor(actor))

        entity.tag.append('carib')

        genre_nodes = tree.xpath('//li[@class="movie-spec"]//span[@class="spec-content"]/a[@class="spec-item"]/text()')
        if 'genre' not in entity.original: entity.original['genre'] = []
        for item in genre_nodes:
            entity.original['genre'].append(item)
            entity.genre.append(cls.get_translated_tag('uncen_tags', item))

        plot_node = tree.xpath('//p[@itemprop="description"]/text()')
        if plot_node:
            cleaned_plot = cls.A_P(plot_node[0])
            entity.original['plot'] = cleaned_plot
            entity.plot = cls.trans(cleaned_plot)

        entity.studio = 'Caribbeancom'
        entity.original['studio'] = 'Caribbeancom'

        # 부가영상 or 예고편
        if cls.config.get('use_extras'):
            try:
                video_url = cls.make_video_url(f'https://smovie.caribbeancom.com/sample/movies/{code_part}/480p.mp4')
                if video_url:
                    trailer_title = entity.tagline if entity.tagline else entity.title
                    entity.extras.append(EntityExtra('trailer', trailer_title, 'mp4', video_url))
            except Exception as e:
                logger.error(f"[{cls.site_name}] Trailer processing error: {e}")

        return entity
