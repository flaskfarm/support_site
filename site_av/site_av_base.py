# python 기본
import os
import re
import time
import socket
import traceback
from datetime import timedelta
from urllib.parse import urlencode, unquote_plus, urlparse
import random
import json
import math
# python 확장
import requests
import ssl
from lxml import html
from flask import Response, abort, send_file
from io import BytesIO
from PIL import Image, UnidentifiedImageError
from requests.adapters import HTTPAdapter

# FF
from support import SupportDiscord
from ..setup import P, F, logger, path_data
from ..site_util_av import SiteUtilAv
from ..entity_base import EntityThumb
from ..trans_util import TransUtil
from ..entity_base import EntityActor

_CURL_CFFI_AVAILABLE = False
try:
    from curl_cffi import requests as cffi_requests
    _CURL_CFFI_AVAILABLE = True
except ImportError:
    try:
        logger.info("Installing curl_cffi...")
        import subprocess
        import sys
        subprocess.check_call([sys.executable, "-m", "pip", "install", "curl_cffi"])
        
        from curl_cffi import requests as cffi_requests
        _CURL_CFFI_AVAILABLE = True
        logger.info("curl_cffi installed successfully.")
    except Exception as e:
        logger.error(f"Failed to install curl_cffi: {e}")

try:
    from dateutil.parser import parse
except ImportError:
    os.system("pip install dateutils")
    from dateutil.parser import parse

# Selenium Imports
#try:
#    from selenium import webdriver
#    from selenium.webdriver.common.by import By
#    from selenium.webdriver.support.ui import WebDriverWait
#    from selenium.webdriver.support import expected_conditions as EC
#    from selenium.common.exceptions import TimeoutException, WebDriverException
#    is_selenium_available = True
#except ImportError:
#    is_selenium_available = False

is_selenium_available = False

# Stealth Import
#try:
#    from selenium_stealth import stealth
#    is_stealth_available = True
#except ImportError:
#    is_stealth_available = False


class SiteAvBase:
    site_name = None
    site_char = None
    module_char = None
    
    session = None
    base_default_headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8",
        "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
    }
    default_headers = None
    config = None
    MetadataSetting = None

    _cf_cookies = {}
    _cf_cookie_timestamp = 0
    CF_COOKIE_EXPIRY = 3600

    ################################################
    # region 기본적인 것들

    # 각 사이트별로 session 객체 생성
    @classmethod
    def get_session(cls):
        """
        세션을 초기화하는 메소드
        :return: requests.Session 객체
        """
        if F.config['run_celery'] == False:
            try:
                from requests_cache import CachedSession
                session = CachedSession(
                    os.path.join(path_data, 'db', 'av_cache'),
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
        return session


    @classmethod
    def get_tree(cls, url, **kwargs):
        text = cls.get_text(url, **kwargs)
        if text is None:
            return None
        try:
            return html.fromstring(text)
        except Exception as e:
            logger.error(f"Failed to parse HTML from URL '{url}': {e}")
            return None


    @classmethod
    def get_text(cls, url, **kwargs):
        res = cls.get_response_cffi(url, **kwargs)
        if res is None:
            logger.warning(f"get_text: get_response returned None for URL: {url}")
            return None
        if 200 <= res.status_code < 300:
            return res.text
        else:
            logger.warning(f"get_text: Received non-2xx status code {res.status_code} for URL: {url}")
            return None


    @classmethod
    def get_response(cls, url, **kwargs):
        try:
            from .site_dmm import SiteDmm
            from .site_mgstage import SiteMgstage
            CONTEXT_SWITCH_RULES = {
                'dmm.co.jp': SiteDmm,
                'mgstage.com': SiteMgstage,
                'r18.com': SiteMgstage,
            }
        except ImportError:
            CONTEXT_SWITCH_RULES = {}

        # 기본 프록시
        proxies = kwargs.pop("proxies", None)
        if not proxies and cls.config and cls.config.get('use_proxy', False):
            p_url = cls.config.get('proxy_url')
            if p_url: proxies = {"http": p_url, "https": p_url}

        request_headers = kwargs.pop("headers", cls.default_headers.copy() if cls.default_headers else cls.base_default_headers.copy())

        # 스위치 모듈 로직
        for domain, expert_module in CONTEXT_SWITCH_RULES.items():
            if domain in url:
                if expert_module and cls.site_name != expert_module.site_name:
                    if not proxies and expert_module.config and expert_module.config.get('use_proxy', False):
                        p_url = expert_module.config.get('proxy_url')
                        if p_url: proxies = {"http": p_url, "https": p_url}
                    
                    if expert_module.default_headers:
                        request_headers.update(expert_module.default_headers)

                    if expert_module.site_name == 'dmm':
                        request_headers['Referer'] = 'https://www.dmm.co.jp/'
                        request_headers['Cookie'] = 'age_check_done=1'
                break

        if 'dmm.co.jp' in url and cls.site_name == 'dmm':
            request_headers['Cookie'] = 'age_check_done=1'

        method = kwargs.pop("method", "GET")
        post_data = kwargs.pop("post_data", None)
        if post_data:
            method = "POST"
            kwargs["data"] = post_data

        try:
            res = cls.session.request(method, url, headers=request_headers, proxies=proxies, **kwargs)
            return res
        except requests.exceptions.RequestException as e:
            logger.error(f"get_response (requests) error for {url}: {e}")
            return None


    @classmethod
    def get_response_cffi(cls, url, **kwargs):
        """WAF 우회용 (curl_cffi 사용)"""
        if not _CURL_CFFI_AVAILABLE:
            logger.error("curl_cffi not available.")
            return cls.get_response(url, **kwargs) # Fallback

        try:
            from .site_dmm import SiteDmm
            from .site_mgstage import SiteMgstage
            CONTEXT_SWITCH_RULES = {
                'dmm.co.jp': SiteDmm,
                'mgstage.com': SiteMgstage,
                'r18.com': SiteMgstage,
            }
        except ImportError:
            CONTEXT_SWITCH_RULES = {}

        # 기본 프록시
        proxies = kwargs.pop("proxies", None)
        if not proxies and cls.config and cls.config.get('use_proxy', False):
            p_url = cls.config.get('proxy_url')
            if p_url: proxies = {"http": p_url, "https": p_url}

        request_headers = kwargs.pop("headers", cls.default_headers.copy() if cls.default_headers else cls.base_default_headers.copy())

        # 스위치 모듈 로직
        for domain, expert_module in CONTEXT_SWITCH_RULES.items():
            if domain in url:
                if expert_module and cls.site_name != expert_module.site_name:
                    if not proxies and expert_module.config and expert_module.config.get('use_proxy', False):
                        p_url = expert_module.config.get('proxy_url')
                        if p_url: proxies = {"http": p_url, "https": p_url}
                    
                    if expert_module.default_headers:
                        request_headers.update(expert_module.default_headers)

                    if expert_module.site_name == 'dmm':
                        request_headers['Referer'] = 'https://www.dmm.co.jp/'
                        request_headers['Cookie'] = 'age_check_done=1'
                break

        if 'dmm.co.jp' in url and cls.site_name == 'dmm':
            request_headers['Cookie'] = 'age_check_done=1'

        method = kwargs.pop("method", "GET").upper()
        if "post_data" in kwargs:
            kwargs["data"] = kwargs.pop("post_data")
            if method == "GET": method = "POST"

        impersonate = kwargs.pop("impersonate", "chrome110")
        timeout = kwargs.pop("timeout", 30)
        if 'verify' in kwargs: kwargs.pop('verify') # cffi 호환

        try:
            res = cffi_requests.request(
                method=method,
                url=url,
                headers=request_headers,
                proxies=proxies,
                impersonate=impersonate,
                timeout=timeout,
                **kwargs
            )
            return res
        except Exception as e:
            logger.error(f"get_response_cffi error for {url}: {e}")
            return None



    # 외부에서 이미지를 요청하는 URL을 만든다.
    # proxy를 사용하지 않고 가공이 필요없다면 그냥 오리지널을 리턴해야하며, 그 판단은 개별 사이트에서 한다.
    @classmethod
    def make_image_url(cls, url, mode=None):
        """
        이미지 URL을 생성하는 메소드
        :param url: 이미지 URL
        :param mode: 이미지 모드 (예: "ff_proxy")
        :return: 처리된 이미지 URL
        """
        param = {
            "site": cls.site_name,
            "url": url
        }
        if mode:
            param["mode"] = mode

        if cls.module_char != 'E':
            url = f"{F.SystemModelSetting.get('ddns')}/metadata/normal/jav_image?{urlencode(param)}"
        else:
            url = f"{F.SystemModelSetting.get('ddns')}/metadata/normal/jav_image_un?{urlencode(param)}"
        return url

    # 예고편 url
    @classmethod
    def make_video_url(cls, url):
        if cls.config['use_proxy'] == False:
            return url
        param = {
            "site": cls.site_name,
            "url": url
        }

        # 유효성 검사 일단 생략
        #proxies = None
        #if cls.config['use_proxy']:
        #    proxies = {"http": cls.config['proxy_url'], "https": cls.config['proxy_url']}
        #
        #with cls.session.get(url, proxies=proxies, headers=cls.default_headers) as res:
        #    if res.status_code != 200:
        #        return None

        if cls.module_char == 'C':
            return f"{F.SystemModelSetting.get('ddns')}/metadata/normal/jav_video?{urlencode(param)}"
        else:
            return f"{F.SystemModelSetting.get('ddns')}/metadata/normal/jav_video_un?{urlencode(param)}"
    
    @classmethod
    def trans(cls, text, source="ja", target="ko"):
        text = text.strip()
        if not text:
            return text
        if cls.config['trans_option'] == 'not_using':
            return text
        elif cls.config['trans_option'] == 'using':
            return TransUtil.trans(text, source=source, target=target).strip()
        elif cls.config['trans_option'] == 'using_plugin':
            try:
                from trans import SupportTrans
                return SupportTrans.translate(text, source=source, target=target).strip()
            except Exception as e:
                logger.error(f"trans plugin error: {str(e)}")
                #logger.error(traceback.format_exc())
                return TransUtil.trans_web2(text, source=source, target=target).strip()


    # endregion 
    ################################################


    ################################################
    # region SiteAvBase 인터페이스

    @classmethod
    def search(cls, keyword, **kwargs):
        pass

    @classmethod
    def info(cls, code, **kwargs):
        pass

    # 메타데이터 라우팅 함수에서 호출한다.
    # 리턴타입: redirect 
    @classmethod
    def jav_image(cls, url=None, mode=None, site=None, path=None):
        # 1. 로컬 파일 요청 처리
        if site == 'system' and path:
            try:
                allowed_path = os.path.join(path_data, "tmp")
                if os.path.commonpath([allowed_path, os.path.abspath(path)]) != allowed_path:
                    abort(403)
                return send_file(path, mimetype='image/jpeg')
            except FileNotFoundError:
                abort(404)
            except Exception:
                abort(500)

        # 2. 원격 URL에 대한 기본 처리
        # mode가 'crop_...' 이거나 None인 경우만 처리됨
        return cls.default_jav_image(url, mode)


    @classmethod
    def jav_video(cls, url):
        try:
            try:
                from .site_dmm import SiteDmm
                from .site_mgstage import SiteMgstage
                CONTEXT_SWITCH_RULES = {
                    'dmm.co.jp': SiteDmm,
                    'mgstage.com': SiteMgstage,
                    'r18.com': SiteMgstage,
                }
            except ImportError:
                CONTEXT_SWITCH_RULES = {}

            proxies = None
            if cls.config and cls.config.get('use_proxy', False):
                proxies = {"http": cls.config['proxy_url'], "https": cls.config['proxy_url']}

            request_headers = cls.default_headers.copy()

            for domain, expert_module in CONTEXT_SWITCH_RULES.items():
                if domain in url:
                    if expert_module and cls.site_name != expert_module.site_name:
                        logger.debug(f"jav_video: Overriding proxy/headers for '{cls.site_name}' with settings from '{expert_module.site_name}' for URL: {url}")

                        if expert_module.config and expert_module.config.get('use_proxy', False):
                            proxies = {"http": expert_module.config['proxy_url'], "https": expert_module.config['proxy_url']}
                        else:
                            proxies = None

                        request_headers.update(expert_module.default_headers)
                        if expert_module.site_name == 'dmm':
                            request_headers['Referer'] = 'https://www.dmm.co.jp/'
                        elif expert_module.site_name == 'mgstage':
                            request_headers['Referer'] = 'https://www.mgstage.com/'
                    break

            req = cls.session.get(url, proxies=proxies, headers=request_headers, stream=True, timeout=(10, 120))
            req.raise_for_status()

        except requests.exceptions.RequestException as e:
            logger.error(f"jav_video: Failed to get video stream for {url}. Error: {e}")
            return abort(500)

        def generate_content():
            for chunk in req.iter_content(chunk_size=8192):
                yield chunk

        response_headers = {
            'Content-Type': req.headers.get('Content-Type', 'video/mp4'),
            'Content-Length': req.headers.get('Content-Length'),
            'Accept-Ranges': 'bytes',
        }
        return Response(generate_content(), headers=response_headers)


    _yaml_settings = {}

    @classmethod
    def set_yaml_settings(cls, settings):
        cls._yaml_settings = settings if settings is not None else {}
        # logger.debug(f"Global parsing rules updated. Generic: {len(cls._parsing_rules.get('generic_rules', []))}, Censored: {len(cls._parsing_rules.get('censored_special_rules', []))}")


    @classmethod
    def set_config(cls, db):
        if cls.session is None:
            cls.session = cls.get_session()
        else:
            cls.session.close()
            cls.session = cls.get_session()

        cls.MetadataSetting = db

        # 모듈 종류(Censored/Uncensored)에 따라 설정 키 접두사를 결정
        module_type = 'jav_censored' if cls.module_char == 'C' else 'jav_uncensored'

        # 공통 설정은 항상 jav_censored의 것을 따르도록 강제
        common_config_prefix = 'jav_censored'

        use_proxy_key = f"{module_type}_{cls.site_name}_use_proxy"
        proxy_url_key = f"{module_type}_{cls.site_name}_proxy_url"

        # config 딕셔너리 구성
        if getattr(cls, 'config', None) is None:
            cls.config = {}

        parsing_rules = cls._yaml_settings.get('jav_parsing_rules', {})
        image_settings = cls._yaml_settings.get('jav_image_settings', {})
        misc_settings = cls._yaml_settings.get('jav_misc_settings', {})

        cls.config.update({
            # 공통 설정 (항상 jav_censored 값을 사용)
            "image_mode": db.get(f'{common_config_prefix}_image_mode'),
            "trans_option": db.get(f'{common_config_prefix}_trans_option'),
            "use_extras": db.get_bool(f'{common_config_prefix}_use_extras'),
            "max_arts": db.get_int(f'{common_config_prefix}_art_count'),
            "use_imagehash": db.get_bool(f'{common_config_prefix}_use_imagehash'),
            "selenium_url": db.get(f'{common_config_prefix}_selenium_url'),
            "selenium_driver_type": db.get(f'{common_config_prefix}_selenium_driver_type'),
            "flaresolverr_url": db.get(f'{common_config_prefix}_flaresolverr_url'),

            # 이미지 서버 관련 공통 설정
            "image_server_local_path": db.get(f'{common_config_prefix}_image_server_local_path'),
            "image_server_url": db.get(f'{common_config_prefix}_image_server_url'),
            "image_server_rewrite": db.get_bool(f'{common_config_prefix}_image_server_rewrite'),
            "censored_image_format": db.get('jav_censored_image_server_save_format'),
            "uncensored_image_format": db.get('jav_uncensored_image_server_save_format'),

            # 사이트별 설정 (각 모듈 타입에 맞는 값을 사용)
            "use_proxy": db.get_bool(use_proxy_key),
            "proxy_url": db.get(proxy_url_key),

            # 파싱 규칙 설정
            "generic_parser_rules": parsing_rules.get('generic_rules', []),
            "censored_parser_rules": parsing_rules.get('censored_special_rules', []),
            "uncensored_parser_rules": parsing_rules.get('uncensored_special_rules', []),

            # 이미지 임계값 설정
            "hq_poster_threshold_strict": image_settings.get('hq_poster_threshold_strict', 10),
            "hq_poster_threshold_normal": image_settings.get('hq_poster_threshold_normal', 30),

            # Selenium 타임아웃 설정
            "selenium_timeout": misc_settings.get('selenium_timeout', 10),

            # 스마트 크롭 설정 (Face)
            "use_smart_crop": db.get_bool(f'{common_config_prefix}_use_smart_crop'),
            "face_landmarker_model_path": db.get(f'{common_config_prefix}_face_landmarker_model_path'),
            "smart_crop_face_threshold": float(image_settings.get('smart_crop_face_threshold', 0.5)),
            "smart_crop_face_rescue_threshold": float(image_settings.get('smart_crop_face_rescue_threshold', 0.3)),

            # 스마트 크롭 설정 (Pose)
            "use_pose_landmarker": db.get_bool(f'{common_config_prefix}_use_pose_landmarker'), 
            "pose_landmarker_model_path": db.get(f'{common_config_prefix}_pose_landmarker_model_path'),
            "smart_crop_body_threshold": float(image_settings.get('smart_crop_body_threshold', 0.5)),

            "smart_crop_face_weight_min": float(image_settings.get('smart_crop_face_weight_min', 0.3)),
            "smart_crop_face_weight_max": float(image_settings.get('smart_crop_face_weight_max', 0.8)),
        })
        # censored_rules_count = len(cls.config.get('censored_parser_rules', {}).get('custom_rules', []))
        # uncensored_rules_count = len(cls.config.get('uncensored_parser_rules', {}).get('custom_rules', []))
        # logger.debug(f"[{cls.site_name}] Config loaded. Censored rules: {censored_rules_count}, Uncensored rules: {uncensored_rules_count}")


    # endregion
    ################################################


    ################################################
    # region 이미지 처리 관련

    @classmethod
    def imopen(cls, img_src):
        if isinstance(img_src, Image.Image):
            return img_src
        if img_src.startswith("http"):
            # remote url
            try:
                res = cls.get_response(img_src)
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


    # jav_image 기본 처리
    @classmethod
    def default_jav_image(cls, image_url, mode=None):
        res = None
        # 재시도 로직 (최대 3회, 타임아웃 60초)
        for i in range(3):
            try:
                res = cls.get_response(image_url, verify=False, timeout=60)
                if res and res.status_code == 200:
                    break
            except Exception as e:
                if i < 2: 
                    time.sleep(2)

        if res is None:
            P.logger.error(f"image_proxy: SiteUtil.get_response returned None for URL: {image_url}")
            abort(404) # 또는 적절한 에러 응답
            return # 함수 종료

        if res.status_code != 200:
            P.logger.warning(f"image_proxy: Received status code {res.status_code} for URL: {image_url}")
            abort(res.status_code if res.status_code >= 400 else 500)
            return

        content_type_header = res.headers.get('Content-Type', '').lower()
        content_bytes = res.content
        is_image_content = False

        # 1. Content-Type 헤더로 1차 확인
        if content_type_header.startswith('image/'):
            is_image_content = True
        # 2. binary/octet-stream인 경우, 파일 시그니처(Magic Number)로 2차 확인
        elif content_type_header == 'binary/octet-stream':
            if len(content_bytes) > 4:
                # JPEG (JFIF, EXIF) or PNG or GIF
                if (content_bytes.startswith(b'\xFF\xD8\xFF') or
                    content_bytes.startswith(b'\x89PNG') or
                    content_bytes.startswith(b'GIF8')):
                    # logger.warning(f"image_proxy: Content-Type is 'binary/octet-stream' but content is a valid image. Proceeding for URL: {image_url}")
                    is_image_content = True

        if not is_image_content:
            P.logger.error(f"image_proxy: Expected image, but got Content-Type '{content_type_header}' and invalid content for URL: {image_url}")
            abort(400)

        try:
            bytes_im = BytesIO(content_bytes)
            im = Image.open(bytes_im)
            imformat = im.format

            # Pillow가 포맷을 감지 못했거나, Content-Type이 binary였을 경우, im.format으로 재확인
            if imformat is None or content_type_header == 'binary/octet-stream':
                P.logger.debug(f"image_proxy: Pillow detected format '{imformat}' for binary stream. URL: {image_url}")
                # Pillow가 감지한 포맷이 없다면, 기본 JPEG로 가정
                if imformat not in ['JPEG', 'PNG', 'WEBP', 'GIF']:
                    imformat = 'JPEG'

            mimetype = im.get_format_mimetype() or f'image/{imformat.lower()}'

        except UnidentifiedImageError as e: # PIL.UnidentifiedImageError 명시적 임포트 필요
            P.logger.error(f"image_proxy: PIL.UnidentifiedImageError for URL: {image_url}. Response Content-Type: {content_type_header}")
            P.logger.error(f"image_proxy: Error details: {e}")
            # 디버깅을 위해 실패한 이미지 데이터 일부 저장 (선택적)
            try:
                failed_image_path = os.path.join(path_data, "tmp", f"failed_image_{time.time()}.bin")
                with open(failed_image_path, 'wb') as f:
                    f.write(res.content)
                P.logger.info(f"image_proxy: Content of failed image saved to: {failed_image_path}")
            except Exception as save_err:
                P.logger.error(f"image_proxy: Could not save failed image content: {save_err}")
            abort(400) # 잘못된 이미지 파일
            return
        except Exception as e_pil:
            P.logger.error(f"image_proxy: General PIL error for URL: {image_url}: {e_pil}")
            P.logger.error(traceback.format_exc())
            abort(500)
            return

        if mode == 'smart_crop':
            # 가로 이미지(Landscape)인 경우에만 세로 포스터로 크롭 시도
            # 비율 기준: 가로가 세로보다 1.1배 이상 클 때
            w, h = im.size
            if w > h * 0.8:
                cropped = cls._smart_crop_image(im)
                if cropped:
                    im = cropped
            
            # 처리가 끝났으므로 mode 초기화
            mode = None

        if mode is not None and mode.startswith("crop_"):

            operations = mode.replace("crop_", "").split('_')

            # 1. 비율 정보가 있는지 확인하고 추출
            aspect_ratio = 1.4225
            if operations and operations[-1].replace('.', '', 1).isdigit():
                try:
                    aspect_ratio = float(operations.pop())
                except ValueError:
                    pass

            # 2. 크롭 명령
            processed_im = im
            is_first_op = True
            num_ops = len(operations)

            for op in operations:
                new_im = None
                # 이중 크롭의 첫 번째 단계('r' 또는 'l')일 때만 너비를 반으로 자름
                if op in ['r', 'l'] and is_first_op and num_ops > 1:
                    width, height = processed_im.size
                    box = (width / 2, 0, width, height) if op == 'r' else (0, 0, width / 2, height)
                    new_im = processed_im.crop(box)
                else: # 단일 크롭이거나, 이중 크롭의 두 번째 단계일 경우
                    new_im = SiteUtilAv.imcrop(processed_im, position=op, aspect_ratio=aspect_ratio)

                # 중간 이미지 객체 메모리 관리
                if processed_im is not im:
                    processed_im.close()
                processed_im = new_im

                if processed_im is None:
                    logger.warning(f"Cropping failed at operation '{op}' for mode '{mode}'. Using original image.")
                    if im.fp: im.fp.seek(0)
                    processed_im = im
                    break

                is_first_op = False

            im = processed_im

        return cls.pil_to_response(im, format=imformat, mimetype=mimetype)


    @classmethod
    def default_jav_image_cs(cls, image_url, mode=None):
        """
        default_jav_image와 동일하지만, get_response_cs를 사용하는 버전.
        """
        # get_response_cs를 사용하여 이미지 데이터를 가져옴
        res = cls.get_response_cs(image_url, verify=False) 

        # --- 응답 검증 추가 ---
        if res is None:
            P.logger.error(f"image_proxy: SiteUtil.get_response returned None for URL: {image_url}")
            abort(404) # 또는 적절한 에러 응답
            return # 함수 종료
        
        if res.status_code != 200:
            P.logger.warning(f"image_proxy: Received status code {res.status_code} for URL: {image_url}. Content: {res.text[:200]}")
            abort(res.status_code if res.status_code >= 400 else 500)
            return

        content_type_header = res.headers.get('Content-Type', '').lower()
        if not content_type_header.startswith('image/'):
            P.logger.error(f"image_proxy: Expected image Content-Type, but got '{content_type_header}' for URL: {image_url}. Content: {res.text[:200]}")
            abort(400) # 잘못된 요청 또는 서버 응답 오류
            return
        # --- 응답 검증 끝 ---

        try:
            bytes_im = BytesIO(res.content)
            im = Image.open(bytes_im)
            imformat = im.format
            if imformat is None: # Pillow가 포맷을 감지 못하는 경우 (드물지만 발생 가능)
                P.logger.warning(f"image_proxy: Pillow could not determine format for image from URL: {image_url}. Attempting to infer from Content-Type.")
                if 'jpeg' in content_type_header or 'jpg' in content_type_header:
                    imformat = 'JPEG'
                elif 'png' in content_type_header:
                    imformat = 'PNG'
                elif 'webp' in content_type_header:
                    imformat = 'WEBP'
                elif 'gif' in content_type_header:
                    imformat = 'GIF'
                else:
                    P.logger.error(f"image_proxy: Could not infer image format from Content-Type '{content_type_header}'. URL: {image_url}")
                    abort(400)
                    return
            mimetype = im.get_format_mimetype()
            if mimetype is None: # 위에서 imformat을 강제로 설정한 경우 mimetype도 설정
                if imformat == 'JPEG': mimetype = 'image/jpeg'
                elif imformat == 'PNG': mimetype = 'image/png'
                elif imformat == 'WEBP': mimetype = 'image/webp'
                elif imformat == 'GIF': mimetype = 'image/gif'
                else:
                    P.logger.error(f"image_proxy: Could not determine mimetype for inferred format '{imformat}'. URL: {image_url}")
                    abort(400)
                    return

        except UnidentifiedImageError as e: # PIL.UnidentifiedImageError 명시적 임포트 필요
            P.logger.error(f"image_proxy: PIL.UnidentifiedImageError for URL: {image_url}. Response Content-Type: {content_type_header}")
            P.logger.error(f"image_proxy: Error details: {e}")
            # 디버깅을 위해 실패한 이미지 데이터 일부 저장 (선택적)
            try:
                failed_image_path = os.path.join(path_data, "tmp", f"failed_image_{time.time()}.bin")
                with open(failed_image_path, 'wb') as f:
                    f.write(res.content)
                P.logger.info(f"image_proxy: Content of failed image saved to: {failed_image_path}")
            except Exception as save_err:
                P.logger.error(f"image_proxy: Could not save failed image content: {save_err}")
            abort(400) # 잘못된 이미지 파일
            return
        except Exception as e_pil:
            P.logger.error(f"image_proxy: General PIL error for URL: {image_url}: {e_pil}")
            P.logger.error(traceback.format_exc())
            abort(500)
            return

        if mode is not None and mode.startswith("crop_"):
            operations = mode.replace("crop_", "").split('_')
            aspect_ratio = 1.4225
            if operations and operations[-1].replace('.', '', 1).isdigit():
                try:
                    aspect_ratio = float(operations.pop())
                except ValueError:
                    pass

            processed_im = im
            is_first_op = True
            num_ops = len(operations)

            for op in operations:
                new_im = None
                if op in ['r', 'l'] and is_first_op and num_ops > 1:
                    width, height = processed_im.size
                    box = (width / 2, 0, width, height) if op == 'r' else (0, 0, width / 2, height)
                    new_im = processed_im.crop(box)
                else:
                    new_im = SiteUtilAv.imcrop(processed_im, position=op, aspect_ratio=aspect_ratio)

                if processed_im is not im:
                    processed_im.close()
                processed_im = new_im

                if processed_im is None:
                    logger.warning(f"Cropping failed at operation '{op}' for mode '{mode}'. Using original image.")
                    if im.fp: im.fp.seek(0)
                    processed_im = im
                    break

                is_first_op = False
            im = processed_im
        return cls.pil_to_response(im, format=imformat, mimetype=mimetype)


    @classmethod
    def pil_to_response(cls, pil, format="JPEG", mimetype='image/jpeg'):
        with BytesIO() as buf:
            pil.save(buf, format=format, quality=95)
            return Response(buf.getvalue(), mimetype=mimetype)


    @classmethod
    def process_image_data(cls, entity, raw_image_urls, ps_url_from_cache):
        image_mode = cls.config.get('image_mode')
        temp_filepath_to_clean = None

        try:
            # --- 1. 결정에 필요한 모든 정보 수집 (Decision Data) ---
            decision_data = {
                'raw_urls': raw_image_urls,
                'ps_url': ps_url_from_cache,
                'ui_code': entity.ui_code,
                'site_name': cls.site_name,
                'site_config': cls.config,
                'image_mode': image_mode,
                'image_server_paths': {'target_folder': None, 'url_prefix': None},
                'user_files_exist': {'poster': False, 'landscape': False},
                'system_files_exist': {'poster': False, 'landscape': False, 'arts': 0},
                'rewrite_flag': True
            }

            if image_mode == 'image_server' and entity.ui_code:
                # entity에 미리 계산된 경로가 있는지 먼저 확인
                pre_calculated_target_folder = getattr(entity, 'image_server_target_folder', None)
                pre_calculated_url_prefix = getattr(entity, 'image_server_url_prefix', None)

                target_folder = None
                url_prefix = None

                if pre_calculated_target_folder and pre_calculated_url_prefix:
                    # Case 1: 사이트 모듈에서 이미 경로를 계산해 준 경우 (FC2, 1pondo 등)
                    # logger.debug(f"Using pre-calculated image server path from entity: {pre_calculated_target_folder}")
                    target_folder = pre_calculated_target_folder
                    url_prefix = pre_calculated_url_prefix
                else:
                    # Case 2: 경로가 없는 경우 (DMM, JavDB 등), 여기서 경로를 새로 계산
                    # logger.debug("No pre-calculated path found. Calculating image server path in SiteAvBase.")
                    module_prefix = 'jav_censored' if cls.module_char == 'C' else 'jav_uncensored'

                    base_path = cls.config.get('image_server_local_path')
                    url_base = cls.config.get('image_server_url')
                    save_format_key = 'censored_image_format' if cls.module_char == 'C' else 'uncensored_image_format'
                    save_format = cls.config.get(save_format_key)

                    if base_path and url_base and save_format:
                        base_label = getattr(entity, 'label', entity.ui_code.split('-')[0])
                        label_full = base_label

                        # '741'로 시작하는 특수 레이블은 규칙에서 제외
                        if not base_label.upper().startswith('741'):
                            numeric_prefix_match = re.match(r'^(\d+)([A-Z].*)', base_label.upper())
                            if numeric_prefix_match:
                                label_full = numeric_prefix_match.group(2)
                                # logger.debug(f"Numeric prefix label detected: '{base_label}'. Using '{label_full}' for path.")

                        # --- label_1 (첫 글자) 결정 로직 ---
                        label_first = ""
                        # 1. 741로 시작하는 특수 품번 예외 처리
                        if base_label.upper().startswith('741'):
                            label_first = '09'
                            # logger.debug(f"Special '741' prefix label detected: '{base_label}'. Using '09' for label_1.")
                        # 2. entity에 이미 label_1이 설정된 경우 (DMM 등에서 파싱)
                        elif getattr(entity, 'label_1', None):
                            label_first = entity.label_1
                        # 3. 그 외의 경우, 정제된 label_full의 첫 글자 사용
                        elif label_full:
                            label_first = label_full[0]

                        try:
                            # KeyError 방지를 위해 format_map 사용
                            format_map = {'label': label_full, 'label_1': label_first}
                            sub_path = save_format.format_map(format_map).strip('/\\')
                        except KeyError as e:
                            logger.warning(f"Image server save_format error for '{save_format}'. Key {e} not found. Falling back to default.")
                            # 폴백: Uncensored는 레이블, Censored는 첫 글자 사용
                            sub_path = label_full if cls.module_char == 'U' else label_first

                        target_folder = os.path.join(base_path, sub_path)
                        url_prefix = f"{url_base.rstrip('/')}/{sub_path}"

                if target_folder and url_prefix:
                    # 최종 결정된 경로를 decision_data에 할당
                    decision_data['image_server_paths'] = {'target_folder': target_folder, 'url_prefix': url_prefix}

                    # 사용자 및 시스템 파일 존재 여부 확인
                    code_lower = entity.ui_code.lower()
                    supported_extensions = ['jpg', 'png', 'webp']

                    # 사용자 포스터 파일 확인 (발견된 파일명을 저장)
                    for ext in supported_extensions:
                        user_poster_filename = f"{code_lower}_p_user.{ext}"
                        if os.path.exists(os.path.join(target_folder, user_poster_filename)):
                            # True/False가 아닌, 실제 파일명을 저장합니다.
                            decision_data['user_files_exist']['poster'] = user_poster_filename
                            break 

                    # 사용자 랜드스케이프 파일 확인 (발견된 파일명을 저장)
                    for ext in supported_extensions:
                        user_landscape_filename = f"{code_lower}_pl_user.{ext}"
                        if os.path.exists(os.path.join(target_folder, user_landscape_filename)):
                            # True/False가 아닌, 실제 파일명을 저장합니다.
                            decision_data['user_files_exist']['landscape'] = user_landscape_filename
                            break

                    if os.path.exists(os.path.join(target_folder, f"{code_lower}_p.jpg")):
                        decision_data['system_files_exist']['poster'] = True
                    if os.path.exists(os.path.join(target_folder, f"{code_lower}_pl.jpg")):
                        decision_data['system_files_exist']['landscape'] = True

                    if os.path.exists(target_folder):
                        arts_count = len([f for f in os.listdir(target_folder) if f.startswith(f"{code_lower}_art_")])
                        decision_data['system_files_exist']['arts'] = arts_count

                module_prefix = 'jav_censored' if cls.module_char == 'C' else 'jav_uncensored'
                rewrite_str = cls.MetadataSetting.get(f'{module_prefix}_image_server_rewrite')
                if rewrite_str is None:
                    rewrite_str = cls.MetadataSetting.get('jav_censored_image_server_rewrite')
                decision_data['rewrite_flag'] = (rewrite_str == 'True')

            # --- 2. 이미지 소스 결정 위임 ---
            decision_data['final_image_sources'] = cls.determine_final_image_sources(decision_data)
            temp_filepath_to_clean = decision_data['final_image_sources'].get('temp_poster_filepath')

            # --- 3. 최종 이미지 정보 생성 위임 ---
            cls.finalize_images_for_entity(entity, decision_data)

        except Exception as e:
            logger.error(f"Error during process_image_data for {entity.code}: {e}")
            logger.error(traceback.format_exc())
        finally:
            if temp_filepath_to_clean and os.path.exists(temp_filepath_to_clean):
                try:
                    os.remove(temp_filepath_to_clean)
                except Exception as e_remove:
                    logger.error(f"Failed to remove temp file {temp_filepath_to_clean}: {e_remove}")

        return entity


    # --- 이미지 소스 결정 ---
    @classmethod
    def determine_final_image_sources(cls, decision_data):
        """
        명시된 모든 조건을 반영하여 포스터, 랜드스케이프, 팬아트 소스를 최종 결정합니다.
        """
        # --- 1. 모든 로직에서 공통으로 사용할 변수 선언 ---
        ui_code = decision_data['ui_code']
        image_mode = decision_data['image_mode']
        raw_urls = decision_data.get('raw_urls', {})
        ps_url = decision_data.get('ps_url')
        site_config = decision_data.get('site_config', {})
        site_name = decision_data.get('site_name')

        pl_url = raw_urls.get('pl')
        specific_candidates_on_page = raw_urls.get('specific_poster_candidates', [])
        other_arts_on_page = raw_urls.get('arts', [])
        direct_poster_url = raw_urls.get('poster')

        final_image_sources = {
            'poster_source': None, 'poster_mode': None,
            'landscape_source': None, 'arts': [], 'temp_poster_filepath': None,
            'skip_poster_download': False, 'skip_landscape_download': False,
            'is_user_poster': False, 'is_user_landscape': False,
            'processed_from_url': None,
        }

        # imagehash 사용 조건 확인 및 ps_url 조정
        use_advanced_comparison = False
        is_imagehash_installed = False
        
        if cls.config.get('use_imagehash', False):
            try:
                import imagehash
                use_advanced_comparison = True
                is_imagehash_installed = True
            except ImportError:
                is_imagehash_installed = False
        else:
            # 설정이 꺼져 있어도 설치 여부는 확인 (로그 출력용)
            try:
                import imagehash
                is_imagehash_installed = True
            except ImportError:
                is_imagehash_installed = False

        if ps_url and not use_advanced_comparison:
            if not is_imagehash_installed:
                logger.warning("imagehash library not found. Falling back to basic poster selection.")
            else:
                logger.debug("Imagehash is disabled by user setting. Falling back to basic poster selection.")
            ps_url = None # ps_url을 비워서 비교 없는 로직을 타도록 유도

        should_process_poster = True
        should_process_landscape = True

        # --- 2. 처리 필요 여부 사전 결정 (이미지 서버 모드) ---
        if image_mode == 'image_server':
            paths = decision_data['image_server_paths']
            rewrite = decision_data['rewrite_flag']
            code_lower = ui_code.lower()
            
            user_poster_filename = decision_data['user_files_exist']['poster']
            if user_poster_filename:
                final_image_sources['poster_source'] = f"{paths['url_prefix']}/{user_poster_filename}"
                final_image_sources['skip_poster_download'] = True
                final_image_sources['is_user_poster'] = True
                should_process_poster = False
            elif decision_data['system_files_exist']['poster'] and not rewrite:
                final_image_sources['poster_source'] = f"{paths['url_prefix']}/{code_lower}_p.jpg"
                final_image_sources['skip_poster_download'] = True
                should_process_poster = False

            user_landscape_filename = decision_data['user_files_exist']['landscape']
            if user_landscape_filename:
                final_image_sources['landscape_source'] = f"{paths['url_prefix']}/{user_landscape_filename}"
                final_image_sources['skip_landscape_download'] = True
                final_image_sources['is_user_landscape'] = True
                should_process_landscape = False
            elif decision_data['system_files_exist']['landscape'] and not rewrite:
                final_image_sources['landscape_source'] = f"{paths['url_prefix']}/{code_lower}_pl.jpg"
                final_image_sources['skip_landscape_download'] = True
                should_process_landscape = False

        # --- 3. 포스터 소스 결정 ---
        if should_process_poster:
            # logger.debug(f"Determining poster source for {ui_code} as no user/system file exists or rewrite is on.")
            
            if direct_poster_url:
                # logger.debug(f"Using pre-determined poster URL for {ui_code}.")
                final_image_sources['poster_source'] = direct_poster_url
                
                # URL이 http로 시작할 때만 스마트 크롭 예약.
                # 로컬 파일 경로라면 이미 처리된 것이므로 모드를 'local_file'로 설정.
                if direct_poster_url.startswith('http'):
                    if cls.config.get('use_smart_crop'):
                        final_image_sources['poster_mode'] = 'smart_crop'
                else:
                    final_image_sources['poster_mode'] = 'local_file'
                    temp_dir = os.path.join(path_data, "tmp")
                    if os.path.commonpath([temp_dir, os.path.abspath(direct_poster_url)]) == temp_dir:
                        final_image_sources['temp_poster_filepath'] = direct_poster_url

            # PS가 있는 다른 모든 사이트를 위한 공통 로직
            elif ps_url:
                # Case 2: Censored와 같이 ps_url을 기반으로 복잡한 결정이 필요한 경우
                # 1. (설정) ps_force_labels 확인 (ps_url 직접 사용)
                apply_ps_to_poster = False
                label_from_ui_code = ui_code.split('-', 1)[0] if '-' in ui_code else (re.match(r'([A-Z]+)', ui_code.upper()).group(1) if re.match(r'([A-Z]+)', ui_code.upper()) else '')
                if label_from_ui_code:
                    if site_config.get('ps_force_labels_set') and label_from_ui_code in site_config['ps_force_labels_set']:
                        apply_ps_to_poster = True

                if apply_ps_to_poster:
                    final_image_sources['poster_source'] = ps_url

                # PS 이미지 객체 생성 (전체 로직에서 공통 사용)
                im_sm_obj = cls.imopen(ps_url)
                
                try:
                    if not final_image_sources['poster_source'] and im_sm_obj:
                        # [공통] PL 유효성 및 높이 확인 (미리 수행)
                        pl_height = 0
                        pl_valid = False
                        
                        if pl_url:
                            try:
                                im_pl_obj = cls.imopen(pl_url)
                                if im_pl_obj:
                                    pl_height = im_pl_obj.height
                                    # PL이 PS를 포함하는지 확인 (표준 비율로 크롭 시도)
                                    standard_aspect_ratio = 1.4225
                                    pos = cls.has_hq_poster(im_sm_obj, im_pl_obj, aspect_ratio=standard_aspect_ratio)
                                    if pos: pl_valid = True
                                    im_pl_obj.close()
                            except: pass

                        # 2. (자동 탐색) 우선 후보군 탐색
                        poster_candidates_simple = ([pl_url] if pl_url else []) + specific_candidates_on_page
                        
                        for candidate_url in poster_candidates_simple:
                            im_lg_obj = None
                            try:
                                im_lg_obj = cls.imopen(candidate_url)
                                if im_lg_obj and cls.is_hq_poster(im_sm_obj, im_lg_obj):
                                    # [검증] PL이 유효하고 더 고화질이라면, 저화질 후보 스킵
                                    if pl_valid and pl_height > im_lg_obj.height:
                                        # logger.debug(f"Skipping low-res candidate ({im_lg_obj.height} < {pl_height}): {candidate_url}")
                                        continue

                                    logger.debug(f"Found ideal poster (visually same as thumbnail): {candidate_url}")
                                    final_image_sources['poster_source'] = candidate_url
                                    break
                            finally:
                                if im_lg_obj: im_lg_obj.close()

                        # 3. (자동 탐색) 확장 후보군 탐색
                        if not final_image_sources['poster_source']:
                            all_candidates_advanced = list(dict.fromkeys(([pl_url] if pl_url else []) + other_arts_on_page))
                            standard_aspect_ratio = 1.4225

                            # Phase 1: 확장 후보군에 대해 is_hq_poster로 먼저 빠르게 검사
                            for candidate_url in all_candidates_advanced:
                                im_lg_obj = None
                                try:
                                    im_lg_obj = cls.imopen(candidate_url)
                                    if im_lg_obj and cls.is_hq_poster(im_sm_obj, im_lg_obj):
                                        # [검증] PL이 유효하고 더 고화질이라면, 저화질 후보 스킵
                                        if pl_valid and pl_height > im_lg_obj.height:
                                            # logger.debug(f"Skipping low-res advanced candidate ({im_lg_obj.height} < {pl_height}): {candidate_url}")
                                            continue

                                        logger.debug(f"HQ Poster Found in advanced Phase 1: {candidate_url}")
                                        final_image_sources['poster_source'] = candidate_url
                                        break
                                finally:
                                    if im_lg_obj: im_lg_obj.close()

                            # Phase 2: Phase 1에서 못 찾았을 경우 상세 분석
                            if not final_image_sources['poster_source']:
                                for candidate_url in all_candidates_advanced:
                                    im_lg_obj = cls.imopen(candidate_url)
                                    if not im_lg_obj: continue

                                    found_poster_for_this_candidate = False
                                    try:
                                        w, h = im_lg_obj.size
                                        aspect_ratio = w / h if h > 0 else 0
                                        crop_pos = None

                                        # 1순위: 고화질 이미지 레터박스 처리 시도
                                        if abs(aspect_ratio - (4/3)) < 0.05:
                                            processed_lg_obj = None
                                            final_poster = None
                                            try:
                                                top_crop = int(h * 0.0567)
                                                bottom_crop = h - top_crop
                                                box = (0, top_crop, w, bottom_crop)

                                                cropped_view = im_lg_obj.crop(box)
                                                processed_lg_obj = cropped_view.copy()
                                                cropped_view.close()

                                                pos = cls.has_hq_poster(im_sm_obj, processed_lg_obj, aspect_ratio=standard_aspect_ratio)

                                                if pos:
                                                    final_poster = SiteUtilAv.imcrop(processed_lg_obj, position=pos, aspect_ratio=standard_aspect_ratio)

                                                    if final_poster:
                                                        temp_filepath = cls.save_pil_to_temp(final_poster)

                                                        if temp_filepath:
                                                            final_image_sources['poster_source'] = temp_filepath
                                                            final_image_sources['poster_mode'] = 'local_file'
                                                            final_image_sources['temp_poster_filepath'] = temp_filepath
                                                            final_image_sources['processed_from_url'] = candidate_url

                                                            found_poster_for_this_candidate = True
                                                            logger.debug(f"HQ Poster Found (Letterbox Processed): Saved to {temp_filepath}")
                                                        else:
                                                            logger.error("Failed to save the final cropped poster to a temporary file.")
                                            finally:
                                                if processed_lg_obj: processed_lg_obj.close()
                                                if final_poster: final_poster.close()

                                        # 2, 3순위는 1순위에서 찾지 못했을 경우에만 실행
                                        if not found_poster_for_this_candidate:
                                            # 2순위: 1.7:1 이상 와이드 이미지 처리
                                            if aspect_ratio >= 1.7:
                                                sm_w, sm_h = im_sm_obj.size
                                                sm_aspect = sm_h / sm_w if sm_w > 0 else standard_aspect_ratio
                                                with im_lg_obj.crop((w / 2, 0, w, h)) as right_half_obj:
                                                    sub_pos = cls.has_hq_poster(im_sm_obj, right_half_obj, aspect_ratio=sm_aspect)
                                                    if sub_pos:
                                                        crop_pos = f"r_{sub_pos}_{sm_aspect:.4f}"
                                                        logger.debug(f"HQ Poster Found (Wide_R): using mode {crop_pos}")
                                                if not crop_pos:
                                                    with im_lg_obj.crop((0, 0, w / 2, h)) as left_half_obj:
                                                        sub_pos = cls.has_hq_poster(im_sm_obj, left_half_obj, aspect_ratio=sm_aspect)
                                                        if sub_pos:
                                                            crop_pos = f"l_{sub_pos}_{sm_aspect:.4f}"
                                                            logger.debug(f"HQ Poster Found (Wide_L): using mode {crop_pos}")
                                                if not crop_pos:
                                                    with im_sm_obj.crop((0, sm_h * 0.07, sm_w, sm_h * 0.93)) as cropped_sm_obj:
                                                        sm_w_new, sm_h_new = cropped_sm_obj.size
                                                        sm_aspect_new = sm_h_new / sm_w_new if sm_w_new > 0 else standard_aspect_ratio
                                                        single_pos = cls.has_hq_poster(cropped_sm_obj, im_lg_obj, aspect_ratio=sm_aspect_new)
                                                        if single_pos:
                                                            crop_pos = f"{single_pos}_{sm_aspect_new:.4f}"
                                                            logger.debug(f"HQ Poster Found (Thumb_Lbox): using mode {crop_pos}")

                                            # 3순위: 원본 이미지 자체에 대한 일반적인 CRL 비교 시도
                                            if not crop_pos:
                                                single_pos = cls.has_hq_poster(im_sm_obj, im_lg_obj, aspect_ratio=standard_aspect_ratio)
                                                if single_pos:
                                                    crop_pos = f"{single_pos}_{standard_aspect_ratio:.4f}"
                                                    logger.debug(f"HQ Poster Found (Standard): using mode {crop_pos}")

                                            if crop_pos:
                                                logger.debug(f"HQ Poster Found Matched in Advanced Phase 2: '{candidate_url}' using mode '{crop_pos}'.")
                                                final_image_sources.update({'poster_source': candidate_url, 'poster_mode': f"crop_{crop_pos}"})
                                                found_poster_for_this_candidate = True
                                    finally:
                                        if im_lg_obj: im_lg_obj.close()

                                    if found_poster_for_this_candidate:
                                        break
                finally:
                    if im_sm_obj: im_sm_obj.close()

                # 4. (수동 설정) 모든 자동 탐색 실패 시, 강제 크롭 모드 적용
                if not final_image_sources['poster_source']:
                    forced_crop_mode = None
                    if site_config.get('crop_mode'):
                        for line in site_config['crop_mode']:
                            parts = [x.strip() for x in line.split(":", 1)]
                            if len(parts) == 2 and parts[0].upper() == label_from_ui_code and parts[1].lower() in "rlc":
                                forced_crop_mode = parts[1].lower()
                                break
                    if forced_crop_mode and pl_url:
                        final_image_sources.update({'poster_source': pl_url, 'poster_mode': f"crop_{forced_crop_mode}"})

            else:
                # Case 3: JavDB와 같이 ps_url 없이 pl/arts로 결정해야 하는 경우
                # 1. (자동 탐색) 고화질 세로 이미지 우선 탐색
                portrait_found = False
                for candidate_url in specific_candidates_on_page:
                    if cls.is_portrait_high_quality_image(cls.imopen(candidate_url)):
                        final_image_sources['poster_source'] = candidate_url
                        portrait_found = True
                        logger.debug(f"Found & using portrait HQ poster: {candidate_url}")
                        break

                # 2. (수동 설정) 세로 이미지가 없을 경우, 강제 크롭 모드 적용
                if not portrait_found: # final_image_sources['poster_source'] 대신 portrait_found 플래그 사용
                    forced_crop_mode = None
                    label = ui_code.split('-', 1)[0]
                    if label and site_config.get('crop_mode'):
                        for rule in site_config['crop_mode']:
                            # JavDB는 '='를 사용한다고 가정.
                            parts = [x.strip() for x in rule.split(":", 1)]
                            if len(parts) == 2 and parts[0].upper() == label.upper() and parts[1].lower() in "rlc":
                                forced_crop_mode = parts[1].lower()
                                break
                    if forced_crop_mode and pl_url:
                        final_image_sources.update({'poster_source': pl_url, 'poster_mode': f"crop_{forced_crop_mode}"})
                        logger.debug(f"Applying forced crop mode: {pl_url}, (crop_mode: crop_{forced_crop_mode})")

                # 3. 비율에 따른 크롭 규칙
                if not final_image_sources.get('poster_source'):
                    if pl_url:
                        try:
                            im_lg_obj = cls.imopen(pl_url)
                            w, h = im_lg_obj.size
                            aspect_ratio = w / h if h > 0 else 0

                            # 1. 4:3 비율 (레터박스 가능성)
                            if abs(aspect_ratio - (4/3)) < 0.05:
                                im_no_lb = im_lg_obj.crop((0, int(h * 0.0533), w, h - int(h * 0.0533)))
                                processed_im = SiteUtilAv.imcrop(im_no_lb, position='r')
                                temp_filepath = cls.save_pil_to_temp(processed_im)
                                if temp_filepath:
                                    logger.debug(f"Image for {ui_code} has aspect ratio = 4:3. Applying 'Remove Letterbox & crop_r'.")
                                    final_image_sources.update({'poster_source': temp_filepath, 'poster_mode': 'local_file', 'temp_poster_filepath': temp_filepath, 'processed_from_url': pl_url})
                                processed_im.close(); im_no_lb.close()

                            # 2. 1.7:1 이상 와이드 (MG-Style)
                            elif aspect_ratio >= 1.7:
                                logger.debug(f"Image for {ui_code} has aspect ratio >= 1.7. Applying 'crop_r_c'.")
                                # 최종 크롭 연산을 poster_mode에 기록
                                final_image_sources.update({'poster_source': pl_url, 'poster_mode': 'crop_r_c'})

                            # 3. 4:3 비율 미만 (가로가 충분히 넓지 않음)
                            elif aspect_ratio < (4/3 - 0.05):
                                logger.debug(f"Image for {ui_code} has aspect ratio < 4:3. Applying 'crop_c'.")
                                final_image_sources.update({'poster_source': pl_url, 'poster_mode': 'crop_c'})

                            # 4. 그 외 나머지 (4:3 ~ 1.7:1 사이의 일반적인 가로 이미지)
                            else:
                                logger.debug(f"Image for {ui_code} has standard landscape ratio. Applying 'crop_r'.")
                                final_image_sources.update({'poster_source': pl_url, 'poster_mode': 'crop_r'})
                        finally:
                            if im_lg_obj: im_lg_obj.close()

            # 최종 폴백: 어떤 조건도 만족하지 못하면 PS 이미지를 포스터로 사용
            if not final_image_sources.get('poster_source') and ps_url:
                final_image_sources['poster_source'] = ps_url

        # --- 4. 랜드스케이프 소스 결정 (필요한 경우에만) ---
        if should_process_landscape:
            # logger.debug(f"Determining landscape source for {ui_code} as no user/system file exists or rewrite is on.")
            final_image_sources['landscape_source'] = pl_url

        # --- 5. 팬아트 목록 결정 ---
        if image_mode != 'image_server' or decision_data['rewrite_flag']:
            final_thumb_source_urls = set()
            if final_image_sources.get('landscape_source'):
                final_thumb_source_urls.add(final_image_sources['landscape_source'])

            poster_source = final_image_sources.get('poster_source')
            if poster_source:
                if final_image_sources.get('poster_mode') == 'local_file':
                    processed_from = final_image_sources.get('processed_from_url')
                    if processed_from: final_thumb_source_urls.add(processed_from)
                elif isinstance(poster_source, str) and poster_source.startswith('http'):
                    final_thumb_source_urls.add(poster_source)

            all_potential_arts = list(dict.fromkeys(other_arts_on_page + ([pl_url] if pl_url else [])))

            final_fanarts = []
            exclude_set = set(final_thumb_source_urls)
            for art_url in all_potential_arts:
                if art_url and art_url not in exclude_set:
                    final_fanarts.append(art_url)

            max_arts = site_config.get('max_arts', 0)
            final_image_sources['arts'] = final_fanarts[:max_arts] if max_arts > 0 else []

        return final_image_sources


    @classmethod
    def save_pil_to_temp(cls, pil_obj):
        """PIL 객체를 임시 파일로 저장하고 경로를 반환합니다."""
        try:
            temp_dir = os.path.join(path_data, "tmp")
            os.makedirs(temp_dir, exist_ok=True)
            filename = f"temp_poster_{int(time.time())}_{os.urandom(4).hex()}.jpg"
            filepath = os.path.join(temp_dir, filename)

            img_to_save = pil_obj
            if pil_obj.mode != 'RGB':
                img_to_save = pil_obj.convert('RGB')

            img_to_save.save(filepath, "JPEG", quality=95)
            logger.debug(f"Saved temporary poster to: {filepath}")
            return filepath
        except Exception as e:
            logger.error(f"Failed to save PIL to temp file: {e}")
            return None


    # 의미상 메타데이터에서 처리해야한다.
    # 귀찮아서 일단 여기서 처리
    # 이미지 처리모드는 기본(ff_proxy)와 discord_proxy, image_server가 있다.
    # 오리지널은 proxy사용 여부에 따라 ff_proxy에서 판단한다.
    @classmethod
    def finalize_images_for_entity(cls, entity, decision_data):
        if entity.thumb is None: entity.thumb = []
        if entity.fanart is None: entity.fanart = []

        image_mode = decision_data['image_mode']
        image_sources = decision_data['final_image_sources']

        poster_source = image_sources.get('poster_source')
        poster_mode = image_sources.get('poster_mode', '')
        landscape_source = image_sources.get('landscape_source')
        arts = image_sources.get('arts', [])

        if not image_sources or not poster_source:
            return

        # 안전하게 jav_image 호출 헬퍼
        def safe_jav_image(url, mode=None, site=None):
            try:
                from werkzeug.exceptions import HTTPException
                return cls.jav_image(url=url, mode=mode, site=site)
            except HTTPException as e:
                logger.debug(f"Image processing failed (HTTP {e.code}) for {url}")
                return None
            except Exception as e:
                logger.error(f"Image processing error for {url}: {e}")
                return None

        if image_mode == 'ff_proxy':
            # proxy를 사용하거나, mode가 있거나, 로컬 파일인 경우 ff_proxy URL 생성
            if cls.config['use_proxy'] or poster_mode:
                if poster_mode == 'local_file':
                    # 사전 처리된 로컬 파일인 경우
                    param = {'site': 'system', 'path': poster_source}
                else:
                    # 원격 URL이거나, 원격 URL에 crop 모드가 적용된 경우
                    param = {'site': cls.site_name, 'url': unquote_plus(poster_source), 'mode': poster_mode}

                if not param.get('mode'):
                    param.pop('mode', None)

                param_str = urlencode(param)
                module_prefix = 'jav_image' if cls.module_char == 'C' else 'jav_image_un'
                url = f"{F.SystemModelSetting.get('ddns')}/metadata/normal/{module_prefix}?{param_str}"
            else:
                # 프록시도, 모드도 없는 순수 원격 URL
                url = poster_source
            entity.thumb.append(EntityThumb(aspect="poster", value=url))

            if landscape_source:
                if cls.config['use_proxy']:
                    param = urlencode({'site': cls.site_name, 'url': unquote_plus(landscape_source)})
                    module_prefix = 'jav_image' if cls.module_char == 'C' else 'jav_image_un'
                    url = f"{F.SystemModelSetting.get('ddns')}/metadata/normal/{module_prefix}?{param}"
                else:
                    url = landscape_source
                entity.thumb.append(EntityThumb(aspect="landscape", value=url))

            for art_url in arts:
                if cls.config['use_proxy']:
                    param = urlencode({'site': cls.site_name, 'url': unquote_plus(art_url)})
                    module_prefix = 'jav_image' if cls.module_char == 'C' else 'jav_image_un'
                    url = f"{F.SystemModelSetting.get('ddns')}/metadata/normal/{module_prefix}?{param}"
                else:
                    url = art_url
                entity.fanart.append(url)

        elif image_mode == 'discord_proxy':
            def apply(url, use_proxy_server, server_url):
                if not use_proxy_server:
                    return url
                if url and '/attachments/' in url:
                    return server_url.rstrip('/') + '/attachments/' + url.split('/attachments/')[1]
                return url

            use_proxy_server = cls.MetadataSetting.get('jav_censored_use_discord_proxy_server') == 'True'
            server_url = cls.MetadataSetting.get('jav_censored_discord_proxy_server_url')
            use_my_webhook = cls.MetadataSetting.get('jav_censored_use_my_webhook') == 'True'
            webhook_list = cls.MetadataSetting.get_list('jav_censored_my_webhook_list')
            webhook_url = None

            # --- 포스터 처리 ---
            response_bytes = None
            if poster_mode == 'local_file':
                try:
                    with open(poster_source, 'rb') as f:
                        response_bytes = BytesIO(f.read())
                except Exception as e:
                    logger.error(f"Failed to read local file for discord: {e}")
            else:
                response = safe_jav_image(url=poster_source, mode=poster_mode, site=cls.site_name)
                if response: response_bytes = BytesIO(response.data)

            if response_bytes:
                if use_my_webhook and webhook_list:
                    webhook_url = webhook_list[random.randint(0, len(webhook_list) - 1)]
                discord_url = SupportDiscord.discord_proxy_image_bytes(response_bytes, webhook_url=webhook_url)
                final_url = apply(discord_url, use_proxy_server, server_url)
                entity.thumb.append(EntityThumb(aspect="poster", value=final_url))

            # --- 랜드스케이프 처리 ---
            if landscape_source:
                response = safe_jav_image(url=landscape_source, site=cls.site_name)
                if response:
                    response_bytes = BytesIO(response.data)
                    if use_my_webhook and webhook_list:
                        webhook_url = webhook_list[random.randint(0, len(webhook_list) - 1)]
                    discord_url = SupportDiscord.discord_proxy_image_bytes(response_bytes, webhook_url=webhook_url)
                    final_url = apply(discord_url, use_proxy_server, server_url)
                    entity.thumb.append(EntityThumb(aspect="landscape", value=final_url))

            # --- 팬아트 처리 ---
            for art_url in arts:
                response = safe_jav_image(url=art_url, site=cls.site_name)
                if response:
                    response_bytes = BytesIO(response.data)
                    if use_my_webhook and webhook_list:
                        webhook_url = webhook_list[random.randint(0, len(webhook_list) - 1)]
                    discord_url = SupportDiscord.discord_proxy_image_bytes(response_bytes, webhook_url=webhook_url)
                    final_url = apply(discord_url, use_proxy_server, server_url)
                    entity.fanart.append(final_url)

        elif image_mode == 'image_server':
            image_server_paths = decision_data.get('image_server_paths', {})
            target_folder = image_server_paths.get('target_folder')
            server_url_prefix = image_server_paths.get('url_prefix')
            rewrite = decision_data.get('rewrite_flag', True)
            system_files_exist = decision_data.get('system_files_exist', {})
            code_lower = entity.ui_code.lower()

            if not target_folder or not server_url_prefix:
                logger.error(f"Image Server Error: 'target_folder' or 'url_prefix' not available for {entity.ui_code}")
                return

            # --- 포스터 처리 ---
            poster_source = image_sources.get('poster_source')
            if poster_source:
                if image_sources.get('skip_poster_download'):
                    entity.thumb.append(EntityThumb(aspect="poster", value=poster_source))
                else: # 다운로드 필요
                    system_poster_path = os.path.join(target_folder, f"{code_lower}_p.jpg")
                    os.makedirs(target_folder, exist_ok=True)
                    source_mode = image_sources.get('poster_mode')
                    
                    save_success = False
                    if source_mode == 'local_file':
                        try:
                            with open(poster_source, 'rb') as f:
                                if not cls._save_image_as_jpeg(BytesIO(f.read()), system_poster_path):
                                    import shutil
                                    shutil.copy(poster_source, system_poster_path)
                            save_success = True
                        except Exception as e_read_local:
                            logger.error(f"Failed to read local file {poster_source}: {e_read_local}")
                    else:
                        response = safe_jav_image(url=poster_source, mode=source_mode, site=cls.site_name)
                        if response and response.status_code == 200:
                            if not cls._save_image_as_jpeg(BytesIO(response.data), system_poster_path):
                                with open(system_poster_path, 'wb') as f: f.write(response.data)
                            save_success = True
                        else:
                            logger.error(f"Failed to download poster for {code_lower} from {poster_source}")
                    
                    # 파일 저장 성공 시 또는 파일이 존재할 시 엔티티 추가
                    if save_success or os.path.exists(system_poster_path):
                        entity.thumb.append(EntityThumb(aspect="poster", value=f"{server_url_prefix}/{code_lower}_p.jpg"))

            # --- 랜드스케이프 처리 ---
            landscape_source = image_sources.get('landscape_source')
            if landscape_source:
                if image_sources.get('skip_landscape_download'):
                    entity.thumb.append(EntityThumb(aspect="landscape", value=landscape_source))
                else: 
                    system_landscape_path = os.path.join(target_folder, f"{code_lower}_pl.jpg")
                    os.makedirs(target_folder, exist_ok=True)
                    
                    save_success = False
                    response = safe_jav_image(url=landscape_source, site=cls.site_name)
                    if response and response.status_code == 200:
                        if not cls._save_image_as_jpeg(BytesIO(response.data), system_landscape_path):
                            with open(system_landscape_path, 'wb') as f: f.write(response.data)
                        save_success = True
                    else:
                        logger.warning(f"Failed to download landscape for {code_lower} from {landscape_source}")
                    
                    # 파일 저장 성공 시 또는 파일이 존재할 시 엔티티 추가
                    if save_success or os.path.exists(system_landscape_path):
                        entity.thumb.append(EntityThumb(aspect="landscape", value=f"{server_url_prefix}/{code_lower}_pl.jpg"))

            # --- 팬아트 처리 ---
            if rewrite or system_files_exist.get('arts', 0) == 0:
                if rewrite and os.path.exists(target_folder):
                    for f in os.listdir(target_folder):
                        if f.startswith(f"{code_lower}_art_"):
                            try: os.remove(os.path.join(target_folder, f))
                            except: pass

                for idx, art_url in enumerate(image_sources.get('arts', [])):
                    filename = f"{code_lower}_art_{idx+1}.jpg"
                    filepath = os.path.join(target_folder, filename)
                    os.makedirs(os.path.dirname(filepath), exist_ok=True)
                    
                    response = safe_jav_image(url=art_url, site=cls.site_name)
                    if response and response.status_code == 200:
                        if cls._save_image_as_jpeg(BytesIO(response.data), filepath):
                            pass
                        else:
                            with open(filepath, 'wb') as f: f.write(response.data)
                        entity.fanart.append(f"{server_url_prefix}/{os.path.basename(filepath)}")
                    else:
                        logger.error(f"Failed to download art for {code_lower} from {art_url}")
            else:
                if os.path.exists(target_folder):
                    for filename in sorted(os.listdir(target_folder)):
                        if filename.startswith(f"{code_lower}_art_"):
                            entity.fanart.append(f"{server_url_prefix}/{filename}")

        logger.info(f"[ImageUtil] 이미지 최종 처리 완료. Thumbs: {len(entity.thumb)}, Fanarts: {len(entity.fanart)}")


    # endregion 이미지 처리 관련
    ################################################


    ################################################
    # region SiteUtilAV 이미지 처리 관련
    @classmethod
    def is_portrait_high_quality_image(cls, img_pil_object, min_height=600, aspect_ratio_threshold=1.2):
        """주어진 PIL Image 객체가 세로형 고화질 이미지인지 판단합니다."""
        if not img_pil_object: return False
        try:
            width, height = img_pil_object.size
            if width == 0: return False
            return height >= min_height and (height / width) >= aspect_ratio_threshold
        except Exception: return False


    @classmethod
    def is_hq_poster(cls, im_sm_obj, im_lg_obj):
        """두 PIL Image 객체의 시각적 유사성을 판단합니다."""
        try:
            from imagehash import dhash as hfun, phash
        except ImportError:
            return False

        try:
            if im_sm_obj is None or im_lg_obj is None: return False

            ws, hs = im_sm_obj.size; wl, hl = im_lg_obj.size
            if hs == 0 or hl == 0: return False
            if abs((ws / hs) - (wl / hl)) > 0.1: return False

            hdis_d = hfun(im_sm_obj) - hfun(im_lg_obj)
            if hdis_d >= 10: return False
            if hdis_d <= 5: return True

            hdis_p = phash(im_sm_obj) - phash(im_lg_obj)
            threshold = cls.config.get('hq_poster_threshold_strict')
            return (hdis_d + hdis_p) < threshold
        except Exception: return False


    @classmethod
    def has_hq_poster(cls, im_sm_obj, im_lg_obj, aspect_ratio):
        """두 PIL Image 객체를 받아 크롭 영역 일치 여부를 판단하고 크롭 위치를 반환합니다."""
        try:
            from imagehash import phash, average_hash
        except ImportError:
            return None

        try:
            if im_sm_obj is None or im_lg_obj is None: return None

            ws, hs = im_sm_obj.size; wl, hl = im_lg_obj.size
            if ws > wl or hs > hl: return None

            positions = ["c", "r", "l"]
            threshold = cls.config.get('hq_poster_threshold_normal')

            for pos in positions:
                cropped_im = None
                try:
                    cropped_im = SiteUtilAv.imcrop(im_lg_obj, position=pos, aspect_ratio=aspect_ratio)
                    if cropped_im is None: continue

                    # average_hash와 phash를 조합하여 비교
                    dist_a = average_hash(im_sm_obj) - average_hash(cropped_im)
                    dist_p = phash(im_sm_obj) - phash(cropped_im)

                    if (dist_a + dist_p) < threshold:
                        return pos
                finally:
                    if cropped_im: cropped_im.close()
            return None
        except Exception as e:
            logger.debug(f"has_hq_poster exception: {e}")
            return None


    # endregion SiteUtilAV 이미지 처리 관련
    ################################################


    ################################################
    # region 유틸


    @classmethod
    def _parse_ui_code(cls, cid_part_raw: str, content_type: str = 'unknown') -> tuple:
        if not cls.config or 'censored_parser_rules' not in cls.config:
            logger.warning("Censored UI Code Parser rules not loaded in config.")
            ui_code = cid_part_raw.upper()
            label_part = ui_code.split('-')[0].lower() if '-' in ui_code else ui_code.lower()
            return ui_code, label_part, ""

        # CID 전처리
        processed_cid = cid_part_raw.lower().strip()
        processed_cid = re.sub(r'^[hn]_\d', '', processed_cid)
        suffix_strip_match = re.match(r'^(.*\d+)([a-z]+)$', processed_cid, re.I)
        if suffix_strip_match:
            processed_cid = suffix_strip_match.group(1)

        # 파싱 변수 초기화
        final_label_part, final_num_part, final_search_label_part, rule_applied = "", "", "", False
        special_rules = cls.config.get('censored_parser_rules', [])
        generic_rules = cls.config.get('generic_parser_rules', [])
        all_rules = special_rules + generic_rules

        for line in all_rules:
            line = line.strip()
            if not line or line.startswith('#'):
                continue

            parts = line.split('=>')
            if len(parts) != 2:
                logger.warning(f"Invalid rule format (expected 'pattern => template'): {line}")
                continue

            pattern, template = parts[0].strip(), parts[1].strip()

            try:
                match = re.match(pattern, processed_cid, re.I)
                if match:
                    template_parts = template.split('|')
                    if len(template_parts) < 2: continue

                    label_template = template_parts[0]
                    num_template = template_parts[1]
                    # 검색용 템플릿이 있는지 확인 (선택 사항)
                    search_label_template = template_parts[2] if len(template_parts) > 2 else None

                    groups = match.groups()
                    groups = tuple('' if g is None else g for g in groups)
                    final_label_part = label_template.format(*groups)
                    final_num_part = num_template.format(*groups)

                    # 검색용 템플릿이 있으면 그것으로 final_search_label_part를 채움
                    if search_label_template:
                        final_search_label_part = search_label_template.format(*groups)

                    rule_applied = True
                    break
            except (re.error, IndexError) as e:
                logger.error(f"Error applying rule: '{line}' - {e}")

        # 모든 규칙에 실패했을 경우의 최후의 폴백
        if not rule_applied:
            logger.debug(f"UI Code Parser: No rule matched for '{processed_cid}'. Falling back.")
            
            match_fallback = re.match(r'^([0-9a-z]+)-(\d+)$', processed_cid, re.I)
            if match_fallback:
                final_label_part = match_fallback.group(1)
                final_num_part = match_fallback.group(2)
                logger.debug(f"UI Code Parser Fallback: Hyphen split successful -> Label:'{final_label_part}', Num:'{final_num_part}'")
            else:
                final_label_part, final_num_part = processed_cid, ""

        # === 최종 값 조합 ===
        label_ui_part = final_label_part.upper().strip('-')

        # --- 숫자 부분 처리 분기 ---
        if final_num_part.isdigit():
            num_stripped = final_num_part.lstrip('0') or "0"
            num_ui_part = num_stripped.zfill(3)
        else:
            num_ui_part = final_num_part.upper().strip('-')

        # 최종 UI 코드 조합
        if label_ui_part and num_ui_part:
            ui_code_final = f"{label_ui_part}-{num_ui_part}"
        else:
            ui_code_final = label_ui_part or cid_part_raw.upper()

        # 반환값 준비
        score_label_part = final_search_label_part.lower() if final_search_label_part else final_label_part.lower()
        score_num_raw_part = final_num_part

        # logger.debug(f"UI Code Parser: Parsed '{cid_part_raw}' > '{pattern}' > Final: '{ui_code_final}'")
        return ui_code_final, score_label_part, score_num_raw_part


    @classmethod
    def _parse_ui_code_uncensored(cls, cid_part_raw: str) -> str:
        """
        Uncensored 품번을 파싱하고 표준화된 UI 코드를 반환합니다.
        (예: 'fc2-ppv-1234567' -> 'FC2-1234567')
        """
        if not cls.config or 'uncensored_parser_rules' not in cls.config:
            logger.warning("Uncensored UI Code Parser rules not loaded in config. Using raw value.")
            return cid_part_raw.upper()

        processed_cid = cid_part_raw.lower().strip()
        processed_cid = re.sub(r'\.\w+$', '', processed_cid)
        processed_cid = re.sub(r'[\[\(].*?[\]\)]', '', processed_cid).strip()

        final_label_part, final_num_part, rule_applied = "", "", False
        
        special_rules = cls.config.get('uncensored_parser_rules', [])
        generic_rules = cls.config.get('generic_parser_rules', [])
        all_rules = special_rules + generic_rules

        # logger.debug(f"[{cls.site_name}] _parse_ui_code_uncensored started for '{cid_part_raw}'. Using {len(special_rules)} special + {len(generic_rules)} generic rules.")

        for line in all_rules:
            line = line.strip()
            if not line or line.startswith('#'): continue

            parts = line.split('=>')
            if len(parts) != 2:
                logger.warning(f"Invalid rule format (expected 'pattern => template'): {line}")
                continue

            pattern, template = parts[0].strip(), parts[1].strip()
            try:
                match = re.match(pattern, processed_cid, re.I)
                if match:
                    template_parts = template.split('|')
                    if len(template_parts) != 2: continue

                    label_template, num_template = template_parts
                    groups = match.groups()
                    final_label_part = label_template.format(*groups).strip()
                    final_num_part = num_template.format(*groups).strip()
                    rule_applied = True
                    # logger.debug(f"Uncensored Parser: Matched Rule '{pattern}' -> Label:'{final_label_part}', Num:'{final_num_part}'")
                    break
            except Exception as e:
                logger.error(f"Error applying uncensored rule: '{line}' - {e}")

        if not rule_applied:
            logger.debug(f"Uncensored Parser: No rule matched for '{processed_cid}'. Falling back.")
            final_label_part, final_num_part = processed_cid, ""

        label_ui_part = final_label_part.upper().strip('-_ ')
        num_ui_part = final_num_part.upper().strip('-_ ')

        if label_ui_part and num_ui_part:
            ui_code_final = f"{label_ui_part}-{num_ui_part}"
        else:
            ui_code_final = label_ui_part or cid_part_raw.upper()

        logger.debug(f"Uncensored Parser: Parsed '{cid_part_raw}' -> Final UI Code: '{ui_code_final}'")
        return ui_code_final


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
    def get_translated_tag(cls, tag_type, tag):
        tags_json = os.path.join(os.path.dirname(os.path.dirname(__file__)), "tags.json")
        with open(tags_json, "r", encoding="utf8") as f:
            tags = json.load(f)

        if tag_type not in tags:
            return tag

        if tag in tags[tag_type]:
            return tags[tag_type][tag]

        trans_text = cls.trans(tag, source="ja", target="ko")
        # logger.debug(f'태그 번역: {tag} - {trans_text}')
        if SiteUtilAv.is_include_hangul(trans_text) or trans_text.replace(" ", "").isalnum():
            tags[tag_type][tag] = trans_text

            with open(tags_json, "w", encoding="utf8") as f:
                json.dump(tags, f, indent=4, ensure_ascii=False)

            res = tags[tag_type][tag]
        else:
            res = tag

        return res


    @classmethod
    def _calculate_score(cls, original_keyword, item_ui_code):
        """
        모든 사이트에서 사용하는 표준 점수 계산기.
        """
        try:
            # [1단계: 표준화] 키워드를 표준 UI Code로 변환
            kw_ui_code, _, _ = cls._parse_ui_code(original_keyword)
            # item_ui_code는 이미 표준화된 상태로 전달됨

            # [2단계: 분할] UI Code를 '레이블 파트'와 '넘버 파트'로 분할
            kw_label_part, kw_num_part = (kw_ui_code.split('-', 1) + [''])[:2] if '-' in kw_ui_code else (kw_ui_code, '')
            item_label_part, item_num_part = (item_ui_code.split('-', 1) + [''])[:2] if '-' in item_ui_code else (item_ui_code, '')

            # --- 넘버 파트 정규화 (숫자로만 구성된 경우에만 적용) ---
            # 'G02'는 그대로, '003'은 '3'으로 변환
            if kw_num_part.isdigit(): kw_num_part = kw_num_part.lstrip('0') or '0'
            if item_num_part.isdigit(): item_num_part = item_num_part.lstrip('0') or '0'
            
            # --- [3단계: 비교 및 점수 부여] ---
            # 최우선 조건: 넘버 파트가 정확히 일치해야 함
            if kw_num_part == item_num_part and kw_num_part != '':
                # 넘버가 일치하므로 레이블 파트를 분석
                
                # 레이블 파트에서 (숫자 접두사, 문자 레이블) 분해
                kw_match = re.match(r'^(\d+)([A-Z].*)$', kw_label_part)
                item_match = re.match(r'^(\d+)([A-Z].*)$', item_label_part)

                kw_prefix, kw_label = (kw_match.group(1), kw_match.group(2)) if kw_match else ('', kw_label_part)
                item_prefix, item_label = (item_match.group(1), item_match.group(2)) if item_match else ('', item_label_part)
                
                # 레이블의 '문자' 부분이 정확히 일치하는지 확인
                if kw_label == item_label:
                    if kw_prefix == item_prefix:
                        return 100 # 모든 게 정확히 일치
                    elif (kw_prefix and not item_prefix) or (not kw_prefix and item_prefix):
                        return 99 # 한쪽에만 숫자 접두사
                    elif kw_prefix != item_prefix:
                        return 80 # 둘 다 있지만 불일치
                else:
                    return 60 # 넘버는 같지만 문자 레이블이 다름
            else:
                return 60 # 넘버 파트가 다름
        except Exception as e:
            logger.error(f"Score calculation error: {e}. Keyword: '{original_keyword}', Item: '{item_ui_code}'")
            return 20


    @classmethod
    def A_P(cls, text: str) -> str:
        """
        HTML 태그를 정제하고 기본적인 텍스트를 정리하는 유틸리티 메서드.
        (A_P는 Anti-Parsing의 약자)
        """
        if not text:
            return ""

        try:
            import html

            # 1. <br> 태그를 줄바꿈으로 변환
            text = re.sub(r'<\s*br\s*/?\s*>', '\n', text, flags=re.I)

            # 2. 나머지 모든 HTML 태그 제거
            text = re.sub(r'</?\s?[^>]+>', '', text)

            # 3. HTML 엔티티 변환
            text = html.unescape(text)

            # 4. 여러 줄바꿈을 2개로 제한하고 양쪽 끝 공백 제거
            text = re.sub(r'(\s*\n\s*){3,}', '\n\n', text).strip()

            return text
        except Exception:
            # 실패 시 원본 텍스트 반환
            return text


    @classmethod
    def _save_image_as_jpeg(cls, image_data_bytesio: BytesIO, save_path: str) -> bool:
        """
        이미지 바이너리 데이터를 받아, 필요할 때만 JPEG로 변환하여 저장합니다.
        성공 시 True, 실패 시 False를 반환합니다.
        """
        try:
            # 버퍼의 내용을 복사하여 원본 BytesIO 객체에 영향을 주지 않도록 함
            image_data_bytesio.seek(0)
            temp_buffer = BytesIO(image_data_bytesio.read())
            
            # Pillow로 이미지 열어 포맷과 모드 확인
            with Image.open(temp_buffer) as img:
                is_jpeg = img.format == 'JPEG'
                is_compatible_mode = img.mode in ('RGB', 'L')

                # 조건 1: 이미 JPEG이고, 호환되는 모드(RGB, L)인 경우
                if is_jpeg and is_compatible_mode:
                    # 재압축 없이 원본 바이너리 데이터를 그대로 저장
                    logger.debug(f"Saving to {save_path}")
                    image_data_bytesio.seek(0) # 원본 버퍼 포인터 리셋
                    with open(save_path, 'wb') as f:
                        f.write(image_data_bytesio.read())
                    return True
                
                # 조건 2: 그 외의 모든 경우 (PNG, WEBP, RGBA/CMYK JPEG 등)
                else:
                    logger.debug(f"Image format '{img.format}'. Converting to JPEG for {save_path}")
                    # RGB로 변환
                    if img.mode not in ('RGB', 'L'):
                        rgb_img = img.convert('RGB')
                        # 변환된 이미지 저장
                        rgb_img.save(save_path, 'JPEG', quality=95)
                        rgb_img.close()
                    else:
                        # 모드는 정상이지만 포맷이 다른 경우 (PNG, WEBP 등)
                        img.save(save_path, 'JPEG', quality=95)
                    return True

        except UnidentifiedImageError:
            # Pillow가 이미지로 인식하지 못하는 경우, 원본 데이터라도 저장
            logger.warning(f"UnidentifiedImageError for {save_path}. Saving raw data as fallback.")
            image_data_bytesio.seek(0)
            with open(save_path, 'wb') as f:
                f.write(image_data_bytesio.read())
            return True # 저장은 했으므로 True 반환
        except Exception as e:
            logger.error(f"Failed to intelligently save image to {save_path}: {e}")
            logger.error(traceback.format_exc())
            return False


    @classmethod
    def save_actor_image(cls, entity_actor):
        """
        배우 이미지를 로컬에 저장하고 entity_actor.thumb를 업데이트합니다.
        """
        # 1. 정보 추출 (객체/딕셔너리 호환)
        thumb_url = None
        kor_name = ""
        jpn_name = ""
        actor_idx = ""

        if isinstance(entity_actor, dict):
            thumb_url = entity_actor.get('thumb')
            kor_name = entity_actor.get('name', '')
            jpn_name = entity_actor.get('originalname', '')
            actor_idx = entity_actor.get('actor_idx', '')
        else:
            thumb_url = getattr(entity_actor, 'thumb', None)
            kor_name = getattr(entity_actor, 'name', '')
            jpn_name = getattr(entity_actor, 'originalname', '')
            actor_idx = getattr(entity_actor, 'actor_idx', '')
        
        if not thumb_url or not actor_idx: return

        # 2. 설정 가져오기
        root_path = cls.MetadataSetting.get('jav_censored_image_server_local_path')
        actor_sub_path = cls.MetadataSetting.get('jav_censored_image_server_actor_path') or '/jav/actor'
        server_url = cls.MetadataSetting.get('jav_censored_image_server_url')
        rewrite = cls.MetadataSetting.get_bool('jav_censored_image_server_rewrite')

        if not root_path or not server_url: return

        # 3. URL 파싱 (프록시 URL인 경우 원본 추출)
        real_thumb_url = thumb_url
        if 'jav_image' in thumb_url and 'url=' in thumb_url:
            try:
                from urllib.parse import parse_qs, urlparse
                parsed = urlparse(thumb_url)
                qs_dict = parse_qs(parsed.query)
                if 'url' in qs_dict:
                    real_thumb_url = qs_dict['url'][0]
            except Exception as e:
                logger.error(f"Failed to parse proxy URL: {e}")

        # 4. 파일명 및 경로 생성
        def clean_name(n):
            return re.sub(r'\s+', '_', str(n).strip())
        
        filename_base = f"{clean_name(kor_name)}"
        if jpn_name:
            filename_base += f"_({clean_name(jpn_name)})"
        filename_base += f"_A{actor_idx}.jpg"

        first_char = kor_name[0] if kor_name else 'A'
        sub_folder = cls._get_actor_folder_name(first_char)
        
        relative_path = f"{actor_sub_path.strip('/')}/{sub_folder}/{filename_base}"
        full_path = os.path.join(root_path, relative_path)
        
        # 5. 이미지 다운로드 및 저장
        if rewrite or not os.path.exists(full_path):
            try:
                os.makedirs(os.path.dirname(full_path), exist_ok=True)
                
                # [중요] 원본 URL로 요청
                res = cls.get_response(real_thumb_url)
                if res and res.status_code == 200:
                    if not cls._save_image_as_jpeg(BytesIO(res.content), full_path):
                        with open(full_path, 'wb') as f: f.write(res.content)
                else:
                    logger.warning(f"Failed to download actor image. Status: {res.status_code if res else 'None'}")
                    return # 저장 실패 시 URL 업데이트 안 함
            except Exception as e:
                logger.error(f"Failed to save actor image: {e}")
                return

        # 6. URL 업데이트 (성공 시에만)
        new_url = f"{server_url.rstrip('/')}/{relative_path}"
        
        if isinstance(entity_actor, dict):
            entity_actor['thumb'] = new_url
        else:
            entity_actor.thumb = new_url


    @staticmethod
    def _get_actor_folder_name(char):
        """한글 초성 또는 알파벳에 따라 폴더명을 반환합니다."""
        if '가' <= char <= '힣':
            char_code = ord(char) - ord('가')
            cho_index = char_code // 588
            
            # 초성 인덱스: 0(ㄱ), 1(ㄲ), 2(ㄴ), 3(ㄷ), 4(ㄸ), 5(ㄹ), 6(ㅁ), 7(ㅂ), 8(ㅃ), 9(ㅅ), 
            #             10(ㅆ), 11(ㅇ), 12(ㅈ), 13(ㅉ), 14(ㅊ), 15(ㅋ), 16(ㅌ), 17(ㅍ), 18(ㅎ)
            
            # 폴더명 매핑 (된소리는 예사소리 폴더로, ㅋㅌㅍㅎ은 그대로)
            mapping = {
                0: '가', 1: '가',  # ㄱ, ㄲ -> 가
                2: '나',          # ㄴ -> 나
                3: '다', 4: '다',  # ㄷ, ㄸ -> 다
                5: '라',          # ㄹ -> 라
                6: '마',          # ㅁ -> 마
                7: '바', 8: '바',  # ㅂ, ㅃ -> 바
                9: '사', 10: '사', # ㅅ, ㅆ -> 사
                11: '아',         # ㅇ -> 아
                12: '자', 13: '자', # ㅈ, ㅉ -> 자
                14: '차',         # ㅊ -> 차
                15: '카',         # ㅋ -> 카
                16: '타',         # ㅌ -> 타
                17: '파',         # ㅍ -> 파
                18: '하'          # ㅎ -> 하
            }
            return mapping.get(cho_index, '기타')
            
        elif 'A' <= char.upper() <= 'Z':
            return "AZ"
        elif '0' <= char <= '9':
            return "#"
        else:
            return "#"


    # =========================================================================
    # AI Detection Methods (MediaPipe Face)
    # -------------------------------------------------------------------------

    @classmethod
    def _detect_body(cls, open_cv_image):
        if not cls.config.get('use_pose_landmarker'): return False, []

        try:
            import cv2
            import numpy as np
            import mediapipe as mp
            from mediapipe.tasks import python
            from mediapipe.tasks.python import vision
        except ImportError as e:
            logger.warning(f"[{cls.site_name}] Missing libraries for Pose Landmarker: {e}")
            return False, []
            
        os.environ['TF_CPP_MIN_LOG_LEVEL'] = '2'

        model_path = cls.config.get('pose_landmarker_model_path')
        if not model_path or not os.path.exists(model_path):
            logger.error(f"[{cls.site_name}] Pose Model file missing: {model_path}")
            return False, []

        try:
            body_thresh = cls.config.get('smart_crop_body_threshold')
            
            h, w = open_cv_image.shape[:2]
            img_rgb = cv2.cvtColor(open_cv_image, cv2.COLOR_BGR2RGB)
            mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=img_rgb)

            base_options = python.BaseOptions(model_asset_path=model_path)
            options = vision.PoseLandmarkerOptions(
                base_options=base_options,
                num_poses=5, 
                min_pose_detection_confidence=body_thresh,
                min_pose_presence_confidence=body_thresh,
                min_tracking_confidence=0.5
            )
            
            with vision.PoseLandmarker.create_from_options(options) as landmarker:
                detection_result = landmarker.detect(mp_image)

            if not detection_result.pose_landmarks:
                return False, []

            people_list = []
            
            for idx, landmarks in enumerate(detection_result.pose_landmarks):
                # 1. 랜드마크 추출
                nose = landmarks[0]
                l_eye, r_eye = landmarks[2], landmarks[5]
                l_ear, r_ear = landmarks[7], landmarks[8]
                l_sh, r_sh = landmarks[11], landmarks[12]
                l_hip, r_hip = landmarks[23], landmarks[24]
                
                limb_indices = [13, 14, 25, 26]
                visible_limbs_subset_x = []
                for li in limb_indices:
                    if landmarks[li].visibility > 0.5:
                        visible_limbs_subset_x.append(landmarks[li].x)

                visible_ears_x = []
                if l_ear.visibility > 0.5: visible_ears_x.append(l_ear.x)
                if r_ear.visibility > 0.5: visible_ears_x.append(r_ear.x)

                # 2. 좌표 그룹핑 (Torso Only for Base Box)
                pts_torso = [l_sh, r_sh, l_hip, r_hip]
                x_torso = [p.x for p in pts_torso]
                y_torso = [p.y for p in pts_torso]

                if min(x_torso) < -0.2 or max(x_torso) > 1.2: continue

                # [Hip Bias Logic] 무게중심 계산
                width_sh = abs(l_sh.x - r_sh.x)
                width_hip = abs(l_hip.x - r_hip.x)
                
                sh_cx = (l_sh.x + r_sh.x) / 2
                hip_cx = (l_hip.x + r_hip.x) / 2
                
                # 엉덩이 강조 가중치 (1.2배 이상 크면 2배 가중)
                w_hip = 2.0 if width_hip > width_sh * 1.2 else 1.0
                torso_core_cx = (sh_cx * 1.0 + hip_cx * w_hip) / (1.0 + w_hip)
                
                # Limbs Integration (오탐 방지: 2개 이상일 때만)
                limb_pts = [landmarks[i] for i in limb_indices]
                valid_limbs = [p for p in limb_pts if p.visibility > 0.5]
                
                if len(valid_limbs) >= 2:
                    limbs_cx = sum([p.x for p in valid_limbs]) / len(valid_limbs)
                    cx_float = (torso_core_cx + limbs_cx) / 2.0
                else:
                    cx_float = torso_core_cx
                
                body_cx = int(cx_float * w)
                
                # [Torso Box]
                min_x = int(min(x_torso) * w)
                max_x = int(max(x_torso) * w)
                min_y = int(min(y_torso) * h)
                max_y = int(max(y_torso) * h)
                box_w = max_x - min_x
                box_h = max_y - min_y
                torso_box = (min_x, min_y, box_w, box_h)
                
                # [Full Box] (Log Only)
                all_pts = pts_torso + valid_limbs
                fx1 = int(min([p.x for p in all_pts]) * w)
                fx2 = int(max([p.x for p in all_pts]) * w)
                fy1 = int(min([p.y for p in all_pts]) * h)
                fy2 = int(max([p.y for p in all_pts]) * h)
                full_box = (fx1, fy1, fx2 - fx1, fy2 - fy1)
                
                nose_point = (int(nose.x * w), int(nose.y * h))
                
                # 4. 각도 및 Yaw 계산
                body_angle = 0.0
                is_torso_visible = (l_sh.visibility > 0.5 and r_sh.visibility > 0.5 and 
                                    l_hip.visibility > 0.5 and r_hip.visibility > 0.5)
                
                if is_torso_visible:
                    mid_sh_x = (l_sh.x + r_sh.x) / 2; mid_sh_y = (l_sh.y + r_sh.y) / 2
                    mid_hip_x = (l_hip.x + r_hip.x) / 2; mid_hip_y = (l_hip.y + r_hip.y) / 2
                    body_angle = math.degrees(math.atan2(mid_sh_x - mid_hip_x, -(mid_sh_y - mid_hip_y)))
                elif l_eye.visibility > 0.5 and r_eye.visibility > 0.5:
                    mid_eye_x = (l_eye.x + r_eye.x) / 2; mid_eye_y = (l_eye.y + r_eye.y) / 2
                    body_angle = math.degrees(math.atan2(mid_eye_x - nose.x, -(mid_eye_y - nose.y)))

                # 5. 가상 얼굴 박스 생성 (Robust Logic)
                face_w_float = 0.0
                source_name = "Init"

                def get_dist(p1, p2):
                    return ((p1.x - p2.x)**2 + (p1.y - p2.y)**2)**0.5

                # A. Torso Scale Calculation
                torso_scale = 0.0
                if is_torso_visible:
                    diag_1 = get_dist(l_sh, r_hip)
                    diag_2 = get_dist(r_sh, l_hip)
                    side_1 = get_dist(l_sh, l_hip)
                    side_2 = get_dist(r_sh, r_hip)
                    width_sh = get_dist(l_sh, r_sh)
                    width_hip = get_dist(l_hip, r_hip)
                    torso_scale = max(diag_1, diag_2, side_1, side_2, width_sh, width_hip)

                body_width_ratio = box_w / w if w > 0 else 0

                def is_valid_part(part_size, min_ratio=0.2):
                    if torso_scale > 0:
                        return part_size > (torso_scale * min_ratio)
                    if body_width_ratio == 0: return False
                    return part_size > (body_width_ratio * min_ratio)

                # B. Size Estimation
                dist_ear = get_dist(l_ear, r_ear) if (l_ear.visibility > 0.5 and r_ear.visibility > 0.5) else 0.0
                dist_eye = get_dist(l_eye, r_eye) if (l_eye.visibility > 0.5 and r_eye.visibility > 0.5) else 0.0
                dist_sh  = get_dist(l_sh, r_sh)   if (l_sh.visibility > 0.5 and r_sh.visibility > 0.5) else 0.0
                
                min_valid_face = (torso_scale * 0.1) if torso_scale > 0 else 0.02

                if dist_ear > min_valid_face:
                    face_w_float = dist_ear * 1.8
                    source_name = "Ears"
                elif dist_eye > min_valid_face:
                    face_w_float = dist_eye * 3.0
                    source_name = "Eyes"
                elif torso_scale > 0:
                    # [Logic 2] Torso Scale Based
                    std_face_w = torso_scale * 0.22
                    min_valid_sh = torso_scale * 0.3
                    
                    if dist_sh > min_valid_sh:
                        face_w_float = dist_sh * 0.6
                        source_name = "Shoulders(Wide)"
                    else:
                        face_w_float = std_face_w
                        source_name = "TorsoStd"
                else:
                    # [Logic 3] Fallback
                    l_arm = get_dist(l_sh, landmarks[13]) if (l_sh.visibility > 0.5 and landmarks[13].visibility > 0.5) else 0
                    r_arm = get_dist(r_sh, landmarks[14]) if (r_sh.visibility > 0.5 and landmarks[14].visibility > 0.5) else 0
                    dist_arm = max(l_arm, r_arm)
                    
                    if dist_arm > 0 and is_valid_part(dist_arm, 0.2): 
                        face_w_float = dist_arm * 0.7
                        source_name = "Arms"
                    elif dist_sh > 0 and is_valid_part(dist_sh, 0.2): 
                        face_w_float = dist_sh * 0.6
                        source_name = "Shoulders(Only)"
                    else:
                        face_w_float = max(0.15, body_width_ratio * 0.5)
                        source_name = "BodyFallback"

                # C. Final Validations
                if face_w_float > 0.6: face_w_float = 0.6
                
                face_w = int(face_w_float * w)
                face_h = int(face_w * 1.2)
                
                # 중심점 보정
                if dist_ear > 0:
                    mid_ear_x = (l_ear.x + r_ear.x) / 2
                    mid_ear_y = (l_ear.y + r_ear.y) / 2
                    face_cx = int(((nose.x + mid_ear_x) / 2) * w)
                    face_cy = int(((nose.y + mid_ear_y) / 2) * h)
                else:
                    face_cx = nose_point[0]
                    face_cy = nose_point[1]
                
                face_cy -= int(face_h * 0.15)
                v_box = (face_cx - face_w//2, face_cy - face_h//2, face_w, face_h)
                v_x1 = face_cx - face_w//2
                v_x2 = v_x1 + face_w

                # 6. 점수 계산
                area = (max_x - min_x) * (max_y - min_y)
                avg_presence = sum([p.presence for p in pts_torso]) / 4.0
                score = (area * 0.8) + (avg_presence * 0.2)

                people_list.append({
                    'cx': body_cx,
                    'cx_float': cx_float,
                    'box': torso_box,
                    'full_box': full_box,
                    'nose': nose_point,
                    'nose_x_float': nose.x,
                    'angle': body_angle,
                    'score': score,
                    'limbs_subset_x': visible_limbs_subset_x,
                    'ears_x': visible_ears_x,
                    'virtual_face': {
                        'box': v_box, 'w': face_w, 'h': face_h,
                        'cx': face_cx, 'cy': face_cy,
                        'x1': v_x1, 'x2': v_x2,
                        'source': source_name
                    }
                })

            people_list.sort(key=lambda x: x['score'], reverse=True)
            
            try:
                log_msg = f"[{cls.site_name}] MP-Pose: {len(people_list)} bodies found."
                for i, p in enumerate(people_list):
                    n_limbs = len(p.get('limbs_subset_x', []))
                    
                    vf = p['virtual_face']
                    v_info = f"V.Face:[Src:{vf['source']} W:{vf['w']} Box:{vf['box']}]"
                    f_box = p.get('full_box', p['box'])
                    
                    log_msg += f"\n    #{i+1} [Body] Score:{p['score']:.0f} Ang:{p['angle']:.1f} {v_info} Torso:{p['box']} Limbs:{n_limbs}{f_box}"
                logger.debug(log_msg)
            except Exception: pass
            
            return True, people_list

        except Exception as e:
            logger.error(f"[{cls.site_name}] MediaPipe Pose Error: {e}")
            return False, []


    @classmethod
    def _detect_face(cls, open_cv_image, threshold=None, people_list=None, roi=None):
        try:
            import cv2
            import numpy as np
            import mediapipe as mp
            from mediapipe.tasks import python
            from mediapipe.tasks.python import vision
        except ImportError as e:
            logger.warning(f"[{cls.site_name}] Missing libraries for Face Landmarker: {e}")
            return False, []

        model_path = cls.config.get('face_landmarker_model_path') 
        if not model_path or not os.path.exists(model_path):
            if not roi: logger.error(f"[{cls.site_name}] Face Model file missing: {model_path}")
            return False, []

        if threshold is None:
            threshold = cls.config.get('smart_crop_face_threshold')

        try:
            # 1. ROI 처리
            if roi:
                rx, ry, rw, rh = roi
                h_img, w_img = open_cv_image.shape[:2]
                rx = max(0, rx); ry = max(0, ry)
                rw = min(rw, w_img - rx); rh = min(rh, h_img - ry)
                if rw <= 10 or rh <= 10: return False, []
                detect_image_np = open_cv_image[ry:ry+rh, rx:rx+rw]
                offset_x, offset_y = rx, ry
                img_h, img_w = rh, rw
            else:
                offset_x, offset_y = 0, 0
                img_h, img_w = open_cv_image.shape[:2]
                detect_image_np = open_cv_image

            detect_image_np = cv2.cvtColor(detect_image_np, cv2.COLOR_BGR2RGB)
            mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=detect_image_np)

            # 2. Landmarker 인스턴스
            if not hasattr(cls, '_mp_face_landmarker_instance'):
                base_options = python.BaseOptions(model_asset_path=model_path)
                options = vision.FaceLandmarkerOptions(
                    base_options=base_options,
                    output_face_blendshapes=False,
                    output_facial_transformation_matrixes=False,
                    num_faces=5,
                    min_face_detection_confidence=threshold,
                    min_face_presence_confidence=threshold,
                )
                cls._mp_face_landmarker_instance = vision.FaceLandmarker.create_from_options(options)
            
            landmarker = cls._mp_face_landmarker_instance
            detection_result = landmarker.detect(mp_image)
            
            # 3. 결과 파싱
            detected_faces = []
            if detection_result.face_landmarks:
                for face_landmarks in detection_result.face_landmarks:
                    xs = [l.x for l in face_landmarks]
                    ys = [l.y for l in face_landmarks]
                    
                    min_x, max_x = min(xs), max(xs)
                    min_y, max_y = min(ys), max(ys)
                    
                    box_x = int(min_x * img_w) + offset_x
                    box_y = int(min_y * img_h) + offset_y
                    box_w = int((max_x - min_x) * img_w)
                    box_h = int((max_y - min_y) * img_h)
                    
                    if box_w <= 0 or box_h <= 0: continue

                    face_cx = box_x + (box_w // 2)
                    face_cy = box_y + (box_h // 2)
                    area = box_w * box_h
                    
                    # 각도 계산
                    roll_angle = 0.0
                    yaw_angle = 0.0
                    try:
                        l_eye = face_landmarks[33]; r_eye = face_landmarks[263]
                        nose = face_landmarks[1]
                        l_cheek = face_landmarks[454]; r_cheek = face_landmarks[234]
                        
                        dy = (r_eye.y - l_eye.y) * img_h
                        dx = (r_eye.x - l_eye.x) * img_w
                        roll_angle = math.degrees(math.atan2(dy, dx))
                        
                        dist_l = abs(nose.x - l_cheek.x)
                        dist_r = abs(nose.x - r_cheek.x)
                        yaw_ratio = (dist_l - dist_r) / (dist_l + dist_r + 1e-6)
                        yaw_angle = yaw_ratio * 120.0
                    except: pass

                    detected_faces.append({
                        'cx': face_cx, 'cy': face_cy,
                        'w': box_w, 'h': box_h, 
                        'x1': box_x, 'x2': box_x + box_w,
                        'area': area,
                        'score': float(area),
                        'angle': roll_angle,
                        'yaw': yaw_angle,
                        'body_idx': -1, 'is_virtual': False,
                        'box': (box_x, box_y, box_w, box_h)
                    })

            if not detected_faces and not roi:
                logger.debug(f"[{cls.site_name}] MP-Face: No faces detected. (Threshold: {threshold})")

            # 4. 매칭 및 가상 얼굴 추가
            valid_faces = []
            if people_list:
                for b_idx, person in enumerate(people_list):
                    nx, ny = person['nose']
                    best_match = None
                    min_dist = float('inf')
                    
                    for face in detected_faces:
                        if face['body_idx'] != -1: continue
                        diag = (face['w']**2 + face['h']**2)**0.5
                        dist = ((face['cx'] - nx)**2 + (face['cy'] - ny)**2)**0.5
                        
                        if dist < diag * 1.5:
                            if dist < min_dist:
                                min_dist = dist
                                best_match = face
                                
                    if best_match:
                        best_match['body_idx'] = b_idx
                        best_match['score'] *= 2.0
                        valid_faces.append(best_match)
                    elif person['score'] > 0.2 and not roi:
                        v_face = person['virtual_face']
                        
                        dummy_face = {
                            'cx': v_face['cx'], 'cy': v_face['cy'],
                            'w': v_face['w'], 'h': v_face['h'],
                            'area': v_face['w'] * v_face['h'],
                            'x1': v_face.get('x1', v_face['cx'] - v_face['w']//2),
                            'x2': v_face.get('x2', v_face['cx'] + v_face['w']//2),
                            'score': person['score'] * 50000,
                            'angle': person['angle'], 
                            'yaw': 0.0, 
                            'body_idx': b_idx, 'is_virtual': True,
                            'box': v_face['box'],
                            'source': v_face.get('source', '?')
                        }
                        valid_faces.append(dummy_face)
                        # logger.debug(f"Added Virtual Face for Body {b_idx}")

            # 5. 매칭 안 된 얼굴 처리 (Unmatched Real Faces)
            if not roi:
                remaining_faces = [f for f in detected_faces if f['body_idx'] == -1]
                main_face = valid_faces[0] if valid_faces else None
                for sub in remaining_faces:
                    if main_face:
                        size_diff_ratio = abs(sub['area'] - main_face['area']) / max(sub['area'], main_face['area'])
                        if size_diff_ratio > 0.8: continue
                        dist = ((sub['cx'] - main_face['cx'])**2 + (sub['cy'] - main_face['cy'])**2)**0.5
                        main_diag = (main_face['w']**2 + main_face['h']**2)**0.5
                        if dist > main_diag * 3.0: continue
                        valid_faces.append(sub)
                    else:
                        valid_faces.append(sub)
            else:
                # ROI Rescue 모드: 가장 큰 얼굴 선택
                if not valid_faces and detected_faces:
                    detected_faces.sort(key=lambda x: x['score'], reverse=True)
                    valid_faces.append(detected_faces[0])

            valid_faces.sort(key=lambda x: x['score'], reverse=True)

            try:
                log_header = "MP-Face (Rescue)" if roi else "MP-Face"
                log_msg = f"[{cls.site_name}] {log_header}: {len(valid_faces)} valid / {len(detected_faces)} detected."
                
                for i, f in enumerate(valid_faces):
                    f_type = "Virtual" if f.get('is_virtual') else "Real"
                    b_str = f"Body:{f.get('body_idx', -1)}"
                    yaw_val = f.get('yaw', 0.0)
                    ang_val = f.get('angle', 0.0)
                    src_str = f" Src:{f.get('source', '')}" if f_type == "Virtual" else ""
                    
                    log_msg += f"\n    #{i+1} [{f_type}] Score:{f['score']:.0f} W:{f['w']} Ang:{ang_val:.1f} Yaw:{yaw_val:.1f} {b_str}{src_str} Box:{f['box']}"
                
                if valid_faces or roi: logger.debug(log_msg)
            except Exception as e:
                logger.error(f"Log Error: {e}")

            return True, valid_faces

        except Exception as e:
            logger.error(f"[{cls.site_name}] MediaPipe Face Error: {e}")
            return False, []


    @classmethod
    def _attempt_face_rescue(cls, image, virtual_face, body_angle, thresh):
        vx, vy, vw, vh = virtual_face['box']
        # 가상 얼굴 중심점
        vcx = vx + vw // 2
        vcy = vy + vh // 2
        
        img_h, img_w = image.shape[:2]
        
        # 확장 스케일(가상 얼굴 크기 기준)
        scales = [1.5, 2.0, 3.0]
        
        # 1. MediaPipe Scan
        for scale in scales:
            roi_w = int(vw * scale)
            roi_h = int(vh * scale)
            
            roi_x = max(0, vcx - roi_w // 2)
            roi_y = max(0, vcy - roi_h // 2)
            
            roi_x = min(roi_x, img_w - roi_w)
            roi_y = min(roi_y, img_h - roi_h)
            if roi_x < 0: roi_x = 0; roi_w = img_w
            if roi_y < 0: roi_y = 0; roi_h = img_h

            if roi_w <= 10 or roi_h <= 10: continue

            roi = (roi_x, roi_y, roi_w, roi_h)

            logger.debug(f"[{cls.site_name}] Rescue[MP] Trying Scale {scale}x ROI:{roi} Thresh:{thresh}")

            res_mp = cls._detect_face(image, threshold=thresh, roi=roi)
            if res_mp and res_mp[1]:
                face = res_mp[1][0]
                logger.debug(f"[{cls.site_name}] Rescue[MP] Success at Scale {scale}x")
                return face
        
        return None


    @classmethod
    def _smart_crop_image(cls, pil_image, target_ratio=1.4225):
        if not cls.config.get('use_smart_crop'):
            return False, []

        try:
            import cv2
            import numpy as np
            import mediapipe as mp
        except ImportError as e:
            logger.warning(f"[{cls.site_name}] Required libraries not installed. Skipping Smart Crop. ({e})")
            return False, []

        open_cv_image = np.array(pil_image)
        if pil_image.mode == 'RGB': open_cv_image = open_cv_image[:, :, ::-1].copy()
        elif pil_image.mode == 'RGBA': open_cv_image = cv2.cvtColor(open_cv_image, cv2.COLOR_RGBA2BGR)
        
        h, w = open_cv_image.shape[:2]
        
        # detect_image = cls._apply_clahe(open_cv_image) # 필터링이 오히려 해가 되는 경우가 있음...옵션화?
        detect_image = open_cv_image
        
        body_res = cls._detect_body(detect_image)
        people_list = body_res[1]
        
        face_res = cls._detect_face(detect_image, people_list=people_list)
        valid_faces = face_res[1]
        
        # Rescue Phase (with Safety Check)
        if any(f.get('is_virtual') for f in valid_faces):
            rescued_list = []
            
            for face in valid_faces:
                if face.get('is_virtual'):
                    # [Safety Check]
                    body_idx = face.get('body_idx', -1)
                    if body_idx == -1: continue 
                    
                    body = people_list[body_idx]
                    
                    # (1) 크기 검증: 몸통 너비(tw)의 1.5배 OR 높이(th)의 0.6배 중 하나만 만족하면 OK
                    body_w = body['box'][2]; body_h = body['box'][3]
                    is_size_safe = (face['w'] < body_w * 1.5) or (face['w'] < body_h * 0.6)

                    # (2) 거리 검증: 몸통 너비의 2.0배 이내 OR 높이의 0.5배 이내
                    tx, ty, tw, th = body['box']
                    tcx, tcy = tx + tw//2, ty + th//2 
                    dist_y = abs(face['cy'] - tcy)
                    dist_x = abs(face['cx'] - tcx)
                    is_dist_safe = (dist_y < th * 1.5) and (dist_x < max(tw * 2.0, th * 0.5))

                    is_safe = is_size_safe and is_dist_safe
                    if not is_safe:
                        logger.debug(f"[{cls.site_name}] Virtual Face Unsafe (Body:{body_idx}). Will drop if rescue fails.")

                    # Rescue 시도 (Unsafe라도 시도함)
                    rescue_thresh = cls.config.get('smart_crop_face_rescue_threshold')
                    rescued_face = cls._attempt_face_rescue(detect_image, face, body, rescue_thresh)
                    
                    if rescued_face:
                        # 성공: 진짜 얼굴 사용 (Safety 무관)
                        rescued_face['body_idx'] = body_idx
                        rescued_list.append(rescued_face)
                        logger.debug(f"[{cls.site_name}] Rescue Success! (Score:{rescued_face['score']:.0f})")
                    else:
                        # 실패: Safe한 경우만 Fallback 사용
                        if is_safe:
                            logger.debug(f"[{cls.site_name}] Rescue Failed. Using Safe Virtual Face.")
                            rescued_list.append(face)
                        else:
                            logger.debug(f"[{cls.site_name}] Rescue Failed & Unsafe. Dropping.")
                else:
                    rescued_list.append(face)

            valid_faces = rescued_list

        # [Multi-face Filtering]
        final_faces = []
        for f in valid_faces:
            if not f.get('is_virtual') or f.get('body_idx') == 0:
                final_faces.append(f)
                if f.get('is_virtual'):
                    logger.debug(f"[{cls.site_name}] Keep Main Body Virtual Face.")

        if final_faces:
            valid_faces = final_faces
            valid_faces.sort(key=lambda x: x['score'], reverse=True)
        else:
            logger.debug(f"[{cls.site_name}] No valid faces found after filtering.")
            return None

        # Center Calculation Phase
        final_center_x = None
        main_face = valid_faces[0]
        target_w = int(h / target_ratio)
        
        def get_face_weight(angle):
            min_w = cls.config.get('smart_crop_face_weight_min', 0.3)
            max_w = cls.config.get('smart_crop_face_weight_max', 0.9)
            abs_angle = abs(angle)
            if abs_angle > 90: abs_angle = 180 - abs_angle
            ratio = abs_angle / 90.0
            return min_w + (max_w - min_w) * ratio

        shifted_cx = None
        is_multi_face = False
        target_w = int(h / target_ratio) 

        # [A] Multi-face Logic
        shifted_cx = None
        is_multi_face = False
        if len(valid_faces) > 1:
            for sub_face in valid_faces[1:]:
                # 메인 얼굴과 서브 얼굴
                f1 = valid_faces[0]
                f2 = sub_face
                
                # 기본: 정중앙 (0.5 : 0.5)
                w1 = 0.5
                
                # Virtual Face Weighting (위치가 부정확할 수 있으므로, 잘림 방지)
                if f1.get('is_virtual'):
                    w1 = 0.55
                
                # 중심점 계산
                mid_point = int(f1['cx'] * w1 + f2['cx'] * (1.0 - w1))
                
                half_crop = target_w // 2
                crop_x1 = mid_point - half_crop
                crop_x2 = mid_point + half_crop
                
                # Tolerance Check (가상 얼굴일 경우 Tolerance 여유 없음 -> 마진 증가)
                tol_factor_1 = 0.2 if f1.get('body_idx') != -1 else 0.3
                if f1.get('is_virtual'): tol_factor_1 = 0.0
                
                tol_1 = f1['w'] * tol_factor_1
                tol_2 = f2['w'] * 0.2
                
                safe_x1 = f1['x1'] + tol_1
                safe_x2 = f2['x2'] - tol_2
                
                # x1(왼쪽얼굴)이 x2(오른쪽얼굴)보다 왼쪽에 있다고 가정하고 정렬
                if safe_x1 > safe_x2: safe_x1, safe_x2 = safe_x2, safe_x1
                
                if crop_x1 <= safe_x1 and crop_x2 >= safe_x2:
                    shifted_cx = mid_point
                    is_multi_face = True
                    logger.debug(f"[{cls.site_name}] Smart Crop: Multi-face Shift applied (Weight:{w1:.2f}).")
                    break

        if shifted_cx:
            final_center_x = shifted_cx
        else:
            # [B] Single Face Logic (Shift-based)
            main_body = None
            if main_face.get('body_idx') != -1 and people_list:
                main_body = people_list[main_face['body_idx']]

            # 1. Base Center: Torso Center (or Face if no body)
            if main_body:
                base_center = main_body['cx'] # Torso Center
            else:
                base_center = main_face['cx']
            
            final_center_x = base_center
            
            # 2. Calculate Shifts (S_face, S_limb, S_gaze)
            shift_face = 0
            shift_limb = 0
            shift_gaze = 0
            
            # [LOG] Shift Details
            log_details = []

            # (1) Face Shift
            if main_body:
                fw_weight = get_face_weight(main_body['angle'])
                if main_face.get('is_virtual'): 
                    abs_angle = abs(main_body['angle'])
                    if abs_angle > 90: abs_angle = 180 - abs_angle
                    virtual_weight = 0.6 + (0.3 * (abs_angle / 90.0))
                    fw_weight = max(fw_weight, virtual_weight)
                
                shift_face = int((main_face['cx'] - main_body['cx']) * fw_weight)
                log_details.append(f"Face:{shift_face}(W:{fw_weight:.2f})")

            # (2) Limbs Shift
            if main_body:
                limbs = main_body.get('limbs_subset_x', [])
                if limbs and len(limbs) >= 2:
                    torso_cx = main_body['cx_float'] # Torso Center
                    
                    # 1. Full Body Center (Geometry Center)
                    # 팔다리 뻗은 범위의 중심
                    all_x = limbs + [torso_cx]
                    full_min = min(all_x)
                    full_max = max(all_x)
                    full_cx = (full_min + full_max) / 2.0
                    
                    # 2. Raw Shift Amount (Torso -> Full 방향)
                    raw_shift = (full_cx - torso_cx) * w # 픽셀 단위 변환
                    
                    # 3. Damping Factors
                    # 3-1. Size Damping (Target Width 기준)
                    full_width_px = (full_max - full_min) * w 
                    width_ratio_to_crop = full_width_px / target_w
                    
                    size_damp = cls._calculate_damping_factor(
                        width_ratio_to_crop, 
                        min_val=0.7, # 크롭 폭의 70% 이하면 100% 이동 허용
                        max_val=1.0, # 크롭 폭의 100% 이상이면 0% (이동 불가)
                        max_scale=1.0, 
                        curve_type='linear'
                    )
                    
                    # 3-2. Angle Damping
                    # 누울수록(90도) 이동 줄임
                    abs_angle = abs(main_body['angle'])
                    if abs_angle > 90: abs_angle = 180 - abs_angle
                    angle_damp = cls._calculate_damping_factor(
                        abs_angle, 
                        min_val=10.0, 
                        max_val=60.0, 
                        max_scale=1.0, 
                        curve_type='linear'
                    )
                    
                    # 4. Final Calculation
                    # 최대 이동폭 제한: 크롭 너비의 30%
                    max_limb_shift = int(target_w * 0.3)
                    
                    # 가중치 적용 (기본 50% 강도 * 댐핑들)
                    # "토르소와 팔다리의 중간점" = 50% 이동
                    base_strength = 0.5 
                    
                    shift_limb = int(raw_shift * base_strength * size_damp * angle_damp)
                    
                    # Clamp
                    shift_limb = max(-max_limb_shift, min(max_limb_shift, shift_limb))
                    
                    if abs(shift_limb) <= 10: shift_limb = 0

                    log_details.append(f"Limb:{shift_limb}(Sz:{size_damp:.2f}, An:{angle_damp:.2f})")

            # (3) Gaze Shift
            face_yaw = main_face.get('yaw', 0.0)
            fw = main_face['w']
            
            yaw_trust_factor = 0.0
            if fw >= 200: yaw_trust_factor = 1.0
            elif fw >= 80: yaw_trust_factor = (fw - 80) / (200 - 80)

            if abs(face_yaw) > 5 and yaw_trust_factor > 0:
                cancel_gaze = False
                if main_body:
                    b_angle = main_body['angle']
                    limbs_count = len(main_body.get('limbs_subset_x', []))
                    
                    if limbs_count >= 2:
                        if abs(b_angle) > 5 and (b_angle * face_yaw > 0):
                            cancel_gaze = True
                            log_details.append("Gaze:Cross")
                
                if not cancel_gaze:
                    shift_ratio = -(face_yaw / 60.0) 
                    shift_ratio = max(-1.0, min(1.0, shift_ratio))
                    calc_gaze = int(fw * shift_ratio * 0.8)

                    face_ratio = fw / w
                    size_damp = cls._calculate_damping_factor(face_ratio, 0.1, 0.3, 1.0, 'linear')
                    
                    angle_damp = 1.0
                    if main_body:
                        abs_angle = abs(main_body['angle'])
                        if abs_angle > 90: abs_angle = 180 - abs_angle
                        angle_damp = cls._calculate_damping_factor(abs_angle, 0.0, 30.0, 1.0, 'linear')

                    shift_gaze = int(calc_gaze * yaw_trust_factor * size_damp * angle_damp)
                    if abs(shift_gaze) <= 5: shift_gaze = 0
                    
                    log_details.append(f"Gaze:{shift_gaze}(Tr:{yaw_trust_factor:.1f}, Sz:{size_damp:.1f}, An:{angle_damp:.1f})")

            # 3. Merge Shifts
            shifts = [shift_face, shift_limb, shift_gaze]
            pos_shifts = [s for s in shifts if s > 0]
            neg_shifts = [s for s in shifts if s < 0]
            
            total_shift = 0
            if pos_shifts: total_shift += max(pos_shifts)
            if neg_shifts: total_shift += min(neg_shifts)
            
            final_center_x += total_shift
            
            details_str = ", ".join(log_details)
            logger.debug(f"[{cls.site_name}] Shift Info: Base:{base_center} -> Final:{final_center_x} | {details_str}")

            # 4. Tilt Correction
            tilt_angle = main_face.get('angle', 0.0)
            if abs(tilt_angle) > 10:
                eff_angle = abs(tilt_angle)
                if eff_angle > 90: eff_angle = 180 - eff_angle
                shift_px = int(main_face['w'] * eff_angle * 0.001 * 1.5)
                
                if tilt_angle > 0: final_center_x += shift_px
                else: final_center_x -= shift_px

            # 5. Safety: Torso Protection
            if main_body:
                torso_cx = main_body['cx']
                torso_w = main_body['box'][2]
                
                limit_rule = int(target_w * 0.15)
                margin = target_w - torso_w
                
                limit = limit_rule
                if margin > 0:
                    pad = int(torso_w * 0.05)
                    limit_phys = max(0, (margin // 2) - pad)
                    limit = min(limit_rule, limit_phys)
                
                drift = final_center_x - torso_cx
                if abs(drift) > limit:
                    prev_x = final_center_x
                    if drift > 0: final_center_x = torso_cx + limit
                    else: final_center_x = torso_cx - limit
                    logger.debug(f"[{cls.site_name}] Torso Protect: {prev_x} -> {final_center_x} (Limit:{limit})")

        # --- Final Crop ---
        half_crop = target_w // 2
        crop_x1 = final_center_x - half_crop
        crop_x2 = final_center_x + half_crop
        
        # [Safety: Fit Face (Cosine S-Curve + Directional)]
        if not is_multi_face and main_face['w'] > 0:
            fx1, fx2, fw = main_face['x1'], main_face['x2'], main_face['w']
            if fw < target_w:
                face_ratio = fw / target_w
                padding_multiplier = cls._calculate_damping_factor(
                    face_ratio, 0.1, 1.0, 0.5, 'cosine'
                )
                base_padding = int(fw * padding_multiplier)
                
                yaw = main_face.get('yaw', 0.0)
                abs_yaw = abs(yaw)
                max_dir_pad = int(target_w * 0.05)
                extra_pad = 0
                
                if abs_yaw > 20:
                    ratio = min(1.0, (abs_yaw - 20) / 80.0)
                    extra_pad = int(max_dir_pad * ratio)

                pad_left = base_padding
                pad_right = base_padding
                
                if yaw < 0: pad_right = max(base_padding, extra_pad)
                else:       pad_left = max(base_padding, extra_pad)
                
                safe_fx1 = fx1 - pad_left
                safe_fx2 = fx2 + pad_right
                
                req_width = safe_fx2 - safe_fx1
                if req_width > target_w:
                    overflow = req_width - target_w
                    if yaw < -20:   safe_fx1 += overflow
                    elif yaw > 20:  safe_fx2 -= overflow
                    else:
                        safe_fx1 += overflow // 2
                        safe_fx2 -= overflow // 2

                if crop_x1 > safe_fx1:
                    diff = crop_x1 - safe_fx1
                    crop_x1 = safe_fx1
                    crop_x2 = safe_fx1 + target_w
                    logger.debug(f"[{cls.site_name}] Fit Face: LEFT {diff}px (Base:{base_padding}, Extra:{extra_pad})")
                elif crop_x2 < safe_fx2:
                    diff = safe_fx2 - crop_x2
                    crop_x2 = safe_fx2
                    crop_x1 = safe_fx2 - target_w
                    logger.debug(f"[{cls.site_name}] Fit Face: RIGHT {diff}px (Base:{base_padding}, Extra:{extra_pad})")

        if crop_x1 < 0: crop_x1 = 0; crop_x2 = target_w
        elif crop_x2 > w: crop_x2 = w; crop_x1 = w - target_w

        return pil_image.crop((crop_x1, 0, crop_x2, h))


    @staticmethod
    def _calculate_damping_factor(current_val, min_val, max_val, max_scale=1.0, curve_type='cosine'):
        """
        입력값에 따라 감쇠 계수를 계산하는 헬퍼 메서드.
        :param current_val: 현재 값 (예: 얼굴 비율, 각도)
        :param min_val: 감쇠 시작 임계값 (이 값 이하에서는 max_scale 반환)
        :param max_val: 감쇠 종료 임계값 (이 값 이상에서는 0.0 반환)
        :param max_scale: 최대 반환값 (기본 1.0)
        :param curve_type: 'linear' (선형), 'cosine' (S자 곡선), 'concave' (오목, 2차함수)
        :return: 감쇠된 계수 (0.0 ~ max_scale)
        """
        # 1. 범위 벗어나는 경우 처리
        if current_val <= min_val:
            return float(max_scale)
        if current_val >= max_val:
            return 0.0

        # 2. 정규화 (0.0 ~ 1.0)
        # min일 때 0.0, max일 때 1.0
        t = (current_val - min_val) / (max_val - min_val)

        # 3. 곡선 적용 (팩터는 1.0 -> 0.0 으로 가야 함)
        factor = 0.0
        if curve_type == 'cosine':
            # S-Curve: (1 + cos(πt)) / 2
            # 양 끝은 완만하고 중간이 가파른 형태
            factor = (1.0 + math.cos(math.pi * t)) / 2.0
        
        elif curve_type == 'linear':
            # 직선 감소
            factor = 1.0 - t
            
        elif curve_type == 'concave': # (예: 제곱 함수)
            # 초반에 급격히 줄고 나중에 천천히 0으로
            factor = (1.0 - t) ** 2.0
            
        else: # Default Linear
            factor = 1.0 - t

        return factor * max_scale


    @staticmethod
    def _apply_clahe(image):
        try:
            import cv2

            lab = cv2.cvtColor(image, cv2.COLOR_BGR2LAB)
            l, a, b = cv2.split(lab)
            clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
            cl = clahe.apply(l)
            limg = cv2.merge((cl, a, b))
            return cv2.cvtColor(limg, cv2.COLOR_LAB2BGR)
        except:
            return image


    # endregion 유틸
    ################################################


    # ---------------------------------------------------------
    # region Selenium & FlareSolverr Common Methods (Legacy)
    # ---------------------------------------------------------


    @classmethod
    def get_tree_cs(cls, url, **kwargs):
        text = cls.get_text_cs(url, **kwargs)
        if text is None:
            return text
        return html.fromstring(text)


    @classmethod
    def get_text_cs(cls, url, **kwargs):
        res = cls.get_response_cs(url, **kwargs)
        if res is None: return None
        return res.text


    @classmethod
    def get_cloudscraper_instance(cls, new_instance=False, no_verify=False):
        """
        cloudscraper 인스턴스를 반환합니다.
        no_verify=True일 경우, SSL 인증서 검증을 비활성화한 별도의 인스턴스를 반환합니다.
        """
        if no_verify:
            if new_instance or cls._cs_scraper_no_verify_instance is None:
                try:
                    # 1. 커스텀 SSLContext 생성
                    context = ssl.create_default_context(ssl.Purpose.SERVER_AUTH)
                    context.check_hostname = False
                    context.verify_mode = ssl.CERT_NONE

                    # 2. 커스텀 HTTPAdapter 정의
                    class NoVerifyAdapter(HTTPAdapter):
                        def init_poolmanager(self, *args, **kwargs):
                            kwargs['ssl_context'] = context
                            super().init_poolmanager(*args, **kwargs)

                        def proxy_manager_for(self, *args, **kwargs):
                            kwargs['ssl_context'] = context
                            return super().proxy_manager_for(*args, **kwargs)

                    # 3. requests.Session 객체를 만들고 어댑터 마운트
                    custom_session = requests.Session()
                    custom_session.mount('https://', NoVerifyAdapter())

                    # 4. create_scraper에 직접 세션 객체 전달
                    cls._cs_scraper_no_verify_instance = cloudscraper.create_scraper(
                        sess=custom_session,
                        delay=5
                    )
                    logger.debug("Created new cloudscraper instance with SSL verification DISABLED.")
                except Exception as e_cs_create:
                    logger.error(f"Failed to create no-verify cloudscraper instance: {e_cs_create}")
                    logger.error(traceback.format_exc())
                    return None
            return cls._cs_scraper_no_verify_instance
        else:
            # 기본 인스턴스
            if new_instance or cls._cs_scraper_instance is None:
                try:
                    cls._cs_scraper_instance = cloudscraper.create_scraper(sess=cls.session, delay=5)
                    logger.debug("Created new cloudscraper instance.")
                except Exception as e_cs_create:
                    logger.error(f"Failed to create cloudscraper instance: {e_cs_create}")
                    return None
            return cls._cs_scraper_instance


    @classmethod
    def get_response_cs(cls, url, **kwargs):
        """cloudscraper를 사용하여 HTTP GET 요청을 보내고 응답 객체를 반환합니다."""
        method = kwargs.pop("method", "GET").upper()
        post_data = kwargs.pop("post_data", None)
        if post_data:
            method = "POST"

        proxies = kwargs.pop("proxies", None)
        proxy_url = None

        if proxies is None:
            if cls.config and cls.config.get('use_proxy', False):
                proxy_url = cls.config.get('proxy_url')
                if proxy_url:
                    proxies = {"http": proxy_url, "https": proxy_url}
        else:
            proxy_url = proxies.get("http", proxies.get("https"))

        kwargs.pop("cookies", None) 

        headers = kwargs.pop("headers", cls.default_headers)
        verify = kwargs.pop("verify", True)

        scraper = cls.get_cloudscraper_instance(no_verify=(not verify))
        if scraper is None:
            logger.error("SiteUtil.get_response_cs: Failed to get cloudscraper instance.")
            return None

        if headers: 
            scraper.headers.update(headers)

        try:
            if method == "POST":
                res = scraper.post(url, data=post_data, proxies=proxies, **kwargs)
            else: # GET
                res = scraper.get(url, proxies=proxies, **kwargs)

            if res.status_code == 429:
                return res

            if res.status_code != 200:
                logger.warning(f"SiteUtil.get_response_cs: Received status code {res.status_code} for URL='{url}'. Proxy='{proxy_url}'.")
                if res.status_code == 403:
                    logger.error(f"SiteUtil.get_response_cs: Received 403 Forbidden for URL='{url}'. Proxy='{proxy_url}'. Response text: {res.text[:500]}")
                return None

            return res
        except requests.exceptions.RequestException as e_req:
            logger.error(f"SiteUtil.get_response_cs: RequestException (not related to status code) for URL='{url}'. Proxy='{proxy_url}'. Error: {e_req}")
            logger.error(traceback.format_exc())
            return None
        except Exception as e_general:
            logger.error(f"SiteUtil.get_response_cs: General Exception for URL='{url}'. Proxy='{proxy_url}'. Error: {e_general}")
            logger.error(traceback.format_exc())
            return None


    @classmethod
    def _get_selenium_driver(cls):
        if not is_selenium_available:
            raise ImportError("Selenium 라이브러리가 설치되어 있지 않습니다.")
        
        selenium_url = cls.config.get('selenium_url')
        if not selenium_url: raise Exception("Selenium 서버 URL이 설정되지 않았습니다.")
        
        driver_type = cls.config.get('selenium_driver_type', 'chrome')
        logger.debug(f"[{cls.site_name}] Preparing Selenium driver. Type: {driver_type}")

        if driver_type == 'firefox':
            options = webdriver.FirefoxOptions()
            options.add_argument('--headless')
        else:
            options = webdriver.ChromeOptions()
            options.add_argument("--no-sandbox")
            options.add_argument("--disable-dev-shm-usage")
            options.add_argument("--disable-blink-features=AutomationControlled")
            options.add_experimental_option("excludeSwitches", ["enable-automation"])
            options.add_experimental_option('useAutomationExtension', False)
            options.add_argument("--disable-infobars")
            options.add_argument("--window-size=1920,1080")
            options.add_argument('user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')

        if cls.config.get('use_proxy') and cls.config.get('proxy_url'):
            proxy_url = cls.config["proxy_url"]
            if driver_type == 'firefox':
                if '@' in proxy_url:
                    parsed_proxy = urlparse(proxy_url)
                    proxy_url = f"{parsed_proxy.scheme}://{parsed_proxy.hostname}:{parsed_proxy.port}"
                parsed_proxy = urlparse(proxy_url)
                options.set_preference("network.proxy.type", 1)
                options.set_preference("network.proxy.http", parsed_proxy.hostname)
                options.set_preference("network.proxy.http_port", parsed_proxy.port)
                options.set_preference("network.proxy.ssl", parsed_proxy.hostname)
                options.set_preference("network.proxy.ssl_port", parsed_proxy.port)
            else:
                options.add_argument(f'--proxy-server={proxy_url}')

        original_timeout = socket.getdefaulttimeout()
        try:
            socket.setdefaulttimeout(30) 
            driver = webdriver.Remote(command_executor=selenium_url, options=options)
            
            if driver_type == 'chrome':
                # 광고 및 트래커 차단 (Network.setBlockedURLs)
                try:
                    driver.execute_cdp_cmd("Network.enable", {})
                    blocked_patterns = [
                        "*.doubleclick.net", "*.googleadservices.com", "*.googlesyndication.com",
                        "*.exoclick.com", "*.juicyads.com", "*.trafficjunky.com", "*.popads.net",
                        "*.popcash.net", "*.propellerads.com", "*.ero-advertising.com", "*.adxpansion.com",
                        "*.i-mobile.co.jp", "*.microad.jp", "*.ad-stir.com",
                        "*.google-analytics.com", "*.scorecardresearch.com", "*.newrelic.com",
                        "*fc2.com/ads/*", "*fc2.com/*/ads/*"
                    ]
                    driver.execute_cdp_cmd("Network.setBlockedURLs", {"urls": blocked_patterns})
                    # logger.debug(f"[{cls.site_name}] AdBlock enabled via CDP.")
                except Exception as e_cdp:
                    logger.debug(f"[{cls.site_name}] Failed to set blocked URLs: {e_cdp}")

                # Stealth 적용 로직
                stealth_applied = False
                if is_stealth_available:
                    try:
                        stealth(driver,
                            languages=["en-US", "en"],
                            vendor="Google Inc.",
                            platform="Win32",
                            webgl_vendor="Intel Inc.",
                            renderer="Intel Iris OpenGL Engine",
                            fix_hairline=True,
                        )
                        stealth_applied = True
                    except ValueError: pass
                
                if not stealth_applied:
                    driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
                        "source": """
                            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
                            window.navigator.chrome = { runtime: {} };
                            Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
                            Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });
                            const originalQuery = window.navigator.permissions.query;
                            window.navigator.permissions.query = (parameters) => (
                                parameters.name === 'notifications' ?
                                Promise.resolve({ state: Notification.permission }) :
                                originalQuery(parameters)
                            );
                        """
                    })
            return driver
        except Exception as e:
            logger.error(f"[{cls.site_name}] Selenium 드라이버 생성 실패: {e}")
            raise
        finally:
            socket.setdefaulttimeout(original_timeout)


    @classmethod
    def _quit_selenium_driver(cls, driver):
        if driver:
            try: driver.quit()
            except: pass


    @classmethod
    def _get_page_content_selenium(cls, driver, url, wait_for_locator):
        """
        Selenium을 사용하여 페이지 내용을 가져옵니다.
        Cloudflare 우회 로직만 유지합니다. (성인 인증은 각 사이트별로 처리 권장)
        """
        driver.get(url)
        time.sleep(3) # 로딩 대기

        # [삭제] 공통 성인 인증 버튼 처리 로직 제거
        # 각 사이트(site_fc2com 등)에서 _add_cookies 나 별도 로직으로 처리하는 것이 안전함.

        # 2. Cloudflare Turnstile (Shadow DOM)
        if "Just a moment" in driver.title or "Cloudflare" in driver.title:
            logger.debug(f"[{cls.site_name}] Cloudflare detected. Attempting bypass...")
            try:
                driver.execute_script("""
                    setInterval(() => {
                        function findAndClick(root) {
                            const checkbox = root.querySelector('input[type="checkbox"]');
                            if (checkbox && !checkbox.checked) {
                                checkbox.click();
                                return true;
                            }
                            const all = root.querySelectorAll('*');
                            for (let el of all) {
                                if (el.shadowRoot) findAndClick(el.shadowRoot);
                            }
                        }
                        findAndClick(document);
                    }, 1000);
                """)
                time.sleep(8)
            except Exception as e:
                logger.debug(f"[{cls.site_name}] Bypass script error: {e}")

        # 3. 결과 대기
        timeout = cls.config.get('selenium_timeout', 30)
        try:
            WebDriverWait(driver, timeout).until(EC.presence_of_element_located(wait_for_locator))
        except TimeoutException:
            # 타임아웃 시 디버깅용 파일 저장
            #try:
            #    import os
            #    tmp_dir = '/data/tmp'
            #    if not os.path.exists(tmp_dir): os.makedirs(tmp_dir, exist_ok=True)
            #    timestamp = int(time.time())
            #    
            #    driver.save_screenshot(os.path.join(tmp_dir, f"{cls.site_name}_timeout_{timestamp}.png"))
            #    logger.error(f"[{cls.site_name}] Timeout waiting for element. Screenshot saved.")
            #except: pass
            
            return None, driver.page_source

        return html.fromstring(driver.page_source), driver.page_source


    @classmethod
    def _get_page_content_flaresolverr(cls, url, validator=None):
        """
        FlareSolverr를 사용하여 페이지 내용을 가져옵니다.
        쿠키 재사용 및 재시도 로직이 포함되어 있습니다.
        """
        flaresolverr_url = cls.config.get('flaresolverr_url', '').rstrip('/')
        if not flaresolverr_url: return None, None
        
        api_url = f"{flaresolverr_url}/v1"
        payload = {
            "cmd": "request.get",
            "url": url,
            "maxTimeout": 60000,
        }
        
        if cls.config.get('use_proxy') and cls.config.get('proxy_url'):
            payload["proxy"] = {"url": cls.config['proxy_url']}

        # 재시도 루프 (최대 3회)
        for attempt in range(3):
            # 쿠키 재사용 로직
            if cls._cf_cookies and (time.time() - cls._cf_cookie_timestamp < cls.CF_COOKIE_EXPIRY):
                cookies_payload = []
                for k, v in cls._cf_cookies.items():
                    cookie_dict = {
                        "name": k, 
                        "value": v,
                        "domain": urlparse(url).hostname,
                        "path": "/"
                    }
                    cookies_payload.append(cookie_dict)
                payload["cookies"] = cookies_payload

            try:
                # logger.debug(f"[{cls.site_name}] Requesting FlareSolverr (Attempt {attempt+1}): {url}")
                res = requests.post(api_url, json=payload, headers={'Content-Type': 'application/json'}, timeout=65)
                
                if res.status_code == 200:
                    data = res.json()
                    if data.get('status') == 'ok':
                        html_source = data['solution']['response']
                        tree = html.fromstring(html_source)
                        
                        # 쿠키 갱신
                        if 'cookies' in data['solution']:
                            new_cookies = {}
                            for c in data['solution']['cookies']:
                                new_cookies[c['name']] = c['value']
                            cls._cf_cookies.update(new_cookies)
                            cls._cf_cookie_timestamp = time.time()

                        # 결과 검증 (Validator)
                        if validator:
                            if validator(tree):
                                return tree, html_source
                            else:
                                logger.debug(f"[{cls.site_name}] FlareSolverr success but validation failed. Retrying...")
                                time.sleep(2)
                                continue
                        else:
                            return tree, html_source
                    else:
                        logger.warning(f"[{cls.site_name}] FlareSolverr error: {data}")
                else:
                    logger.warning(f"[{cls.site_name}] FlareSolverr HTTP Error: {res.status_code}")
            except Exception as e:
                logger.error(f"[{cls.site_name}] FlareSolverr Connection Error: {e}")
            
            # 실패 시 잠시 대기 후 재시도
            time.sleep(2)
        
        return None, None

    # ---------------------------------------------------------
    # endregion Selenium & FlareSolverr Common Methods
    # ---------------------------------------------------------

