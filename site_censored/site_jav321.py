import re
import os

from lxml import html
from copy import deepcopy
from PIL import Image

from ..entity_av import EntityAVSearch
from ..entity_base import EntityActor, EntityExtra, EntityMovie, EntityRatings, EntityThumb
from ..setup import P, logger
from ..site_util_av import SiteUtilAv as SiteUtil
from .site_dmm import SiteDmm


class SiteJav321:
    site_name = "jav321"
    site_base_url = "https://www.jav321.com"
    module_char = "C"
    site_char = "T"
    _ps_url_cache = {} 

    @classmethod
    def _parse_jav321_ui_code(cls, code_str: str, maintain_series_labels_set: set = None, dmm_parser_rules: dict = None) -> tuple:
        if not code_str or not isinstance(code_str, str): return "", "", ""
        if maintain_series_labels_set is None: maintain_series_labels_set = set()
        
        # 입력된 코드에 하이픈이 있는지 확인
        if '-' in code_str:
            # --- 하이픈이 있는 경우 (MGStage 등 다른 소스 형식) ---
            # DMM 파서를 사용하지 않고, 직접 파싱
            logger.debug(f"Jav321 Parser: Hyphenated code detected '{code_str}'. Using direct parsing.")
            
            parts = code_str.split('-', 1)
            remaining_for_label = parts[0]
            num_part = parts[1]

            score_num_raw = num_part
            num_ui_part = (num_part.lstrip('0') or "0").zfill(3)

            score_label_part = remaining_for_label.lower()

            pure_alpha_label_match = re.search(r'[a-zA-Z]+', remaining_for_label)
            pure_alpha_label = pure_alpha_label_match.group(0).upper() if pure_alpha_label_match else ""
            
            if pure_alpha_label and pure_alpha_label in maintain_series_labels_set:
                label_ui_part = remaining_for_label.upper()
            else:
                non_prefix_label_match = re.search(r'[a-zA-Z].*', remaining_for_label)
                if non_prefix_label_match:
                    label_ui_part = non_prefix_label_match.group(0).upper()
                else:
                    label_ui_part = remaining_for_label.upper()
            
            ui_code_final = f"{label_ui_part}-{num_ui_part}"
            return ui_code_final, score_label_part, score_num_raw

        else:
            # --- 하이픈이 없는 경우 (DMM 형식 가능성 높음) ---
            # DMM의 파서를 호출하여 처리
            logger.debug(f"Jav321 Parser: Non-hyphenated code detected '{code_str}'. Using DMM parser.")
            if dmm_parser_rules is None: dmm_parser_rules = {}

            # 'videoa'를 우선 시도하고, 실패 시 'dvd'로 폴백
            ui_code_videoa, label_videoa, num_videoa = SiteDmm._parse_ui_code_from_cid(
                code_str, 'videoa', dmm_parser_rules=dmm_parser_rules
            )
            
            # videoa 파싱이 성공적이면 바로 반환
            if label_videoa and num_videoa:
                return ui_code_videoa, label_videoa, num_videoa
            
            # videoa 파싱 실패 시, dvd 파싱 시도
            logger.debug(f"Jav321 Parser: 'videoa' parsing failed for '{code_str}'. Falling back to 'dvd' type.")
            ui_code_dvd, label_dvd, num_dvd = SiteDmm._parse_ui_code_from_cid(
                code_str, 'dvd', dmm_parser_rules=dmm_parser_rules
            )
            return ui_code_dvd, label_dvd, num_dvd


    @classmethod
    def get_label_from_ui_code(cls, ui_code_str: str) -> str:
        if not ui_code_str or not isinstance(ui_code_str, str): 
            return ""
        ui_code_upper = ui_code_str.upper()

        # ID 계열 레이블 먼저 확인 (예: "16ID-045" -> "16ID")
        id_match = re.match(r'^(\d*[A-Z]+ID)', ui_code_upper) 
        if id_match:
            return id_match.group(1)

        # 일반적인 경우 (하이픈 앞부분)
        if '-' in ui_code_upper:
            label_part = ui_code_upper.split('-', 1)[0]
            # 숫자 접두사 제거 (예: 436ABF -> ABF)
            pure_alpha_match = re.search(r'([A-Z]+)', label_part)
            if pure_alpha_match: return pure_alpha_match.group(1)
            return label_part

        # 하이픈 없는 경우 (예: HAGE001 -> HAGE)
        match_alpha_prefix = re.match(r'^([A-Z]+)', ui_code_upper)
        if match_alpha_prefix:
            return match_alpha_prefix.group(1)

        return ui_code_upper


    @classmethod
    def __search(
        cls,
        keyword,
        do_trans=True,
        proxy_url=None,
        image_mode="0",
        manual=False,
        priority_label_setting_str="",
        maintain_series_number_labels=""
        ):

        original_keyword = keyword
        temp_keyword = keyword.strip().lower()
        temp_keyword = re.sub(r'[-_]?cd\d*$', '', temp_keyword, flags=re.I)
        keyword_for_url = temp_keyword.strip('-_ ')

        logger.debug(f"Jav321 Search: original_keyword='{original_keyword}', keyword_for_url='{keyword_for_url}'")
        
        url = f"{cls.site_base_url}/search"
        headers = SiteUtil.default_headers.copy(); headers['Referer'] = cls.site_base_url + "/"
        res = SiteUtil.get_response(url, proxy_url=proxy_url, headers=headers, post_data={"sn": keyword_for_url})

        if res is None:
            logger.error(f"Jav321 Search: Failed to get response for keyword '{keyword_for_url}'.")
            return []

        if not res.history or not res.url.startswith(cls.site_base_url + "/video/"):
            logger.debug(f"Jav321 Search: No direct match or multiple results for keyword '{keyword_for_url}'. Final URL: {res.url}")
            return []
        
        ret = []
        try:
            item = EntityAVSearch(cls.site_name)
            
            code_from_url_path = res.url.split("/")[-1]
            item.code = cls.module_char + cls.site_char + code_from_url_path

            maintain_series_labels_set = {lbl.strip().upper() for lbl in maintain_series_number_labels.split(',') if lbl.strip()}

            # --- 점수 계산 로직 ---
            # 1. 검색어와 아이템 코드를 각각 파싱
            _, search_label_part, search_num_part = cls._parse_jav321_ui_code(original_keyword, maintain_series_labels_set)
            item.ui_code, item_label_part, item_num_part = cls._parse_jav321_ui_code(code_from_url_path, maintain_series_labels_set)

            # 2. 비교용 표준 품번 생성 (숫자 부분을 5자리로 패딩)
            search_full_code = f"{search_label_part}{search_num_part.zfill(5)}"
            item_full_code = f"{item_label_part}{item_num_part.zfill(5)}"
            
            search_pure_alpha_match = re.search(r'[a-zA-Z]+', search_label_part)
            item_pure_alpha_match = re.search(r'[a-zA-Z]+', item_label_part)
            search_pure_code = ""
            item_pure_code = ""
            if search_pure_alpha_match:
                search_pure_code = f"{search_pure_alpha_match.group(0).lower()}{search_num_part.zfill(5)}"
            if item_pure_alpha_match:
                item_pure_code = f"{item_pure_alpha_match.group(0).lower()}{item_num_part.zfill(5)}"
            
            # 3. 점수 부여
            if search_full_code == item_full_code:
                item.score = 100
            elif search_pure_code and item_pure_code and search_pure_code == item_pure_code:
                item.score = 80
            else:
                item.score = 60

            # logger.debug(f"Jav321 Score: SearchFull='{search_full_code}', ItemFull='{item_full_code}' -> Score={item.score}")
            # logger.debug(f"Jav321 Score: SearchPure='{search_pure_code}', ItemPure='{item_pure_code}'")

            base_xpath = "/html/body/div[2]/div[1]/div[1]"
            tree = html.fromstring(res.text)

            img_tag_node = tree.xpath(f"{base_xpath}/div[2]/div[1]/div[1]/img")
            raw_ps_url = ""
            if img_tag_node:
                src_attr = img_tag_node[0].attrib.get('src')
                onerror_attr = img_tag_node[0].attrib.get('onerror')
                if src_attr and src_attr.strip(): raw_ps_url = src_attr.strip()
                elif onerror_attr: 
                    parsed_onerror_url = cls._process_jav321_url_from_attribute(onerror_attr)
                    if parsed_onerror_url: raw_ps_url = parsed_onerror_url
            
            item.image_url = cls._process_jav321_url_from_attribute(raw_ps_url) if raw_ps_url else ""
            
            date_tags = tree.xpath(f'{base_xpath}/div[2]/div[1]/div[2]/b[contains(text(),"配信開始日")]/following-sibling::text()')
            date_str = date_tags[0].lstrip(":").strip() if date_tags and date_tags[0].lstrip(":").strip() else "1900-01-01"
            item.desc = f"발매일: {date_str}"
            try: item.year = int(date_str[:4])
            except ValueError: item.year = 1900

            title_tags = tree.xpath(f"{base_xpath}/div[1]/h3/text()")
            item.title = title_tags[0].strip() if title_tags else "제목 없음"
            
            if manual:
                _image_mode = "1" if image_mode != "0" else image_mode
                if item.image_url: item.image_url = SiteUtil.process_image_mode(_image_mode, item.image_url, proxy_url=proxy_url)
                item.title_ko = "(현재 인터페이스에서는 번역을 제공하지 않습니다) " + item.title
            else:
                item.title_ko = SiteUtil.trans(item.title, do_trans=do_trans)

            if item.code:
                if item.image_url: cls._ps_url_cache[item.code] = item.image_url
                item_dict = item.as_dict()
                ret.append(item_dict)
        except Exception as e_item_search:
            logger.exception(f"Jav321 Search: Error processing single direct match: {e_item_search}")

        if ret:
            logger.debug(f"Score={item.score}, Code={item.code}, UI Code={item.ui_code}, Title='{item.title_ko}'")
        return ret


    @classmethod
    def search(cls, keyword, **kwargs):
        ret = {}
        try:
            do_trans_arg = kwargs.get('do_trans', True)
            proxy_url_arg = kwargs.get('proxy_url', None)
            image_mode_arg = kwargs.get('image_mode', "0")
            manual_arg = kwargs.get('manual', False)
            priority_label_str_arg = kwargs.get('priority_label_setting_str', "")
            maintain_series_labels_arg = kwargs.get('maintain_series_number_labels', "")
            data = cls.__search(keyword,
                                do_trans=do_trans_arg,
                                proxy_url=proxy_url_arg,
                                image_mode=image_mode_arg,
                                manual=manual_arg,
                                priority_label_setting_str=priority_label_str_arg,
                                maintain_series_number_labels=maintain_series_labels_arg)
        except Exception as exception:
            logger.exception("검색 결과 처리 중 예외:")
            ret["ret"] = "exception"; ret["data"] = str(exception)
        else:
            ret["ret"] = "success" if data else "no_match"; ret["data"] = data
        return ret


    @staticmethod
    def _process_jav321_url_from_attribute(url_attribute_value):
        """
        img 태그의 src 또는 onerror 속성값에서 Jav321 관련 URL을 추출하고 처리합니다.
        onerror의 경우 "this.src='...'" 패턴을 파싱합니다.
        반환값은 소문자화, https 변환된 URL이거나, 유효하지 않으면 None입니다.
        """
        if not url_attribute_value:
            return None
        
        raw_url = ""
        if "this.src='" in url_attribute_value: # onerror 형태
            url_match = re.search(r"this\.src='([^']+)'", url_attribute_value)
            if url_match:
                raw_url = url_match.group(1).strip()
        else: # src 형태 (또는 onerror가 아니지만 URL일 수 있는 경우)
            raw_url = url_attribute_value.strip()

        if not raw_url:
            return None

        # jav321.com 또는 pics.dmm.co.jp 등의 유효한 도메인인지 체크 (선택적)
        # if not ("jav321.com" in raw_url or "pics.dmm.co.jp" in raw_url):
        #     logger.debug(f"Jav321 URL Process: Skipping non-target domain URL: {raw_url}")
        #     return None

        processed_url = raw_url.lower()
        if processed_url.startswith("http://"):
            processed_url = "https://" + processed_url[len("http://"):]
        # //netloc//path 형태의 더블 슬래시는 .lower()나 replace에 의해 변경되지 않음.
        
        return processed_url

    @classmethod
    def __img_urls(cls, tree):
        img_urls = {'ps': "", 'pl': "", 'arts': []}
        
        try:
            # 1. PS 이미지 추출 (src 우선, 없으면 onerror)
            ps_xpath = '/html/body/div[2]/div[1]/div[1]/div[2]/div[1]/div[1]/img'
            ps_img_node = tree.xpath(ps_xpath)
            if ps_img_node:
                src_val = ps_img_node[0].attrib.get('src')
                onerror_val = ps_img_node[0].attrib.get('onerror')
                
                url_candidate_ps = None
                if src_val and src_val.strip(): # src 값 우선
                    url_candidate_ps = cls._process_jav321_url_from_attribute(src_val)
                if not url_candidate_ps and onerror_val: # src 없거나 처리 실패 시 onerror
                    url_candidate_ps = cls._process_jav321_url_from_attribute(onerror_val)
                
                if url_candidate_ps: 
                    img_urls['ps'] = url_candidate_ps
                    logger.debug(f"Jav321 ImgUrls: PS URL='{img_urls['ps']}' (From src: {bool(src_val and src_val.strip() and img_urls['ps'] == cls._process_jav321_url_from_attribute(src_val))})")
                else: logger.warning(f"Jav321 ImgUrls: PS URL not found.")
            else: logger.warning(f"Jav321 ImgUrls: PS tag not found.")

            # 2. PL 이미지 추출 (사이드바 첫번째, src 우선)
            pl_xpath = '/html/body/div[2]/div[2]/div[1]/p/a/img'
            pl_img_node = tree.xpath(pl_xpath)
            if pl_img_node:
                src_val = pl_img_node[0].attrib.get('src')
                onerror_val = pl_img_node[0].attrib.get('onerror')
                
                url_candidate_pl = None
                if src_val and src_val.strip():
                    url_candidate_pl = cls._process_jav321_url_from_attribute(src_val)
                if not url_candidate_pl and onerror_val:
                    url_candidate_pl = cls._process_jav321_url_from_attribute(onerror_val)

                if url_candidate_pl:
                    img_urls['pl'] = url_candidate_pl
                    logger.debug(f"Jav321 ImgUrls: PL URL='{img_urls['pl']}' (From src: {bool(src_val and src_val.strip() and img_urls['pl'] == cls._process_jav321_url_from_attribute(src_val))})")
                else: logger.warning(f"Jav321 ImgUrls: PL (sidebar first) URL not found.")
            else: logger.warning(f"Jav321 ImgUrls: PL (sidebar first) tag not found.")

            # 3. Arts 이미지 추출 (사이드바 두 번째 이후, src 우선)
            arts_xpath = '/html/body/div[2]/div[2]/div[position()>1]//a[contains(@href, "/snapshot/")]/img'
            arts_img_nodes = tree.xpath(arts_xpath)
            temp_arts_list = []
            if arts_img_nodes:
                for img_node in arts_img_nodes:
                    src_val = img_node.attrib.get('src')
                    onerror_val = img_node.attrib.get('onerror')
                    
                    url_candidate_art = None
                    if src_val and src_val.strip():
                        url_candidate_art = cls._process_jav321_url_from_attribute(src_val)
                    if not url_candidate_art and onerror_val:
                        url_candidate_art = cls._process_jav321_url_from_attribute(onerror_val)
                    
                    if url_candidate_art: temp_arts_list.append(url_candidate_art)
            
            img_urls['arts'] = list(dict.fromkeys(temp_arts_list)) # 중복 제거
            
        except Exception as e_img_extract:
            logger.exception(f"Jav321 ImgUrls: Error extracting image URLs: {e_img_extract}")
        
        logger.debug(f"Jav321 ImgUrls Final: PS='{img_urls['ps']}', PL='{img_urls['pl']}', Arts({len(img_urls['arts'])})='{img_urls['arts'][:3]}...'")
        return img_urls


    @staticmethod
    def _clean_value(value_str):
        """주어진 문자열 값에서 앞뒤 공백 및 특정 접두사(': ')를 제거합니다."""
        if isinstance(value_str, str):
            cleaned = value_str.strip()
            if cleaned.startswith(": "):
                return cleaned[2:].strip()
            return cleaned
        return value_str


    @classmethod
    def __info(
        cls,
        code,
        do_trans=True,
        proxy_url=None,
        image_mode="0",
        max_arts=10,
        use_extras=True,
        dmm_parser_rules=None,
        **kwargs
    ):
        # === 1. 설정값 로드, 페이지 로딩, Entity 초기화 ===
        use_image_server = kwargs.get('use_image_server', False)
        image_server_url = kwargs.get('image_server_url', '').rstrip('/') if use_image_server else ''
        image_server_local_path = kwargs.get('image_server_local_path', '') if use_image_server else ''
        image_path_segment = kwargs.get('url_prefix_segment', 'unknown/unknown')
        ps_to_poster_labels_str = kwargs.get('ps_to_poster_labels_str', '')
        crop_mode_settings_str = kwargs.get('crop_mode_settings_str', '')
        maintain_series_number_labels_str = kwargs.get('maintain_series_number_labels', '')
        
        logger.debug(f"Jav321 Info: Starting for {code}. ImageMode: {image_mode}, UseImgServ: {use_image_server}")

        url_pid = code[2:]
        url = f"{cls.site_base_url}/video/{url_pid}"
        headers = SiteUtil.default_headers.copy(); headers['Referer'] = cls.site_base_url + "/"
        tree = None
        try:
            tree = SiteUtil.get_tree(url, proxy_url=proxy_url, headers=headers)
            if tree is None or not tree.xpath('/html/body/div[2]/div[1]/div[1]'): 
                logger.error(f"Jav321: Failed to get valid detail page tree for {code}. URL: {url}")
                return None
        except Exception as e_get_tree:
            logger.exception(f"Jav321: Exception while getting detail page for {code}: {e_get_tree}")
            return None

        entity = EntityMovie(cls.site_name, code)
        entity.country = ["일본"]; entity.mpaa = "청소년 관람불가"
        entity.thumb = []; entity.fanart = []; entity.extras = []
        
        maintain_labels_set = {lbl.strip().upper() for lbl in maintain_series_number_labels_str.split(',') if lbl.strip()}
        
        if '-' in url_pid:
            # 하이픈이 있는 경우, 자체 파서 로직을 위해 maintain_labels_set 전달
            entity.ui_code, _, _ = cls._parse_jav321_ui_code(url_pid, maintain_series_labels_set=maintain_labels_set)
        else:
            # 하이픈이 없는 경우, DMM 파서 로직을 위해 dmm_parser_rules 전달
            entity.ui_code, _, _ = cls._parse_jav321_ui_code(url_pid, dmm_parser_rules=dmm_parser_rules)

        ui_code_for_image = entity.ui_code.lower()
        entity.title = entity.originaltitle = entity.sorttitle = entity.ui_code
        logger.debug(f"Jav321 Info: Initial identifier from URL ('{url_pid}') parsed as: {ui_code_for_image}")

        ps_url_from_search_cache = cls._ps_url_cache.get(code)
        if ps_url_from_search_cache:
            logger.debug(f"Jav321: Found PS URL in cache for {code}: {ps_url_from_search_cache}")
        else:
            logger.debug(f"Jav321: No PS URL found in cache for {code}.")

        # === 2. 전체 메타데이터 파싱 (ui_code_for_image 확정 포함) ===
        identifier_parsed = bool(ui_code_for_image)
        raw_h3_title_text = "" # H3 제목 저장용
        try:
            logger.debug(f"Jav321: Parsing metadata for {code}...")

            # --- 제목(Tagline) 파싱 ---
            tagline_h3_nodes = tree.xpath('/html/body/div[2]/div[1]/div[1]/div[1]/h3')
            if tagline_h3_nodes:
                h3_node = tagline_h3_nodes[0]
                try:
                    h3_clone = deepcopy(h3_node)
                    for small_tag_node in h3_clone.xpath('.//small'):
                        small_tag_node.getparent().remove(small_tag_node) 
                    raw_h3_title_text = h3_clone.text_content().strip() 
                except Exception as e_remove_small_tag:
                    logger.warning(f"Jav321: Failed to remove <small> from H3, using full text. Error: {e_remove_small_tag}")
                    raw_h3_title_text = h3_node.text_content().strip()
            else: 
                logger.warning(f"Jav321: H3 title tag not found for {code}.")

            # --- 줄거리(Plot) 파싱 ---
            plot_div_nodes = tree.xpath('/html/body/div[2]/div[1]/div[1]/div[2]/div[3]/div')
            if plot_div_nodes:
                plot_full_text = plot_div_nodes[0].text_content().strip()
                if plot_full_text: 
                    entity.plot = SiteUtil.trans(cls._clean_value(plot_full_text), do_trans=do_trans)
            else:
                logger.warning(f"Jav321: Plot div (original XPath) not found for {code}.")

            # --- 부가 정보 파싱 (div class="col-md-9" 내부) ---
            info_container_node_list = tree.xpath('//div[contains(@class, "panel-body")]//div[contains(@class, "col-md-9")]')

            if info_container_node_list:
                info_node = info_container_node_list[0]
                all_b_tags = info_node.xpath("./b")

                for b_tag_key_node in all_b_tags:
                    current_key = cls._clean_value(b_tag_key_node.text_content()).replace(":", "")
                    if not current_key: continue

                    if current_key == "品番":
                        pid_value_nodes = b_tag_key_node.xpath("./following-sibling::text()[1][normalize-space()]")
                        pid_value_raw = pid_value_nodes[0].strip() if pid_value_nodes else ""
                        if not identifier_parsed: # URL에서 파싱 실패 시 백업
                            pid_value_raw = cls._clean_value(b_tag_key_node.xpath("./following-sibling::text()[1]")[0])
                            if pid_value_raw:
                                entity.ui_code, _, _ = cls._parse_jav321_ui_code(pid_value_raw, maintain_labels_set)
                                ui_code_for_image = entity.ui_code
                                entity.title = entity.originaltitle = entity.sorttitle = entity.ui_code
                                identifier_parsed = True
                                logger.warning(f"Jav321 Info: Fallback identifier from '品番': {ui_code_for_image}")

                    elif current_key == "出演者":
                        if entity.actor is None: entity.actor = []
                        if entity.actor is None: entity.actor = []
                        actor_a_tags = b_tag_key_node.xpath("./following-sibling::a[contains(@href, '/star/')]")
                        temp_actor_names = set()
                        for actor_link in actor_a_tags:
                            actor_name_raw = actor_link.text_content().strip()
                            actor_name_cleaned = cls._clean_value(actor_name_raw) # 배우 이름 클리닝
                            if actor_name_cleaned: temp_actor_names.add(actor_name_cleaned)

                        for name_item in temp_actor_names:
                            if not any(ea_item.name == name_item for ea_item in entity.actor):
                                entity.actor.append(EntityActor(name_item))

                    elif current_key == "メーカー":
                        studio_name_raw = ""
                        maker_a_tag = b_tag_key_node.xpath("./following-sibling::a[1][contains(@href, '/company/')]")
                        if maker_a_tag:
                            studio_name_raw = maker_a_tag[0].text_content().strip()
                        else:
                            maker_text_node = b_tag_key_node.xpath("./following-sibling::text()[1][normalize-space()]")
                            if maker_text_node:
                                studio_name_raw = maker_text_node[0].strip()

                        cleaned_studio_name = cls._clean_value(studio_name_raw)
                        if cleaned_studio_name:
                            entity.studio = SiteUtil.trans(cleaned_studio_name, do_trans=do_trans)

                    elif current_key == "ジャンル":
                        if entity.genre is None: entity.genre = []
                        genre_a_tags = b_tag_key_node.xpath("./following-sibling::a[contains(@href, '/genre/')]")
                        temp_genre_list = []
                        for genre_link in genre_a_tags:
                            genre_ja_raw = genre_link.text_content().strip()
                            genre_ja_cleaned = cls._clean_value(genre_ja_raw) # 장르 이름 클리닝
                            if not genre_ja_cleaned or genre_ja_cleaned in SiteUtil.av_genre_ignore_ja: continue

                            if genre_ja_cleaned in SiteUtil.av_genre: temp_genre_list.append(SiteUtil.av_genre[genre_ja_cleaned])
                            else:
                                genre_ko_item = SiteUtil.trans(genre_ja_cleaned, do_trans=do_trans).replace(" ", "")
                                if genre_ko_item not in SiteUtil.av_genre_ignore_ko: temp_genre_list.append(genre_ko_item)
                        if temp_genre_list: entity.genre = list(set(temp_genre_list))

                    elif current_key == "配信開始日":
                        date_val_nodes = b_tag_key_node.xpath("./following-sibling::text()[1][normalize-space()]")
                        date_val_raw = date_val_nodes[0].strip() if date_val_nodes else ""
                        date_val_cleaned = cls._clean_value(date_val_raw)
                        if date_val_cleaned: 
                            entity.premiered = date_val_cleaned.replace("/", "-")
                            if len(entity.premiered) >= 4 and entity.premiered[:4].isdigit():
                                try: entity.year = int(entity.premiered[:4])
                                except ValueError: entity.year = 0
                            else: entity.year = 0

                    elif current_key == "収録時間":
                        time_val_nodes = b_tag_key_node.xpath("./following-sibling::text()[1][normalize-space()]")
                        time_val_raw = time_val_nodes[0].strip() if time_val_nodes else ""
                        time_val_cleaned = cls._clean_value(time_val_raw)
                        if time_val_cleaned:
                            match_rt = re.search(r"(\d+)", time_val_cleaned)
                            if match_rt: entity.runtime = int(match_rt.group(1))

                    elif current_key == "シリーズ":
                        series_name_raw = ""
                        series_a_tag = b_tag_key_node.xpath("./following-sibling::a[1][contains(@href, '/series/')]")
                        if series_a_tag:
                            series_name_raw = series_a_tag[0].text_content().strip()
                        else:
                            series_text_node = b_tag_key_node.xpath("./following-sibling::text()[1][normalize-space()]")
                            if series_text_node:
                                series_name_raw = series_text_node[0].strip()

                        series_name_cleaned = cls._clean_value(series_name_raw)
                        if series_name_cleaned:
                            if entity.tag is None: entity.tag = []
                            trans_series = SiteUtil.trans(series_name_cleaned, do_trans=do_trans)
                            if trans_series and trans_series not in entity.tag: 
                                entity.tag.append(trans_series)

                    elif current_key == "平均評価":
                        rating_val_nodes = b_tag_key_node.xpath("./following-sibling::text()[1][normalize-space()]")
                        rating_val_raw = rating_val_nodes[0].strip() if rating_val_nodes else ""
                        rating_val_cleaned = cls._clean_value(rating_val_raw)
                        if rating_val_cleaned:
                            try: 
                                rating_float = float(rating_val_cleaned)
                                if entity.ratings is None: entity.ratings = [EntityRatings(rating_float, max=5, name=cls.site_name)]
                                else: entity.ratings[0].value = rating_float
                            except ValueError: logger.warning(f"Jav321: Could not parse rating value '{rating_val_cleaned}'")
            else: 
                logger.warning(f"Jav321: Main info container (col-md-9) not found for {code}.")

            # Tagline 최종 설정 (H3 제목에서 품번 제외)
            if raw_h3_title_text and ui_code_for_image:
                tagline_candidate_text = raw_h3_title_text
                if raw_h3_title_text.upper().startswith(ui_code_for_image): # 품번으로 시작하면 제거
                    tagline_candidate_text = raw_h3_title_text[len(ui_code_for_image):].strip()
                entity.tagline = SiteUtil.trans(cls._clean_value(tagline_candidate_text), do_trans=do_trans)
            elif raw_h3_title_text: 
                entity.tagline = SiteUtil.trans(cls._clean_value(raw_h3_title_text), do_trans=do_trans)

            if not identifier_parsed:
                logger.error(f"Jav321: CRITICAL - Identifier parse failed for {code} from any source.")
                ui_code_for_image = code[2:].upper().replace("_", "-") 
                entity.title = entity.originaltitle = entity.sorttitle = ui_code_for_image
                entity.ui_code = ui_code_for_image
            
            # 최종 정리 (plot, tagline 등)
            if entity.title: entity.title = cls._clean_value(entity.title) # 품번으로 설정된 title도 클리닝
            if entity.originaltitle: entity.originaltitle = cls._clean_value(entity.originaltitle)
            if entity.sorttitle: entity.sorttitle = cls._clean_value(entity.sorttitle)
            if not entity.tagline and entity.title: entity.tagline = entity.title
            if not entity.plot and entity.tagline: entity.plot = entity.tagline 
            elif not entity.plot and entity.title: entity.plot = entity.title # Plot도 최종적으로 없으면 Title

        except Exception as e_meta_main_final:
            logger.exception(f"Jav321: Major error during metadata parsing for {code}: {e_meta_main_final}")
            if not ui_code_for_image: return None

        label_from_ui_code_for_settings = ""
        if hasattr(entity, 'ui_code') and entity.ui_code:
            ui_code_for_image = entity.ui_code
            label_from_ui_code_for_settings = cls.get_label_from_ui_code(entity.ui_code)
            logger.debug(f"[{cls.site_name} Info] Extracted label for settings: '{label_from_ui_code_for_settings}' from ui_code '{entity.ui_code}'")
        else:
            logger.warning(f"[{cls.site_name} Info] entity.ui_code not found after parsing. Using fallback for image filenames.")
            ui_code_for_image = code[len(cls.module_char)+len(cls.site_char):].upper().replace("_", "-")

        apply_ps_to_poster_for_this_item = False
        forced_crop_mode_for_this_item = None

        # 포스터 예외처리 플래그 결정
        apply_ps_to_poster_for_this_item = False
        forced_crop_mode_for_this_item = None
        if label_from_ui_code_for_settings:
            if ps_to_poster_labels_str:
                ps_force_labels_set = {lbl.strip().upper() for lbl in ps_to_poster_labels_str.split(',') if lbl.strip()}
                if label_from_ui_code_for_settings in ps_force_labels_set:
                    apply_ps_to_poster_for_this_item = True
            if crop_mode_settings_str:
                for line in crop_mode_settings_str.splitlines():
                    if not line.strip(): continue
                    parts = [x.strip() for x in line.split(":", 1)]
                    if len(parts) == 2 and parts[0].upper() == label_from_ui_code_for_settings and parts[1].lower() in ["r", "l", "c"]:
                        forced_crop_mode_for_this_item = parts[1].lower(); break

        # === 3. 사용자 지정 포스터 확인 및 처리 ===
        user_custom_poster_url = None; user_custom_landscape_url = None
        skip_default_poster_logic = False; skip_default_landscape_logic = False
        if use_image_server and image_server_local_path and image_server_url and ui_code_for_image:
            poster_suffixes = ["_p_user.jpg", "_p_user.png", "_p_user.webp"]
            landscape_suffixes = ["_pl_user.jpg", "_pl_user.png", "_pl_user.webp"]
            for suffix in poster_suffixes:
                _, web_url = SiteUtil.get_user_custom_image_paths(image_server_local_path, image_path_segment, ui_code_for_image, suffix, image_server_url)
                if web_url: user_custom_poster_url = web_url; entity.thumb.append(EntityThumb(aspect="poster", value=user_custom_poster_url)); skip_default_poster_logic = True; logger.debug(f"MGStage ({cls.module_char}): Using user custom poster: {web_url}"); break 
            for suffix in landscape_suffixes:
                _, web_url = SiteUtil.get_user_custom_image_paths(image_server_local_path, image_path_segment, ui_code_for_image, suffix, image_server_url)
                if web_url: user_custom_landscape_url = web_url; entity.thumb.append(EntityThumb(aspect="landscape", value=user_custom_landscape_url)); skip_default_landscape_logic = True; logger.debug(f"MGStage ({cls.module_char}): Using user custom landscape: {web_url}"); break

        # --- 기본 이미지 처리 로직 진입 조건 ---
        needs_default_image_processing = not skip_default_poster_logic or \
                                         not skip_default_landscape_logic or \
                                         (entity.fanart is None or (len(entity.fanart) < max_arts and max_arts > 0))

        # === 4. 기본 이미지 처리: 사용자 지정 이미지가 없거나, 팬아트가 더 필요한 경우 실행 ===
        final_poster_source = None; final_poster_crop_mode = None
        final_landscape_url_source = None
        arts_urls_for_processing = []

        mgs_special_poster_filepath = None
        fixed_size_crop_applied = False

        if needs_default_image_processing:
            logger.debug(f"Jav321: Running default image logic for {code}...")
            try:
                img_urls_from_page = cls.__img_urls(tree)
                ps_from_detail_page = img_urls_from_page.get('ps')
                pl_from_detail_page = img_urls_from_page.get('pl')
                all_arts_from_page = img_urls_from_page.get('arts', [])

                now_printing_path = None
                if use_image_server and image_server_local_path:
                    now_printing_path = os.path.join(image_server_local_path, "now_printing.jpg")
                    if not os.path.exists(now_printing_path): now_printing_path = None

                # --- 유효한 PS 및 PL 후보 확정 (플레이스홀더 제외) ---
                valid_ps_candidate = None
                if ps_from_detail_page and not (now_printing_path and SiteUtil.are_images_visually_same(ps_from_detail_page, now_printing_path, proxy_url=proxy_url)):
                    valid_ps_candidate = ps_from_detail_page
                elif ps_url_from_search_cache and not (now_printing_path and SiteUtil.are_images_visually_same(ps_url_from_search_cache, now_printing_path, proxy_url=proxy_url)):
                    valid_ps_candidate = ps_url_from_search_cache
                else:
                    valid_ps_candidate = ps_url_from_search_cache
                    logger.warning(f"Jav321: No valid PS found.")

                valid_pl_candidate = None
                if pl_from_detail_page and not (now_printing_path and SiteUtil.are_images_visually_same(pl_from_detail_page, now_printing_path, proxy_url=proxy_url)):
                    valid_pl_candidate = pl_from_detail_page
                else:
                    logger.warning(f"Jav321: Detail page PL ('{pl_from_detail_page}') is a placeholder.")

                if valid_pl_candidate:
                    final_landscape_url_source = valid_pl_candidate

                # 1. 크롭 모드 사용자 설정
                if forced_crop_mode_for_this_item and valid_pl_candidate:
                    logger.debug(f"[{cls.site_name} Info] Poster determined by FORCED 'crop_mode={forced_crop_mode_for_this_item}'. Using PL: {valid_pl_candidate}")
                    final_poster_source = valid_pl_candidate
                    final_poster_crop_mode = forced_crop_mode_for_this_item

                # --- valid_ps_candidate 존재 유무에 따른 분기 ---
                if valid_ps_candidate:
                    # 포스터 결정 로직 (if not skip_default_poster_logic: 내부)
                    if not skip_default_poster_logic:
                        # 2. PS 강제 포스터 사용 설정
                        if apply_ps_to_poster_for_this_item and valid_ps_candidate:
                            logger.debug(f"[{cls.site_name} Info] Poster determined by FORCED 'ps_to_poster' setting. Using PS: {valid_ps_candidate}")
                            final_poster_source = valid_ps_candidate
                            final_poster_crop_mode = None

                    logger.debug(f"Jav321 Poster: Valid PS ('{valid_ps_candidate}') found. Proceeding with PS-comparison logic.")
                    if final_poster_source is None:
                        # --- 일반 비교 ---
                        specific_arts_candidates_ps = []
                        if all_arts_from_page:
                            # 플레이스홀더 아닌 Art만 후보로
                            temp_specific_arts = [art for art in all_arts_from_page if not (now_printing_path and SiteUtil.are_images_visually_same(art, now_printing_path, proxy_url=proxy_url))]
                            if temp_specific_arts:
                                if temp_specific_arts[0] not in specific_arts_candidates_ps: specific_arts_candidates_ps.append(temp_specific_arts[0])
                                if len(temp_specific_arts) > 1 and temp_specific_arts[-1] != temp_specific_arts[0] and temp_specific_arts[-1] not in specific_arts_candidates_ps:
                                    specific_arts_candidates_ps.append(temp_specific_arts[-1])

                        # 3. is_hq_poster
                        if valid_pl_candidate and SiteUtil.is_portrait_high_quality_image(valid_pl_candidate, proxy_url=proxy_url):
                            if SiteUtil.is_hq_poster(valid_ps_candidate, valid_pl_candidate, proxy_url=proxy_url):
                                final_poster_source = valid_pl_candidate
                        if final_poster_source is None and specific_arts_candidates_ps:
                            for art_candidate in specific_arts_candidates_ps:
                                if SiteUtil.is_portrait_high_quality_image(art_candidate, proxy_url=proxy_url):
                                    if SiteUtil.is_hq_poster(valid_ps_candidate, art_candidate, proxy_url=proxy_url):
                                        final_poster_source = art_candidate; break

                        # 4. 고정 크기 크롭
                        if not mgs_special_poster_filepath and \
                            (final_poster_source is None or final_poster_source == valid_ps_candidate) and \
                            valid_pl_candidate:
                            try:
                                pl_image_obj_for_fixed_crop = SiteUtil.imopen(valid_pl_candidate, proxy_url=proxy_url)
                                if pl_image_obj_for_fixed_crop:
                                    img_width, img_height = pl_image_obj_for_fixed_crop.size
                                    if img_width == 800 and 436 <= img_height <= 446:
                                        crop_box_fixed = (img_width - 380, 0, img_width, img_height) 
                                        cropped_pil_object = pl_image_obj_for_fixed_crop.crop(crop_box_fixed)
                                        if cropped_pil_object:
                                            final_poster_source = cropped_pil_object
                                            final_poster_crop_mode = None
                                            fixed_size_crop_applied = True
                                            logger.info(f"Jav321: Fixed-size crop (with PS) applied. Poster is PIL object.")
                            except Exception as e_fcs_ps: logger.error(f"Jav321: Error in fixed crop (with PS): {e_fcs_ps}")

                        # 5. MGS 스타일 처리
                        if (final_poster_source is None or final_poster_source == valid_ps_candidate) and valid_pl_candidate:
                            logger.debug(f"Jav321 Poster (with PS): Attempting MGS style for PL ('{valid_pl_candidate}') & PS ('{valid_ps_candidate}').")
                            _temp_filepath, _, _ = SiteUtil.get_mgs_half_pl_poster_info_local(valid_ps_candidate, valid_pl_candidate, proxy_url=proxy_url)
                            if _temp_filepath and os.path.exists(_temp_filepath):
                                mgs_special_poster_filepath = _temp_filepath
                                final_poster_source = mgs_special_poster_filepath
                                final_poster_crop_mode = None
                                logger.info(f"Jav321: MGS style (with PS) successful. Using temp file: {mgs_special_poster_filepath}")

                        # 6. has_hq_poster
                        if final_poster_source is None:
                            if valid_pl_candidate:
                                crop_pos = SiteUtil.has_hq_poster(valid_ps_candidate, valid_pl_candidate, proxy_url=proxy_url)
                                if crop_pos:
                                    final_poster_source = valid_pl_candidate; final_poster_crop_mode = crop_pos
                            if final_poster_source is None and specific_arts_candidates_ps:
                                for art_candidate in specific_arts_candidates_ps:
                                    crop_pos_art = SiteUtil.has_hq_poster(valid_ps_candidate, art_candidate, proxy_url=proxy_url)
                                    if crop_pos_art:
                                        final_poster_source = art_candidate; final_poster_crop_mode = crop_pos_art; break

                        # 7. PS 사용
                        if final_poster_source is None:
                            logger.debug(f"Jav321 Poster (with PS - Fallback): Using PS.")
                            final_poster_source = valid_ps_candidate
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

                # --- 팬아트 목록 결정 (플레이스홀더 제외) ---
                temp_fanart_list_final = []
                if all_arts_from_page:
                    sources_to_exclude_for_fanart = set()

                    if final_landscape_url_source: sources_to_exclude_for_fanart.add(final_landscape_url_source)
                    if final_poster_source and isinstance(final_poster_source, str) and final_poster_source.startswith("http"):
                        sources_to_exclude_for_fanart.add(final_poster_source)
                    if mgs_special_poster_filepath and final_poster_source == mgs_special_poster_filepath and valid_pl_candidate:
                        sources_to_exclude_for_fanart.add(valid_pl_candidate)
                    if fixed_size_crop_applied and valid_pl_candidate and isinstance(final_poster_source, Image.Image):
                        sources_to_exclude_for_fanart.add(valid_pl_candidate)

                    for art_url in all_arts_from_page:
                        if len(temp_fanart_list_final) >= max_arts: break
                        if art_url and art_url not in sources_to_exclude_for_fanart:
                            if not (now_printing_path and SiteUtil.are_images_visually_same(art_url, now_printing_path, proxy_url=proxy_url)):
                                if art_url not in temp_fanart_list_final:
                                    temp_fanart_list_final.append(art_url)
                arts_urls_for_processing = temp_fanart_list_final

            except Exception as e_img_proc_default:
                logger.exception(f"Jav321: Error during default image processing logic for {code}: {e_img_proc_default}")

            # === 5. 이미지 서버 저장 로직 (플레이스홀더 저장 방지) ===
            if use_image_server and image_mode == '4' and ui_code_for_image:
                logger.info(f"Jav321: Saving images to Image Server for {ui_code_for_image}")
                # 포스터 저장
                if not skip_default_poster_logic and final_poster_source:
                    is_final_poster_placeholder = False
                    if now_printing_path and isinstance(final_poster_source, str) and final_poster_source.startswith("http") and \
                    SiteUtil.are_images_visually_same(final_poster_source, now_printing_path, proxy_url=proxy_url):
                        is_final_poster_placeholder = True

                    if not is_final_poster_placeholder and not any(t.aspect == 'poster' for t in entity.thumb):
                        p_path = SiteUtil.save_image_to_server_path(final_poster_source, 'p', image_server_local_path, image_path_segment, ui_code_for_image, proxy_url=proxy_url, crop_mode=final_poster_crop_mode)
                        if p_path: entity.thumb.append(EntityThumb(aspect="poster", value=f"{image_server_url}/{p_path}"))
                    elif is_final_poster_placeholder:
                        logger.debug(f"Jav321 ImgServ: Final poster source ('{final_poster_source}') is a placeholder. Skipping save.")
                # 랜드스케이프 저장
                if not skip_default_landscape_logic and final_landscape_url_source:
                    if not (now_printing_path and SiteUtil.are_images_visually_same(final_landscape_url_source, now_printing_path, proxy_url=proxy_url)) and \
                    not any(t.aspect == 'landscape' for t in entity.thumb):
                        pl_path = SiteUtil.save_image_to_server_path(final_landscape_url_source, 'pl', image_server_local_path, image_path_segment, ui_code_for_image, proxy_url=proxy_url)
                        if pl_path: entity.thumb.append(EntityThumb(aspect="landscape", value=f"{image_server_url}/{pl_path}"))
                    elif (now_printing_path and SiteUtil.are_images_visually_same(final_landscape_url_source, now_printing_path, proxy_url=proxy_url)):
                        logger.debug(f"Jav321 ImgServ: Final landscape source ('{final_landscape_url_source}') is a placeholder. Skipping save.")

                # 팬아트 저장 (arts_urls_for_processing는 이미 플레이스홀더가 걸러진 리스트)
                if arts_urls_for_processing:
                    if entity.fanart is None: entity.fanart = []
                    current_fanart_urls_on_server = set([thumb.value for thumb in entity.thumb if thumb.aspect == 'fanart' and isinstance(thumb.value, str)] + \
                                                        [fanart_url for fanart_url in entity.fanart if isinstance(fanart_url, str)])
                    processed_fanart_count_server = len(current_fanart_urls_on_server)

                    for idx, art_url_item_server in enumerate(arts_urls_for_processing): # 이 리스트는 이미 플레이스홀더 걸러짐
                        if processed_fanart_count_server >= max_arts: break
                        # arts_urls_for_processing는 제외 로직도 이미 적용됨
                        art_relative_path = SiteUtil.save_image_to_server_path(art_url_item_server, 'art', image_server_local_path, image_path_segment, ui_code_for_image, art_index=idx + 1, proxy_url=proxy_url)
                        if art_relative_path:
                            full_art_url_server = f"{image_server_url}/{art_relative_path}"
                            if full_art_url_server not in current_fanart_urls_on_server:
                                entity.fanart.append(full_art_url_server)
                                current_fanart_urls_on_server.add(full_art_url_server)
                                processed_fanart_count_server +=1

        # === 6. 예고편 처리, Shiroutoname 보정 등 ===
        if use_extras:
            try: 
                trailer_xpath = '//*[@id="vjs_sample_player"]/source/@src'
                trailer_tags = tree.xpath(trailer_xpath)
                if trailer_tags:
                    trailer_url = trailer_tags[0].strip()
                    if trailer_url.startswith("http"):
                        trailer_title = entity.tagline if entity.tagline else entity.ui_code
                        entity.extras.append(EntityExtra("trailer", trailer_title, "mp4", trailer_url))
            except Exception as e_trailer:
                logger.exception(f"Jav321: Error processing trailer for {code}: {e_trailer}")

        # Shiroutoname 보정
        final_entity = entity
        if entity.originaltitle:
            try:
                # logger.debug(f"Jav321: Calling Shiroutoname correction for {entity.originaltitle}")
                final_entity = SiteUtil.shiroutoname_info(entity)
                # logger.debug(f"Jav321: Shiroutoname correction finished. New title (if changed): {final_entity.title}")
            except Exception as e_shirouto: 
                logger.exception(f"Jav321: Exception during Shiroutoname correction call for {entity.originaltitle}: {e_shirouto}")
        # else:
            # logger.warning(f"Jav321: Skipping Shiroutoname correction because originaltitle is missing for {code}.")

        # MGS 스타일 처리로 생성된 임시 파일 정리
        if mgs_special_poster_filepath and os.path.exists(mgs_special_poster_filepath):
            try:
                os.remove(mgs_special_poster_filepath)
                logger.debug(f"Jav321: Removed MGS-style temp poster file: {mgs_special_poster_filepath}")
            except Exception as e_remove_temp:
                logger.error(f"Jav321: Failed to remove MGS-style temp poster file {mgs_special_poster_filepath}: {e_remove_temp}")


        logger.info(f"Jav321: __info processing finished for {code}. UI Code: {ui_code_for_image}, PosterSkip: {skip_default_poster_logic}, LandscapeSkip: {skip_default_landscape_logic}, EntityThumbs: {len(entity.thumb)}, EntityFanarts: {len(entity.fanart)}")
        return final_entity


    @classmethod
    def info(cls, code, **kwargs):
        ret = {}
        try:
            entity = cls.__info(code, **kwargs)
            if entity:
                ret["ret"] = "success"; ret["data"] = entity.as_dict()
            else:
                ret["ret"] = "error"; ret["data"] = f"Failed to get Jav321 info entity for {code}"
        except Exception as exception:
            logger.exception("메타 정보 처리 중 예외:")
            ret["ret"] = "exception"; ret["data"] = str(exception)
        return ret
