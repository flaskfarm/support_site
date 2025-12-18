# -*- coding: utf-8 -*-
import requests
import json
import re
from PIL import Image
from io import BytesIO
import os
import traceback

from ..entity_av import EntityAVSearch
from ..entity_base import EntityActor, EntityExtra, EntityMovie, EntityRatings, EntityThumb
from ..setup import P, logger
from .site_av_base import SiteAvBase


class SitePaco(SiteAvBase):
    site_name = "paco"
    site_char = "P"
    module_char = "E"
    site_base_url = "https://www.pacopacomama.com"
    
    default_headers = SiteAvBase.base_default_headers.copy()
    default_headers.update({
        "Referer": site_base_url + "/",
    })

    api_detail_format = "https://www.pacopacomama.com/dyn/phpauto/movie_details/movie_id/{}.json"
    api_gallery_format = "https://www.pacopacomama.com/dyn/dla/json/movie_gallery/{}.json"
    api_gallery_format_fallback = "https://www.pacopacomama.com/dyn/phpauto/movie_galleries/movie_id/{}.json"

    _info_cache = {}


    @classmethod
    def search(cls, keyword, manual=False):
        try:
            ret = {}
            formatted_keyword = keyword.strip().replace('-', '_')
            if re.search(r'\d{6}_\d+', formatted_keyword):
                match = re.search(r'(\d{6}_\d+)', formatted_keyword)
                if match: formatted_keyword = match.group(1)
            
            code = formatted_keyword
            url = cls.api_detail_format.format(code)

            try:
                response = cls.get_response(url)
                if response.status_code == 200:
                    json_data = response.json()
                    if json_data:
                        cls._info_cache[code] = json_data
                else:
                    return {'ret': 'success', 'data': []}
            except Exception:
                return {'ret': 'success', 'data': []}

            ret = {'data' : []}

            item = EntityAVSearch(cls.site_name)
            item.code = cls.module_char + cls.site_char + code
            item.title = json_data.get('Title', '')
            item.year = int(json_data.get('Year')) if json_data.get('Year') else 1900
            
            image_url = json_data.get('ThumbUltra') or json_data.get('MovieThumb')
            if image_url:
                item.image_url = image_url
            
            if json_data.get('Desc'): 
                item.desc = json_data.get('Desc')[:100] + "..."
            
            movie_id = json_data.get('MovieID', code)

            item.ui_code = cls._parse_ui_code_uncensored(keyword)
            if not item.ui_code or 'PACO' not in item.ui_code.upper():
                item.ui_code = f"PACO-{movie_id}"

            if 'paco' in keyword.lower():
                item.score = 100
            elif manual:
                item.score = 100
            else:
                item.score = 90

            if manual:
                item.title_ko = item.title
                try:
                    if cls.config.get('use_proxy') and item.image_url:
                        item.image_url = cls.make_image_url(item.image_url)
                except Exception as e_img:
                    logger.error(f"[{cls.site_name}] Image processing error in manual search: {e_img}")
            else:
                item.title_ko = cls.trans(item.title)

            ret['data'].append(item.as_dict())
            ret['ret'] = 'success'

        except Exception as e:
            logger.error(f"[{cls.site_name}] Exception:{str(e)}")
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
                ret["ret"] = "success"
                ret["data"] = entity_result_val_final
            else:
                ret["ret"] = "error"
                ret["data"] = f"Failed to get {cls.site_name} info for {code}"
        except Exception as e:
            ret["ret"] = "exception"
            ret["data"] = str(e)
            logger.exception(f"[{cls.site_name}] info error: {e}")
        return ret


    @classmethod
    def __info(cls, code, fp_meta_mode=False):
        code_part = code[2:]
        json_data = None

        if code_part in cls._info_cache:
            json_data = cls._info_cache[code_part]
            del cls._info_cache[code_part]

        if json_data is None:
            url = cls.api_detail_format.format(code_part)
            try:
                response = cls.get_response(url)
                if response.status_code == 200:
                    json_data = response.json()
            except Exception: pass

        if not json_data: return None

        entity = EntityMovie(cls.site_name, code)
        entity.country = [u'일본']; entity.mpaa = u'청소년 관람불가'
        
        entity.thumb = []; entity.fanart = []; entity.extras = []; entity.ratings = []
        entity.tag = []; entity.genre = []; entity.actor = []
        entity.original = {}

        movie_id = json_data.get('MovieID', code_part)
        entity.ui_code = f"PACO-{movie_id}"
        entity.title = entity.originaltitle = entity.sorttitle = entity.ui_code.upper()
        
        entity.year = int(json_data.get('Year')) if json_data.get('Year') else 1900
        entity.premiered = json_data.get('Release')
        entity.studio = "pacopacomama"
        entity.director = None
        entity.label = "PACO"

        raw_title = json_data.get('Title', '')
        if raw_title:
            entity.original['tagline'] = cls.A_P(raw_title)
            entity.tagline = cls.trans(entity.original['tagline'])

        if json_data.get('Series'):
            entity.original['series'] = json_data['Series']
            trans_series = cls.trans(json_data['Series'])
            if trans_series not in entity.tag:
                entity.tag.append(trans_series)
        
        if json_data.get('Desc'):
            entity.original['plot'] = json_data['Desc']
            entity.plot = cls.trans(json_data['Desc'])

        if json_data.get('Duration'):
            entity.runtime = int(json_data['Duration']) // 60

        if json_data.get('ActressesJa'):
            entity.actor = [EntityActor(name) for name in json_data['ActressesJa']]

        if json_data.get('UCNAME'):
            for tag in json_data['UCNAME']:
                if tag not in entity.tag: entity.tag.append(tag)
                
                entity.original['genre'] = entity.original.get('genre', [])
                entity.original['genre'].append(tag)
                trans_tag = cls.trans(tag)
                if trans_tag not in entity.genre: entity.genre.append(trans_tag)

        # 이미지 서버 경로 사전 설정
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

        # === 이미지 처리 섹션 ===
        def format_url(path):
            if path and isinstance(path, str):
                return f"{cls.site_base_url}/{path}" if not path.startswith('http') and not path.startswith('/') else (f"{cls.site_base_url}{path}" if path.startswith('/') else path)
            return None

        def format_gallery_url(path, is_fallback=False):
            if path and isinstance(path, str):
                if is_fallback:
                    return f"{cls.site_base_url}/assets/sample/{code_part}/l/{path}"
                else:
                    if path.startswith('movie_gallery/'):
                        return f"{cls.site_base_url}/dyn/dla/images/{path}"
                    else:
                        return format_url(path)
            return None

        # 1. 기본 이미지 URL 설정
        thumb_ultra = format_url(json_data.get('ThumbUltra')) # PL (가로, 고화질)
        movie_thumb = format_url(json_data.get('MovieThumb')) # Fallback Poster (정사각형, 저화질)
        
        # PL은 무조건 ThumbUltra (없으면 MovieThumb)
        landscape_url = thumb_ultra or movie_thumb
        
        # 2. 갤러리 데이터 확보 & URL 리스트 생성
        arts_urls = []
        try:
            gallery_url = cls.api_gallery_format.format(code_part)
            gal_res = cls.get_response(gallery_url)
            is_fallback = False
            gal_data = None

            if gal_res.status_code == 200:
                try: gal_data = gal_res.json()
                except: gal_data = None
            
            if not gal_data or not gal_data.get('Rows'):
                gallery_url = cls.api_gallery_format_fallback.format(code_part)
                gal_res = cls.get_response(gallery_url)
                if gal_res.status_code == 200:
                    try:
                        gal_data = gal_res.json()
                        if gal_data and gal_data.get('Rows'): is_fallback = True
                    except: pass

            if gal_data and gal_data.get('Rows'):
                for row in gal_data['Rows'][:12]: # 최대 12장만 후보로
                    img_path = row.get('Filename') if is_fallback else row.get('Img')
                    if not img_path: continue
                    
                    full_url = format_gallery_url(img_path, is_fallback)
                    if full_url: arts_urls.append(full_url)

        except Exception as e:
            logger.error(f"[{cls.site_name}] Error parsing gallery: {e}")


        # 3. 포스터 탐색 로직
        poster_url = None
        use_smart = cls.config.get('use_smart_crop')

        # [1단계] 갤러리 순회 (세로 이미지 탐색)
        for curr_url in arts_urls:
            try:
                res = cls.get_response(curr_url, stream=True, timeout=3)
                if not res or res.status_code != 200: continue
                
                img_bytes = BytesIO(res.content)
                with Image.open(img_bytes) as img:
                    w, h = img.size
                    if h > w: # 세로 이미지 발견
                        poster_url = curr_url
                        logger.debug(f"[{cls.site_name}] Found portrait poster in gallery: {poster_url}")
                        break
            except Exception:
                continue

        # 4. 포스터 최종 결정 (스마트 크롭 시도)
        if not poster_url and use_smart:
            logger.debug(f"[{cls.site_name}] No portrait poster found. Trying Smart Crop...")

            # [2단계] PL(ThumbUltra) 스마트 크롭
            if thumb_ultra:
                try:
                    res_pl = cls.get_response(thumb_ultra, stream=True, timeout=5)
                    if res_pl and res_pl.status_code == 200:
                        img_pl = Image.open(BytesIO(res_pl.content))
                        logger.debug(f"[{cls.site_name}] Smart Crop ON. Checking PL: {thumb_ultra}")

                        # 검증+크롭 동시 수행
                        cropped = cls._smart_crop_image(img_pl)
                        if cropped:
                            temp_path = cls.save_pil_to_temp(cropped)
                            if temp_path:
                                poster_url = temp_path
                                logger.debug(f"[{cls.site_name}] PL(ThumbUltra) Smart Cropped.")
                        else:
                            logger.debug(f"[{cls.site_name}] PL(ThumbUltra) ignored (Smart Crop failed).")
                    else:
                        logger.warning(f"[{cls.site_name}] Failed to download PL image: {thumb_ultra}")
                except Exception as e:
                    logger.error(f"[{cls.site_name}] PL Smart Crop Error: {e}")

            # [3단계] 갤러리 스마트 크롭 (PL 실패 시)
            if not poster_url:
                for curr_url in arts_urls:
                    try:
                        res = cls.get_response(curr_url, stream=True, timeout=5)
                        if not res or res.status_code != 200: continue
                        
                        img = Image.open(BytesIO(res.content))
                        cropped = cls._smart_crop_image(img)
                        if cropped:
                            temp_path = cls.save_pil_to_temp(cropped)
                            if temp_path:
                                poster_url = temp_path
                                logger.debug(f"[{cls.site_name}] Gallery Smart Cropped: {curr_url}")
                                break
                    except Exception:
                        continue

        # [4단계] Fallback (최후의 수단)
        if not poster_url:
            # MovieThumb(정사각형) > ThumbUltra(가로)
            poster_url = movie_thumb or thumb_ultra
            logger.debug(f"[{cls.site_name}] Fallback to MovieThumb/PL.")

        try:
            raw_image_urls = {
                'poster': poster_url,
                'pl': landscape_url,
                'arts': arts_urls,
            }

            entity = cls.process_image_data(entity, raw_image_urls, ps_url_from_cache=None)
        except Exception as e:
            logger.exception(f"[{cls.site_name}] Error during image processing delegation: {e}")

        # === 트레일러 처리 ===
        if cls.config.get('use_extras') and json_data.get('SampleFiles'):
            try:
                sample_files = json_data.get('SampleFiles')
                if isinstance(sample_files, list) and sample_files:
                    target_resolutions = ['1080p.mp4', '720p.mp4', '480p.mp4']
                    trailer_url = None
                    for res in target_resolutions:
                        for sample in sample_files:
                            if sample.get('URL', '').endswith(res):
                                trailer_url = sample['URL']; break
                        if trailer_url: break
                    if not trailer_url: trailer_url = sample_files[-1].get('URL')
                    if trailer_url:
                        video_url = cls.make_video_url(trailer_url)
                        if video_url: entity.extras.append(EntityExtra('trailer', entity.title, 'mp4', video_url))
            except Exception as e:
                logger.error(f"[{cls.site_name}] Trailer processing error: {e}")

        if json_data.get('AvgRating'):
            try: entity.ratings.append(EntityRatings(float(json_data['AvgRating']), max=5, name=cls.site_name))
            except: pass

        return entity

