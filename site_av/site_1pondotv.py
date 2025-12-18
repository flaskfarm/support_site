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
            
            item.image_url = cls._format_url(json_data.get('MovieThumb'))

            if manual:
                item.title_ko = "(현재 인터페이스에서는 번역을 제공하지 않습니다) " + item.title
                try:
                    if cls.config.get('use_proxy') and item.image_url:
                        item.image_url = cls.make_image_url(item.image_url)
                except Exception as e_img:
                    logger.error(f"Image processing error in manual search: {e_img}")
            else:
                item.title_ko = item.title

            item.ui_code = cls._parse_ui_code_uncensored(keyword)
            if not item.ui_code or '1PON' not in item.ui_code.upper():
                item.ui_code = f'1PON-{code}'

            if '1pon' in keyword.lower():
                item.score = 100
            elif manual:
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

        # 1. 메인 정보 캐시 확인 및 호출
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

        # 1. 기본 URL 추출
        movie_thumb_url = cls._format_url(json_data.get('MovieThumb')) 
        landscape_url = cls._format_url(json_data.get('ThumbUltra'))   
        
        # PL(ThumbUltra) URL이 비정상이거나 404일 때를 대비한 Fallback URL 생성
        landscape_fallback_urls = []
        if landscape_url:
            landscape_fallback_urls.append(landscape_url)
            
            # https://www.1pondo.tv/assets/sample/{code}/str.jpg 형태 시도
            if '/moviepages/' in landscape_url:
                alt_url = landscape_url.replace('/moviepages/', '/assets/sample/').replace('/images/', '/')
                landscape_fallback_urls.append(alt_url)

        # PL 검증 및 확정 (유효한 URL 찾기)
        final_landscape_url = None
        for url in landscape_fallback_urls:
            try:
                # 헤더만 체크해서 200 OK인지 확인
                # (requests_cache가 켜져있으면 전체 다운로드될 수 있지만 빠름)
                res = cls.get_response(url, method='HEAD', timeout=3)
                if res and res.status_code == 200:
                    final_landscape_url = url
                    break
            except: pass
        
        # 유효한 게 없으면 원래 URL이라도 씀 (나중에 스마트크롭에서 실패하라고)
        landscape_url = final_landscape_url or landscape_url
        
        # 2. 갤러리 데이터 확보 (API -> Fallback API -> Main JSON)
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

        # API 실패 시 기본 JSON 폴백
        if not gallery_rows:
            fallback_gallery = json_data.get('Gallery')
            if isinstance(fallback_gallery, list):
                gallery_rows = [{'Img': p} for p in fallback_gallery]
                is_fallback_gallery = True

        # 3. 갤러리 이미지 URL 리스트 생성 (Arts 후보)
        arts_urls = []
        for row in gallery_rows:
            if row.get('Protected') is True:
                continue

            full_url = None
            if 'Img' in row:
                img_path = row['Img']
                if is_fallback_gallery or img_path.startswith('http') or img_path.startswith('/'):
                    full_url = cls._format_url(img_path)
                else:
                    if 'movie_gallery' in img_path:
                        full_url = f"{SITE_BASE_URL}/dyn/dla/images/{img_path}"
                    else:
                        full_url = cls._format_url(img_path)
            elif 'Filename' in row:
                filename = row['Filename']
                full_url = f"{SITE_BASE_URL}/assets/sample/{code_part}/popu/{filename}"

            if full_url: arts_urls.append(full_url)

        # 4. 포스터 탐색 로직
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
                    if h > w: # 세로 이미지 발견 시 즉시 채택
                        poster_url = curr_url
                        logger.debug(f"[{cls.site_name}] Found portrait poster in gallery: {poster_url}")
                        break
            except Exception:
                continue

        # 5. 포스터 최종 결정 (스마트 크롭 시도)
        if not poster_url and use_smart:
            # [2단계] PL(ThumbUltra) 스마트 크롭
            if landscape_url:
                try:
                    res_pl = cls.get_response(landscape_url, stream=True, timeout=5)
                    if res_pl and res_pl.status_code == 200:
                        img_pl = Image.open(BytesIO(res_pl.content))
                        cropped = cls._smart_crop_image(img_pl)
                        if cropped:
                            temp_path = cls.save_pil_to_temp(cropped)
                            if temp_path:
                                poster_url = temp_path
                                logger.debug(f"[{cls.site_name}] PL(ThumbUltra) Smart Cropped.")
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


    @classmethod
    def _format_url(cls, path):
        if not path or not isinstance(path, str): return None
        path = path.strip()
        if not path: return None
        
        if path.startswith('https:///'):
            path = path.replace('https:///', '/')
        
        if path.startswith('http'): return path
        if path.startswith('//'): return f"https:{path}"
        
        if path.startswith('/'): 
            return f"{SITE_BASE_URL}{path}"
        
        return f"{SITE_BASE_URL}/{path}"


