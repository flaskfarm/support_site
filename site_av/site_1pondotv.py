import re
import os
import traceback
from io import BytesIO
from PIL import Image

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

        # 1. 메인 정보(details) 캐시 확인 및 호출
        if code_part in cls._info_cache:
            json_data = cls._info_cache[code_part]
            del cls._info_cache[code_part]

        if json_data is None:
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
        entity.label = "1PON" 

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

        # === 이미지 처리 섹션 ===
        def format_url(path):
            if not path or not isinstance(path, str): return None
            if path.startswith('http'): return path
            if path.startswith('/'): return f"{SITE_BASE_URL}{path}"
            return f"{SITE_BASE_URL}/{path}"

        # 1. 기본 URL 추출
        movie_thumb_url = format_url(json_data.get('MovieThumb')) 
        landscape_url = format_url(json_data.get('ThumbUltra'))   
        
        # 2. 갤러리 데이터 확보
        gallery_rows = []
        is_fallback_gallery = False

        gallery_api_urls = [
            f'{SITE_BASE_URL}/dyn/dla/json/movie_gallery/{code_part}.json',        # 신형
            f'{SITE_BASE_URL}/dyn/phpauto/movie_galleries/movie_id/{code_part}.json' # 구형
        ]

        for gal_api_url in gallery_api_urls:
            try:
                gal_res = cls.get_response(gal_api_url)
                if gal_res and gal_res.status_code == 200:
                    gal_json = gal_res.json()
                    if gal_json and 'Rows' in gal_json:
                        gallery_rows = gal_json['Rows']
                        break
            except Exception:
                pass

        if not gallery_rows:
            fallback_gallery = json_data.get('Gallery')
            if isinstance(fallback_gallery, list):
                gallery_rows = [{'Img': p} for p in fallback_gallery]
                is_fallback_gallery = True

        # 3. 갤러리 이미지 URL 리스트 생성 (Arts 후보)
        arts_urls = []
        for row in gallery_rows:
            if row.get('Protected') is True: continue

            full_url = None
            if 'Img' in row:
                img_path = row['Img']
                if is_fallback_gallery:
                    full_url = format_url(img_path)
                else:
                    full_url = f"{SITE_BASE_URL}/dyn/dla/images/{img_path}"
            elif 'Filename' in row:
                filename = row['Filename']
                full_url = f"{SITE_BASE_URL}/assets/sample/{code_part}/popu/{filename}"

            if full_url: arts_urls.append(full_url)


        # 4. 포스터 탐색 로직
        poster_url = None
        candidate_face_url = None
        candidate_body_url = None
        
        use_smart = cls.config.get('use_smart_crop')
        use_yolo = cls.config.get('use_yolo_crop')

        # 갤러리 이미지 순회 (세로 탐색 & 후보군 확보)
        for idx, curr_url in enumerate(arts_urls[:12]):
            if poster_url: break

            try:
                res = cls.get_response(curr_url, stream=True, timeout=3)
                if not res or res.status_code != 200: continue
                
                img_bytes = BytesIO(res.content)
                with Image.open(img_bytes) as img:
                    w, h = img.size
                    
                    # [Priority 1] 세로 이미지 발견 (즉시 채택)
                    if h > w:
                        poster_url = curr_url
                        logger.debug(f"[{cls.site_name}] Found portrait poster in gallery: {poster_url}")
                        break
                    
                    # 갤러리 스마트 크롭 후보군 확보
                    if use_smart:
                        if candidate_face_url is None and cls.check_face_detection(img):
                            candidate_face_url = curr_url
                            continue 
                        
                        if use_yolo and candidate_face_url is None and candidate_body_url is None and cls.check_body_detection(img):
                            candidate_body_url = curr_url
            except Exception:
                continue

        # 5. 포스터 최종 결정
        if not poster_url:
            # [Priority 2] PL(ThumbUltra) 스마트 크롭
            if use_smart and landscape_url:
                try:
                    res_pl = cls.get_response(landscape_url, stream=True, timeout=5)
                    if res_pl and res_pl.status_code == 200:
                        img_pl = Image.open(BytesIO(res_pl.content))
                        if cls.check_face_detection(img_pl) or (use_yolo and cls.check_body_detection(img_pl)):
                            poster_url = landscape_url
                            logger.debug(f"[{cls.site_name}] PL(ThumbUltra) used for Smart Crop (Target detected).")
                except Exception:
                    pass

            # [Priority 3] 갤러리 스마트 크롭 후보
            if not poster_url:
                if candidate_face_url:
                    poster_url = candidate_face_url
                    logger.debug(f"[{cls.site_name}] Selected Face candidate from gallery.")
                elif candidate_body_url:
                    poster_url = candidate_body_url
                    logger.debug(f"[{cls.site_name}] Selected Body candidate from gallery.")

            # [Priority 4] 최후의 수단 (MovieThumb or PL)
            if not poster_url:
                poster_url = movie_thumb_url or landscape_url
                logger.debug(f"[{cls.site_name}] Fallback to MovieThumb/PL.")


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

        # 6. 이미지 처리 위임
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
                if isinstance(sample_files, list) and sample_files:
                    def get_resolution(file_info):
                        filename = file_info.get('FileName', '')
                        match = re.search(r'(\d+)p\.mp4', filename)
                        if match: return int(match.group(1))
                        return file_info.get('FileSize', 0) / 1000000 

                    sorted_samples = sorted(sample_files, key=get_resolution, reverse=True)
                    best_quality_video = sorted_samples[0]
                    
                    if best_quality_video and best_quality_video.get('URL'):
                        video_url = cls.make_video_url(best_quality_video['URL'])
                        if video_url:
                            trailer_title = entity.tagline if entity.tagline else entity.title
                            entity.extras.append(EntityExtra('trailer', trailer_title, 'mp4', video_url))
            except Exception as e:
                logger.error(f"[{cls.site_name}] Trailer processing error: {e}")

        return entity
