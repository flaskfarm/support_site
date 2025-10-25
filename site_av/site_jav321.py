import re
import os
from lxml import html
from copy import deepcopy

from ..entity_av import EntityAVSearch
from ..entity_base import EntityActor, EntityExtra, EntityMovie, EntityRatings, EntityThumb
from ..setup import P, logger
from .site_av_base import SiteAvBase
from ..constants import AV_GENRE_IGNORE_JA, AV_GENRE, AV_GENRE_IGNORE_KO

SITE_BASE_URL = "https://www.jav321.com"

class SiteJav321(SiteAvBase):
    site_name = "jav321"
    site_char = "T"
    module_char = "C"

    default_headers = SiteAvBase.base_default_headers.copy()
    default_headers.update({"Referer": SITE_BASE_URL + "/"})
    _ps_url_cache = {}

    ################################################
    # region SEARCH

    @classmethod
    def search(cls, keyword, do_trans, manual):
        ret = {}
        try:
            data = cls.__search(keyword, do_trans, manual)
        except Exception as exception:
            logger.exception("검색 결과 처리 중 예외:")
            ret["ret"] = "exception"; ret["data"] = str(exception)
        else:
            ret["ret"] = "success" if data else "no_match"; ret["data"] = data
        return ret


    @classmethod
    def __search(cls, keyword, do_trans, manual):
        original_keyword = keyword
        # 전역 파서를 사용하여 검색 키워드를 우선 정규화
        kw_ui_code, _, _ = cls._parse_ui_code(original_keyword)
        keyword_for_url = kw_ui_code

        logger.debug(f"Jav321 Search: original='{original_keyword}', parsed_kw='{kw_ui_code}', url_kw='{keyword_for_url}'")

        res = cls.get_response(f"{SITE_BASE_URL}/search", post_data={"sn": keyword_for_url})

        if res is None:
            logger.error(f"Jav321 Search: Failed to get response for keyword '{keyword_for_url}'.")
            return []

        if not res.history or not res.url.startswith(SITE_BASE_URL + "/video/"):
            logger.debug(f"Jav321 Search: No direct match or multiple results for keyword '{keyword_for_url}'. Final URL: {res.url}")
            return []

        ret = []
        try:
            item = EntityAVSearch(cls.site_name)

            code_from_url_path = res.url.split("/")[-1]
            item.code = cls.module_char + cls.site_char + code_from_url_path

            # --- 점수 계산 로직 (DMM 스타일 표준화) ---
            # 검색어와 결과 URL의 품번을 모두 파싱
            kw_ui_code, kw_label_part, kw_num_part = cls._parse_ui_code(original_keyword)
            item_ui_code, item_label_part, item_num_part = cls._parse_ui_code(code_from_url_path)
            item.ui_code = item_ui_code

            # 숫자 부분을 정규화하여 비교
            kw_num_norm = kw_num_part.lstrip('0') or '0'
            item_num_norm = item_num_part.lstrip('0') or '0'

            # 점수 부여
            if kw_num_norm == item_num_norm and (kw_label_part.lower().endswith(item_label_part.lower()) or item_label_part.lower().endswith(kw_label_part.lower())):
                item.score = 100 # 기본 점수
                if kw_label_part.lower() != item_label_part.lower():
                    item.score -= 1 # 접두사 차이 페널티
            
            # elif를 사용하여, 위 조건이 실패했을 때만 기존의 ui_code 비교 수행
            elif kw_ui_code.lower() == item_ui_code.lower():
                item.score = 95 # ui_code가 정확히 일치하면 95점
            else:
                item.score = 60 # 그 외는 60점

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

            processed_ps_url = cls._process_jav321_url_from_attribute(raw_ps_url) if raw_ps_url else ""
            item.image_url = processed_ps_url

            if item.code and processed_ps_url:
                cls._ps_url_cache[item.code] = processed_ps_url
                # logger.debug(f"Jav321 Search: Cached PS URL for {item.code}: {processed_ps_url}")

            date_tags = tree.xpath(f'{base_xpath}/div[2]/div[1]/div[2]/b[contains(text(),"配信開始日")]/following-sibling::text()')
            date_str = date_tags[0].lstrip(":").strip() if date_tags and date_tags[0].lstrip(":").strip() else "1900-01-01"
            item.desc = f"발매일: {date_str}"
            try: item.year = int(date_str[:4])
            except ValueError: item.year = 1900

            title_tags = tree.xpath(f"{base_xpath}/div[1]/h3/text()")
            item.title = title_tags[0].strip() if title_tags else "제목 없음"

            if manual:
                if cls.config['use_proxy']:
                    item.image_url = cls.make_image_url(item.image_url)
                item.title_ko = "(현재 인터페이스에서는 번역을 제공하지 않습니다) " + item.title
            else:
                item.title_ko = cls.trans(item.title)

            item_dict = item.as_dict()

            # --- 우선순위 레이블 처리 로직 추가 ---
            item_dict['is_priority_label_site'] = False
            item_dict['site_key'] = cls.site_name

            if item_dict.get('ui_code') and cls.config.get('priority_labels_set'):
                label_to_check = item_dict['ui_code'].split('-', 1)[0]
                if label_to_check in cls.config['priority_labels_set']:
                    item_dict['is_priority_label_site'] = True

            ret.append(item_dict)

        except Exception as e_item_search:
            logger.exception(f"Jav321 Search: Error processing single direct match: {e_item_search}")

        if ret:
            logger.debug(f"Score={item.score}, Code={item.code}, UI Code={item.ui_code}, Title='{item.title_ko}'")
        return ret


    # endregion SEARCH
    ################################################


    ################################################
    # region INFO

    @classmethod
    def info(cls, code, keyword=None, fp_meta_mode=False):
        ret = {}
        entity_result_val_final = None
        try:
            entity_result_val_final = cls.__info(code, keyword=keyword, fp_meta_mode=fp_meta_mode).as_dict()
            if entity_result_val_final:
                ret["ret"] = "success"
                ret["data"] = entity_result_val_final
            else:
                ret["ret"] = "error"
                ret["data"] = f"Failed to get Jav321 info for {code}"
        except Exception as e:
            ret["ret"] = "exception"
            ret["data"] = str(e)
            logger.exception(f"Jav321 info error: {e}")
        return ret


    @classmethod
    def __info(cls, code, keyword=None, fp_meta_mode=False):
        url_pid = code[2:]
        url = f"{SITE_BASE_URL}/video/{url_pid}"
        tree = None
        try:
            tree = cls.get_tree(url)
            if tree is None or not tree.xpath('/html/body/div[2]/div[1]/div[1]'): 
                logger.error(f"Jav321: Failed to get valid detail page tree for {code}. URL: {url}")
                return None
        except Exception as e_get_tree:
            logger.exception(f"Jav321: Exception while getting detail page for {code}: {e_get_tree}")
            return None

        entity = EntityMovie(cls.site_name, code)
        entity.country = ["일본"]; entity.mpaa = "청소년 관람불가"
        entity.thumb = []; entity.fanart = []; entity.extras = []; entity.ratings = []
        entity.original = {}
        ui_code_for_image = ""
        mgs_special_poster_filepath = None

        try:
            # === 2. 메타데이터 파싱 ===
            if not keyword:
                try:
                    cache = F.get_cache(f"{P.package_name}_jav_censored_keyword_cache")
                    keyword = cache.get(code)
                    if keyword:
                        logger.debug(f"[{cls.site_name} Info] Restored keyword '{keyword}' from cache for code '{code}'.")
                except Exception as e:
                    logger.warning(f"[{cls.site_name} Info] Failed to get keyword from cache: {e}")

            if keyword:
                trusted_ui_code, _, _ = cls._parse_ui_code(keyword)
                logger.debug(f"Jav321 Info: Using trusted UI code '{trusted_ui_code}' from keyword '{keyword}'.")
            else:
                url_pid = code[2:]
                trusted_ui_code, _, _ = cls._parse_ui_code(url_pid)
                logger.debug(f"Jav321 Info: No keyword. Using UI code '{trusted_ui_code}' from URL part '{url_pid}'.")

            entity.ui_code = trusted_ui_code
            entity.title = entity.originaltitle = entity.sorttitle = entity.ui_code

            tagline_h3_nodes = tree.xpath('/html/body/div[2]/div[1]/div[1]/div[1]/h3')
            if tagline_h3_nodes:
                h3_node = tagline_h3_nodes[0]
                try:
                    h3_clone = deepcopy(h3_node)
                    for small_tag_node in h3_clone.xpath('.//small'):
                        small_tag_node.getparent().remove(small_tag_node) 
                    raw_h3_title_text = h3_clone.text_content().strip() 
                except Exception as e_remove_small_tag:
                    raw_h3_title_text = h3_node.text_content().strip()

            plot_div_nodes = tree.xpath('/html/body/div[2]/div[1]/div[1]/div[2]/div[3]/div')
            if plot_div_nodes:
                plot_full_text = plot_div_nodes[0].text_content().strip()
                if plot_full_text:
                    cleaned_plot = cls.A_P(cls._clean_value(plot_full_text))
                    entity.original['plot'] = cleaned_plot
                    entity.plot = cls.trans(cleaned_plot)

            info_container_node_list = tree.xpath('//div[contains(@class, "panel-body")]//div[contains(@class, "col-md-9")]')
            if info_container_node_list:
                info_node = info_container_node_list[0]
                all_b_tags = info_node.xpath("./b")
                for b_tag_key_node in all_b_tags:
                    current_key = cls._clean_value(b_tag_key_node.text_content()).replace(":", "")
                    if not current_key: continue

                    if current_key == "品番":
                        pid_value_raw = (b_tag_key_node.xpath("./following-sibling::text()[1][normalize-space()]") or [""])[0].strip()
                        if pid_value_raw:
                            # 페이지의 품번은 검증용으로만 사용.
                            parsed_pid_from_page, _, _ = cls._parse_ui_code(pid_value_raw)
                            core_trusted = re.sub(r'[^A-Z0-9]', '', trusted_ui_code.upper())
                            core_page = re.sub(r'[^A-Z0-9]', '', parsed_pid_from_page.upper())

                            if not (core_trusted in core_page or core_page in core_trusted):
                                logger.warning(f"Jav321 Info: Significant UI code mismatch detected!")
                                logger.warning(f"  - Trusted UI Code: {trusted_ui_code}")
                                logger.warning(f"  - Page UI Code (for verification): {parsed_pid_from_page}")

                    elif current_key == "出演者":
                        if entity.actor is None: entity.actor = []
                        actor_a_tags = b_tag_key_node.xpath("./following-sibling::a[contains(@href, '/star/')]")
                        temp_actor_names = set()
                        for actor_link in actor_a_tags:
                            actor_name_cleaned = cls._clean_value(actor_link.text_content().strip())
                            if actor_name_cleaned: temp_actor_names.add(actor_name_cleaned)
                        for name_item in temp_actor_names:
                            if not any(ea_item.name == name_item for ea_item in entity.actor):
                                entity.actor.append(EntityActor(name_item))
                    elif current_key == "メーカー":
                        studio_name_raw = (b_tag_key_node.xpath("./following-sibling::a[1][contains(@href, '/company/')]/text()") or [""])[0]
                        if not studio_name_raw: studio_name_raw = (b_tag_key_node.xpath("./following-sibling::text()[1][normalize-space()]") or [""])[0]
                        cleaned_studio_name = cls._clean_value(studio_name_raw)
                        if cleaned_studio_name:
                            entity.original['studio'] = cleaned_studio_name
                            entity.studio = cls.trans(cleaned_studio_name)
                    elif current_key == "ジャンル":
                        if entity.genre is None: entity.genre = []
                        if 'genre' not in entity.original: 
                            entity.original['genre'] = []
                        genre_a_tags = b_tag_key_node.xpath("./following-sibling::a[contains(@href, '/genre/')]")
                        temp_genre_list = []
                        for genre_link in genre_a_tags:
                            genre_ja_cleaned = cls._clean_value(genre_link.text_content().strip())
                            if not genre_ja_cleaned or genre_ja_cleaned in AV_GENRE_IGNORE_JA: continue
                            entity.original['genre'].append(genre_ja_cleaned)
                            if genre_ja_cleaned in AV_GENRE: 
                                temp_genre_list.append(AV_GENRE[genre_ja_cleaned])
                            else:
                                genre_ko_item = cls.trans(genre_ja_cleaned).replace(" ", "")
                                if genre_ko_item not in AV_GENRE_IGNORE_KO: 
                                    temp_genre_list.append(genre_ko_item)
                        if temp_genre_list: entity.genre = list(set(temp_genre_list))
                    elif current_key == "配信開始日":
                        date_val_cleaned = cls._clean_value((b_tag_key_node.xpath("./following-sibling::text()[1][normalize-space()]") or [""])[0])
                        if date_val_cleaned: 
                            entity.premiered = date_val_cleaned.replace("/", "-")
                            if len(entity.premiered) >= 4 and entity.premiered[:4].isdigit():
                                try: entity.year = int(entity.premiered[:4])
                                except ValueError: entity.year = 0
                    elif current_key == "収録時間":
                        time_val_cleaned = cls._clean_value((b_tag_key_node.xpath("./following-sibling::text()[1][normalize-space()]") or [""])[0])
                        if time_val_cleaned:
                            match_rt = re.search(r"(\d+)", time_val_cleaned)
                            if match_rt: entity.runtime = int(match_rt.group(1))
                    elif current_key == "シリーズ":
                        series_name_raw = (b_tag_key_node.xpath("./following-sibling::a[1][contains(@href, '/series/')]/text()") or [""])[0]
                        if not series_name_raw: series_name_raw = (b_tag_key_node.xpath("./following-sibling::text()[1][normalize-space()]") or [""])[0]
                        series_name_cleaned = cls._clean_value(series_name_raw)
                        if series_name_cleaned:
                            if entity.tag is None: entity.tag = []
                            entity.original['series'] = series_name_cleaned
                            tag_to_add = cls.trans(series_name_cleaned)
                            if tag_to_add and tag_to_add not in entity.tag: entity.tag.append(tag_to_add)
                    elif current_key == "平均評価":
                        rating_val_cleaned = cls._clean_value((b_tag_key_node.xpath("./following-sibling::text()[1][normalize-space()]") or [""])[0])
                        if rating_val_cleaned:
                            try: 
                                rating_float = float(rating_val_cleaned)
                                entity.ratings = [EntityRatings(rating_float, max=5, name=cls.site_name)]
                            except ValueError: pass

            if raw_h3_title_text:
                tagline_candidate_text = raw_h3_title_text
                if raw_h3_title_text.upper().startswith(entity.ui_code.upper()):
                    tagline_candidate_text = raw_h3_title_text[len(entity.ui_code):].strip()
                cleaned_tagline = cls.A_P(cls._clean_value(tagline_candidate_text))
                entity.original['tagline'] = cleaned_tagline
                entity.tagline = cls.trans(cleaned_tagline)

            if not entity.tagline and entity.title: entity.tagline = entity.title
            if not entity.plot and entity.tagline: entity.plot = entity.tagline 

            # === 3. 이미지 처리 위임 ===
            ps_url_from_search_cache = cls._ps_url_cache.get(code)

            try:
                raw_image_urls = cls.__img_urls(tree)
                entity = cls.process_image_data(entity, raw_image_urls, ps_url_from_search_cache)

            except Exception as e:
                logger.exception(f"Jav321: Error during image processing delegation for {code}: {e}")

            # === 4. 예고편 및 Shiroutoname 보정 처리 ===
            if cls.config['use_extras']:
                try: 
                    trailer_xpath = '//*[@id="vjs_sample_player"]/source/@src'
                    trailer_tags = tree.xpath(trailer_xpath)
                    if trailer_tags and trailer_tags[0].strip().startswith("http"):
                        url = cls.make_video_url(trailer_tags[0].strip())
                        if url:
                            entity.extras.append(EntityExtra("trailer", entity.tagline or entity.ui_code, "mp4", url))
                except Exception as e_trailer: logger.exception(f"Jav321: Error processing trailer for {code}: {e_trailer}")

            if entity.originaltitle:
                try:
                    entity = cls.shiroutoname_info(entity)
                except Exception as e_shirouto:
                    logger.exception(f"Jav321: Shiroutoname error: {e_shirouto}")

            try:
                title_to_check = entity.original.get('tagline', entity.tagline or "")
                if re.search(r'[\[【]\s*VR\s*[\]】]', title_to_check, re.IGNORECASE):
                    logger.debug(f"[{cls.site_name}] VR keyword detected in title. Setting content_type to 'vr'.")
                    vr_genre_original = "VR"
                    if vr_genre_original not in entity.original.get('genre', []):
                        if 'genre' not in entity.original: entity.original['genre'] = []
                        entity.original['genre'].append(vr_genre_original)
                    vr_genre_translated = "VR"
                    if vr_genre_translated not in entity.genre:
                        entity.genre.append(vr_genre_translated)
            except Exception as e_vr_check:
                logger.error(f"[{cls.site_name}] Error during VR check: {e_vr_check}")

            logger.info(f"Jav321: __info finished for {code}. UI Code: {ui_code_for_image}")
            return entity

        except Exception as e_main:
            logger.exception(f"Jav321: Major error during info processing for {code}: {e_main}")
            return None

        finally:
            # === 6. 임시 파일 정리 ===
            if mgs_special_poster_filepath and os.path.exists(mgs_special_poster_filepath):
                try:
                    os.remove(mgs_special_poster_filepath)
                    logger.debug(f"Jav321: Removed MGS-style temp poster file: {mgs_special_poster_filepath}")
                except Exception as e_remove_temp:
                    logger.error(f"Jav321: Failed to remove MGS-style temp poster file {mgs_special_poster_filepath}: {e_remove_temp}")


    @classmethod
    def __img_urls(cls, tree):
        try:
            # 1. 페이지에서 원본 URL 수집
            raw_ps_url, raw_pl_url = "", ""
            ps_img_node = tree.xpath('/html/body/div[2]/div[1]/div[1]/div[2]/div[1]/div[1]/img')
            if ps_img_node:
                raw_ps_url = ps_img_node[0].attrib.get('src') or ps_img_node[0].attrib.get('onerror', '')

            pl_img_node = tree.xpath('/html/body/div[2]/div[2]/div[1]/p/a/img')
            if pl_img_node:
                raw_pl_url = pl_img_node[0].attrib.get('src') or pl_img_node[0].attrib.get('onerror', '')

            raw_sample_images = []
            arts_img_nodes = tree.xpath('/html/body/div[2]/div[2]/div[position()>1]//a[contains(@href, "/snapshot/")]/img')
            for img_node in arts_img_nodes:
                raw_sample_images.append(img_node.attrib.get('src') or img_node.attrib.get('onerror', ''))

            # 2. 모든 URL에 _process_jav321_url_from_attribute 적용
            ps_url = cls._process_jav321_url_from_attribute(raw_ps_url)
            pl_url = cls._process_jav321_url_from_attribute(raw_pl_url)
            all_sample_images = [cls._process_jav321_url_from_attribute(url) for url in raw_sample_images if url]
            all_sample_images = list(dict.fromkeys(all_sample_images))

            # 3. 역할에 맞게 데이터 분류 (중복 제거 포함)
            thumb_candidates = set()
            if pl_url: thumb_candidates.add(pl_url)

            specific_poster_candidates = []
            if all_sample_images:
                first_art = all_sample_images[0]
                specific_poster_candidates.append(first_art)
                thumb_candidates.add(first_art)
                if len(all_sample_images) > 1 and all_sample_images[-1] != first_art:
                    last_art = all_sample_images[-1]
                    specific_poster_candidates.append(last_art)
                    thumb_candidates.add(last_art)

            pure_arts = [art for art in all_sample_images if art and art not in thumb_candidates]

            # 4. 최종 결과 반환
            ret = {
                "ps": ps_url, "pl": pl_url,
                "specific_poster_candidates": specific_poster_candidates,
                "arts": pure_arts
            }
            logger.debug(f"Jav321 __img_urls collected: PS='{ret['ps']}', PL='{ret['pl']}', ...")
            return ret

        except Exception as e_img_extract:
            logger.exception(f"Jav321 ImgUrls: Error extracting image URLs: {e_img_extract}")
            return {'ps': "", 'pl': "", 'arts': [], 'specific_poster_candidates': []}



    # endregion INFO
    ################################################


    ################################################
    # region UTILITY METHODS

    @classmethod
    def _clean_value(cls, value_str):
        """주어진 문자열 값에서 앞뒤 공백 및 특정 접두사(': ')를 제거합니다."""
        if isinstance(value_str, str):
            cleaned = value_str.strip()
            if cleaned.startswith(": "):
                return cleaned[2:].strip()
            return cleaned
        return value_str


    @classmethod
    def _parse_jav321_ui_code(cls, code_str: str, maintain_series_labels_set: set = None) -> tuple:
        if not code_str or not isinstance(code_str, str): 
            return "", "", ""
        if maintain_series_labels_set is None: 
            maintain_series_labels_set = set()
        
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
            #if dmm_parser_rules is None: dmm_parser_rules = {}

            # 'videoa'를 우선 시도하고, 실패 시 'dvd'로 폴백
            ui_code_videoa, label_videoa, num_videoa = cls._parse_ui_code(
                code_str, 'videoa')
            
            # videoa 파싱이 성공적이면 바로 반환
            if label_videoa and num_videoa:
                return ui_code_videoa, label_videoa, num_videoa
            
            # videoa 파싱 실패 시, dvd 파싱 시도
            logger.debug(f"Jav321 Parser: 'videoa' parsing failed for '{code_str}'. Falling back to 'dvd' type.")
            ui_code_dvd, label_dvd, num_dvd = cls._parse_ui_code(
                code_str, 'dvd')
            return ui_code_dvd, label_dvd, num_dvd


    @classmethod
    def _process_jav321_url_from_attribute(cls, url_attribute_value):
        """
        img 태그 속성값에서 URL을 추출하고, 중복 슬래시(//)를 보존하여 반환합니다.
        """
        if not url_attribute_value:
            return "" # None 대신 빈 문자열 반환하여 타입 일관성 유지
        
        raw_url = ""
        if "this.src='" in url_attribute_value:
            url_match = re.search(r"this\.src='([^']+)'", url_attribute_value)
            if url_match:
                raw_url = url_match.group(1).strip()
        else:
            raw_url = url_attribute_value.strip()

        if not raw_url:
            return ""

        # 프로토콜 보장
        if raw_url.startswith("//"):
            raw_url = "https:" + raw_url
        
        # <<-- START: 중복 슬래시 보존 로직 -->>
        # requests나 urlparse를 사용하면 //가 /로 합쳐지므로, 단순 문자열 처리로만 구성한다.
        # 예: http://.../path//subpath -> http://.../path//subpath (유지)
        # 예: http://...//path/subpath -> http://...//path/subpath (유지)
        # 이미 올바른 형식이므로 특별한 처리가 필요 없음.
        # 단, pics.dmm.co.jp/digital... 형태의 URL이 //를 필요로 한다면 명시적 처리가 필요.
        # 로그를 보면 PL URL에 //가 있으므로, 해당 패턴에 대해서만 보장해준다.
        if 'pics.dmm.co.jp/digital/video' in raw_url:
            # http(s)://pics.dmm.co.jp/digital/video -> http(s)://pics.dmm.co.jp//digital/video
            processed_url = raw_url.replace(
                'pics.dmm.co.jp/digital/video', 
                'pics.dmm.co.jp//digital/video'
            )
            # 만약 이미 //가 있다면 중복되지 않도록 방지
            processed_url = processed_url.replace('//digital//video', '//digital/video')
        else:
            processed_url = raw_url
        # <<-- END: 중복 슬래시 보존 로직 -->>

        return processed_url


    # --- 삭제할 코드 ---
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


    # endregion UTILITY METHODS
    ################################################


    ################################################
    # region SiteAvBase 메서드 오버라이드

    @classmethod
    def set_config(cls, db):
        super().set_config(db)
        cls.config.update({
            "ps_force_labels_list": db.get_list(f"jav_censored_{cls.site_name}_small_image_to_poster", ","),
            "crop_mode": db.get_list(f"jav_censored_{cls.site_name}_crop_mode", ","),
            "priority_labels": db.get_list(f"jav_censored_{cls.site_name}_priority_search_labels", ","),
        })
        cls.config['ps_force_labels_set'] = {lbl.strip().upper() for lbl in cls.config.get('ps_force_labels_list', []) if lbl.strip()}
        cls.config['priority_labels_set'] = {lbl.strip().upper() for lbl in cls.config.get('priority_labels', []) if lbl.strip()}


    # endregion SiteAvBase 메서드 오버라이드
    ################################################

