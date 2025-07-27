import json
import os
import re
import time
from datetime import timedelta
from io import BytesIO
from urllib.parse import urlparse, quote_plus
import traceback

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



    





















































