# -*- coding: utf-8 -*-
import json
import re
from urllib.parse import urljoin, quote, urlencode, urlparse
from lxml import html

from ..entity_av import EntityAVSearch
from ..entity_base import EntityActor, EntityExtra, EntityMovie, EntityRatings
from ..setup import P, logger
from .site_av_base import SiteAvBase
from ..constants import AV_STUDIO, AV_GENRE_IGNORE_JA, AV_GENRE, AV_GENRE_IGNORE_KO

# 상수값. 사용하지 값들 주석처리
SITE_BASE_URL = "https://www.dmm.co.jp"
FANZA_AV_URL = "https://video.dmm.co.jp/av/"
PTN_SEARCH_CID = re.compile(r"\/cid=(?P<code>.*?)\/")
CONTENT_TYPE_PRIORITY = ['videoa', 'vr', 'dvd', 'bluray', 'unknown']


class SiteDmm(SiteAvBase):
    site_name = "dmm"
    site_char = "D"
    module_char = "C"
    default_headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
        "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
        "Sec-Ch-Ua": '"Google Chrome";v="135", "Not-A.Brand";v="8", "Chromium";v="135"',
        "Sec-Ch-Ua-Mobile": "?0", "Sec-Ch-Ua-Platform": '"Windows"',
        "Sec-Fetch-Dest": "document", "Sec-Fetch-Mode": "navigate", "Sec-Fetch-Site": "same-origin",
        "Sec-Fetch-User": "?1", "Upgrade-Insecure-Requests": "1",
        "Referer": "https://www.dmm.co.jp" + "/", "DNT": "1", "Cache-Control": "max-age=0", "Connection": "keep-alive",
    }
    _ps_url_cache = {} # code: {'ps': ps_url, 'type': content_type}


    ################################################
    # region SEARCH
    
    @classmethod
    def search(cls, keyword, do_trans, manual):
        ret = {}
        try:
            data_list = cls.__search(keyword, do_trans=do_trans, manual=manual)
        except Exception as exception:
            logger.exception("SearchErr:")
            ret["ret"] = "exception"; ret["data"] = str(exception)
        else:
            ret["ret"] = "success" if data_list else "no_match"
            ret["data"] = data_list
        return ret
    

    @classmethod
    def __search(cls, keyword, do_trans, manual, is_retry: bool = False):
        # logger.debug(f"SITE_DMM: __search received dmm_parser_rules: {dmm_parser_rules}")
        if not cls._ensure_age_verified(): return []

        original_keyword = keyword

        # --- 1. 초기 정제 (입력된 keyword 기준) ---
        temp_keyword = original_keyword.strip().lower()
        temp_keyword = re.sub(r'[-_]?cd\d*$', '', temp_keyword, flags=re.I)
        temp_keyword = temp_keyword.strip('-_ ') # 예: "dsvr-039" 또는 "id-16045"

        # 점수 계산 시 사용하기 위해 keyword_processed_parts를 여기서 생성
        keyword_processed_parts_for_score = temp_keyword.replace("-", " ").replace("_"," ").strip().split(" ")
        keyword_processed_parts_for_score = [part for part in keyword_processed_parts_for_score if part]

        # `__get_keyword_for_url`로부터 keyword와 재시도용 파트를 모두 받음
        keyword_for_url, label_part_for_retry, num_part_for_retry = cls.__get_keyword_for_url(temp_keyword, is_retry)

        if is_retry:
            logger.debug(f"DMM Search [RETRY]: original_keyword='{original_keyword}', keyword_for_url='{keyword_for_url}'")
        else:
            logger.debug(f"DMM Search: original_keyword='{original_keyword}', keyword_for_url='{keyword_for_url}'")


        # --- 검색 URL 생성 ---
        search_params = { 'redirect': '1', 'enc': 'UTF-8', 'category': '', 'searchstr': keyword_for_url }
        search_url = f"{SITE_BASE_URL}/search/?{urlencode(search_params)}"
        logger.debug(f"DMM Search URL: {search_url}")

        search_headers = cls.get_request_headers(referer=FANZA_AV_URL)
        tree = None
        try:
            tree = cls.get_tree(search_url, headers=search_headers, allow_redirects=True)
            if tree is None: 
                logger.warning(f"DMM Search: Search tree is None for '{original_keyword}'. URL: {search_url}")
                return []
            title_tags_check = tree.xpath('//title/text()')
            if title_tags_check and "年齢認証 - FANZA" in title_tags_check[0]: 
                logger.error(f"DMM Search: Age page received for '{original_keyword}'.")
                return []
        except Exception as e: 
            logger.exception(f"DMM Search: Failed to get tree for '{original_keyword}': {e}")
            return []

        # --- 검색 결과 목록 추출 XPath ---
        list_xpath_options = [
            '//div[contains(@class, "border-r") and contains(@class, "border-b") and contains(@class, "border-gray-300")]',
            '//div[contains(@class, "grid-cols-4")]//div[contains(@class, "border-r") and contains(@class, "border-b")]', # (Fallback)
        ]

        lists = []
        from lxml import html
        with open("output.html", "wb") as f:
            f.write(html.tostring(tree, pretty_print=True, encoding='utf-8'))
        for xpath_expr in list_xpath_options:
            try:
                lists = tree.xpath(xpath_expr)
                if lists:
                    #logger.debug(f"DMM Search: Found {len(lists)} item blocks using XPath: {xpath_expr}")
                    break
            except Exception as e_xpath: 
                logger.warning(f"DMM Search: XPath error with '{xpath_expr}' for '{original_keyword}': {e_xpath}")

        if not lists: 
            logger.debug(f"DMM Search: No item blocks found using any XPath for '{original_keyword}'.")

        ret_temp_before_filtering = []
        score = 60

        for node in lists[:10]:
            try:
                item = EntityAVSearch(cls.site_name)
                href = None; original_ps_url = None; content_type = "unknown" 

                # 1. 기본적인 정보 파싱
                title_link_tags_in_node = node.xpath('.//a[.//p[contains(@class, "text-link")]]') 
                img_link_tags_in_node = node.xpath('.//a[./img[@alt="Product"]]')

                primary_href_candidate = None
                if title_link_tags_in_node and title_link_tags_in_node[0].attrib.get("href", "").lower().count('/cid=') > 0 :
                    primary_href_candidate = title_link_tags_in_node[0].attrib.get("href", "").lower()
                elif img_link_tags_in_node and img_link_tags_in_node[0].attrib.get("href", "").lower().count('/cid=') > 0 :
                    primary_href_candidate = img_link_tags_in_node[0].attrib.get("href", "").lower()

                if not primary_href_candidate:
                    logger.debug("DMM Search Item: No primary link with cid found. Skipping.")
                    continue

                href = primary_href_candidate
                #logger.debug(f"DMM Search Item: Determined href for path check: '{href}'")

                # 경로 필터링 (href 사용)
                try:
                    parsed_url = urlparse(href)
                    path_from_url = parsed_url.path
                except Exception as e_url_parse_item_loop:
                    logger.error(f"DMM Search Item: Failed to parse href '{href}': {e_url_parse_item_loop}")
                    continue

                is_videoa_path = "digital/videoa/" in path_from_url
                is_dvd_path = "mono/dvd/" in path_from_url
                if not (is_videoa_path or is_dvd_path):
                    #logger.debug(f"DMM Search Item: Path ('{path_from_url}' from href '{href}') filtered. Skipping.")
                    continue

                # 작은 포스터(PS) URL 추출 (node 기준 상대 경로)
                ps_img_src_list = node.xpath('.//img[@alt="Product"]/@src')
                if ps_img_src_list:
                    original_ps_url = ps_img_src_list[0]
                    if original_ps_url.startswith("//"): original_ps_url = "https:" + original_ps_url

                if not original_ps_url: # PS 이미지가 없으면 아이템 처리 불가
                    logger.debug("DMM Search Item: No PS image found. Skipping.")
                    continue
                item.image_url = original_ps_url

                # content_type 결정
                is_bluray = False
                bluray_span = node.xpath('.//span[contains(@class, "text-blue-600") and contains(text(), "Blu-ray")]') # node 기준
                if bluray_span: is_bluray = True

                if is_bluray: content_type = 'bluray'
                elif is_videoa_path: content_type = "videoa"
                elif is_dvd_path: content_type = "dvd"
                item.content_type = content_type

                # 제목 추출 (node 기준 상대 경로)
                title_p_tags = node.xpath('.//p[contains(@class, "text-link") and contains(@class, "line-clamp-2")]')
                raw_title = title_p_tags[0].text_content().strip() if title_p_tags else ""
                item.title = raw_title

                # 코드 추출 (href 사용)
                match_cid_s = PTN_SEARCH_CID.search(href) 
                if not match_cid_s: 
                    logger.warning(f"DMM Search Item: Could not extract CID from href '{href}'. Skipping.")
                    continue
                item.code = cls.module_char + cls.site_char + match_cid_s.group("code")

                # 중복 코드 체크
                if any(i_s.get("code") == item.code and i_s.get("content_type") == item.content_type for i_s in ret_temp_before_filtering):
                    logger.debug(f"DMM Search Item: Duplicate code and type, skipping: {item.code} ({item.content_type})")
                    continue

                # 2. item.ui_code 파싱 및 설정
                cid_part_for_parse = item.code[len(cls.module_char)+len(cls.site_char):]
                parsed_ui_code, label_for_score_item, num_raw_for_score_item = cls._parse_ui_code_from_cid(cid_part_for_parse, item.content_type)
                item.ui_code = parsed_ui_code.upper()

                # 제목 접두사 추가
                type_prefix = ""
                if content_type == 'dvd': type_prefix = "[DVD] "
                elif content_type == 'videoa': type_prefix = "[Digital] "
                elif content_type == 'bluray': type_prefix = "[Blu-ray] "

                # 3. item.title 설정
                title_p_tags_node = node.xpath('.//p[contains(@class, "text-link") and contains(@class, "line-clamp-2")]')
                raw_title_node = title_p_tags_node[0].text_content().strip() if title_p_tags_node else ""
                item.title = raw_title_node if raw_title_node and raw_title_node != "Not Found" else item.ui_code

                # 4. item.score 계산
                item_code_for_strict_compare = "" # 아이템의 "레이블+5자리숫자" (DMM 검색형식과 유사)
                item_ui_code_base_for_score = ""  # 아이템의 "레이블+원본숫자" (패딩X)

                if label_for_score_item and num_raw_for_score_item:
                    item_code_for_strict_compare = label_for_score_item + num_raw_for_score_item.zfill(5)
                    item_ui_code_base_for_score = label_for_score_item + num_raw_for_score_item
                elif item.ui_code: # _parse_ui_code_from_cid가 결과를 못냈을 경우의 폴백
                    cleaned_ui_code_for_score = item.ui_code.replace("-","").lower()
                    # cleaned_ui_code_for_score에서 레이블과 숫자 분리 시도 (간단화)
                    temp_match_score = re.match(r'([a-z]+)(\d+)', cleaned_ui_code_for_score)
                    if temp_match_score:
                        item_code_for_strict_compare = temp_match_score.group(1) + temp_match_score.group(2).zfill(5)
                        item_ui_code_base_for_score = temp_match_score.group(1) + temp_match_score.group(2)
                    else:
                        item_code_for_strict_compare = cleaned_ui_code_for_score
                        item_ui_code_base_for_score = cleaned_ui_code_for_score

                current_score_val = 0
                # --- 점수 계산 로직 ---
                # 1. DMM 검색용 키워드와 아이템의 "레이블+5자리숫자" 형태가 정확히 일치
                if keyword_for_url and item_code_for_strict_compare and keyword_for_url == item_code_for_strict_compare: 
                    current_score_val = 100
                # 2. 아이템의 "레이블+원본숫자"가 DMM 검색용 키워드와 일치 (패딩 차이 무시)
                elif item_ui_code_base_for_score == keyword_for_url: # keyword_for_url이 패딩된 형태일 수 있으므로, 이 조건은 위와 중복될 수 있음
                    current_score_val = 100 # 또는 98 (패딩만 다른 경우)
                # 3. 앞의 '0'을 제거한 숫자 부분 비교 (더 유연한 비교)
                elif item_ui_code_base_for_score.replace("0", "") == keyword_for_url.replace("0", ""): 
                    current_score_val = 80 
                # 4. DMM 검색용 키워드가 아이템의 "레이블+원본숫자"에 포함되는 경우
                elif keyword_for_url and item_ui_code_base_for_score and keyword_for_url in item_ui_code_base_for_score:
                    current_score_val = score # score 변수 (초기 60, 점차 감소)
                # 5. 초기 입력 키워드(temp_keyword)가 하이픈/공백으로 두 부분으로 나뉘고, 각 부분이 아이템 코드에 포함될 때 (이전 keyword_processed 사용 부분 대체)
                elif len(keyword_processed_parts_for_score) == 2 and \
                    keyword_processed_parts_for_score[0] in item.code.lower() and \
                    keyword_processed_parts_for_score[1] in item.code.lower():
                    current_score_val = score
                # 6. 초기 입력 키워드(temp_keyword)의 첫 번째 또는 두 번째 부분이 아이템 코드에 포함될 때
                elif len(keyword_processed_parts_for_score) > 0 and \
                    (keyword_processed_parts_for_score[0] in item.code.lower() or \
                    (len(keyword_processed_parts_for_score) > 1 and keyword_processed_parts_for_score[1] in item.code.lower())):
                    current_score_val = 60
                else: 
                    current_score_val = 20

                item.score = current_score_val
                if current_score_val < 100 and score > 20: score -= 5 # 다음 아이템의 기본 점수 감소

                # 5. manual 플래그에 따른 item.image_url 및 item.title_ko 최종 처리
                if manual:
                    try:
                        if cls.config['use_proxy']:
                            item.image_url = cls.make_image_url(item.image_url)
                    except Exception as e_img: 
                        logger.error(f"DMM Search: ImgProcErr (manual):{e_img}")
                    item.title_ko = "(현재 인터페이스에서는 번역을 제공하지 않습니다) " + type_prefix + item.title

                # 6. EntityAVSearch 객체를 dict로 변환
                item_dict = item.as_dict()

                # 7. 캐시 저장
                if item_dict.get('code') and original_ps_url and item_dict.get('content_type'):
                    code_key_cache = item_dict['code']
                    content_type_cache = item_dict['content_type']

                    if code_key_cache not in cls._ps_url_cache:
                        cls._ps_url_cache[code_key_cache] = {}

                    cls._ps_url_cache[code_key_cache][content_type_cache] = original_ps_url

                    current_main_type_cache = cls._ps_url_cache[code_key_cache].get('main_content_type')
                    should_update_main_cache = True
                    if current_main_type_cache:
                        try:
                            if CONTENT_TYPE_PRIORITY.index(content_type_cache) >= CONTENT_TYPE_PRIORITY.index(current_main_type_cache):
                                should_update_main_cache = False
                        except ValueError: pass 

                    if should_update_main_cache:
                        cls._ps_url_cache[code_key_cache]['main_content_type'] = content_type_cache
                    # logger.debug(f"DMM PS Cache: Updated for '{code_key_cache}', type '{content_type_cache}'. Main: '{cls._ps_url_cache[code_key_cache].get('main_content_type')}'")

                # 8. "지정 레이블 최우선" 플래그 설정
                item_dict['is_priority_label_site'] = False 
                item_dict['site_key'] = cls.site_name

                ui_code_for_label_check = item_dict.get('ui_code', "")
                if ui_code_for_label_check and cls.config['priority_labels']: # priority_label_setting_str은 함수 파라미터
                    label_to_check = cls.get_label_from_ui_code(ui_code_for_label_check)
                    if label_to_check:
                        if label_to_check in cls.config['priority_labels']:
                            item_dict['is_priority_label_site'] = True
                            # logger.debug(f"DMM Search: Item '{ui_code_for_label_check}' matched PrioLabel '{label_to_check}'. Flag set True.")

                ret_temp_before_filtering.append(item_dict) # 최종적으로 수정된 딕셔너리를 리스트에 추가
            except Exception as e_inner_loop_dmm:
                logger.exception(f"DMM Search: 아이템 처리 중 예외 (keyword: '{original_keyword}'): {e_inner_loop_dmm}")

        # --- 검색 결과가 없고, 아직 재시도 안했으며, 재시도용 정보가 있을 경우 ---
        if not ret_temp_before_filtering and not is_retry and label_part_for_retry and num_part_for_retry:
            logger.debug(f"DMM Search: No results for '{keyword_for_url}'. Retrying with 3-digit padding.")
            return cls.__search(
                keyword=original_keyword,
                do_trans=do_trans,                 
                manual=manual,
                is_retry=True # 재시도임을 명시
            )

        # --- 2단계: Blu-ray 필터링 ---
        # if not ret_temp_before_filtering: return []
        filtered_after_bluray = []
        dvd_ui_codes = {item_filter.get('ui_code') for item_filter in ret_temp_before_filtering if item_filter.get('content_type') == 'dvd' and item_filter.get('ui_code')}
        for item_to_check_bluray in ret_temp_before_filtering:
            item_content_type_filter = item_to_check_bluray.get('content_type')
            item_ui_code_filter = item_to_check_bluray.get('ui_code')
            # logger.debug(f"Processing item for filtering: Code={item_to_check_bluray.get('code')}, Type={item_content_type_filter}, UI Code={item_ui_code_filter}") # 로그 레벨 조정 또는 기존 유지
            is_bluray_to_filter = item_content_type_filter == 'bluray' and item_ui_code_filter is not None
            if is_bluray_to_filter:
                dvd_exists = item_ui_code_filter in dvd_ui_codes
                # logger.debug(f"  Item is Blu-ray. DVD exists for UI Code '{item_ui_code_filter}'? {dvd_exists}")
                if dvd_exists: logger.debug(f"Excluding Blu-ray item '{item_to_check_bluray.get('code')}' because DVD version exists.")
                else: filtered_after_bluray.append(item_to_check_bluray) 
            else: filtered_after_bluray.append(item_to_check_bluray)

        # --- 2.5단계: 접두사/접미사 변형판 필터링 (DOD 및 아울렛 포함) ---
        logger.debug(f"DMM Search: Starting Variant filtering (DOD, Outlet). Items before: {len(filtered_after_bluray)}")

        title_variants_map = {}
        other_content_types = [] # DVD/Blu-ray가 아닌 타입은 그대로 유지

        for item_to_filter in filtered_after_bluray:
            content_type = item_to_filter.get('content_type')
            original_title = item_to_filter.get('title', "")

            if content_type == 'dvd' or content_type == 'bluray':
                is_outlet = original_title.startswith('【アウトレット】')
                is_dod = original_title.endswith('（DOD）')

                base_title = original_title
                if is_outlet:
                    base_title = base_title.replace('【アウトレット】', '', 1).strip()
                if is_dod:
                    base_title = base_title.replace('（DOD）', '').strip()

                # 아이템 우선순위 값 (낮을수록 좋음)
                # 0: 일반판, 1: DOD만, 2: 아울렛만, 3: 아울렛+DOD
                priority_score = 0
                if is_outlet and is_dod:
                    priority_score = 3
                elif is_outlet:
                    priority_score = 2
                elif is_dod:
                    priority_score = 1

                item_to_filter['_variant_priority'] = priority_score # 임시 필드 추가

                if base_title not in title_variants_map:
                    title_variants_map[base_title] = item_to_filter
                else:
                    # 이미 해당 기본 제목의 아이템이 있다면, 우선순위 비교
                    existing_item = title_variants_map[base_title]
                    if priority_score < existing_item.get('_variant_priority', 99):
                        # 현재 아이템이 우선순위가 더 높으면 교체
                        logger.debug(f"DMM Variant Filter: Replacing item for base title '{base_title}'. Old: '{existing_item.get('title')}' (prio {existing_item.get('_variant_priority')}), New: '{original_title}' (prio {priority_score})")
                        title_variants_map[base_title] = item_to_filter
                    elif priority_score == existing_item.get('_variant_priority', 99):
                        # 우선순위가 같다면 (예: 일반판 vs 일반판 - 거의 발생 안 함, 또는 아울렛 vs 아울렛)
                        # 여기서는 추가적인 비교 없이 기존 것을 유지하거나, 다른 기준으로 선택 (예: 코드가 더 짧은 것 등)
                        # 일단은 기존 것 유지
                        logger.debug(f"DMM Variant Filter: Item for base title '{base_title}' with same priority {priority_score}. Keeping existing: '{existing_item.get('title')}' over '{original_title}'")
                        pass

            else: # DVD/Blu-ray가 아닌 타입은 그대로 리스트에 추가
                other_content_types.append(item_to_filter)

        # title_variants_map에서 최종 선택된 아이템들을 리스트로 변환
        final_filtered_list = list(title_variants_map.values())
        final_filtered_list.extend(other_content_types) # 다른 타입 아이템들 다시 합치기

        # 임시 필드 제거
        for item_final in final_filtered_list:
            item_final.pop('_variant_priority', None)

        logger.debug(f"DMM Search: Variant filtering complete. Items after: {len(final_filtered_list)}")

        # --- 3단계: 최종 결과 처리 ---
        logger.debug(f"DMM Search: Filtered result count: {len(final_filtered_list)} for '{original_keyword}'")
        
        # 재시도 판단 및 실행 로직 (기존 위치에서 여기로 이동)
        if not final_filtered_list and not is_retry and label_part_for_retry and num_part_for_retry:
            logger.debug(f"DMM Search: No results after filtering for '{keyword_for_url}'. Retrying with 3-digit padding.")
            return cls.__search(
                keyword=original_keyword,
                do_trans=do_trans, 
                manual=manual,
                is_retry=True # 재시도임을 명시
            )

        # 재시도하지 않는 경우, 최종 정렬하여 반환
        sorted_result = sorted(final_filtered_list, key=lambda k: k.get("score", 0), reverse=True)
        if sorted_result:
            log_count = min(len(sorted_result), 10)
            logger.debug(f"DMM Search: Top {log_count} results for '{original_keyword}':")
            for idx, item_log_final in enumerate(sorted_result[:log_count]):
                logger.debug(f"  {idx+1}. Score={item_log_final.get('score')}, Type={item_log_final.get('content_type')}, Code={item_log_final.get('code')}, UI Code={item_log_final.get('ui_code')}, Title='{item_log_final.get('title_ko')}'")

        return sorted_result

    # endregion SEARCH
    ################################################


    ################################################
    # region INFO

    @classmethod
    def info(cls, code):
        ret = {}
        entity_result_val_final = None
        try:
            entity_result_val_final = cls.__info(code).as_dict() # kwargs를 사용하지 않음
            if entity_result_val_final: 
                ret["ret"] = "success"; 
                ret["data"] = entity_result_val_final
            else: 
                ret["ret"] = "error"
                ret["data"] = f"Failed to get DMM info for {code}"
        except Exception as e_info_dmm_main_call_val_final: 
            ret["ret"] = "exception"
            ret["data"] = str(e_info_dmm_main_call_val_final)
            logger.exception(f"DMM info main call error: {e_info_dmm_main_call_val_final}")
        return ret


    @classmethod
    def __info(cls, code):

        cached_data = cls._ps_url_cache.get(code, {})
        ps_url_from_search_cache = None # kwargs.get('ps_url')
        if not ps_url_from_search_cache:
            content_type_from_cache = cached_data.get('main_content_type', 'unknown')
            if (content_type_from_cache == 'unknown' or not cached_data.get(content_type_from_cache)) and cached_data: 
                for prio_type in CONTENT_TYPE_PRIORITY:
                    if prio_type in cached_data and cached_data.get(prio_type): 
                        content_type_from_cache = prio_type
                        break
            ps_url_from_search_cache = cached_data.get(content_type_from_cache) if content_type_from_cache != 'unknown' else None
        else:
            content_type_from_cache = 'unknown' # ps_url이 직접 전달되면 타입을 알 수 없음

        current_content_type = content_type_from_cache
        if current_content_type == 'unknown':
            current_content_type = 'videoa'

        if not cls._ensure_age_verified():
            logger.error(f"DMM Info ({current_content_type}): Age verification failed for {code}.")
            return None

        cid_part = code[len(cls.module_char)+len(cls.site_char):]
        
        entity = EntityMovie(cls.site_name, code)
        entity.country = ["일본"]
        entity.mpaa = "청소년 관람불가"
        entity.thumb = []
        entity.fanart = []
        entity.extras = []
        entity.ratings = []
        entity.tag = []
        ui_code_for_image = ""
        entity.content_type = current_content_type
        
        tree = None
        detail_url = None
        api_data = None

        # === 1. 타입별 데이터 소스 분기 ===
        if entity.content_type == 'videoa' or entity.content_type == 'vr':
            # --- 새로운 방식: videoa/vr은 GraphQL API 호출 ---
            logger.debug(f"DMM Info (API): Getting info for {code} (type: {entity.content_type})")

            try:
                # --- 사전 작업: 브라우저의 API 호출 순서 모방 ---
                api_url = "https://api.video.dmm.co.jp/graphql"
                headers = {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36',
                    'Accept': 'application/graphql-response+json, application/graphql+json, application/json, text/event-stream, multipart/mixed',
                    'Content-Type': 'application/json',
                    'fanza-device': 'BROWSER',
                    'Origin': 'https://video.dmm.co.jp',
                    'Referer': f'https://video.dmm.co.jp/av/content/?id={cid_part}',
                    'Sec-Fetch-Dest': 'empty', 'Sec-Fetch-Mode': 'cors', 'Sec-Fetch-Site': 'same-site',
                }

                # 1. IP 정보 확인 API 호출
                payload_root = {"operationName":"Root","query":"query Root {\n  ipInfo {\n    countryCode\n    accessStatus\n    __typename\n  }\n}","variables":{}}
                cls.get_response(api_url, method='POST', headers=headers, json=payload_root)
                logger.debug("DMM Info (API): Step 1/3 'Root' API call completed.")

                # 2. 점검 상태 확인 API 호출
                payload_maintenance = {"operationName":"Maintenance","query":"query Maintenance {\n  maintenance(service: PPV) {\n    description\n    startAt\n    endAt\n    __typename\n  }\n}","variables":{}}
                cls.get_response(api_url, method='POST', headers=headers, json=payload_maintenance)
                logger.debug("DMM Info (API): Step 2/3 'Maintenance' API call completed.")

                # 3. 본편 데이터 요청 API 호출
                query_content = "query ContentPageData($id: ID!, $isLoggedIn: Boolean!, $isAmateur: Boolean!, $isAnime: Boolean!, $isAv: Boolean!, $isCinema: Boolean!, $isSP: Boolean!) {\n  ppvContent(id: $id) {\n    ...ContentData\n    __typename\n  }\n  reviewSummary(contentId: $id) {\n    ...ReviewSummary\n    __typename\n  }\n  ...basketCountFragment\n}\nfragment ContentData on PPVContent {\n  id\n  floor\n  title\n  isExclusiveDelivery\n  releaseStatus\n  description\n  notices\n  isNoIndex\n  isAllowForeign\n  announcements {\n    body\n    __typename\n  }\n  featureArticles {\n    link {\n      url\n      text\n      __typename\n    }\n    __typename\n  }\n  packageImage {\n    largeUrl\n    mediumUrl\n    __typename\n  }\n  sampleImages {\n    number\n    imageUrl\n    largeImageUrl\n    __typename\n  }\n  products {\n    ...ProductData\n    __typename\n  }\n  mostPopularContentImage {\n    ... on ContentSampleImage {\n      __typename\n      largeImageUrl\n      imageUrl\n    }\n    ... on PackageImage {\n      __typename\n      largeUrl\n      mediumUrl\n    }\n    __typename\n  }\n  priceSummary {\n    lowestSalePrice\n    lowestPrice\n    campaign {\n      title\n      id\n      endAt\n      __typename\n    }\n    __typename\n  }\n  weeklyRanking: ranking(term: Weekly)\n  monthlyRanking: ranking(term: Monthly)\n  wishlistCount\n  sample2DMovie {\n    fileID\n    __typename\n  }\n  sampleMovie {\n    has2d\n    hasVr\n    __typename\n  }\n  ...AmateurAdditionalContentData @include(if: $isAmateur)\n  ...AnimeAdditionalContentData @include(if: $isAnime)\n  ...AvAdditionalContentData @include(if: $isAv)\n  ...CinemaAdditionalContentData @include(if: $isCinema)\n  __typename\n}\nfragment ProductData on PPVProduct {\n  id\n  priority\n  deliveryUnit {\n    id\n    priority\n    streamMaxQualityGroup\n    downloadMaxQualityGroup\n    __typename\n  }\n  priceInclusiveTax\n  sale {\n    priceInclusiveTax\n    __typename\n  }\n  expireDays\n  utilization @include(if: $isLoggedIn) {\n    isTVODRentalPlayable\n    status\n    __typename\n  }\n  licenseType\n  shopName\n  availableCoupon {\n    name\n    expirationPolicy {\n      ... on ProductCouponExpirationAt {\n        expirationAt\n        __typename\n      }\n      ... on ProductCouponExpirationDay {\n        expirationDays\n        __typename\n      }\n      __typename\n    }\n    expirationAt\n    discountedPrice\n    minPayment\n    destinationUrl\n    __typename\n  }\n  __typename\n}\nfragment AmateurAdditionalContentData on PPVContent {\n  deliveryStartDate\n  duration\n  amateurActress {\n    id\n    name\n    imageUrl\n    age\n    waist\n    bust\n    bustCup\n    height\n    hip\n    relatedContents {\n      id\n      title\n      __typename\n    }\n    __typename\n  }\n  maker {\n    id\n    name\n    __typename\n  }\n  label {\n    id\n    name\n    __typename\n  }\n  genres {\n    id\n    name\n    __typename\n  }\n  makerContentId\n  playableInfo {\n    ...PlayableInfo\n    __typename\n  }\n  __typename\n}\nfragment PlayableInfo on PlayableInfo {\n  playableDevices {\n    deviceDeliveryUnits {\n      id\n      deviceDeliveryQualities {\n        isDownloadable\n        isStreamable\n        __typename\n      }\n      __typename\n    }\n    device\n    name\n    priority\n    __typename\n  }\n  deviceGroups {\n    id\n    devices {\n      deviceDeliveryUnits {\n        deviceDeliveryQualities {\n          isStreamable\n          isDownloadable\n          __typename\n        }\n        __typename\n      }\n      __typename\n    }\n    __typename\n  }\n  vrViewingType\n  __typename\n}\nfragment AnimeAdditionalContentData on PPVContent {\n  deliveryStartDate\n  duration\n  series {\n    id\n    name\n    __typename\n  }\n  maker {\n    id\n    name\n    __typename\n  }\n  label {\n    id\n    name\n    __typename\n  }\n  genres {\n    id\n    name\n    __typename\n  }\n  makerContentId\n  playableInfo {\n    ...PlayableInfo\n    __typename\n  }\n  __typename\n}\nfragment AvAdditionalContentData on PPVContent {\n  deliveryStartDate\n  makerReleasedAt\n  duration\n  actresses {\n    id\n    name\n    nameRuby\n    imageUrl\n    isBookmarked @include(if: $isLoggedIn)\n    __typename\n  }\n  histrions {\n    id\n    name\n    __typename\n  }\n  directors {\n    id\n    name\n    __typename\n  }\n  series {\n    id\n    name\n    __typename\n  }\n  maker {\n    id\n    name\n    __typename\n  }\n  label {\n    id\n    name\n    __typename\n  }\n  genres {\n    id\n    name\n    __typename\n  }\n  contentType\n  relatedWords\n  makerContentId\n  playableInfo {\n    ...PlayableInfo\n    __typename\n  }\n  __typename\n}\nfragment CinemaAdditionalContentData on PPVContent {\n  deliveryStartDate\n  duration\n  actresses {\n    id\n    name\n    nameRuby\n    imageUrl\n    __typename\n  }\n  histrions {\n    id\n    name\n    __typename\n  }\n  directors {\n    id\n    name\n    __typename\n  }\n  authors {\n    id\n    name\n    __typename\n  }\n  series {\n    id\n    name\n    __typename\n  }\n  maker {\n    id\n    name\n    __typename\n  }\n  label {\n    id\n    name\n    __typename\n  }\n  genres {\n    id\n    name\n    __typename\n  }\n  makerContentId\n  playableInfo {\n    ...PlayableInfo\n    __typename\n  }\n  __typename\n}\nfragment ReviewSummary on ReviewSummary {\n  average\n  total\n  withCommentTotal\n  distributions {\n    total\n    withCommentTotal\n    rating\n    __typename\n  }\n  __typename\n}\nfragment basketCountFragment on Query {\n  basketCount: legacyBasket @include(if: $isSP) {\n    total\n    __typename\n  }\n  __typename\n}"
                payload_content = {"operationName":"ContentPageData", "query":query_content, "variables":{"id":cid_part,"isAmateur":False,"isAnime":False,"isAv":True,"isCinema":False,"isLoggedIn":False,"isSP":False}}
                res = cls.get_response(api_url, method='POST', headers=headers, json=payload_content)
                logger.debug("DMM Info (API): Step 3/3 'ContentPageData' API call completed.")

                if res.status_code != 200:
                    logger.error(f"DMM API Error: Status {res.status_code} for {code} on ContentPageData call."); return None
                data = res.json()
                if 'errors' in data or not data.get('data', {}).get('ppvContent'):
                    logger.error(f"DMM API Error: Invalid JSON for {code} on ContentPageData call. Response: {data}"); return None
                api_data = data['data']
            except Exception as e:
                logger.exception(f"DMM API call sequence failed for {code}: {e}"); return None

        elif entity.content_type == 'dvd' or entity.content_type == 'bluray':
            # --- 기존 방식: dvd/bluray는 HTML 페이지 파싱 ---
            logger.debug(f"DMM Info (HTML): Getting info for {code} (type: {entity.content_type})")
            detail_url = SITE_BASE_URL + f"/mono/dvd/-/detail/=/cid={cid_part}/"
            referer = SITE_BASE_URL + "/mono/dvd/"
            headers = cls.get_request_headers(referer=referer)
            try:
                logger.info(f"DMM INFO URL: {detail_url}")
                tree = cls.get_tree(detail_url, headers=headers, timeout=30, verify=False)
                if tree is None: 
                    logger.error(f"DMM Info (DVD): Failed to get page tree for {code}."); return None
            except Exception as e_gt_info_dmm: 
                logger.exception(f"DMM Info (DVD): Exc getting detail page: {e_gt_info_dmm}"); return None

        # === 2. 전체 메타데이터 파싱 ===
        identifier_parsed = False
        try:
            if api_data:
                # --- 새로운 방식: JSON에서 데이터 매핑 ---
                content = api_data.get('ppvContent')
                review = api_data.get('reviewSummary', {})

                if not content:
                    logger.error(f"DMM API: 'ppvContent' is null in API response for {code}.")
                    return None

                if content.get('contentType') == 'VR':
                    entity.content_type = 'vr'
                    logger.debug(f"DMM Info (API): Content type updated to 'vr' for {code}")

                title_val = content.get('title')
                if title_val: entity.tagline = cls.trans(title_val)
                plot_val = content.get('description')
                if plot_val: entity.plot = cls.trans(plot_val)

                id_to_parse = content.get('makerContentId') or cid_part
                parsed_ui_code, _, _ = cls._parse_ui_code_from_cid(id_to_parse, entity.content_type)
                entity.ui_code = parsed_ui_code
                ui_code_for_image = entity.ui_code.lower()
                entity.title = entity.originaltitle = entity.sorttitle = ui_code_for_image.upper()
                identifier_parsed = True

                premiered_val = content.get('deliveryStartDate')
                if premiered_val and isinstance(premiered_val, str):
                    try:
                        entity.premiered = premiered_val.split('T')[0]
                        entity.year = int(entity.premiered[:4])
                    except (ValueError, IndexError):
                        logger.warning(f"DMM API: Could not parse year from premiered date: {premiered_val}")

                duration_val = content.get('duration')
                if isinstance(duration_val, int):
                    entity.runtime = duration_val // 60

                if review:
                    rating_val = review.get('average')
                    if rating_val is not None:
                        try:
                            entity.ratings.append(EntityRatings(float(rating_val), max=5, name="dmm"))
                        except (ValueError, TypeError):
                            logger.warning(f"DMM API: Could not parse rating value: {rating_val}")

                actresses_list = content.get('actresses')
                if actresses_list:
                    actors = []
                    for actress in actresses_list:
                        if isinstance(actress, dict) and actress.get('name'):
                            actors.append(EntityActor(actress['name']))
                    entity.actor = actors

                directors_list = content.get('directors')
                if directors_list and isinstance(directors_list[0], dict) and directors_list[0].get('name'):
                    entity.director = directors_list[0]['name']

                if content.get('label') and content.get('label').get('name'):
                    entity.studio = AV_STUDIO.get(content['label']['name'], cls.trans(content['label']['name']))
                elif content.get('maker') and content.get('maker').get('name'):
                    entity.studio = cls.trans(content['maker']['name'])

                if content.get('series') and content.get('series').get('name'):
                    entity.tag.append(cls.trans(content['series']['name']))

                parsed_label = entity.ui_code.split('-')[0] if '-' in entity.ui_code else entity.ui_code
                if parsed_label not in entity.tag:
                    entity.tag.append(parsed_label)

                genres_list = content.get('genres')
                if genres_list:
                    entity.genre = []
                    for g_item in genres_list:
                        if not (isinstance(g_item, dict) and g_item.get('name')):
                            continue
                        g_ja = g_item['name']
                        if "％OFF" in g_ja or g_ja in AV_GENRE_IGNORE_JA: continue
                        if g_ja in AV_GENRE: 
                            entity.genre.append(AV_GENRE[g_ja])
                        else:
                            g_ko = cls.trans(g_ja).replace(" ", "")
                            if g_ko not in AV_GENRE_IGNORE_KO: 
                                entity.genre.append(g_ko)

            elif tree is not None:
                # --- 기존 방식: HTML에서 데이터 파싱 (dvd/bluray) ---
                title_node_dvd = tree.xpath('//h1[@id="title"]')
                if title_node_dvd: entity.tagline = cls.trans(title_node_dvd[0].text_content().strip())
                info_table_xpath_dvd = '//div[contains(@class, "wrapper-product")]//table[contains(@class, "mg-b20")]//tr'
                table_rows_dvd = tree.xpath(info_table_xpath_dvd)
                premiered_shouhin_dvd, premiered_hatsubai_dvd, premiered_haishin_dvd = None, None, None   

                if not table_rows_dvd:
                    logger.warning(f"DMM ({entity.content_type}): No <tr> tags found in the info table using XPath: {info_table_xpath_dvd}")

                for row_dvd in table_rows_dvd:
                    tds_dvd = row_dvd.xpath("./td")
                    if len(tds_dvd) != 2:
                        continue

                    key_dvd = tds_dvd[0].text_content().strip().replace("：", "")
                    value_node_dvd = tds_dvd[1]
                    value_text_all_dvd = value_node_dvd.text_content().strip()

                    if value_text_all_dvd == "----" or not value_text_all_dvd:
                        continue

                    if "品番" in key_dvd:

                        if value_text_all_dvd:
                            logger.debug(f"DMM Info: Parsed '品番' value from page: '{key_dvd}' for {code}.")

                            parsed_ui_code_page, _, _ = cls._parse_ui_code_from_cid(value_text_all_dvd, entity.content_type)
                            entity.ui_code = parsed_ui_code_page

                            ui_code_for_image = parsed_ui_code_page.lower()
                            entity.title = entity.originaltitle = entity.sorttitle = ui_code_for_image.upper()
                            identifier_parsed = True
                            # logger.debug(f"DMM ({entity.content_type}): 品番 파싱 완료, ui_code_for_image='{ui_code_for_image}'")

                            parsed_label = parsed_ui_code_page.split('-')[0] if '-' in parsed_ui_code_page else parsed_ui_code_page
                            if entity.tag is None: entity.tag = []
                            if parsed_label and parsed_label not in entity.tag:
                                entity.tag.append(parsed_label)

                    elif "収録時間" in key_dvd: 
                        m_rt_dvd = re.search(r"(\d+)",value_text_all_dvd)
                        if m_rt_dvd: entity.runtime = int(m_rt_dvd.group(1))
                    elif "出演者" in key_dvd:
                        actors_dvd = [a.strip() for a in value_node_dvd.xpath('.//a/text()') if a.strip()]
                        if actors_dvd: entity.actor = [EntityActor(name) for name in actors_dvd]
                        elif value_text_all_dvd != '----': entity.actor = [EntityActor(n.strip()) for n in value_text_all_dvd.split('/') if n.strip()]
                    elif "監督" in key_dvd:
                        directors_dvd = [d.strip() for d in value_node_dvd.xpath('.//a/text()') if d.strip()]
                        if directors_dvd: entity.director = directors_dvd[0] 
                        elif value_text_all_dvd != '----': entity.director = value_text_all_dvd
                    elif "シリーズ" in key_dvd:
                        if entity.tag is None: entity.tag = []
                        series_dvd = [s.strip() for s in value_node_dvd.xpath('.//a/text()') if s.strip()]
                        s_name_dvd = None
                        if series_dvd: s_name_dvd = series_dvd[0]
                        elif value_text_all_dvd != '----': s_name_dvd = value_text_all_dvd
                        if s_name_dvd:
                            trans_s_name_dvd = cls.trans(s_name_dvd)
                            if trans_s_name_dvd not in entity.tag: entity.tag.append(trans_s_name_dvd)
                    elif "メーカー" in key_dvd:
                        if entity.studio is None: 
                            makers_dvd = [mk.strip() for mk in value_node_dvd.xpath('.//a/text()') if mk.strip()]
                            m_name_dvd = None
                            if makers_dvd: m_name_dvd = makers_dvd[0]
                            elif value_text_all_dvd != '----': m_name_dvd = value_text_all_dvd
                            if m_name_dvd: entity.studio = cls.trans(m_name_dvd)
                    elif "レーベル" in key_dvd:
                        labels_dvd = [lb.strip() for lb in value_node_dvd.xpath('.//a/text()') if lb.strip()]
                        l_name_dvd = None
                        if labels_dvd: l_name_dvd = labels_dvd[0]
                        elif value_text_all_dvd != '----': l_name_dvd = value_text_all_dvd
                        if l_name_dvd:
                            entity.studio = AV_STUDIO.get(l_name_dvd, cls.trans(l_name_dvd))
                    elif "ジャンル" in key_dvd:
                        if entity.genre is None: entity.genre = []
                        for genre_ja_tag_dvd in value_node_dvd.xpath('.//a'):
                            genre_ja_dvd = genre_ja_tag_dvd.text_content().strip()
                            if not genre_ja_dvd or "％OFF" in genre_ja_dvd or genre_ja_dvd in AV_GENRE_IGNORE_JA: 
                                continue
                            if genre_ja_dvd in AV_GENRE:
                                if AV_GENRE[genre_ja_dvd] not in entity.genre: 
                                    entity.genre.append(AV_GENRE[genre_ja_dvd])
                            else:
                                genre_ko_dvd = cls.trans(genre_ja_dvd).replace(" ", "")
                                if genre_ko_dvd not in AV_GENRE_IGNORE_KO and genre_ko_dvd not in entity.genre : entity.genre.append(genre_ko_dvd)

                    # 출시일 관련 정보 수집
                    elif "商品発売日" in key_dvd: premiered_shouhin_dvd = value_text_all_dvd.replace("/", "-")
                    elif "発売日" in key_dvd: premiered_hatsubai_dvd = value_text_all_dvd.replace("/", "-")
                    elif "配信開始日" in key_dvd: premiered_haishin_dvd = value_text_all_dvd.replace("/", "-")

                # 평점 추출
                rating_text_node_dvd_specific = tree.xpath('//p[contains(@class, "dcd-review__average")]/strong/text()')
                if rating_text_node_dvd_specific:
                    rating_text = rating_text_node_dvd_specific[0].strip()
                    try:
                        rate_val = float(rating_text)
                        if 0 <= rate_val <= 5: 
                            if not entity.ratings: entity.ratings.append(EntityRatings(rate_val, max=5, name="dmm"))
                    except ValueError:
                        rating_match = re.search(r'([\d\.]+)\s*点?', rating_text)
                        if rating_match:
                            try:
                                rate_val = float(rating_match.group(1))
                                if 0 <= rate_val <= 5: 
                                    if not entity.ratings: entity.ratings.append(EntityRatings(rate_val, max=5, name="dmm"))
                            except ValueError:
                                logger.warning(f"DMM ({entity.content_type}): Rating conversion error (after regex): {rating_text}")
                else:
                    logger.debug(f"DMM ({entity.content_type}): DVD/BR specific rating element (dcd-review__average) not found.")

                # 출시일 최종 결정
                entity.premiered = premiered_shouhin_dvd or premiered_hatsubai_dvd or premiered_haishin_dvd
                if entity.premiered: 
                    try: entity.year = int(entity.premiered[:4])
                    except ValueError: logger.warning(f"DMM ({entity.content_type}): Year parse error from '{entity.premiered}'")
                else:
                    logger.warning(f"DMM ({entity.content_type}): Premiered date not found for {code}.")

                plot_xpath_dvd_specific = '//div[@class="mg-b20 lh4"]/p[@class="mg-b20"]/text()'
                plot_nodes_dvd_specific = tree.xpath(plot_xpath_dvd_specific)
                if plot_nodes_dvd_specific:
                    plot_text = "\n".join([p.strip() for p in plot_nodes_dvd_specific if p.strip()]).split("※")[0].strip()
                    if plot_text: entity.plot = cls.trans(plot_text)
                else: 
                    logger.warning(f"DMM ({entity.content_type}): Plot not found for {code} using XPath: {plot_xpath_dvd_specific}")

            if not identifier_parsed:
                logger.error(f"DMM ({entity.content_type}): CRITICAL - Identifier parse failed for {code} after all attempts.")
                ui_code_for_image = code[2:].upper().replace("_","-")
                entity.title=entity.originaltitle=entity.sorttitle=ui_code_for_image; entity.ui_code=ui_code_for_image
            if not entity.tagline and entity.title: entity.tagline = entity.title
            if not entity.plot and entity.tagline: entity.plot = entity.tagline
        except Exception as e_meta:
            logger.exception(f"DMM Meta parsing error for {code}: {e_meta}")
            return None

        # === 3. 이미지 처리: 모든 이미지 관련 로직을 공통 메서드에 위임 ===
        try:
            # 원본 이미지 URL 목록 수집
            raw_image_urls = cls.__img_urls(
                tree, 
                content_type=entity.content_type,
                api_data=api_data
            )

            # 공통 처리 함수에 모든 것을 위임
            entity = cls.process_image_data(entity, raw_image_urls, ps_url_from_search_cache)

        except Exception as e:
            logger.exception(f"DMM: Error during image processing delegation for {code}: {e}")

        # === 4. 예고편(Extras) 처리 ===

        if cls.config['use_extras']:
            cls.process_extras(entity, tree, detail_url, api_data)
            
        logger.info(f"DMM ({entity.content_type}): __info finished for {code}. UI: {entity.ui_code}, Thumbs:{len(entity.thumb)}, Fanarts:{len(entity.fanart)}")
        return entity


    # 이미지 url 얻기
    @classmethod
    def __img_urls(cls, tree=None, content_type='unknown', api_data=None):
        img_urls_dict = {'ps': "", 'pl': "", 'arts': [], 'specific_poster_candidates': []}

        # --- API 방식 (videoa/vr) ---
        if api_data:
            try:
                content = api_data['ppvContent']
                package_image = content.get('packageImage', {})
                img_urls_dict['pl'] = package_image.get('largeUrl')
                
                arts = []
                if content.get('sampleImages'):
                    for sample in content['sampleImages']:
                        if sample.get('largeImageUrl'):
                            arts.append(sample['largeImageUrl'])
                img_urls_dict['arts'] = arts
                
                if arts:
                    img_urls_dict['specific_poster_candidates'].append(arts[0])
                    if len(arts) > 1 and arts[-1] != arts[0]:
                        img_urls_dict['specific_poster_candidates'].append(arts[-1])
                return img_urls_dict
            except Exception as e:
                logger.error(f"DMM __img_urls (API): Failed to parse image URLs from JSON: {e}")
                return img_urls_dict

        # --- HTML 파싱 방식 (dvd/bluray) ---
        if tree is None:
            logger.warning("DMM __img_urls (HTML): Tree object is None, cannot parse images.")
            return img_urls_dict

        try:
            if content_type == 'dvd' or content_type == 'bluray':
                temp_pl_dvd = ""
                temp_arts_list_dvd = []

                # 1. 메인 패키지 이미지 (PL 후보)
                package_li_node = tree.xpath('//ul[@id="sample-image-block"]/li[contains(@class, "layout-sampleImage__item") and .//a[@name="package-image"]][1]')
                if package_li_node:
                    img_tag_in_pkg_li = package_li_node[0].xpath('.//img')
                    if img_tag_in_pkg_li:
                        thumb_url_raw_pkg = img_tag_in_pkg_li[0].attrib.get("data-lazy") or img_tag_in_pkg_li[0].attrib.get("src")
                        if thumb_url_raw_pkg:
                            thumb_url_pkg = thumb_url_raw_pkg.strip()
                            if not thumb_url_pkg.lower().endswith("dummy_ps.gif"):
                                if not thumb_url_pkg.startswith("http"):
                                    thumb_url_pkg = urljoin(SITE_BASE_URL, thumb_url_pkg)
                                if thumb_url_pkg.endswith("ps.jpg"):
                                    temp_pl_dvd = thumb_url_pkg.replace("ps.jpg", "pl.jpg")

                if temp_pl_dvd:
                    img_urls_dict['pl'] = temp_pl_dvd
                else: # 위에서 PL 못 찾았으면, 대체 경로 시도
                    package_img_xpath_alt = '//div[@id="fn-sampleImage-imagebox"]/img/@src'
                    package_img_tags_alt = tree.xpath(package_img_xpath_alt)
                    if package_img_tags_alt:
                        raw_pkg_img_url_alt = package_img_tags_alt[0].strip()
                        if raw_pkg_img_url_alt:
                            candidate_pl_url_alt = ""
                            if raw_pkg_img_url_alt.startswith("//"):
                                candidate_pl_url_alt = "https:" + raw_pkg_img_url_alt
                            elif not raw_pkg_img_url_alt.startswith("http"):
                                candidate_pl_url_alt = urljoin(SITE_BASE_URL, raw_pkg_img_url_alt)
                            else:
                                candidate_pl_url_alt = raw_pkg_img_url_alt
                            img_urls_dict['pl'] = candidate_pl_url_alt

                # 2. 샘플 이미지에서 Art 추출 (name="sample-image"인 것들)
                sample_li_nodes = tree.xpath('//ul[@id="sample-image-block"]/li[contains(@class, "layout-sampleImage__item") and .//a[@name="sample-image"]]')
                for li_node in sample_li_nodes:
                    img_tag = li_node.xpath('.//img')
                    if not img_tag: continue

                    thumb_url_raw = img_tag[0].attrib.get("data-lazy") or img_tag[0].attrib.get("src")
                    if not thumb_url_raw: continue

                    thumb_url = thumb_url_raw.strip()
                    if thumb_url.lower().endswith("dummy_ps.gif"): continue
                    if not thumb_url.startswith("http"):
                        thumb_url = urljoin(SITE_BASE_URL, thumb_url)
                    
                    high_res_candidate_url = None
                    match_new_pattern = re.search(r'^(.*)-(\d+\.(?:jpg|jpeg|png|webp))$', thumb_url, re.IGNORECASE)
                    if match_new_pattern:
                        base_path_part = match_new_pattern.group(1)
                        numeric_suffix_with_ext = match_new_pattern.group(2)
                        high_res_candidate_url = f"{base_path_part}jp-{numeric_suffix_with_ext}"

                    if high_res_candidate_url:
                        temp_arts_list_dvd.append(high_res_candidate_url)

                # 중복된 URL 제거 후 할당
                img_urls_dict['arts'] = list(dict.fromkeys(temp_arts_list_dvd))
                
                # specific_poster_candidates 설정
                if img_urls_dict['arts']:
                    img_urls_dict['specific_poster_candidates'].append(img_urls_dict['arts'][0])
                    if len(img_urls_dict['arts']) > 1 and img_urls_dict['arts'][-1] != img_urls_dict['arts'][0]:
                        img_urls_dict['specific_poster_candidates'].append(img_urls_dict['arts'][-1])

        except Exception as e_img_urls_main:
            logger.exception(f"DMM __img_urls ({content_type}): General error extracting image URLs: {e_img_urls_main}")

        logger.debug(f"DMM __img_urls ({content_type}) Raw URLs collected: PL='{img_urls_dict.get('pl', '')}', SpecificCandidates={len(img_urls_dict.get('specific_poster_candidates',[]))}, Arts={len(img_urls_dict.get('arts',[]))}.")
        return img_urls_dict

    # endregion INFO
    ################################################


    ################################################
    # region 예고편처리

    @classmethod
    def process_extras(cls, entity, tree, detail_url, api_data=None):
        entity.extras = []
        trailer_title_for_extra = entity.tagline if entity.tagline else entity.ui_code
        trailer_url_final = None
        code = entity.code
        try:
            cid_part = code[len(cls.module_char)+len(cls.site_char):]
            detail_url_for_referer = detail_url

            # API로 정보를 가져온 경우 (videoa/vr)
            if api_data:
                content = api_data.get('ppvContent', {})
                sample_movie = content.get('sampleMovie', {})

                if not sample_movie:
                    logger.debug(f"DMM Trailer: No 'sampleMovie' info in API data for {code}. Skipping trailer search.")
                elif sample_movie.get('has2d'):
                    # 2D 예고편이 있으면, html5_player 방식만 시도
                    logger.debug("DMM Trailer: API indicates a 2D trailer is available. Using html5_player method.")
                    trailer_url_final, _ = cls._get_dmm_video_trailer_from_args_json(cid_part, detail_url_for_referer, entity.content_type)
                elif sample_movie.get('hasVr'):
                    # 2D 예고편은 없고 VR 예고편만 있으면, VR 전용 방식만 시도
                    logger.debug("DMM Trailer: API indicates only a VR trailer is available. Using VR method.")
                    trailer_url_final = cls._get_dmm_vr_trailer(cid_part, detail_url_for_referer)
                else:
                    logger.debug(f"DMM Trailer: 'has2d' and 'hasVr' are both false for {code}. Skipping.")

            # HTML로 정보를 가져온 경우 (dvd/bluray)
            elif tree is not None:
                onclick_trailer = tree.xpath('//a[@id="sample-video1"]/@onclick | //a[contains(@onclick,"gaEventVideoStart")]/@onclick')
                if onclick_trailer:
                    match_json = re.search(r"gaEventVideoStart\s*\(\s*'(\{.*?\})'\s*,\s*'(\{.*?\})'\s*\)", onclick_trailer[0])
                    if match_json:
                        video_data_str = match_json.group(1).replace('\\"', '"')
                        try:
                            video_data = json.loads(video_data_str)
                            if video_data.get("video_url"):
                                trailer_url_final = video_data["video_url"]
                        except json.JSONDecodeError as e_json_dvd:
                            logger.error(f"DMM DVD/BR Trailer: JSONDecodeError - {e_json_dvd}.")

            if trailer_url_final:
                logger.debug(f"DMM Trailer: Found URL for {code}: {trailer_url_final}")
                url = cls.make_video_url(trailer_url_final)
                if url:
                    entity.extras.append(EntityExtra("trailer", trailer_title_for_extra, "mp4", url))

        except Exception as e_trailer_main: 
            logger.exception(f"DMM ({entity.content_type}): Main trailer processing error: {e_trailer_main}")


    @classmethod
    def _get_dmm_video_trailer_from_args_json(cls, cid_part, detail_url_for_referer,  current_content_type_for_log="video"):
        """
        DMM의 videoa 및 VR 타입 예고편 추출 헬퍼.
        html5_player 페이지에 직접 접속하여 'args' 변수에서 JSON 데이터를 파싱합니다.
        성공 시 (trailer_url, trailer_title) 반환, 실패 시 (None, None) 반환.
        """
        trailer_url = None
        trailer_title_from_json = None

        try:
            player_page_url = f"https://www.dmm.co.jp/service/digitalapi/-/html5_player/=/cid={cid_part}"
            logger.debug(f"DMM Trailer Helper ({current_content_type_for_log}): Accessing player page: {player_page_url}")

            player_page_text = cls.get_text(player_page_url, headers=cls.get_request_headers(referer=detail_url_for_referer))
            
            if player_page_text:
                match = re.search(r'const\s+args\s*=\s*(\{.*?\});', player_page_text, re.DOTALL)
                if match:
                    json_str = match.group(1)
                    try:
                        trailer_data = json.loads(json_str)
                        
                        if trailer_data.get('bitrates'):
                            highest_quality_video = trailer_data['bitrates'][0]
                            if highest_quality_video.get('src'):
                                trailer_url_raw = highest_quality_video['src']
                                trailer_url = "https:" + trailer_url_raw if trailer_url_raw.startswith('//') else trailer_url_raw
                        
                        if trailer_data.get('title'):
                            trailer_title_from_json = trailer_data['title']

                    except json.JSONDecodeError as e:
                        logger.error(f"DMM Trailer Helper ({current_content_type_for_log}): Failed to parse JSON. Error: {e}")
                else:
                    logger.warning(f"DMM Trailer Helper ({current_content_type_for_log}): Could not find 'const args' in player page.")
            else:
                logger.warning(f"DMM Trailer Helper ({current_content_type_for_log}): Failed to get content from player page.")
        
        except Exception as e_helper:
            logger.exception(f"DMM Trailer Helper ({current_content_type_for_log}): Exception for CID {cid_part}: {e_helper}")

        return trailer_url, trailer_title_from_json

    @classmethod
    def _get_dmm_vr_trailer(cls, cid_part, detail_url_for_referer):
        trailer_url = None
        try:
            vr_player_page_url = f"{SITE_BASE_URL}/digital/-/vr-sample-player/=/cid={cid_part}/"
            logger.debug(f"DMM VR Trailer: Accessing player page: {vr_player_page_url}")
            vr_player_html = cls.get_text(vr_player_page_url, headers=cls.get_request_headers(referer=detail_url_for_referer))
            if vr_player_html:
                match_js_var = re.search(r'var\s+sampleUrl\s*=\s*["\']([^"\']+)["\']', vr_player_html)
                if match_js_var:
                    trailer_url_raw = match_js_var.group(1)
                    trailer_url = "https:" + trailer_url_raw if trailer_url_raw.startswith("//") else trailer_url_raw
                    # logger.debug(f"DMM VR Trailer: Found sampleUrl: {trailer_url}")
        except Exception as e_fallback:
            logger.exception(f"DMM VR Trailer: Exception for CID {cid_part}: {e_fallback}")
        return trailer_url
    
    # endregion 예고편처리
    ################################################


    ################################################
    # region 전용 UTIL

    @classmethod
    def get_label_from_ui_code(cls, ui_code_str: str) -> str:
        if not ui_code_str or not isinstance(ui_code_str, str): return ""
        ui_code_upper = ui_code_str.upper()

        # PTN_ID와 유사한 패턴으로 ID 계열 레이블 먼저 확인 (예: "16ID-045" -> "16ID")
        id_match = re.match(r'^(\d*[A-Z]+ID)', ui_code_upper) # 예: 16ID, 25ID, ID (숫자 없거나, 있거나)
        if id_match:
            return id_match.group(1)
        
        # 일반적인 경우 (하이픈 앞부분)
        if '-' in ui_code_upper:
            return ui_code_upper.split('-', 1)[0]
        
        # 하이픈 없는 경우 (예: HAGE001)
        match_alpha_prefix = re.match(r'^([A-Z]+)', ui_code_upper)
        if match_alpha_prefix:
            return match_alpha_prefix.group(1)
            
        return ui_code_upper # 최후의 경우 전체 반환


    @classmethod
    def _parse_ui_code_from_cid(cls, cid_part_raw: str, content_type: str) -> tuple:
        
        # 1. 설정 로드
        # 2. CID 전처리
        processed_cid = cid_part_raw.lower()
        processed_cid = re.sub(r'^[hn]_\d', '', processed_cid)
        suffix_strip_match = re.match(r'^(.*\d+)([a-z]+)$', processed_cid, re.I)
        if suffix_strip_match:
            processed_cid = suffix_strip_match.group(1)
            logger.debug(f"SITE_DMM: Stripped suffix. CID is now: '{processed_cid}'")

        # 3. 파싱 변수 초기화
        final_label_part, final_num_part, rule_applied = "", "", False

        # --- 고급 규칙 (유형 0) ---
        for line in cls.config['dmm_parser_rules']['type0_rules']:
            line = line.strip()
            if not line or line.startswith('#'): continue
            
            parts = line.split('=>')
            if len(parts) != 3:
                logger.warning(f"Invalid advanced rule format: {line}")
                continue
            
            pattern, label_group_idx_str, num_group_idx_str = parts[0].strip(), parts[1].strip(), parts[2].strip()
            try:
                label_group_idx = int(label_group_idx_str)
                num_group_idx = int(num_group_idx_str)
                
                match = re.match(pattern, processed_cid, re.I)
                if match:
                    groups = match.groups()
                    # 사용자가 입력한 인덱스가 유효한지 확인
                    if len(groups) >= label_group_idx and len(groups) >= num_group_idx:
                        # 사용자가 입력한 인덱스를 기반으로 바로 값을 가져옴 (1을 빼서 0-based로 변환)
                        final_label_part = groups[label_group_idx - 1]
                        final_num_part = groups[num_group_idx - 1]
                        rule_applied = True
                        logger.debug(f"SITE_DMM: Matched Advanced Rule. Pattern: '{pattern}' -> Label: '{final_label_part}', Num: '{final_num_part}'")
                        break
            except (ValueError, IndexError) as e:
                logger.error(f"Error applying advanced rule: {line} - {e}")
        if rule_applied:
            pass

        # --- 나머지 규칙들 (고급 규칙이 적용되지 않았을 때만 실행) ---
        if not rule_applied:
            # 1. 레이블이 문자로 끝나고 그 뒤에 숫자가 오는 명확한 패턴을 먼저 시도
            clear_pattern_match = re.match(r'^([a-zA-Z\d]*[a-zA-Z])(\d+)$', processed_cid)
            if clear_pattern_match:
                remaining_for_label, extracted_num_part = clear_pattern_match.groups()
            else:
                # 2. 위 패턴이 실패하면, 기존의 길이 기반 숫자 추출을 폴백으로 사용
                expected_num_len = 5 if content_type in ['videoa', 'vr'] else 3
                num_match = re.match(rf'^(.*?)(\d{{{expected_num_len}}})$', processed_cid)
                if num_match:
                    remaining_for_label, extracted_num_part = num_match.groups()
                else:
                    # 3. 길이 기반도 실패하면, 가장 일반적인 숫자 분리
                    general_num_match = re.match(r'^(.*?)(\d+)$', processed_cid)
                    if general_num_match:
                        remaining_for_label, extracted_num_part = general_num_match.groups()
                    else:
                        remaining_for_label, extracted_num_part = processed_cid, ""
            
            final_num_part = extracted_num_part

            # --- 유형 1: 3자리 숫자 + 레이블 ---
            if not rule_applied and cls.config['dmm_parser_rules']['type1_labels']:
                label_pattern = '|'.join(re.escape(label) for label in cls.config['dmm_parser_rules']['type1_labels'])
                match = re.match(r'^.*?(\d{3})(' + label_pattern + r')$', remaining_for_label, re.I)
                if match:
                    final_label_part = match.group(1) + match.group(2)
                    rule_applied = True
                    logger.debug(f"SITE_DMM: Matched Type 1. Remaining '{remaining_for_label}' -> Label '{final_label_part}'")

            # --- 유형 2: 레이블 + 2자리 숫자 ---
            if not rule_applied and cls.config['dmm_parser_rules']['type2_labels']:
                label_pattern = '|'.join(re.escape(label) for label in cls.config['dmm_parser_rules']['type2_labels'])
                match = re.match(r'^.*?(' + label_pattern + r')(\d{2})$', remaining_for_label, re.I)
                if match:
                    series_num, pure_alpha_label = match.group(2), match.group(1)
                    final_label_part = series_num + pure_alpha_label
                    rule_applied = True
                    logger.debug(f"SITE_DMM: Matched Type 2. Remaining '{remaining_for_label}' -> Label '{final_label_part}'")

            # --- 유형 3: 2자리 숫자 + 레이블 ---
            if not rule_applied and cls.config['dmm_parser_rules']['type3_labels']:
                label_pattern = '|'.join(re.escape(label) for label in cls.config['dmm_parser_rules']['type3_labels'])
                match = re.match(r'^.*?(\d{2})(' + label_pattern + r')$', remaining_for_label, re.I)
                if match:
                    final_label_part = match.group(1) + match.group(2)
                    rule_applied = True
                    logger.debug(f"SITE_DMM: Matched Type 3. Remaining '{remaining_for_label}' -> Label '{final_label_part}'")

            # --- 유형 4: 1자리 숫자 + 레이블 ---
            if not rule_applied and cls.config['dmm_parser_rules']['type4_labels']:
                label_pattern = '|'.join(re.escape(label) for label in cls.config['dmm_parser_rules']['type4_labels'])
                match = re.match(r'^.*?(\d{1})(' + label_pattern + r')$', remaining_for_label, re.I)
                if match:
                    final_label_part = match.group(1) + match.group(2)
                    rule_applied = True
                    logger.debug(f"SITE_DMM: Matched Type 4. Remaining '{remaining_for_label}' -> Label '{final_label_part}'")

            # --- 일반 처리 ---
            if not rule_applied:
                alpha_match = re.search(r'([a-zA-Z].*)', remaining_for_label, re.I)
                if alpha_match:
                    final_label_part = alpha_match.group(1)
                else:
                    final_label_part = remaining_for_label
                logger.debug(f"SITE_DMM: No special rule. General parse on '{remaining_for_label}' -> Label '{final_label_part}'")

        # 6. 최종 값 조합
        score_label_part = final_label_part.lower()
        label_ui_part = final_label_part.upper().strip('-') # 후행 하이픈 제거
        label_num_raw_for_score = final_num_part
        num_stripped = final_num_part.lstrip('0') or "0"
        label_num_ui_final = num_stripped.zfill(3)

        if label_ui_part and label_num_ui_final:
            ui_code_final = f"{label_ui_part}-{label_num_ui_final}"
        else:
            ui_code_final = label_ui_part or cid_part_raw.upper()
        
        logger.debug(f"SITE_DMM: _parse_ui_code_from_cid result for '{cid_part_raw}' -> UI Code: '{ui_code_final}'")
        return ui_code_final, score_label_part, label_num_raw_for_score


   




    # 검색용 키워드 반환
    @classmethod
    def __get_keyword_for_url(cls, temp_keyword, is_retry):
        # 재시도에 필요한 부분을 담을 변수 초기화
        label_part_for_retry = ""
        num_part_for_retry = ""
        keyword_for_url = ""

        # --- 2. "ID 계열" 품번 특별 처리 (DMM 검색 형식으로 변환) ---
        match_id_prefix = re.match(r'^id[-_]?(\d{2})(\d+)$', temp_keyword, re.I)
        if match_id_prefix:
            label_series = match_id_prefix.group(1) 
            num_part = match_id_prefix.group(2)
            keyword_for_url = label_series + "id" + num_part.zfill(5)
            return keyword_for_url, "", ""
        
        match_series_id_prefix = re.match(r'^(\d{2})id[-_]?(\d+)$', temp_keyword, re.I)
        if match_series_id_prefix:
            label_series = match_series_id_prefix.group(1)
            num_part = match_series_id_prefix.group(2)
            keyword_for_url = label_series + "id" + num_part.zfill(5)
            return keyword_for_url, "", ""

        # --- 3. ID 계열이 아닌 일반 품번 처리 (DMM 검색 형식으로 변환) ---
        temp_parts_for_url_gen = temp_keyword.replace("-", " ").replace("_"," ").strip().split(" ")
        temp_parts_for_url_gen = [part for part in temp_parts_for_url_gen if part]

        padding_length = 3 if is_retry else 5 # 재시도 여부에 따라 패딩 길이 결정

        if len(temp_parts_for_url_gen) == 2:
            # 재시도에 사용하기 위해 레이블과 숫자 부분을 변수에 저장
            label_part_for_retry = temp_parts_for_url_gen[0]
            num_part_for_retry = temp_parts_for_url_gen[1]
            keyword_for_url = label_part_for_retry + num_part_for_retry.zfill(padding_length)
        elif len(temp_parts_for_url_gen) == 1:
            single_part = temp_parts_for_url_gen[0]
            match_label_num = re.match(r'^([a-z0-9]+?)(\d+)$', single_part, re.I)
            if match_label_num:
                # 재시도에 사용하기 위해 레이블과 숫자 부분을 변수에 저장
                label_part_for_retry = match_label_num.group(1)
                num_part_for_retry = match_label_num.group(2)
                keyword_for_url = label_part_for_retry + num_part_for_retry.zfill(padding_length)
            else: 
                keyword_for_url = single_part
        else: # 0개 또는 3개 이상 파트 (일반적이지 않음)
            keyword_for_url = "".join(temp_parts_for_url_gen) # 일단 모두 합침

        return keyword_for_url, label_part_for_retry, num_part_for_retry



    # 기본헤더에서 Referer를 설정하여 요청 헤더를 반환하는 메서드
    # 복사 불필요
    @classmethod
    def get_request_headers(cls, referer=None):
        cls.default_headers['Referer'] = referer
        return cls.default_headers


    # 인증확인.
    @classmethod
    def _ensure_age_verified(cls):
        # 인증이 되어 있고, 이전 proxy와 동일하다면 바로 True 반환
        if cls.config['age_verified']:
            #logger.debug("DMM age verification already done with the same proxy.")
            return True
        #if not cls.age_verified or cls.last_proxy_used != proxy_url:
        logger.debug("Checking/Performing DMM age verification.")
        
        session_cookies = cls.session.cookies
        domain_checks = ['.dmm.co.jp', '.dmm.com']
        if any('age_check_done' in session_cookies.get_dict(domain=d) and session_cookies.get_dict(domain=d)['age_check_done'] == '1' for d in domain_checks):
            cls.config['age_verified'] = True
            return cls.config['age_verified']
        #logger.debug("Attempting DMM age verification via confirmation GET...")
        try:
            confirm_response = cls.get_response( 
                urljoin(SITE_BASE_URL, f"/age_check/=/declared=yes/?rurl={quote(FANZA_AV_URL, safe='')}"), 
                method='GET', 
                headers=cls.get_request_headers(referer=SITE_BASE_URL + "/"), 
                allow_redirects=False, verify=False
            )
            if confirm_response.status_code == 302 and 'age_check_done=1' in confirm_response.headers.get('Set-Cookie', ''):
                #logger.debug("Age confirmation successful via Set-Cookie.")
                final_cookies = cls.session.cookies
                if any('age_check_done' in final_cookies.get_dict(domain=d) and final_cookies.get_dict(domain=d)['age_check_done'] == '1' for d in domain_checks):
                    #logger.debug("age_check_done=1 confirmed in session.")
                    cls.config['age_verified'] = True
                    return cls.config['age_verified']
                else:
                    logger.warning("Set-Cookie received, but not updated in session. Trying manual set.")
                    cls.session.cookies.set("age_check_done", "1", domain=".dmm.co.jp", path="/")
                    cls.session.cookies.set("age_check_done", "1", domain=".dmm.com", path="/")
                    #logger.debug("Manually set age_check_done cookie.")
                    cls.config['age_verified'] = True
                    return cls.config['age_verified']
            else: 
                logger.warning(f"Age check failed (Status:{confirm_response.status_code} or cookie missing).")
        except Exception as e: 
            logger.exception(f"Age verification exception: {e}")
        cls.config['age_verified'] = False
        return cls.config['age_verified']

    # endregion UTIL
    ################################################


    ################################################
    # region SiteAvBase 메서드 오버라이드

    @classmethod
    def set_config(cls, db):
        super().set_config(db)
        cls.config.update({
            "dmm_parser_rules": {
                "type0_rules": db.get_list(f"jav_censored_{cls.site_name}_parser_type0_rules", "\n"),
                "type1_labels": db.get_list(f"jav_censored_{cls.site_name}_parser_type1_labels", ","),
                "type2_labels": db.get_list(f"jav_censored_{cls.site_name}_parser_type2_labels", ","),
                "type3_labels": db.get_list(f"jav_censored_{cls.site_name}_parser_type3_labels", ","),
                "type4_labels": db.get_list(f"jav_censored_{cls.site_name}_parser_type4_labels", ","),
            },
            # 포스터 예외처리1. 설정된 레이블은 저화질 썸네일을 포스터로 사용
            "ps_force_labels_list": set(db.get_list(f"jav_censored_{cls.site_name}_small_image_to_poster", ",")),
            # 포스터 예외처리2. 가로 이미지 크롭이 필요한 경우 그 위치를 수동 지정
            "crop_mode": db.get_list(f"jav_censored_{cls.site_name}_crop_mode", ","),
            # 지정 레이블 최우선 검색
            "priority_labels": db.get_list(f"jav_censored_{cls.site_name}_priority_search_labels", ","),

            # 설정이 바뀌면 
            "age_verified": False,  # 나이 인증 여부
        })


    # endregion SiteAvBase 메서드 오버라이드
    ################################################

