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

    _info_cache = {}

    @classmethod
    def search(cls, keyword, manual=False):
        try:
            logger.debug(f"[{cls.site_name}] search started. keyword: {keyword}")
            ret = {}
            # 키워드 포맷팅 (111825-100 -> 111825_100)
            formatted_keyword = keyword.strip().replace('-', '_')
            if re.search(r'\d{6}_\d+', formatted_keyword):
                match = re.search(r'(\d{6}_\d+)', formatted_keyword)
                if match: formatted_keyword = match.group(1)
            
            code = formatted_keyword
            url = cls.api_detail_format.format(code)
            logger.debug(f"[{cls.site_name}] API URL: {url}")

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
            item.ui_code = f"PACO-{movie_id}"
            item.score = 100

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
            logger.debug(f"Using cached JSON data for {cls.site_name} code: {code_part}")
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

        # === 이미지 처리 ===
        def format_url(path):
            if path and isinstance(path, str):
                return f"{cls.site_base_url}/{path}" if not path.startswith('http') and not path.startswith('/') else (f"{cls.site_base_url}{path}" if path.startswith('/') else path)
            return None

        def format_gallery_url(path):
            if path and isinstance(path, str):
                if path.startswith('movie_gallery/'):
                    return f"{cls.site_base_url}/dyn/dla/images/{path}"
                else:
                    return format_url(path)
            return None

        main_img_url = format_url(json_data.get('ThumbUltra') or json_data.get('ThumbHigh') or json_data.get('MovieThumb'))
        
        poster_url = None
        try:
            gallery_url = cls.api_gallery_format.format(code_part)
            
            gal_res = cls.get_response(gallery_url)
            if gal_res.status_code == 200:
                gal_data = gal_res.json()
                if gal_data.get('Rows'):
                    for row in gal_data['Rows']:
                        img_path = row.get('Img')
                        if not img_path: continue
                        
                        poster_candidate_url = format_gallery_url(img_path)
                        if cls._is_portrait_image(poster_candidate_url):
                            poster_url = poster_candidate_url
                            logger.debug(f"[{cls.site_name}] Found portrait poster: {poster_url}")
                            break 
        except Exception as e:
            logger.error(f"[{cls.site_name}] Error extracting poster: {e}")

        if not poster_url and main_img_url:
            poster_url = main_img_url

        try:
            raw_image_urls = {
                'poster': poster_url,
                'pl': main_img_url,
                'arts': [main_img_url] if main_img_url else [],
            }
            entity = cls.process_image_data(entity, raw_image_urls, ps_url_from_cache=None)
        except Exception as e:
            logger.exception(f"[{cls.site_name}] Error during image processing delegation for {code}: {e}")

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
                                trailer_url = sample['URL']
                                break
                        if trailer_url: break
                    
                    if not trailer_url:
                        trailer_url = sample_files[-1].get('URL')

                    if trailer_url:
                        video_url = cls.make_video_url(trailer_url)
                        if video_url:
                            entity.extras.append(EntityExtra('trailer', entity.title, 'mp4', video_url))
            except Exception as e:
                logger.error(f"[{cls.site_name}] Trailer processing error: {e}")

        if json_data.get('AvgRating'):
            try:
                entity.ratings.append(EntityRatings(float(json_data['AvgRating']), max=5, name=cls.site_name))
            except: pass

        return entity

    @classmethod
    def _is_portrait_image(cls, url):
        try:
            res = cls.get_response(url, stream=True, timeout=10)
            if res.status_code == 200:
                img = Image.open(BytesIO(res.content))
                width, height = img.size
                img.close()
                return height > width
        except Exception:
            return False
        return False
