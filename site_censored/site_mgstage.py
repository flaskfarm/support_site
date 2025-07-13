import re
import os

from ..constants import MGS_CODE_LEN, MGS_LABEL_MAP
from ..entity_av import EntityAVSearch
from ..entity_base import EntityActor, EntityExtra, EntityMovie, EntityRatings, EntityThumb
from ..setup import P, logger
from ..site_util_av import SiteUtilAv as SiteUtil

class SiteMgstage:
    site_name = "mgstage"
    site_char = "M"
    site_base_url = "https://www.mgstage.com"
    module_char = None
    _ps_url_cache = {} 

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/71.0.3578.98 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8",
        "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
        "Cookie": "coc=1;mgs_agef=1;",
    }

    PTN_SEARCH_PID = re.compile(r"\/product_detail\/(?P<code>.*?)\/")
    PTN_SEARCH_REAL_NO = re.compile(r"^(?P<label_part>\d*[a-zA-Z]+[0-9]*)\-(?P<no>\d+)$")
    PTN_TEXT_SUB = [
        re.compile(r"【(?<=【)(?:MGSだけのおまけ映像付き|期間限定).*(?=】)】(:?\s?\+\d+分\s?)?"),
        re.compile(r"※通常版\+\d+分の特典映像付のスペシャルバージョン！"),
        re.compile(r"【(?<=【).+実施中(?=】)】"),
    ]
    PTN_RATING = re.compile(r"\s(?P<rating>[\d\.]+)点\s.+\s(?P<vote>\d+)\s件")


    @classmethod
    def get_label_from_ui_code(cls, ui_code_str: str) -> str:
        if not ui_code_str or not isinstance(ui_code_str, str): return ""
        
        ui_code_upper = ui_code_str.upper()
        label_part = ui_code_upper.split('-', 1)[0]

        # 숫자 접두사 제거 (예: 298GOOD -> GOOD)
        match = re.match(r"\d*(?P<label>[a-zA-Z].*)", label_part)
        if match:
            return match.group('label')
        return label_part


    @classmethod
    def __search(
        cls,
        keyword,
        do_trans=True,
        proxy_url=None,
        image_mode="ff_proxy",
        manual=False,
        priority_label_setting_str=""
        ):

        temp_keyword = keyword.strip().lower()
        temp_keyword = re.sub(r'[_-]?cd\d+$', '', temp_keyword, flags=re.I)
        keyword_for_url = temp_keyword.strip(' _-')

        url = f"{cls.site_base_url}/search/cSearch.php?search_word={keyword_for_url}&x=0&y=0&type=top"
        logger.debug(f"MGStage Search URL: {url}")

        tree = SiteUtil.get_tree(url, proxy_url=proxy_url, headers=cls.headers)
        if tree is None:
            logger.warning(f"MGStage Search ({cls.module_char}): Failed to get tree for URL: {url}")
            return []
        lists = tree.xpath('//div[@class="search_list"]/div/ul/li')
        # logger.debug("mgs search kwd=%s len=%d", keyword_for_url, len(lists))

        ret = []
        for node in lists[:10]:
            try:
                item = EntityAVSearch(cls.site_name)
                tag = node.xpath(".//a")[0]
                href = tag.attrib["href"].lower()
                match = cls.PTN_SEARCH_PID.search(href)
                if not match: continue
                
                item.code = cls.module_char + cls.site_char + match.group("code").upper()
                if any(exist_item["code"] == item.code for exist_item in ret):
                    continue

                tag_img = node.xpath(".//img")[0]
                item.image_url = tag_img.attrib["src"]
                if item.code and item.image_url:
                    cls._ps_url_cache[item.code] = {'ps': item.image_url}

                tag_title = node.xpath('.//a[@class="title lineclamp"]')[0]
                title = tag_title.text_content()
                for ptn in cls.PTN_TEXT_SUB:
                    title = ptn.sub("", title)
                item.title = item.title_ko = title.strip()

                if manual:
                    _image_mode = "ff_proxy" if image_mode != "original" else image_mode
                    item.image_url = SiteUtil.process_image_mode(_image_mode, item.image_url, proxy_url=proxy_url)
                    item.title_ko = "(현재 인터페이스에서는 번역을 제공하지 않습니다) " + item.title
                else:
                    item.title_ko = SiteUtil.trans(item.title, do_trans=do_trans)

                match_ui_code = cls.PTN_SEARCH_REAL_NO.search(item.code[2:])
                if match_ui_code:
                    item.ui_code = match_ui_code.group("label_part").upper() + "-" + match_ui_code.group("no")
                else:
                    item.ui_code = item.code[2:]
                
                normalized_keyword = keyword_for_url.upper().replace('-', '')
                normalized_ui_code = item.ui_code.upper().replace('-', '')

                if normalized_keyword == normalized_ui_code:
                    item.score = 100
                elif normalized_keyword in normalized_ui_code:
                    item.score = 90
                else:
                    item.score = 70 - (len(ret) * 10)
                if item.score < 0: item.score = 0

                item_dict = item.as_dict()
                item_dict['is_priority_label_site'] = False
                item_dict['site_key'] = cls.site_name

                if item_dict.get('ui_code') and priority_label_setting_str:
                    label_to_check = cls.get_label_from_ui_code(item_dict['ui_code'])
                    if label_to_check:
                        priority_labels_set = {lbl.strip().upper() for lbl in priority_label_setting_str.split(',') if lbl.strip()}
                        if label_to_check in priority_labels_set:
                            item_dict['is_priority_label_site'] = True
                ret.append(item_dict)
            except Exception as e:
                logger.exception(f"개별 검색 결과 처리 중 예외: {e}")

        sorted_result = sorted(ret, key=lambda k: k.get("score", 0), reverse=True)
        if sorted_result:
            log_count = min(len(sorted_result), 5)
            logger.debug(f"MGS Search: Top {log_count} results for '{keyword_for_url}':")
            for idx, item_log_final in enumerate(sorted_result[:log_count]):
                logger.debug(f"  {idx+1}. Score={item_log_final.get('score')}, Code={item_log_final.get('code')}, UI Code={item_log_final.get('ui_code')}, Title='{item_log_final.get('title_ko')}'")
        return sorted_result


    @classmethod
    def search(cls, keyword, **kwargs):
        ret = {}
        try:
            temp_keyword = keyword.strip().upper()
            temp_keyword = re.sub(r'[_]?CD\d+$', '', temp_keyword)
            temp_keyword = temp_keyword.strip(' _-')

            do_trans_arg = kwargs.get('do_trans', True)
            proxy_url_arg = kwargs.get('proxy_url', None)
            image_mode_arg = kwargs.get('image_mode', "original")
            manual_arg = kwargs.get('manual', False)
            priority_label_str_arg = kwargs.get('priority_label_setting_str', "")

            data = []
            tmps = temp_keyword.split('-')
            
            search_keyword_for_mgs = temp_keyword
            if len(tmps) == 2:
                input_label, code_part = tmps
                
                # MGS_LABEL_MAP에서 변환할 레이블 목록을 가져옴
                mgs_labels_to_try = MGS_LABEL_MAP.get(input_label)
                if mgs_labels_to_try:
                    mgs_label = mgs_labels_to_try[0] # 첫 번째 것을 대표로 사용
                    if codelen := MGS_CODE_LEN.get(mgs_label):
                        try: code_part = str(int(code_part)).zfill(codelen)
                        except ValueError: pass
                    search_keyword_for_mgs = f"{mgs_label}-{code_part}"
                    logger.debug(f"MGStage Search: Mapping '{keyword}' to '{search_keyword_for_mgs}' for search.")
                
            data = cls.__search(search_keyword_for_mgs,
                                do_trans=do_trans_arg,
                                proxy_url=proxy_url_arg,
                                image_mode=image_mode_arg,
                                manual=manual_arg,
                                priority_label_setting_str=priority_label_str_arg)

        except Exception as exception:
            logger.exception("검색 결과 처리 중 예외:")
            ret["ret"] = "exception"; ret["data"] = str(exception)
        else:
            ret["ret"] = "success" if data else "no_match"; ret["data"] = data
        return ret


class SiteMgstageDvd(SiteMgstage):
    module_char = "C"

    @classmethod
    def __img_urls(cls, tree):
        pl = tree.xpath('//*[@id="package"]/a/@href')
        pl = pl[0] if pl else ""

        arts = tree.xpath('//*[@id="sample-photo"]//ul/li/a/@href')
        if pl and "pb_e_" in pl:
            potential_pf = pl.replace("pb_e_", "pf_e_")
            if potential_pf not in arts:
                arts.insert(0, potential_pf)
        return {"pl": pl, "arts": arts}


    @classmethod
    def __info( 
        cls,
        code,
        do_trans=True,
        proxy_url=None,
        image_mode="original",
        max_arts=10,
        use_extras=True,
        ps_to_poster_labels_str="", 
        crop_mode_settings_str="",
        **kwargs          
    ):
        use_image_server = kwargs.get('use_image_server', False)
        image_server_url = kwargs.get('image_server_url', '').rstrip('/') if use_image_server else ''
        image_server_local_path = kwargs.get('image_server_local_path', '') if use_image_server else ''
        image_path_segment = kwargs.get('url_prefix_segment', 'unknown/unknown')
        maintain_series_number_labels_str = kwargs.get('maintain_series_number_labels', '')

        cached_data = cls._ps_url_cache.get(code, {}) 
        ps_url_from_search_cache = kwargs.get('ps_url')
        if not ps_url_from_search_cache:
            ps_url_from_search_cache = cached_data.get('ps')

        url = cls.site_base_url + f"/product/product_detail/{code[2:]}/"
        tree = SiteUtil.get_tree(url, proxy_url=proxy_url, headers=cls.headers)
        if tree is None:
            logger.error(f"MGStage ({cls.module_char}): Failed to get page tree for {code}. URL: {url}")
            return None

        entity = EntityMovie(cls.site_name, code)
        entity.country = ["일본"]; entity.mpaa = "청소년 관람불가"; entity.tag = []
        entity.thumb = []; entity.fanart = []; entity.extras = []; entity.ratings = []

        ui_code_for_image = ""
        mgs_special_poster_filepath = None

        try:
            # === 2. 메타데이터 파싱 ===
            h1_tags = tree.xpath('//h1[@class="tag"]/text()')
            if h1_tags:
                h1_text_raw = h1_tags[0]
                for ptn in cls.PTN_TEXT_SUB: h1_text_raw = ptn.sub("", h1_text_raw)
                entity.tagline = SiteUtil.trans(h1_text_raw.strip(), do_trans=do_trans)
            
            info_table_xpath = '//div[@class="detail_data"]//tr'
            tr_nodes = tree.xpath(info_table_xpath)

            temp_shohin_hatsubai = None
            temp_haishin_kaishi = None
            maintain_series_labels_set = {lbl.strip().upper() for lbl in maintain_series_number_labels_str.split(',') if lbl.strip()}

            for tr_node in tr_nodes:
                key_node = tr_node.xpath("./th"); value_node_outer = tr_node.xpath("./td")
                if not key_node or not value_node_outer: continue
                key_text = key_node[0].text_content().strip(); value_text_content = value_node_outer[0].text_content().strip()
                value_node_instance = value_node_outer[0]

                if "品番" in key_text:
                    official_code = value_text_content.strip().upper()
                    pure_label = cls.get_label_from_ui_code(official_code)
                    if pure_label in maintain_series_labels_set:
                        final_ui_code = official_code
                    else:
                        match = cls.PTN_SEARCH_REAL_NO.search(official_code)
                        if match:
                            final_ui_code = f"{pure_label}-{match.group('no')}"
                        else:
                            final_ui_code = official_code
                    
                    ui_code_for_image = final_ui_code.lower()
                    entity.ui_code = final_ui_code
                    entity.title = entity.originaltitle = entity.sorttitle = final_ui_code
                    label_for_tag = official_code.split('-', 1)[0]
                    if entity.tag is None: entity.tag = []
                    if label_for_tag and label_for_tag not in entity.tag:
                        entity.tag.append(label_for_tag)
                    logger.debug(f"MGStage ({cls.module_char}): Official Code='{official_code}', Pure Label='{pure_label}', Final UI Code='{final_ui_code}' (Maintain Series: {pure_label in maintain_series_labels_set})")
                elif "商品発売日" in key_text:
                    if "----" not in value_text_content: temp_shohin_hatsubai = value_text_content.replace("/", "-")
                elif "配信開始日" in key_text:
                    if "----" not in value_text_content: temp_haishin_kaishi = value_text_content.replace("/", "-")
                elif "収録時間" in key_text:
                    rt_match = re.search(r'(\d+)', value_text_content)
                    if rt_match: entity.runtime = int(rt_match.group(1))
                elif "出演" in key_text:
                    entity.actor = [EntityActor(act.strip().split(" ", 1)[0]) for act in value_node_instance.xpath("./a/text()") if act.strip()]
                elif "監督" in key_text: 
                    entity.director = value_text_content.strip() or None
                elif "シリーズ" in key_text:
                    s_name = (value_node_instance.xpath("./a/text()")[0] if value_node_instance.xpath("./a/text()") else value_text_content).strip()
                    if s_name:
                        trans_s = SiteUtil.trans(s_name, do_trans=do_trans)
                        if trans_s and trans_s not in (entity.tag or []): 
                            if entity.tag is None: entity.tag = []
                            entity.tag.append(trans_s)
                elif "レーベル" in key_text: 
                    studio_name = (value_node_instance.xpath("./a/text()")[0] if value_node_instance.xpath("./a/text()") else value_text_content).strip()
                    if studio_name: entity.studio = SiteUtil.trans(studio_name, do_trans=do_trans) if do_trans else studio_name
                elif "ジャンル" in key_text:
                    if entity.genre is None: entity.genre = []
                    for g_tag in value_node_instance.xpath("./a"):
                        g_ja = g_tag.text_content().strip()
                        if "MGSだけのおまけ映像付き" in g_ja or not g_ja or g_ja in SiteUtil.av_genre_ignore_ja: continue
                        if g_ja in SiteUtil.av_genre:
                            g_ko = SiteUtil.av_genre[g_ja]
                            if g_ko not in entity.genre: entity.genre.append(g_ko)
                        else:
                            g_ko = SiteUtil.trans(g_ja, do_trans=do_trans).replace(" ", "")
                            if g_ko not in SiteUtil.av_genre_ignore_ko and g_ko not in entity.genre: entity.genre.append(g_ko)

            entity.premiered = temp_shohin_hatsubai or temp_haishin_kaishi
            if entity.premiered:
                try: entity.year = int(entity.premiered[:4])
                except (ValueError, IndexError): pass
            
            rating_nodes = tree.xpath('//div[@class="user_review_head"]/p[@class="detail"]/text()')
            if rating_nodes:
                rating_match = cls.PTN_RATING.search(rating_nodes[0])
                if rating_match:
                    try:
                        rating_val = float(rating_match.group("rating"))
                        votes = int(rating_match.group("vote"))
                        entity.ratings = [EntityRatings(rating_val, max=5, name=cls.site_name, votes=votes)]
                    except Exception: pass
            
            if not ui_code_for_image:
                logger.error(f"MGStage ({cls.module_char}): CRITICAL - Failed to parse identifier for {code}.")
                return None

            # === 3. 이미지 소스 결정 및 관계 처리 ===
            
            # --- 3a. 원본 이미지 URL 파싱 ---
            img_urls_from_page = cls.__img_urls(tree)
            pl_url = img_urls_from_page.get('pl')
            all_arts = img_urls_from_page.get('arts', [])
            
            # --- 3b. 최종 소스로 사용할 변수 초기화 ---
            final_poster_source = None
            final_poster_crop_mode = None
            final_landscape_url_source = None
            arts_urls_for_processing = []

            # --- 3c. 랜드스케이프 소스 결정 ---
            if pl_url:
                final_landscape_url_source = pl_url

            # --- 3d. 포스터 소스 결정 ---
            apply_ps_to_poster_for_this_item = False
            forced_crop_mode_for_this_item = None
            if hasattr(entity, 'ui_code') and entity.ui_code:
                label_from_ui_code = cls.get_label_from_ui_code(entity.ui_code)
                if label_from_ui_code:
                    if ps_to_poster_labels_str:
                        ps_force_labels_set = {lbl.strip().upper() for lbl in ps_to_poster_labels_str.split(',') if lbl.strip()}
                        if label_from_ui_code in ps_force_labels_set:
                            apply_ps_to_poster_for_this_item = True
                    if crop_mode_settings_str:
                        for line in crop_mode_settings_str.splitlines():
                            parts = [x.strip() for x in line.split(":", 1)]
                            if len(parts) == 2 and parts[0].upper() == label_from_ui_code and parts[1].lower() in ["r", "l", "c"]:
                                forced_crop_mode_for_this_item = parts[1].lower(); break
            
            if forced_crop_mode_for_this_item and pl_url:
                final_poster_source = pl_url
                final_poster_crop_mode = forced_crop_mode_for_this_item
            elif ps_url_from_search_cache:
                if apply_ps_to_poster_for_this_item:
                    final_poster_source = ps_url_from_search_cache
                else:
                    specific_arts_candidates = []
                    if all_arts:
                        if all_arts[0]: specific_arts_candidates.append(all_arts[0])
                        if len(all_arts) > 1 and all_arts[-1] != all_arts[0]: specific_arts_candidates.append(all_arts[-1])
                    
                    poster_candidates = ([pl_url] if pl_url else []) + specific_arts_candidates
                    for candidate in poster_candidates:
                        if SiteUtil.is_portrait_high_quality_image(candidate, proxy_url=proxy_url) and \
                           SiteUtil.is_hq_poster(ps_url_from_search_cache, candidate, proxy_url=proxy_url,
                                                sm_source_info=ps_url_from_search_cache, lg_source_info=candidate):
                            final_poster_source = candidate
                            break
                    if final_poster_source is None and pl_url:
                        temp_filepath, _, _ = SiteUtil.get_mgs_half_pl_poster_info_local(ps_url_from_search_cache, pl_url, proxy_url=proxy_url)
                        if temp_filepath and os.path.exists(temp_filepath):
                            mgs_special_poster_filepath = temp_filepath
                            final_poster_source = mgs_special_poster_filepath
                    if final_poster_source is None:
                        for candidate in poster_candidates:
                            crop_pos = SiteUtil.has_hq_poster(ps_url_from_search_cache, candidate, proxy_url=proxy_url)
                            if crop_pos:
                                final_poster_source = candidate
                                final_poster_crop_mode = crop_pos
                                break

                    if final_poster_source is None:
                        final_poster_source = ps_url_from_search_cache
            else:
                logger.warning(f"[{cls.site_name} Info] No PS url found. Poster cannot be determined.")

            # --- 3e. 최종 팬아트 목록 결정 (아트 처리 및 변수 처리) ---
            if all_arts and max_arts > 0:
                used_for_thumb = set()
                if final_landscape_url_source: used_for_thumb.add(final_landscape_url_source)
                if final_poster_source and isinstance(final_poster_source, str): used_for_thumb.add(final_poster_source)
                if mgs_special_poster_filepath and pl_url: used_for_thumb.add(pl_url)
                arts_urls_for_processing = [art for art in all_arts if art and art not in used_for_thumb][:max_arts]
            
            logger.debug(f"MGStage (Decision Phase): Final Poster='{str(final_poster_source)[:100]}...', Landscape='{final_landscape_url_source}', Fanarts to process({len(arts_urls_for_processing)})")

            # === 4. 최종 후처리 위임 ===
            final_image_sources = {
                'poster_source': final_poster_source,
                'poster_crop': final_poster_crop_mode,
                'landscape_source': final_landscape_url_source,
                'arts': arts_urls_for_processing,
            }
            image_processing_settings = {
                'image_mode': image_mode,
                'proxy_url': proxy_url,
                'max_arts': max_arts,
                'ui_code': ui_code_for_image,
                'use_image_server': use_image_server,
                'image_server_url': image_server_url,
                'image_server_local_path': image_server_local_path,
                'image_path_segment': image_path_segment,
            }
            SiteUtil.finalize_images_for_entity(entity, final_image_sources, image_processing_settings)

            # === 5. 예고편 및 Shiroutoname 보정 처리 ===
            if use_extras:
                try:
                    trailer_sample_btn = tree.xpath('//*[@class="sample_movie_btn"]/a/@href')
                    if trailer_sample_btn:
                        pid_trailer = trailer_sample_btn[0].split("/")[-1]
                        api_url_trailer = f"https://www.mgstage.com/sampleplayer/sampleRespons.php?pid={pid_trailer}"
                        api_headers_trailer = cls.headers.copy(); api_headers_trailer['Referer'] = url 
                        api_headers_trailer['X-Requested-With'] = 'XMLHttpRequest'; api_headers_trailer['Accept'] = 'application/json, text/javascript, */*; q=0.01'
                        res_json_trailer = SiteUtil.get_response(api_url_trailer, proxy_url=proxy_url, headers=api_headers_trailer).json()
                        if res_json_trailer and res_json_trailer.get("url"):
                            trailer_base = res_json_trailer["url"].split(".ism")[0]; trailer_final_url = trailer_base + ".mp4"
                            trailer_title_text = entity.tagline if entity.tagline else entity.ui_code 
                            entity.extras.append(EntityExtra("trailer", trailer_title_text, "mp4", trailer_final_url))
                except Exception as e_trailer_proc_dvd:
                    logger.exception(f"MGStage ({cls.module_char}): Error processing trailer: {e_trailer_proc_dvd}")

            if entity.originaltitle:
                try: 
                    entity = SiteUtil.shiroutoname_info(entity)
                except Exception as e_shirouto_proc: 
                    logger.exception(f"MGStage (Ama): Shiroutoname error: {e_shirouto_proc}")
            
            logger.info(f"MGStage ({cls.module_char}): __info finished for {code}. UI Code: {ui_code_for_image}")
            return entity

        except Exception as e:
            logger.exception(f"MGStage ({cls.module_char}): Major error during info processing for {code}: {e}")
            return None # 예외 발생 시 None 반환
        
        finally:
            # === 6. 임시 파일 정리 ===
            if mgs_special_poster_filepath and os.path.exists(mgs_special_poster_filepath):
                try:
                    os.remove(mgs_special_poster_filepath)
                    logger.debug(f"MGStage ({cls.module_char}): Removed MGS-style temp poster file: {mgs_special_poster_filepath}")
                except Exception as e_remove_temp:
                    logger.error(f"MGStage ({cls.module_char}): Failed to remove MGS-style temp poster file {mgs_special_poster_filepath}: {e_remove_temp}")


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
                ret["data"] = f"Failed to get MGStage ({cls.module_char}) info for {code}"
        except Exception as e: 
            ret["ret"] = "exception"
            ret["data"] = str(e)
            logger.exception(f"MGStage ({cls.module_char}) info error: {e}")
        return ret
