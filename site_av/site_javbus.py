import re
from lxml import html
from typing import Union

from ..entity_av import EntityAVSearch
from ..entity_base import EntityMovie, EntityActor
from ..setup import P, logger
from .site_av_base import SiteAvBase
from ..constants import AV_GENRE_IGNORE_JA, AV_GENRE, AV_GENRE_IGNORE_KO


SITE_BASE_URL = "https://www.javbus.com"

class SiteJavbus(SiteAvBase):
    site_name = "javbus"
    site_char = "B"
    module_char = "C"
    default_headers = SiteAvBase.base_default_headers.copy()
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
        temp_keyword = original_keyword.strip().lower()
        temp_keyword = re.sub(r'[_-]?cd\d+$', '', temp_keyword, flags=re.I)
        temp_keyword = temp_keyword.strip(' _-')

        keyword_for_url = re.sub(r'^\d+', '', temp_keyword).lstrip('-_')

        logger.debug(f"JavBus Search: original='{original_keyword}', url_kw='{keyword_for_url}'")

        url = f"{SITE_BASE_URL}/search/{keyword_for_url}"
        tree = cls._get_javbus_page_tree(url)
        if tree is None:
            return []

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
                    if cls.config['use_proxy']:
                        item.image_url = cls.make_image_url(item.image_url)
                    item.title_ko = "(현재 인터페이스에서는 번역을 제공하지 않습니다) " + item.title
                else:
                    item.title_ko = cls.trans(item.title)

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

    
    @classmethod
    def __info(cls, code):
        try:
            # === 1. 페이지 로딩 및 기본 Entity 생성 ===
            original_code_for_url = code[len(cls.module_char) + len(cls.site_char):]
            url = f"{SITE_BASE_URL}/{original_code_for_url}"
            tree = cls._get_javbus_page_tree(url)

            if tree is None or not tree.xpath("//div[@class='container']//div[@class='row movie']"):
                logger.error(f"JavBus __info: Failed to get valid detail page for {code}. URL: {url}")
                return None

            entity = EntityMovie(cls.site_name, code)
            entity.country = ["일본"]; entity.mpaa = "청소년 관람불가"
            entity.thumb = []; entity.fanart = []; entity.tag = []; entity.actor = []

            # === 2. 메타데이터 파싱 ===
            info_node = tree.xpath("//div[contains(@class, 'container')]//div[@class='col-md-3 info']")[0]
            
            base_ui_code = original_code_for_url.split('_')[0].upper()
            ui_code_val_nodes = info_node.xpath("./p[./span[@class='header' and contains(text(),'識別碼')]]/span[not(@class='header')]//text()")
            if not ui_code_val_nodes:
                ui_code_val_nodes = info_node.xpath("./p[./span[@class='header' and contains(text(),'識別碼')]]/text()[normalize-space()]")
            raw_ui_code_from_page = "".join(ui_code_val_nodes).strip()
            if not base_ui_code and raw_ui_code_from_page:
                base_ui_code = raw_ui_code_from_page.upper()

            final_ui_code = base_ui_code
            keyword = None
            if keyword and base_ui_code and cls.config['maintain_series_number_labels']:
                kw_match = re.match(r'^(\d+)([a-zA-Z].*)', keyword.upper())
                if kw_match:
                    kw_prefix, kw_core = kw_match.groups()
                    kw_core = kw_core.replace('-', '')
                    jb_match = re.match(r'^(\d*)?([A-Z]+-?\d+)', base_ui_code)
                    if jb_match:
                        jb_core = jb_match.group(2).replace('-', '')
                        jb_label_match = re.match(r'(\D+)', jb_core)
                        if jb_label_match and jb_label_match.group(1) in cls.config['maintain_series_number_labels']:
                            final_ui_code = f"{kw_prefix}{base_ui_code}"
            
            entity.ui_code = final_ui_code
            entity.title = entity.originaltitle = entity.sorttitle = final_ui_code
            ui_code_for_image = entity.ui_code.lower()

            h3_text = tree.xpath("normalize-space(//div[@class='container']/h3/text())")
            if h3_text.upper().startswith(base_ui_code):
                entity.tagline = cls.trans(h3_text[len(base_ui_code):].strip())
            else:
                entity.tagline = cls.trans(h3_text)

            all_p_tags_in_info = info_node.xpath("./p")
            genre_header_p_node = actor_header_p_node = None
            for p_tag_node_loop in all_p_tags_in_info:
                header_text = p_tag_node_loop.xpath("normalize-space(./span[@class='header']/text())")
                if "類別:" in header_text: genre_header_p_node = p_tag_node_loop
                elif "演員" in header_text: actor_header_p_node = p_tag_node_loop

            for p_tag in all_p_tags_in_info:
                header_span = p_tag.xpath("./span[@class='header']")
                if not header_span or not header_span[0].text: continue
                key = header_span[0].text.strip().replace(":", "")
                if key in ["類別", "演員"]: continue
                value = "".join(header_span[0].xpath("./following-sibling::node()/text()")).strip()
                if not value or value == "----": continue
                
                if key == "發行日期":
                    if value != "0000-00-00": entity.premiered, entity.year = value, int(value[:4])
                elif key == "長度":
                    try: entity.runtime = int(value.replace("分鐘", "").strip())
                    except: pass
                elif key == "導演": entity.director = value
                elif key == "製作商": entity.studio = cls.trans(value)
                elif key == "發行商" and not entity.studio: entity.studio = cls.trans(value)
                elif key == "系列":
                    trans_series = cls.trans(value)
                    if trans_series not in entity.tag:
                        entity.tag.append(trans_series)

            if genre_header_p_node is not None:
                entity.genre = []
                for genre_span in genre_header_p_node.xpath("./following-sibling::p[1]/span[@class='genre']"):
                    genre_ja = "".join(genre_span.xpath("./label/a/text() | ./a/text()")).strip()
                    if not genre_ja or genre_ja == "多選提交" or genre_ja in AV_GENRE_IGNORE_JA: 
                        continue
                    if genre_ja in AV_GENRE:
                        if AV_GENRE[genre_ja] not in entity.genre:
                            entity.genre.append(AV_GENRE[genre_ja])
                    else:
                        genre_ko = cls.trans(genre_ja).replace(" ", "")
                        if genre_ko not in AV_GENRE_IGNORE_KO and genre_ko not in entity.genre: 
                            entity.genre.append(genre_ko)

            if actor_header_p_node is not None:
                for actor_span in actor_header_p_node.xpath("./following-sibling::p[1]//span[@class='genre']"):
                    actor_name = actor_span.xpath("string(.)").strip()
                    if actor_name and actor_name != "暫無出演者資訊":
                        if entity.actor is None: entity.actor = [] # 방어 코드
                        if not any(act.name == actor_name for act in entity.actor):
                            entity.actor.append(EntityActor(actor_name))

            if entity.ui_code:
                label = entity.ui_code.split('-')[0]
                if label not in entity.tag:
                    entity.tag.append(label)

            # === 3. 이미지 소스 결정 및 관계 처리 ===
            final_image_sources = {
                'poster_source': None,
                'poster_mode': None,
                'landscape_source': None,
                'arts': [],
            }

            img_urls_from_page = cls.__img_urls(tree)
            pl_url = img_urls_from_page.get('pl')
            all_arts_from_page = img_urls_from_page.get('arts', [])

            cached_data = cls._ps_url_cache.get(code, {})
            ps_url_from_search_cache = cached_data.get('ps')
            ps_url_inferred_from_page = img_urls_from_page.get('ps')
            ps_url = ps_url_from_search_cache or ps_url_inferred_from_page


            if pl_url: 
                final_image_sources['landscape_source'] = pl_url

            apply_ps_to_poster_for_this_item = False
            forced_crop_mode_for_this_item = None
            if hasattr(entity, 'ui_code') and entity.ui_code:
                label = entity.ui_code.split('-',1)[0].upper()
                if label in cls.config['ps_force_labels_set']: 
                    apply_ps_to_poster_for_this_item = True
                if cls.config['crop_mode']:
                    for line in cls.config['crop_mode']:
                        parts = [x.strip() for x in line.split(":", 1) if x.strip()]
                        if len(parts) == 2 and parts[0].upper() == label and parts[1].lower() in "rlc":
                            forced_crop_mode_for_this_item = parts[1].lower()
                            break

            if forced_crop_mode_for_this_item and pl_url:
                final_image_sources['poster_source'] = pl_url
                final_image_sources['poster_mode'] = f"crop_{forced_crop_mode_for_this_item}"
            elif ps_url:
                if apply_ps_to_poster_for_this_item:
                    final_image_sources['poster_source'] = ps_url
                else:
                    poster_candidates = ([pl_url] if pl_url else []) + (all_arts_from_page[:1] + all_arts_from_page[-1:] if all_arts_from_page else [])
                    for candidate in poster_candidates:
                        _1 = cls.is_portrait_high_quality_image(candidate)
                        _2 = cls.is_hq_poster(ps_url, candidate, sm_source_info=ps_url, lg_source_info=candidate)
                        if _1 and _2:
                            final_image_sources['poster_source'] = candidate
                            break
                    if final_image_sources['poster_source'] is None:
                        for candidate in poster_candidates:
                            crop_pos = cls.has_hq_poster(ps_url, candidate)
                            if crop_pos:
                                final_image_sources['poster_source'] = candidate
                                final_image_sources['poster_crop'] = f"crop_{crop_pos}"
                                break
                    if final_image_sources['poster_source'] is None: 
                        final_image_sources['poster_source'] = ps_url
            elif pl_url:
                final_image_sources['poster_source'] = pl_url
                final_image_sources['poster_mode'] = f"crop_r"  

            if all_arts_from_page and cls.config['max_arts'] > 0:
                used = {final_image_sources['landscape_source'], final_image_sources['poster_source'] if isinstance(final_image_sources['poster_source'], str) else None}
                final_image_sources['arts'] = [art for art in all_arts_from_page if art and art not in used][:cls.config['max_arts']]

            # === 4. 최종 후처리 위임 ===
            
            cls.finalize_images_for_entity(entity, final_image_sources)

            # === 5. Shiroutoname 보정 처리 ===
            if entity.ui_code:
                try: 
                    entity = cls.shiroutoname_info(entity)
                    if entity.ui_code.upper() != original_code_for_url.split('_')[0].upper():
                        new_code_value = entity.ui_code.lower()
                        if '_' in original_code_for_url:
                            new_code_value += '_' + original_code_for_url.split('_')[1]
                        entity.code = cls.module_char + cls.site_char + new_code_value
                except Exception as e_shirouto: logger.exception(f"JavBus: Shiroutoname error: {e_shirouto}")

            logger.info(f"JavBus: __info finished for {code}. UI Code: {entity.ui_code}")
            return entity

        except Exception as e:
            logger.exception(f"JavBus __info: Main processing error for {code}: {e}")
            return None

    # endregion INFO
    ################################################

    @classmethod
    def __fix_url(cls, url):
        if not url.startswith("http"):
            return SITE_BASE_URL + url
        return url

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
    def _get_javbus_page_tree(cls, page_url: str, cf_clearance_cookie: str = None) -> Union[html.HtmlElement, None]:
        javbus_cookies = {'age': 'verified', 'age_check_done': '1', 'ckcy': '1', 'dv': '1', 'existmag': 'mag'}
        if cf_clearance_cookie:
            javbus_cookies['cf_clearance'] = cf_clearance_cookie
            # logger.debug(f"SiteJavbus._get_javbus_page_tree: Using cf_clearance cookie for URL: {page_url}")

        try:
            res = cls.get_response_cs(page_url, cookies=javbus_cookies, allow_redirects=True)

            if res is None or res.status_code != 200:
                status_code = res.status_code if res else "None"
                logger.warning(f"SiteJavbus._get_javbus_page_tree: Failed to get page or status not 200 for URL='{page_url}'. Status: {status_code}. Falling back to .get_response if configured.")

                # Cloudscraper 실패 시, .get_response로 fallback
                # logger.debug(f"SiteJavbus._get_javbus_page_tree: Attempting fallback with .get_response for URL='{page_url}'")
                res_fallback = cls.get_response(page_url,  cookies=javbus_cookies, verify=False)
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


    ################################################
    # region SiteAvBase 메서드 오버라이드

    @classmethod
    def set_config(cls, db):
        super().set_config(db)
        cls.config.update({
            "ps_force_labels_list": set(db.get_list(f"jav_censored_{cls.site_name}_small_image_to_poster", ",")),
            "crop_mode": db.get_list(f"jav_censored_{cls.site_name}_crop_mode", ","),
            "maintain_series_number_labels": db.get_list(f"jav_censored_{cls.site_name}_maintain_series_number_labels", ","),
        })
        cls.config['maintain_series_number_labels'] = {lbl.strip().upper() for lbl in cls.config['maintain_series_number_labels'] if lbl.strip()}
        cls.config['ps_force_labels_set'] = {lbl.strip().upper() for lbl in cls.config['ps_force_labels_list'] if lbl.strip()}
    
    # endregion SiteAvBase 메서드 오버라이드
    ################################################
