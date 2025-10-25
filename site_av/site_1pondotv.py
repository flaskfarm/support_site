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
        entity.original = {}

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

        # 1. URL을 완전한 주소로 만들어주는 헬퍼 함수
        def format_url(path):
            if path and isinstance(path, str):
                return f"{SITE_BASE_URL}{path}" if path.startswith('/') else path
            return None

        # 2. 모든 이미지 URL을 수집하고 완전한 주소로 변환
        poster_url = format_url(json_data.get('MovieThumb'))
        landscape_url = format_url(json_data.get('ThumbUltra'))
        gallery_data = json_data.get('Gallery', [])
        arts_urls = [format_url(p) for p in gallery_data if p] if isinstance(gallery_data, list) else []

        # 3. 포스터 폴백 로직 적용
        if not poster_url and landscape_url:
            logger.debug(f"[{cls.site_name}] Poster image is missing. Using landscape image as a fallback for poster.")
            poster_url = landscape_url

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

        raw_tagline = json_data.get('Title', '')
        original_tagline = cls.A_P(raw_tagline)
        entity.original['tagline'] = original_tagline
        entity.tagline = cls.trans(original_tagline)

        # actor
        actresses = json_data.get('ActressesJa', [])
        if isinstance(actresses, list):
            for actor in actresses:
                entity.actor.append(EntityActor(actor))

        entity.tag.append('1Pondo')

        # genre
        genrelist = json_data.get('UCNAME', [])
        if isinstance(genrelist, list):
            if 'genre' not in entity.original: entity.original['genre'] = []
            for item in genrelist:
                entity.original['genre'].append(item)
                entity.genre.append(cls.get_translated_tag('uncen_tags', item))

        try:
            avg_rating = json_data.get('AvgRating')
            if avg_rating is not None:
                entity.ratings.append(EntityRatings(float(avg_rating), name=cls.site_name))
        except (ValueError, TypeError): pass

        # plot
        raw_plot = json_data.get('Desc', '')
        original_plot = cls.A_P(raw_plot)
        entity.original['plot'] = original_plot
        entity.plot = cls.trans(original_plot)

        # 제작사
        entity.studio = '1Pondo'
        entity.original['studio'] = '1Pondo'

        # 부가영상 or 예고편
        if cls.config.get('use_extras'):
            try:
                sample_files = json_data.get('SampleFiles')
                
                # SampleFiles가 리스트이고, 비어있지 않은지 확인
                if isinstance(sample_files, list) and sample_files:
                    
                    # 해상도를 기준으로 정렬하기 위한 헬퍼 함수
                    def get_resolution(file_info):
                        filename = file_info.get('FileName', '')
                        match = re.search(r'(\d+)p\.mp4', filename)
                        if match:
                            return int(match.group(1))
                        # 해상도를 찾을 수 없으면 파일 크기를 기준으로 하되, 우선순위를 낮춤
                        return file_info.get('FileSize', 0) / 1000000 # 단위를 맞추기 위해 조정

                    # get_resolution 함수의 결과를 기준으로 내림차순 정렬
                    sorted_samples = sorted(sample_files, key=get_resolution, reverse=True)
                    
                    # 가장 첫 번째 요소가 가장 고화질 영상
                    best_quality_video = sorted_samples[0]
                    
                    if best_quality_video and best_quality_video.get('URL'):
                        video_url = cls.make_video_url(best_quality_video['URL'])
                        if video_url:
                            trailer_title = entity.tagline if entity.tagline else entity.title
                            entity.extras.append(EntityExtra('trailer', trailer_title, 'mp4', video_url))
            except Exception as e:
                logger.error(f"[{cls.site_name}] Trailer processing error: {e}")

        return entity
