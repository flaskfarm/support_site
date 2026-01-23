import re
from lxml import html
from typing import Union

from ..entity_av import EntityAVSearch
from ..entity_base import EntityMovie, EntityActor, EntityThumb
from ..setup import P, logger, F
from .site_av_base import SiteAvBase
from ..constants import AV_GENRE_IGNORE_JA, AV_GENRE, AV_GENRE_IGNORE_KO


SITE_BASE_URL = "https://www.javbus.com"

class SiteJavbus(SiteAvBase):
    site_name = "javbus"
    site_char = "B"
    module_char = "C"
    default_headers = SiteAvBase.base_default_headers.copy()
    default_headers.update({
        "Referer": SITE_BASE_URL + "/",
        "Cookie": "age=verified; age_check_done=1; ckcy=1; dv=1; existmag=mag"
    })
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
        tree = cls.get_tree(url)
        if tree is None:
            return []

        ret = []
        kw_ui_code, kw_label_part, kw_num_part = cls._parse_ui_code(temp_keyword)

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

                # --- ui_code 파싱 및 점수 계산 로직 ---
                raw_ui_code_from_page = node.xpath(".//date")[0].text_content().strip()
                item_ui_code, _, _ = cls._parse_ui_code(raw_ui_code_from_page)
                item.ui_code = item_ui_code

                item.score = cls._calculate_score(original_keyword, item.ui_code)
                if not item.score:
                    item.score = 20

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
                ret["data"] = f"Failed to get JavBus info for {code}"
        except Exception as e:
            ret["ret"] = "exception"
            ret["data"] = str(e)
            logger.exception(f"JavBus info error: {e}")
        return ret


    @classmethod
    def __info(cls, code, keyword=None, fp_meta_mode=False):
        try:
            # === 1. 페이지 로딩 및 기본 Entity 생성 ===
            original_code_for_url = code[len(cls.module_char) + len(cls.site_char):]
            url = f"{SITE_BASE_URL}/{original_code_for_url}"
            tree = cls.get_tree(url)

            if tree is None or not tree.xpath("//div[@class='container']//div[@class='row movie']"):
                logger.error(f"JavBus __info: Failed to get valid detail page for {code}. URL: {url}")
                return None

            entity = EntityMovie(cls.site_name, code)
            entity.country = ["일본"]; entity.mpaa = "청소년 관람불가"
            entity.thumb = []; entity.fanart = []; entity.tag = []; entity.actor = []
            entity.original = {}

            # === 2. 메타데이터 파싱 ===
            info_node = tree.xpath("//div[contains(@class, 'container')]//div[@class='col-md-3 info']")[0]

            # 페이지 내 품번을 최우선으로 사용, 키워드는 폴백으로 사용
            # 1. 페이지에서 "識別碼"(식별 코드)를 가져옵니다.
            ui_code_val_nodes = info_node.xpath("./p[./span[@class='header' and contains(text(),'識別碼')]]/span[not(@class='header')]//text()")
            if not ui_code_val_nodes:
                ui_code_val_nodes = info_node.xpath("./p[./span[@class='header' and contains(text(),'識別碼')]]/text()[normalize-space()]")
            raw_ui_code_from_page = "".join(ui_code_val_nodes).strip()

            # 2. 페이지 품번이 존재하면 그것을 최종 UI Code로 확정합니다.
            if raw_ui_code_from_page:
                entity.ui_code, _, _ = cls._parse_ui_code(raw_ui_code_from_page)
                logger.debug(f"JavBus Info: UI Code set from page '識別碼' -> '{entity.ui_code}'")
            else:
                # 3. 페이지 품번이 없을 경우, 키워드를 폴백으로 사용합니다.
                logger.warning(f"JavBus Info: '識別碼' not found on page. Falling back to keyword.")
                if not keyword:
                    try:
                        cache = F.get_cache(f"{P.package_name}_jav_censored_keyword_cache")
                        keyword = cache.get(code)
                    except Exception as e:
                        logger.warning(f"[{cls.site_name} Info] Failed to get keyword from cache: {e}")
                
                if keyword:
                    entity.ui_code, _, _ = cls._parse_ui_code(keyword)
                    logger.debug(f"JavBus Info: UI Code set from keyword (fallback) -> '{entity.ui_code}'")
                else:
                    # 키워드도 없으면 URL 일부를 최후의 폴백으로 사용
                    logger.error(f"JavBus Info: No keyword available. Using URL part as last resort.")
                    entity.ui_code, _, _ = cls._parse_ui_code(original_code_for_url)

            entity.title = entity.originaltitle = entity.sorttitle = entity.ui_code

            h3_text = tree.xpath("normalize-space(//div[@class='container']/h3/text())")
            cleaned_h3_text = cls.A_P(h3_text)

            original_tagline = ""
            if cleaned_h3_text:
                if cleaned_h3_text.upper().startswith(entity.ui_code):
                    original_tagline = cleaned_h3_text[len(entity.ui_code):].strip()
                else:
                    original_tagline = cleaned_h3_text

            entity.original['tagline'] = original_tagline
            entity.tagline = cls.trans(original_tagline)

            if not entity.plot and entity.tagline and entity.tagline != entity.ui_code:
                entity.plot = entity.tagline

            all_p_tags_in_info = info_node.xpath("./p")
            genre_header_p_node = actor_header_p_node = None
            
            for p_tag_node_loop in all_p_tags_in_info:
                full_text = p_tag_node_loop.xpath("string(.)").strip()
                if full_text.startswith("類別:"): 
                    genre_header_p_node = p_tag_node_loop
                elif full_text.startswith("演員:"):
                    actor_header_p_node = p_tag_node_loop

            for p_tag in all_p_tags_in_info:
                header_span = p_tag.xpath("./span[@class='header']")
                if not header_span: continue
                
                header_text = header_span[0].text_content().strip()
                key = header_text.replace(":", "").strip()
                
                if key in ["類別", "演員"]: continue

                full_p_text = p_tag.xpath("string(.)").strip()
                
                # 헤더 부분 제거 (예: "識別碼: DVDES-532" -> "DVDES-532")
                if full_p_text.startswith(header_text):
                    value = full_p_text[len(header_text):].strip()
                else:
                    value_nodes = header_span[0].xpath("./following-sibling::node()")
                    value = ""
                    for node in value_nodes:
                        if isinstance(node, str):
                            value += node
                        elif hasattr(node, 'text_content'):
                            value += node.text_content()
                    value = value.strip()

                if not value or value == "----": continue

                if key == "識別碼":
                    pass 
                elif key == "發行日期":
                    if value != "0000-00-00": entity.premiered, entity.year = value, int(value[:4])
                elif key == "長度":
                    try: entity.runtime = int(value.replace("分鐘", "").strip())
                    except: pass
                elif key == "導演": entity.director = value
                elif key == "製作商":
                    entity.original['studio'] = value
                    entity.studio = cls.trans(value)
                elif key == "發行商" and not entity.studio:
                    entity.original['studio'] = value
                    entity.studio = cls.trans(value)
                elif key == "系列":
                    entity.original['series'] = value
                    trans_series = cls.trans(value)
                    if trans_series not in entity.tag:
                        entity.tag.append(trans_series)

            if genre_header_p_node is not None:
                entity.genre = []
                if 'genre' not in entity.original: 
                    entity.original['genre'] = []
                for genre_span in genre_header_p_node.xpath("./following-sibling::p[1]/span[@class='genre']"):
                    genre_ja = "".join(genre_span.xpath("./label/a/text() | ./a/text()")).strip()
                    if not genre_ja or genre_ja == "多選提交" or genre_ja in AV_GENRE_IGNORE_JA: 
                        continue
                    entity.original['genre'].append(genre_ja)
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

            # === 3. 이미지 URL 수집 및 처리 위임 ===
            ps_url_from_search_cache = cls._ps_url_cache.get(code, {}).get('ps')

            try:
                # 3-1. 페이지에서 모든 원본 이미지 URL 수집
                raw_image_urls = cls.__img_urls(tree)

                # 3-2. fp_meta_mode에 따른 분기 처리
                entity = cls.process_image_data(entity, raw_image_urls, ps_url_from_search_cache)

            except Exception as e:
                logger.exception(f"JavBus: Error during image processing for {code}: {e}")

            # === 4. Shiroutoname 보정 처리 ===
            if entity.originaltitle:
                try:
                    entity = cls.shiroutoname_info(entity)
                except Exception as e_shirouto:
                    logger.exception(f"JavBus: Shiroutoname error: {e_shirouto}")

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
        if tree is None:
            return {'ps': "", 'pl': "", 'arts': [], 'specific_poster_candidates': []}

        try:
            # 1. PL (큰 포스터) URL 수집
            pl_nodes = tree.xpath('//a[@class="bigImage"]/img/@src')
            pl_url = cls.__fix_url(pl_nodes[0]) if pl_nodes else ""

            # 2. PS (작은 포스터) URL 유추
            ps_url = ""
            if pl_url:
                try:
                    filename = pl_url.split("/")[-1].replace("_b.", ".")
                    ps_url = cls.__fix_url(f"/pics/thumb/{filename}")
                except Exception: pass

            # 3. Arts (샘플 이미지) URL 수집
            all_sample_images = []
            for href_art in tree.xpath('//*[@id="sample-waterfall"]/a/@href'):
                all_sample_images.append(cls.__fix_url(href_art))
            all_sample_images = list(dict.fromkeys(all_sample_images))

            # 4. 역할에 맞게 데이터 분류 및 정제
            thumb_candidates = set()
            if pl_url:
                thumb_candidates.add(pl_url)

            # Javbus는 PL 외에 명확한 포스터 후보가 없으므로 specific_poster_candidates는 비워둠
            specific_poster_candidates = []

            # 순수 팬아트 목록 생성
            pure_arts = [art for art in all_sample_images if art and art not in thumb_candidates]

            # 5. 최종 결과 반환
            ret = {
                "ps": ps_url,
                "pl": pl_url,
                "specific_poster_candidates": specific_poster_candidates,
                "arts": pure_arts
            }
            logger.debug(f"JavBus __img_urls collected: PS='{ret['ps']}', PL='{ret['pl']}', SpecificCandidates={len(ret['specific_poster_candidates'])}, PureArts={len(ret['arts'])}")
            return ret
        except Exception as e:
            logger.exception(f"JavBus __img_urls: Error extracting URLs: {e}")
            return {'ps': "", 'pl': "", 'arts': [], 'specific_poster_candidates': []}


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
