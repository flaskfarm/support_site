import re
import os
import traceback
from ..entity_av import EntityAVSearch
from ..entity_base import (EntityActor, EntityExtra, EntityMovie, EntityRatings, EntityThumb)
from ..setup import P, logger
from .site_av_base import SiteAvBase

SITE_BASE_URL = 'https://www.1pondo.tv'

class Site1PondoTv(SiteAvBase):
    site_name = '1pondo'
    site_char = 'D'
    module_char = 'E'
    default_headers = SiteAvBase.base_default_headers.copy()

    _info_cache = {}

    @classmethod
    def search(cls, keyword, manual=False):
        try:
            ret = {}
            # 품번 형식(010123_001)을 먼저 찾음
            code_match = re.search(r'(\d{6}[_-]\d+)', keyword, re.I)
            if code_match:
                code = code_match.group(1).replace('-', '_')
            else:
                return {'ret': 'success', 'data': []}

            url = f'{SITE_BASE_URL}/dyn/phpauto/movie_details/movie_id/{code}.json'

            try:
                response = cls.get_response(url)
                json_data = response.json()
                if json_data:
                    cls._info_cache[code] = json_data
            except Exception:
                return {'ret': 'success', 'data': []}

            ret = {'data' : []}

            item = EntityAVSearch(cls.site_name)
            item.code = cls.module_char + cls.site_char + code
            item.title = item.title_ko = json_data.get('Title', '')
            item.year = json_data.get('Year')
            item.image_url = json_data.get('MovieThumb')

            if manual:
                item.title_ko = "(현재 인터페이스에서는 번역을 제공하지 않습니다) " + item.title
                try:
                    if cls.config.get('use_proxy'):
                        item.image_url = cls.make_image_url(item.image_url)
                except Exception as e_img:
                    logger.error(f"Image processing error in manual search: {e_img}")
            else:
                item.title_ko = item.title

            item.ui_code = cls._parse_ui_code_uncensored(keyword)
            if not item.ui_code: # 파싱 실패 시 폴백
                item.ui_code = f'1PON-{code}'

            if '1pon' in keyword.lower():
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
                ret["data"] = f"Failed to get 1pondo info for {code}"
        except Exception as e:
            ret['ret'] = 'exception'
            ret['data'] = str(e)
            logger.exception(f"1pondo info error: {e}")
        return ret


    @classmethod
    def __info(cls, code, fp_meta_mode=False):
        code_part = code[2:]
        json_data = None

        # 1. 캐시에 데이터가 있는지 먼저 확인
        if code_part in cls._info_cache:
            logger.debug(f"Using cached JSON data for 1pondo code: {code_part}")
            json_data = cls._info_cache[code_part]
            del cls._info_cache[code_part] # 한 번 사용한 캐시는 메모리 관리를 위해 삭제

        # 2. 캐시에 데이터가 없으면 API를 통해 직접 호출
        if json_data is None:
            logger.debug(f"Cache miss for 1pondo code: {code_part}. Calling API.")
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

        entity.ui_code = cls._parse_ui_code_uncensored(f'1pon-{code_part}')
        if not entity.ui_code: entity.ui_code = f'1pon-{code_part}'

        entity.title = entity.originaltitle = entity.sorttitle = entity.ui_code.upper()
        entity.label = "1PON" # 이미지 서버 경로 포맷팅을 위해

        entity.premiered = json_data.get('Release')

        try:
            year_from_api = json_data.get('Year')
            if year_from_api:
                entity.year = int(year_from_api)
            else:
                if len(code[2:]) >= 6:
                    entity.year = 2000 + int(code[2:][4:6])
                else:
                    entity.year = 0
        except (ValueError, TypeError, IndexError):
            entity.year = 0

        gallery_data = json_data.get('Gallery')
        arts_urls = []
        if isinstance(gallery_data, list):
            arts_urls = [f"{SITE_BASE_URL}{p}" for p in gallery_data if p and isinstance(p, str) and p.startswith('/')]

        poster_url = json_data.get('MovieThumb')
        landscape_url = json_data.get('ThumbUltra')

        if not fp_meta_mode:
            # [일반 모드] : 전체 이미지 처리 파이프라인 실행
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
                    'arts': arts_urls,
                }
                entity = cls.process_image_data(entity, raw_image_urls, ps_url_from_cache=None)
            except Exception as e:
                logger.exception(f"[{cls.site_name}] Error during image processing delegation for {code}: {e}")
        else:
            # [파일처리 모드] : 원본 URL만 추가하고 무거운 처리는 생략
            logger.debug(f"[{cls.site_name}] FP Meta Mode: Skipping full image processing for {code}.")
            if poster_url:
                entity.thumb.append(EntityThumb(aspect="poster", value=poster_url))
            if landscape_url:
                entity.thumb.append(EntityThumb(aspect="landscape", value=landscape_url))
            entity.fanart = arts_urls

        raw_tagline = json_data.get('Title', '')
        entity.tagline = cls.trans(cls.A_P(raw_tagline))

        # actor
        actresses = json_data.get('ActressesJa', [])
        if isinstance(actresses, list):
            for actor in actresses:
                entity.actor.append(EntityActor(actor))

        entity.tag.append('1Pondo')

        # genre
        genrelist = json_data.get('UCNAME', [])
        if isinstance(genrelist, list):
            for item in genrelist:
                entity.genre.append(cls.get_translated_tag('uncen_tags', item)) # 미리 번역된 태그를 포함

        try:
            avg_rating = json_data.get('AvgRating')
            if avg_rating is not None:
                entity.ratings.append(EntityRatings(float(avg_rating), name=cls.site_name))
        except (ValueError, TypeError): pass

        # plot
        raw_plot = json_data.get('Desc', '')
        entity.plot = cls.trans(cls.A_P(raw_plot))

        # 제작사
        entity.studio = '1Pondo'

        # 부가영상 or 예고편
        if not fp_meta_mode and cls.config.get('use_extras'):
            try:
                sample_files = json_data.get('SampleFiles')
                if isinstance(sample_files, list) and sample_files:
                    video_url_data = next((f for f in sample_files if f.get('FileSize') and f.get('URL')), None)
                    if video_url_data:
                        video_url = cls.make_video_url(video_url_data['URL'])
                        if video_url:
                            trailer_title = entity.tagline if entity.tagline else entity.title
                            entity.extras.append(EntityExtra('trailer', trailer_title, 'mp4', video_url))
            except Exception as e:
                logger.error(f"[{cls.site_name}] Trailer processing error: {e}")

        return entity
