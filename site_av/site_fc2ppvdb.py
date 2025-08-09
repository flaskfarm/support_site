import re
import os
import traceback
import time
from datetime import datetime, timedelta
from lxml import html

from ..entity_av import EntityAVSearch
from ..entity_base import (EntityActor, EntityExtra, EntityMovie, EntityThumb)
from ..setup import P, logger
from .site_av_base import SiteAvBase

SITE_BASE_URL = 'https://fc2ppvdb.com'

class SiteFc2ppvdb(SiteAvBase):
    site_name = 'fc2'
    site_char = 'P'
    module_char = 'E'
    default_headers = SiteAvBase.base_default_headers.copy()
    default_headers['Referer'] = SITE_BASE_URL + "/"

    _info_cache = {}
    ppvdb_default_cookies = {}
    _block_release_time_fc2ppvdb = 0 # 차단 해제 시간 저장 (타임스탬프)
    _last_retry_after_value = 0 # 마지막으로 받은 Retry-After 값 (로그용)

    @classmethod
    def search(cls, keyword, manual=False):
        try:
            ret = {}
            match = re.search(r'(\d{6,7})', keyword)
            if not match:
                return {'ret': 'success', 'data': []}

            code = match.group(1)

            if cls._is_blocked():
                logger.warning(f"[{cls.site_name} Search] Aborted due to rate-limiting.")
                return {'ret': 'success', 'data': []}

            search_url = f'{SITE_BASE_URL}/articles/{code}/'
            tree, response_html_text = cls._get_fc2ppvdb_page_content(search_url, use_cloudscraper=True)

            if tree is None:
                return {'ret': 'success', 'data': []}

            if response_html_text:
                cls._info_cache[code] = response_html_text

            not_found_elements = tree.xpath('/html/head/title[contains(text(), "お探しの商品が見つかりません")] | //h1[contains(text(), "404 Not Found")] | //h1[contains(text(), "このページは削除されました")]')
            if not_found_elements:
                logger.debug(f"[{cls.site_name} Search] Page not found or deleted for code: {code}")
                return {'ret': 'success', 'data': []}

            item = EntityAVSearch(cls.site_name)
            item.code = cls.module_char + cls.site_char + code
            item.ui_code = f'FC2-{code}'
            item.score = 100

            info_block_xpath_base = '/html/body/div[1]/div/div/main/div/section/div[1]/div[1]'
            title_elements = tree.xpath(f'{info_block_xpath_base}/div[2]/h2/a/text()')
            item.title = title_elements[0].strip() if title_elements else item.ui_code

            if manual:
                item.title_ko = "(현재 인터페이스에서는 번역을 제공하지 않습니다) " + item.title
            else:
                item.title_ko = item.title

            year_text_elements = tree.xpath(f"{info_block_xpath_base}/div[2]/div[starts-with(normalize-space(.), '販売日：')]/span/text()")
            if year_text_elements:
                date_str = year_text_elements[0].strip()
                if re.match(r'\d{4}-\d{2}-\d{2}', date_str):
                    try: item.year = int(date_str.split('-')[0])
                    except (ValueError, IndexError): pass

            img_elements = tree.xpath(f'{info_block_xpath_base}/div[1]/a/img/@src')
            if img_elements:
                item.image_url = f"{SITE_BASE_URL}{img_elements[0]}" if img_elements[0].startswith('/') else img_elements[0]
            else:
                item.image_url = ""

            if manual:
                if cls.config.get('use_proxy'):
                    item.image_url = cls.make_image_url(item.image_url)

            ret['data'] = [item.as_dict()]
            ret['ret'] = 'success'

        except Exception as exception: 
            logger.error(f'[{cls.site_name} Search] Exception for keyword {keyword}: {exception}')
            logger.error(traceback.format_exc())
            ret['ret'] = 'exception'
            ret['data'] = str(exception)
        return ret


    @classmethod
    def info(cls, code):
        try:
            ret = {}
            entity = cls.__info(code)
            if entity:
                ret['ret'] = 'success'
                ret['data'] = entity.as_dict()
            else:
                ret['ret'] = 'error'
        except Exception as exception: 
            logger.error(f'[{cls.site_name} Info] Exception for code {code}: {exception}')
            logger.error(traceback.format_exc())
            ret['ret'] = 'exception'
            ret['data'] = str(exception)
        return ret


    @classmethod
    def __info(cls, code):
        if cls._is_blocked():
            logger.warning(f"[{cls.site_name} Info] Aborted due to rate-limiting.")
            return None

        code_part = code[len(cls.module_char) + len(cls.site_char):]
        tree = None

        if code_part in cls._info_cache:
            logger.debug(f"Using cached HTML data for FC2 code: {code_part}")
            html_text = cls._info_cache[code_part]
            tree = html.fromstring(html_text)
            del cls._info_cache[code_part]

        if tree is None:
            logger.debug(f"Cache miss for FC2 code: {code_part}. Calling site.")
            info_url = f'{SITE_BASE_URL}/articles/{code_part}/'
            tree, _ = cls._get_fc2ppvdb_page_content(info_url, use_cloudscraper=True)

        if tree is None:
            return None

        entity = EntityMovie(cls.site_name, code)
        entity.country = ['일본']; entity.mpaa = '청소년 관람불가'
        entity.thumb = []; entity.fanart = []; entity.extras = []; entity.ratings = []
        entity.tag = []; entity.genre = []; entity.actor = []

        entity.ui_code = f'FC2-{code_part}'
        entity.title = entity.originaltitle = entity.sorttitle = entity.ui_code

        info_base_xpath = '/html/body/div[1]/div/div/main/div/section/div[1]/div[1]/div[2]'
        info_element = tree.xpath(info_base_xpath)
        if not info_element: 
            logger.warning(f"FC2 Info: Main info block not found for {code}")
            return None
        info_element = info_element[0]

        title_elements = info_element.xpath('./h2/a/text()')
        if title_elements:
            entity.tagline = cls.trans(title_elements[0].strip())
        entity.plot = entity.tagline

        date_elements = info_element.xpath("./div[starts-with(normalize-space(.), '販売日：')]/span/text()")
        if date_elements:
            date_str = date_elements[0].strip()
            if re.match(r'\d{4}-\d{2}-\d{2}', date_str):
                entity.premiered = date_str
                try: entity.year = int(date_str.split('-')[0])
                except (ValueError, IndexError): pass

        seller_elements = info_element.xpath("./div[starts-with(normalize-space(.), '販売者：')]/span/a/text()")
        if seller_elements:
            entity.director = entity.studio = seller_elements[0].strip()

        actor_elements = info_element.xpath("./div[starts-with(normalize-space(.), '女優：')]/span//a/text()")
        for actor_name in actor_elements:
            actor_obj = EntityActor(cls.trans(actor_name.strip()))
            actor_obj.originalname = actor_name.strip()
            entity.actor.append(actor_obj)

        entity.tag.append('FC2')
        genre_elements = info_element.xpath("./div[starts-with(normalize-space(.), 'タグ：')]/span//a/text()")
        for item_genre in genre_elements:
            entity.genre.append(cls.trans(item_genre.strip()))

        image_mode = cls.MetadataSetting.get('jav_censored_image_mode')
        if image_mode == 'image_server':
            module_type = 'jav_uncensored'
            local_path = cls.MetadataSetting.get('jav_censored_image_server_local_path')
            server_url = cls.MetadataSetting.get('jav_censored_image_server_url')
            base_save_format = cls.MetadataSetting.get(f'{module_type}_image_server_save_format')

            label = "FC2"
            # 1. code_part (순수 숫자 품번)를 7자리로 패딩
            padded_code = code_part.zfill(7)
            # 2. 패딩된 코드의 '앞 3자리'를 하위 폴더 이름으로 사용
            code_prefix_part = padded_code[:3]

            base_path_part = base_save_format.format(label=label)
            final_relative_folder_path = os.path.join(base_path_part.strip('/\\'), code_prefix_part)

            entity.image_server_target_folder = os.path.join(local_path, final_relative_folder_path)
            entity.image_server_url_prefix = f"{server_url.rstrip('/')}/{final_relative_folder_path.replace(os.path.sep, '/')}"

        poster_url = ""
        poster_elements = tree.xpath('/html/body/div[1]/div/div/main/div/section/div[1]/div[1]/div[1]/a/img/@src')
        if poster_elements:
            poster_url = f"{SITE_BASE_URL}{poster_elements[0]}" if poster_elements[0].startswith('/') else poster_elements[0]

        final_image_sources = {
            'poster_source': poster_url,
            'poster_mode': None,
            'landscape_source': None,
            'arts': [],
        }
        cls.finalize_images_for_entity(entity, final_image_sources)

        return entity


    ################################################
    # region 전용 UTIL

    @classmethod
    def _get_fc2ppvdb_page_content(cls, url, use_cloudscraper=True):
        if cls._is_blocked():
            return None, "Site is rate-limited"

        res = None
        page_text_for_rate_limit_check = "" # Rate limit HTML 내용 검사용

        if use_cloudscraper:
            res_cs = cls.get_response_cs(url, cookies=cls.ppvdb_default_cookies, timeout=20)
            if res_cs is not None: # Cloudscraper가 응답 객체를 반환했다면
                res = res_cs # 일단 res에 할당
                if hasattr(res_cs, 'text'):
                    page_text_for_rate_limit_check = res_cs.text

                # Cloudscraper 응답에서 바로 Rate Limit 조건 확인
                is_rate_limited_by_content_cs = False
                if "<title>Too Many Requests</title>" in page_text_for_rate_limit_check:
                    is_rate_limited_by_content_cs = True

                if res.status_code == 429 or 'Retry-After' in res.headers or is_rate_limited_by_content_cs:
                    logger.warning(f"[{cls.site_name}] Rate limit detected by Cloudscraper. Status: {res.status_code}, Headers: {res.headers.get('Retry-After')}, HTML Title: {is_rate_limited_by_content_cs}")
                    if cls._handle_rate_limit(res.headers): # Retry-After 헤더가 있으면 그것을 우선 사용
                        return None, f"Rate limit hit (Cloudscraper with Header). Retry-After: {res.headers.get('Retry-After', 'N/A')}"
                    elif is_rate_limited_by_content_cs: # HTML 내용으로만 감지
                        logger.warning(f"[{cls.site_name}] Rate limit by HTML (Cloudscraper), no Retry-After. Default block.")
                        cls._block_release_time_fc2ppvdb = time.time() + 300 # 예: 5분 기본 차단
                        cls._last_retry_after_value = 300 
                        return None, "Rate limit detected by HTML content (Cloudscraper - default block applied)"
                    # else: Retry-After 헤더 없고, HTML 내용으로도 특정 못하면 그냥 일반 실패로 간주 (아래 로직 따름)

            if res is None and use_cloudscraper: # Cloudscraper가 None을 반환했거나, 위 Rate Limit 조건에 안 걸렸지만 실패한 경우
                logger.warning(f"[{cls.site_name}] Cloudscraper returned None or non-rate-limit error for {url}. Falling back to standard requests.")
                # res는 여전히 None인 상태로 아래 fallback 로직으로 넘어감

        # Cloudscraper를 사용하지 않았거나, Cloudscraper가 None을 반환했거나,
        # Cloudscraper가 응답했지만 Rate Limit이 아닌 다른 이유로 실패했을 경우 fallback
        if res is None:
            logger.debug(f"[{cls.site_name}] Attempting with standard requests for {url}...")
            res_std = cls.get_response(url, cookies=cls.ppvdb_default_cookies, timeout=20)
            if res_std is not None:
                res = res_std # res에 할당
                if hasattr(res_std, 'text'):
                    page_text_for_rate_limit_check = res_std.text
            # else: res는 여전히 None

        # 최종 res 객체로 나머지 처리
        if res:
            page_text = res.text if hasattr(res, 'text') else ""

            # 표준 requests 응답에서도 Rate Limit 조건 한 번 더 확인 (Cloudscraper가 실패하고 fallback했을 경우 대비)
            is_rate_limited_by_content_std = False
            if "<title>Too Many Requests</title>" in page_text: # status code 조건은 위에서 res_cs에 대해 이미 했을 수 있으므로 여기선 생략 가능
                is_rate_limited_by_content_std = True

            if res.status_code == 429 or 'Retry-After' in res.headers or is_rate_limited_by_content_std:
                logger.warning(f"[{cls.site_name}] Rate limit detected by standard requests (or fallback). Status: {res.status_code}, Headers: {res.headers.get('Retry-After')}, HTML Title: {is_rate_limited_by_content_std}")
                if cls._handle_rate_limit(res.headers):
                    return None, f"Rate limit hit (Standard Requests with Header). Retry-After: {res.headers.get('Retry-After', 'N/A')}"
                elif is_rate_limited_by_content_std:
                    logger.warning(f"[{cls.site_name}] Rate limit by HTML (Standard Requests), no Retry-After. Default block.")
                    cls._block_release_time_fc2ppvdb = time.time() + 300 # 예: 5분 기본 차단
                    cls._last_retry_after_value = 300
                    return None, "Rate limit detected by HTML content (Standard Requests - default block applied)"

            if res.status_code == 200:
                # 로그인 페이지 또는 "페이지 없음" 감지는 그대로 유지
                if "fc2.com" in res.url and "login.php" in res.url:
                    logger.warning(f"[{cls.site_name}] Detected redirection to FC2 main login page...")
                    return None, page_text
                if "お探しのページは見つかりません。" in page_text:
                    logger.info(f"[{cls.site_name}] Page explicitly states 'not found'...")
                    return None, page_text

                try:
                    return html.fromstring(page_text), page_text
                except Exception as e_parse:
                    logger.error(f"[{cls.site_name}] Failed to parse HTML: {e_parse}. URL: {url}")
                    return None, page_text
            else: # 200도 아니고 Rate Limit 조건에도 해당 안되는 다른 에러
                logger.warning(f"[{cls.site_name}] Failed to get page. Status: {res.status_code}. URL: {url}")
                return None, page_text
        else: # 최종적으로 res가 None인 경우 (모든 시도 실패)
            logger.warning(f"[{cls.site_name}] Failed to get page (all attempts failed - response is None). URL: {url}")
            return None, "Network error or no response from all attempts"


    @classmethod
    def _is_blocked(cls):
        """현재 사이트가 차단 상태인지 확인하고, 남은 차단 시간을 로깅합니다."""
        if cls._block_release_time_fc2ppvdb == 0:
            return False # 차단된 적 없거나 해제됨

        now_timestamp = time.time()
        if now_timestamp < cls._block_release_time_fc2ppvdb:
            remaining_seconds = int(cls._block_release_time_fc2ppvdb - now_timestamp)
            remaining_time_str = str(timedelta(seconds=remaining_seconds)) # HH:MM:SS 형식
            logger.warning(f"[{cls.site_name}] Site is currently rate-limited. Retrying after {remaining_time_str} (Retry-After was {cls._last_retry_after_value}s).")
            return True
        else: # 차단 시간 지남
            logger.info(f"[{cls.site_name}] Rate-limit period has passed. Resetting block time.")
            cls._block_release_time_fc2ppvdb = 0 # 차단 해제, 변수 초기화
            cls._last_retry_after_value = 0
            return False


    @classmethod
    def _handle_rate_limit(cls, response_headers):
        """Retry-After 헤더를 확인하고 차단 시간을 설정합니다."""
        retry_after_str = response_headers.get('Retry-After')
        if retry_after_str and retry_after_str.isdigit():
            retry_after_seconds = int(retry_after_str)
            cls._last_retry_after_value = retry_after_seconds # 로그용으로 저장
            # 현재 시간에 Retry-After 초를 더해 차단 해제 시간 계산
            # 너무 긴 시간(예: 하루 이상)이 설정되면 최대치를 두는 것도 고려
            # if retry_after_seconds > 86400: # 예: 하루 이상이면 최대 1시간으로 제한 (선택적)
            #    logger.warning(f"[{cls.site_name}] Received very long Retry-After: {retry_after_seconds}s. Limiting block to 1 hour.")
            #    retry_after_seconds = 3600

            cls._block_release_time_fc2ppvdb = time.time() + retry_after_seconds
            release_dt_str = datetime.fromtimestamp(cls._block_release_time_fc2ppvdb).strftime('%Y-%m-%d %H:%M:%S')
            logger.warning(f"[{cls.site_name}] Rate limit detected. Retry-After: {retry_after_seconds}s. Blocking requests until {release_dt_str}.")
            return True # 차단 설정됨
        return False # Retry-After 헤더 없거나 유효하지 않음

    # endregion UTIL
    ################################################