import re
from lxml import html
import os
from typing import Union

from ..entity_av import EntityAVSearch
from ..entity_base import EntityMovie, EntityActor, EntityThumb
from ..setup import P, logger
from ..site_util_av import SiteUtilAv as SiteUtil


class SiteJavbus:
    site_name = "javbus"
    site_base_url = "https://www.javbus.com"
    module_char = "C"
    site_char = "B"

    _ps_url_cache = {}

    @classmethod
    def __fix_url(cls, url):
        if not url.startswith("http"):
            return cls.site_base_url + url
        return url

    @classmethod
    def _get_javbus_page_tree(cls, page_url: str, proxy_url: str = None, cf_clearance_cookie: str = None) -> Union[html.HtmlElement, None]:
        javbus_cookies = {'age': 'verified', 'age_check_done': '1', 'ckcy': '1', 'dv': '1', 'existmag': 'mag'}
        if cf_clearance_cookie:
            javbus_cookies['cf_clearance'] = cf_clearance_cookie
            # logger.debug(f"SiteJavbus._get_javbus_page_tree: Using cf_clearance cookie for URL: {page_url}")

        request_headers = SiteUtil.default_headers.copy()
        request_headers['Referer'] = cls.site_base_url + "/"
        # logger.debug(f"SiteJavbus._get_javbus_page_tree: Requesting URL='{page_url}', Proxy='{proxy_url}', Cookies='{javbus_cookies}'")

        try:
            res = SiteUtil.get_response_cs(page_url, proxy_url=proxy_url, headers=request_headers, cookies=javbus_cookies, allow_redirects=True)

            if res is None or res.status_code != 200:
                status_code = res.status_code if res else "None"
                logger.warning(f"SiteJavbus._get_javbus_page_tree: Failed to get page or status not 200 for URL='{page_url}'. Status: {status_code}. Falling back to SiteUtil.get_response if configured.")

                # Cloudscraper 실패 시, SiteUtil.get_response로 fallback
                # logger.debug(f"SiteJavbus._get_javbus_page_tree: Attempting fallback with SiteUtil.get_response for URL='{page_url}'")
                res_fallback = SiteUtil.get_response(page_url, proxy_url=proxy_url, headers=request_headers, cookies=javbus_cookies, verify=False)
                if res_fallback and res_fallback.status_code == 200:
                #     logger.debug(f"SiteJavbus._get_javbus_page_tree: Fallback request successful for URL='{page_url}'.")
                    return html.fromstring(res_fallback.text)
                else:
                    status_code_fallback = res_fallback.status_code if res_fallback else "None"
                    logger.error(f"SiteJavbus._get_javbus_page_tree: Fallback request also failed for URL='{page_url}'. Status: {status_code_fallback}.")
                    return None
                # return None # get_response_cs 실패 시 여기서 None 반환 (fallback 사용 안 할 경우)

            # logger.debug(f"SiteJavbus._get_javbus_page_tree: Successfully fetched page for URL='{page_url}'. Status: {res.status_code}")
            return html.fromstring(res.text)
        
        except Exception as e:
            logger.exception(f"SiteJavbus._get_javbus_page_tree: Exception while getting or parsing page for URL='{page_url}': {e}")
            return None


    @classmethod
    def __search(
        cls,
        keyword,
        do_trans=True,
        proxy_url=None,
        image_mode="0",
        manual=False,
        cf_clearance_cookie=None,
        priority_label_setting_str=""
        ):

        original_keyword = keyword
        temp_keyword = original_keyword.strip().lower()
        temp_keyword = re.sub(r'[_-]?cd\d+$', '', temp_keyword, flags=re.I)
        temp_keyword = temp_keyword.strip(' _-')

        keyword_for_url = re.sub(r'^\d+', '', temp_keyword).lstrip('-_')

        logger.debug(f"JavBus Search: original='{original_keyword}', url_kw='{keyword_for_url}'")

        url = f"{cls.site_base_url}/search/{keyword_for_url}"
        tree = cls._get_javbus_page_tree(url, proxy_url=proxy_url, cf_clearance_cookie=cf_clearance_cookie)
        if tree is None:
            return []

        logger.debug(f"JavBus Search: original='{original_keyword}', url_kw='{keyword_for_url}'")

        ret = []
        for node in tree.xpath('//a[@class="movie-box"]')[:10]:
            try:
                item = EntityAVSearch(cls.site_name)
                item.image_url = cls.__fix_url(node.xpath(".//img/@src")[0])
                tag = node.xpath(".//date")
                item.ui_code = tag[0].text_content().strip()
                
                code_from_url = node.attrib["href"].split("/")[-1]
                item.code = cls.module_char + cls.site_char + code_from_url

                item.desc = "발매일: " + tag[1].text_content().strip()
                item.year = int(item.desc[-10:-6])
                item.title = node.xpath(".//span/text()")[0].strip()
                
                # --- 점수 계산 로직 ---
                # 1. 키워드 표준화
                kw_match = re.match(r'^(\d*)?([a-zA-Z]+)-?(\d+)', temp_keyword)
                kw_std_code = ""
                kw_core_code = ""
                if kw_match:
                    kw_prefix, kw_label, kw_num = kw_match.groups()
                    kw_prefix = kw_prefix if kw_prefix else ""
                    kw_std_code = f"{kw_prefix}{kw_label}{kw_num.zfill(5)}".lower()
                    kw_core_code = f"{kw_label}{kw_num.zfill(5)}".lower()
                
                # 2. 아이템 코드 표준화
                item_match = re.match(r'^(\d*)?([a-zA-Z]+)-?(\d+)', item.ui_code.lower())
                item_std_code = ""
                item_core_code = ""
                if item_match:
                    item_prefix, item_label, item_num = item_match.groups()
                    item_prefix = item_prefix if item_prefix else ""
                    item_std_code = f"{item_prefix}{item_label}{item_num.zfill(5)}".lower()
                    item_core_code = f"{item_label}{item_num.zfill(5)}".lower()

                # 3. 점수 부여
                if kw_std_code and item_std_code:
                    if kw_std_code == item_std_code:
                        item.score = 100 # 시리즈 넘버까지 완벽 일치 (또는 둘 다 없을 때)
                    elif kw_core_code == item_core_code:
                        item.score = 80 # 시리즈 넘버는 다르지만, 핵심은 일치
                    else:
                        item.score = 60
                else:
                    item.score = 20 # 표준화 실패 시

                if manual:
                    _image_mode = "1" if image_mode != "0" else image_mode
                    item.image_url = SiteUtil.process_image_mode(_image_mode, item.image_url, proxy_url=proxy_url)
                    item.title_ko = "(현재 인터페이스에서는 번역을 제공하지 않습니다) " + item.title
                else:
                    item.title_ko = SiteUtil.trans(item.title, do_trans=do_trans)

                item_dict = item.as_dict()
                item_dict['is_priority_label_site'] = False
                item_dict['site_key'] = cls.site_name
                item_dict['original_keyword'] = original_keyword

                original_ps_url = cls.__fix_url(node.xpath(".//img/@src")[0])
                if item_dict.get('code') and original_ps_url:
                    cls._ps_url_cache[item_dict['code']] = {'ps': original_ps_url}

                ret.append(item_dict)

            except Exception: logger.exception("개별 검색 결과 처리 중 예외:")
        sorted_result = sorted(ret, key=lambda k: k.get("score", 0), reverse=True)

        if sorted_result:
            log_count = min(len(sorted_result), 5)
            logger.debug(f"JavBus Search: Top {log_count} results for '{keyword_for_url}':")
            for idx, item_log_final in enumerate(sorted_result[:log_count]):
                logger.debug(f"  {idx+1}. Score={item_log_final.get('score')}, Code={item_log_final.get('code')}, UI Code={item_log_final.get('ui_code')}, Title='{item_log_final.get('title_ko')}'")
        return sorted_result


    @classmethod
    def search(cls, keyword, **kwargs):
        ret = {}
        try:
            do_trans_arg = kwargs.get('do_trans', True)
            proxy_url_arg = kwargs.get('proxy_url', None)
            image_mode_arg = kwargs.get('image_mode', "0")
            manual_arg = kwargs.get('manual', False)
            cf_clearance_cookie_arg = kwargs.get('cf_clearance_cookie', None)
            priority_label_str_arg = kwargs.get('priority_label_setting_str', "")
            data = cls.__search(keyword, 
                                do_trans=do_trans_arg, 
                                proxy_url=proxy_url_arg, 
                                image_mode=image_mode_arg, 
                                manual=manual_arg,
                                cf_clearance_cookie=cf_clearance_cookie_arg,
                                priority_label_setting_str=priority_label_str_arg)
        except Exception as exception:
            logger.exception("검색 결과 처리 중 예외:")
            ret["ret"] = "exception"; ret["data"] = str(exception)
        else:
            ret["ret"] = "success" if data else "no_match"; ret["data"] = data
        return ret

    @classmethod
    def __img_urls(cls, tree):
        img_urls = {'ps': "", 'pl': "", 'arts': []}
        if tree is None:
            logger.warning("JavBus __img_urls: Input tree is None. Cannot extract image URLs.")
            return img_urls

        pl_nodes = tree.xpath('//a[@class="bigImage"]/img/@src')
        pl = pl_nodes[0] if pl_nodes else ""
        if pl: pl = cls.__fix_url(pl)
        else: logger.warning("JavBus __img_urls: PL 이미지 URL을 얻을 수 없음")

        ps = ""
        if pl:
            try:
                filename = pl.split("/")[-1].replace("_b.", ".")
                ps = cls.__fix_url(f"/pics/thumb/{filename}")
            except Exception as e_ps_infer: logger.warning(f"JavBus __img_urls: ps URL 유추 실패: {e_ps_infer}")

        arts = []
        try:
            for href_art in tree.xpath('//*[@id="sample-waterfall"]/a/@href'):
                arts.append(cls.__fix_url(href_art))
        except Exception as e_arts_extract: logger.warning(f"JavBus __img_urls: arts URL 추출 실패: {e_arts_extract}")

        img_urls["ps"] = ps
        img_urls["pl"] = pl
        img_urls["arts"] = list(dict.fromkeys(arts))
        return img_urls

    @classmethod
    def __info(
        cls,
        code, 
        do_trans=True,
        proxy_url=None,
        image_mode="0",
        max_arts=10,
        **kwargs 
    ):
        use_image_server = kwargs.get('use_image_server', False)
        image_server_url = kwargs.get('image_server_url', '').rstrip('/') if use_image_server else ''
        image_server_local_path = kwargs.get('image_server_local_path', '') if use_image_server else ''
        image_path_segment = kwargs.get('url_prefix_segment', 'unknown/unknown')
        ps_to_poster_labels_str = kwargs.get('ps_to_poster_labels_str', '')
        crop_mode_settings_str = kwargs.get('crop_mode_settings_str', '')
        cf_clearance_cookie_value_from_kwargs = kwargs.get('cf_clearance_cookie', None)

        keyword = kwargs.get('original_keyword', None)
        maintain_series_number_labels_str = kwargs.get('maintain_series_number_labels', '')

        cached_data_for_javbus = cls._ps_url_cache.get(code, {})
        ps_url_from_search_cache = cached_data_for_javbus.get('ps')
        # logger.debug(f"JavBus Info: PS URL from cache for '{code}': {ps_url_from_search_cache}")

        original_code_for_url = code[len(cls.module_char) + len(cls.site_char):]
        url = f"{cls.site_base_url}/{original_code_for_url}"

        tree = cls._get_javbus_page_tree(url, proxy_url=proxy_url, cf_clearance_cookie=cf_clearance_cookie_value_from_kwargs)

        if tree is None:
            logger.error(f"JavBus __info: _get_javbus_page_tree returned None for {code}. URL: {url}")
            return None

        if not tree.xpath("//div[@class='container']//div[@class='row movie']"):
            logger.error(f"JavBus __info: Failed to get valid detail page structure for {code}. Main content div not found. URL: {url}")
            return None

        entity = EntityMovie(cls.site_name, code)
        entity.country = ["일본"]; entity.mpaa = "청소년 관람불가"
        entity.thumb = []; entity.fanart = []; entity.tag = []

        try:
            info_node = tree.xpath("//div[contains(@class, 'container')]//div[@class='col-md-3 info']")[0]
            
            # 1. URL 기반으로 기본 ui_code를 먼저 설정
            base_ui_code = original_code_for_url.split('_')[0].upper()
            
            # 2. 페이지의 "識別碼" 필드를 파싱 (폴백용)
            ui_code_val_nodes = info_node.xpath("./p[./span[@class='header' and contains(text(),'識別碼')]]/span[not(@class='header')]//text()")
            if not ui_code_val_nodes:
                ui_code_val_nodes = info_node.xpath("./p[./span[@class='header' and contains(text(),'識別碼')]]/text()[normalize-space()]")
            raw_ui_code_from_page = "".join(ui_code_val_nodes).strip()
            
            # URL 기반 코드가 유효하지 않을 경우(예: 빈 문자열), 페이지 기반 코드로 폴백
            if not base_ui_code and raw_ui_code_from_page:
                base_ui_code = raw_ui_code_from_page.upper()
                logger.warning(f"JavBus: URL-based code was empty. Falling back to page-based code: {base_ui_code}")

            # 3. 시리즈 넘버 유지 로직 적용
            final_ui_code = base_ui_code
            maintain_labels_set = {label.strip().upper() for label in maintain_series_number_labels_str.split(',') if label}

            if keyword and base_ui_code and maintain_labels_set:
                # 키워드에서 prefix와 core 분리
                kw_match = re.match(r'^(\d+)([a-zA-Z].*)', keyword.upper())
                if kw_match:
                    kw_prefix = kw_match.group(1)
                    kw_core = kw_match.group(2).replace('-', '')
                    
                    # 페이지 품번에서 prefix와 core 분리
                    jb_match = re.match(r'^(\d*)?([A-Z]+-?\d+)', base_ui_code)
                    if jb_match:
                        jb_core = jb_match.group(2).replace('-', '')
                        jb_label = jb_core.split('-')[0]
                        pure_jb_label_match = re.match(r'(\D+)', jb_label)
                        pure_jb_label = pure_jb_label_match.group(1) if pure_jb_label_match else jb_label

                        if kw_core == jb_core and pure_jb_label in maintain_labels_set:
                            final_ui_code = f"{kw_prefix}{base_ui_code}"
            
            entity.ui_code = final_ui_code
            entity.title = entity.originaltitle = entity.sorttitle = final_ui_code

            h3_text = tree.xpath("normalize-space(//div[@class='container']/h3/text())")
            if h3_text.upper().startswith(base_ui_code):
                entity.tagline = SiteUtil.trans(h3_text[len(base_ui_code):].strip(), do_trans)
            else:
                entity.tagline = SiteUtil.trans(h3_text, do_trans)

            # 나머지 정보 직접 XPath로 추출 (info_node 기준)
            all_p_tags_in_info = info_node.xpath("./p")
            genre_header_p_node = None; actor_header_p_node = None
            for p_idx, p_tag_node_loop in enumerate(all_p_tags_in_info):
                header_span_text_nodes = p_tag_node_loop.xpath("normalize-space(./span[@class='header']/text())")
                if "類別:" in header_span_text_nodes or (p_tag_node_loop.get("class") == "header" and p_tag_node_loop.text_content().strip().startswith("類別")):
                    genre_header_p_node = p_tag_node_loop
                elif "演員" in header_span_text_nodes or (p_tag_node_loop.get("class") == "star-show" and "演員" in p_tag_node_loop.xpath("normalize-space(./span[@class='header']/text())")):
                    actor_header_p_node = p_tag_node_loop

            for p_tag_node_loop_general in all_p_tags_in_info:
                header_span_general = p_tag_node_loop_general.xpath("./span[@class='header']")
                if not header_span_general or not header_span_general[0].text: continue
                key_text_general = header_span_general[0].text_content().replace(":", "").strip()
                if key_text_general in ["類別", "演員"]: continue

                value_nodes_general = header_span_general[0].xpath("./following-sibling::node()")
                value_parts_general = []
                for node_item_general in value_nodes_general:
                    if hasattr(node_item_general, 'tag'):
                        if node_item_general.tag == 'a': value_parts_general.append(node_item_general.text_content().strip())
                        elif node_item_general.tag == 'span' and not node_item_general.get('class'): value_parts_general.append(node_item_general.text_content().strip())
                    elif isinstance(node_item_general, str): 
                        stripped_text_general = node_item_general.strip()
                        if stripped_text_general: value_parts_general.append(stripped_text_general)
                value_text_general = " ".join(filter(None, value_parts_general)).strip()
                if not value_text_general or value_text_general == "----": continue

                if key_text_general == "發行日期":
                    if value_text_general != "0000-00-00": entity.premiered = value_text_general; entity.year = int(value_text_general[:4])
                    else: entity.premiered = "1900-01-01"; entity.year = 1900
                elif key_text_general == "長度":
                    try: entity.runtime = int(value_text_general.replace("分鐘", "").strip())
                    except: pass
                elif key_text_general == "導演":
                    entity.director = value_text_general
                elif key_text_general == "製作商":
                    entity.studio = SiteUtil.trans(value_text_general, do_trans=do_trans, source='ja', target='ko')
                elif key_text_general == "發行商":
                    if not entity.studio:
                        entity.studio = SiteUtil.trans(value_text_general, do_trans=do_trans, source='ja', target='ko')
                elif key_text_general == "系列":
                    value_text_general = SiteUtil.trans(value_text_general, do_trans=do_trans, source='ja', target='ko')
                    if entity.tag is None: entity.tag = []
                    if value_text_general not in entity.tag: entity.tag.append(value_text_general)

            if genre_header_p_node is not None:
                genre_values_p_node_list = genre_header_p_node.xpath("./following-sibling::p[1]")
                if genre_values_p_node_list:
                    genre_values_p_actual_node = genre_values_p_node_list[0]
                    # logger.debug(f"JavBus: Genre values P tag content: {html.tostring(genre_values_p_actual_node, encoding='unicode')[:300]}")

                    genre_span_tags = genre_values_p_actual_node.xpath("./span[@class='genre']")

                    if entity.genre is None: entity.genre = []

                    # logger.debug(f"JavBus: Found {len(genre_span_tags)} <span class='genre'> tags.")
                    for span_tag_genre in genre_span_tags:
                        a_tag_text_nodes = span_tag_genre.xpath("./label/a/text() | ./a/text()")
                        genre_ja = ""
                        if a_tag_text_nodes:
                            genre_ja = a_tag_text_nodes[0].strip()
                        else:
                            if not span_tag_genre.xpath("./button[@id='gr_btn']"):
                                genre_ja = span_tag_genre.text_content().strip()

                        # logger.debug(f"  Raw genre text from span: '{genre_ja}'")
                        if not genre_ja or genre_ja == "多選提交" or genre_ja in SiteUtil.av_genre_ignore_ja: 
                            # logger.debug(f"    Skipping genre: '{genre_ja}'")
                            continue

                        if genre_ja in SiteUtil.av_genre: 
                            if SiteUtil.av_genre[genre_ja] not in entity.genre: entity.genre.append(SiteUtil.av_genre[genre_ja])
                        else:
                            genre_ko = SiteUtil.trans(genre_ja, do_trans=do_trans, source='ja', target='ko').replace(" ", "")
                            if genre_ko not in SiteUtil.av_genre_ignore_ko and genre_ko not in entity.genre:
                                entity.genre.append(genre_ko)
                else:
                    logger.warning(f"JavBus: Genre values P tag (sibling of header) not found for {code}.")
            else:
                logger.warning(f"JavBus: Genre header P tag ('類別') not found for {code}.")

            if actor_header_p_node is not None:
                actor_values_p_node = actor_header_p_node.xpath("./following-sibling::p[1]")
                if actor_values_p_node:
                    actor_a_tags = actor_values_p_node[0].xpath(".//span[@class='genre']/a")
                    if entity.actor is None: entity.actor = []
                    for a_tag_actor in actor_a_tags:
                        actor_name = a_tag_actor.text_content().strip()
                        if actor_name and actor_name != "暫無出演者資訊":
                            if not any(act.originalname == actor_name for act in entity.actor):
                                actor_entity = EntityActor(actor_name); actor_entity.name = actor_name
                                entity.actor.append(actor_entity)
            else: logger.warning(f"JavBus: Actor header P tag ('演員') not found for {code}.")

            if entity.ui_code:
                label_part = entity.ui_code.split('-')[0]
                if label_part and label_part not in (entity.tag or []):
                    if entity.tag is None: entity.tag = []
                    entity.tag.append(label_part)

        except Exception as e:
            logger.exception(f"JavBus Info: Metadata parsing error: {e}")
            return None

        ui_code_for_image = entity.ui_code.lower()
        user_custom_poster_url = None; user_custom_landscape_url = None
        skip_default_poster_logic = False; skip_default_landscape_logic = False

        if use_image_server and image_server_local_path and image_server_url and ui_code_for_image:
            logger.debug(f"JavBus: Checking for user custom images for {ui_code_for_image}")
            poster_suffixes = ["_p_user.jpg", "_p_user.png", "_p_user.webp"]
            landscape_suffixes = ["_pl_user.jpg", "_pl_user.png", "_pl_user.webp"]
            for suffix in poster_suffixes:
                _, web_url = SiteUtil.get_user_custom_image_paths(image_server_local_path, image_path_segment, ui_code_for_image, suffix, image_server_url)
                if web_url:
                    user_custom_poster_url = web_url
                    if not any(t.aspect == 'poster' and t.value == user_custom_poster_url for t in entity.thumb):
                        entity.thumb.append(EntityThumb(aspect="poster", value=user_custom_poster_url))
                    skip_default_poster_logic = True; logger.debug(f"JavBus: Using user custom poster: {web_url}"); break
            for suffix in landscape_suffixes:
                _, web_url = SiteUtil.get_user_custom_image_paths(image_server_local_path, image_path_segment, ui_code_for_image, suffix, image_server_url)
                if web_url:
                    user_custom_landscape_url = web_url
                    if not any(t.aspect == 'landscape' and t.value == user_custom_landscape_url for t in entity.thumb):
                        entity.thumb.append(EntityThumb(aspect="landscape", value=user_custom_landscape_url))
                    skip_default_landscape_logic = True; logger.debug(f"JavBus: Using user custom landscape: {web_url}"); break

        final_poster_source = None; final_poster_crop_mode = None
        final_landscape_url_source = None
        arts_urls_for_processing = []
        mgs_style_poster_filepath = None
        fixed_size_crop_applied_for_javbus = False # Javbus용 고정 크롭 플래그

        needs_default_image_processing = not skip_default_poster_logic or \
                                         not skip_default_landscape_logic or \
                                         (entity.fanart is not None and (len(entity.fanart) < max_arts and max_arts > 0))

        if needs_default_image_processing:
            logger.debug(f"JavBus: Running default image logic for {code} (P_skip:{skip_default_poster_logic}, L_skip:{skip_default_landscape_logic}, FanartNeed:{entity.fanart is not None and (len(entity.fanart) < max_arts and max_arts > 0)}).")

            img_urls_from_page = cls.__img_urls(tree)
            ps_url = ps_url_from_search_cache
            # ps_url = img_urls_from_page.get('ps')
            pl_url = img_urls_from_page.get('pl')
            all_arts_from_page = img_urls_from_page.get('arts', [])

            if not skip_default_landscape_logic and pl_url:
                final_landscape_url_source = pl_url
                # logger.debug(f"JavBus: Default landscape set to PL: {pl_url}")

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
                    # 1. 크롭 모드 사용자 설정 (PS 강제 사용 아닐 때)
                    if forced_crop_mode_for_this_item and pl_url: # 또는 valid_pl_candidate
                        logger.debug(f"[{cls.site_name} Info] Poster determined by FORCED 'crop_mode={forced_crop_mode_for_this_item}'. Using PL: {pl_url}")
                        final_poster_source = pl_url
                        final_poster_crop_mode = forced_crop_mode_for_this_item

                    if ps_url:
                        # 2. PS 강제 포스터 사용 설정
                        if apply_ps_to_poster_for_this_item:
                            logger.debug(f"[{cls.site_name} Info] Poster determined by FORCED 'ps_to_poster' setting. Using PS: {ps_url}")
                            final_poster_source = ps_url
                            final_poster_crop_mode = None

                        # --- 일반 포스터 결정 로직 (is_hq_poster, has_hq_poster) ---
                        specific_arts_candidates = []
                        if all_arts_from_page:
                            if all_arts_from_page[0] not in specific_arts_candidates: specific_arts_candidates.append(all_arts_from_page[0])
                            if len(all_arts_from_page) > 1 and all_arts_from_page[-1] != all_arts_from_page[0] and all_arts_from_page[-1] not in specific_arts_candidates:
                                specific_arts_candidates.append(all_arts_from_page[-1])

                        # 3. is_hq_poster
                        if final_poster_source is None and pl_url and SiteUtil.is_portrait_high_quality_image(pl_url, proxy_url=proxy_url):
                            if SiteUtil.is_hq_poster(ps_url, pl_url, proxy_url=proxy_url):
                                final_poster_source = pl_url
                        if final_poster_source is None and specific_arts_candidates:
                            for art_candidate in specific_arts_candidates:
                                if SiteUtil.is_portrait_high_quality_image(art_candidate, proxy_url=proxy_url):
                                    if SiteUtil.is_hq_poster(ps_url, art_candidate, proxy_url=proxy_url):
                                        final_poster_source = art_candidate; break

                        # 4. 특수 고정 크기 크롭 (해상도 기반)
                        if (final_poster_source is None or (ps_url and final_poster_source == ps_url)) and pl_url:
                            logger.debug(f"JavBus Poster (Prio 3-C attempt): Applying fixed-size crop logic for PL: {pl_url}")
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
                                            fixed_size_crop_applied_for_javbus = True
                                            logger.debug(f"JavBus: Fixed-size crop (resolution based) applied to PL. Poster source is now a PIL object.")
                                    # else: logger.debug(f"JavBus PL ({img_width}x{img_height}) does not meet fixed-size crop criteria.")
                            except Exception as e_fixed_crop_javbus:
                                logger.error(f"JavBus: Error during fixed-size crop attempt: {e_fixed_crop_javbus}")

                        # 5. MGS 스타일 처리
                        if (final_poster_source is None or final_poster_source == ps_url) and \
                           not fixed_size_crop_applied_for_javbus and pl_url:
                            logger.debug(f"JavBus Poster (Prio 4 attempt with PS): Attempting MGS-style processing for PL ('{pl_url}') with PS ('{ps_url}').")
                            temp_filepath, _, _ = SiteUtil.get_mgs_half_pl_poster_info_local(ps_url, pl_url, proxy_url=proxy_url)
                            if temp_filepath and os.path.exists(temp_filepath):
                                mgs_style_poster_filepath = temp_filepath
                                final_poster_source = mgs_style_poster_filepath
                                final_poster_crop_mode = None
                                logger.debug(f"JavBus: MGS-style processing successful with PS. Using temp file: {final_poster_source}")

                        # 6. has_hq_poster
                        if final_poster_source is None:
                            if pl_url:
                                crop_pos = SiteUtil.has_hq_poster(ps_url, pl_url, proxy_url=proxy_url)
                                if crop_pos:
                                    final_poster_source = pl_url
                                    final_poster_crop_mode = crop_pos
                            if final_poster_source is None and specific_arts_candidates:
                                for art_candidate in specific_arts_candidates:
                                    crop_pos_art = SiteUtil.has_hq_poster(ps_url, art_candidate, proxy_url=proxy_url)
                                    if crop_pos_art:
                                        final_poster_source = art_candidate
                                        final_poster_crop_mode = crop_pos_art; break

                        if final_poster_source: logger.debug(f"JavBus: General logic (is_hq/has_hq) determined poster: '{str(final_poster_source)[:100]}...', crop: {final_poster_crop_mode}")

                        # 7. PS 사용
                        if final_poster_source is None:
                            logger.debug(f"JavBus Poster (with PS - Fallback): Using PS.")
                            final_poster_source = ps_url
                            final_poster_crop_mode = None

                    else:
                        logger.debug(f"[{cls.site_name} Info] No PS url found. Skipping poster processing")

                    # 최종 결정된 포스터 정보 로깅
                    if final_poster_source:
                        logger.debug(f"[{cls.site_name} Info] Final Poster Decision - Source type: {type(final_poster_source)}, Crop: {final_poster_crop_mode}")
                        if isinstance(final_poster_source, str): logger.debug(f"  Source URL/Path: {final_poster_source[:150]}")
                    else:
                        logger.error(f"[{cls.site_name} Info] CRITICAL: No poster source could be determined for {code}")
                        final_poster_source = None
                        final_poster_crop_mode = None

            if all_arts_from_page:
                temp_fanart_list_jb = []
                sources_to_exclude_for_fanart_jb = set()
                if final_landscape_url_source: sources_to_exclude_for_fanart_jb.add(final_landscape_url_source)
                if isinstance(final_poster_source, str) and final_poster_source.startswith("http"):
                    sources_to_exclude_for_fanart_jb.add(final_poster_source)

                if mgs_style_poster_filepath and final_poster_source == mgs_style_poster_filepath and pl_url:
                    sources_to_exclude_for_fanart_jb.add(pl_url)

                for art_url_item_jb in all_arts_from_page:
                    if len(temp_fanart_list_jb) >= max_arts: break
                    if art_url_item_jb and art_url_item_jb not in sources_to_exclude_for_fanart_jb:
                        if art_url_item_jb not in temp_fanart_list_jb:
                            temp_fanart_list_jb.append(art_url_item_jb)
                arts_urls_for_processing = temp_fanart_list_jb
                logger.debug(f"JavBus: Fanart candidates ({len(arts_urls_for_processing)}): {arts_urls_for_processing[:3]}")

        logger.debug(f"JavBus: Final Images Decision - Poster='{str(final_poster_source)[:100]}...' (Type: {type(final_poster_source)}, Crop='{final_poster_crop_mode}'), Landscape='{final_landscape_url_source}', Fanarts_to_process({len(arts_urls_for_processing)})")

        if use_image_server and image_mode == '4' and ui_code_for_image:
            logger.debug(f"JavBus: Saving images to Image Server for {ui_code_for_image}...")
            if not skip_default_poster_logic and final_poster_source:
                p_path = SiteUtil.save_image_to_server_path(
                    final_poster_source, 'p', image_server_local_path, image_path_segment,
                    ui_code_for_image, proxy_url=proxy_url, crop_mode=final_poster_crop_mode
                )
                if p_path and not any(t.aspect == 'poster' and t.value.endswith(p_path) for t in entity.thumb):
                    entity.thumb.append(EntityThumb(aspect="poster", value=f"{image_server_url}/{p_path}"))
            if not skip_default_landscape_logic and final_landscape_url_source:
                pl_path = SiteUtil.save_image_to_server_path(
                    final_landscape_url_source, 'pl', image_server_local_path, image_path_segment,
                    ui_code_for_image, proxy_url=proxy_url
                )
                if pl_path and not any(t.aspect == 'landscape' and t.value.endswith(pl_path) for t in entity.thumb):
                    entity.thumb.append(EntityThumb(aspect="landscape", value=f"{image_server_url}/{pl_path}"))
            if arts_urls_for_processing:
                current_fanart_server_count = len([fa for fa in entity.fanart if fa.startswith(image_server_url)])
                for idx, art_url in enumerate(arts_urls_for_processing):
                    if current_fanart_server_count >= max_arts: break
                    art_relative_path = SiteUtil.save_image_to_server_path(
                        art_url, 'art', image_server_local_path, image_path_segment,
                        ui_code_for_image, art_index=len(entity.fanart) + 1, proxy_url=proxy_url
                    )
                    if art_relative_path:
                        full_art_url = f"{image_server_url}/{art_relative_path}"
                        if full_art_url not in entity.fanart:
                            entity.fanart.append(full_art_url)
                            current_fanart_server_count +=1
        else:
            if not skip_default_poster_logic and final_poster_source and not any(t.aspect == 'poster' for t in entity.thumb):
                p_url = SiteUtil.process_image_mode(image_mode, final_poster_source, proxy_url=proxy_url, crop_mode=final_poster_crop_mode)
                if p_url: entity.thumb.append(EntityThumb(aspect="poster", value=p_url))
            if not skip_default_landscape_logic and final_landscape_url_source and not any(t.aspect == 'landscape' for t in entity.thumb):
                pl_url = SiteUtil.process_image_mode(image_mode, final_landscape_url_source, proxy_url=proxy_url)
                if pl_url: entity.thumb.append(EntityThumb(aspect="landscape", value=pl_url))
            if arts_urls_for_processing:
                for art_url in arts_urls_for_processing:
                    if len(entity.fanart) >= max_arts: break
                    processed_art = SiteUtil.process_image_mode(image_mode, art_url, proxy_url=proxy_url)
                    if processed_art: entity.fanart.append(processed_art)

        final_entity = entity
        if final_entity.ui_code:
            try: 
                final_entity = SiteUtil.shiroutoname_info(final_entity)
                if final_entity.ui_code.upper() != original_code_for_url.split('_')[0].upper():
                    new_code_value = final_entity.ui_code.lower()
                    if '_' in original_code_for_url:
                        new_code_value += '_' + original_code_for_url.split('_')[1]
                    if final_entity.code != (cls.module_char + cls.site_char + new_code_value):
                        final_entity.code = cls.module_char + cls.site_char + new_code_value
            except Exception as e_shirouto: logger.exception(f"JavBus: Shiroutoname error: {e_shirouto}")
        
        if mgs_style_poster_filepath and os.path.exists(mgs_style_poster_filepath):
            try: os.remove(mgs_style_poster_filepath)
            except Exception as e: logger.error(f"Failed to remove temp file {mgs_style_poster_filepath}: {e}")
        
        logger.info(f"JavBus: __info finished for {code}. UI Code: {final_entity.ui_code if hasattr(final_entity, 'ui_code') else 'N/A'}, Thumbs: {len(final_entity.thumb)}, Fanarts: {len(final_entity.fanart)}")
        return final_entity

    @classmethod
    def info(cls, code, **kwargs):
        ret = {}
        try:
            entity = cls.__info(code, **kwargs)
            if entity:
                ret["ret"] = "success"
                ret["data"] = entity.as_dict()
            else:
                ret["ret"] = "error"
                ret["data"] = f"Failed to get JavBus info for {code} (__info returned None)."
        except Exception as e:
            ret["ret"] = "exception"
            ret["data"] = str(e)
            logger.exception(f"JavBus info (outer) error for code {code}: {e}")
        return ret
