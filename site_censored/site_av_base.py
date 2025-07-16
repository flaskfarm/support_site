# python 기본
import os
import time
import traceback
from datetime import timedelta
from urllib.parse import urlencode, unquote_plus
import random
# python 확장
import requests
from lxml import html
from flask import Response, abort, send_file
from io import BytesIO
from PIL import Image, UnidentifiedImageError
# FF
from support import SupportDiscord
from ..setup import P, F, logger, path_data
from tool import ToolUtil
from ..site_util_av import SiteUtilAv
from ..entity_base import EntityThumb
from ..trans_util import TransUtil

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

        url = f"{F.SystemModelSetting.get('ddns')}/metadata/normal/jav_image?{urlencode(param)}"
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
        return f"{F.SystemModelSetting.get('ddns')}/metadata/normal/jav_video?{urlencode(param)}"
    
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
        cls.config = {
            #공통
            "image_mode": db.get('jav_censored_image_mode'), # 사용하지 않음
            "trans_option": db.get('jav_censored_trans_option'),
            "use_extras": db.get_bool('jav_censored_use_extras'),
            "max_arts": db.get_int('jav_censored_art_count'),

            # 사이트별
            "use_proxy": db.get_bool(f"jav_censored_{cls.site_name}_use_proxy"),
            "proxy_url": db.get(f"jav_censored_{cls.site_name}_proxy_url"),

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
            logger.exception(f"MGS Special Local: Error in get_mgs_half_pl_poster_info_local: {e}")


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
        
        image_mode = cls.MetadataSetting.get('jav_censored_image_mode')

        if image_mode == 'ff_proxy':
            # proxy를 사용하거나 mode값이 있다면. 조작을 해야하니 ff로
            if cls.config['use_proxy'] or image_sources['poster_mode']:
                param = urlencode({
                    'site': cls.site_name,
                    'url': unquote_plus(image_sources['poster_source']), 
                    'mode': image_sources.get('poster_mode', '')
                })
                url = f"{F.SystemModelSetting.get('ddns')}/metadata/normal/jav_image?{param}"
            else:
                url = image_sources['poster_source']
            entity.thumb.append(EntityThumb(aspect="poster", value=url))

            if cls.config['use_proxy']:
                param = urlencode({
                    'site': cls.site_name,
                    'url': unquote_plus(image_sources['landscape_source']),
                })
                url = f"{F.SystemModelSetting.get('ddns')}/metadata/normal/jav_image?{param}"
            else:
                url = image_sources['landscape_source']
            entity.thumb.append(EntityThumb(aspect="landscape", value=url))
        
            for art_url in image_sources['arts']:
                if cls.config['use_proxy']:
                    param = urlencode({
                        'site': cls.site_name,
                        'url': unquote_plus(art_url)
                    })
                    url = f"{F.SystemModelSetting.get('ddns')}/metadata/normal/jav_image?{param}"
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
                for filename in filenames:
                    filepath = os.path.join(target_folder, filename)
                    url = f"{server_url}/{target_folder.replace(local_path, '').strip('/')}/{filename}"
                    if os.path.exists(filepath):
                        entity.thumb.append(EntityThumb(aspect=aspect, value=url))
                        break
                else:
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


