import json
import os
import re
import time
from datetime import timedelta
from io import BytesIO
from urllib.parse import urlparse, quote_plus
import traceback
try:
    import cloudscraper
except ImportError:
    os.system("pip install cloudscraper")
    import cloudscraper
try:
    import imagehash
except ImportError:
    os.system("pip install imagehash")
    import imagehash
try:
    import requests_cache
except ImportError:
    os.system("pip install requests-cache")
    import requests_cache

import requests
from lxml import html
from PIL import Image

from tool import ToolUtil
from .setup import P, logger, path_data, F
from .cache_util import CacheUtil
from .constants import (AV_GENRE, AV_GENRE_IGNORE_JA, AV_GENRE_IGNORE_KO,
                        AV_STUDIO, COUNTRY_CODE_TRANSLATE, GENRE_MAP)
from .tool_discord import DiscordUtil
from .entity_base import EntityActor, EntityThumb
from .trans_util import TransUtil


class SiteUtilAv:
    if F.config['run_celery'] == False:
        try:
            from requests_cache import CachedSession

            session = CachedSession(
                P.package_name,
                use_temp=True,
                expire_after=timedelta(hours=6),
            )
            # logger.debug("requests_cache.CachedSession initialized successfully.")
        except Exception as e:
            logger.debug("requests cache 사용 안함: %s", e)
            session = requests.Session()
    else:
        # 2025.07.12
        # Celery 환경에서는 requests_cache를 사용하지 않음.
        session = requests.Session()


    default_headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/93.0.4577.82 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8",
        "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
        # 'Cookie' : 'over18=1;age_check_done=1;',
    }

    av_genre = AV_GENRE
    av_genre_ignore_ja = AV_GENRE_IGNORE_JA
    av_genre_ignore_ko = AV_GENRE_IGNORE_KO
    av_studio = AV_STUDIO
    country_code_translate = COUNTRY_CODE_TRANSLATE
    genre_map = GENRE_MAP

    PTN_SPECIAL_CHAR = re.compile(r"[-=+,#/\?:^$.@*\"※~&%ㆍ!』\\‘|\(\)\[\]\<\>`'…》]")
    PTN_HANGUL_CHAR = re.compile(r"[ㄱ-ㅣ가-힣]+")


    _cs_scraper_instance = None # cloudscraper 인스턴스 캐싱용 (선택적)

    @classmethod
    def get_cloudscraper_instance(cls, new_instance=False):
        # 간단한 싱글톤 또는 캐시된 인스턴스 반환 (매번 생성 방지)
        # browser={'browser': 'chrome', 'platform': 'windows', 'mobile': False} 등 User-Agent 설정 가능
        # delay: 요청 사이 지연시간 (초) - 너무 자주 요청 시 차단 방지
        if new_instance or cls._cs_scraper_instance is None:
            try:
                # User-Agent는 default_headers의 것을 활용하거나, cloudscraper 기본값 사용
                # browser_kwargs = {'custom': cls.default_headers['User-Agent']} if 'User-Agent' in cls.default_headers else {}
                cls._cs_scraper_instance = cloudscraper.create_scraper(
                    # browser=browser_kwargs, # 필요시 User-Agent 지정
                    delay=5 # 예시: 요청 간 5초 지연 (너무 짧으면 차단될 수 있음, 적절히 조절)
                )
                # logger.debug("Created new cloudscraper instance.")
            except Exception as e_cs_create:
                logger.error(f"Failed to create cloudscraper instance: {e_cs_create}")
                return None # 생성 실패 시 None 반환
        return cls._cs_scraper_instance

    @classmethod
    def get_response_cs(cls, url, **kwargs):
        """cloudscraper를 사용하여 HTTP GET 요청을 보내고 응답 객체를 반환합니다."""
        method = kwargs.pop("method", "GET").upper()
        proxy_url = kwargs.pop("proxy_url", None)
        cookies = kwargs.pop("cookies", None)
        headers = kwargs.pop("headers", cls.default_headers.copy())

        scraper = cls.get_cloudscraper_instance()
        if scraper is None:
            logger.error("SiteUtil.get_response_cs: Failed to get cloudscraper instance.")
            return None

        current_proxies = None
        if proxy_url:
            current_proxies = {"http": proxy_url, "https": proxy_url}
            scraper.proxies.update(current_proxies)

        # logger.debug(f"SiteUtil.get_response_cs: Making {method} request to URL='{url}'")
        if headers: scraper.headers.update(headers)

        try:
            if method == "POST":
                post_data = kwargs.pop("post_data", None)
                res = scraper.post(url, data=post_data, cookies=cookies, **kwargs)
            else: # GET
                res = scraper.get(url, cookies=cookies, **kwargs)

            if res.status_code == 429:
                return res

            if res.status_code != 200:
                logger.warning(f"SiteUtil.get_response_cs: Received status code {res.status_code} for URL='{url}'. Proxy='{proxy_url}'.")
                if res.status_code == 403:
                    logger.error(f"SiteUtil.get_response_cs: Received 403 Forbidden for URL='{url}'. Proxy='{proxy_url}'. Response text: {res.text[:500]}")
                return None #

            return res
        except cloudscraper.exceptions.CloudflareChallengeError as e_cf_challenge:
            logger.error(f"SiteUtil.get_response_cs: Cloudflare challenge error for URL='{url}'. Error: {e_cf_challenge}")
            return None
        except requests.exceptions.RequestException as e_req:
            logger.error(f"SiteUtil.get_response_cs: RequestException (not related to status code) for URL='{url}'. Proxy='{proxy_url}'. Error: {e_req}")
            logger.error(traceback.format_exc())
            return None
        except Exception as e_general:
            logger.error(f"SiteUtil.get_response_cs: General Exception for URL='{url}'. Proxy='{proxy_url}'. Error: {e_general}")
            logger.error(traceback.format_exc())
            return None


    

    # 파일명에 indx 포함. 0 우, 1 좌
    @classmethod
    def get_mgs_half_pl_poster_info_local(cls, ps_url: str, pl_url: str, proxy_url: str = None, do_save:bool = True):
        """
        MGStage용으로 pl 이미지를 특별 처리합니다. (로컬 임시 파일 사용)
        pl 이미지를 가로로 반으로 자르고 (오른쪽 우선), 각 절반의 중앙 부분을 ps와 비교합니다.
        is_hq_poster 검사 성공 시에만 해당 결과를 사용하고,
        모든 검사 실패 시에는 None, None, None을 반환합니다.
        """
        try:
            # logger.debug(f"MGS Special Local: Trying get_mgs_half_pl_poster_info_local for ps='{ps_url}', pl='{pl_url}'")
            if not ps_url or not pl_url: return None, None, None

            ps_image = cls.imopen(ps_url, proxy_url=proxy_url)
            pl_image_original = cls.imopen(pl_url, proxy_url=proxy_url)

            if ps_image is None or pl_image_original is None:
                # logger.debug("MGS Special Local: Failed to open ps_image or pl_image_original.")
                return None, None, None

            pl_width, pl_height = pl_image_original.size
            if pl_width < pl_height * 1.1: # 가로가 세로의 1.1배보다 작으면 충분히 넓지 않다고 판단
                # logger.debug(f"MGS Special Local: pl_image_original not wide enough ({pl_width}x{pl_height}). Skipping.")
                return None, None, None

            # 처리 순서 정의: 오른쪽 먼저
            candidate_sources = []
            # 오른쪽 절반
            right_half_box = (pl_width / 2, 0, pl_width, pl_height)
            right_half_img_obj = pl_image_original.crop(right_half_box)
            if right_half_img_obj: candidate_sources.append( (right_half_img_obj, f"{pl_url} (right_half)") )
            # 왼쪽 절반
            left_half_box = (0, 0, pl_width / 2, pl_height)
            left_half_img_obj = pl_image_original.crop(left_half_box)
            if left_half_img_obj: candidate_sources.append( (left_half_img_obj, f"{pl_url} (left_half)") )

            idx = 0
            for img_obj_to_crop, obj_name in candidate_sources:
                # logger.debug(f"MGS Special Local: Processing candidate source: {obj_name}")
                # 중앙 크롭 시도
                with img_obj_to_crop:
                    with cls.imcrop(img_obj_to_crop, position='c') as center_cropped_candidate_obj:

                        if center_cropped_candidate_obj:
                            # logger.debug(f"MGS Special Local: Successfully cropped center from {obj_name}.")

                            # is_hq_poster 유사도 검사 시도
                            # logger.debug(f"MGS Special Local: Comparing ps_image with cropped candidate from {obj_name}")
                            is_similar = cls.is_hq_poster(
                                ps_image, 
                                center_cropped_candidate_obj, 
                                sm_source_info=ps_url, 
                                lg_source_info=obj_name
                            )

                            if is_similar:
                                logger.debug(f"MGS Special Local: Similarity check PASSED for {obj_name}. This is the best match.")
                                # 성공! 이 객체를 저장하고 반환
                                img_format = center_cropped_candidate_obj.format if center_cropped_candidate_obj.format else "JPEG"
                                ext = img_format.lower().replace("jpeg", "jpg")
                                if ext not in ['jpg', 'png', 'webp']: ext = 'jpg'
                                temp_filename = f"mgs_temp_poster_{int(time.time())}_{os.urandom(4).hex()}_{idx}.{ext}"
                                temp_filepath = os.path.join(path_data, "tmp", temp_filename)
                                if do_save == False:
                                    center_cropped_candidate_obj.close()
                                    return temp_filepath, None, pl_url

                                try:
                                    
                                    os.makedirs(os.path.join(path_data, "tmp"), exist_ok=True)
                                    save_params = {}
                                    if ext in ['jpg', 'webp']: save_params['quality'] = 95
                                    elif ext == 'png': save_params['optimize'] = True

                                    # JPEG 저장 시 RGB 변환 필요할 수 있음
                                    img_to_save = center_cropped_candidate_obj
                                    if ext == 'jpg' and img_to_save.mode not in ('RGB', 'L'):
                                        img_to_save = img_to_save.convert('RGB')

                                    img_to_save.save(temp_filepath, **save_params)
                                    logger.debug(f"MGS Special Local: Saved similarity match to temp file: {temp_filepath}")
                                    return temp_filepath, None, pl_url # 성공 반환 (파일경로, crop=None, 원본pl)
                                except Exception as e_save_hq:
                                    logger.exception(f"MGS Special Local: Failed to save HQ similarity match from {obj_name}: {e_save_hq}")

                            else: # is_hq_poster 검사 실패
                                logger.debug(f"MGS Special Local: Similarity check FAILED for {obj_name}.")
                        else: # 크롭 자체 실패
                            logger.debug(f"MGS Special Local: Failed to crop center from {obj_name}.")
                idx += 1
            
            logger.debug("MGS Special Local: All similarity checks failed. No suitable poster found.")
            return None, None, None # 최종적으로 실패 반환

        except Exception as e:
            logger.exception(f"MGS Special Local: Error in get_mgs_half_pl_poster_info_local: {e}")
            return None, None, None


    @classmethod
    def is_portrait_high_quality_image(cls, image_url, proxy_url=None, min_height=600, aspect_ratio_threshold=1.2):
        """
        주어진 이미지 URL 또는 파일 경로가 세로형 고화질 이미지인지 판단합니다.
        SiteUtil.imopen을 사용하여 PIL Image 객체를 가져옵니다.
        - 높이가 min_height 이상
        - 세로/가로 비율이 aspect_ratio_threshold 이상
        """
        if not image_url:
            logger.debug("is_portrait_high_quality_image: No image_url/path provided.")
            return False

        img_pil_object = None
        try:
            img_pil_object = cls.imopen(image_url, proxy_url=proxy_url) 

            if img_pil_object is None:
                logger.debug(f"is_portrait_high_quality_image: SiteUtil.imopen returned None for '{image_url}'")
                return False

            width, height = img_pil_object.size
            
            actual_ratio = 0
            if width > 0:
                actual_ratio = height / width

            if height >= min_height and actual_ratio >= aspect_ratio_threshold:
                # logger.debug(f"Image '{image_url}' IS portrait high quality (W: {width}, H: {height}, Ratio: {actual_ratio:.2f}). Criteria: H>={min_height}, Ratio>={aspect_ratio_threshold}")
                return True
            else:
                #logger.debug(f"Image '{image_url}' is NOT portrait high quality (W: {width}, H: {height}, Ratio: {actual_ratio:.2f}). Criteria: H>={min_height}, Ratio>={aspect_ratio_threshold}")
                return False

        except Exception as e: 
            logger.debug(f"is_portrait_high_quality_image: Unexpected error processing image '{image_url}': {e}")
            # logger.error(traceback.format_exc()) # 상세 오류 로깅
            return False
        finally:
            if img_pil_object and not isinstance(image_url, Image.Image): 
                try:
                    img_pil_object.close() 
                except Exception as e_close:
                    logger.debug(f"is_portrait_high_quality_image: Error closing PIL image object for '{image_url}': {e_close}")


    @classmethod
    def get_javdb_poster_from_pl_local(cls, pl_url: str, original_code_for_log: str = "unknown", proxy_url: str = None):
        """
        JavDB용으로 PL 이미지를 특별 처리하여 포스터로 사용할 임시 파일 경로와 추천 crop_mode를 반환합니다.
        - PL 이미지의 aspect ratio를 확인합니다.
        - 1.8 이상 (가로로 매우 김): 오른쪽 절반을 잘라 임시 파일로 저장하고, 추천 crop_mode는 'c' (센터).
        - 1.8 미만 (일반 가로): 이 경우에는 이미지 처리를 하지 않고, 원본 URL과 crop 'r'을 반환합니다.
        - 성공 시 (임시 파일 경로 또는 원본 URL, 추천 crop_mode, 원본 PL URL), 실패 시 (None, None, None) 반환.
        """
        try:
            # logger.debug(f"JavDB Poster Util: Trying get_javdb_poster_from_pl_local for pl_url='{pl_url}', code='{original_code_for_log}'")
            if not pl_url:
                return None, None, None

            pl_image_original = cls.imopen(pl_url, proxy_url=proxy_url)
            if pl_image_original is None:
                logger.debug(f"JavDB Poster Util: Failed to open pl_image_original from '{pl_url}'.")
                return None, None, None
            
            pl_width, pl_height = pl_image_original.size
            aspect_ratio = pl_width / pl_height if pl_height > 0 else 0
            # logger.debug(f"JavDB Poster Util: PL aspect_ratio={aspect_ratio:.2f} ({pl_width}x{pl_height})")

            if aspect_ratio >= 1.8: # 가로로 매우 긴 이미지만 처리
                logger.debug(f"JavDB Poster Util: PL is very wide (ratio {aspect_ratio:.2f}). Processing right-half.")
                right_half_box = (pl_width / 2, 0, pl_width, pl_height)
                try:
                    right_half_img_obj = pl_image_original.crop(right_half_box)
                    if right_half_img_obj:
                        # 임시 파일로 저장
                        img_format = right_half_img_obj.format if right_half_img_obj.format else pl_image_original.format
                        if not img_format: img_format = "JPEG"
                        ext = img_format.lower().replace("jpeg", "jpg")
                        if ext not in ['jpg', 'png', 'webp']: ext = 'jpg'
                        
                        temp_filename = f"javdb_temp_poster_{int(time.time())}_{os.urandom(4).hex()}.{ext}"
                        temp_filepath = os.path.join(path_data, "tmp", temp_filename)
                        os.makedirs(os.path.join(path_data, "tmp"), exist_ok=True)
                        
                        save_params = {}
                        if ext in ['jpg', 'webp']: save_params['quality'] = 95
                        elif ext == 'png': save_params['optimize'] = True

                        img_to_save = right_half_img_obj
                        if ext == 'jpg' and img_to_save.mode not in ('RGB', 'L'):
                            img_to_save = img_to_save.convert('RGB')
                        
                        img_to_save.save(temp_filepath, **save_params)
                        logger.debug(f"JavDB Poster Util: Saved processed image to temp file: {temp_filepath}")
                        
                        pl_image_original.close() # 원본 이미지 닫기
                        right_half_img_obj.close() # 잘라낸 이미지 닫기
                        
                        return temp_filepath, 'c', pl_url # 임시 파일 경로, 추천 크롭 'c', 원본 pl_url 반환
                    else:
                        logger.debug("JavDB Poster Util: Cropping right-half returned None. Using original PL.")
                except Exception as e_process:
                    logger.error(f"JavDB Poster Util: Error processing/saving wide image: {e_process}. Using original PL.")
            
            # 1.8 미만 비율 또는 처리 실패 시, PIL 객체를 닫고 원본 URL 반환
            pl_image_original.close()
            return pl_url, 'r', pl_url

        except Exception as e:
            logger.exception(f"JavDB Poster Util: Error in get_javdb_poster_from_pl_local: {e}")
            if 'pl_image_original' in locals() and pl_image_original:
                pl_image_original.close()
            return None, None, None


    

    

    @classmethod
    def resolve_jav_imgs(cls, img_urls: dict, ps_to_poster: bool = False, proxy_url: str = None, crop_mode: str = None):
        ps = img_urls["ps"]  # poster small
        pl = img_urls["pl"]  # poster large
        arts = img_urls["arts"]  # arts

        # poster 기본값
        poster = ps if ps_to_poster else ""
        poster_crop = None

        if not poster and arts:
            if cls.is_hq_poster(ps, arts[0], proxy_url=proxy_url):
                # first art to poster
                poster = arts[0]
            elif len(arts) > 1 and cls.is_hq_poster(ps, arts[-1], proxy_url=proxy_url):
                # last art to poster
                poster = arts[-1]
        if not poster and pl:
            if cls.is_hq_poster(ps, pl, proxy_url=proxy_url):
                # pl이 세로로 큰 이미지
                poster = pl
            elif crop_mode is not None:
                # 사용자 설정에 따름
                poster, poster_crop = pl, crop_mode
            else:
                loc = cls.has_hq_poster(ps, pl, proxy_url=proxy_url)
                if loc:
                    # pl의 일부를 crop해서 포스터로...
                    poster, poster_crop = pl, loc
        if not poster:
            # 그래도 없으면...
            poster = ps

        # # first art to landscape
        # if arts and not pl:
        #     pl = arts.pop(0)

        img_urls.update(
            {
                "poster": poster,
                "poster_crop": poster_crop,
                "landscape": pl,
            }
        )

    
    
    @classmethod
    def process_image_mode(cls, image_mode, image_source, proxy_url=None, crop_mode=None):
        if image_source is None:
            return

        log_name = image_source
        if isinstance(image_source, str) and os.path.exists(image_source):
            log_name = f"localfile:{os.path.basename(image_source)}"
        
        if image_mode == "original": 
            return image_source

        # SJVA 프록시(ff_proxy, discord_redirect)가 로컬 파일을 처리할 수 없으므로,
        # 로컬 파일인 경우 mode 3(discord_proxy)으로 강제 전환
        is_local_file = isinstance(image_source, str) and os.path.exists(image_source)
        
        effective_image_mode = image_mode
        if is_local_file and image_mode in ["ff_proxy", "discord_redirect"]:
            logger.debug(f"Local file '{log_name}' cannot be used with mode '{image_mode}'. Switching to 'discord_proxy' (mode 3).")
            effective_image_mode = "discord_proxy"

        if effective_image_mode in ["ff_proxy", "discord_redirect"]:
            # 이제 이 코드는 URL일 때만 실행됨
            if not isinstance(image_source, str): # PIL 객체 등은 처리 불가
                return image_source
            api_path = "image_proxy" if effective_image_mode == "ff_proxy" else "discord_proxy"
            tmp = f"{F.SystemModelSetting.get('ddns')}/metadata/normal/{api_path}?url=" + quote_plus(image_source)
            if proxy_url: tmp += "&proxy_url=" + quote_plus(proxy_url)
            if crop_mode: tmp += "&crop_mode=" + quote_plus(crop_mode)
            return tmp

        if effective_image_mode == "discord_proxy":
            discord_kwargs = {}
            if proxy_url: discord_kwargs['proxy_url'] = proxy_url
            if crop_mode: discord_kwargs['crop_mode'] = crop_mode
            
            if not isinstance(image_source, (str, Image.Image)): # PIL 객체도 처리 가능하도록
                logger.error(f"process_image_mode (discord_proxy): image_source is not a URL/filepath/PIL object. Type: {type(image_source)}")
                return None
            
            # discord_proxy_image는 URL, 로컬 파일 경로, PIL 객체를 모두 처리
            return cls.discord_proxy_image(image_source, **discord_kwargs)

        if image_mode == "image_server":
            # 1. image_source (URL)로 이미지 열기
            im_opened = cls.imopen(image_source, proxy_url=proxy_url)
            if im_opened is None: return image_source

            # 2. (선택적) 크롭 적용
            #    만약 crop_mode를 여기서 적용하려면:
            #    if crop_mode:
            #        cropped = cls.imcrop(im_opened, position=crop_mode)
            #        if cropped: im_opened = cropped
            
            # 3. 임시 파일로 저장
            #    파일 이름에 crop_mode 정보를 포함시키는 것이 좋음 (만약 여기서 크롭했다면)
            temp_filename_mode_image_server = f"proxy_mode_image_server_{os.path.basename(image_source if isinstance(image_source, str) else 'img')}_{time.time()}.jpg"
            if crop_mode: temp_filename_mode_image_server = f"proxy_mode_image_server_crop{crop_mode}_{os.path.basename(image_source if isinstance(image_source, str) else 'img')}_{time.time()}.jpg"

            temp_filepath_mode_image_server = os.path.join(path_data, "tmp", temp_filename_mode_image_server)
            try:
                save_format = im_opened.format if im_opened.format else "JPEG"
                # JPEG 저장 시 RGB 변환 필요할 수 있음
                img_to_save_mode_image_server = im_opened
                if save_format == 'JPEG' and img_to_save_mode_image_server.mode not in ('RGB', 'L'):
                    img_to_save_mode_image_server = img_to_save_mode_image_server.convert('RGB')

                img_to_save_mode_image_server.save(temp_filepath_mode_image_server, format=save_format, quality=95)
                return cls.discord_proxy_image_localfile(temp_filepath_mode_image_server)
            except Exception as e_save5:
                logger.exception(f"process_image_mode: Mode 5 failed to save/proxy image from '{log_name}': {e_save5}")
                return image_source

        #logger.debug(f"process_image_mode: No specific action for mode '{image_mode}'. Returning original source: {image_source}")
        return image_source


    @classmethod
    def save_image_to_server_path(cls, image_source, image_type: str, base_path: str, path_segment: str, ui_code: str, art_index: int = None, proxy_url: str = None, crop_mode: str = None):
        # 1. 필수 인자 유효성 검사 (image_source는 PIL 객체일 수도 있으므로 all() 검사에서 제외 후 타입 체크)
        if not all([image_type, base_path, path_segment, ui_code]): # image_source는 아래에서 별도 체크
            logger.warning("save_image_to_server_path: 기본 필수 인자 누락.")
            return None
        if not image_source: # image_source가 None이나 빈 문자열 등 Falsy 값일 때
            logger.warning("save_image_to_server_path: image_source가 유효하지 않습니다.")
            return None
        # image_type 유효성 검사는 유지 (ps, pl, p, art)
        # ps: poster small (javdb에서 사용), p: poster (일반)
        if image_type not in ['ps', 'pl', 'p', 'art']:
            logger.warning(f"save_image_to_server_path: 유효하지 않은 image_type: {image_type}")
            return None
        if image_type == 'art' and art_index is None: # art_index는 1부터 시작한다고 가정
            logger.debug("save_image_to_server_path: image_type='art'일 때 art_index 필요.")
            return None

        im_opened_original = None # 원본으로 열리거나 전달된 이미지
        log_source_info = ""

        # source_is_pil_object = isinstance(image_source, Image.Image)
        # source_is_local_file = not source_is_pil_object and isinstance(image_source, str) and os.path.exists(image_source)
        # source_is_url = not source_is_pil_object and not source_is_local_file and isinstance(image_source, str)

        # 2. 입력 소스 타입 판별 및 이미지 로드
        if isinstance(image_source, Image.Image): # 이미 PIL Image 객체로 전달된 경우
            im_opened_original = image_source
            log_source_info = "PIL Image Object"
        elif isinstance(image_source, str) and os.path.exists(image_source): # 로컬 파일 경로인 경우
            im_opened_original = cls.imopen(image_source) # SiteUtil.imopen 사용 가정
            log_source_info = f"localfile:{os.path.basename(image_source)}"
        elif isinstance(image_source, str): # URL 문자열인 경우
            im_opened_original = cls.imopen(image_source, proxy_url=proxy_url) # SiteUtil.imopen 사용 가정
            log_source_info = image_source
        else:
            logger.warning(f"save_image_to_server_path: 지원하지 않는 image_source 타입: {type(image_source)}.")
            return None

        if im_opened_original is None:
            logger.warning(f"save_image_to_server_path: 이미지 열기/로드 실패: {log_source_info}")
            return None

        try:
            # 3. 실제 처리 대상 이미지 준비 (초기에는 원본과 동일)
            im_to_process = im_opened_original

            # 4. 레터박스 제거 (image_type='p' 또는 'ps' 이고 crop_mode가 있을 때, 4:3 비율이면 시도)
            # 원본 코드에서는 image_type == 'p' 조건만 있었으나, 'ps'도 포스터이므로 포함 고려. 여기서는 원본 유지.
            if image_type == 'p' and crop_mode:
                try:
                    wl_orig, hl_orig = im_to_process.size # 현재 처리 대상 이미지의 크기
                    if hl_orig > 0:
                        aspect_ratio_orig = wl_orig / hl_orig
                        if 1.30 <= aspect_ratio_orig <= 1.36: # 4:3 비율 근처
                            top_crop_ratio = 0.0555
                            bottom_crop_ratio = 0.0555
                            top_pixels = int(hl_orig * top_crop_ratio)
                            bottom_y_coord = hl_orig - int(hl_orig * bottom_crop_ratio)

                            if top_pixels < bottom_y_coord and top_pixels >= 0 and bottom_y_coord <= hl_orig:
                                box_for_lb_removal = (0, top_pixels, wl_orig, bottom_y_coord)
                                im_no_lb = im_to_process.crop(box_for_lb_removal) # 현재 im_to_process에서 crop
                                if im_no_lb:
                                    im_to_process = im_no_lb 
                                    wl_new, hl_new = im_to_process.size
                                    logger.debug(f"save_image_to_server_path: Letterbox removed from '{log_source_info}'. Original: {wl_orig}x{hl_orig}, Now: {wl_new}x{hl_new}")
                        #        else:
                        #            logger.warning(f"save_image_to_server_path: Failed to crop letterbox from '{log_source_info}'.")
                        #    else:
                        #        logger.debug(f"save_image_to_server_path: Invalid letterbox crop pixels for '{log_source_info}'.")
                        #else:
                        #    logger.debug(f"save_image_to_server_path: Image '{log_source_info}' ratio ({aspect_ratio_orig:.2f}) not in 4:3 range. No letterbox removal.")
                except Exception as e_letterbox:
                    logger.error(f"save_image_to_server_path: Error during letterbox removal for '{log_source_info}': {e_letterbox}")

            # 5. 최종 크롭 적용 (image_type='p' 또는 'ps' 이고 crop_mode가 있을 때)
            if image_type == 'p' and crop_mode:
                logger.debug(f"save_image_to_server_path: Applying final crop_mode '{crop_mode}' to image for {log_source_info}")
                cropped_im_final = cls.imcrop(im_to_process, position=crop_mode) # SiteUtil.imcrop 사용 가정
                if cropped_im_final is None:
                    logger.error(f"save_image_to_server_path: 최종 크롭 실패 (crop_mode: {crop_mode}) for {log_source_info}")
                    return None 
                im_to_process = cropped_im_final

            # --- 이미지 확장자 결정 ---
            current_format_for_ext = None
            if im_to_process.format: 
                current_format_for_ext = im_to_process.format
            elif im_opened_original.format: 
                current_format_for_ext = im_opened_original.format

            if not current_format_for_ext: 
                if isinstance(image_source, str) and (image_source.startswith('http://') or image_source.startswith('https://')): # source_is_url 대신 직접 체크
                    ext_match = re.search(r'\.(jpg|jpeg|png|webp|gif)(\?|$)', image_source.lower()) 
                    if ext_match: current_format_for_ext = ext_match.group(1).upper()
                elif isinstance(image_source, str) and os.path.exists(image_source):
                    _, file_ext_val = os.path.splitext(image_source) 
                    if file_ext_val: current_format_for_ext = file_ext_val[1:].upper()
                if not current_format_for_ext: current_format_for_ext = "JPEG" # 기본 JPEG

            ext = current_format_for_ext.lower().replace("jpeg", "jpg")
            allowed_exts = ['jpg', 'png', 'webp']

            if ext not in allowed_exts: # 지원하지 않는 확장자는 jpg로 강제 변환 시도 또는 에러
                logger.warning(f"save_image_to_server_path: Original image format '{ext}' from '{log_source_info}' is not in allowed_exts. Attempting to save as JPG.")
                ext = 'jpg' # 기본 저장 포맷 JPG

            # --- 파일명 및 폴더 경로 결정 ---
            # path_segment: 'jav/cen', 'jav/uncen', 'jav/fc2' 등
            # base_path: 로컬 이미지 서버의 최상위 실제 경로 (예: /data/imgserver)

            # 기본 파일명 (확장자 제외)
            filename_base = ui_code.lower() # 예: fc2-6686531 또는 ssni-001

            # 이미지 타입에 따른 접미사
            if image_type == 'art':
                filename_with_suffix = f"{filename_base}_art_{art_index}"
            else: # 'p', 'ps', 'pl'
                filename_with_suffix = f"{filename_base}_{image_type}"

            filename = f"{filename_with_suffix}.{ext}" # 최종 파일명 (확장자 포함)

            # 폴더 구조 생성
            # save_dir: 이미지가 실제 저장될 전체 로컬 경로 (base_path 포함)
            # relative_dir_parts: 웹 접근 시 base_path를 제외한 상대 경로 부분 리스트

            relative_dir_parts = [path_segment] # 예: ['jav/fc2'] 또는 ['jav/cen']

            if path_segment == 'jav/fc2': # FC2 전용 경로 규칙
                # logger.debug(f"FC2 이미지 저장 경로 규칙 적용. ui_code: {ui_code}")
                match_fc2_id = re.search(r'(?:FC2-)?(\d+)', ui_code, re.I) # FC2- 접두사 있거나 없거나, 숫자 부분 추출
                if match_fc2_id:
                    num_id_str = match_fc2_id.group(1)
                    # logger.debug(f"FC2 숫자 ID 추출: {num_id_str}")

                    if len(num_id_str) > 4:
                        prefix_num_str = num_id_str[:-4]
                        sub_folder_name = prefix_num_str.zfill(3)
                        # logger.debug(f"FC2 ID > 4자리: 앞부분 '{prefix_num_str}', 패딩 후 폴더명 '{sub_folder_name}'")
                    elif len(num_id_str) > 0: # 1~4자리 ID
                        sub_folder_name = "000"
                        # logger.debug(f"FC2 ID <= 4자리: 폴더명 '000'")
                    else: # 숫자 ID가 비어있는 경우 (이론상 발생 어려움)
                        sub_folder_name = "_error_no_fc2_numid" # 에러 상황 명시
                        logger.warning(f"FC2 숫자 ID가 비어있습니다: {num_id_str}. 폴더명: {sub_folder_name}")
                else: # FC2- 다음 숫자가 없는 경우 (예외 케이스)
                    sub_folder_name = "_error_fc2_id_format" # 에러 상황 명시
                    logger.warning(f"FC2 UI 코드에서 숫자 ID를 찾을 수 없습니다: {ui_code}. 폴더명: {sub_folder_name}")
                relative_dir_parts.append(sub_folder_name)
            else: # FC2가 아닌 다른 path_segment의 경우
                ui_code_parts = ui_code.split('-')
                label_part_original_case = ui_code_parts[0] if ui_code_parts else ui_code
                label_part_input = label_part_original_case.upper() # 원본 label_part (대문자), 예: "12ID", "SSNI", "007MIRD", "741MOM"

                first_char_of_label_folder = ""
                label_part_for_folder = "" # 최종적으로 사용될 레이블 폴더명

                if label_part_input.startswith("741"):
                    # "741"로 시작하는 경우: 첫 글자 폴더는 '09', 레이블 폴더는 원본 레이블 그대로
                    first_char_of_label_folder = '09'
                    label_part_for_folder = label_part_input
                    logger.debug(f"save_image_to_server_path: Label '{label_part_input}' starts with '741'. Using '09/{label_part_input}'.")
                else:
                    # "741"로 시작하지 않는 경우: 앞의 숫자 제거 후 알파벳 첫 글자 기준
                    # 예: "007MIRD" -> "MIRD", "12ID" -> "ID", "SSNI" -> "SSNI"
                    match_leading_digits = re.match(r'^(\d*)([a-zA-Z].*)$', label_part_input)
                    if match_leading_digits:
                        # 그룹1: 앞의 숫자 (007, 12, 또는 없음)
                        # 그룹2: 알파벳으로 시작하는 나머지 부분 (MIRD, ID, SSNI)
                        label_after_stripping_digits = match_leading_digits.group(2)
                        label_part_for_folder = label_after_stripping_digits # 예: "MIRD", "ID", "SSNI"

                        if label_part_for_folder and label_part_for_folder[0].isalpha():
                            first_char_of_label_folder = label_part_for_folder[0].upper()
                        else: # 숫자 제거 후에도 알파벳으로 시작하지 않거나 비어있는 극히 예외적인 경우
                            first_char_of_label_folder = 'ETC'
                            logger.warning(f"save_image_to_server_path: Label '{label_part_input}' after stripping digits resulted in '{label_part_for_folder}'. Using 'ETC'.")
                        # logger.debug(f"save_image_to_server_path: Label '{label_part_input}' (not starting with '741'). Stripped to '{label_part_for_folder}'. Using '{first_char_of_label_folder}/{label_part_for_folder}'.")

                    else:
                        # 알파벳으로 시작하는 부분을 찾지 못한 경우 (예: 레이블 전체가 숫자이거나, 특수문자로 시작 등)
                        # 또는 label_part_input이 비어있는 경우
                        if label_part_input and label_part_input[0].isdigit():
                            first_char_of_label_folder = '09' # 숫자로 시작하면 '09'
                        elif label_part_input and label_part_input[0].isalpha(): # 이미 알파벳으로 시작하는 경우 (위 match_leading_digits에서 걸렸어야 하지만, 폴백)
                            first_char_of_label_folder = label_part_input[0].upper()
                        else: # 비어있거나 기타 특수문자
                            first_char_of_label_folder = 'ETC'
                        label_part_for_folder = label_part_input # 원본 레이블 사용
                        # logger.warning(f"save_image_to_server_path: Label '{label_part_input}' (not starting with '741') did not match leading digits pattern. Using '{first_char_of_label_folder}/{label_part_for_folder}'.")


                # 폴더 경로 리스트에 추가
                if first_char_of_label_folder: # 비어있지 않은 경우에만 추가
                    relative_dir_parts.append(first_char_of_label_folder)
                if label_part_for_folder: # 비어있지 않은 경우에만 추가
                    relative_dir_parts.append(label_part_for_folder)
                
                # 만약 위에서 first_char_of_label_folder나 label_part_for_folder가 설정되지 않는 극단적인 경우,
                # relative_dir_parts에 아무것도 추가되지 않을 수 있음. 이에 대한 대비 필요 (예: 기본 폴더 'UNKNOWN')
                if not first_char_of_label_folder and not label_part_for_folder and label_part_input:
                    # 둘 다 비었는데 원본 레이블 입력이 있었다면, 원본 레이블 기준으로 폴더 생성 시도
                    logger.warning(f"save_image_to_server_path: Could not determine first_char or label_folder for '{label_part_input}'. Using 'UNKNOWN/{label_part_input}' as fallback.")
                    relative_dir_parts.append("UNKNOWN")
                    relative_dir_parts.append(label_part_input if label_part_input else "UNKNOWN_LABEL")


            # 최종 저장될 로컬 디렉토리 경로
            save_dir = os.path.join(base_path, *relative_dir_parts)
            # 최종 저장될 로컬 파일 전체 경로
            save_filepath = os.path.join(save_dir, filename)

            os.makedirs(save_dir, exist_ok=True)

            # 7. 이미지 저장 (im_to_process 사용)
            # logger.debug(f"Saving final image (format: {ext}) to {save_filepath} (will overwrite if exists).")
            save_options = {}
            if ext == 'jpg': save_options['quality'] = 95
            elif ext == 'webp': save_options.update({'quality': 95, 'lossless': False}) 
            elif ext == 'png': save_options['optimize'] = True

            try:
                # 저장 전 이미지 모드 변환 (필요시)
                im_to_save_final = im_to_process # 최종 저장할 이미지 객체
                if ext == 'jpg' and im_to_process.mode not in ('RGB', 'L'):
                    # logger.debug(f"Converting final image mode from {im_to_process.mode} to RGB for JPG saving.")
                    im_to_save_final = im_to_process.convert('RGB')
                elif ext == 'png' and im_to_process.mode == 'P': 
                    # logger.debug(f"Converting final PNG image mode from P to RGBA/RGB for saving.")
                    im_to_save_final = im_to_process.convert('RGBA' if 'transparency' in im_to_process.info else 'RGB')

                im_to_save_final.save(save_filepath, **save_options)
            except OSError as e_os_save_final: # 디스크 공간 부족, 권한 문제 등
                logger.warning(f"save_image_to_server_path: OSError on final save ({save_filepath}): {str(e_os_save_final)}. Check permissions/disk space.")
                return None # 저장 실패
            except Exception as e_main_save_final: # 기타 PIL 저장 관련 예외
                logger.exception(f"save_image_to_server_path: Main final image save failed for {save_filepath}: {e_main_save_final}")
                return None # 저장 실패

            # 8. 성공 시 상대 경로 반환 (웹 접근용)
            # relative_dir_parts는 base_path를 제외한 부분이므로, 파일명만 추가하면 됨
            relative_web_path = os.path.join(*relative_dir_parts, filename).replace("\\", "/") # OS에 따라 \를 /로 변경
            logger.debug(f"save_image_to_server_path: 저장 성공: {relative_web_path}")
            return relative_web_path

        except Exception as e_outer: 
            logger.exception(f"save_image_to_server_path: 전체 처리 중 예외 발생 ({log_source_info}): {e_outer}")
            return None
        finally: # PIL Image 객체는 사용 후 닫아주는 것이 좋음 (메모리 관리)
            if im_opened_original:
                try:
                    im_opened_original.close()
                except Exception: pass # 이미 닫혔거나 다른 문제로 실패해도 무시
            if im_to_process and im_to_process is not im_opened_original: # im_to_process가 다른 객체인 경우
                try:
                    im_to_process.close()
                except Exception: pass


    @classmethod
    def _check_and_apply_user_images(cls, entity, settings):
        """[내부헬퍼] 사용자 지정 이미지가 있는지 확인하고, 있다면 entity.thumb에 추가."""
        skip_poster = False
        skip_landscape = False
        
        if not (settings.get('use_image_server') and settings.get('ui_code')):
            return skip_poster, skip_landscape

        base_path = settings.get('image_server_local_path')
        segment = settings.get('image_path_segment')
        ui_code = settings.get('ui_code')
        server_url = settings.get('image_server_url')

        # 포스터 확인
        for suffix in ["_p_user.jpg", "_p_user.png", "_p_user.webp"]:
            _, web_url = cls.get_user_custom_image_paths(base_path, segment, ui_code, suffix, server_url)
            if web_url:
                if not any(t.aspect == 'poster' for t in entity.thumb):
                    entity.thumb.append(EntityThumb(aspect="poster", value=web_url))
                skip_poster = True
                logger.debug(f"[ImageUtil] Found user custom poster: {web_url}")
                break
        
        # 풍경(landscape) 확인
        for suffix in ["_pl_user.jpg", "_pl_user.png", "_pl_user.webp"]:
            _, web_url = cls.get_user_custom_image_paths(base_path, segment, ui_code, suffix, server_url)
            if web_url:
                if not any(t.aspect == 'landscape' for t in entity.thumb):
                    entity.thumb.append(EntityThumb(aspect="landscape", value=web_url))
                skip_landscape = True
                logger.debug(f"[ImageUtil] Found user custom landscape: {web_url}")
                break
        
        return skip_poster, skip_landscape


    @classmethod
    def finalize_images_for_entity(cls, entity, image_sources, settings):
        """
        최종 결정된 이미지 소스를 받아, 설정에 따라 처리 후 entity에 추가하는 통합 함수.
        이 함수는 '어떤' 이미지를 쓸지 결정하지 않고, '어떻게' 처리할지만 담당한다.

        :param entity: 메타데이터 EntityMovie 객체
        :param image_sources: {'poster_source':..., 'poster_crop':..., 'landscape_source':..., 'arts':...} 형식의 딕셔너리
        :param settings: {'image_mode':..., 'proxy_url':..., 'use_image_server':..., 등} 형식의 딕셔너리
        """
        # 1. 사용자 지정 이미지 우선 확인 및 적용
        skip_poster, skip_landscape = cls._check_and_apply_user_images(entity, settings)

        # 2. 인자에서 소스 및 설정값 추출
        poster_source = image_sources.get('poster_source')
        poster_crop = image_sources.get('poster_crop')
        landscape_source = image_sources.get('landscape_source')
        final_art_urls = image_sources.get('arts', [])

        image_mode = settings.get('image_mode', 'original')
        proxy_url = settings.get('proxy_url')
        use_image_server = settings.get('use_image_server', False)

        # 3. 이미지 모드에 따라 이미지 처리 및 entity에 추가
        if use_image_server and image_mode == 'image_server':
            # 이미지 서버 저장 로직
            base_path = settings.get('image_server_local_path')
            segment = settings.get('image_path_segment')
            ui_code = settings.get('ui_code')
            server_url = settings.get('image_server_url')
            
            if not all([base_path, segment, ui_code, server_url]):
                logger.error("[ImageUtil] 이미지 서버 설정이 불완전하여 저장을 건너뜁니다.")
                return

            if poster_source and not skip_poster:
                p_path = cls.save_image_to_server_path(poster_source, 'p', base_path, segment, ui_code, proxy_url=proxy_url, crop_mode=poster_crop)
                if p_path and not any(t.aspect == 'poster' for t in entity.thumb):
                    entity.thumb.append(EntityThumb(aspect="poster", value=f"{server_url}/{p_path}"))
            
            if landscape_source and not skip_landscape:
                pl_path = cls.save_image_to_server_path(landscape_source, 'pl', base_path, segment, ui_code, proxy_url=proxy_url)
                if pl_path and not any(t.aspect == 'landscape' for t in entity.thumb):
                    entity.thumb.append(EntityThumb(aspect="landscape", value=f"{server_url}/{pl_path}"))

            for idx, art_url in enumerate(final_art_urls):
                art_path = cls.save_image_to_server_path(art_url, 'art', base_path, segment, ui_code, art_index=idx + 1, proxy_url=proxy_url)
                if art_path: entity.fanart.append(f"{server_url}/{art_path}")
        
        else:
            # 일반 URL 처리 로직 (프록시 등)
            if poster_source and not skip_poster:
                processed_poster = cls.process_image_mode(image_mode, poster_source, proxy_url=proxy_url, crop_mode=poster_crop)
                if processed_poster and not any(t.aspect == 'poster' for t in entity.thumb):
                    entity.thumb.append(EntityThumb(aspect="poster", value=processed_poster))

            if landscape_source and not skip_landscape:
                processed_landscape = cls.process_image_mode(image_mode, landscape_source, proxy_url=proxy_url)
                if processed_landscape and not any(t.aspect == 'landscape' for t in entity.thumb):
                    entity.thumb.append(EntityThumb(aspect="landscape", value=processed_landscape))

            for art_url in final_art_urls:
                processed_art = cls.process_image_mode(image_mode, art_url, proxy_url=proxy_url)
                if processed_art: entity.fanart.append(processed_art)

        logger.info(f"[ImageUtil] 이미지 최종 처리 완료. Thumbs: {len(entity.thumb)}, Fanarts: {len(entity.fanart)}")


    @classmethod
    def __shiroutoname_info(cls, keyword):
        url = "https://shiroutoname.com/"
        tree = cls.get_tree(url, params={"s": keyword}, timeout=30)

        results = []
        for article in tree.xpath("//section//article"):
            title = article.xpath("./h2")[0].text_content()
            title = title[title.find("【") + 1 : title.rfind("】")]

            link = article.xpath(".//a/@href")[0]
            thumb_url = article.xpath(".//a/img/@data-src")[0]
            title_alt = article.xpath(".//a/img/@alt")[0]
            assert title == title_alt  # 다르면?

            result = {"title": title, "link": link, "thumb_url": thumb_url}

            for div in article.xpath("./div/div"):
                kv = div.xpath("./div")
                if len(kv) != 2:
                    continue
                key, value = [x.text_content().strip() for x in kv]
                if not key.endswith("："):
                    continue

                if key.startswith("品番"):
                    result["code"] = value
                    another_link = kv[1].xpath("./a/@href")[0]
                    assert link == another_link  # 다르면?
                elif key.startswith("素人名"):
                    result["name"] = value
                elif key.startswith("配信日"):
                    result["premiered"] = value
                    # format - YYYY/MM/DD
                elif key.startswith("シリーズ"):
                    result["series"] = value
                else:
                    logger.warning("UNKNOWN: %s=%s", key, value)

            a_class = "mlink" if "mgstage.com" in link else "flink"
            actors = []
            for a_tag in article.xpath(f'./div/div/a[@class="{a_class}"]'):
                actors.append(
                    {
                        "name": a_tag.text_content().strip(),
                        "href": a_tag.xpath("./@href")[0],
                    }
                )
            result["actors"] = actors
            results.append(result)
        return results

    @classmethod
    def shiroutoname_info(cls, entity):
        """upgrade entity(meta info) by shiroutoname"""
        data = None
        for d in cls.__shiroutoname_info(entity.originaltitle):
            if entity.originaltitle.lower() in d["code"].lower():
                data = d
                break
        if data is None:
            return entity
        if data.get("premiered", None):
            value = data["premiered"].replace("/", "-")
            entity.premiered = value
            entity.year = int(value[:4])
        if data.get("actors", []):
            entity.actor = [EntityActor(a["name"]) for a in data["actors"]]
        return entity



    @classmethod
    def discord_proxy_image(cls, image_url: str, **kwargs) -> str: # 첫 인자는 URL 또는 파일 경로 (문자열)
        if not image_url or not isinstance(image_url, str):
            logger.warning(f"Discord_proxy_image: Invalid image_url (not a string or empty): {image_url}")
            return image_url

        cache = CacheUtil.get_cache()
        cached_data_for_url = cache.get(image_url, {})

        crop_mode_from_caller = kwargs.pop("crop_mode", None) 
        
        # 캐시 내부 키 (mode_str)는 crop_mode 유무 및 값에 따라 유니크하게 생성
        is_cropped_image = False
        if crop_mode_from_caller and isinstance(crop_mode_from_caller, str) and crop_mode_from_caller.strip():
            mode_str = f"crop_{crop_mode_from_caller.strip()}" # 예: "crop_r"
            is_cropped_image = True
        else:
            mode_str = "no_crop" # 크롭 없으면 "no_crop"
        
        # logger.debug(f"Discord_proxy_image: Processing URL/Path='{image_url}', Mode='{mode_str}'")

        if cached_discord_url := cached_data_for_url.get(mode_str):
            if DiscordUtil.isurlattachment(cached_discord_url) and not DiscordUtil.isurlexpired(cached_discord_url):
                # logger.debug(f"Discord_proxy_image: Cache hit for Mode='{mode_str}'. URL: {cached_discord_url}")
                return cached_discord_url
            else:
                logger.debug(f"Discord_proxy_image: Cache for Mode='{mode_str}' found but expired or invalid.")

        proxy_url_for_open = kwargs.pop("proxy_url", None)
        
        pil_image_opened = cls.imopen(image_url, proxy_url=proxy_url_for_open)
        if pil_image_opened is None:
            logger.warning(f"Discord_proxy_image: Failed to open image from: {image_url}")
            return image_url

        try:
            image_to_upload = pil_image_opened
            original_format_from_pil = pil_image_opened.format # 열린 이미지의 원본 포맷

            if is_cropped_image: # crop_mode가 실제로 있을 때만 크롭 수행
                # logger.debug(f"Discord_proxy_image: Applying crop_mode '{crop_mode_from_caller}' to image from '{image_url}'.")
                cropped_image = cls.imcrop(pil_image_opened, position=crop_mode_from_caller.strip())
                if cropped_image:
                    image_to_upload = cropped_image
                    if original_format_from_pil: image_to_upload.format = original_format_from_pil 
                    elif not image_to_upload.format : image_to_upload.format = "JPEG"
                else:
                    logger.warning(f"Discord_proxy_image: Cropping failed for URL='{image_url}', Mode='{mode_str}'. Uploading uncropped (original from imopen).")
                    # image_to_upload는 이미 pil_image_opened (크롭 안 된 상태)
            
            if not image_to_upload.format:
                image_to_upload.format = "JPEG"

            # --- 파일명 생성 로직 변경 ---
            # 원본 URL에서 파일명과 확장자 분리 (쿼리스트링 제거)
            base_name_with_ext = os.path.basename(urlparse(image_url).path)
            name_part, ext_part = os.path.splitext(base_name_with_ext)
            
            # Pillow에서 얻은 실제 이미지 포맷으로 확장자 결정 (더 신뢰성 있음)
            current_image_format = image_to_upload.format if image_to_upload.format else "JPEG"
            final_ext = current_image_format.lower().replace("jpeg", "jpg")
            if final_ext not in ['jpg', 'png', 'webp']: final_ext = 'jpg' # 안전한 확장자로 통일

            # 최종 파일명 결정
            if is_cropped_image: # 크롭된 이미지인 경우
                filename_for_discord = f"{name_part[:50]}_crop.{final_ext}" # 예: originalname_crop.jpg
            else: # 원본 이미지인 경우
                filename_for_discord = f"{name_part[:50]}.{final_ext}"     # 예: originalname.jpg
            
            # 파일명이 비어있거나 "."으로 시작하는 경우 방지
            if not name_part: filename_for_discord = f"image{'_crop' if is_cropped_image else ''}.{final_ext}"
            elif filename_for_discord.startswith("."): filename_for_discord = f"image{filename_for_discord}"


            fields = [{"name": "original_url", "value": image_url[:1000]}]
            fields.append({"name": "applied_transform", "value": mode_str}) # 캐시 키에 사용된 mode_str 기록
            
            # logger.debug(f"Discord_proxy_image: Uploading to Discord. Filename: '{filename_for_discord}', Title: '{image_url}'")
            new_discord_url = DiscordUtil.proxy_image(image_to_upload, filename_for_discord, title=image_url, fields=fields)
            
            cached_data_for_url[mode_str] = new_discord_url
            cache[image_url] = cached_data_for_url
            logger.debug(f"Discord_proxy_image: Uploaded and cached. MainKey='{image_url}', Mode='{mode_str}'. URL: {new_discord_url}")
            return new_discord_url
        except Exception as e_proxy:
            logger.exception(f"이미지 프록시 중 예외 (discord_proxy_image for {image_url}): {e_proxy}")
            return image_url


    @classmethod
    def discord_proxy_image_localfile(cls, filepath: str) -> str:
        if not filepath:
            return filepath
        try:
            im = Image.open(filepath)
            # 파일 이름이 이상한 값이면 첨부가 안될 수 있음
            filename = f"localfile.{im.format.lower().replace('jpeg', 'jpg')}"
            return DiscordUtil.proxy_image(im, filename, title=filepath)
        except Exception:
            logger.exception("이미지 프록시 중 예외:")
            return filepath

    @classmethod
    def discord_renew_urls(cls, data):
        return DiscordUtil.renew_urls(data)


    @classmethod
    def get_user_custom_image_paths(cls, base_local_dir: str, path_segment: str, ui_code: str, type_suffix_with_extension: str, image_server_url: str):
        if not all([base_local_dir, path_segment, ui_code, type_suffix_with_extension, image_server_url]):
            # logger.debug("get_user_custom_image_paths: Required arguments missing.")
            return None, None

        try:
            ui_code_lower = ui_code.lower()
            filename_with_suffix = f"{ui_code_lower}{type_suffix_with_extension}"

            # --- 폴더 결정 로직 시작 (save_image_to_server_path와 유사하게) ---
            relative_dir_parts = [path_segment] # 기본 path_segment (예: 'jav/cen')

            ui_code_parts = ui_code.split('-')
            label_part_original_case = ui_code_parts[0] if ui_code_parts else ui_code
            label_part_input = label_part_original_case.upper()

            first_char_of_label_folder = ""
            label_part_for_folder = ""

            if label_part_input.startswith("741"):
                first_char_of_label_folder = '09'
                label_part_for_folder = label_part_input
            else:
                match_leading_digits = re.match(r'^(\d*)([a-zA-Z].*)$', label_part_input)
                if match_leading_digits:
                    label_after_stripping_digits = match_leading_digits.group(2)
                    label_part_for_folder = label_after_stripping_digits

                    if label_part_for_folder and label_part_for_folder[0].isalpha():
                        first_char_of_label_folder = label_part_for_folder[0].upper()
                    else:
                        first_char_of_label_folder = 'ETC'
                else:
                    if label_part_input and label_part_input[0].isdigit():
                        first_char_of_label_folder = '09'
                    elif label_part_input and label_part_input[0].isalpha():
                        first_char_of_label_folder = label_part_input[0].upper()
                    else:
                        first_char_of_label_folder = 'ETC'
                    label_part_for_folder = label_part_input

            if not first_char_of_label_folder: first_char_of_label_folder = "UNKNOWN"
            if not label_part_for_folder: label_part_for_folder = "UNKNOWN"

            relative_dir_parts.append(first_char_of_label_folder)
            relative_dir_parts.append(label_part_for_folder)

            user_image_dir_local = os.path.join(base_local_dir, *relative_dir_parts)
            user_image_file_local_path = os.path.join(user_image_dir_local, filename_with_suffix)

            # logger.debug(f"get_user_custom_image_paths: Checking custom image at '{user_image_file_local_path}'")

            if os.path.exists(user_image_file_local_path):
                relative_web_path = os.path.join(*relative_dir_parts, filename_with_suffix).replace("\\", "/")
                full_web_url = f"{image_server_url.rstrip('/')}/{relative_web_path.lstrip('/')}"
                # logger.debug(f"get_user_custom_image_paths: User custom image found: Web='{full_web_url}'")
                return user_image_file_local_path, full_web_url
            else:
                return None, None
        except Exception as e:
            logger.exception(f"Error in get_user_custom_image_paths for {ui_code}{type_suffix_with_extension}: {e}")
            return None, None


    @classmethod
    def get_image_url(cls, image_url, image_mode, proxy_url=None, with_poster=False):
        try:
            # logger.debug('get_image_url')
            # logger.debug(image_url)
            # logger.debug(image_mode)
            ret = {}
            # tmp = cls.discord_proxy_get_target(image_url)

            # logger.debug('tmp : %s', tmp)
            # if tmp is None:
            ret["image_url"] = cls.process_image_mode(image_mode, image_url, proxy_url=proxy_url)
            # else:
            #    ret['image_url'] = tmp

            if with_poster:
                # logger.debug(ret["image_url"])
                # ret['poster_image_url'] = cls.discord_proxy_get_target_poster(image_url)
                # if ret['poster_image_url'] is None:
                ret["poster_image_url"] = cls.process_image_mode("5", ret["image_url"])  # 포스터이미지 url 본인 sjva
                # if image_mode == '3': # 디스코드 url 모드일때만 포스터도 디스코드로
                # ret['poster_image_url'] = cls.process_image_mode('3', tmp) #디스코드 url / 본인 sjva가 소스이므로 공용으로 등록
                # cls.discord_proxy_set_target_poster(image_url, ret['poster_image_url'])

        except Exception:
            logger.exception("Image URL 생성 중 예외:")
        # logger.debug('get_image_url')
        # logger.debug(ret)
        return ret

    


    @classmethod
    def _internal_has_hq_poster_comparison(cls, im_sm_obj, im_lg_to_compare, function_name_for_log="has_hq_poster", sm_source_info=None, lg_source_info=None):
        # [수정] sm_source_info, lg_source_info 파라미터를 기본값 None으로 추가
        try:
            from imagehash import average_hash, phash
        except ImportError:
            logger.warning(f"{function_name_for_log} for '{sm_source_info}' vs '{lg_source_info}': ImageHash library not found.")
            return None

        ws, hs = im_sm_obj.size
        wl, hl = im_lg_to_compare.size
        if ws > wl or hs > hl:
            logger.debug(f"{function_name_for_log} for '{sm_source_info}' vs '{lg_source_info}': Small image ({ws}x{hs}) > large image ({wl}x{hl}).")
            return None

        positions = ["r", "l", "c"]
        ahash_threshold = 10
        for pos in positions:
            try:
                cropped_im = cls.imcrop(im_lg_to_compare, position=pos)
                if cropped_im is None: continue
                if average_hash(im_sm_obj) - average_hash(cropped_im) <= ahash_threshold:
                    # [수정] 로그 강화
                    logger.debug(f"{function_name_for_log} for '{sm_source_info}' vs '{lg_source_info}': Found similar (ahash) at pos '{pos}'.")
                    return pos
            except Exception as e_ahash:
                logger.error(f"{function_name_for_log} for '{sm_source_info}' vs '{lg_source_info}': Exception during ahash for pos '{pos}': {e_ahash}")
                continue

        phash_threshold = 10
        for pos in positions:
            try:
                cropped_im = cls.imcrop(im_lg_to_compare, position=pos)
                if cropped_im is None: continue
                if phash(im_sm_obj) - phash(cropped_im) <= phash_threshold:
                    logger.debug(f"{function_name_for_log} for '{sm_source_info}' vs '{lg_source_info}': Found similar (phash) at pos '{pos}'.")
                    return pos
            except Exception as e_phash:
                logger.error(f"{function_name_for_log} for '{sm_source_info}' vs '{lg_source_info}': Exception during phash for pos '{pos}': {e_phash}")
                continue

        logger.debug(f"{function_name_for_log} for '{sm_source_info}' vs '{lg_source_info}': No similar region found (ahash & phash).")
        return None


    @classmethod
    def is_hq_poster(cls, im_sm_source, im_lg_source, proxy_url=None, sm_source_info=None, lg_source_info=None):
        logger.debug(f"--- is_hq_poster called ---")
        log_sm_info = sm_source_info or (f"URL: {im_sm_source}" if isinstance(im_sm_source, str) else f"Type: {type(im_sm_source)}")
        log_lg_info = lg_source_info or (f"URL: {im_lg_source}" if isinstance(im_lg_source, str) else f"Type: {type(im_lg_source)}")
        
        logger.debug(f"  Small Image Source: {log_sm_info}")
        logger.debug(f"  Large Image Source: {log_lg_info}")

        try:
            if im_sm_source is None or im_lg_source is None:
                logger.debug("  Result: False (Source is None)")
                return False

            im_sm_obj = cls.imopen(im_sm_source, proxy_url=proxy_url)
            im_lg_obj = cls.imopen(im_lg_source, proxy_url=proxy_url)

            if im_sm_obj is None or im_lg_obj is None:
                logger.debug("  Result: False (Failed to open one or both images from source)")
                return False
            # logger.debug("  Images acquired/opened successfully.")

            try:
                from imagehash import dhash as hfun
                from imagehash import phash 

                ws, hs = im_sm_obj.size; wl, hl = im_lg_obj.size
                logger.debug(f"  Sizes: Small=({ws}x{hs}), Large=({wl}x{hl})")

                ratio_sm = ws / hs if hs != 0 else 0
                ratio_lg = wl / hl if hl != 0 else 0
                ratio_diff = abs(ratio_sm - ratio_lg)
                # logger.debug(f"  Aspect Ratios: Small={ratio_sm:.3f}, Large={ratio_lg:.3f}, Diff={ratio_diff:.3f}")

                if ratio_diff > 0.1: 
                    # logger.debug("  Result: False (Aspect ratio difference > 0.1)")
                    return False

                # dhash 비교
                dhash_sm = hfun(im_sm_obj); dhash_lg = hfun(im_lg_obj)
                hdis_d = dhash_sm - dhash_lg
                # logger.debug(f"  dhash distance: {hdis_d}")
                if hdis_d >= 14:
                    # logger.debug("  Result: False (dhash distance >= 14)")
                    return False

                if hdis_d <= 6:
                    # logger.debug("  Result: True (dhash distance <= 6)")
                    return True

                phash_sm = phash(im_sm_obj); phash_lg = phash(im_lg_obj)
                hdis_p = phash_sm - phash_lg
                hdis_sum = hdis_d + hdis_p # 합산 거리
                logger.debug(f"  phash distance: {hdis_p}, Combined distance (d+p): {hdis_sum}")
                result = hdis_sum < 24 # 유사도 판단 기준
                logger.debug(f"  Result: {result} (Combined distance < 24)")
                return result

            except ImportError:
                logger.warning("  ImageHash library not found. Cannot perform hash comparison.")
                return False
            except Exception as hash_e:
                logger.exception(f"  Error during image hash comparison: {hash_e}")
                return False
        except Exception as e:
            logger.exception(f"  Error in is_hq_poster: {e}")
            return False
        # finally:
            # logger.debug(f"--- is_hq_poster finished ---")

    @classmethod
    def has_hq_poster(cls, im_sm_url, im_lg_url, proxy_url=None):
        try:
            if not im_sm_url or not isinstance(im_sm_url, str) or \
               not im_lg_url or not isinstance(im_lg_url, str):
                logger.debug("has_hq_poster: Invalid or empty URL(s) provided.")
                return None

            im_sm_obj = cls.imopen(im_sm_url, proxy_url=proxy_url)
            im_lg_obj_original = cls.imopen(im_lg_url, proxy_url=proxy_url)

            if im_sm_obj is None or im_lg_obj_original is None:
                logger.debug("has_hq_poster: Failed to open one or both images.")
                return None

            # 1단계: 원본 PL 이미지로 비교 시도
            # logger.debug(f"has_hq_poster: Attempting comparison with original PL ('{im_lg_url}').")
            found_pos = cls._internal_has_hq_poster_comparison(
                im_sm_obj, 
                im_lg_obj_original, 
                function_name_for_log="has_hq_poster_original_pl",
                sm_source_info=im_sm_url,
                lg_source_info=im_lg_url
            )

            if found_pos:
                logger.debug(f"has_hq_poster: Found position '{found_pos}' using original PL.")
                return found_pos

            # 2단계: 1단계 실패 시, PL이 4:3 비율이면 레터박스 제거 후 재시도
            logger.debug("has_hq_poster: Original PL comparison failed. Checking for letterbox removal eligibility.")
            im_lg_no_letterbox = None
            try:
                wl_orig, hl_orig = im_lg_obj_original.size
                if hl_orig > 0:
                    aspect_ratio_lg = wl_orig / hl_orig
                    # 4:3 비율 근처인지 확인 (예: 1.30 ~ 1.36 범위)
                    if 1.30 <= aspect_ratio_lg <= 1.36:
                        top_crop_ratio = 0.0533 
                        bottom_crop_ratio = 0.0533 # 상하 동일 비율로 가정
                        
                        top_pixels = int(hl_orig * top_crop_ratio)
                        # bottom_pixels는 잘라낼 하단 영역의 시작점이 아니라, 남길 영역의 끝 y좌표
                        bottom_y_coord = hl_orig - int(hl_orig * bottom_crop_ratio) 
                        
                        if top_pixels < bottom_y_coord and top_pixels >= 0 and bottom_y_coord <= hl_orig :
                            box_for_lb_removal = (0, top_pixels, wl_orig, bottom_y_coord)
                            cropped_candidate = im_lg_obj_original.crop(box_for_lb_removal)
                            if cropped_candidate:
                                im_lg_no_letterbox = cropped_candidate
                                wl_new, hl_new = im_lg_no_letterbox.size
                                logger.debug(f"has_hq_poster: PL ('{im_lg_url}') is 4:3 like. Letterbox removed. Original: {wl_orig}x{hl_orig}, Cropped for retry: {wl_new}x{hl_new}")
                            else:
                                logger.debug(f"has_hq_poster: Failed to crop letterbox from 4:3 PL ('{im_lg_url}').")
                        else:
                            logger.debug(f"has_hq_poster: Invalid letterbox crop pixels for 4:3 PL ('{im_lg_url}'). Top: {top_pixels}, Bottom_Y: {bottom_y_coord}, Height: {hl_orig}.")
                    else:
                        logger.debug(f"has_hq_poster: PL ('{im_lg_url}') aspect ratio ({aspect_ratio_lg:.2f}) not in 4:3 range for letterbox removal retry.")
                else:
                    logger.debug(f"has_hq_poster: PL ('{im_lg_url}') height is 0. Cannot calculate aspect ratio.")
            except Exception as e_letterbox_check:
                logger.error(f"has_hq_poster: Error during letterbox check/removal for PL ('{im_lg_url}'): {e_letterbox_check}")

            # 레터박스 제거된 이미지가 있다면, 그것으로 다시 비교 시도
            if im_lg_no_letterbox:
                found_pos_retry = cls._internal_has_hq_poster_comparison(
                    im_sm_obj, 
                    im_lg_no_letterbox, 
                    function_name_for_log="has_hq_poster_letterbox_removed",
                    sm_source_info=im_sm_url,
                    lg_source_info=f"{im_lg_url} (letterbox removed)"
                )
                if found_pos_retry:
                    logger.debug(f"has_hq_poster: Found position '{found_pos_retry}' using letterbox-removed PL.")
                    # 중요: 여기서 반환되는 found_pos_retry는 레터박스 제거된 이미지 기준의 크롭 위치.
                    # 호출부에서 이 PL URL을 사용할 때는 레터박스 제거를 다시 수행해야 함.
                    return found_pos_retry 
            
            logger.debug(f"has_hq_poster: All comparison attempts failed for PL ('{im_lg_url}').")
            return None

        except Exception as e: 
            logger.exception(f"Error in has_hq_poster function for PL ('{im_lg_url if isinstance(im_lg_url, str) else 'Non-URL_LG'}'): {e}")
            return None





















    #############################################################
    # 유틸리티성.... 나중에 SiteUtil과 합친다.
    ############################################################# 
    
    @classmethod
    def change_html(cls, text):
        if not text:
            return text
        return (
            text.replace("&nbsp;", " ")
            .replace("&nbsp", " ")
            .replace("&lt;", "<")
            .replace("&gt;", ">")
            .replace("&amp;", "&")
            .replace("&quot;", '"')
            .replace("&#35;", "#")
            .replace("&#39;", "‘")
        )

    @classmethod
    def remove_special_char(cls, text):
        return cls.PTN_SPECIAL_CHAR.sub("", text)

    @classmethod
    def compare(cls, a, b):
        return (
            cls.remove_special_char(a).replace(" ", "").lower() == cls.remove_special_char(b).replace(" ", "").lower()
        )

    @classmethod
    def get_show_compare_text(cls, title):
        title = title.replace("일일연속극", "").strip()
        title = title.replace("특별기획드라마", "").strip()
        title = re.sub(r"\[.*?\]", "", title).strip()
        title = re.sub(r"\(.*?\)", "", title).strip()
        title = re.sub(r"^.{2,3}드라마", "", title).strip()
        title = re.sub(r"^.{1,3}특집", "", title).strip()
        return title

    @classmethod
    def compare_show_title(cls, title1, title2):
        title1 = cls.get_show_compare_text(title1)
        title2 = cls.get_show_compare_text(title2)
        return cls.compare(title1, title2)

    @classmethod
    def info_to_kodi(cls, data):
        data["info"] = {}
        data["info"]["title"] = data["title"]
        data["info"]["studio"] = data["studio"]
        data["info"]["premiered"] = data["premiered"]
        # if data['info']['premiered'] == '':
        #    data['info']['premiered'] = data['year'] + '-01-01'
        data["info"]["year"] = data["year"]
        data["info"]["genre"] = data["genre"]
        data["info"]["plot"] = data["plot"]
        data["info"]["tagline"] = data["tagline"]
        data["info"]["mpaa"] = data["mpaa"]
        if "director" in data and len(data["director"]) > 0:
            if isinstance(data["director"][0], dict):
                tmp_list = []
                for tmp in data["director"]:
                    tmp_list.append(tmp["name"])
                data["info"]["director"] = ", ".join(tmp_list).strip()
            else:
                data["info"]["director"] = data["director"]
        if "credits" in data and len(data["credits"]) > 0:
            data["info"]["writer"] = []
            if isinstance(data["credits"][0], dict):
                for tmp in data["credits"]:
                    data["info"]["writer"].append(tmp["name"])
            else:
                data["info"]["writer"] = data["credits"]

        if "extras" in data and data["extras"] is not None and len(data["extras"]) > 0:
            if data["extras"][0]["mode"] in ["naver", "youtube"]:
                url = "/metadata/api/video?site={site}&param={param}".format(
                    site=data["extras"][0]["mode"],
                    param=data["extras"][0]["content_url"],
                )
                url = ToolUtil.make_apikey_url(url)
                data["info"]["trailer"] = url
            elif data["extras"][0]["mode"] == "mp4":
                data["info"]["trailer"] = data["extras"][0]["content_url"]

        data["cast"] = []

        if "actor" in data and data["actor"] is not None:
            for item in data["actor"]:
                entity = {}
                entity["type"] = "actor"
                entity["role"] = item["role"]
                entity["name"] = item["name"]
                entity["thumbnail"] = item["thumb"]
                data["cast"].append(entity)

        if "art" in data and data["art"] is not None:
            for item in data["art"]:
                if item["aspect"] == "landscape":
                    item["aspect"] = "fanart"
        elif "thumb" in data and data["thumb"] is not None:
            for item in data["thumb"]:
                if item["aspect"] == "landscape":
                    item["aspect"] = "fanart"
            data["art"] = data["thumb"]
        if "art" in data:
            data["art"] = sorted(data["art"], key=lambda k: k["score"], reverse=True)
        return data

    @classmethod
    def is_hangul(cls, text):
        hanCount = len(cls.PTN_HANGUL_CHAR.findall(text))
        return hanCount > 0

    @classmethod
    def is_include_hangul(cls, text):
        try:
            return cls.is_hangul(text)
        except Exception:
            return False
   

    @classmethod
    def process_image_book(cls, url):
        im = cls.imopen(url)
        width, _ = im.size
        filename = f"proxy_{time.time()}.jpg"
        filepath = os.path.join(path_data, "tmp", filename)
        left = 0
        top = 0
        right = width
        bottom = width
        poster = im.crop((left, top, right, bottom))
        try:
            poster.save(filepath, quality=95)
        except Exception:
            poster = poster.convert("RGB")
            poster.save(filepath, quality=95)
        ret = cls.discord_proxy_image_localfile(filepath)
        return ret

    @classmethod
    def get_treefromcontent(cls, url, **kwargs):
        text = cls.get_response(url, **kwargs).content
        # logger.debug(text)
        if text is None:
            return
        return html.fromstring(text)

    @classmethod
    def get_translated_tag(cls, tag_type, tag):
        tags_json = os.path.join(os.path.dirname(__file__), "tags.json")
        with open(tags_json, "r", encoding="utf8") as f:
            tags = json.load(f)

        if tag_type not in tags:
            return tag

        if tag in tags[tag_type]:
            return tags[tag_type][tag]

        trans_text = cls.trans(tag, source="ja", target="ko")
        # logger.debug(f'태그 번역: {tag} - {trans_text}')
        if cls.is_include_hangul(trans_text) or trans_text.replace(" ", "").isalnum():
            tags[tag_type][tag] = trans_text

            with open(tags_json, "w", encoding="utf8") as f:
                json.dump(tags, f, indent=4, ensure_ascii=False)

            res = tags[tag_type][tag]
        else:
            res = tag

        return res








    # 범용 이미지 처리
    @classmethod
    def imcrop(cls, im, position=None, box_only=False):
        """원본 이미지에서 잘라내 세로로 긴 포스터를 만드는 함수"""

        if not isinstance(im, Image.Image):
            return im

        original_format = im.format

        width, height = im.size
        new_w = height / 1.4225
        if position == "l":
            left = 0
        elif position == "c":
            left = (width - new_w) / 2
        else:
            # default: from right
            left = width - new_w
        
        # left, right 값이 이미지 경계를 벗어나지 않도록 조정 (음수 또는 width 초과 방지)
        left = max(0, min(left, width - new_w))
        right = left + new_w
        if right > width : # new_w가 너무 커서 오른쪽 경계를 넘는 경우
            new_w = width - left
            right = width
        if new_w <= 0 : # 계산된 너비가 0 이하이면 크롭 불가
            logger.debug(f"imcrop: Calculated new_w ({new_w}) is invalid for image size {width}x{height}. Returning original.")
            return im # 원본 반환 또는 None

        box = (left, 0, right, height)
        
        if box_only:
            return box
        
        try:
            cropped_im = im.crop(box)
            if cropped_im and original_format: # 크롭 성공했고 원본 포맷 정보가 있었다면
                cropped_im.format = original_format # format 속성 복사
            return cropped_im
        except Exception as e_crop:
            logger.error(f"Error during im.crop with box {box}: {e_crop}")
            return None # 크롭 실패 시 None 반환



    





























































    #############################################################
    # SiteAvBase 에 넘어간 메소드들
    ############################################################# 

    @classmethod
    def get_tree(cls, url, **kwargs):
        text = cls.get_text(url, **kwargs)
        # logger.debug(text)
        if text is None:
            return text
        return html.fromstring(text)

    @classmethod
    def get_text(cls, url, **kwargs):
        res = cls.get_response(url, **kwargs)
        # logger.debug('url: %s, %s', res.status_code, url)
        # if res.status_code != 200:
        #    return None
        return res.text

    @classmethod
    def get_response(cls, url, **kwargs):
        kwargs['verify'] = False  # SSL 인증서 검증 비활성화 (필요시)   
        proxy_url_from_arg = kwargs.pop("proxy_url", None)

        proxies_for_this_request = None
        if proxy_url_from_arg:
            proxies_for_this_request = {"http": proxy_url_from_arg, "https": proxy_url_from_arg}
            # logger.debug(f"SiteUtil.get_response for URL='{url}': Using EXPLICIT proxy from argument: {proxies_for_this_request}")
        else:
            proxies_for_this_request = {} # 세션 기본 프록시 무시
            # logger.debug(f"SiteUtil.get_response for URL='{url}': NO explicit proxy from argument. Setting proxies to {proxies_for_this_request} to bypass session proxies for this request.")

        request_headers = kwargs.pop("headers", cls.default_headers.copy())
        method = kwargs.pop("method", "GET")
        post_data = kwargs.pop("post_data", None)
        if post_data:
            method = "POST"
            kwargs["data"] = post_data

        if "javbus.com" in url:
            request_headers["referer"] = "https://www.javbus.com/"

        try:
            res = cls.session.request(method, url, headers=request_headers, proxies=proxies_for_this_request, **kwargs)

            #log_source = "FROM CACHE" if hasattr(res, 'from_cache') and res.from_cache else "fetched (NOT from cache or cache expired/missed)"

            #if res.status_code == 200:
            #    logger.info(f"SiteUtil.get_response: URL '{url}' {log_source}. Status: {res.status_code} OK.")
            #else:
            #    logger.warning(f"SiteUtil.get_response: URL '{url}' {log_source}. Status: {res.status_code} (Not 200 OK).")

            return res

        except requests.exceptions.Timeout as e_timeout:
            # 에러 로그에 사용하려 했던 프록시 정보 (proxy_url_from_arg)를 명시
            logger.error(f"SiteUtil.get_response: Timeout for URL='{url}'. Attempted Proxy (from arg)='{proxy_url_from_arg}'. Error: {e_timeout}")
            return None
        except requests.exceptions.ConnectionError as e_conn:
            logger.error(f"SiteUtil.get_response: ConnectionError for URL='{url}'. Attempted Proxy (from arg)='{proxy_url_from_arg}'. Error: {e_conn}")
            return None
        except requests.exceptions.RequestException as e_req:
            logger.error(f"SiteUtil.get_response: RequestException (other) for URL='{url}'. Attempted Proxy (from arg)='{proxy_url_from_arg}'. Error: {e_req}")
            logger.error(traceback.format_exc()) 
            return None 
        except Exception as e_general:
            logger.error(f"SiteUtil.get_response: General Exception for URL='{url}'. Attempted Proxy (from arg)='{proxy_url_from_arg}'. Error: {e_general}")
            logger.error(traceback.format_exc())
            return None
        
    @classmethod
    def are_images_visually_same(cls, img_src1, img_src2, proxy_url=None, threshold=10):
        """
        두 이미지 소스(URL 또는 로컬 경로)가 시각적으로 거의 동일한지 비교합니다.
        Image hashing (dhash + phash)을 사용하여 거리가 임계값 미만인지 확인합니다.
        """
        # logger.debug(f"Comparing visual similarity (threshold: {threshold})...")
        # log_src1 = img_src1 if isinstance(img_src1, str) else "PIL Object 1"
        # log_src2 = img_src2 if isinstance(img_src2, str) else "PIL Object 2"
        # logger.debug(f"  Source 1: {log_src1}")
        # logger.debug(f"  Source 2: {log_src2}")

        try:
            if img_src1 is None or img_src2 is None:
                logger.debug("  Result: False (One or both sources are None)")
                return False

            # 이미지 열기 (imopen은 URL, 경로, PIL 객체 처리 가능)
            # 첫 번째 이미지는 proxy_url 사용 가능, 두 번째는 주로 로컬 파일이므로 불필요
            im1 = cls.imopen(img_src1, proxy_url=proxy_url) 
            im2 = cls.imopen(img_src2) # 두 번째는 로컬 파일 경로 가정

            if im1 is None or im2 is None:
                logger.debug("  Result: False (Failed to open one or both images)")
                return False
            # logger.debug("  Images opened successfully.")

            try:
                from imagehash import dhash, phash # 한 번에 임포트

                # 크기가 약간 달라도 해시는 비슷할 수 있으므로 크기 비교는 선택적
                # w1, h1 = im1.size; w2, h2 = im2.size
                # if w1 != w2 or h1 != h2:
                #     logger.debug(f"  Sizes differ: ({w1}x{h1}) vs ({w2}x{h2}). Might still be visually similar.")

                # dhash 및 phash 계산
                dhash1 = dhash(im1); dhash2 = dhash(im2)
                phash1 = phash(im1); phash2 = phash(im2)

                # 거리 계산
                d_dist = dhash1 - dhash2
                p_dist = phash1 - phash2
                combined_dist = d_dist + p_dist

                # logger.debug(f"  dhash distance: {d_dist}")
                # logger.debug(f"  phash distance: {p_dist}")
                # logger.debug(f"  Combined distance: {combined_dist}")

                # 임계값 비교
                is_same = combined_dist < threshold
                # logger.debug(f"  Result: {is_same} (Combined distance < {threshold})")
                return is_same

            except ImportError:
                logger.warning("  ImageHash library not found. Cannot perform visual similarity check.")
                return False # 라이브러리 없으면 비교 불가
            except Exception as hash_e:
                logger.exception(f"  Error during image hash comparison: {hash_e}")
                return False # 해시 비교 중 오류

        except Exception as e:
            logger.exception(f"  Error in are_images_visually_same: {e}")
            return False # 전체 함수 오류
        


    @classmethod
    def imopen(cls, img_src, proxy_url=None):
        if isinstance(img_src, Image.Image):
            return img_src
        if img_src.startswith("http"):
            # remote url
            try:
                # 2025.07.12 by soju
                # url이 ff proxy를 사용하는 경우 proxy_url 이 또 들어온다.
                if proxy_url and 'normal/image_proxy' in img_src:
                    proxy_url = None  # ff proxy URL은 이미 내부적으로 처리됨
                res = cls.get_response(img_src, proxy_url=proxy_url)
                return Image.open(BytesIO(res.content))
            except Exception:
                logger.exception("이미지 여는 중 예외:")
                return None
        else:
            try:
                # local file
                return Image.open(img_src)
            except (FileNotFoundError, OSError):
                logger.exception("이미지 여는 중 예외:")
                return None
            
    

    @classmethod
    def trans(cls, text, do_trans=True, source="ja", target="ko"):
        text = text.strip()
        if do_trans and text:
            return TransUtil.trans(text, source=source, target=target).strip()
        return text