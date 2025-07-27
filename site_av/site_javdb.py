import re, time
import traceback
from lxml import html
import os 
import urllib.parse as py_urllib_parse
from PIL import Image

from ..entity_av import EntityAVSearch
from ..entity_base import EntityMovie, EntityActor, EntityThumb, EntityExtra, EntityRatings
from ..setup import P, logger, path_data
from .site_av_base import SiteAvBase

SITE_BASE_URL = 'https://javdb.com'

class SiteJavdb(SiteAvBase):
    site_name = 'javdb'
    site_char = 'J'
    module_char = 'C'
    default_headers = SiteAvBase.base_default_headers.copy()
    
    ################################################
    # region SEARCH

    @classmethod
    def search(cls, keyword, do_trans, manual):
        ret = {}
        try:
            data = cls.__search(keyword, do_trans=do_trans, manual=manual)
        except Exception as exception:
            logger.exception("검색 결과 처리 중 예외:")
            ret["ret"] = "exception"; ret["data"] = str(exception)
        else:
            ret["ret"] = "success" if data else "no_match"; ret["data"] = data
        return ret


    @classmethod
    def __search(cls, keyword, do_trans, manual):
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
        search_url = f"{SITE_BASE_URL}/search?q={search_keyword_for_url}&f=all"

        logger.debug(f"JavDB Search: original_keyword='{original_keyword}', keyword_for_url='{keyword_for_url}', label_for_compare='{label_for_compare}'")

        custom_cookies_for_search = {'over18': '1'}
        res_for_search = cls.get_response_cs(search_url, cookies=custom_cookies_for_search)

        if res_for_search is None:
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
                            premiered_date_str = str(date_str_candidate) # 참고용 날짜 문자열
                            try: item.year = int(date_match_year_only.group(1))
                            except ValueError: pass
                            break # 연도 찾으면 중단

                # 번역 처리 (manual 플래그 및 do_trans에 따라)
                if manual: 
                    if cls.config['use_proxy']:
                        item.image_url = cls.make_image_url(item.image_url)
                    item.title_ko = "(현재 인터페이스에서는 번역을 제공하지 않습니다) " + item.title
                elif do_trans and item.title: 
                    item.title_ko = cls.trans(item.title)
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
    
    # endregion SEARCH
    ################################################


    ################################################
    # region INFO
    
    @classmethod
    def info(cls, code):
        ret = {}
        try:
            entity_obj = cls.__info(code)
            
            if entity_obj:
                if hasattr(entity_obj, 'ui_code') and entity_obj.ui_code:
                    try: 
                        logger.debug(f"JavDB Info: Attempting Shiroutoname correction for {entity_obj.ui_code}")
                        entity_obj = cls.shiroutoname_info(entity_obj) 
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
    

    @classmethod
    def __info(cls, code):
       
        original_keyword = ''

        custom_cookies = { 'over18': '1', 'locale': 'en' }
        custom_cookies['cf_clearance'] = ''

        original_code_for_url = code[len(cls.module_char) + len(cls.site_char):]
        detail_url = f"{SITE_BASE_URL}/v/{original_code_for_url}"
        temp_poster_file_to_clean = None

        try:
            logger.debug(f"JavDB Info: Accessing URL: {detail_url} for code {code}")
            res_info = cls.get_response_cs(detail_url,  cookies=custom_cookies)

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
            entity.country = ['일본']; entity.mpaa = '청소년 관람불가'
            entity.thumb = []; entity.fanart = []; entity.extras = []; entity.ratings = []; entity.tag = []

            # === 2. 메타데이터 파싱 ===
            id_panel_block = tree_info.xpath('//div[@class="panel-block" and ./strong[contains(text(),"ID:")]]/span[@class="value"]/text()')
            base_ui_code = id_panel_block[0].strip().upper() if id_panel_block else ""
            if not base_ui_code:
                h2_visible_code_node = tree_info.xpath('//h2[@class="title is-4"]/strong[1]/text()')
                if h2_visible_code_node:
                    base_ui_code = h2_visible_code_node[0].strip().upper()
            
            final_ui_code = base_ui_code

            if original_keyword and base_ui_code and cls.config['maintain_series_number_labels']:
                keyword_match = re.match(r'^(\d+)?([A-Z]+)-?(\d+)', original_keyword.upper())
                javdb_match = re.match(r'^([A-Z]+)-(\d+)', base_ui_code)
                if keyword_match and javdb_match:
                    kw_prefix, kw_label, kw_num = keyword_match.groups()
                    jb_label, jb_num = javdb_match.groups()
                    if (kw_prefix and kw_label == jb_label and kw_num.lstrip('0') == jb_num.lstrip('0') and jb_label in cls.config['maintain_series_number_labels']):
                        final_ui_code = f"{kw_prefix}{base_ui_code}"

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
                entity.tagline = cls.trans(actual_raw_title_text)
            else: 
                entity.tagline = entity.ui_code

            key_map = {
                '番號': 'id', 'id': 'id', '日期': 'released date', 'released date': 'released date', '時長': 'duration', 
                'duration': 'duration', '導演': 'director', 'director': 'director', '片商': 'maker', 'maker': 'maker', 
                '發行': 'publisher', 'publisher': 'publisher', '系列': 'series', 'series': 'series', '評分': 'rating', 
                'rating': 'rating', '類別': 'tags', 'tags': 'tags', '演員': 'actor(s)', 'actor(s)': 'actor(s)'
            }
            panel_blocks = tree_info.xpath('//nav[contains(@class, "movie-panel-info")]/div[contains(@class,"panel-block")]')
            for block in panel_blocks:
                strong_tag_list = block.xpath('./strong/text()')
                if not strong_tag_list: continue
                raw_key = strong_tag_list[0].strip().replace(':', '')
                key = key_map.get(raw_key, raw_key.lower())
                value_node = block.xpath('./span[@class="value"]')
                if not value_node: continue
                value_node = value_node[0]

                if key == 'released date':
                    entity.premiered = value_node.xpath('normalize-space()')
                    if entity.premiered:
                        try: entity.year = int(entity.premiered[:4])
                        except ValueError: pass
                elif key == 'duration':
                    duration_match = re.search(r'(\d+)', value_node.xpath('normalize-space()'))
                    if duration_match: entity.runtime = int(duration_match.group(1))
                elif key == 'rating':
                    rating_match = re.search(r'([\d\.]+)\s*.*?,\s*.*?([\d,]+)\s*(?:users|人評價)', value_node.xpath('normalize-space()'), re.I)
                    if rating_match:
                        try:
                            entity.ratings.append(EntityRatings(float(rating_match.group(1)), max=5, name=cls.site_name, votes=int(rating_match.group(2).replace(',', ''))))
                        except (ValueError, IndexError): pass
                elif key == 'director':
                    director_text = value_node.xpath('normalize-space()')
                    if director_text.lower() not in ['n/a', '暂无', '暫無']: entity.director = cls.trans(director_text)
                elif key in ('maker', 'publisher'):
                    studio_text = value_node.xpath('normalize-space(./a/text())') or value_node.xpath('normalize-space()')
                    if not entity.studio and studio_text.lower() not in ['n/a', '暂无', '暫無']:
                        entity.studio = cls.trans(studio_text.split(',')[0].strip())
                elif key == 'series':
                    series_text = value_node.xpath('normalize-space(./a/text())') or value_node.xpath('normalize-space()')
                    if series_text.lower() not in ['n/a', '暂无', '暫無']:
                        series_name = cls.trans(series_text)
                        if series_name not in (entity.tag or []):
                            if entity.tag is None: entity.tag = []
                            entity.tag.append(series_name)
                elif key == 'tags':
                    if entity.genre is None: entity.genre = []
                    for genre_name_raw in value_node.xpath('./a/text()'):
                        genre_name = genre_name_raw.strip()
                        if genre_name:
                            trans_genre = cls.trans(genre_name)
                            if trans_genre not in entity.genre: 
                                entity.genre.append(trans_genre)
                elif key == 'actor(s)':
                    if entity.actor is None: entity.actor = []
                    for actor_node in value_node.xpath('./a'):
                        if 'female' in (actor_node.xpath('./following-sibling::strong[1]/@class') or [''])[0]:
                            actor_name = actor_node.xpath('string()').strip()
                            if actor_name and actor_name.lower() not in ['n/a', '暂无', '暫無'] and not any(act.originalname == actor_name for act in entity.actor):
                                actor_entity = EntityActor(cls.trans(actor_name))
                                actor_entity.originalname = actor_name
                                entity.actor.append(actor_entity)

            if not entity.plot and entity.tagline and entity.tagline != entity.ui_code:
                entity.plot = entity.tagline

            # === 3. 이미지 소스 결정 및 관계 처리 ===
            
            pl_url = None
            main_cover_img_src_nodes = tree_info.xpath('//div[@class="column column-video-cover"]//img[@class="video-cover"]/@src')
            if main_cover_img_src_nodes:
                pl_url_raw = main_cover_img_src_nodes[0].strip()
                if pl_url_raw.startswith("//"): pl_url = "https:" + pl_url_raw
                else: pl_url = pl_url_raw

            arts_urls = [] 
            sample_image_container = tree_info.xpath('//div[contains(@class, "preview-images")]')
            if sample_image_container:
                for art_link_raw in sample_image_container[0].xpath('./a[@class="tile-item"]/@href'):
                    art_full_url_raw = art_link_raw.strip()
                    if art_full_url_raw:
                        if art_full_url_raw.startswith("//"): arts_urls.append("https:" + art_full_url_raw)
                        else: arts_urls.append(art_full_url_raw)

            valid_pl_url = pl_url
            
            final_image_sources = {
                'poster_source': None,
                'poster_mode': None,
                'landscape_source': None,
                'arts': [],
            }

            if valid_pl_url:
                final_image_sources['landscape_source'] = valid_pl_url

                forced_crop_mode_for_this_item = None
                if hasattr(entity, 'ui_code') and entity.ui_code:
                    label_from_ui_code_for_settings = cls.get_label_from_ui_code(entity.ui_code)
                    if label_from_ui_code_for_settings:
                        for line in cls.config['crop_mode']:
                            parts = [x.strip() for x in line.split(":", 1)]
                            if len(parts) == 2 and parts[0].upper() == label_from_ui_code_for_settings and parts[1].lower() in ["r", "l", "c"]:
                                forced_crop_mode_for_this_item = parts[1].lower()
                                break

                is_vr_content = (entity.tagline or "").upper().startswith(("[VR]", "【VR】"))

                effective_crop_mode_to_try = forced_crop_mode_for_this_item
                if effective_crop_mode_to_try:
                    final_image_sources['poster_source'] = valid_pl_url
                    final_image_sources['poster_mode'] = f"crop_{effective_crop_mode_to_try}"
                    
                elif cls.is_portrait_high_quality_image(valid_pl_url):
                    final_image_sources['poster_source'] = valid_pl_url
                elif is_vr_content and arts_urls and cls.is_portrait_high_quality_image(arts_urls[0]):
                    final_image_sources['poster_source'] = arts_urls[0]
                else:
                    processed_source, rec_crop, _ = cls.get_javdb_poster_from_pl_local(valid_pl_url, entity.ui_code)
                    if processed_source:
                        final_image_sources['poster_source'] = valid_pl_url
                        final_image_sources['poster_mode'] = f"crop_{rec_crop}"
                        if isinstance(processed_source, str) and os.path.basename(processed_source).startswith("javdb_temp_poster_"):
                            temp_poster_file_to_clean = processed_source

            if arts_urls and cls.config['max_arts'] > 0:
                used_for_thumb = set()
                if final_image_sources['landscape_source']: 
                    used_for_thumb.add(final_image_sources['landscape_source'])
                if final_image_sources['poster_source'] and isinstance(final_image_sources['poster_source'], str) and final_image_sources['poster_source'].startswith("http"):
                    used_for_thumb.add(final_image_sources['poster_source'])
                final_image_sources['arts'] = [art for art in arts_urls if art and art not in used_for_thumb][:cls.config['max_arts']]

            # === 4. 최종 후처리 위임 ===
            cls.finalize_images_for_entity(entity, final_image_sources)

            # === 5. 예고편 및 Shiroutoname 보정 처리 ===
            if cls.config['use_extras']:
                trailer_source_tag = tree_info.xpath('//video[@id="preview-video"]/source/@src')
                if trailer_source_tag:
                    trailer_url_raw = trailer_source_tag[0].strip()
                    if trailer_url_raw:
                        trailer_url_final = "https:" + trailer_url_raw if trailer_url_raw.startswith("//") else trailer_url_raw
                        trailer_url_final = cls.make_video_url(trailer_url_final)
                        entity.extras.append(EntityExtra("trailer", entity.tagline or entity.ui_code, "mp4", trailer_url_final))

            if entity.originaltitle:
                try: entity = cls.shiroutoname_info(entity)
                except Exception as e_shirouto: logger.exception(f"JavDB Info: Shiroutoname correction error for {entity.originaltitle}: {e_shirouto}")

            logger.info(f"JavDB: __info finished for {code}. UI Code: {entity.ui_code}")
            return entity

        finally:
            # === 6. 임시 파일 정리 ===
            if temp_poster_file_to_clean and os.path.exists(temp_poster_file_to_clean):
                try:
                    os.remove(temp_poster_file_to_clean)
                    logger.debug(f"JavDB: Cleaned up temp poster file: {temp_poster_file_to_clean}")
                except Exception as e_remove:
                    logger.error(f"JavDB: Failed to remove temp poster file: {e_remove}")

    # endregion INFO
    ################################################
    
    
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
    def get_javdb_poster_from_pl_local(cls, pl_url: str, original_code_for_log: str = "unknown", proxy_url: str = None):
        """
        JavDB용으로 PL 이미지를 특별 처리하여 포스터로 사용할 임시 파일 경로와 추천 crop_mode를 반환합니다.
        - PL 이미지의 aspect ratio를 확인합니다.
        - 1.8 이상 (가로로 매우 김): 오른쪽 절반을 잘라 임시 파일로 저장하고, 추천 crop_mode는 'c' (센터).
        - 1.8 미만 (일반 가로): 이 경우에는 이미지 처리를 하지 않고, 원본 URL과 crop 'r'을 반환합니다.
        - 성공 시 (임시 파일 경로 또는 원본 URL, 추천 crop_mode, 원본 PL URL), 실패 시 (None, None, None) 반환.
        """
        try:
            # logger.debug(f"JavDB Poster Util: Trying get_javdb_poster_from_pl_local for pl_url='{pl_url}', code='{original_code_for_log}'")
            if not pl_url:
                return None, None, None

            pl_image_original = cls.imopen(pl_url)
            if pl_image_original is None:
                logger.debug(f"JavDB Poster Util: Failed to open pl_image_original from '{pl_url}'.")
                return None, None, None
            
            pl_width, pl_height = pl_image_original.size
            aspect_ratio = pl_width / pl_height if pl_height > 0 else 0
            # logger.debug(f"JavDB Poster Util: PL aspect_ratio={aspect_ratio:.2f} ({pl_width}x{pl_height})")

            if aspect_ratio >= 1.8: # 가로로 매우 긴 이미지만 처리
                logger.debug(f"JavDB Poster Util: PL is very wide (ratio {aspect_ratio:.2f}). Processing right-half.")
                right_half_box = (pl_width / 2, 0, pl_width, pl_height)
                try:
                    right_half_img_obj = pl_image_original.crop(right_half_box)
                    if right_half_img_obj:
                        # 임시 파일로 저장
                        img_format = right_half_img_obj.format if right_half_img_obj.format else pl_image_original.format
                        if not img_format: img_format = "JPEG"
                        ext = img_format.lower().replace("jpeg", "jpg")
                        if ext not in ['jpg', 'png', 'webp']: ext = 'jpg'
                        
                        temp_filename = f"javdb_temp_poster_{int(time.time())}_{os.urandom(4).hex()}.{ext}"
                        temp_filepath = os.path.join(path_data, "tmp", temp_filename)
                        os.makedirs(os.path.join(path_data, "tmp"), exist_ok=True)
                        
                        save_params = {}
                        if ext in ['jpg', 'webp']: save_params['quality'] = 95
                        elif ext == 'png': save_params['optimize'] = True

                        img_to_save = right_half_img_obj
                        if ext == 'jpg' and img_to_save.mode not in ('RGB', 'L'):
                            img_to_save = img_to_save.convert('RGB')
                        
                        img_to_save.save(temp_filepath, **save_params)
                        logger.debug(f"JavDB Poster Util: Saved processed image to temp file: {temp_filepath}")
                        
                        pl_image_original.close() # 원본 이미지 닫기
                        right_half_img_obj.close() # 잘라낸 이미지 닫기
                        
                        return temp_filepath, 'c', pl_url # 임시 파일 경로, 추천 크롭 'c', 원본 pl_url 반환
                    else:
                        logger.debug("JavDB Poster Util: Cropping right-half returned None. Using original PL.")
                except Exception as e_process:
                    logger.error(f"JavDB Poster Util: Error processing/saving wide image: {e_process}. Using original PL.")
            
            # 1.8 미만 비율 또는 처리 실패 시, PIL 객체를 닫고 원본 URL 반환
            pl_image_original.close()
            return pl_url, 'r', pl_url

        except Exception as e:
            logger.exception(f"JavDB Poster Util: Error in get_javdb_poster_from_pl_local: {e}")
            if 'pl_image_original' in locals() and pl_image_original:
                pl_image_original.close()
            return None, None, None

    ################################################
    # region SiteAvBase 메서드 오버라이드
    
    @classmethod
    def set_config(cls, db):
        super().set_config(db)
        site = 'javdb'
        cls.config.update({
            "crop_mode": db.get_list(f"jav_censored_{cls.site_name}_crop_mode", ","),
            "maintain_series_number_labels": db.get_list(f"jav_censored_{cls.site_name}_maintain_series_number_labels", ","),
        })
        cls.config['maintain_series_number_labels'] = {lbl.strip().upper() for lbl in cls.config['maintain_series_number_labels'] if lbl.strip()}

    # endregion SiteAvBase 메서드 오버라이드
    ################################################