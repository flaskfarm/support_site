# python 기본
import os
import re
import time
import traceback
from datetime import timedelta
from urllib.parse import urlencode, unquote_plus
import random
import json
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
from tool import ToolUtil
from ..site_util_av import SiteUtilAv
from ..entity_base import EntityThumb
from ..trans_util import TransUtil
from ..entity_base import EntityActor

try:
    import cloudscraper
except ImportError:
    os.system("pip install cloudscraper")
    import cloudscraper

try:
    from dateutil.parser import parse
except ImportError:
    os.system("pip install dateutils")
    from dateutil.parser import parse

try:
    from imagehash import dhash as hfun, phash, average_hash
    _IMAGEHASH_AVAILABLE = True
except ImportError:
    _IMAGEHASH_AVAILABLE = False
    hfun = phash = average_hash = None

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

    _cs_scraper_instance = None  # cloudscraper 인스턴스 캐싱용 (선택적)
    _cs_scraper_no_verify_instance = None # SSL 검증 안하는 인스턴스 캐싱용
    
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
        res = cls.get_response(url, **kwargs)
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
        # 순환 참조를 피하기 위해 함수 내에서 필요한 모듈을 임포트
        try:
            from .site_dmm import SiteDmm
            from .site_mgstage import SiteMgstage
            # 규칙: {타겟 도메인: 해당 도메인을 처리할 스위치 사이트 모듈 클래스}
            CONTEXT_SWITCH_RULES = {
                'dmm.co.jp': SiteDmm,
                'mgstage.com': SiteMgstage,
                'r18.com': SiteMgstage,
            }
        except ImportError:
            CONTEXT_SWITCH_RULES = {} # 임포트 실패 시 규칙 비활성화

        # 기본값은 현재 실행 중인 모듈(cls)의 설정을 사용
        proxies = None
        if cls.config and cls.config.get('use_proxy', False):
            proxies = {"http": cls.config['proxy_url'], "https": cls.config['proxy_url']}

        request_headers = kwargs.pop("headers", cls.default_headers.copy())

        # URL을 분석하여 스위치 모듈의 설정이 필요한지 확인
        for domain, expert_module in CONTEXT_SWITCH_RULES.items():
            if domain in url:
                # expert_module이 성공적으로 임포트되었고,
                # 현재 모듈이 해당 도메인의 스위치가 아닐 경우에만 설정 빌려오기
                if expert_module and cls.site_name != expert_module.site_name:
                    # logger.debug(f"get_response: Overriding proxy/headers for '{cls.site_name}' with settings from '{expert_module.site_name}' for URL: {url}")

                    # 스위치 모듈의 프록시 설정으로 덮어쓰기
                    if expert_module.config and expert_module.config.get('use_proxy', False):
                        proxies = {"http": expert_module.config['proxy_url'], "https": expert_module.config['proxy_url']}
                    else:
                        proxies = None

                    # 스위치 모듈의 헤더를 가져와 업데이트 (기존 헤더에 추가/덮어쓰기)
                    request_headers.update(expert_module.default_headers)

                    # DMM의 경우, Referer와 Cookie를 확실하게 설정
                    if expert_module.site_name == 'dmm':
                        request_headers['Referer'] = 'https://www.dmm.co.jp/'
                        dmm_cookie = expert_module.session.cookies.get('age_check_done', domain='.dmm.co.jp')
                        if dmm_cookie:
                            request_headers['Cookie'] = f"age_check_done={dmm_cookie}"
                break # 첫 번째 일치하는 규칙만 적용

        method = kwargs.pop("method", "GET")
        post_data = kwargs.pop("post_data", None)
        if post_data:
            method = "POST"
            kwargs["data"] = post_data

        try:
            # 요청의 주체는 항상 현재 모듈(cls)의 세션
            res = cls.session.request(method, url, headers=request_headers, proxies=proxies, **kwargs)
            return res
        except requests.exceptions.RequestException as e:
            logger.error(f"get_response: RequestException for URL='{url}'. Error: {e}")
            logger.error(traceback.format_exc())
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


# site_av_base.py

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

            req = cls.session.get(url, proxies=proxies, headers=request_headers, stream=True)
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

        cls.config.update({
            # 공통 설정 (항상 jav_censored 값을 사용)
            "image_mode": db.get(f'{common_config_prefix}_image_mode'),
            "trans_option": db.get(f'{common_config_prefix}_trans_option'),
            "use_extras": db.get_bool(f'{common_config_prefix}_use_extras'),
            "max_arts": db.get_int(f'{common_config_prefix}_art_count'),
            "use_imagehash": db.get_bool(f'{common_config_prefix}_use_imagehash'),
            "selenium_url": db.get('jav_uncensored_selenium_url'),

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
        # image open
        res = cls.get_response(image_url, verify=False)  # SSL 인증서 검증 비활성화 (필요시)

        if res is None:
            P.logger.error(f"image_proxy: SiteUtil.get_response returned None for URL: {image_url}")
            abort(404) # 또는 적절한 에러 응답
            return # 함수 종료

        if res.status_code != 200:
            P.logger.error(f"image_proxy: Received status code {res.status_code} for URL: {image_url}. Content: {res.text[:200]}")
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
            P.logger.error(f"image_proxy: Received status code {res.status_code} for URL: {image_url}. Content: {res.text[:200]}")
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
                    logger.debug(f"Using pre-calculated image server path from entity: {pre_calculated_target_folder}")
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
        use_advanced_comparison = _IMAGEHASH_AVAILABLE and cls.config.get('use_imagehash', False)

        if ps_url and not use_advanced_comparison:
            if not _IMAGEHASH_AVAILABLE:
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

        # --- 3. 포스터 소스 결정 (필요한 경우에만) ---
        if should_process_poster:
            # logger.debug(f"Determining poster source for {ui_code} as no user/system file exists or rewrite is on.")
            
            if direct_poster_url:
                # Case 1: Uncensored 등 이미 포스터가 확정된 경우
                logger.debug(f"Using pre-determined poster URL for {ui_code}.")
                final_image_sources['poster_source'] = direct_poster_url

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

                # 2. (자동 탐색) 우선 후보군 탐색
                if not final_image_sources['poster_source']:
                    poster_candidates_simple = ([pl_url] if pl_url else []) + specific_candidates_on_page
                    im_sm_obj = cls.imopen(ps_url)
                    if im_sm_obj:
                        for candidate_url in poster_candidates_simple:
                            im_lg_obj = None # finally 블록을 위해 미리 선언
                            try:
                                im_lg_obj = cls.imopen(candidate_url)

                                if im_lg_obj and cls.is_hq_poster(im_sm_obj, im_lg_obj):
                                    logger.info(f"Found ideal poster (visually same as thumbnail): {candidate_url}")
                                    final_image_sources['poster_source'] = candidate_url
                                    break
                            finally:
                                if im_lg_obj: im_lg_obj.close()

                        im_sm_obj.close()

                # 3. (자동 탐색) 확장 후보군 탐색
                if not final_image_sources['poster_source']:
                    all_candidates_advanced = list(dict.fromkeys(([pl_url] if pl_url else []) + other_arts_on_page))
                    standard_aspect_ratio = 1.4225

                    im_sm_obj = cls.imopen(ps_url)
                    if im_sm_obj:
                        try:
                            # Phase 1: 확장 후보군에 대해 is_hq_poster로 먼저 빠르게 검사
                            # logger.debug("Advanced Check (Phase 1): Performing fast strict check on all advanced candidates.")
                            for candidate_url in all_candidates_advanced:
                                im_lg_obj = None
                                try:
                                    im_lg_obj = cls.imopen(candidate_url)
                                    # is_hq_poster (엄격한 기준)로 완벽한 매칭 찾기
                                    if im_lg_obj and cls.is_hq_poster(im_sm_obj, im_lg_obj):
                                        logger.info(f"HQ Poster Found in advanced Phase 1: {candidate_url}")
                                        final_image_sources['poster_source'] = candidate_url
                                        break # 찾았으면 즉시 종료
                                finally:
                                    if im_lg_obj: im_lg_obj.close()

                            # Phase 2: Phase 1에서 못 찾았을 경우에
                            if not final_image_sources['poster_source']:
                                # logger.debug("Advanced Check (Phase 2): Strict check failed. Performing detailed analysis.")
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
                                                            logger.info(f"HQ Poster Found (Letterbox Processed): Saved to {temp_filepath}")
                                                        else:
                                                            logger.error("Failed to save the final cropped poster to a temporary file.")
                                            finally:
                                                if processed_lg_obj: processed_lg_obj.close()
                                                if final_poster: final_poster.close()

                                        # 2, 3순위는 1순위에서 찾지 못했을 경우에만 실행
                                        if not found_poster_for_this_candidate:
                                            # 2순위: 1.7:1 이상 와이드 이미지 처리
                                            if aspect_ratio >= 1.7:
                                                # 기본 비교: 원본 썸네일 사용
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
                                                # 재시도: 썸네일 레터박스 제거 후 비교
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
                                                # 표준 포스터 비율 강제 적용
                                                single_pos = cls.has_hq_poster(im_sm_obj, im_lg_obj, aspect_ratio=standard_aspect_ratio)
                                                if single_pos:
                                                    crop_pos = f"{single_pos}_{standard_aspect_ratio:.4f}"
                                                    logger.debug(f"HQ Poster Found (Standard): using mode {crop_pos}")

                                            # 2, 3순위 최종 결과 저장
                                            if crop_pos:
                                                logger.info(f"HQ Poster Found Matched in Advanced Phase 2: '{candidate_url}' using mode '{crop_pos}'.")
                                                final_image_sources.update({'poster_source': candidate_url, 'poster_mode': f"crop_{crop_pos}"})
                                                found_poster_for_this_candidate = True
                                    finally:
                                        if im_lg_obj: im_lg_obj.close()

                                    # 이 후보에서 포스터를 찾았다면, 전체 for 루프를 탈출
                                    if found_poster_for_this_candidate:
                                        break

                            # for 루프가 break 없이 모두 실행된 후
                            else: # no-break
                                if not final_image_sources.get('poster_source'):
                                    logger.debug("Advanced Check: No HQ poster found in any advanced candidates.")

                        finally:
                            if im_sm_obj:
                                im_sm_obj.close()

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

                # 3. (자동 분석) 위 방법들이 모두 실패했을 경우, 비율 기반 분석
                if not final_image_sources['poster_source']:
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
    def finalize_images_for_entity(cls, entity, decision_data): # 인자 2개 (cls 제외)
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
            if poster_mode == 'local_file':
                # 로컬 파일인 경우, 파일을 직접 읽어서 BytesIO 생성
                with open(poster_source, 'rb') as f:
                    response_bytes = BytesIO(f.read())
            else:
                # 원격 URL인 경우, jav_image를 통해 이미지 데이터 가져오기
                response = cls.jav_image(url=poster_source, mode=poster_mode, site=cls.site_name)
                response_bytes = BytesIO(response.data)

            if use_my_webhook and webhook_list:
                webhook_url = webhook_list[random.randint(0, len(webhook_list) - 1)]

            discord_url = SupportDiscord.discord_proxy_image_bytes(response_bytes, webhook_url=webhook_url)
            final_url = apply(discord_url, use_proxy_server, server_url)
            entity.thumb.append(EntityThumb(aspect="poster", value=final_url))

            # --- 랜드스케이프 처리 ---
            if landscape_source:
                response = cls.jav_image(url=landscape_source, site=cls.site_name)
                response_bytes = BytesIO(response.data)
                if use_my_webhook and webhook_list:
                    webhook_url = webhook_list[random.randint(0, len(webhook_list) - 1)]

                discord_url = SupportDiscord.discord_proxy_image_bytes(response_bytes, webhook_url=webhook_url)
                final_url = apply(discord_url, use_proxy_server, server_url)
                entity.thumb.append(EntityThumb(aspect="landscape", value=final_url))

            # --- 팬아트 처리 ---
            for art_url in arts:
                response = cls.jav_image(url=art_url, site=cls.site_name)
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

                    if source_mode == 'local_file':
                        import shutil
                        shutil.copy(poster_source, system_poster_path)
                    else:
                        response = cls.jav_image(url=poster_source, mode=source_mode, site=cls.site_name)
                        if response and response.status_code == 200:
                            with open(system_poster_path, 'wb') as f: f.write(response.data)
                        else:
                            logger.error(f"Failed to download poster for {code_lower} from {poster_source}")

                    entity.thumb.append(EntityThumb(aspect="poster", value=f"{server_url_prefix}/{code_lower}_p.jpg"))

            # --- 랜드스케이프 처리 ---
            landscape_source = image_sources.get('landscape_source')
            if landscape_source:
                if image_sources.get('skip_landscape_download'):
                    entity.thumb.append(EntityThumb(aspect="landscape", value=landscape_source))
                else: # 다운로드 필요
                    system_landscape_path = os.path.join(target_folder, f"{code_lower}_pl.jpg")
                    os.makedirs(target_folder, exist_ok=True)
                    response = cls.jav_image(url=landscape_source, site=cls.site_name)
                    if response and response.status_code == 200:
                        with open(system_landscape_path, 'wb') as f: f.write(response.data)
                    else:
                        logger.error(f"Failed to download landscape for {code_lower} from {landscape_source}")

                    entity.thumb.append(EntityThumb(aspect="landscape", value=f"{server_url_prefix}/{code_lower}_pl.jpg"))

            # --- 팬아트 처리 ---
            # 덮어쓰기 on 또는 기존 팬아트 없음 -> 새로 다운로드
            if rewrite or system_files_exist.get('arts', 0) == 0:
                # 덮어쓰기 모드이면 기존 아트 파일 삭제
                if rewrite and os.path.exists(target_folder):
                    for f in os.listdir(target_folder):
                        if f.startswith(f"{code_lower}_art_"):
                            try: os.remove(os.path.join(target_folder, f))
                            except: pass

                for idx, art_url in enumerate(image_sources.get('arts', [])):
                    filename = f"{code_lower}_art_{idx+1}.jpg"
                    filepath = os.path.join(target_folder, filename)
                    os.makedirs(os.path.dirname(filepath), exist_ok=True)
                    response = cls.jav_image(url=art_url, site=cls.site_name)
                    if response and response.status_code == 200:
                        with open(filepath, 'wb') as f: f.write(response.data)
                        entity.fanart.append(f"{server_url_prefix}/{filename}")
                    else:
                        logger.error(f"Failed to download art for {code_lower} from {art_url}")
            # 덮어쓰기 off and 기존 팬아트 존재 -> 기존 파일 URL만 추가
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
            if im_sm_obj is None or im_lg_obj is None: return False

            ws, hs = im_sm_obj.size; wl, hl = im_lg_obj.size
            if hs == 0 or hl == 0: return False
            if abs((ws / hs) - (wl / hl)) > 0.1: return False

            hdis_d = hfun(im_sm_obj) - hfun(im_lg_obj)
            if hdis_d >= 10: return False
            if hdis_d <= 5: return True

            hdis_p = phash(im_sm_obj) - phash(im_lg_obj)
            threshold = cls.config.get('hq_poster_threshold_strict', 10)
            return (hdis_d + hdis_p) < threshold
        except Exception: return False


    @classmethod
    def has_hq_poster(cls, im_sm_obj, im_lg_obj, aspect_ratio):
        """두 PIL Image 객체를 받아 크롭 영역 일치 여부를 판단하고 크롭 위치를 반환합니다."""
        try:
            if im_sm_obj is None or im_lg_obj is None: return None

            ws, hs = im_sm_obj.size; wl, hl = im_lg_obj.size
            if ws > wl or hs > hl: return None

            positions = ["c", "r", "l"]
            threshold = cls.config.get('hq_poster_threshold_normal', 30)

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

        logger.debug(f"[{cls.site_name}] _parse_ui_code_uncensored started for '{cid_part_raw}'. Using {len(special_rules)} special + {len(generic_rules)} generic rules.")

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
                    logger.debug(f"Uncensored Parser: Matched Rule '{pattern}' -> Label:'{final_label_part}', Num:'{final_num_part}'")
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


    # endregion 유틸
    ################################################
