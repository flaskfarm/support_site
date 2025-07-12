import re
import traceback
from lxml import html
import os 
import urllib.parse as py_urllib_parse
from PIL import Image

from ..entity_av import EntityAVSearch
from ..entity_base import EntityMovie, EntityActor, EntityThumb, EntityExtra, EntityRatings
from ..setup import P, logger, path_data
from ..site_util_av import SiteUtilAv as SiteUtil

class SiteJavdb:
    site_name = 'javdb'
    site_base_url = 'https://javdb.com'
    module_char = 'C'
    site_char = 'J'

    @classmethod
    def __search(
        cls,
        keyword,
        do_trans=True,
        proxy_url=None,
        image_mode="original",
        manual=False,
        cf_clearance_cookie_value='',
        priority_label_setting_str=""
        ):

        original_keyword = keyword
        temp_keyword = original_keyword.strip().lower()
        temp_keyword = re.sub(r'[_-]?cd\d+$', '', temp_keyword, flags=re.I)
        temp_keyword = temp_keyword.strip(' _-')

        keyword_for_url = ""

        # ID 계열 패턴 우선 처리
        match_id_prefix = re.match(r'^id[-_]?(\d{2})(\d+)$', temp_keyword, re.I)
        if match_id_prefix:
            label_series = match_id_prefix.group(1) # "16"
            num_part = match_id_prefix.group(2)     # "045" 또는 "45" 등
            num_part_padded_3 = num_part.lstrip('0').zfill(3) if num_part else "000"
            keyword_for_url = f"{label_series}id-{num_part_padded_3}" # 예: "16id-045"
            label_for_compare = label_series + "id" + num_part.zfill(5) # 점수용은 DMM 스타일
        else:
            match_series_id_prefix = re.match(r'^(\d{2})id[-_]?(\d+)$', temp_keyword, re.I)
            if match_series_id_prefix:
                label_series = match_series_id_prefix.group(1) # "16"
                num_part = match_series_id_prefix.group(2)      # "045" 또는 "45" 등
                num_part_padded_3 = num_part.lstrip('0').zfill(3) if num_part else "000"
                keyword_for_url = f"{label_series}id-{num_part_padded_3}" # 예: "16id-045"
                label_for_compare = label_series + "id" + num_part.zfill(5) # 점수용
            else:
                # 일반 품번 처리
                label_part = temp_keyword.split('-')[0].upper() if '-' in temp_keyword else temp_keyword.upper()
                num_part = temp_keyword.split('-')[1] if '-' in temp_keyword else temp_keyword
                if num_part.isdigit():
                    num_part_padded_3 = num_part.lstrip('0').zfill(3) if num_part else "000"
                    num_part_padded_5 = num_part.lstrip('0').zfill(5) if num_part else "00000"
                    label_for_compare = f"{label_part}{num_part_padded_5}"
                    keyword_for_url = f"{label_part}-{num_part_padded_3}"
                else:
                    keyword_for_url = temp_keyword
                    label_for_compare = temp_keyword
        search_keyword_for_url = py_urllib_parse.quote_plus(keyword_for_url)
        search_url = f"{cls.site_base_url}/search?q={search_keyword_for_url}&f=all"

        logger.debug(f"JavDB Search: original_keyword='{original_keyword}', keyword_for_url='{keyword_for_url}', label_for_compare='{label_for_compare}'")

        custom_cookies_for_search = {'over18': '1'}
        if cf_clearance_cookie_value:
            custom_cookies_for_search['cf_clearance'] = cf_clearance_cookie_value

        res_for_search = SiteUtil.get_response_cs(search_url, proxy_url=proxy_url, cookies=custom_cookies_for_search)

        if res_for_search is None:
            logger.error(f"JavDB Search: Failed to get response from SiteUtil.get_response_cs for '{keyword_for_url}'. Proxy used: {'Yes' if proxy_url else 'No'}. Check SiteUtil logs for specific error (e.g., 403).")
            return []

        html_content_text = res_for_search.text

        if res_for_search.status_code != 200:
            logger.warning(f"JavDB Search: Status code {res_for_search.status_code} for URL: {res_for_search.url} (keyword: '{keyword_for_url}')")
            if "cf-error-details" in html_content_text or "Cloudflare to restrict access" in html_content_text:
                logger.error(f"JavDB Search: Cloudflare restriction page detected for '{keyword_for_url}' (potentially IP block or stricter rules).")
            if "Due to copyright restrictions" in html_content_text or "由於版權限制" in html_content_text:
                logger.error(f"JavDB Search: Access prohibited for '{keyword_for_url}' (country block).")
            if "cf-challenge-running" in html_content_text or "Checking if the site connection is secure" in html_content_text or "Verifying you are human" in html_content_text:
                logger.error(f"JavDB Search: Cloudflare challenge page detected for '{keyword_for_url}'. cf_clearance cookie might be invalid or missing.")
            return []

        try:
            tree = html.fromstring(html_content_text)
        except Exception as e_parse:
            logger.error(f"JavDB Search: Failed to parse HTML for '{keyword_for_url}': {e_parse}")
            logger.error(traceback.format_exc())
            return []

        if tree is None:
            logger.warning(f"JavDB Search: Tree is None after parsing for '{keyword_for_url}'.")
            return []

        final_search_results_list = []
        keyword_lower_norm = keyword_for_url.replace('-', '').replace(' ', '')
        processed_codes_in_search = set()

        item_list_xpath_expression = '//div[(contains(@class, "item-list") or contains(@class, "movie-list"))]//div[contains(@class, "item")]/a[contains(@class, "box")]'
        item_nodes = tree.xpath(item_list_xpath_expression)

        if not item_nodes: 
            no_results_message_xpath = tree.xpath('//div[contains(@class, "empty-message") and (contains(text(), "No videos found") or contains(text(), "沒有找到影片"))]')
            if no_results_message_xpath:
                logger.info(f"JavDB Search: 'No videos found' message on page for keyword '{keyword_for_url}'.")
                return []

            # --- XPath 실패 시 HTML 저장 로직 ---
            #try:
            #    safe_keyword_for_filename = keyword_for_url.replace('/', '_').replace('\\', '_').replace(':', '_').replace('*', '_').replace('?', '_').replace('"', '_').replace('<', '_').replace('>', '_').replace('|', '_')

            #    unique_suffix = os.urandom(4).hex() 

            #    debug_filename = f"javdb_xpath_fail_{safe_keyword_for_filename}_{unique_suffix}.html"
            #    debug_html_path = os.path.join(path_data, 'tmp', debug_filename)

            #    os.makedirs(os.path.join(path_data, 'debug'), exist_ok=True) 
            #    with open(debug_html_path, 'w', encoding='utf-8') as f:
            #        f.write(html_content_text)
            #    logger.info(f"JavDB Search: XPath failed. HTML content for '{keyword_for_url}' saved to: {debug_html_path}")
            #except Exception as e_save_html:
            #    logger.error(f"JavDB Search: Failed to save HTML content on XPath failure for '{keyword_for_url}': {e_save_html}")
            # --- HTML 저장 로직 끝 ---

            title_match = re.search(r'<title>(.*?)</title>', html_content_text, re.IGNORECASE | re.DOTALL)
            page_title_from_text = title_match.group(1).strip() if title_match else "N/A"
            logger.warning(f"JavDB Search: No item nodes found with XPath ('{item_list_xpath_expression}') for keyword '{keyword_for_url}'. Page title: '{page_title_from_text}'. HTML saved (if successful).")
            return []

        # --- 검색 결과 아이템 처리 루프 ---
        for node_a_tag in item_nodes[:10]:
            try:
                item = EntityAVSearch(cls.site_name)

                detail_link = node_a_tag.attrib.get('href', '').strip()
                if not detail_link or not detail_link.startswith("/v/"): 
                    logger.debug(f"JavDB Search Item: Invalid detail_link '{detail_link}'. Skipping.")
                    continue 

                item_code_match = re.search(r'/v/([^/?]+)', detail_link)
                if not item_code_match: 
                    logger.debug(f"JavDB Search Item: Could not extract item_code_raw from detail_link '{detail_link}'. Skipping.")
                    continue

                item_code_raw = item_code_match.group(1).strip()
                item.code = cls.module_char + cls.site_char + item_code_raw 

                # 중복된 item.code (모듈+사이트+ID) 방지
                if item.code in processed_codes_in_search:
                    logger.debug(f"JavDB Search Item: Duplicate item.code '{item.code}'. Skipping.")
                    continue
                processed_codes_in_search.add(item.code)

                # --- 나머지 정보 파싱 ---
                full_title_from_attr = node_a_tag.attrib.get('title', '').strip()
                video_title_node = node_a_tag.xpath('.//div[@class="video-title"]')

                visible_code_on_card = "" # 카드에 표시되는 품번 (예: "ABC-123")
                actual_title_on_card = "" # 카드에 표시되는 실제 제목

                if video_title_node:
                    strong_tag_node = video_title_node[0].xpath('./strong[1]')
                    if strong_tag_node and strong_tag_node[0].text:
                        visible_code_on_card = strong_tag_node[0].text.strip().upper()

                    temp_title_node = html.fromstring(html.tostring(video_title_node[0])) # 복사본으로 작업
                    for strong_el in temp_title_node.xpath('.//strong'): # 모든 strong 태그 제거
                        strong_el.getparent().remove(strong_el)
                    actual_title_on_card = temp_title_node.text_content().strip()

                # 제목 설정 우선순위
                if actual_title_on_card: item.title = actual_title_on_card
                elif full_title_from_attr: item.title = full_title_from_attr # a 태그의 title 속성
                elif visible_code_on_card: item.title = visible_code_on_card # 카드 품번
                else: item.title = item_code_raw.upper() # 최후에는 JavDB 내부 ID

                # ui_code는 카드에 보이는 품번 우선, 없으면 JavDB 내부 ID
                item.ui_code = visible_code_on_card if visible_code_on_card else item_code_raw.upper()
                
                # 이미지 URL
                item_img_tag_src = node_a_tag.xpath('.//div[contains(@class, "cover")]/img/@src')
                item.image_url = ""
                if item_img_tag_src:
                    img_url_raw = item_img_tag_src[0].strip()
                    if img_url_raw.startswith("//"): item.image_url = "https:" + img_url_raw
                    elif img_url_raw.startswith("http"): item.image_url = img_url_raw
                    # JavDB는 보통 // 아니면 http(s)로 시작. 상대경로 거의 없음.

                # 출시년도
                item.year = 0 # 기본값
                date_meta_text_nodes = node_a_tag.xpath('.//div[@class="meta"]/text()')
                premiered_date_str = "" # 디버깅용
                if date_meta_text_nodes:
                    for text_node_val in reversed(date_meta_text_nodes): # 뒤에서부터 찾아야 날짜일 확률 높음
                        date_str_candidate = text_node_val.strip()
                        # JavDB 날짜 형식 예: "2023-01-15", "15/01/2023" 등 다양할 수 있으므로, 연도만 정확히 추출
                        date_match_year_only = re.search(r'(\d{4})', date_str_candidate) # 4자리 숫자(연도) 찾기
                        if date_match_year_only:
                            premiered_date_str = date_str_candidate # 참고용 날짜 문자열
                            try: item.year = int(date_match_year_only.group(1))
                            except ValueError: pass
                            break # 연도 찾으면 중단

                # 번역 처리 (manual 플래그 및 do_trans에 따라)
                if manual: 
                    # image_mode는 logic_jav_censored에서 처리하므로 여기서는 원본 URL 반환
                    item.title_ko = "(현재 인터페이스에서는 번역을 제공하지 않습니다) " + item.title
                elif do_trans and item.title: 
                    item.title_ko = SiteUtil.trans(item.title, source='ja', target='ko')
                else: 
                    item.title_ko = item.title

                # --- 점수 계산 ---
                current_score_val = 0

                item_code_for_compare = ""
                if item.ui_code:
                    item_ui_code_cleaned = item.ui_code.replace("-","").lower()

                    temp_match = re.match(r'([a-z]+)(\d+)', item_ui_code_cleaned)
                    if temp_match:
                        item_code_for_compare = temp_match.group(1) + temp_match.group(2).zfill(5)
                    else:
                        item_code_for_compare = item_ui_code_cleaned

                if label_for_compare and item_code_for_compare and label_for_compare == item_code_for_compare:
                    current_score_val = 100
                elif keyword_for_url.replace("-","") == item.ui_code.lower().replace("-",""):
                    current_score_val = 100
                elif item.ui_code.lower().replace("-", "") == keyword_for_url.lower().replace("-", ""):
                    current_score_val = 100
                else:
                    current_score_val = 60
                item.score = current_score_val

                item_dict = item.as_dict()

                item_dict['is_priority_label_site'] = False 
                item_dict['site_key'] = cls.site_name 

                if item_dict.get('ui_code') and priority_label_setting_str:
                    label_to_check = ""
                    if '-' in item_dict['ui_code']:
                        label_to_check = item_dict['ui_code'].split('-', 1)[0].upper()
                    else:
                        match_label_no_hyphen = re.match(r'^([A-Z]+)', item_dict['ui_code'].upper())
                        if match_label_no_hyphen: label_to_check = match_label_no_hyphen.group(1)
                        else: label_to_check = item_dict['ui_code'].upper()

                    if label_to_check:
                        priority_labels_set = {lbl.strip().upper() for lbl in priority_label_setting_str.split(',') if lbl.strip()}
                        if label_to_check in priority_labels_set:
                            item_dict['is_priority_label_site'] = True
                            logger.debug(f"JavDB Search: Item '{item_dict['ui_code']}' matched priority label '{label_to_check}'. Setting is_priority_label_site=True.")
                
                final_search_results_list.append(item_dict)
                # logger.debug(f"  JavDB Parsed: code={item.code}, score={item.score}, title='{item.title_ko}', year={item.year}, ui_code='{item.ui_code}'")

            except Exception as e_item_parse:
                logger.error(f"JavDB Search Item (keyword: '{keyword_for_url}'): Error parsing item: {e_item_parse}")
                logger.error(traceback.format_exc())
                # 개별 아이템 파싱 실패 시 해당 아이템은 건너뛰고 계속 진행
        
        sorted_result = sorted(final_search_results_list, key=lambda k: k.get("score", 0), reverse=True)
        if sorted_result:
            log_count = min(len(sorted_result), 5)
            logger.debug(f"JavDB Search: Top {log_count} results for '{keyword_for_url}':")
            for idx, item_log_final in enumerate(sorted_result[:log_count]):
                logger.debug(f"  {idx+1}. Score={item_log_final.get('score')}, Code={item_log_final.get('code')}, UI Code={item_log_final.get('ui_code')}, Title='{item_log_final.get('title_ko')}'")
        return sorted_result


    @classmethod
    def search(cls, keyword, **kwargs):
        ret = {}
        try:
            do_trans_arg = kwargs.get('do_trans', True)
            proxy_url_arg = kwargs.get('proxy_url', None)
            image_mode_arg = kwargs.get('image_mode', 'original')
            manual_arg = kwargs.get('manual', False)
            cf_clearance_cookie_value_arg = kwargs.get('cf_clearance_cookie_value', '')
            priority_label_str_arg = kwargs.get('priority_label_setting_str', "")
            data = cls.__search(keyword,
                                do_trans=do_trans_arg,
                                proxy_url=proxy_url_arg,
                                image_mode=image_mode_arg,
                                manual=manual_arg,
                                cf_clearance_cookie_value=cf_clearance_cookie_value_arg,
                                priority_label_setting_str=priority_label_str_arg)
        except Exception as exception:
            logger.exception("검색 결과 처리 중 예외:")
            ret["ret"] = "exception"; ret["data"] = str(exception)
        else:
            ret["ret"] = "success" if data else "no_match"; ret["data"] = data
        return ret


    @classmethod
    def get_label_from_ui_code(cls, ui_code_str: str) -> str:
        if not ui_code_str or not isinstance(ui_code_str, str): 
            return ""
        ui_code_upper = ui_code_str.upper()
        if '-' in ui_code_upper:
            return ui_code_upper.split('-', 1)[0]
        else: 
            match = re.match(r'^([A-Z]+)', ui_code_upper)
            if match:
                return match.group(1)
            return ui_code_upper

    @classmethod
    def __info(cls, code, **kwargs):
        do_trans = kwargs.get('do_trans', True)
        proxy_url = kwargs.get('proxy_url', None)
        image_mode = kwargs.get('image_mode', 'original')
        max_arts = kwargs.get('max_arts', 10) 
        use_image_server = kwargs.get('use_image_server', False)
        image_server_url = kwargs.get('image_server_url', '').rstrip('/') if use_image_server else ''
        image_server_local_path = kwargs.get('image_server_local_path', '') if use_image_server else ''
        image_path_segment = kwargs.get('url_prefix_segment', 'jav/db') 
        user_defined_crop_mode = kwargs.get('crop_mode', None)
        use_extras_setting = kwargs.get('use_extras', True)
        cf_clearance_cookie_value = kwargs.get('cf_clearance_cookie', None)
        crop_mode_settings_str = kwargs.get('crop_mode_settings_str', '')
        original_keyword = kwargs.get('original_keyword', None)
        maintain_series_number_labels_str = kwargs.get('maintain_series_number_labels', '')

        custom_cookies = { 'over18': '1', 'locale': 'en' }
        if cf_clearance_cookie_value:
            custom_cookies['cf_clearance'] = cf_clearance_cookie_value

        original_code_for_url = code[len(cls.module_char) + len(cls.site_char):]
        detail_url = f"{cls.site_base_url}/v/{original_code_for_url}"
        temp_poster_file_to_clean = None  # 삭제할 임시 파일 경로를 저장할 변수

        try:
            logger.debug(f"JavDB Info: Accessing URL: {detail_url} for code {code}")
            res_info = SiteUtil.get_response_cs(detail_url, proxy_url=proxy_url, cookies=custom_cookies)

            if res_info is None or res_info.status_code != 200:
                status_code_val = res_info.status_code if res_info else "None"
                logger.warning(f"JavDB Info: Failed to get page or status not 200 for {code}. Status: {status_code_val}")
                if res_info and ("cf-error-details" in res_info.text or "Cloudflare to restrict access" in res_info.text):
                    logger.error(f"JavDB Info: Cloudflare restriction page detected for {code}.")
                return None

            html_info_text = res_info.text

            tree_info = html.fromstring(html_info_text)
            if tree_info is None:
                logger.warning(f"JavDB Info: Failed to parse detail page HTML for {code}.")
                return None

            entity = EntityMovie(cls.site_name, code)
            entity.country = ['일본'] 
            entity.mpaa = '청소년 관람불가'
            entity.thumb = []; entity.fanart = []; entity.extras = []; entity.ratings = []; entity.tag = []

            # 1. 페이지의 "ID" 필드에서 표준 ui_code 파싱
            id_panel_block = tree_info.xpath('//div[@class="panel-block" and ./strong[contains(text(),"ID:")]]/span[@class="value"]/text()')
            base_ui_code = id_panel_block[0].strip().upper() if id_panel_block else ""
            if not base_ui_code:
                h2_visible_code_node = tree_info.xpath('//h2[@class="title is-4"]/strong[1]/text()')
                if h2_visible_code_node:
                    base_ui_code = h2_visible_code_node[0].strip().upper()
            
            # --- 시리즈 넘버 유지 로직 ---
            final_ui_code = base_ui_code # 기본값
            maintain_labels_set = {label.strip().upper() for label in maintain_series_number_labels_str.split(',') if label}

            logger.debug(f"JavDB Info: final_ui_code = {final_ui_code}, original_keyword = {original_keyword}, base_ui_code = {base_ui_code}, maintain_labels_set = {maintain_labels_set}")

            if original_keyword and base_ui_code and maintain_labels_set:
                keyword_match = re.match(r'^(\d+)?([A-Z]+)-?(\d+)', original_keyword.upper())
                javdb_match = re.match(r'^([A-Z]+)-(\d+)', base_ui_code)

                logger.debug(f"JavDB Info: keyword_match = {keyword_match}, javdb_match = {javdb_match}")

                if keyword_match and javdb_match:
                    kw_prefix, kw_label, kw_num = keyword_match.groups()
                    jb_label, jb_num = javdb_match.groups()
                    
                    logger.debug(f"JavDB Info: Keyword Parts: prefix={kw_prefix}, label={kw_label}, num={kw_num}")
                    logger.debug(f"JavDB Info: JavDB Parts: label={jb_label}, num={jb_num}")

                    if (kw_prefix and 
                        kw_label == jb_label and 
                        kw_num.lstrip('0') == jb_num.lstrip('0') and 
                        jb_label in maintain_labels_set):
                        
                        final_ui_code = f"{kw_prefix}{base_ui_code}"
                        logger.debug(f"JavDB Info: Applied series number '{kw_prefix}' from keyword. New ui_code: {final_ui_code}")

            entity.ui_code = final_ui_code if final_ui_code else original_code_for_url.upper()
            entity.title = entity.originaltitle = entity.sorttitle = entity.ui_code
            current_ui_code_for_image = entity.ui_code.lower()

            if '-' in current_ui_code_for_image and current_ui_code_for_image.split('-',1)[0].upper() not in entity.tag:
                entity.tag.append(current_ui_code_for_image.split('-',1)[0].upper())

            actual_raw_title_text = ""
            h2_title_node = tree_info.xpath('//h2[@class="title is-4"]')
            if h2_title_node:
                full_h2_text = h2_title_node[0].text_content().strip()
                visible_code_in_h2 = tree_info.xpath('string(//h2[@class="title is-4"]/strong[1])').strip().upper()
                if visible_code_in_h2 and full_h2_text.startswith(visible_code_in_h2):
                    actual_raw_title_text = full_h2_text[len(visible_code_in_h2):].strip()
                else:
                    current_title_node = h2_title_node[0].xpath('./strong[@class="current-title"]/text()')
                    if current_title_node:
                        actual_raw_title_text = current_title_node[0].strip()

            if actual_raw_title_text and actual_raw_title_text != entity.ui_code:
                entity.tagline = SiteUtil.trans(actual_raw_title_text, do_trans=do_trans, source='ja', target='ko')
            else: 
                entity.tagline = entity.ui_code

            if entity.ratings is None: entity.ratings = []

            # 정보 패널 블록 전체 순회 로직
            panel_blocks_xpath = '//nav[contains(@class, "movie-panel-info")]/div[contains(@class,"panel-block")]'
            panel_blocks = tree_info.xpath(panel_blocks_xpath)

            # 키 매핑: 실제 HTML에 나타날 수 있는 모든 언어의 키를 영어 키로 매핑
            key_map = {
                '番號': 'id', 'id': 'id',
                '日期': 'released date', 'released date': 'released date',
                '時長': 'duration', 'duration': 'duration',
                '導演': 'director', 'director': 'director',
                '片商': 'maker', 'maker': 'maker',
                '發行': 'publisher', 'publisher': 'publisher',
                '系列': 'series', 'series': 'series',
                '評分': 'rating', 'rating': 'rating',
                '類別': 'tags', 'tags': 'tags',
                '演員': 'actor(s)', 'actor(s)': 'actor(s)'
            }

            for block in panel_blocks:
                strong_tag_list = block.xpath('./strong/text()')
                if not strong_tag_list: continue
                
                # HTML의 키 텍스트를 가져와서 정규화된 영어 키로 변환
                raw_key = strong_tag_list[0].strip().replace(':', '')
                key = key_map.get(raw_key, raw_key.lower()) # 매핑에 없으면 소문자로 사용

                value_node = block.xpath('./span[@class="value"]')
                if not value_node: continue
                value_node = value_node[0]

                if key == 'id':
                    # ID는 이미 위에서 처리했으므로 건너뛰기
                    continue
                elif key == 'released date':
                    entity.premiered = value_node.xpath('normalize-space()')
                    if entity.premiered:
                        try: entity.year = int(entity.premiered[:4])
                        except ValueError: logger.warning(f"JavDB Info: Year parse error from '{entity.premiered}' for code {code}")
                
                elif key == 'duration':
                    duration_text = value_node.xpath('normalize-space()')
                    duration_match = re.search(r'(\d+)', duration_text)
                    if duration_match: entity.runtime = int(duration_match.group(1))
                
                elif key == 'rating':
                    rating_text = value_node.xpath('normalize-space()')
                    # 다국어 지원 정규식 (users|人評價)
                    rating_match = re.search(r'([\d\.]+)\s*.*?,\s*.*?([\d,]+)\s*(?:users|人評價)', rating_text, re.I)
                    if rating_match:
                        try:
                            rating_val_original = float(rating_match.group(1))
                            votes_count = int(rating_match.group(2).replace(',', ''))
                            if entity.ratings is None: entity.ratings = []
                            entity.ratings.append(EntityRatings(rating_val_original, max=5, name=cls.site_name, votes=votes_count))
                        except (ValueError, IndexError):
                            logger.warning(f"JavDB Info: Could not parse rating from text: '{rating_text}' for code {code}")
                
                elif key == 'director':
                    director_text = value_node.xpath('normalize-space()')
                    if director_text.lower() not in ['n/a', '暂无', '暫無']:
                        entity.director = SiteUtil.trans(director_text, do_trans=do_trans, source='ja', target='ko')
                
                elif key in ('maker', 'publisher'):
                    studio_text = value_node.xpath('normalize-space(./a/text())') or value_node.xpath('normalize-space()')
                    if not entity.studio and studio_text.lower() not in ['n/a', '暂无', '暫無']:
                        studio_name = studio_text.split(',')[0].strip()
                        entity.studio = SiteUtil.trans(studio_name, do_trans=do_trans, source='ja', target='ko')
                
                elif key == 'series':
                    series_text = value_node.xpath('normalize-space(./a/text())') or value_node.xpath('normalize-space()')
                    if series_text.lower() not in ['n/a', '暂无', '暫無']:
                        if entity.tag is None: entity.tag = []
                        series_name = SiteUtil.trans(series_text, do_trans=do_trans, source='ja', target='ko')
                        if series_name not in entity.tag: entity.tag.append(series_name)
                
                elif key == 'tags':
                    if entity.genre is None: entity.genre = []
                    genre_tags_from_panel_links = value_node.xpath('./a/text()')
                    for genre_name_raw in genre_tags_from_panel_links:
                        genre_name = genre_name_raw.strip()
                        if genre_name:
                            # 중국어 태그도 일본어->한국어 번역기를 사용하면 대부분 잘 번역됨
                            trans_genre = SiteUtil.trans(genre_name, do_trans=do_trans, source='ja', target='ko')
                            if trans_genre not in entity.genre: entity.genre.append(trans_genre)
                
                elif key == 'actor(s)':
                    if entity.actor is None: entity.actor = []
                    actor_nodes_with_gender = value_node.xpath('./a')
                    for actor_node in actor_nodes_with_gender:
                        actor_name_tag = actor_node.xpath('./text()')
                        gender_symbol_node = actor_node.xpath('./following-sibling::strong[1][contains(@class, "symbol")]')
                        
                        if gender_symbol_node and 'female' in gender_symbol_node[0].get('class', ''):
                            if actor_name_tag:
                                actor_name_original_lang = actor_name_tag[0].strip()
                                if actor_name_original_lang and actor_name_original_lang.lower() not in ['n/a', '暂无', '暫無']:
                                    if not any(act.originalname == actor_name_original_lang for act in entity.actor):
                                        # 배우 이름도 번역
                                        actor_entity = EntityActor(SiteUtil.trans(actor_name_original_lang, do_trans=do_trans, source='ja', target='ko'))
                                        actor_entity.originalname = actor_name_original_lang
                                        entity.actor.append(actor_entity)

            if not entity.plot:
                if entity.tagline and entity.tagline != entity.ui_code:
                    entity.plot = entity.tagline

            # === "포스터 예외처리 2 (크롭 모드)"를 위한 레이블 기반 forced_crop_mode_for_this_item 결정 ===
            forced_crop_mode_for_this_item = None
            if hasattr(entity, 'ui_code') and entity.ui_code and crop_mode_settings_str:
                label_from_ui_code_for_settings = cls.get_label_from_ui_code(entity.ui_code)
                if label_from_ui_code_for_settings:
                    for line in crop_mode_settings_str.splitlines():
                        if not line.strip(): continue
                        parts = [x.strip() for x in line.split(":", 1)]
                        if len(parts) == 2 and parts[0].upper() == label_from_ui_code_for_settings and parts[1].lower() in ["r", "l", "c"]:
                            forced_crop_mode_for_this_item = parts[1].lower()
                            logger.debug(f"[{cls.site_name} Info] 레이블 기반 강제 크롭 모드 '{forced_crop_mode_for_this_item}' 적용 for ui_code '{entity.ui_code}'")
                            break 

            # === 사용자 지정 이미지 로드 ===
            skip_default_poster_logic = False
            skip_default_landscape_logic = False
            if use_image_server and image_server_local_path and image_server_url and current_ui_code_for_image:
                poster_suffixes = ["_p_user.jpg", "_p_user.png", "_p_user.webp"]
                landscape_suffixes = ["_pl_user.jpg", "_pl_user.png", "_pl_user.webp"]
                for suffix in poster_suffixes:
                    _, web_url = SiteUtil.get_user_custom_image_paths(image_server_local_path, image_path_segment, current_ui_code_for_image, suffix, image_server_url)
                    if web_url: 
                        if not any(t.aspect == 'poster' and t.value == web_url for t in entity.thumb):
                            entity.thumb.append(EntityThumb(aspect="poster", value=web_url))
                        skip_default_poster_logic = True; logger.info(f"JavDB Info: Using user custom poster: {web_url}"); break 
                for suffix in landscape_suffixes:
                    _, web_url = SiteUtil.get_user_custom_image_paths(image_server_local_path, image_path_segment, current_ui_code_for_image, suffix, image_server_url)
                    if web_url: 
                        if not any(t.aspect == 'landscape' and t.value == web_url for t in entity.thumb):
                            entity.thumb.append(EntityThumb(aspect="landscape", value=web_url))
                        skip_default_landscape_logic = True; logger.info(f"JavDB Info: Using user custom landscape: {web_url}"); break

            # === 기본 이미지 처리 시작 ===
            final_poster_source = None 
            final_poster_crop_mode = None 
            final_landscape_source = None

            # 1. 이미지 URL 추출 (PL, Arts)
            pl_url = None
            main_cover_img_src_nodes = tree_info.xpath('//div[@class="column column-video-cover"]//img[@class="video-cover"]/@src')
            if main_cover_img_src_nodes:
                pl_url_raw = main_cover_img_src_nodes[0].strip()
                if pl_url_raw.startswith("//"): pl_url = "https:" + pl_url_raw
                elif not pl_url_raw.startswith("http"): 
                    if pl_url_raw.startswith("/"): pl_url = py_urllib_parse.urljoin(cls.site_base_url, pl_url_raw)
                    else: logger.warning(f"JavDB Info: Unexpected PL image src format: {pl_url_raw}")
                else: pl_url = pl_url_raw
            else:
                main_cover_a_href_nodes = tree_info.xpath('//div[@class="column column-video-cover"]/a[@data-fancybox="gallery"]/@href')
                if main_cover_a_href_nodes:
                    pl_url_raw_href = main_cover_a_href_nodes[0].strip()
                    if pl_url_raw_href and not pl_url_raw_href.startswith("/v/"): 
                        if pl_url_raw_href.startswith("//"): pl_url = "https:" + pl_url_raw_href
                        elif not pl_url_raw_href.startswith("http"):
                            if pl_url_raw_href.startswith("/"): pl_url = py_urllib_parse.urljoin(cls.site_base_url, pl_url_raw_href)
                            else: logger.warning(f"JavDB Info: Unexpected PL a/@href format: {pl_url_raw_href}")
                        else: pl_url = pl_url_raw_href
            logger.debug(f"JavDB Info: Determined pl_url = '{pl_url}' after parsing page.")

            arts_urls = [] 
            sample_image_container = tree_info.xpath('//div[contains(@class, "preview-images")]')
            if sample_image_container:
                sample_image_nodes_info = sample_image_container[0].xpath('./a[@class="tile-item"]/@href')
                for art_link_raw in sample_image_nodes_info:
                    art_full_url_raw = art_link_raw.strip()
                    art_full_url = None
                    if art_full_url_raw:
                        if art_full_url_raw.startswith("//"): art_full_url = "https:" + art_full_url_raw
                        elif not art_full_url_raw.startswith("http"):
                            if art_full_url_raw.startswith("/"): art_full_url = py_urllib_parse.urljoin(cls.site_base_url, art_full_url_raw)
                            else: logger.warning(f"JavDB Info: Unexpected art_link_raw format: {art_full_url_raw}"); continue
                        else: art_full_url = art_full_url_raw
                    if art_full_url: arts_urls.append(art_full_url)
            logger.debug(f"JavDB Info: Collected {len(arts_urls)} arts_urls: {arts_urls[:5]}")

            # 2. VR 작품 여부 판단
            is_vr_content = False
            title_to_check_for_vr = entity.tagline if entity.tagline and entity.tagline != entity.ui_code else actual_raw_title_text
            if title_to_check_for_vr:
                normalized_title_for_vr_check = title_to_check_for_vr.upper()
                if normalized_title_for_vr_check.startswith("[VR]") or normalized_title_for_vr_check.startswith("【VR】"):
                    is_vr_content = True
            # logger.debug(f"JavDB Info: Is VR content? {is_vr_content} (Checked title: '{title_to_check_for_vr}')")

            # 3. 유효한 PL URL 확정 (플레이스홀더 검사)
            valid_pl_url = None
            if pl_url:
                is_placeholder = False
                if use_image_server and image_server_local_path:
                    placeholder_path = os.path.join(image_server_local_path, 'javdb_no_img.jpg')
                    if os.path.exists(placeholder_path):
                        if SiteUtil.are_images_visually_same(pl_url, placeholder_path, proxy_url=proxy_url):
                            is_placeholder = True
                            logger.info(f"JavDB Info: PL URL ('{pl_url}') is a placeholder (javdb_no_img.jpg).")
                if not is_placeholder:
                    valid_pl_url = pl_url

            if not valid_pl_url and not skip_default_poster_logic:
                logger.warning(f"JavDB Info: No valid PL URL for {code} for default poster generation.")

            # 4. 포스터 및 랜드스케이프 결정
            if valid_pl_url: # 유효한 PL이 있을 때만 기본 포스터/랜드스케이프 로직 진행
                # --- 포스터 결정 ---
                if not skip_default_poster_logic:
                    temp_poster_source = None
                    temp_crop_mode = None

                    effective_crop_mode_to_try = forced_crop_mode_for_this_item if forced_crop_mode_for_this_item else user_defined_crop_mode
                    if effective_crop_mode_to_try:
                        temp_poster_source = valid_pl_url
                        temp_crop_mode = effective_crop_mode_to_try
                        logger.debug(f"JavDB Poster (Prio 1): Effective crop_mode '{temp_crop_mode}' with PL '{valid_pl_url}'.")

                    # 1. PL이 세로형 고품질 이미지일 경우
                    if temp_poster_source is None:
                        is_pl_suitable_as_poster = False
                        try:
                            pl_image_obj = SiteUtil.imopen(valid_pl_url, proxy_url=proxy_url)
                            if pl_image_obj:
                                pl_width, pl_height = pl_image_obj.size
                                if pl_width > 0 and pl_height > 0:
                                    if pl_height >= pl_width and pl_width >= 300:
                                        is_pl_suitable_as_poster = True
                                        logger.info(f"JavDB Poster (Prio 0 - New): PL is suitable as portrait poster (W:{pl_width}, H:{pl_height}). Using PL: {valid_pl_url}")
                            if pl_image_obj: pl_image_obj.close()
                        except Exception as e_pl_check:
                            logger.warning(f"JavDB Poster (Prio 0 - New): Error checking PL suitability: {e_pl_check}")

                        if is_pl_suitable_as_poster:
                            temp_poster_source = valid_pl_url
                            temp_crop_mode = None

                    # 2. 세로 포스터 우선(VR / ART)
                    if temp_poster_source is None and is_vr_content and arts_urls:
                        first_art_url = arts_urls[0]
                        if SiteUtil.is_portrait_high_quality_image(first_art_url, proxy_url=proxy_url, min_height=600, aspect_ratio_threshold=1.2):
                            temp_poster_source = first_art_url
                            temp_crop_mode = None 
                            logger.info(f"JavDB Poster (Prio 2): VR content, using first art '{first_art_url}'.")

                    # 3. 특수 고정 크기 크롭 (해상도 기반: blue-ray 포스터)
                    if temp_poster_source is None:
                        try:
                            pl_image_obj_for_fixed_crop = SiteUtil.imopen(valid_pl_url, proxy_url=proxy_url)
                            if pl_image_obj_for_fixed_crop:
                                img_width, img_height = pl_image_obj_for_fixed_crop.size
                                if img_width == 800 and 436 <= img_height <= 446:
                                    crop_box_fixed = (img_width - 380, 0, img_width, img_height) 
                                    cropped_pil_object = pl_image_obj_for_fixed_crop.crop(crop_box_fixed)
                                    if cropped_pil_object:
                                        # PIL 객체를 임시 파일로 저장하고 그 경로를 사용
                                        temp_filename = f"javdb_fixed_crop_{current_ui_code_for_image.replace('/','_')}_{os.urandom(4).hex()}.jpg"
                                        temp_filepath = os.path.join(path_data, "tmp", temp_filename)
                                        os.makedirs(os.path.join(path_data, "tmp"), exist_ok=True)
                                        
                                        img_to_save = cropped_pil_object
                                        if img_to_save.mode not in ('RGB', 'L'):
                                            img_to_save = img_to_save.convert('RGB')
                                        
                                        img_to_save.save(temp_filepath, format="JPEG", quality=95)
                                        
                                        temp_poster_source = temp_filepath
                                        temp_poster_file_to_clean = temp_filepath # 삭제를 위해 경로 저장
                                        temp_crop_mode = None # 이미 잘랐으므로 추가 크롭 없음
                                        logger.info(f"JavDB Poster (Prio 3): Fixed-size crop applied. Using temp file: {temp_filepath}")
                                    cropped_pil_object.close()
                                pl_image_obj_for_fixed_crop.close()
                        except Exception as e_fixed_crop:
                            logger.warning(f"JavDB Info: Error during fixed-size crop: {e_fixed_crop}")

                    # 4. 가로로 더 긴 이미지 처리(2:1 비율)
                    if temp_poster_source is None:
                        log_id = entity.ui_code or original_code_for_url
                        try:
                            processed_source, rec_crop, _ = SiteUtil.get_javdb_poster_from_pl_local(valid_pl_url, log_id, proxy_url=proxy_url)
                            if processed_source:
                                temp_poster_source = processed_source
                                temp_crop_mode = rec_crop
                                # 반환값이 임시 파일 경로인지 확인하고, 그렇다면 삭제 리스트에 추가
                                if isinstance(processed_source, str) and os.path.basename(processed_source).startswith("javdb_temp_poster_"):
                                    temp_poster_file_to_clean = processed_source
                                logger.info(f"JavDB Poster (Prio 4): JavDB-style. Source: '{temp_poster_source}', Crop: {temp_crop_mode}")
                        except Exception: pass

                    # 5. 일반 처리(crop: r)
                    if temp_poster_source is None: 
                        temp_poster_source = valid_pl_url
                        temp_crop_mode = 'r'
                        logger.debug(f"JavDB Poster (Prio 5 - Fallback): Default right-crop to PL: {valid_pl_url}")

                    final_poster_source = temp_poster_source
                    final_poster_crop_mode = temp_crop_mode

                # 4-B. 랜드스케이프 결정
                if not skip_default_landscape_logic:
                    final_landscape_source = valid_pl_url

            else: # valid_pl_url이 없는 경우
                if not skip_default_poster_logic: 
                    logger.warning(f"JavDB Info: Default poster cannot be generated as no valid PL URL.")
                if not skip_default_landscape_logic:
                    logger.warning(f"JavDB Info: Default landscape cannot be generated as no valid PL URL.")

            # === 이미지 최종 적용 (서버 저장 또는 프록시) ===
            if not (use_image_server and image_mode == 'image_server'):
                # 프록시 모드
                if not skip_default_poster_logic and final_poster_source:
                    if not any(t.aspect == 'poster' for t in entity.thumb):
                        processed_poster = SiteUtil.process_image_mode(image_mode, final_poster_source, proxy_url=proxy_url, crop_mode=final_poster_crop_mode)
                        if processed_poster:
                            entity.thumb.append(EntityThumb(aspect="poster", value=processed_poster))

                if not skip_default_landscape_logic and final_landscape_source:
                    if not any(t.aspect == 'landscape' for t in entity.thumb):
                        processed_landscape = SiteUtil.process_image_mode(image_mode, final_landscape_source, proxy_url=proxy_url)
                        if processed_landscape:
                            entity.thumb.append(EntityThumb(aspect="landscape", value=processed_landscape))

                if arts_urls:
                    if entity.fanart is None: entity.fanart = []
                    unique_arts_for_fanart = []
                    vr_poster_override_url_proxy = None
                    if is_vr_content and isinstance(final_poster_source, str) and final_poster_source in arts_urls and final_poster_crop_mode is None:
                        vr_poster_override_url_proxy = final_poster_source

                    for art_url_item in arts_urls: 
                        if not (vr_poster_override_url_proxy and art_url_item == vr_poster_override_url_proxy):
                            if art_url_item not in unique_arts_for_fanart:
                                unique_arts_for_fanart.append(art_url_item)

                    for art_url_item in unique_arts_for_fanart:
                        if len(entity.fanart) >= max_arts: break
                        processed_art = SiteUtil.process_image_mode(image_mode, art_url_item, proxy_url=proxy_url)
                        if processed_art and processed_art not in entity.fanart:
                            entity.fanart.append(processed_art)
                            
            elif use_image_server and image_mode == 'image_server' and current_ui_code_for_image: 
                # 이미지 서버 모드
                if final_poster_source and not skip_default_poster_logic:
                    if not any(t.aspect == 'poster' for t in entity.thumb):
                        p_path = SiteUtil.save_image_to_server_path(final_poster_source, 'p', image_server_local_path, image_path_segment, current_ui_code_for_image, proxy_url=proxy_url, crop_mode=final_poster_crop_mode)
                        if p_path: entity.thumb.append(EntityThumb(aspect="poster", value=f"{image_server_url}/{p_path}"))

                if final_landscape_source and not skip_default_landscape_logic:
                    if not any(t.aspect == 'landscape' for t in entity.thumb):
                        pl_path = SiteUtil.save_image_to_server_path(final_landscape_source, 'pl', image_server_local_path, image_path_segment, current_ui_code_for_image, proxy_url=proxy_url)
                        if pl_path: entity.thumb.append(EntityThumb(aspect="landscape", value=f"{image_server_url}/{pl_path}"))

                if arts_urls: # 팬아트 처리
                    if entity.fanart is None: entity.fanart = []
                    unique_arts_for_fanart_server = []
                    # VR 포스터로 사용된 첫 번째 Art는 팬아트에서 제외
                    vr_poster_override_url = None
                    if is_vr_content and isinstance(final_poster_source, str) and final_poster_source in arts_urls and final_poster_crop_mode is None:
                        vr_poster_override_url = final_poster_source

                    for art_url_item_s in arts_urls: 
                        if not (vr_poster_override_url and art_url_item_s == vr_poster_override_url):
                            if art_url_item_s not in unique_arts_for_fanart_server: unique_arts_for_fanart_server.append(art_url_item_s)

                    current_fanart_server_count = len([fa_url for fa_url in entity.fanart if isinstance(fa_url, str) and fa_url.startswith(image_server_url)])
                    for idx, art_url_item_server in enumerate(unique_arts_for_fanart_server):
                        if current_fanart_server_count >= max_arts : break
                        art_relative_path = SiteUtil.save_image_to_server_path(art_url_item_server, 'art', image_server_local_path, image_path_segment, current_ui_code_for_image, art_index=idx + 1, proxy_url=proxy_url)
                        if art_relative_path: 
                            full_art_url = f"{image_server_url}/{art_relative_path}"
                            if full_art_url not in entity.fanart: entity.fanart.append(full_art_url); current_fanart_server_count += 1
            
            # === 7. 트레일러 처리 ===
            if use_extras_setting:
                entity.extras = []
                trailer_title_to_use = entity.tagline if entity.tagline else entity.ui_code
                if not trailer_title_to_use : trailer_title_to_use = code

                trailer_source_tag = tree_info.xpath('//video[@id="preview-video"]/source/@src')
                if trailer_source_tag:
                    trailer_url_raw = trailer_source_tag[0].strip()
                    if trailer_url_raw:
                        trailer_url_final = trailer_url_raw
                        if trailer_url_raw.startswith("//"): trailer_url_final = "https:" + trailer_url_raw
                        elif not trailer_url_raw.startswith(("http:", "https:")): 
                            if trailer_url_raw.startswith("/"): trailer_url_final = py_urllib_parse.urljoin(cls.site_base_url, trailer_url_raw)
                            else: trailer_url_final = "https:" + trailer_url_raw
                        entity.extras.append(EntityExtra("trailer", trailer_title_to_use, "mp4", trailer_url_final))

            entity.code = cls.module_char + cls.site_char + original_code_for_url

            logger.info(f"JavDB Info Parsed: final_code='{entity.code}', ui_code='{entity.ui_code}', Thumbs: {len(entity.thumb)}, Fanarts: {len(entity.fanart)}, Extras: {len(entity.extras)}")
            return entity

        except Exception as e_main_info:
            logger.exception(f"JavDB __info Exception for input code {code}: {e_main_info}")
            return None
        finally:
            if 'temp_poster_file_to_clean' in locals() and temp_poster_file_to_clean and os.path.exists(temp_poster_file_to_clean):
                try:
                    os.remove(temp_poster_file_to_clean)
                    logger.debug(f"JavDB __info: Cleaned up temp poster file: {temp_poster_file_to_clean}")
                except Exception as e_remove_exc:
                    logger.error(f"JavDB __info: Failed to remove temp poster on exception: {e_remove_exc}")


    @classmethod
    def info(cls, code, **kwargs):
        ret = {}
        try:
            entity_obj = cls.__info(code, **kwargs)
            
            if entity_obj:
                if hasattr(entity_obj, 'ui_code') and entity_obj.ui_code:
                    try: 
                        logger.debug(f"JavDB Info: Attempting Shiroutoname correction for {entity_obj.ui_code}")
                        entity_obj = SiteUtil.shiroutoname_info(entity_obj) 
                    except Exception as e_shirouto: 
                        logger.exception(f"JavDB Info: Shiroutoname correction error for {entity_obj.ui_code}: {e_shirouto}")

                ret["ret"] = "success"
                ret["data"] = entity_obj.as_dict()
            else:
                ret["ret"] = "error"
                ret["data"] = f"Failed to get JavDB info for {code} (__info returned None)."
        except Exception as e:
            ret["ret"] = "exception"
            ret["data"] = str(e)
            logger.exception(f"JavDB info (outer) error for code {code}: {e}")
        return ret
