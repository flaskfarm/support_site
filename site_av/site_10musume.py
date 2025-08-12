import re
import os
import traceback
from ..entity_av import EntityAVSearch
from ..entity_base import (EntityActor, EntityExtra, EntityMovie,
                           EntityRatings, EntityThumb)
from ..setup import P, logger
from .site_av_base import SiteAvBase

SITE_BASE_URL = 'https://www.10musume.com'

class Site10Musume(SiteAvBase):
    site_name = '10musume'
    site_char = 'M'    
    module_char = 'E'
    default_headers = SiteAvBase.base_default_headers.copy()

    _info_cache = {}

    @classmethod
    def search(cls, keyword, manual=False):
        try:
            ret = {}
            if re.search('(\\d{6}[_-]\\d+)', keyword, re.I) is not None:
                code = re.search('(\\d{6}[_-]\\d+)', keyword, re.I).group().replace('-', '_')
            else:
                return {'ret': 'success', 'data': []}

            url = f'{SITE_BASE_URL}/dyn/phpauto/movie_details/movie_id/{code}.json'
            try:
                response = cls.get_response(url)
                json_data = response.json()
                if json_data:
                    cls._info_cache[code] = json_data
            except:
                return {'ret': 'success', 'data': []}

            ret = {'data' : []}

            item = EntityAVSearch(cls.site_name)
            item.code = cls.module_char + cls.site_char + code
            item.title = item.title_ko = json_data.get('Title', '')
            item.year = json_data.get('Year')

            moviethumb = json_data.get('MovieThumb', '')
            if moviethumb and not moviethumb.startswith('http'):
                moviethumb = f"{SITE_BASE_URL}{moviethumb}"
            item.image_url = moviethumb

            if manual:
                item.title_ko = "(현재 인터페이스에서는 번역을 제공하지 않습니다) " + item.title
                try:
                    if cls.config.get('use_proxy'):
                        item.image_url = cls.make_image_url(item.image_url)
                except Exception as e_img: 
                    logger.error(f"Image processing error in manual search: {e_img}")
            else:
                item.title_ko = item.title

            item.ui_code = f'10mu-{code}'

            if '10mu' in keyword.lower():
                item.score = 100
            elif code.replace('_', '-') in keyword.replace('_', '-'):
                item.score = 95
            else:
                item.score = 90

            logger.debug('score :%s %s ', item.score, item.ui_code)
            ret['data'].append(item.as_dict())
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
                ret["data"] = f"Failed to get 10musume info for {code}"
        except Exception as e:
            ret['ret'] = 'exception'
            ret['data'] = str(e)
            logger.exception(f"10musume info error: {e}")
        return ret


    @classmethod
    def __info(cls, code, fp_meta_mode=False):
        code_part = code[2:]
        json_data = None

        # 1. 캐시에 데이터가 있는지 먼저 확인
        if code_part in cls._info_cache:
            logger.debug(f"Using cached JSON data for 10musume code: {code_part}")
            json_data = cls._info_cache[code_part]
            del cls._info_cache[code_part]
        
        # 2. 캐시에 데이터가 없으면 API를 통해 직접 호출
        if json_data is None:
            logger.debug(f"Cache miss for 10musume code: {code_part}. Calling API.")
            url = f'{SITE_BASE_URL}/dyn/phpauto/movie_details/movie_id/{code_part}.json'
            try:
                json_data = cls.get_response(url).json() or {}
            except Exception:
                json_data = {}

        if not json_data: return None
            
        entity = EntityMovie(cls.site_name, code)
        entity.country = [u'일본']; entity.mpaa = u'청소년 관람불가'

        entity.thumb = []; entity.fanart = []; entity.extras = []; entity.ratings = []
        entity.tag = []; entity.genre = []; entity.actor = []

        entity.ui_code = f'10mu-{code[2:]}'
        entity.title = entity.originaltitle = entity.sorttitle = entity.ui_code.upper()

        entity.premiered = json_data.get('Release')

        try:
            # 1. API의 'Year' 필드를 정수로 변환 시도
            year_from_api = json_data.get('Year')
            if year_from_api:
                entity.year = int(year_from_api)
            else:
                # 2. 'Year' 필드가 없으면 품번에서 추출 시도
                if len(code[2:]) >= 6:
                    entity.year = 2000 + int(code[2:][4:6])
                else:
                    entity.year = 0
        except (ValueError, TypeError, IndexError):
            entity.year = 0

        image_mode = cls.MetadataSetting.get('jav_censored_image_mode')
        if image_mode == 'image_server':
            module_type = 'jav_uncensored'
            local_path = cls.MetadataSetting.get('jav_censored_image_server_local_path')
            server_url = cls.MetadataSetting.get('jav_censored_image_server_url')
            base_save_format = cls.MetadataSetting.get(f'{module_type}_image_server_save_format')

            label = entity.ui_code.split('-')[0].upper()
            year_part = str(entity.year) if entity.year else "0000"

            base_path_part = base_save_format.format(label=label)
            final_relative_folder_path = os.path.join(base_path_part.strip('/\\'), year_part)

            entity.image_server_target_folder = os.path.join(local_path, final_relative_folder_path)
            entity.image_server_url_prefix = f"{server_url.rstrip('/')}/{final_relative_folder_path.replace(os.path.sep, '/')}"

        # 썸네일
        def format_thumb_url(path):
            if not path or not isinstance(path, str): return ""
            return f"{SITE_BASE_URL}{path}" if path.startswith('/') else path

        gallery_data = json_data.get('Gallery', [])
        arts_urls = [format_thumb_url(p) for p in gallery_data] if isinstance(gallery_data, list) else []

        # 썸네일
        try:
            raw_image_urls = {
                'poster': format_thumb_url(json_data.get('MovieThumb')),
                'pl': format_thumb_url(json_data.get('ThumbUltra')),
                'ps': None,
                'arts': [],
                'specific_poster_candidates': []
            }
            entity = cls.process_image_data(entity, raw_image_urls, ps_url_from_cache=None)
        except Exception as e:
            logger.exception(f"10Musume: Error during image processing delegation for {code}: {e}")

        # tagline
        entity.tagline = cls.trans(json_data.get('Title', ''))

        # actor
        actresses = json_data.get('ActressesJa', [])
        if isinstance(actresses, list):
            for actor in actresses:
                entity.actor.append(EntityActor(actor))

        # tag
        entity.tag.append('10Musume')

        # genre
        genrelist = json_data.get('UCNAME', [])
        if isinstance(genrelist, list):
            for item in genrelist:
                entity.genre.append(cls.get_translated_tag('uncen_tags', item))

        # entity.ratings
        try:
            avg_rating = json_data.get('AvgRating')
            if avg_rating is not None:
                entity.ratings.append(EntityRatings(float(avg_rating), name=cls.site_name))
        except (ValueError, TypeError): pass

        # plot
        entity.plot = cls.trans(json_data.get('Desc', ''))

        # 제작사
        entity.studio = '10Musume'

        # 부가영상 or 예고편
        if not fp_meta_mode and cls.config['use_extras']:
            try:
                sample_files = json_data.get('SampleFiles')
                if cls.config.get('use_extras') and isinstance(sample_files, list) and sample_files:
                    thumb_url = next((t.value for t in entity.thumb if t.aspect == 'poster'), '')
                    video_url = cls.make_video_url(sample_files[-1].get('URL'))
                    if video_url:
                        trailer_title = entity.tagline if entity.tagline else entity.title
                        entity.extras.append(EntityExtra('trailer', trailer_title, 'mp4', video_url, thumb=thumb_url))
            except Exception: pass
        elif fp_meta_mode:
            # logger.debug(f"FP Meta Mode: Skipping extras processing for {code}.")
            pass

        return entity
