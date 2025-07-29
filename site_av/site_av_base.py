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
        
        proxies = None
        if cls.config and cls.config.get('use_proxy', False):
            proxies = {"http": cls.config['proxy_url'], "https": cls.config['proxy_url']}

        request_headers = kwargs.pop("headers", cls.default_headers)
        method = kwargs.pop("method", "GET")
        post_data = kwargs.pop("post_data", None)
        if post_data:
            method = "POST"
            kwargs["data"] = post_data

        # TODO: 호출하는 쪽에서 넣도록 변경
        if "javbus.com" in url:
            request_headers["referer"] = "https://www.javbus.com/"

        try:
            res = cls.session.request(method, url, headers=request_headers, proxies=proxies, **kwargs)
            return res

        except requests.exceptions.Timeout as e_timeout:
            # 에러 로그에 사용하려 했던 프록시 정보 (proxy_url_from_arg)를 명시
            logger.error(f"SiteUtil.get_response: Timeout for URL='{url}'. Attempted Proxy (from arg)='{cls.config['proxy_url']}'. Error: {e_timeout}")
            return None
        except requests.exceptions.ConnectionError as e_conn:
            logger.error(f"SiteUtil.get_response: ConnectionError for URL='{url}'. Attempted Proxy (from arg)='{cls.config['proxy_url']}'. Error: {e_conn}")
            return None
        except requests.exceptions.RequestException as e_req:
            logger.error(f"SiteUtil.get_response: RequestException (other) for URL='{url}'. Attempted Proxy (from arg)='{cls.config['proxy_url']}'. Error: {e_req}")
            logger.error(traceback.format_exc())
            return None
        except Exception as e_general:
            logger.error(f"SiteUtil.get_response: General Exception for URL='{url}'. Attempted Proxy (from arg)='{cls.config['proxy_url']}'. Error: {e_general}")
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
        # 정상적일때만.
        proxies = None
        if cls.config['use_proxy']:
            proxies = {"http": cls.config['proxy_url'], "https": cls.config['proxy_url']}
        with cls.session.get(url, proxies=proxies, headers=cls.default_headers) as res:
            if res.status_code != 200:
                return None
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

        proxies = None
        if cls.config and cls.config.get('use_proxy', False):
            proxies = {"http": cls.config['proxy_url'], "https": cls.config['proxy_url']}

        proxy_url = kwargs.pop("proxy_url", None)
        cookies = kwargs.pop("cookies", None)
        headers = kwargs.pop("headers", cls.default_headers)

        scraper = cls.get_cloudscraper_instance()
        if scraper is None:
            logger.error("SiteUtil.get_response_cs: Failed to get cloudscraper instance.")
            return None

        # logger.debug(f"SiteUtil.get_response_cs: Making {method} request to URL='{url}'")
        if headers: 
            scraper.headers.update(headers)

        try:
            if method == "POST":
                post_data = kwargs.pop("post_data", None)
                res = scraper.post(url, data=post_data, cookies=cookies, proxies=proxies, **kwargs)
            else: # GET
                res = scraper.get(url, cookies=cookies, proxies=proxies,**kwargs)

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
    def jav_image(cls, url, mode=None):
        if mode == None or mode.startswith("crop"):
            return cls.default_jav_image(url, mode)

    @classmethod
    def jav_video(cls, url):
        try:
            proxies = None
            if cls.config['use_proxy']:
                proxies = {"http": cls.config['proxy_url'], "https": cls.config['proxy_url']}
            req = cls.session.get(url, proxies=proxies, headers=cls.default_headers, stream=True)
            req.raise_for_status()
        except requests.exceptions.RequestException as e:
            return abort(500)

        def generate_content():
            for chunk in req.iter_content(chunk_size=8192):
                yield chunk

        response_headers = {
            'Content-Type': req.headers.get('Content-Type', 'video/mp4'),
            'Content-Length': req.headers.get('Content-Length'),
            'Accept-Ranges': 'bytes', # 시간 탐색을 위해 필요
        }
        return Response(generate_content(), headers=response_headers)


    @classmethod
    def set_config(cls, db):
        """
        사이트별 설정을 적용하는 메소드
        :param config: 사이트 설정 딕셔너리
        """
        if cls.session == None:
            cls.session = cls.get_session()
        else:
            # 설정을 변경하면 그냥 새로 생성.
            cls.session.close()
            cls.session = cls.get_session()
        cls.MetadataSetting = db
        use_proxy = f"jav_censored_{cls.site_name}_use_proxy"
        if db.get(use_proxy) == None:
            use_proxy = f"jav_uncensored_{cls.site_name}_use_proxy"
        proxy_url = f"jav_censored_{cls.site_name}_proxy_url"
        if db.get(proxy_url) == None:
            proxy_url = f"jav_uncensored_{cls.site_name}_proxy_url"
        cls.config = {
            #공통
            "image_mode": db.get('jav_censored_image_mode'), # 사용하지 않음
            "trans_option": db.get('jav_censored_trans_option'),
            "use_extras": db.get_bool('jav_censored_use_extras'),
            "max_arts": db.get_int('jav_censored_art_count'),

            # 사이트별
            "use_proxy": db.get_bool(use_proxy),
            "proxy_url": db.get(proxy_url),
        }


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
    def pil_to_response(cls, pil, format="JPEG", mimetype='image/jpeg'):
        with BytesIO() as buf:
            pil.save(buf, format=format, quality=95)
            return Response(buf.getvalue(), mimetype=mimetype)


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

        if image_mode == 'ff_proxy':
            # proxy를 사용하거나 mode값이 있다면. 조작을 해야하니 ff로
            if cls.config['use_proxy'] or image_sources['poster_mode']:
                param = {
                    'site': cls.site_name,
                    'url': unquote_plus(image_sources['poster_source']), 
                    'mode': image_sources.get('poster_mode', '')
                }
                if param['mode'] == None:
                    del param['mode']  # mode가 None이면 제거
                param = urlencode(param)
                if cls.module_char == 'C':
                    url = f"{F.SystemModelSetting.get('ddns')}/metadata/normal/jav_image?{param}"
                else:
                    url = f"{F.SystemModelSetting.get('ddns')}/metadata/normal/jav_image_un?{param}"
            else:
                url = image_sources['poster_source']
            entity.thumb.append(EntityThumb(aspect="poster", value=url))

            if cls.config['use_proxy']:
                param = urlencode({
                    'site': cls.site_name,
                    'url': unquote_plus(image_sources['landscape_source']),
                })
                if cls.module_char == 'C':
                    url = f"{F.SystemModelSetting.get('ddns')}/metadata/normal/jav_image?{param}"
                else:
                    url = f"{F.SystemModelSetting.get('ddns')}/metadata/normal/jav_image_un?{param}"
            else:
                url = image_sources['landscape_source']
            entity.thumb.append(EntityThumb(aspect="landscape", value=url))
        
            for art_url in image_sources['arts']:
                if cls.config['use_proxy']:
                    param = urlencode({
                        'site': cls.site_name,
                        'url': unquote_plus(art_url)
                    })
                    if cls.module_char == 'C':
                        url = f"{F.SystemModelSetting.get('ddns')}/metadata/normal/jav_image?{param}"
                    else:
                        url = f"{F.SystemModelSetting.get('ddns')}/metadata/normal/jav_image_un?{param}"
                else:
                    url = art_url
                entity.fanart.append(url)
        elif image_mode == 'discord_proxy':
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
                    url = f"{server_url}/{target_folder.replace(local_path, '').strip('/')}/{filename}"
                    if idx == 0 and os.path.exists(filepath):
                        entity.thumb.append(EntityThumb(aspect=aspect, value=url))
                        save = False
                        break
                    elif idx == 1 and os.path.exists(filepath):
                        if rewrite:
                            os.remove(filepath)
                        else:
                            entity.thumb.append(EntityThumb(aspect=aspect, value=url))
                            save = False
                if save:
                    os.makedirs(os.path.dirname(filepath), exist_ok=True)
                    if aspect == "poster":
                        response = cls.jav_image(image_sources['poster_source'], mode=image_sources.get('poster_mode', ''))
                    else:
                        response = cls.jav_image(image_sources['landscape_source'])
                    response_bytes = BytesIO(response.data)
                    response_bytes.seek(0)
                    with open(filepath, 'wb') as f:
                        f.write(response_bytes.read())
                    entity.thumb.append(EntityThumb(aspect=aspect, value=url))

            # arts
            for idx, art_url in enumerate(image_sources['arts']):
                filename = f"{code}_art_{idx+1}.jpg"
                filepath = os.path.join(target_folder, filename)
                url = f"{server_url}/{target_folder.replace(local_path, '').strip('/')}/{filename}"
                if os.path.exists(filepath):
                    if rewrite:
                        os.remove(filepath)
                    else:
                        entity.fanart.append(url)
                        continue
                os.makedirs(os.path.dirname(filepath), exist_ok=True)
                response = cls.jav_image(art_url)
                response_bytes = BytesIO(response.data)
                response_bytes.seek(0)
                with open(filepath, 'wb') as f:
                    f.write(response_bytes.read())
                entity.fanart.append(url)

        logger.info(f"[ImageUtil] 이미지 최종 처리 완료. Thumbs: {len(entity.thumb)}, Fanarts: {len(entity.fanart)}")

    # endregion 이미지 처리 관련
    ################################################


    ################################################
    # region SiteUtilAV 이미지 처리 관련
    @classmethod
    def is_portrait_high_quality_image(cls, image_url, min_height=600, aspect_ratio_threshold=1.2):
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
            img_pil_object = cls.imopen(image_url) 

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
    def is_hq_poster(cls, im_sm_source, im_lg_source, sm_source_info=None, lg_source_info=None):
        logger.debug(f"--- is_hq_poster called ---")
        log_sm_info = sm_source_info or (f"URL: {im_sm_source}" if isinstance(im_sm_source, str) else f"Type: {type(im_sm_source)}")
        log_lg_info = lg_source_info or (f"URL: {im_lg_source}" if isinstance(im_lg_source, str) else f"Type: {type(im_lg_source)}")
        
        logger.debug(f"  Small Image Source: {log_sm_info}")
        logger.debug(f"  Large Image Source: {log_lg_info}")

        try:
            if im_sm_source is None or im_lg_source is None:
                logger.debug("  Result: False (Source is None)")
                return False

            im_sm_obj = cls.imopen(im_sm_source)
            im_lg_obj = cls.imopen(im_lg_source)

            if im_sm_obj is None or im_lg_obj is None:
                logger.debug("  Result: False (Failed to open one or both images from source)")
                return False
            # logger.debug("  Images acquired/opened successfully.")

            try:

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
    def has_hq_poster(cls, im_sm_url, im_lg_url):
        try:
            if not im_sm_url or not isinstance(im_sm_url, str) or \
               not im_lg_url or not isinstance(im_lg_url, str):
                logger.debug("has_hq_poster: Invalid or empty URL(s) provided.")
                return None

            im_sm_obj = cls.imopen(im_sm_url)
            im_lg_obj_original = cls.imopen(im_lg_url)

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
