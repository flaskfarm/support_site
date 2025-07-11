# -*- coding: utf-8 -*-
import json
import re
import urllib.parse as py_urllib_parse
from lxml import html
import os

from ..entity_av import EntityAVSearch
from ..entity_base import EntityActor, EntityExtra, EntityMovie, EntityRatings, EntityThumb
from ..setup import P, logger
from ..site_util_av import SiteUtilAv as SiteUtil


class SiteDmm:
    site_name = "dmm"
    site_base_url = "https://www.dmm.co.jp"
    fanza_av_url = "https://video.dmm.co.jp/av/"
    module_char = "C"
    site_char = "D"

    dmm_base_headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
        "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
        "Sec-Ch-Ua": '"Google Chrome";v="135", "Not-A.Brand";v="8", "Chromium";v="135"',
        "Sec-Ch-Ua-Mobile": "?0", "Sec-Ch-Ua-Platform": '"Windows"',
        "Sec-Fetch-Dest": "document", "Sec-Fetch-Mode": "navigate", "Sec-Fetch-Site": "same-origin",
        "Sec-Fetch-User": "?1", "Upgrade-Insecure-Requests": "1",
        "Referer": site_base_url + "/", "DNT": "1", "Cache-Control": "max-age=0", "Connection": "keep-alive",
    }

    PTN_SEARCH_CID = re.compile(r"\/cid=(?P<code>.*?)\/")
    PTN_SEARCH_REAL_NO = re.compile(r"^([hn]_)?\d*(?P<real>[a-zA-Z]+)(?P<no>\d+)([a-zA-Z]+)?$")
    PTN_ID = re.compile(r"\d{2}id", re.I)
    PTN_RATING = re.compile(r"(?P<rating>[\d|_]+)\.gif") # v_old 패턴

    age_verified = False
    last_proxy_used = None
    _ps_url_cache = {} # code: {'ps': ps_url, 'type': content_type}

    CONTENT_TYPE_PRIORITY = ['videoa', 'vr', 'dvd', 'bluray', 'unknown']


    @classmethod
    def _get_request_headers(cls, referer=None):
        headers = cls.dmm_base_headers.copy()
        if referer: headers['Referer'] = referer
        return headers

    @classmethod
    def _ensure_age_verified(cls, proxy_url=None):
        if not cls.age_verified or cls.last_proxy_used != proxy_url:
            logger.debug("Checking/Performing DMM age verification.")
            cls.last_proxy_used = proxy_url
            session_cookies = SiteUtil.session.cookies
            domain_checks = ['.dmm.co.jp', '.dmm.com']
            if any('age_check_done' in session_cookies.get_dict(domain=d) and session_cookies.get_dict(domain=d)['age_check_done'] == '1' for d in domain_checks):
                #logger.debug("Age verification cookie found in SiteUtil.session.")
                cls.age_verified = True; return True
            #logger.debug("Attempting DMM age verification via confirmation GET...")
            try:
                target_rurl = cls.fanza_av_url
                confirm_path = f"/age_check/=/declared=yes/?rurl={py_urllib_parse.quote(target_rurl, safe='')}"
                age_check_confirm_url = py_urllib_parse.urljoin(cls.site_base_url, confirm_path)
                confirm_headers = cls._get_request_headers(referer=cls.site_base_url + "/")
                confirm_response = SiteUtil.get_response( age_check_confirm_url, method='GET', proxy_url=proxy_url, headers=confirm_headers, allow_redirects=False, verify=False )
                if confirm_response.status_code == 302 and 'age_check_done=1' in confirm_response.headers.get('Set-Cookie', ''):
                    #logger.debug("Age confirmation successful via Set-Cookie.")
                    final_cookies = SiteUtil.session.cookies
                    if any('age_check_done' in final_cookies.get_dict(domain=d) and final_cookies.get_dict(domain=d)['age_check_done'] == '1' for d in domain_checks):
                        #logger.debug("age_check_done=1 confirmed in session.")
                        cls.age_verified = True; return True
                    else:
                        logger.warning("Set-Cookie received, but not updated in session. Trying manual set.")
                        SiteUtil.session.cookies.set("age_check_done", "1", domain=".dmm.co.jp", path="/"); SiteUtil.session.cookies.set("age_check_done", "1", domain=".dmm.com", path="/")
                        #logger.debug("Manually set age_check_done cookie.")
                        cls.age_verified = True; return True
                else: logger.warning(f"Age check failed (Status:{confirm_response.status_code} or cookie missing).")
            except Exception as e: logger.exception(f"Age verification exception: {e}")
            cls.age_verified = False; return False
        else:
            #logger.debug("Age verification already done.")
            return True

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
    def _parse_ui_code_from_cid(cls, cid_part_raw: str, content_type: str, dmm_parser_rules: dict = None) -> tuple:
        if dmm_parser_rules is None: dmm_parser_rules = {}
        # logger.debug(f"SITE_DMM: _parse_ui_code_from_cid called with cid='{cid_part_raw}', type='{content_type}', rules={dmm_parser_rules}")

        # 1. 설정 로드
        def get_labels_from_string(label_str):
            return {label.strip().lower() for label in (label_str or "").split(',') if label.strip()}

        type0_rules_str = dmm_parser_rules.get('type0_rules', '') # 고급 규칙
        type1_labels = get_labels_from_string(dmm_parser_rules.get('type1')) # 3자리 숫자 + 레이블
        type2_labels = get_labels_from_string(dmm_parser_rules.get('type2')) # 레이블 + 2자리 숫자
        type3_labels = get_labels_from_string(dmm_parser_rules.get('type3')) # 2자리 숫자 + 레이블
        type4_labels = get_labels_from_string(dmm_parser_rules.get('type4')) # 1자리 숫자 + 레이블

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
        if type0_rules_str:
            for line in type0_rules_str.splitlines():
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
            if not rule_applied and type1_labels:
                label_pattern = '|'.join(re.escape(label) for label in type1_labels)
                match = re.match(r'^.*?(\d{3})(' + label_pattern + r')$', remaining_for_label, re.I)
                if match:
                    final_label_part = match.group(1) + match.group(2)
                    rule_applied = True
                    logger.debug(f"SITE_DMM: Matched Type 1. Remaining '{remaining_for_label}' -> Label '{final_label_part}'")

            # --- 유형 2: 레이블 + 2자리 숫자 ---
            if not rule_applied and type2_labels:
                label_pattern = '|'.join(re.escape(label) for label in type2_labels)
                match = re.match(r'^.*?(' + label_pattern + r')(\d{2})$', remaining_for_label, re.I)
                if match:
                    series_num, pure_alpha_label = match.group(2), match.group(1)
                    final_label_part = series_num + pure_alpha_label
                    rule_applied = True
                    logger.debug(f"SITE_DMM: Matched Type 2. Remaining '{remaining_for_label}' -> Label '{final_label_part}'")

            # --- 유형 3: 2자리 숫자 + 레이블 ---
            if not rule_applied and type3_labels:
                label_pattern = '|'.join(re.escape(label) for label in type3_labels)
                match = re.match(r'^.*?(\d{2})(' + label_pattern + r')$', remaining_for_label, re.I)
                if match:
                    final_label_part = match.group(1) + match.group(2)
                    rule_applied = True
                    logger.debug(f"SITE_DMM: Matched Type 3. Remaining '{remaining_for_label}' -> Label '{final_label_part}'")

            # --- 유형 4: 1자리 숫자 + 레이블 ---
            if not rule_applied and type4_labels:
                label_pattern = '|'.join(re.escape(label) for label in type4_labels)
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
        label_ui_part = final_label_part.upper()
        label_num_raw_for_score = final_num_part
        num_stripped = final_num_part.lstrip('0') or "0"
        label_num_ui_final = num_stripped.zfill(3)

        if label_ui_part and label_num_ui_final:
            ui_code_final = f"{label_ui_part}-{label_num_ui_final}"
        else:
            ui_code_final = label_ui_part or cid_part_raw.upper()
        
        logger.debug(f"SITE_DMM: _parse_ui_code_from_cid result for '{cid_part_raw}' -> UI Code: '{ui_code_final}'")
        return ui_code_final, score_label_part, label_num_raw_for_score


    @classmethod
    def __search(
        cls,
        keyword,
        do_trans=True,
        proxy_url=None,
        image_mode="0",
        manual=False,
        priority_label_setting_str="",
        dmm_parser_rules: dict = None,
        is_retry: bool = False
        ):
        # logger.debug(f"SITE_DMM: __search received dmm_parser_rules: {dmm_parser_rules}")

        if not cls._ensure_age_verified(proxy_url=proxy_url): return []

        original_keyword = keyword
        keyword_for_url = ""

        # 재시도 로직을 위한 변수
        label_part_for_retry = ""
        num_part_for_retry = ""

        # --- 1. 초기 정제 (입력된 keyword 기준) ---
        temp_keyword = original_keyword.strip().lower()
        temp_keyword = re.sub(r'[-_]?cd\d*$', '', temp_keyword, flags=re.I)
        temp_keyword = temp_keyword.strip('-_ ') # 예: "dsvr-039" 또는 "id-16045"

        # 점수 계산 시 사용하기 위해 keyword_processed_parts를 여기서 생성
        keyword_processed_parts_for_score = temp_keyword.replace("-", " ").replace("_"," ").strip().split(" ")
        keyword_processed_parts_for_score = [part for part in keyword_processed_parts_for_score if part]


        # --- 2. "ID 계열" 품번 특별 처리 (DMM 검색 형식으로 변환) ---
        match_id_prefix = re.match(r'^id[-_]?(\d{2})(\d+)$', temp_keyword, re.I)
        if match_id_prefix:
            label_series = match_id_prefix.group(1) 
            num_part = match_id_prefix.group(2)     
            keyword_for_url = label_series + "id" + num_part.zfill(5) 
        else:
            match_series_id_prefix = re.match(r'^(\d{2})id[-_]?(\d+)$', temp_keyword, re.I)
            if match_series_id_prefix:
                label_series = match_series_id_prefix.group(1) 
                num_part = match_series_id_prefix.group(2)      
                keyword_for_url = label_series + "id" + num_part.zfill(5)
            else:
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

        if is_retry:
            logger.debug(f"DMM Search [RETRY]: original_keyword='{original_keyword}', keyword_for_url='{keyword_for_url}'")
        else:
            logger.debug(f"DMM Search: original_keyword='{original_keyword}', keyword_for_url='{keyword_for_url}', priority_label='{priority_label_setting_str}'")

        # --- 검색 URL 생성 ---
        search_params = { 'redirect': '1', 'enc': 'UTF-8', 'category': '', 'searchstr': keyword_for_url }
        search_url = f"{cls.site_base_url}/search/?{py_urllib_parse.urlencode(search_params)}"
        logger.debug(f"DMM Search URL: {search_url}")

        search_headers = cls._get_request_headers(referer=cls.fanza_av_url)
        tree = None
        try:
            tree = SiteUtil.get_tree(search_url, proxy_url=proxy_url, headers=search_headers, allow_redirects=True)
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
            # HTML 저장 로직
            #try:
            #    import os; from framework import path_data; import html as lxml_html
            #    debug_html_path = os.path.join(path_data, 'tmp', f'dmm_search_fail_{original_keyword.replace("/", "_")}.html')
            #    os.makedirs(os.path.join(path_data, 'tmp'), exist_ok=True)
            #    with open(debug_html_path, 'w', encoding='utf-8') as f:
            #        f.write(etree.tostring(tree, pretty_print=True, encoding='unicode'))
            #    logger.debug(f"DMM Search HTML content saved to: {debug_html_path} due to no items found.")
            #except Exception as e_save_html: logger.error(f"DMM Search: Failed to save HTML for no items: {e_save_html}")
            pass

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
                    parsed_url = py_urllib_parse.urlparse(href)
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
                match_cid_s = cls.PTN_SEARCH_CID.search(href) 
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
                parsed_ui_code, label_for_score_item, num_raw_for_score_item = cls._parse_ui_code_from_cid(cid_part_for_parse, item.content_type, dmm_parser_rules=dmm_parser_rules)
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
                    _image_mode = "1" if image_mode != "0" else image_mode
                    try: item.image_url = SiteUtil.process_image_mode(_image_mode, original_ps_url, proxy_url=proxy_url)
                    except Exception as e_img: logger.error(f"DMM Search: ImgProcErr (manual):{e_img}")
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
                            if cls.CONTENT_TYPE_PRIORITY.index(content_type_cache) >= cls.CONTENT_TYPE_PRIORITY.index(current_main_type_cache):
                                should_update_main_cache = False
                        except ValueError: pass 

                    if should_update_main_cache:
                        cls._ps_url_cache[code_key_cache]['main_content_type'] = content_type_cache
                    # logger.debug(f"DMM PS Cache: Updated for '{code_key_cache}', type '{content_type_cache}'. Main: '{cls._ps_url_cache[code_key_cache].get('main_content_type')}'")

                # 8. "지정 레이블 최우선" 플래그 설정
                item_dict['is_priority_label_site'] = False 
                item_dict['site_key'] = cls.site_name

                ui_code_for_label_check = item_dict.get('ui_code', "")
                if ui_code_for_label_check and priority_label_setting_str: # priority_label_setting_str은 함수 파라미터
                    label_to_check = cls.get_label_from_ui_code(ui_code_for_label_check)
                    if label_to_check:
                        priority_labels_set = {lbl.strip().upper() for lbl in priority_label_setting_str.split(',') if lbl.strip()}
                        if label_to_check in priority_labels_set:
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
                proxy_url=proxy_url, 
                image_mode=image_mode, 
                manual=manual,
                priority_label_setting_str=priority_label_setting_str,
                dmm_parser_rules=dmm_parser_rules,
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
                proxy_url=proxy_url, 
                image_mode=image_mode, 
                manual=manual,
                priority_label_setting_str=priority_label_setting_str,
                dmm_parser_rules=dmm_parser_rules,
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

    @classmethod
    def search(cls, keyword, **kwargs):
        ret = {}
        try:
            do_trans_arg = kwargs.get('do_trans', True)
            proxy_url_arg = kwargs.get('proxy_url', None)
            image_mode_arg = kwargs.get('image_mode', "0")
            manual_arg = kwargs.get('manual', False)
            priority_label_str_arg = kwargs.get('priority_label_setting_str', "")
            dmm_parser_rules = kwargs.get('dmm_parser_rules', {})

            data_list = cls.__search(keyword, do_trans=do_trans_arg, proxy_url=proxy_url_arg, image_mode=image_mode_arg, manual=manual_arg, priority_label_setting_str=priority_label_str_arg, dmm_parser_rules=dmm_parser_rules)

        except Exception as exception:
            logger.exception("SearchErr:")
            ret["ret"] = "exception"; ret["data"] = str(exception)
        else:
            ret["ret"] = "success" if data_list else "no_match"
            ret["data"] = data_list
        return ret

    @classmethod
    def __img_urls(cls, tree, content_type='unknown', now_printing_path=None, proxy_url=None):
        #logger.debug(f"DMM __img_urls: Extracting raw image URLs for type: {content_type}")
        img_urls_dict = {'ps': "", 'pl': "", 'arts': [], 'specific_poster_candidates': []}

        try:
            if content_type == 'videoa' or content_type == 'vr':
                sample_image_links = tree.xpath('//div[@id="sample-image-block"]//a[.//img]')
                if not sample_image_links: # a 태그가 없는 경우 img src 직접 사용
                    all_img_tags_src = tree.xpath('//div[@id="sample-image-block"]//img/@src')
                    if not all_img_tags_src: return img_urls_dict # 이미지조차 없으면 반환

                    # 첫 번째 이미지를 PL로, 나머지를 Art로
                    if all_img_tags_src:
                        pl_candidate_url = py_urllib_parse.urljoin(cls.site_base_url, all_img_tags_src[0].strip())
                        # 플레이스홀더 검사
                        if not (now_printing_path and SiteUtil.are_images_visually_same(pl_candidate_url, now_printing_path, proxy_url=proxy_url)):
                            img_urls_dict['pl'] = pl_candidate_url

                        temp_arts_from_img_tags = []
                        for src in all_img_tags_src[1:]:
                            art_url = py_urllib_parse.urljoin(cls.site_base_url, src.strip())
                            if art_url != img_urls_dict.get('pl') and art_url not in temp_arts_from_img_tags:
                                # 플레이스홀더 검사
                                if not (now_printing_path and SiteUtil.are_images_visually_same(art_url, now_printing_path, proxy_url=proxy_url)):
                                    temp_arts_from_img_tags.append(art_url)
                        img_urls_dict['arts'] = temp_arts_from_img_tags
                        # specific_poster_candidates는 arts 기반으로 생성
                        if img_urls_dict['arts']:
                            img_urls_dict['specific_poster_candidates'].append(img_urls_dict['arts'][0])
                            if len(img_urls_dict['arts']) > 1 and img_urls_dict['arts'][-1] != img_urls_dict['arts'][0]:
                                img_urls_dict['specific_poster_candidates'].append(img_urls_dict['arts'][-1])
                    return img_urls_dict

                # a 태그가 있는 경우 (href 우선, 없으면 img src)
                temp_arts_list_for_processing = [] # 모든 유효한 이미지 URL (순서 유지, 중복 없음)
                seen_urls_in_videoa_vr = set() # 빠른 중복 체크용

                for a_tag in sample_image_links:
                    final_image_url = None
                    href = a_tag.attrib.get("href", "").strip()
                    img_src_list = a_tag.xpath('.//img/@src') # img 태그는 항상 있다고 가정
                    img_src = img_src_list[0].strip() if img_src_list else ""

                    # href가 이미지 URL 형태이면 href 우선
                    if href and re.search(r'\.(jpg|jpeg|png|webp)$', href, re.IGNORECASE):
                        final_image_url = py_urllib_parse.urljoin(cls.site_base_url, href)
                    elif img_src and re.search(r'\.(jpg|jpeg|png|webp)$', img_src, re.IGNORECASE): # 아니면 img_src 사용
                        final_image_url = py_urllib_parse.urljoin(cls.site_base_url, img_src)

                    if final_image_url and final_image_url not in seen_urls_in_videoa_vr:
                        # 플레이스홀더 검사
                        if not (now_printing_path and SiteUtil.are_images_visually_same(final_image_url, now_printing_path, proxy_url=proxy_url)):
                            temp_arts_list_for_processing.append(final_image_url)
                            seen_urls_in_videoa_vr.add(final_image_url)

                # PL 결정 (파일명 기반 또는 첫 번째 이미지)
                processed_pl_v = None
                for url_idx, url_item in enumerate(temp_arts_list_for_processing):
                    filename = url_item.split('/')[-1].lower()
                    is_pl_type = filename.endswith("pl.jpg") or filename.endswith("jp-0.jpg") # jp-0.jpg는 Video A 메인 이미지일 수 있음
                    if is_pl_type:
                        processed_pl_v = url_item
                        # PL로 선택된 이미지는 temp_arts_list_for_processing에서 제거 (또는 아래 arts 리스트 만들 때 제외)
                        # temp_arts_list_for_processing.pop(url_idx) # 제거 시 인덱스 문제 주의
                        break
                if not processed_pl_v and temp_arts_list_for_processing: # PL 못찾았으면 첫번째를 PL로
                    processed_pl_v = temp_arts_list_for_processing[0]

                img_urls_dict['pl'] = processed_pl_v if processed_pl_v else ""

                # Arts 및 Specific Candidates 결정 (순서 유지, 중복 없음)
                remaining_arts_v = []
                if temp_arts_list_for_processing:
                    for url_item_art in temp_arts_list_for_processing:
                        if url_item_art != processed_pl_v: # PL로 사용된 URL 제외
                            if url_item_art not in remaining_arts_v: # 이미 추가된 Art가 아니면
                                remaining_arts_v.append(url_item_art)
                img_urls_dict['arts'] = remaining_arts_v

                if remaining_arts_v: # PL 제외된 아트 목록에서 specific 후보 추출
                    img_urls_dict['specific_poster_candidates'].append(remaining_arts_v[0])
                    if len(remaining_arts_v) > 1 and remaining_arts_v[-1] != remaining_arts_v[0]:
                        img_urls_dict['specific_poster_candidates'].append(remaining_arts_v[-1])

            elif content_type == 'dvd' or content_type == 'bluray':
                # --- DVD/Blu-ray 타입 이미지 추출 로직 ---
                temp_pl_dvd = ""
                temp_arts_list_dvd = []
                seen_high_res_urls = set()

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
                                    thumb_url_pkg = py_urllib_parse.urljoin(cls.site_base_url, thumb_url_pkg)

                                if thumb_url_pkg.endswith("ps.jpg"):
                                    temp_pl_dvd = thumb_url_pkg.replace("ps.jpg", "pl.jpg")

                                if temp_pl_dvd and not (now_printing_path and SiteUtil.are_images_visually_same(temp_pl_dvd, now_printing_path, proxy_url=proxy_url)):
                                    img_urls_dict['pl'] = temp_pl_dvd
                                    seen_high_res_urls.add(temp_pl_dvd)
                                    logger.debug(f"DMM __img_urls ({content_type}): Package Image (PL) inferred: {temp_pl_dvd}")

                if not img_urls_dict['pl']: # 위에서 PL 못 찾았으면, 기존 fn-sampleImage-imagebox 방식 시도
                    package_img_xpath_alt = '//div[@id="fn-sampleImage-imagebox"]/img/@src'
                    package_img_tags_alt = tree.xpath(package_img_xpath_alt)
                    if package_img_tags_alt:
                        raw_pkg_img_url_alt = package_img_tags_alt[0].strip()
                        if raw_pkg_img_url_alt:
                            candidate_pl_url_alt = ""
                            if raw_pkg_img_url_alt.startswith("//"): candidate_pl_url_alt = "https:" + raw_pkg_img_url_alt
                            elif not raw_pkg_img_url_alt.startswith("http"): candidate_pl_url_alt = py_urllib_parse.urljoin(cls.site_base_url, raw_pkg_img_url_alt)
                            else: candidate_pl_url_alt = raw_pkg_img_url_alt
                            if candidate_pl_url_alt and not (now_printing_path and SiteUtil.are_images_visually_same(candidate_pl_url_alt, now_printing_path, proxy_url=proxy_url)):
                                img_urls_dict['pl'] = candidate_pl_url_alt
                                seen_high_res_urls.add(candidate_pl_url_alt)
                                logger.debug(f"DMM __img_urls ({content_type}): Package Image (PL from fn-sampleImage-imagebox) extracted: {img_urls_dict['pl']}.")

                # 2. 샘플 이미지에서 Art 추출 (name="sample-image"인 것들)
                sample_li_nodes = tree.xpath('//ul[@id="sample-image-block"]/li[contains(@class, "layout-sampleImage__item") and .//a[@name="sample-image"]]')
                logger.debug(f"DMM __img_urls ({content_type}): Found {len(sample_li_nodes)} sample <li> tags for art inference.")

                for li_node in sample_li_nodes:
                    img_tag = li_node.xpath('.//img')
                    if not img_tag: continue

                    thumb_url_raw = img_tag[0].attrib.get("data-lazy") or img_tag[0].attrib.get("src")
                    if not thumb_url_raw: continue

                    thumb_url = thumb_url_raw.strip()
                    if thumb_url.lower().endswith("dummy_ps.gif"): continue
                    if not thumb_url.startswith("http"):
                        thumb_url = py_urllib_parse.urljoin(cls.site_base_url, thumb_url)
                    
                    high_res_candidate_url = None
                    # 새로운 패턴: .../xxxx-N.jpg -> .../xxxxjp-N.jpg
                    # 예: https://pics.dmm.co.jp/digital/video/venu00354/venu00354-1.jpg -> .../venu00354jp-1.jpg
                    match_new_pattern = re.search(r'^(.*)-(\d+\.(?:jpg|jpeg|png|webp))$', thumb_url, re.IGNORECASE)
                    if match_new_pattern:
                        base_path_part = match_new_pattern.group(1)
                        numeric_suffix_with_ext = match_new_pattern.group(2)
                        high_res_candidate_url = f"{base_path_part}jp-{numeric_suffix_with_ext}"
                    
                    if high_res_candidate_url and high_res_candidate_url not in seen_high_res_urls:
                        if not (now_printing_path and SiteUtil.are_images_visually_same(high_res_candidate_url, now_printing_path, proxy_url=proxy_url)):
                            temp_arts_list_dvd.append(high_res_candidate_url)
                            seen_high_res_urls.add(high_res_candidate_url)
                            # logger.debug(f"DMM DVD/BR Art: Added inferred high-res URL (-N to jp-N): {high_res_candidate_url}")
                
                img_urls_dict['arts'] = temp_arts_list_dvd
                
                # specific_poster_candidates 설정
                if temp_arts_list_dvd:
                    if temp_arts_list_dvd[0] not in img_urls_dict['specific_poster_candidates']:
                        img_urls_dict['specific_poster_candidates'].append(temp_arts_list_dvd[0])
                    if len(temp_arts_list_dvd) > 1 and \
                       temp_arts_list_dvd[-1] != temp_arts_list_dvd[0] and \
                       temp_arts_list_dvd[-1] not in img_urls_dict['specific_poster_candidates']:
                        img_urls_dict['specific_poster_candidates'].append(temp_arts_list_dvd[-1])
                # === DVD/Blu-ray 타입 이미지 추출 로직 끝 ===

            else: 
                logger.error(f"DMM __img_urls: Unknown content type '{content_type}' for image extraction.")
        
        except Exception as e_img_urls_main:
            logger.exception(f"DMM __img_urls ({content_type}): General error extracting image URLs: {e_img_urls_main}")

        logger.debug(f"DMM __img_urls ({content_type}) Final: PL='{img_urls_dict.get('pl', '')}', SpecificCandidatesCount={len(img_urls_dict.get('specific_poster_candidates',[]))}, ArtsCount={len(img_urls_dict.get('arts',[]))}.")
        return img_urls_dict


    @classmethod
    def _get_dmm_video_trailer_from_args_json(cls, cid_part, detail_url_for_referer, proxy_url=None, current_content_type_for_log="video"):
        """
        DMM의 videoa 및 새로운 VR 타입 예고편 추출 헬퍼.
        AJAX -> iframe -> args JSON 파싱하여 (trailer_url, trailer_title) 반환.
        실패 시 (None, None) 반환.
        """
        trailer_url = None
        trailer_title_from_json = None # JSON에서 가져온 제목

        try:
            ajax_url = py_urllib_parse.urljoin(cls.site_base_url, f"/digital/videoa/-/detail/ajax-movie/=/cid={cid_part}/")
            #logger.debug(f"DMM Trailer Helper ({current_content_type_for_log}): Accessing AJAX URL: {ajax_url}")

            ajax_headers = cls._get_request_headers(referer=detail_url_for_referer)
            ajax_headers.update({'Accept': 'text/html, */*; q=0.01', 'X-Requested-With': 'XMLHttpRequest'})

            ajax_res = SiteUtil.get_response(ajax_url, proxy_url=proxy_url, headers=ajax_headers)

            if ajax_res and ajax_res.status_code == 200 and ajax_res.text.strip():
                iframe_tree = html.fromstring(ajax_res.text)
                iframe_srcs = iframe_tree.xpath("//iframe/@src")

                if iframe_srcs:
                    iframe_url = py_urllib_parse.urljoin(ajax_url, iframe_srcs[0])
                    #logger.debug(f"DMM Trailer Helper ({current_content_type_for_log}): Accessing iframe URL: {iframe_url}")
                    iframe_text = SiteUtil.get_text(iframe_url, proxy_url=proxy_url, headers=cls._get_request_headers(referer=ajax_url))

                    if iframe_text:
                        match_args_json = re.search(r'(?:const|var|let)?\s*args\s*=\s*(\{.*?\});', iframe_text, re.DOTALL)
                        if match_args_json:
                            json_data_str = match_args_json.group(1)
                            try:
                                data_json = json.loads(json_data_str)
                                bitrates = sorted(data_json.get("bitrates",[]), key=lambda k: isinstance(k.get("bitrate"), int) and k.get("bitrate", 0), reverse=True) # bitrate가 숫자인 경우에만 정렬, 아니면 순서대로

                                if bitrates and isinstance(bitrates[0], dict) and bitrates[0].get("src"):
                                    trailer_url_raw = bitrates[0]["src"]
                                    trailer_url = "https:" + trailer_url_raw if trailer_url_raw.startswith("//") else trailer_url_raw
                                elif data_json.get("src"): # bitrates 없고 최상위 src
                                    trailer_url_raw = data_json.get("src")
                                    trailer_url = "https:" + trailer_url_raw if trailer_url_raw.startswith("//") else trailer_url_raw

                                if data_json.get("title") and data_json.get("title").strip():
                                    trailer_title_from_json = data_json.get("title").strip()

                            except json.JSONDecodeError as e_json:
                                logger.error(f"DMM Trailer Helper ({current_content_type_for_log}): JSONDecodeError - {e_json}. Data: {json_data_str[:200]}...")
                        else:
                            logger.warning(f"DMM Trailer Helper ({current_content_type_for_log}): 'args' JSON not found in iframe for CID: {cid_part}")
                    else:
                        logger.warning(f"DMM Trailer Helper ({current_content_type_for_log}): Failed to get iframe content for CID: {cid_part}")
                else:
                    logger.warning(f"DMM Trailer Helper ({current_content_type_for_log}): No iframe in AJAX response for CID: {cid_part}")
            else:
                status_code = ajax_res.status_code if ajax_res else "None"
                logger.warning(f"DMM Trailer Helper ({current_content_type_for_log}): AJAX request failed for CID: {cid_part}. Status: {status_code}")
        except Exception as e_helper:
            logger.exception(f"DMM Trailer Helper ({current_content_type_for_log}): Exception for CID {cid_part}: {e_helper}")

        return trailer_url, trailer_title_from_json

    @classmethod
    def _get_dmm_vr_trailer_fallback(cls, cid_part, detail_url_for_referer, proxy_url=None):
        trailer_url = None
        try:
            vr_player_page_url = f"{cls.site_base_url}/digital/-/vr-sample-player/=/cid={cid_part}/"
            logger.debug(f"DMM VR Trailer Fallback: Accessing player page: {vr_player_page_url}")
            vr_player_html = SiteUtil.get_text(vr_player_page_url, proxy_url=proxy_url, headers=cls._get_request_headers(referer=detail_url_for_referer))
            if vr_player_html:
                match_js_var = re.search(r'var\s+sampleUrl\s*=\s*["\']([^"\']+)["\']', vr_player_html)
                if match_js_var:
                    trailer_url_raw = match_js_var.group(1)
                    trailer_url = "https:" + trailer_url_raw if trailer_url_raw.startswith("//") else trailer_url_raw
                    logger.debug(f"DMM VR Trailer Fallback: Found sampleUrl: {trailer_url}")
        except Exception as e_fallback:
            logger.exception(f"DMM VR Trailer Fallback: Exception for CID {cid_part}: {e_fallback}")
        return trailer_url


    @classmethod
    def __info( 
        cls, code, do_trans=True, proxy_url=None, image_mode="0", max_arts=10, use_extras=True, **kwargs 
    ):
        # === 1. 설정값 로드, 캐시 로드, 페이지 로딩, Entity 초기화 ===
        use_image_server = kwargs.get('use_image_server', False)
        image_server_url = kwargs.get('image_server_url', '').rstrip('/') if use_image_server else ''
        image_server_local_path = kwargs.get('image_server_local_path', '') if use_image_server else ''
        image_path_segment = kwargs.get('url_prefix_segment', 'unknown/unknown')
        ps_to_poster_labels_str = kwargs.get('ps_to_poster_labels_str', '')
        crop_mode_settings_str = kwargs.get('crop_mode_settings_str', '')
        dmm_parser_rules = kwargs.get('dmm_parser_rules', {})

        # <<< 디버깅 로그 추가 (5) >>>
        logger.debug(f"SITE_DMM: __info received dmm_parser_rules via kwargs: {dmm_parser_rules}")

        cached_data = cls._ps_url_cache.get(code, {}) # 기존 변수명 cached_data 사용
        ps_url_from_search_cache = kwargs.get('ps_url')
        if not ps_url_from_search_cache:
            # 전달받은 ps_url이 없으면, 기존 캐시 방식 사용
            cached_data = cls._ps_url_cache.get(code, {})
            content_type_from_cache = cached_data.get('main_content_type', 'unknown')
            ps_url_from_search_cache = cached_data.get(content_type_from_cache)

        # content_type_from_cache 초기화 및 값 할당 (기존 변수명 사용)
        content_type_from_cache = cached_data.get('main_content_type', 'unknown') # <<--- 기본값을 'unknown' 문자열로 명시

        if (content_type_from_cache == 'unknown' or not cached_data.get(content_type_from_cache)) and cached_data: 
            found_type_from_prio = False
            for prio_type in cls.CONTENT_TYPE_PRIORITY:
                if prio_type in cached_data and cached_data.get(prio_type): 
                    content_type_from_cache = prio_type
                    found_type_from_prio = True
                    break
            if not found_type_from_prio: 
                content_type_from_cache = 'unknown'

        ps_url_from_search_cache = cached_data.get(content_type_from_cache) if content_type_from_cache != 'unknown' else None

        #logger.debug(f"DMM Info: Using content_type_from_cache: '{content_type_from_cache}' for page load. PS from cache for this type: {'Yes' if ps_url_from_search_cache else 'No'}")
        #logger.debug(f"DMM Info: Using content_type_from_cache: PS from cache: {ps_url_from_search_cache}")

        # 페이지 로드 및 파싱에 사용될 content_type (기존 변수명 current_content_type 유지)
        current_content_type = content_type_from_cache 
        if current_content_type == 'unknown':
            current_content_type = 'videoa' 
            # logger.warning(f"DMM Info: content_type_from_cache is 'unknown'. Defaulting page load to '{current_content_type}'.")

        #logger.debug(f"DMM Info: Starting for {code}. Type to load: '{current_content_type}'. ImgMode: {image_mode}, UseImgServ: {use_image_server}")

        if not cls._ensure_age_verified(proxy_url=proxy_url):
            logger.error(f"DMM Info ({current_content_type}): Age verification failed for {code}.")
            return None

        cid_part = code[len(cls.module_char)+len(cls.site_char):] # 기존 방식대로 접두사 길이 사용
        detail_url = None

        if current_content_type == 'videoa' or current_content_type == 'vr':
            detail_url = cls.site_base_url + f"/digital/videoa/-/detail/=/cid={cid_part}/"
        elif current_content_type == 'dvd' or current_content_type == 'bluray':
            detail_url = cls.site_base_url + f"/mono/dvd/-/detail/=/cid={cid_part}/"
        else: 
            logger.error(f"DMM Info: Invalid current_content_type '{current_content_type}'. Code: {code}")
            return None 

        logger.debug(f"DMM Info (Processing as {current_content_type}): Accessing detail page: {detail_url}")
        referer = cls.fanza_av_url if current_content_type in ['videoa', 'vr'] else (cls.site_base_url + "/mono/dvd/")
        headers = cls._get_request_headers(referer=referer)

        tree = None
        try:
            tree = SiteUtil.get_tree(detail_url, proxy_url=proxy_url, headers=headers, timeout=30, verify=False)
            if tree is None: 
                logger.error(f"DMM Info ({current_content_type}): Failed to get page tree for {code}. URL: {detail_url}")
                if (content_type_from_cache == 'unknown' or content_type_from_cache == 'videoa') and current_content_type == 'videoa':
                    logger.debug(f"DMM Info: Retrying with DVD path for {code} as videoa failed.")
                    current_content_type = 'dvd' 
                    detail_url = cls.site_base_url + f"/mono/dvd/-/detail/=/cid={cid_part}/"
                    referer = cls.site_base_url + "/mono/dvd/"
                    headers = cls._get_request_headers(referer=referer)
                    tree = SiteUtil.get_tree(detail_url, proxy_url=proxy_url, headers=headers, timeout=30, verify=False)
                    if tree is None: logger.error(f"DMM Info (DVD Retry): Failed to get page tree for {code}."); return None
                else: return None 
            if "年齢認証" in (tree.xpath('//title/text()')[0] if tree.xpath('//title/text()') else ""):
                logger.error(f"DMM Info ({current_content_type}): Age page received for {code}."); return None
        except Exception as e_gt_info_dmm: logger.exception(f"DMM Info ({current_content_type}): Exc getting detail page: {e_gt_info_dmm}"); return None

        entity = EntityMovie(cls.site_name, code); entity.country = ["일본"]; entity.mpaa = "청소년 관람불가"
        entity.thumb = []; entity.fanart = []; entity.extras = []; entity.ratings = []; entity.tag = []
        ui_code_for_image = ""; entity.content_type = current_content_type

        # === 2. 전체 메타데이터 파싱 (ui_code_for_image 및 entity.title 등 확정) ===
        identifier_parsed = False; is_vr_actual = False # 상세페이지에서 VR 여부 최종 확인
        try:
            #logger.debug(f"DMM Info (Parsing as {entity.content_type}): Metadata for {code}...")

            # --- DMM 타입별 메타데이터 파싱 로직 ---
            if entity.content_type == 'videoa' or entity.content_type == 'vr':
                # videoa/vr 파싱
                raw_title_text_v = ""
                try:
                    title_node_v = tree.xpath('//h1[@id="title"]')
                    if title_node_v:
                        raw_title_text_v = title_node_v[0].text_content().strip()
                        if raw_title_text_v.startswith("【VR】"): is_vr_actual = True; entity.content_type = 'vr' # VR 타입 최종 확정
                        entity.tagline = SiteUtil.trans(raw_title_text_v, do_trans=do_trans) # tagline 우선 설정
                    else: logger.warning(f"DMM ({entity.content_type}): Could not find h1#title.")
                except Exception as e_title_parse_v: logger.warning(f"DMM ({entity.content_type}): Error parsing title: {e_title_parse_v}")

                info_table_xpath_v = '//table[contains(@class, "mg-b20")]//tr'

                tags_v = tree.xpath(info_table_xpath_v)
                premiered_shouhin_v = None; premiered_haishin_v = None
                for tag_v in tags_v:
                    key_node_v = tag_v.xpath('./td[@class="nw"]/text()')
                    value_node_list_v = tag_v.xpath('./td[not(@class="nw")]')
                    if not key_node_v or not value_node_list_v: continue
                    key_v = key_node_v[0].strip().replace("：", "")
                    value_node_v_instance = value_node_list_v[0]; value_text_all_v = value_node_v_instance.text_content().strip()
                    if value_text_all_v == "----" or not value_text_all_v: continue

                    if "品番" in key_v:

                        if value_text_all_v:
                            logger.debug(f"DMM Info: Parsed '品番' value from page: '{key_v}' for {code}.")

                            parsed_ui_code_page, _, _ = cls._parse_ui_code_from_cid(value_text_all_v, entity.content_type, dmm_parser_rules=dmm_parser_rules)
                            entity.ui_code = parsed_ui_code_page

                            ui_code_for_image = parsed_ui_code_page.lower()
                            entity.title = entity.originaltitle = entity.sorttitle = ui_code_for_image.upper()
                            identifier_parsed = True
                            # logger.debug(f"DMM ({entity.content_type}): 品番 파싱 완료, ui_code_for_image='{ui_code_for_image}'")

                            parsed_label = parsed_ui_code_page.split('-')[0] if '-' in parsed_ui_code_page else parsed_ui_code_page
                            if entity.tag is None: entity.tag = []
                            if parsed_label and parsed_label not in entity.tag:
                                entity.tag.append(parsed_label)

                    elif "配信開始日" in key_v:
                        premiered_haishin_v = value_text_all_v.replace("/", "-")
                    elif "収録時間" in key_v: 
                        m_rt_v = re.search(r"(\d+)",value_text_all_v); entity.runtime = int(m_rt_v.group(1)) if m_rt_v else None
                    elif "出演者" in key_v:
                        actors_v = [a_v.strip() for a_v in value_node_v_instance.xpath('.//a/text()') if a_v.strip()]
                        if actors_v: entity.actor = [EntityActor(name_v) for name_v in actors_v]
                        elif value_text_all_v != '----': entity.actor = [EntityActor(n_v.strip()) for n_v in value_text_all_v.split('/') if n_v.strip()]
                    elif "監督" in key_v:
                        directors_v = [d_v.strip() for d_v in value_node_v_instance.xpath('.//a/text()') if d_v.strip()]
                        entity.director = directors_v[0] if directors_v else (value_text_all_v if value_text_all_v != '----' else None)
                    elif "シリーズ" in key_v:
                        if entity.tag is None: entity.tag = []
                        series_v = [s_v.strip() for s_v in value_node_v_instance.xpath('.//a/text()') if s_v.strip()]
                        s_name_v = series_v[0] if series_v else (value_text_all_v if value_text_all_v != '----' else None)
                        if s_name_v and SiteUtil.trans(s_name_v, do_trans=do_trans) not in entity.tag: entity.tag.append(SiteUtil.trans(s_name_v, do_trans=do_trans))
                    elif "メーカー" in key_v:
                        if entity.studio is None: # 스튜디오 정보 없으면 제작사로 채움
                            makers_v = [mk_v.strip() for mk_v in value_node_v_instance.xpath('.//a/text()') if mk_v.strip()]
                            m_name_v = makers_v[0] if makers_v else (value_text_all_v if value_text_all_v != '----' else None)
                            if m_name_v: entity.studio = SiteUtil.trans(m_name_v, do_trans=do_trans)
                    elif "レーベル" in key_v: # 레이블은 스튜디오로 사용 (제작사보다 우선)
                        labels_v = [lb_v.strip() for lb_v in value_node_v_instance.xpath('.//a/text()') if lb_v.strip()]
                        l_name_v = labels_v[0] if labels_v else (value_text_all_v if value_text_all_v != '----' else None)
                        if l_name_v:
                            if do_trans: entity.studio = SiteUtil.av_studio.get(l_name_v, SiteUtil.trans(l_name_v))
                            else: entity.studio = l_name_v
                    elif "ジャンル" in key_v:
                        entity.genre = []
                        for genre_ja_tag_v in value_node_v_instance.xpath('.//a'):
                            genre_ja_v = genre_ja_tag_v.text_content().strip();
                            if not genre_ja_v or "％OFF" in genre_ja_v or genre_ja_v in SiteUtil.av_genre_ignore_ja: continue
                            if genre_ja_v in SiteUtil.av_genre: entity.genre.append(SiteUtil.av_genre[genre_ja_v])
                            else:
                                genre_ko_v = SiteUtil.trans(genre_ja_v, do_trans=do_trans).replace(" ", "")
                                if genre_ko_v not in SiteUtil.av_genre_ignore_ko: entity.genre.append(genre_ko_v)

                rating_text_node = tree.xpath('//p[contains(@class, "d-review__average")]/strong/text()')
                if rating_text_node:
                    rating_text = rating_text_node[0].strip()
                    rating_match_text = re.search(r'([\d\.]+)\s*点', rating_text)
                    if rating_match_text:
                        try:
                            rate_val_text = float(rating_match_text.group(1))
                            if 0 <= rate_val_text <= 5:
                                # entity.ratings는 이미 []로 초기화되었으므로 바로 append
                                entity.ratings.append(EntityRatings(rate_val_text, max=5, name="dmm"))
                        except ValueError:
                            logger.warning(f"DMM ({entity.content_type}): Text-based rating conversion error: {rating_text}")
                else:
                    logger.debug(f"DMM ({entity.content_type}): Text-based rating element (d-review__average) not found.")

                # videoa/vr 출시일: 상품일 > 배신일 순
                entity.premiered = premiered_shouhin_v or premiered_haishin_v 
                if entity.premiered: entity.year = int(entity.premiered[:4]) if len(entity.premiered) >=4 else None
                else: logger.warning(f"DMM ({entity.content_type}): Premiered date not found for {code}.")

                # videoa/vr 줄거리
                plot_xpath_v_meta_info = '//div[@class="mg-b20 lh4"]/text()'
                plot_nodes_v_meta_info = tree.xpath(plot_xpath_v_meta_info)
                if plot_nodes_v_meta_info:
                    plot_text_v_meta_info = "\n".join([p_v_info.strip() for p_v_info in plot_nodes_v_meta_info if p_v_info.strip()]).split("※")[0].strip()
                    if plot_text_v_meta_info: entity.plot = SiteUtil.trans(plot_text_v_meta_info, do_trans=do_trans)
                else: logger.warning(f"DMM ({entity.content_type}): Plot not found for {code}.")

            elif entity.content_type == 'dvd' or entity.content_type == 'bluray':
                title_node_dvd = tree.xpath('//h1[@id="title"]')
                if title_node_dvd: 
                    entity.tagline = SiteUtil.trans(title_node_dvd[0].text_content().strip(), do_trans=do_trans)

                info_table_xpath_dvd = '//div[contains(@class, "wrapper-product")]//table[contains(@class, "mg-b20")]//tr'
                table_rows_dvd = tree.xpath(info_table_xpath_dvd)

                premiered_shouhin_dvd = None 
                premiered_hatsubai_dvd = None  
                premiered_haishin_dvd = None   

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

                    # --- 테이블 내부 항목 파싱 (videoa/vr 로직을 여기에 적용) ---
                    if "品番" in key_dvd:

                        if value_text_all_dvd:
                            logger.debug(f"DMM Info: Parsed '品番' value from page: '{key_dvd}' for {code}.")

                            parsed_ui_code_page, _, _ = cls._parse_ui_code_from_cid(value_text_all_dvd, entity.content_type, dmm_parser_rules=dmm_parser_rules)
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
                            trans_s_name_dvd = SiteUtil.trans(s_name_dvd, do_trans=do_trans)
                            if trans_s_name_dvd not in entity.tag: entity.tag.append(trans_s_name_dvd)
                    elif "メーカー" in key_dvd:
                        if entity.studio is None: 
                            makers_dvd = [mk.strip() for mk in value_node_dvd.xpath('.//a/text()') if mk.strip()]
                            m_name_dvd = None
                            if makers_dvd: m_name_dvd = makers_dvd[0]
                            elif value_text_all_dvd != '----': m_name_dvd = value_text_all_dvd
                            if m_name_dvd: entity.studio = SiteUtil.trans(m_name_dvd, do_trans=do_trans)
                    elif "レーベル" in key_dvd:
                        labels_dvd = [lb.strip() for lb in value_node_dvd.xpath('.//a/text()') if lb.strip()]
                        l_name_dvd = None
                        if labels_dvd: l_name_dvd = labels_dvd[0]
                        elif value_text_all_dvd != '----': l_name_dvd = value_text_all_dvd
                        if l_name_dvd:
                            if do_trans: entity.studio = SiteUtil.av_studio.get(l_name_dvd, SiteUtil.trans(l_name_dvd))
                            else: entity.studio = l_name_dvd
                    elif "ジャンル" in key_dvd:
                        if entity.genre is None: entity.genre = []
                        for genre_ja_tag_dvd in value_node_dvd.xpath('.//a'):
                            genre_ja_dvd = genre_ja_tag_dvd.text_content().strip()
                            if not genre_ja_dvd or "％OFF" in genre_ja_dvd or genre_ja_dvd in SiteUtil.av_genre_ignore_ja: continue
                            if genre_ja_dvd in SiteUtil.av_genre: 
                                if SiteUtil.av_genre[genre_ja_dvd] not in entity.genre: entity.genre.append(SiteUtil.av_genre[genre_ja_dvd])
                            else:
                                genre_ko_dvd = SiteUtil.trans(genre_ja_dvd, do_trans=do_trans).replace(" ", "")
                                if genre_ko_dvd not in SiteUtil.av_genre_ignore_ko and genre_ko_dvd not in entity.genre : entity.genre.append(genre_ko_dvd)

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
                    if plot_text: entity.plot = SiteUtil.trans(plot_text, do_trans=do_trans)
                else: 
                    logger.warning(f"DMM ({entity.content_type}): Plot not found for {code} using XPath: {plot_xpath_dvd_specific}")

            if not identifier_parsed:
                logger.error(f"DMM ({entity.content_type}): CRITICAL - Identifier parse failed for {code} after all attempts.")
                ui_code_for_image = code[2:].upper().replace("_","-"); entity.title=entity.originaltitle=entity.sorttitle=ui_code_for_image; entity.ui_code=ui_code_for_image
            if not entity.tagline and entity.title: entity.tagline = entity.title
            if not entity.plot and entity.tagline: entity.plot = entity.tagline
        except Exception as e_meta_dmm_main_detail_full:
            logger.exception(f"DMM ({entity.content_type}): Meta parsing error for {code}: {e_meta_dmm_main_detail_full}")
            if not ui_code_for_image: return None

        # === 3. 사용자 지정 포스터 확인 ===
        user_custom_poster_url = None; user_custom_landscape_url = None
        skip_default_poster_logic = False; skip_default_landscape_logic = False
        if use_image_server and image_server_local_path and image_server_url and ui_code_for_image:
            poster_suffixes = ["_p_user.jpg", "_p_user.png", "_p_user.webp"]
            landscape_suffixes = ["_pl_user.jpg", "_pl_user.png", "_pl_user.webp"]
            for suffix_p_dmm_user in poster_suffixes:
                _, web_url_p_dmm_user = SiteUtil.get_user_custom_image_paths(image_server_local_path, image_path_segment, ui_code_for_image, suffix_p_dmm_user, image_server_url)
                if web_url_p_dmm_user: user_custom_poster_url = web_url_p_dmm_user; entity.thumb.append(EntityThumb(aspect="poster", value=user_custom_poster_url)); skip_default_poster_logic = True; break 
            for suffix_pl_dmm_user in landscape_suffixes:
                _, web_url_pl_dmm_user = SiteUtil.get_user_custom_image_paths(image_server_local_path, image_path_segment, ui_code_for_image, suffix_pl_dmm_user, image_server_url)
                if web_url_pl_dmm_user: user_custom_landscape_url = web_url_pl_dmm_user; entity.thumb.append(EntityThumb(aspect="landscape", value=user_custom_landscape_url)); skip_default_landscape_logic = True; break

        # === 4. 이미지 정보 추출 및 처리 ===
        logger.debug(f"DMM Info: PS url from cache: {ps_url_from_search_cache}")

        now_printing_path = None
        if use_image_server and image_server_local_path:
            now_printing_path = os.path.join(image_server_local_path, "now_printing.jpg")
            if not os.path.exists(now_printing_path): now_printing_path = None

        # proxy_url은 __info의 파라미터로 이미 존재
        raw_image_urls = cls.__img_urls(tree, 
                                        content_type=entity.content_type, 
                                        now_printing_path=now_printing_path,
                                        proxy_url=proxy_url)

        pl_url = raw_image_urls.get('pl')
        specific_candidates_on_page = raw_image_urls.get('specific_poster_candidates', []) 
        other_arts_on_page = raw_image_urls.get('arts', [])

        final_poster_source = None
        final_poster_crop_mode = None
        final_landscape_source = None
        arts_urls_for_processing = [] 

        if not skip_default_landscape_logic:
            final_landscape_source = pl_url

        # --- 현재 아이템에 대한 PS 강제 사용 여부 및 크롭 모드 결정 ---
        apply_ps_to_poster_for_this_item = False
        forced_crop_mode_for_this_item = None

        if hasattr(entity, 'ui_code') and entity.ui_code:
            # 1. entity.ui_code에서 비교용 레이블 추출
            label_from_ui_code = ""
            if '-' in entity.ui_code:
                temp_label_part = entity.ui_code.split('-',1)[0]
                label_from_ui_code = temp_label_part.upper()

            if label_from_ui_code:
                # 2. PS 강제 사용 여부 결정
                if ps_to_poster_labels_str:
                    ps_force_labels_list = [x.strip().upper() for x in ps_to_poster_labels_str.split(',') if x.strip()]
                    if label_from_ui_code in ps_force_labels_list:
                        apply_ps_to_poster_for_this_item = True
                        logger.debug(f"[{cls.site_name} Info] PS to Poster WILL BE APPLIED for label '{label_from_ui_code}' based on settings.")

                # 3. 크롭 모드 결정 (PS 강제 사용이 아닐 때만 의미 있을 수 있음)
                if crop_mode_settings_str:
                    for line in crop_mode_settings_str.splitlines():
                        if not line.strip(): continue
                        parts = [x.strip() for x in line.split(":", 1)]
                        if len(parts) == 2:
                            setting_label = parts[0].upper()
                            setting_mode = parts[1].lower()
                            if setting_label == label_from_ui_code and setting_mode in ["r", "l", "c"]:
                                forced_crop_mode_for_this_item = setting_mode
                                logger.debug(f"[{cls.site_name} Info] Forced crop mode '{forced_crop_mode_for_this_item}' WILL BE APPLIED for label '{label_from_ui_code}'.")
                                break

            # 포스터 결정 로직 (if not skip_default_poster_logic: 내부)
            if not skip_default_poster_logic:
                # 1. "포스터 예외처리 2" (사용자 지정 크롭 모드)
                if forced_crop_mode_for_this_item and pl_url:
                    logger.info(f"[{cls.site_name} Info] Poster determined by FORCED 'crop_mode={forced_crop_mode_for_this_item}'. Using PL: {pl_url}")
                    final_poster_source = pl_url
                    final_poster_crop_mode = forced_crop_mode_for_this_item

                # --- 위에서 사용자 지정 크롭으로 포스터가 결정되지 *않았을* 경우에만 다음 로직 진행 ---
                if final_poster_source is None: 
                    if ps_url_from_search_cache: # PS Cache가 있는 경우
                        logger.debug(f"[{cls.site_name} Info] PS cache exists ('{ps_url_from_search_cache}'). Evaluating PS-based poster options.")

                        # 2. "포스터 예외처리 1" (PS 강제 사용)
                        if apply_ps_to_poster_for_this_item:
                            logger.info(f"[{cls.site_name} Info] Poster determined by FORCED 'ps_to_poster' setting. Using PS: {ps_url_from_search_cache}")
                            final_poster_source = ps_url_from_search_cache
                            final_poster_crop_mode = None

                        # 일반적인 포스터 결정 로직
                        else: # apply_ps_to_poster_for_this_item is False
                            logger.debug(f"[{cls.site_name} Info] Applying general poster determination with PS.")

                            # 3. is_hq_poster
                            if pl_url and SiteUtil.is_portrait_high_quality_image(pl_url, proxy_url=proxy_url):
                                if SiteUtil.is_hq_poster(ps_url_from_search_cache, pl_url, proxy_url=proxy_url):
                                    final_poster_source = pl_url
                            if final_poster_source is None and specific_candidates_on_page:
                                for art_candidate in specific_candidates_on_page:
                                    if SiteUtil.is_portrait_high_quality_image(art_candidate, proxy_url=proxy_url):
                                        if SiteUtil.is_hq_poster(ps_url_from_search_cache, art_candidate, proxy_url=proxy_url):
                                            final_poster_source = art_candidate; break

                            # 4. 특수 고정 크롭 처리 (해상도 기반) ---
                            if (final_poster_source is None or final_poster_source == ps_url_from_search_cache) and pl_url:
                                logger.debug(f"DMM Poster (Priority 3-C attempt with PS): Applying fixed-size crop logic for PL: {pl_url}")
                                try:
                                    pl_image_obj_for_fixed_crop = SiteUtil.imopen(pl_url, proxy_url=proxy_url)
                                    if pl_image_obj_for_fixed_crop:
                                        img_width, img_height = pl_image_obj_for_fixed_crop.size
                                        if img_width == 800 and 436 <= img_height <= 446:
                                            crop_box_fixed = (img_width - 380, 0, img_width, img_height) 
                                            cropped_pil_object = pl_image_obj_for_fixed_crop.crop(crop_box_fixed)
                                            if cropped_pil_object:
                                                final_poster_source = cropped_pil_object 
                                                final_poster_crop_mode = None
                                                logger.info(f"DMM: Fixed-size crop applied to PL (with PS). Poster is PIL object.")
                                except Exception as e_fixed_crop_dmm_ps:
                                    logger.error(f"DMM: Error during fixed-size crop (with PS): {e_fixed_crop_dmm_ps}")

                            # 5. has_hq_poster
                            if final_poster_source is None:
                                if pl_url:
                                    crop_pos = SiteUtil.has_hq_poster(ps_url_from_search_cache, pl_url, proxy_url=proxy_url)
                                    if crop_pos:
                                        final_poster_source = pl_url
                                        final_poster_crop_mode = crop_pos
                                if final_poster_source is None and specific_candidates_on_page:
                                    for art_candidate in specific_candidates_on_page:
                                        crop_pos_art = SiteUtil.has_hq_poster(ps_url_from_search_cache, art_candidate, proxy_url=proxy_url)
                                        if crop_pos_art:
                                            final_poster_source = art_candidate
                                            final_poster_crop_mode = crop_pos_art; break

                            # 6. PS 사용 ---
                            if final_poster_source is None: # 위 모든 PS 기반 비교 실패 시
                                logger.debug(f"DMM Poster (Priority 4 with PS - Fallback): Using PS as poster.")
                                final_poster_source = ps_url_from_search_cache
                                final_poster_crop_mode = None

                    else: # PS Cache가 없는 경우 (그리고 위에서 사용자 지정 크롭도 적용 안됨)
                        logger.warning(f"[{cls.site_name} Info] No PS url found (ps_url_from_search_cache is None). Poster cannot be determined by PS-based logic.")
                        final_poster_source = None 
                        final_poster_crop_mode = None

                # 최종 결정된 포스터 정보 로깅
                if final_poster_source:
                    logger.debug(f"[{cls.site_name} Info] Final Poster Decision - Source type: {type(final_poster_source)}, Crop: {final_poster_crop_mode}")
                    if isinstance(final_poster_source, str): logger.debug(f"  Source URL/Path: {final_poster_source[:150]}")
                else:
                    # 이 로그는 이제 PS가 없을 때, 그리고 사용자 지정 크롭도 없을 때만 발생해야 함.
                    logger.error(f"[{cls.site_name} Info] CRITICAL: No poster source could be determined for {code}")
                    final_poster_source = None # 명시적으로 None
                    final_poster_crop_mode = None

        # 팬아트 목록 결정
        arts_urls_for_processing = []

        all_potential_arts_from_page = raw_image_urls.get('arts', [])
        # logger.debug(f"DMM Info: Potential arts from __img_urls before filtering: {len(all_potential_arts_from_page)} items.")

        if all_potential_arts_from_page and max_arts > 0:
            urls_used_as_thumb = set()
            if final_landscape_source and not skip_default_landscape_logic and isinstance(final_landscape_source, str):
                urls_used_as_thumb.add(final_landscape_source)
            if final_poster_source and not skip_default_poster_logic and isinstance(final_poster_source, str):
                urls_used_as_thumb.add(final_poster_source)

            # logger.debug(f"DMM Info: URLs used as poster/landscape (to be excluded from fanart): {urls_used_as_thumb}")

            seen_for_fanart_processing = set()
            for art_url in all_potential_arts_from_page:
                if len(arts_urls_for_processing) >= max_arts:
                    #logger.debug(f"DMM Info: Reached max_arts ({max_arts}). Stopping fanart collection.")
                    break 

                if art_url and art_url not in urls_used_as_thumb and art_url not in seen_for_fanart_processing:
                    # 플레이스홀더 검사는 __img_urls에서 이미 수행되었다고 가정.
                    # 만약 이 단계에서도 플레이스홀더를 엄격히 걸러내고 싶다면,
                    # if now_printing_path and SiteUtil.are_images_visually_same(art_url, now_printing_path, proxy_url=proxy_url):
                    #     logger.debug(f"DMM Info: Skipping fanart '{art_url}' as it is a placeholder.")
                    #     continue
                    arts_urls_for_processing.append(art_url)
                    seen_for_fanart_processing.add(art_url)

            logger.debug(f"DMM Info: Final arts_urls_for_processing (count: {len(arts_urls_for_processing)}): {arts_urls_for_processing[:3]}...")
        elif max_arts == 0:
            logger.debug(f"DMM Info: max_arts is 0. No fanart will be processed.")

        logger.debug(f"DMM ({entity.content_type}): Final Images Decision - Poster='{str(final_poster_source)[:100] if final_poster_source else 'None'}' (Crop='{final_poster_crop_mode}'), Landscape='{final_landscape_source}', Fanarts_to_process({len(arts_urls_for_processing)})='{arts_urls_for_processing[:3]}...'")

        # entity.thumb 및 entity.fanart 채우기
        if not (use_image_server and image_mode == '4'):
            if final_poster_source and not skip_default_poster_logic:
                if not any(t.aspect == 'poster' for t in entity.thumb):
                    processed_poster = SiteUtil.process_image_mode(image_mode, final_poster_source, proxy_url=proxy_url, crop_mode=final_poster_crop_mode)
                    if processed_poster: entity.thumb.append(EntityThumb(aspect="poster", value=processed_poster))

            if final_landscape_source and not skip_default_landscape_logic:
                if not any(t.aspect == 'landscape' for t in entity.thumb):
                    processed_landscape = SiteUtil.process_image_mode(image_mode, final_landscape_source, proxy_url=proxy_url)
                    if processed_landscape: entity.thumb.append(EntityThumb(aspect="landscape", value=processed_landscape))

            for art_url_item in arts_urls_for_processing:
                processed_art = SiteUtil.process_image_mode(image_mode, art_url_item, proxy_url=proxy_url)
                if processed_art: entity.fanart.append(processed_art)

        elif use_image_server and image_mode == '4' and ui_code_for_image:
            if final_poster_source and not skip_default_poster_logic:
                if not any(t.aspect == 'poster' for t in entity.thumb):
                    p_path = SiteUtil.save_image_to_server_path(final_poster_source, 'p', image_server_local_path, image_path_segment, ui_code_for_image, proxy_url=proxy_url, crop_mode=final_poster_crop_mode)
                    if p_path: entity.thumb.append(EntityThumb(aspect="poster", value=f"{image_server_url}/{p_path}"))

            if final_landscape_source and not skip_default_landscape_logic:
                if not any(t.aspect == 'landscape' for t in entity.thumb):
                    pl_path = SiteUtil.save_image_to_server_path(final_landscape_source, 'pl', image_server_local_path, image_path_segment, ui_code_for_image, proxy_url=proxy_url)
                    if pl_path: entity.thumb.append(EntityThumb(aspect="landscape", value=f"{image_server_url}/{pl_path}"))

            for idx, art_url_item_server in enumerate(arts_urls_for_processing):
                art_relative_path = SiteUtil.save_image_to_server_path(art_url_item_server, 'art', image_server_local_path, image_path_segment, ui_code_for_image, art_index=idx + 1, proxy_url=proxy_url)
                if art_relative_path: entity.fanart.append(f"{image_server_url}/{art_relative_path}")

        if use_extras:
            entity.extras = []
            trailer_title_for_extra = entity.tagline if entity.tagline else entity.ui_code
            trailer_url_final = None

            try:
                cid_part = code[len(cls.module_char)+len(cls.site_char):]
                detail_url_for_referer = detail_url

                if entity.content_type == 'vr':
                    trailer_url_final, title_from_json = cls._get_dmm_video_trailer_from_args_json(cid_part, detail_url_for_referer, proxy_url, entity.content_type)
                    # title_from_json은 사용하지 않음
                    if not trailer_url_final:
                        trailer_url_final = cls._get_dmm_vr_trailer_fallback(cid_part, detail_url_for_referer, proxy_url)

                elif entity.content_type == 'videoa':
                    trailer_url_final, _ = cls._get_dmm_video_trailer_from_args_json(cid_part, detail_url_for_referer, proxy_url, entity.content_type)

                elif entity.content_type == 'dvd' or entity.content_type == 'bluray':
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
                    entity.extras.append(EntityExtra("trailer", trailer_title_for_extra, "mp4", trailer_url_final))
            
            except Exception as e_trailer_main: 
                logger.exception(f"DMM ({entity.content_type}): Main trailer processing error: {e_trailer_main}")

        logger.info(f"DMM ({entity.content_type}): __info finished for {code}. UI: {ui_code_for_image}, PSkip:{skip_default_poster_logic}, PLSkip:{skip_default_landscape_logic}, Thumbs:{len(entity.thumb)}, Fanarts:{len(entity.fanart)}")
        return entity

    @classmethod
    def info(cls, code, **kwargs):
        ret = {}; entity_result_val_final = None
        try:
            entity_result_val_final = cls.__info(code, **kwargs) 
            if entity_result_val_final: ret["ret"] = "success"; ret["data"] = entity_result_val_final.as_dict()
            else: ret["ret"] = "error"; ret["data"] = f"Failed to get DMM info for {code}"
        except Exception as e_info_dmm_main_call_val_final: ret["ret"] = "exception"; ret["data"] = str(e_info_dmm_main_call_val_final); logger.exception(f"DMM info main call error: {e_info_dmm_main_call_val_final}")
        return ret
