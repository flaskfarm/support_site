import re
import os
from lxml import html
from copy import deepcopy

from ..entity_av import EntityAVSearch
from ..entity_base import EntityActor, EntityExtra, EntityMovie, EntityRatings, EntityThumb
from ..setup import P, logger
from ..site_util_av import SiteUtilAv as SiteUtil
from .site_dmm import SiteDmm
from .site_av_base import SiteAvBase

SITE_BASE_URL = "https://www.jav321.com"

class SiteJav321(SiteAvBase):
    site_name = "jav321"
    site_char = "T"
    module_char = "C"
    default_headers = SiteAvBase.base_default_headers.copy()
    default_headers.update({'Referer': SITE_BASE_URL + '/'})
    _ps_url_cache = {} 

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
        temp_keyword = keyword.strip().lower()
        temp_keyword = re.sub(r'[-_]?cd\d*$', '', temp_keyword, flags=re.I)
        keyword_for_url = temp_keyword.strip('-_ ')

        logger.debug(f"Jav321 Search: original_keyword='{original_keyword}', keyword_for_url='{keyword_for_url}'")
        
        res = cls.get_response(
            f"{SITE_BASE_URL}/search",
            post_data={"sn": keyword_for_url}
        )

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

            # --- 점수 계산 로직 ---
            # 1. 검색어와 아이템 코드를 각각 파싱
            _, search_label_part, search_num_part = cls._parse_jav321_ui_code(original_keyword, cls.config['maintain_series_number_labels'])
            
            item.ui_code, item_label_part, item_num_part = cls._parse_jav321_ui_code(code_from_url_path, cls.config['maintain_series_number_labels'])

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
                if cls.config['use_proxy']:
                    item.image_url = cls.make_image_url(item.image_url)
                item.title_ko = "(현재 인터페이스에서는 번역을 제공하지 않습니다) " + item.title
            else:
                item.title_ko = cls.trans(item.title, do_trans=do_trans)

            if item.code:
                if item.image_url: 
                    cls._ps_url_cache[item.code] = item.image_url
                item_dict = item.as_dict()
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
    def info(cls, code):
        ret = {}
        try:
            entity = cls.__info(code)
            if entity:
                ret["ret"] = "success"; ret["data"] = entity.as_dict()
            else:
                ret["ret"] = "error"; ret["data"] = f"Failed to get Jav321 info entity for {code}"
        except Exception as exception:
            logger.exception("메타 정보 처리 중 예외:")
            ret["ret"] = "exception"; ret["data"] = str(exception)
        return ret
    

    @classmethod
    def __info(cls, code):
        url_pid = code[2:]
        url = f"{SITE_BASE_URL}/video/{url_pid}"
        headers = SiteUtil.default_headers.copy(); headers['Referer'] = SITE_BASE_URL + "/"
        tree = None
        try:
            tree = cls.get_tree(url, headers=headers)
            if tree is None or not tree.xpath('/html/body/div[2]/div[1]/div[1]'): 
                logger.error(f"Jav321: Failed to get valid detail page tree for {code}. URL: {url}")
                return None
        except Exception as e_get_tree:
            logger.exception(f"Jav321: Exception while getting detail page for {code}: {e_get_tree}")
            return None

        entity = EntityMovie(cls.site_name, code)
        entity.country = ["일본"]; entity.mpaa = "청소년 관람불가"
        entity.thumb = []; entity.fanart = []; entity.extras = []; entity.ratings = []
        ui_code_for_image = ""
        mgs_special_poster_filepath = None

        try:
            # === 2. 메타데이터 파싱 ===
            if '-' in url_pid:
                entity.ui_code, _, _ = cls._parse_jav321_ui_code(url_pid, maintain_series_labels_set=cls.config['maintain_series_number_labels'])
            else:
                entity.ui_code, _, _ = cls._parse_jav321_ui_code(url_pid)

            ui_code_for_image = entity.ui_code.lower()
            entity.title = entity.originaltitle = entity.sorttitle = entity.ui_code
            logger.debug(f"Jav321 Info: Initial identifier from URL ('{url_pid}') parsed as: {ui_code_for_image}")
       
            
            identifier_parsed = bool(ui_code_for_image)
            raw_h3_title_text = ""
            
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
                    entity.plot = cls.trans(cls._clean_value(plot_full_text))

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
                        if not identifier_parsed and pid_value_raw:
                            entity.ui_code, _, _ = cls._parse_jav321_ui_code(pid_value_raw, maintain_series_labels_set=cls.config['maintain_series_number_labels'])
                            ui_code_for_image = entity.ui_code
                            entity.title = entity.originaltitle = entity.sorttitle = entity.ui_code
                            identifier_parsed = True
                            logger.warning(f"Jav321 Info: Fallback identifier from '品番': {ui_code_for_image}")
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
                        if cleaned_studio_name: entity.studio = cls.trans(cleaned_studio_name)
                    elif current_key == "ジャンル":
                        if entity.genre is None: entity.genre = []
                        genre_a_tags = b_tag_key_node.xpath("./following-sibling::a[contains(@href, '/genre/')]")
                        temp_genre_list = []
                        for genre_link in genre_a_tags:
                            genre_ja_cleaned = cls._clean_value(genre_link.text_content().strip())
                            if not genre_ja_cleaned or genre_ja_cleaned in SiteUtil.av_genre_ignore_ja: continue
                            if genre_ja_cleaned in SiteUtil.av_genre: temp_genre_list.append(SiteUtil.av_genre[genre_ja_cleaned])
                            else:
                                genre_ko_item = cls.trans(genre_ja_cleaned).replace(" ", "")
                                if genre_ko_item not in SiteUtil.av_genre_ignore_ko: temp_genre_list.append(genre_ko_item)
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
                            trans_series = cls.trans(series_name_cleaned)
                            if trans_series and trans_series not in entity.tag: entity.tag.append(trans_series)
                    elif current_key == "平均評価":
                        rating_val_cleaned = cls._clean_value((b_tag_key_node.xpath("./following-sibling::text()[1][normalize-space()]") or [""])[0])
                        if rating_val_cleaned:
                            try: 
                                rating_float = float(rating_val_cleaned)
                                entity.ratings = [EntityRatings(rating_float, max=5, name=cls.site_name)]
                            except ValueError: pass

            if raw_h3_title_text and ui_code_for_image:
                tagline_candidate_text = raw_h3_title_text
                if raw_h3_title_text.upper().startswith(ui_code_for_image.upper()):
                    tagline_candidate_text = raw_h3_title_text[len(ui_code_for_image):].strip()
                entity.tagline = cls.trans(cls._clean_value(tagline_candidate_text))
            elif raw_h3_title_text: 
                entity.tagline = cls.trans(cls._clean_value(raw_h3_title_text))

            if not identifier_parsed:
                logger.error(f"Jav321: CRITICAL - Identifier parse failed for {code} from any source.")
                return None
            
            if not entity.tagline and entity.title: entity.tagline = entity.title
            if not entity.plot and entity.tagline: entity.plot = entity.tagline 
            
            # === 3. 이미지 소스 결정 및 관계 처리 ===
            
            # --- 3a. 원본 이미지 URL 파싱 ---
            img_urls_from_page = cls.__img_urls(tree)
            ps_from_detail_page = img_urls_from_page.get('ps')
            pl_from_detail_page = img_urls_from_page.get('pl')
            all_arts_from_page = img_urls_from_page.get('arts', [])
            
            # 로컬파일로 저장하는 로직이 없다.
            # 항상 none과 비교하는가???????????

            # --- 플레이스홀더 이미지 경로 설정 ---
            now_printing_path = None
            #if use_image_server and image_server_local_path:
            #    now_printing_path = os.path.join(image_server_local_path, "now_printing.jpg")
            #    if not os.path.exists(now_printing_path):
            #        now_printing_path = None

            # --- 플레이스홀더를 제외한 유효한 이미지 후보군 생성 ---
            ps_url_from_search_cache = cls._ps_url_cache.get(code)

            valid_ps_candidate = None

            if ps_from_detail_page and not (now_printing_path and cls.are_images_visually_same(ps_from_detail_page, now_printing_path)):
                valid_ps_candidate = ps_from_detail_page
            elif ps_url_from_search_cache and not (now_printing_path and cls.re_images_visually_same(ps_url_from_search_cache, now_printing_path)):
                valid_ps_candidate = ps_url_from_search_cache
            
            valid_pl_candidate = None
            if pl_from_detail_page and not (now_printing_path and cls.are_images_visually_same(pl_from_detail_page, now_printing_path)):
                valid_pl_candidate = pl_from_detail_page

            # --- 3b. 최종 소스로 사용할 변수 초기화 ---
            final_image_sources = {
                'poster_source': None,
                'poster_mode': None,
                'landscape_source': None,
                'arts': [],
            }
            
            # --- 3c. 랜드스케이프 소스 결정 ---
            if valid_pl_candidate:
                final_image_sources['landscape_source'] = valid_pl_candidate

            # --- 3d. 포스터 소스 결정 ---
            apply_ps_to_poster_for_this_item = False
            forced_crop_mode_for_this_item = None
            if hasattr(entity, 'ui_code') and entity.ui_code:
                label_from_ui_code = cls.get_label_from_ui_code(entity.ui_code)
                if label_from_ui_code:
                    if cls.config['ps_force_labels_set'] and ps_from_detail_page:
                        if label_from_ui_code in cls.config['ps_force_labels_set']: 
                            apply_ps_to_poster_for_this_item = True
                    if cls.config['crop_mode']:
                        for line in cls.config['crop_mode']:
                            parts = [x.strip() for x in line.split(":", 1)]
                            if len(parts) == 2 and parts[0].upper() == label_from_ui_code and parts[1].lower() in ["r", "l", "c"]:
                                forced_crop_mode_for_this_item = parts[1].lower(); 
                                break
            
            if forced_crop_mode_for_this_item and valid_pl_candidate:
                final_image_sources['poster_source'] = valid_pl_candidate
                final_image_sources['poster_mode'] = forced_crop_mode_for_this_item
            elif valid_ps_candidate:
                if apply_ps_to_poster_for_this_item:
                    final_image_sources['poster_source'] = valid_ps_candidate
                else:
                    # 플레이스홀더 제외한 아트만 후보로 사용
                    specific_arts = [art for art in all_arts_from_page if art and not (now_printing_path and cls.are_images_visually_same(art, now_printing_path))]
                    poster_candidates = ([valid_pl_candidate] if valid_pl_candidate else []) + specific_arts
                    
                    for candidate in poster_candidates:
                        tmp1 = SiteUtil.is_portrait_high_quality_image(
                            candidate, 
                            proxy_url=cls.config['proxy_url']
                        )
                        tmpe2 = SiteUtil.is_hq_poster(
                            valid_ps_candidate, 
                            candidate, 
                            proxy_url=cls.config['proxy_url'], 
                            sm_source_info=valid_ps_candidate, 
                            lg_source_info=candidate
                        )
                        if tmp1 and tmpe2:
                            final_image_sources['poster_source'] = candidate
                            break
                    if final_image_sources['poster_source'] is None and valid_pl_candidate:
                        _temp_filepath, _, _ = SiteUtil.get_mgs_half_pl_poster_info_local(
                            valid_ps_candidate, 
                            valid_pl_candidate, 
                            proxy_url=cls.config['proxy_url'],
                            do_save=False
                        )
                        if _temp_filepath:
                            mgs_special_poster_filepath = _temp_filepath
                            final_image_sources['poster_source'] = valid_pl_candidate
                            final_image_sources['poster_mode'] = f"mgs_half_{_temp_filepath[-5]}"
                            

                    if final_image_sources['poster_source'] is None:
                        for candidate in poster_candidates:
                            crop_pos = SiteUtil.has_hq_poster(valid_ps_candidate, candidate, proxy_url=cls.config['proxy_url'])
                            if crop_pos:
                                final_image_sources['poster_source'] = candidate
                                final_image_sources['poster_mode'] = f"crop_{crop_pos}"
                                break
                    if final_image_sources['poster_source'] is None:
                        final_image_sources['poster_source'] = valid_ps_candidate

            # --- 3e. 최종 팬아트 목록 결정 ---
            if all_arts_from_page and cls.config['max_arts'] > 0:
                used_for_thumb = set()
                if final_image_sources['landscape_source']: 
                    used_for_thumb.add(final_image_sources['landscape_source'])
                if final_image_sources['poster_source'] and isinstance(final_image_sources['poster_source'], str): 
                    used_for_thumb.add(final_image_sources['poster_source'])
                if mgs_special_poster_filepath and valid_pl_candidate: used_for_thumb.add(valid_pl_candidate)
                
                # 플레이스홀더 제외 로직 포함
                final_image_sources['args'] = [
                    art for art in all_arts_from_page 
                    if art and art not in used_for_thumb and not (now_printing_path and SiteUtil.are_images_visually_same(art, now_printing_path, proxy_url=cls.config['proxy_url']))
                ][:cls.config['max_arts']]


            # === 4. 최종 후처리 위임 ===
            cls.finalize_images_for_entity(entity, final_image_sources)
            
            # === 5. 예고편 및 Shiroutoname 보정 처리 ===
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
                try: entity = SiteUtil.shiroutoname_info(entity)
                except Exception as e_shirouto: logger.exception(f"Jav321: Exception during Shiroutoname call for {entity.originaltitle}: {e_shirouto}")
            
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
            ui_code_videoa, label_videoa, num_videoa = SiteDmm._parse_ui_code_from_cid(
                code_str, 'videoa')
            
            # videoa 파싱이 성공적이면 바로 반환
            if label_videoa and num_videoa:
                return ui_code_videoa, label_videoa, num_videoa
            
            # videoa 파싱 실패 시, dvd 파싱 시도
            logger.debug(f"Jav321 Parser: 'videoa' parsing failed for '{code_str}'. Falling back to 'dvd' type.")
            ui_code_dvd, label_dvd, num_dvd = SiteDmm._parse_ui_code_from_cid(
                code_str, 'dvd')
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
    def _process_jav321_url_from_attribute(cls, url_attribute_value):
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

    # endregion UTILITY METHODS
    ################################################


    ################################################
    # region SiteAvBase 메서드 오버라이드

    @classmethod
    def set_config(cls, db):
        super().set_config(db)
        cls.config.update({
            # 포스터 예외처리1. 설정된 레이블은 저화질 썸네일을 포스터로 사용
            "ps_force_labels_list": db.get_list("jav_censored_jav321_small_image_to_poster", ","),
            
            # 포스터 예외처리2. 가로 이미지 크롭이 필요한 경우 그 위치를 수동 지정
            "crop_mode": db.get_list("jav_censored_jav321_crop_mode", ","),
            # 지정 레이블 최우선 검색
            "priority_labels": db.get_list("jav_censored_jav321_priority_search_labels", ","),
            "maintain_series_number_labels": db.get_list("jav_censored_jav321_maintain_series_number_labels", ","),
        })
        cls.config['maintain_series_number_labels'] = {lbl.strip().upper() for lbl in cls.config['maintain_series_number_labels'] if lbl.strip()}
        cls.config['ps_force_labels_set'] = {lbl.strip().upper() for lbl in cls.config['ps_force_labels_list'] if lbl.strip()}

    
    @classmethod
    def jav_image(cls, url, mode=None):
        if mode and mode.startswith("mgs_half"):
            return cls.pil_to_response(cls.get_mgs_half_pl_poster(url, int(mode[-1])))
        return super().default_jav_image(url, mode)

    # endregion SiteAvBase 메서드 오버라이드
    ################################################

