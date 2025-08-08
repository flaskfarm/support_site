# python 기본
import os
import time
import traceback
from datetime import timedelta
from urllib.parse import urlencode, unquote_plus
import random
import json
# python 확장
import requests
from lxml import html
from flask import Response, abort, send_file
from io import BytesIO
from PIL import Image, UnidentifiedImageError
from imagehash import dhash as hfun
from imagehash import phash 
from imagehash import average_hash

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


class SiteAvBase:
    site_name = None
    site_char = None
    module_char = None
    
    session = None
    base_default_headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/93.0.4577.82 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8",
        "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
    }
    default_headers = None
    config = None
    MetadataSetting = None

    _cs_scraper_instance = None  # cloudscraper 인스턴스 캐싱용 (선택적)
    
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
            return text
        return html.fromstring(text)

    @classmethod
    def get_text(cls, url, **kwargs):
        res = cls.get_response(url, **kwargs)
        return res.text

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
                    logger.debug(f"get_response: Overriding proxy/headers for '{cls.site_name}' with settings from '{expert_module.site_name}' for URL: {url}")

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
            # kwargs로 프록시가 전달되지 않은 경우, cls.config에서 찾음
            if cls.config and cls.config.get('use_proxy', False):
                proxy_url = cls.config.get('proxy_url')
                if proxy_url:
                    proxies = {"http": proxy_url, "https": proxy_url}
        else:
            proxy_url = proxies.get("http", proxies.get("https"))

        cookies = kwargs.pop("cookies", None)
        headers = kwargs.pop("headers", cls.default_headers)

        scraper = cls.get_cloudscraper_instance()
        if scraper is None:
            logger.error("SiteUtil.get_response_cs: Failed to get cloudscraper instance.")
            return None

        if headers: 
            scraper.headers.update(headers)

        try:
            if method == "POST":
                res = scraper.post(url, data=post_data, cookies=cookies, proxies=proxies, **kwargs)
            else: # GET
                res = scraper.get(url, cookies=cookies, proxies=proxies, **kwargs)

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


    @classmethod
    def set_config(cls, db):
        if cls.session is None:
            cls.session = cls.get_session()
        else:
            cls.session.close()
            cls.session = cls.get_session()
        
        cls.MetadataSetting = db

        if cls.config is None:
            cls.config = {}

        use_proxy = f"jav_censored_{cls.site_name}_use_proxy"
        if db.get(use_proxy) is None:
            use_proxy = f"jav_uncensored_{cls.site_name}_use_proxy"
        
        proxy_url = f"jav_censored_{cls.site_name}_proxy_url"
        if db.get(proxy_url) is None:
            proxy_url = f"jav_uncensored_{cls.site_name}_proxy_url"
        
        new_config_values = {
            "image_mode": db.get('jav_censored_image_mode'),
            "trans_option": db.get('jav_censored_trans_option'),
            "use_extras": db.get_bool('jav_censored_use_extras'),
            "max_arts": db.get_int('jav_censored_art_count'),

            # 사이트별
            "use_proxy": db.get_bool(use_proxy),
            "proxy_url": db.get(proxy_url),
        }

        cls.config.update(new_config_values)


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


    # 유사도 확인시에 호출. 0이면 오른쪽
    @classmethod
    def get_mgs_half_pl_poster(cls, pl_url: str, idx: int = 0):
        try:
            pl_image_original = cls.imopen(pl_url)
            pl_width, pl_height = pl_image_original.size

            if idx == 0:
                right_half_box = (pl_width / 2, 0, pl_width, pl_height)
                target = pl_image_original.crop(right_half_box)
            else:
                left_half_box = (0, 0, pl_width / 2, pl_height)
                target = pl_image_original.crop(left_half_box)

            return SiteUtilAv.imcrop(target, position='c')
        except Exception as e:
            logger.exception(f"MGS Special Local: Error in : {e}")


    # jav_image 기본 처리
    @classmethod
    def default_jav_image(cls, image_url, mode=None):
        # image open
        res = cls.get_response(image_url, verify=False)  # SSL 인증서 검증 비활성화 (필요시)

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

        # apply crop - quality loss
        
        if mode is not None and mode.startswith("crop_"):
            im = SiteUtilAv.imcrop(im, position=mode[-1])
        return cls.pil_to_response(im, format=imformat, mimetype=mimetype)
        #bytes_im.seek(0)
        #return send_file(bytes_im, mimetype=mimetype)


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

        # apply crop - quality loss
        
        if mode is not None and mode.startswith("crop_"):
            im = SiteUtilAv.imcrop(im, position=mode[-1])
        return cls.pil_to_response(im, format=imformat, mimetype=mimetype)
        #bytes_im.seek(0)
        #return send_file(bytes_im, mimetype=mimetype)


    @classmethod
    def pil_to_response(cls, pil, format="JPEG", mimetype='image/jpeg'):
        with BytesIO() as buf:
            pil.save(buf, format=format, quality=95)
            return Response(buf.getvalue(), mimetype=mimetype)



    # START: ADDED METHOD FOR IMAGE PROCESSING REFACTOR

    @classmethod
    def process_image_data(cls, entity, raw_image_urls, ps_url_from_cache):
        """
        이미지 처리 전체 과정을 담당하는 최상위 공통 메서드.
        __info 메서드는 이 함수를 호출하여 이미지 처리를 위임한다.
        """
        image_mode = cls.MetadataSetting.get('jav_censored_image_mode')
        final_image_sources = None
        temp_filepath_to_clean = None

        try:
            # Step 1: 이미지 서버 모드이고 사용자 포스터가 있는지 먼저 확인
            user_poster_exists = False
            if image_mode == 'image_server':
                if cls.check_user_poster_exists_for_image_server(entity):
                    user_poster_exists = True
                    logger.debug(f"Image Server: User poster for {entity.ui_code} found. Skipping image determination.")

            # Step 2: 사용자 포스터가 없을 경우에만 이미지 분석 및 결정 로직 실행
            if not user_poster_exists:
                decision_data = {
                    'raw_urls': raw_image_urls,
                    'ps_url': ps_url_from_cache,
                    'ui_code': entity.ui_code,
                    'site_name': cls.site_name,
                    'site_config': cls.config,
                }
                final_image_sources = cls.determine_final_image_sources(decision_data)
                # 정리해야 할 임시 파일 경로를 받아옴
                temp_filepath_to_clean = final_image_sources.get('temp_poster_filepath')

            # Step 3: 최종 URL 생성 및 Entity에 추가
            # finalize_images_for_entity는 final_image_sources가 None인 경우도 처리할 수 있어야 함
            cls.finalize_images_for_entity(entity, final_image_sources)

        except Exception as e:
            logger.error(f"Error during process_image_data for {entity.code}: {e}")
            logger.error(traceback.format_exc())

        finally:
            # Step 4: 임시 파일 정리
            if temp_filepath_to_clean and os.path.exists(temp_filepath_to_clean):
                try:
                    os.remove(temp_filepath_to_clean)
                    logger.debug(f"Cleaned up temporary poster file: {temp_filepath_to_clean}")
                except Exception as e_remove:
                    logger.error(f"Failed to remove temp file {temp_filepath_to_clean}: {e_remove}")

        return entity # 이미지가 추가된 entity 객체 반환


    # << Step 1 & 3-2 헬퍼: 이미지 서버 경로 및 파일 확인 >>
    @classmethod
    def get_image_server_path(cls, entity):
        """이미지 서버 저장 경로를 계산하는 헬퍼 함수"""
        local_path = cls.MetadataSetting.get('jav_censored_image_server_local_path')
        save_format = cls.MetadataSetting.get('jav_censored_image_server_save_format')
        code = entity.ui_code.lower()
        CODE = code.upper()
        label = code.split('-')[0].upper()
        label_1 = label[0]

        _format = save_format.format(
            code=code, CODE=CODE, label=label, label_1=label_1,
        ).split('/')
        return os.path.join(local_path, *(_format))

    @classmethod
    def check_user_poster_exists_for_image_server(cls, entity):
        """이미지 서버 모드에서 사용자 지정 포스터가 존재하는지 확인합니다."""
        if not entity.ui_code:
            return False
        try:
            target_folder = cls.get_image_server_path(entity)
            user_poster_filename = f"{entity.ui_code.lower()}_p_user.jpg"
            user_poster_filepath = os.path.join(target_folder, user_poster_filename)
            return os.path.exists(user_poster_filepath)
        except Exception as e:
            logger.error(f"Error checking user poster for {entity.ui_code}: {e}")
            return False


    # << Step 2 헬퍼: 이미지 소스 결정 >>
    @classmethod
    def determine_final_image_sources(cls, decision_data):
        """
        명시된 모든 조건을 반영하여 포스터 소스를 결정.
        """
        # --- 1. 초기 설정 및 변수 준비 ---
        raw_urls = decision_data.get('raw_urls', {})
        ps_url = decision_data.get('ps_url')
        ui_code = decision_data.get('ui_code', '')
        site_config = decision_data.get('site_config', {})
        site_name = decision_data.get('site_name')
        
        pl_url = raw_urls.get('pl')
        specific_candidates_on_page = raw_urls.get('specific_poster_candidates', [])
        other_arts_on_page = raw_urls.get('arts', [])
        
        final_image_sources = {
            'poster_source': None, 'poster_mode': None,
            'landscape_source': pl_url, 'arts': [], 'temp_poster_filepath': None,
            'processed_from_url': None,
        }
        poster_found = False

        # --- 2. 포스터 결정 로직 ---
        
        # 2-1. JavDB (PS 없는 사이트) 전용 로직
        if not poster_found and site_name == 'javdb' and not ps_url:
            logger.debug(f"JavDB-specific PS-less logic activated.")
            
            # 우선순위 1: 룰 기반 강제 크롭
            forced_crop_mode = None
            if ui_code:
                label = ui_code.split('-', 1)[0] if '-' in ui_code else (re.match(r'([A-Z]+)', ui_code.upper()).group(1) if re.match(r'([A-Z]+)', ui_code.upper()) else '')
                if label and site_config.get('crop_mode'):
                    for rule in site_config['crop_mode']:
                        parts = [x.strip() for x in rule.split(":", 1)]
                        if len(parts) == 2 and parts[0].upper() == label and parts[1].lower() in "rlc":
                            forced_crop_mode = parts[1].lower(); break
            if forced_crop_mode and pl_url:
                final_image_sources.update({'poster_source': pl_url, 'poster_mode': f"crop_{forced_crop_mode}"})
                poster_found = True

            # 우선순위 2: specific_poster_candidates에서 세로형 고화질 포스터 확인
            if not poster_found:
                for candidate_url in specific_candidates_on_page:
                    if cls.is_portrait_high_quality_image(candidate_url):
                        final_image_sources['poster_source'] = candidate_url
                        poster_found = True; break
            
            # 우선순위 3: PL 이미지 비율에 따른 사전 처리
            if not poster_found and pl_url:
                im_lg_obj = None
                try:
                    im_lg_obj = cls.imopen(pl_url)
                    if im_lg_obj:
                        w, h = im_lg_obj.size; aspect_ratio = w / h if h > 0 else 0
                        
                        if abs(aspect_ratio - 4/3) < 0.05:
                            im_no_lb = im_lg_obj.crop((0, int(h * 0.0533), w, h - int(h * 0.0533)))
                            processed_im = SiteUtilAv.imcrop(im_no_lb, position='r')
                            temp_filepath = cls.save_pil_to_temp(processed_im)
                            if temp_filepath: final_image_sources.update({'poster_source': temp_filepath, 'poster_mode': 'local_file', 'temp_poster_filepath': temp_filepath, 'processed_from_url': pl_url})
                            processed_im.close(); im_no_lb.close()
                        elif aspect_ratio >= 1.8:
                            right_half = im_lg_obj.crop((w / 2, 0, w, h))
                            processed_im = SiteUtilAv.imcrop(right_half, position='c')
                            temp_filepath = cls.save_pil_to_temp(processed_im)
                            if temp_filepath: final_image_sources.update({'poster_source': temp_filepath, 'poster_mode': 'local_file', 'temp_poster_filepath': temp_filepath, 'processed_from_url': pl_url})
                            processed_im.close(); right_half.close()
                        else:
                            final_image_sources.update({'poster_source': pl_url, 'poster_mode': 'crop_r'})
                finally:
                    if im_lg_obj: im_lg_obj.close()

        # 2-2. PS가 있는 다른 모든 사이트를 위한 공통 로직
        if not poster_found and ps_url:
            # logger.debug(f"Standard PS-based logic activated for site '{site_name}'.")

            # 1. 룰 기반 예외처리
            apply_ps_to_poster = False
            forced_crop_mode = None
            if ui_code:
                label_from_ui_code = ui_code.split('-', 1)[0] if '-' in ui_code else (re.match(r'([A-Z]+)', ui_code.upper()).group(1) if re.match(r'([A-Z]+)', ui_code.upper()) else '')
                if label_from_ui_code:
                    if site_config.get('ps_force_labels_set') and label_from_ui_code in site_config['ps_force_labels_set']:
                        apply_ps_to_poster = True
                    if site_config.get('crop_mode'):
                        for line in site_config['crop_mode']:
                            parts = [x.strip() for x in line.split(":", 1)]
                            if len(parts) == 2 and parts[0].upper() == label_from_ui_code and parts[1].lower() in "rlc":
                                forced_crop_mode = parts[1].lower()
                                break
            if forced_crop_mode and pl_url:
                final_image_sources.update({'poster_source': pl_url, 'poster_mode': f"crop_{forced_crop_mode}"})
                poster_found = True
            elif apply_ps_to_poster:
                final_image_sources['poster_source'] = ps_url
                poster_found = True

            # 2. 고화질 세로 포스터 탐색
            if not poster_found:
                poster_candidates_simple = ([pl_url] if pl_url else []) + specific_candidates_on_page
                im_sm_obj = None
                try:
                    im_sm_obj = cls.imopen(ps_url)
                    if im_sm_obj:
                        for candidate_url in poster_candidates_simple:
                            im_lg_obj = None
                            try:
                                im_lg_obj = cls.imopen(candidate_url)
                                if im_lg_obj and cls.is_portrait_high_quality_image(im_lg_obj) and cls.is_hq_poster(im_sm_obj, im_lg_obj):
                                    final_image_sources['poster_source'] = candidate_url
                                    poster_found = True
                                    break # for 루프 탈출
                            finally:
                                if im_lg_obj: im_lg_obj.close()
                finally:
                    if im_sm_obj: im_sm_obj.close()

            # 3. 특수 / 일반 처리
            if not poster_found:
                all_candidates_advanced = list(dict.fromkeys(([pl_url] if pl_url else []) + other_arts_on_page))
                im_sm_obj = cls.imopen(ps_url)
                if im_sm_obj:
                    try:
                        for candidate_url in all_candidates_advanced:
                            im_lg_obj = None
                            try:
                                im_lg_obj = cls.imopen(candidate_url)
                                if not im_lg_obj: continue
                                w, h = im_lg_obj.size
                                aspect_ratio = w / h if h > 0 else 0
                                
                                # 규칙 1: DMM 특수 사이즈
                                if w == 800 and 436 <= h <= 446:
                                    processed_im = im_lg_obj.crop((w - 380, 0, w, h))
                                    temp_filepath = cls.save_pil_to_temp(processed_im)
                                    if temp_filepath:
                                        final_image_sources.update({'poster_source': temp_filepath, 'poster_mode': 'local_file', 'temp_poster_filepath': temp_filepath, 'processed_from_url': candidate_url})
                                        poster_found = True
                                    processed_im.close()
                                
                                # 규칙 2: 4:3 비율 (레터박스)
                                elif abs(aspect_ratio - 4/3) < 0.05:
                                    crop_pos = cls.has_hq_poster(im_sm_obj, im_lg_obj)
                                    if crop_pos:
                                        final_image_sources.update({'poster_source': candidate_url, 'poster_mode': f"crop_{crop_pos}"})
                                        poster_found = True
                                    else:
                                        im_no_lb = im_lg_obj.crop((0, int(h * 0.0533), w, h - int(h * 0.0533)))
                                        crop_pos_lb = cls.has_hq_poster(im_sm_obj, im_no_lb)
                                        if crop_pos_lb:
                                            final_poster_obj = SiteUtilAv.imcrop(im_no_lb, position=crop_pos_lb)
                                            temp_filepath = cls.save_pil_to_temp(final_poster_obj)
                                            if temp_filepath:
                                                final_image_sources.update({'poster_source': temp_filepath, 'poster_mode': 'local_file', 'temp_poster_filepath': temp_filepath, 'processed_from_url': candidate_url})
                                                poster_found = True
                                            final_poster_obj.close()
                                        im_no_lb.close()

                                # 규칙 3: 1.8:1 이상 와이드 (MG-Style)
                                elif aspect_ratio >= 1.8:
                                    crop_pos = cls.has_hq_poster(im_sm_obj, im_lg_obj)
                                    if crop_pos:
                                        final_image_sources.update({'poster_source': candidate_url, 'poster_mode': f"crop_{crop_pos}"})
                                        poster_found = True
                                    else:
                                        right_half = im_lg_obj.crop((w / 2, 0, w, h))
                                        if cls.is_hq_poster(im_sm_obj, right_half):
                                            final_poster_obj = SiteUtilAv.imcrop(right_half, position='c')
                                            temp_filepath = cls.save_pil_to_temp(final_poster_obj)
                                            if temp_filepath:
                                                final_image_sources.update({'poster_source': temp_filepath, 'poster_mode': 'local_file', 'temp_poster_filepath': temp_filepath, 'processed_from_url': candidate_url})
                                                poster_found = True
                                            final_poster_obj.close()
                                        right_half.close()
                                        
                                        if not poster_found:
                                            left_half = im_lg_obj.crop((0, 0, w / 2, h))
                                            if cls.is_hq_poster(im_sm_obj, left_half):
                                                final_poster_obj = SiteUtilAv.imcrop(left_half, position='c')
                                                temp_filepath = cls.save_pil_to_temp(final_poster_obj)
                                                if temp_filepath:
                                                    final_image_sources.update({'poster_source': temp_filepath, 'poster_mode': 'local_file', 'temp_poster_filepath': temp_filepath, 'processed_from_url': candidate_url})
                                                    poster_found = True
                                                final_poster_obj.close()
                                            left_half.close()

                                # 규칙 4: 일반 이미지
                                else:
                                    crop_pos = cls.has_hq_poster(im_sm_obj, im_lg_obj)
                                    if crop_pos:
                                        final_image_sources.update({'poster_source': candidate_url, 'poster_mode': f"crop_{crop_pos}"})
                                        poster_found = True
                            finally:
                                if im_lg_obj: im_lg_obj.close()
                            if poster_found: break
                    finally:
                        if im_sm_obj: im_sm_obj.close()

            # 4. 최종 폴백
            if not final_image_sources.get('poster_source') and ps_url:
                final_image_sources['poster_source'] = ps_url

        # --- 3. 팬아트 목록 결정 (항상 마지막에 실행) ---
        final_thumb_source_urls = set()
        if final_image_sources.get('landscape_source'):
            final_thumb_source_urls.add(final_image_sources['landscape_source'])
        
        poster_source = final_image_sources.get('poster_source')
        poster_mode = final_image_sources.get('poster_mode')
        
        if poster_mode == 'local_file':
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


    @classmethod
    def has_hq_poster_from_url(cls, im_sm_source, im_lg_source):
        """
        이미지 소스(URL/경로)를 직접 받아 has_hq_poster를 호출하는 래퍼 함수.
        내부에서 이미지 객체를 열고 닫는 것을 책임진다.
        """
        im_sm_obj, im_lg_obj = None, None
        try:
            im_sm_obj = cls.imopen(im_sm_source)
            im_lg_obj = cls.imopen(im_lg_source)
            return cls.has_hq_poster(im_sm_obj, im_lg_obj)
        except Exception as e:
            logger.error(f"Error in has_hq_poster_from_url for '{im_lg_source}': {e}")
            return None
        finally:
            if im_sm_obj: im_sm_obj.close()
            if im_lg_obj: im_lg_obj.close()


    # END: ADDED METHOD


    # 의미상 메타데이터에서 처리해야한다.
    # 귀찮아서 일단 여기서 처리
    # 이미지 처리모드는 기본(ff_proxy)와 discord_proxy, image_server가 있다.
    # 오리지널은 proxy사용 여부에 따라 ff_proxy에서 판단한다.
    @classmethod
    def finalize_images_for_entity(cls, entity, image_sources):
        if entity.thumb == None:
            entity.thumb = []
        if entity.fanart == None:
            entity.fanart = []
        image_mode = cls.MetadataSetting.get('jav_censored_image_mode')

        # image_sources가 None일 경우(image_server 모드에서 사용자 파일이 이미 있을 때)에 대한 방어 코드
        if image_sources is None and image_mode != 'image_server':
            # logger.warning("image_sources is None but image_mode is not 'image_server'. No images will be processed.")
            return

        if image_mode == 'ff_proxy':
            # image_sources가 없을 경우를 대비한 방어 코드
            if not image_sources or not image_sources.get('poster_source'):
                return

            poster_source = image_sources['poster_source']
            poster_mode = image_sources.get('poster_mode', '')

            # proxy를 사용하거나, mode가 있거나, 로컬 파일인 경우 ff_proxy URL 생성
            if cls.config['use_proxy'] or poster_mode:
                if poster_mode == 'local_file':
                    # 사전 처리된 로컬 파일인 경우
                    param = {
                        'site': 'system',
                        'path': poster_source 
                    }
                else:
                    # 원격 URL이거나, 원격 URL에 crop 모드가 적용된 경우
                    param = {
                        'site': cls.site_name,
                        'url': unquote_plus(poster_source), 
                        'mode': poster_mode
                    }
                
                if param.get('mode') in [None, '']:
                    del param['mode']

                param_str = urlencode(param)
                module_prefix = 'jav_image' if cls.module_char == 'C' else 'jav_image_un'
                url = f"{F.SystemModelSetting.get('ddns')}/metadata/normal/{module_prefix}?{param_str}"
            else:
                # 프록시도, 모드도 없는 순수 원격 URL
                url = poster_source
            entity.thumb.append(EntityThumb(aspect="poster", value=url))

            if image_sources.get('landscape_source'):
                landscape_source = image_sources['landscape_source']
                if cls.config['use_proxy']:
                    param = urlencode({
                        'site': cls.site_name,
                        'url': unquote_plus(landscape_source)
                    })
                    module_prefix = 'jav_image' if cls.module_char == 'C' else 'jav_image_un'
                    url = f"{F.SystemModelSetting.get('ddns')}/metadata/normal/{module_prefix}?{param}"
                else:
                    url = landscape_source
                entity.thumb.append(EntityThumb(aspect="landscape", value=url))

            for art_url in image_sources.get('arts', []):
                if cls.config['use_proxy']:
                    param = urlencode({
                        'site': cls.site_name,
                        'url': unquote_plus(art_url)
                    })
                    module_prefix = 'jav_image' if cls.module_char == 'C' else 'jav_image_un'
                    url = f"{F.SystemModelSetting.get('ddns')}/metadata/normal/{module_prefix}?{param}"
                else:
                    url = art_url
                entity.fanart.append(url)

        elif image_mode == 'discord_proxy':
            if not image_sources or not image_sources.get('poster_source'):
                return

            def apply(url, use_proxy_server, server_url):
                if use_proxy_server == False:
                    return url
                url = server_url.rstrip('/') + '/attachments/' + url.split('/attachments/')[1]
                return url

            use_proxy_server = cls.MetadataSetting.get_bool('jav_censored_use_discord_proxy_server')
            server_url = cls.MetadataSetting.get('jav_censored_discord_proxy_server_url')
            use_my_webhook = cls.MetadataSetting.get_bool('jav_censored_use_my_webhook')
            webhook_list = cls.MetadataSetting.get_list('jav_censored_my_webhook_list')
            webhook_url = None

            # poster
            response = cls.jav_image(image_sources['poster_source'], mode=image_sources.get('poster_mode', ''))

            if poster_mode == 'local_file':
                # 로컬 파일인 경우, 파일을 직접 읽어서 BytesIO 생성
                with open(poster_source, 'rb') as f:
                    response_bytes = BytesIO(f.read())
            else:
                # 원격 URL인 경우, jav_image를 통해 이미지 데이터 가져오기
                response = cls.jav_image(url=poster_source, mode=poster_mode, site=cls.site_name)
                response_bytes = BytesIO(response.data)

            if use_my_webhook:
                webhook_url = webhook_list[random.randint(0,len(webhook_list)-1)]
            url = SupportDiscord.discord_proxy_image_bytes(response_bytes, webhook_url=webhook_url)
            url = apply(url, use_proxy_server, server_url)
            entity.thumb.append(EntityThumb(aspect="poster", value=url))

            # poster
            response = cls.jav_image(image_sources['landscape_source'])
            response_bytes = BytesIO(response.data)
            if use_my_webhook:
                webhook_url = webhook_list[random.randint(0,len(webhook_list)-1)]
            url = SupportDiscord.discord_proxy_image_bytes(response_bytes, webhook_url=webhook_url)
            url = apply(url, use_proxy_server, server_url)
            entity.thumb.append(EntityThumb(aspect="landscape", value=url))

            # arts
            for art_url in image_sources['arts']:
                response = cls.jav_image(art_url)
                response_bytes = BytesIO(response.data)
                if use_my_webhook:
                    webhook_url = webhook_list[random.randint(0,len(webhook_list)-1)]
                url = SupportDiscord.discord_proxy_image_bytes(response_bytes, webhook_url=webhook_url)
                url = apply(url, use_proxy_server, server_url)
                entity.fanart.append(url)
            
        elif image_mode == 'image_server':
            server_url = cls.MetadataSetting.get('jav_censored_image_server_url').rstrip('/')
            local_path = cls.MetadataSetting.get('jav_censored_image_server_local_path')

            save_format = cls.MetadataSetting.get('jav_censored_image_server_save_format')
            rewrite = cls.MetadataSetting.get_bool('jav_censored_image_server_rewrite')

            code = entity.ui_code.lower()
            CODE = code.upper()
            label = code.split('-')[0].upper()
            label_1 = label[0]

            _format = save_format.format(
                code=code,
                CODE=CODE,
                label=label,
                label_1=label_1,
            ).split('/')
            target_folder = os.path.join(local_path, *(_format))

            # 포스터
            data = {
                "poster": [f"{code}_p_user.jpg", f"{code}_p.jpg"],
                "landscape": [f"{code}_pl_user.jpg", f"{code}_pl.jpg"],
            }
            for aspect, filenames in data.items():
                save = True
                for idx, filename in enumerate(filenames):
                    filepath = os.path.join(target_folder, filename)
                    url = f"{server_url}/{os.path.relpath(filepath, local_path)}".replace("\\", "/")
                    if idx == 0 and os.path.exists(filepath):
                        entity.thumb.append(EntityThumb(aspect=aspect, value=url))
                        save = False
                        break
                    elif idx == 1 and os.path.exists(filepath):
                        if not rewrite:
                            entity.thumb.append(EntityThumb(aspect=aspect, value=url))
                            save = False

                if save and image_sources:
                    os.makedirs(os.path.dirname(filepath), exist_ok=True)
                    
                    source_key = 'poster_source' if aspect == 'poster' else 'landscape_source'
                    source = image_sources.get(source_key)
                    if not source: continue

                    mode = image_sources.get('poster_mode') if aspect == 'poster' else None

                    if mode == 'local_file':
                        # 로컬 파일은 복사
                        import shutil
                        shutil.copy(source, filepath)
                    else:
                        # 원격 파일은 다운로드
                        response = cls.jav_image(url=source, mode=mode, site=cls.site_name)
                        with open(filepath, 'wb') as f:
                            f.write(response.data)
                    entity.thumb.append(EntityThumb(aspect=aspect, value=url))

            # arts
            if image_sources and image_sources.get('arts'):
                for idx, art_url in enumerate(image_sources['arts']):
                    filename = f"{entity.ui_code.lower()}_art_{idx+1}.jpg"
                    filepath = os.path.join(target_folder, filename)
                    url = f"{server_url}/{os.path.relpath(filepath, local_path)}".replace("\\", "/")
                    if os.path.exists(filepath) and not rewrite:
                        entity.fanart.append(url)
                        continue
                    os.makedirs(os.path.dirname(filepath), exist_ok=True)
                    response = cls.jav_image(url=art_url, site=cls.site_name)
                    with open(filepath, 'wb') as f:
                        f.write(response.data)
                    entity.fanart.append(url)

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
    def are_images_visually_same(cls, img_src1, img_src2, threshold=10):
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
            im1 = cls.imopen(img_src1) 
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
    def is_hq_poster(cls, im_sm_obj, im_lg_obj):
        """두 PIL Image 객체의 시각적 유사성을 판단합니다."""
        try:
            if im_sm_obj is None or im_lg_obj is None: return False
            
            ws, hs = im_sm_obj.size; wl, hl = im_lg_obj.size
            if hs == 0 or hl == 0: return False
            if abs((ws / hs) - (wl / hl)) > 0.1: return False

            hdis_d = hfun(im_sm_obj) - hfun(im_lg_obj)
            if hdis_d >= 14: return False
            if hdis_d <= 6: return True

            hdis_p = phash(im_sm_obj) - phash(im_lg_obj)
            return (hdis_d + hdis_p) < 24
        except Exception: return False


    @classmethod
    def has_hq_poster(cls, im_sm_obj, im_lg_obj):
        """두 PIL Image 객체를 받아 크롭 영역 일치 여부를 판단하고 크롭 위치를 반환합니다."""
        try:
            if im_sm_obj is None or im_lg_obj is None: return None
            
            ws, hs = im_sm_obj.size; wl, hl = im_lg_obj.size
            if ws > wl or hs > hl: return None

            positions = ["r", "l", "c"]
            threshold = 20  # 이 임계값은 필요에 따라 조정 가능

            for pos in positions:
                cropped_im = None
                try:
                    cropped_im = SiteUtilAv.imcrop(im_lg_obj, position=pos)
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


    @classmethod
    def _internal_has_hq_poster_comparison(cls, im_sm_obj, im_lg_to_compare, function_name_for_log="has_hq_poster", sm_source_info=None, lg_source_info=None):
        # [수정] sm_source_info, lg_source_info 파라미터를 기본값 None으로 추가
        
        ws, hs = im_sm_obj.size
        wl, hl = im_lg_to_compare.size
        if ws > wl or hs > hl:
            logger.debug(f"{function_name_for_log} for '{sm_source_info}' vs '{lg_source_info}': Small image ({ws}x{hs}) > large image ({wl}x{hl}).")
            return None

        positions = ["r", "l", "c"]
        ahash_threshold = 10
        for pos in positions:
            try:
                cropped_im = SiteUtilAv.imcrop(im_lg_to_compare, position=pos)
                if cropped_im is None: 
                    continue
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
                cropped_im = SiteUtilAv.imcrop(im_lg_to_compare, position=pos)
                if cropped_im is None: continue
                if phash(im_sm_obj) - phash(cropped_im) <= phash_threshold:
                    logger.debug(f"{function_name_for_log} for '{sm_source_info}' vs '{lg_source_info}': Found similar (phash) at pos '{pos}'.")
                    return pos
            except Exception as e_phash:
                logger.error(f"{function_name_for_log} for '{sm_source_info}' vs '{lg_source_info}': Exception during phash for pos '{pos}': {e_phash}")
                continue

        logger.debug(f"{function_name_for_log} for '{sm_source_info}' vs '{lg_source_info}': No similar region found (ahash & phash).")
        return None



    
    # 파일명에 indx 포함. 0 우, 1 좌
    @classmethod
    def get_mgs_half_pl_poster_info_local(cls, ps_url: str, pl_url: str, do_save:bool = True):
        """
        MGStage용으로 pl 이미지를 특별 처리합니다. (로컬 임시 파일 사용)
        pl 이미지를 가로로 반으로 자르고 (오른쪽 우선), 각 절반의 중앙 부분을 ps와 비교합니다.
        is_hq_poster 검사 성공 시에만 해당 결과를 사용하고,
        모든 검사 실패 시에는 None, None, None을 반환합니다.
        """
        try:
            # logger.debug(f"MGS Special Local: Trying get_mgs_half_pl_poster_info_local for ps='{ps_url}', pl='{pl_url}'")
            if not ps_url or not pl_url: return None, None, None

            ps_image = cls.imopen(ps_url)
            pl_image_original = cls.imopen(pl_url)

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
                    with SiteUtilAv.imcrop(img_obj_to_crop, position='c') as center_cropped_candidate_obj:

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







    # endregion SiteUtilAV 이미지 처리 관련
    ################################################
    



    
    ################################################
    # region 유틸

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


    # endregion 유틸
    ################################################
