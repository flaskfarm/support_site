import re
import os

from ..constants import MGS_CODE_LEN, MGS_LABEL_MAP, AV_GENRE, AV_GENRE_IGNORE_JA, AV_GENRE_IGNORE_KO
from ..entity_av import EntityAVSearch
from ..entity_base import EntityActor, EntityExtra, EntityMovie, EntityRatings, EntityThumb
from ..setup import P, logger
from .site_av_base import SiteAvBase


SITE_BASE_URL = "https://www.mgstage.com"
PTN_SEARCH_PID = re.compile(r"\/product_detail\/(?P<code>.*?)\/")
PTN_TEXT_SUB = [
    re.compile(r"【(?<=【)(?:MGSだけのおまけ映像付き|期間限定).*(?=】)】(:?\s?\+\d+分\s?)?"),
    re.compile(r"※通常版\+\d+分の特典映像付のスペシャルバージョン！"),
    re.compile(r"【(?<=【).+実施中(?=】)】"),
]
PTN_RATING = re.compile(r"\s(?P<rating>[\d\.]+)点\s.+\s(?P<vote>\d+)\s件")

class SiteMgstage(SiteAvBase):
    site_name = "mgstage"
    site_char = "M"
    module_char = "C"
    default_headers = SiteAvBase.base_default_headers.copy()
    default_headers.update({
        "Referer": SITE_BASE_URL + "/",
        "Cookie": "coc=1;mgs_agef=1;",
    })
    _ps_url_cache = {} 

    ################################################
    # region SEARCH

    @classmethod
    def search(cls, keyword, do_trans, manual):
        ret = {}
        try:
            # 1. 입력된 키워드를 전역 파서로 우선 정규화
            normalized_ui_code, _, _ = cls._parse_ui_code(keyword)

            search_keyword_for_mgs = normalized_ui_code # 기본 검색어는 정규화된 품번

            # 2. MGS_LABEL_MAP을 사용한 레이블 변환 시도
            if '-' in normalized_ui_code:
                input_label, code_part = normalized_ui_code.split('-', 1)
                
                mgs_labels_to_try = MGS_LABEL_MAP.get(input_label.upper())
                if mgs_labels_to_try:
                    mgs_label = mgs_labels_to_try[0]
                    if codelen := MGS_CODE_LEN.get(mgs_label):
                        try: code_part = str(int(code_part)).zfill(codelen)
                        except ValueError: pass
                    search_keyword_for_mgs = f"{mgs_label}-{code_part}"
                    logger.debug(f"MGStage Search: Mapping '{keyword}' to '{search_keyword_for_mgs}' for search.")

            data = cls.__search(search_keyword_for_mgs, normalized_ui_code, do_trans, manual)
        except Exception as exception:
            logger.exception("검색 결과 처리 중 예외:")
            ret["ret"] = "exception"; ret["data"] = str(exception)
        else:
            ret["ret"] = "success" if data else "no_match"; ret["data"] = data
        return ret


    @classmethod
    def __search(cls, keyword_for_url, original_ui_code, do_trans, manual):

        url = f"{SITE_BASE_URL}/search/cSearch.php?search_word={keyword_for_url}&x=0&y=0&type=top"
        logger.debug(f"MGStage Search URL: {url}")

        tree = cls.get_tree(url)
        if tree is None:
            logger.warning(f"MGStage Search ({cls.module_char}): Failed to get tree for URL: {url}")
            return []

        lists = tree.xpath('//div[@class="search_list"]/div/ul/li')

        ret = []
        # 비교 기준이 될 검색 키워드를 미리 파싱
        kw_ui_code, _, _ = cls._parse_ui_code(original_ui_code)

        for node in lists[:10]:
            try:
                item = EntityAVSearch(cls.site_name)

                # 1. 링크에서 PID(제품 ID) 추출
                tag = node.xpath(".//a")[0]
                href = tag.attrib["href"].lower()
                match = PTN_SEARCH_PID.search(href)
                if not match: 
                    continue

                pid_from_link = match.group("code").upper()

                # 2. 전역 파서로 검색어와 결과 품번을 모두 정규화
                kw_ui_code, kw_label_part, kw_num_part = cls._parse_ui_code(original_ui_code)
                item_ui_code, item_label_part, item_num_part = cls._parse_ui_code(pid_from_link)
                
                item.ui_code = item_ui_code
                item.code = cls.module_char + cls.site_char + pid_from_link

                # 3. 정규화된 품번으로 점수 계산 (5자리 패딩으로 통일)
                kw_std_code = kw_label_part.lower() + kw_num_part.zfill(5) if kw_num_part.isdigit() else kw_label_part.lower() + kw_num_part
                item_std_code = item_label_part.lower() + item_num_part.zfill(5) if item_num_part.isdigit() else item_label_part.lower() + item_num_part

                if kw_std_code.lower() == item_std_code.lower():
                    item.score = 100
                elif kw_ui_code.lower().replace('-', '') == item.ui_code.lower().replace('-', ''):
                    item.score = 95
                else:
                    # 검색어의 레이블/숫자와 결과의 레이블/숫자를 비교하여 부분 점수 부여
                    kw_label, kw_num = kw_ui_code.split('-', 1) if '-' in kw_ui_code else (kw_ui_code, "")
                    item_label, item_num = item.ui_code.split('-', 1) if '-' in item.ui_code else (item.ui_code, "")
                    if kw_label.lower() == item_label.lower() and kw_num in item_num:
                        item.score = 80
                    else:
                        item.score = 60
                if not item.score:
                    item.score = 20

                # 4. 중복 아이템 체크 (ui_code 기준)
                if any(exist_item["ui_code"] == item.ui_code for exist_item in ret):
                    continue

                # 5. 나머지 정보 파싱 (이미지, 제목 등)
                tag_img = node.xpath(".//img")[0]
                item.image_url = tag_img.attrib["src"]
                if item.code and item.image_url:
                    cls._ps_url_cache[item.code] = {'ps': item.image_url}

                tag_title = node.xpath('.//a[@class="title lineclamp"]')[0]
                title = tag_title.text_content()
                for ptn in PTN_TEXT_SUB:
                    title = ptn.sub("", title)
                item.title = title.strip()

                # 6. manual 모드 및 번역 처리
                if manual:
                    if cls.config.get('use_proxy') and item.image_url:
                        item.image_url = cls.make_image_url(item.image_url)
                    item.title_ko = "(현재 인터페이스에서는 번역을 제공하지 않습니다) " + item.title
                else:
                    item.title_ko = cls.trans(item.title)

                # 7. 최종 딕셔너리 생성 및 추가
                item_dict = item.as_dict()
                item_dict['is_priority_label_site'] = False
                item_dict['site_key'] = cls.site_name

                if item_dict.get('ui_code') and cls.config.get('priority_labels_set'):
                    label_to_check = item_dict['ui_code'].split('-', 1)[0]
                    if label_to_check in cls.config['priority_labels_set']:
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
                ret["data"] = f"Failed to get MGStage info for {code}"
        except Exception as e: 
            ret["ret"] = "exception"
            ret["data"] = str(e)
            logger.exception(f"MGStage info error: {e}")
        return ret


    @classmethod
    def __info(cls, code, keyword=None, fp_meta_mode=False):
        cached_data = cls._ps_url_cache.get(code, {}) 
        ps_url_from_search_cache = cached_data.get('ps')

        url = SITE_BASE_URL + f"/product/product_detail/{code[2:]}/"
        tree = cls.get_tree(url)
        if tree is None:
            logger.error(f"MGStage info error: Failed to get page tree for {code}. URL: {url}")
            return None

        entity = EntityMovie(cls.site_name, code)
        entity.country = ["일본"]; entity.mpaa = "청소년 관람불가"; entity.tag = []
        entity.thumb = []; entity.fanart = []; entity.extras = []; entity.ratings = []

        mgs_special_poster_filepath = None

        try:
            # === 2. 메타데이터 파싱 ===
            h1_tags = tree.xpath('//h1[@class="tag"]/text()')
            if h1_tags:
                h1_text_raw = h1_tags[0]
                for ptn in PTN_TEXT_SUB: h1_text_raw = ptn.sub("", h1_text_raw)
                entity.tagline = cls.trans(h1_text_raw.strip())
            
            info_table_xpath = '//div[@class="detail_data"]//tr'
            tr_nodes = tree.xpath(info_table_xpath)

            temp_shohin_hatsubai = None
            temp_haishin_kaishi = None

            for tr_node in tr_nodes:
                key_node = tr_node.xpath("./th"); value_node_outer = tr_node.xpath("./td")
                if not key_node or not value_node_outer: continue
                key_text = key_node[0].text_content().strip(); value_text_content = value_node_outer[0].text_content().strip()
                value_node_instance = value_node_outer[0]

                if "品番" in key_text:
                    official_code = value_text_content.strip()

                    # --- 전역 파서를 사용하여 최종 ui_code 결정 ---
                    final_ui_code, _, _ = cls._parse_ui_code(official_code)
                    entity.ui_code = final_ui_code.upper()

                    entity.title = entity.originaltitle = entity.sorttitle = entity.ui_code

                    label_for_tag = entity.ui_code.split('-', 1)[0]
                    if entity.tag is None: entity.tag = []
                    if label_for_tag and label_for_tag not in entity.tag:
                        entity.tag.append(label_for_tag)

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
                        trans_s = cls.trans(s_name)
                        if trans_s and trans_s not in (entity.tag or []): 
                            if entity.tag is None: entity.tag = []
                            entity.tag.append(trans_s)
                elif "レーベル" in key_text: 
                    studio_name = (value_node_instance.xpath("./a/text()")[0] if value_node_instance.xpath("./a/text()") else value_text_content).strip()
                    if studio_name: 
                        entity.studio = cls.trans(studio_name)
                elif "ジャンル" in key_text:
                    if entity.genre is None: entity.genre = []
                    for g_tag in value_node_instance.xpath("./a"):
                        g_ja = g_tag.text_content().strip()
                        if "MGSだけのおまけ映像付き" in g_ja or not g_ja or g_ja in AV_GENRE_IGNORE_JA: continue
                        if g_ja in AV_GENRE:
                            g_ko = AV_GENRE[g_ja]
                            if g_ko not in entity.genre: entity.genre.append(g_ko)
                        else:
                            g_ko = cls.trans(g_ja).replace(" ", "")
                            if g_ko not in AV_GENRE_IGNORE_KO and g_ko not in entity.genre: entity.genre.append(g_ko)

            entity.premiered = temp_shohin_hatsubai or temp_haishin_kaishi
            if entity.premiered:
                try: entity.year = int(entity.premiered[:4])
                except (ValueError, IndexError): pass

            rating_nodes = tree.xpath('//div[@class="user_review_head"]/p[@class="detail"]/text()')
            if rating_nodes:
                rating_match = PTN_RATING.search(rating_nodes[0])
                if rating_match:
                    try:
                        rating_val = float(rating_match.group("rating"))
                        votes = int(rating_match.group("vote"))
                        entity.ratings = [EntityRatings(rating_val, max=5, name=cls.site_name, votes=votes)]
                    except Exception: pass

            if not entity.ui_code:
                logger.error(f"MGStage ({cls.module_char}): CRITICAL - Failed to parse identifier for {code}.")
                return None
        except Exception as e_meta:
            logger.exception(f"MGStage ({cls.module_char}): Meta parsing error for {code}: {e_meta}")
            return None

        # 3. 이미지 처리: 모든 이미지 관련 로직을 공통 메서드에 위임
        try:
            raw_image_urls = cls.__img_urls(tree)

            if not fp_meta_mode:
                entity = cls.process_image_data(entity, raw_image_urls, ps_url_from_search_cache)
            else:
                poster_url = raw_image_urls.get('pl') or raw_image_urls.get('specific_poster_candidates', [None])[0]
                if poster_url:
                    entity.thumb.append(EntityThumb(aspect="poster", value=poster_url))

                landscape_url = raw_image_urls.get('pl')
                if landscape_url:
                    entity.thumb.append(EntityThumb(aspect="landscape", value=landscape_url))

                # 팬아트는 URL만 리스트로 할당
                entity.fanart = raw_image_urls.get('arts', [])

        except Exception as e:
            logger.exception(f"MGStage: Error during image processing delegation for {code}: {e}")

        # 4. 예고편 및 Shiroutoname 보정 처리
        if not fp_meta_mode and cls.config['use_extras']:
            if cls.config['use_extras']:
                try:
                    trailer_sample_btn = tree.xpath('//*[@class="sample_movie_btn"]/a/@href')
                    if trailer_sample_btn:
                        pid_trailer = trailer_sample_btn[0].split("/")[-1]
                        api_url_trailer = f"https://www.mgstage.com/sampleplayer/sampleRespons.php?pid={pid_trailer}"
                        api_headers_trailer = cls.default_headers.copy(); api_headers_trailer['Referer'] = url 
                        api_headers_trailer['X-Requested-With'] = 'XMLHttpRequest'; api_headers_trailer['Accept'] = 'application/json, text/javascript, */*; q=0.01'
                        res_json_trailer = cls.get_response(api_url_trailer, headers=api_headers_trailer).json()
                        if res_json_trailer and res_json_trailer.get("url"):
                            trailer_base = res_json_trailer["url"].split(".ism")[0]; 
                            trailer_final_url = trailer_base + ".mp4"
                            trailer_final_url = cls.make_video_url(trailer_final_url)
                            trailer_title_text = entity.tagline if entity.tagline else entity.ui_code 
                            entity.extras.append(EntityExtra("trailer", trailer_title_text, "mp4", trailer_final_url))
                except Exception as e_trailer_proc_dvd:
                    logger.exception(f"MGStage ({cls.module_char}): Error processing trailer: {e_trailer_proc_dvd}")
        elif fp_meta_mode:
            # logger.debug(f"FP Meta Mode: Skipping extras processing for {code}.")
            pass

        if entity.originaltitle:
            try:
                entity = cls.shiroutoname_info(entity)
            except Exception as e_shirouto:
                logger.exception(f"MGStage (Ama): Shiroutoname error: {e_shirouto}")

        logger.info(f"MGStage ({cls.module_char}): __info finished for {code}. UI Code: {entity.ui_code}")
        return entity


    @classmethod
    def __img_urls(cls, tree):
        pl_nodes = tree.xpath('//*[@id="package"]/a/@href')
        pl_url = pl_nodes[0] if pl_nodes else ""
        
        all_sample_images = tree.xpath('//*[@id="sample-photo"]//ul/li/a/@href')
        
        # pl에서 파생된 pf가 있다면, 샘플 목록의 맨 앞에 추가
        if pl_url and "pb_e_" in pl_url:
            potential_pf = pl_url.replace("pb_e_", "pf_e_")
            if potential_pf not in all_sample_images:
                all_sample_images.insert(0, potential_pf)

        specific_poster_candidates = []
        if all_sample_images:
            specific_poster_candidates.append(all_sample_images[0])
            if len(all_sample_images) > 1 and all_sample_images[-1] != all_sample_images[0]:
                specific_poster_candidates.append(all_sample_images[-1])
        
        ret = {
            "pl": pl_url,
            "specific_poster_candidates": specific_poster_candidates,
            "arts": all_sample_images
        }

        logger.debug(f"MGStage __img_urls collected: PL='{ret['pl']}', SpecificCandidates={len(ret['specific_poster_candidates'])}, Total Sample Arts={len(ret['arts'])}")
        return ret


    # endregion INFO
    ################################################


    ################################################
    # region 전용 UTIL

    # --- 삭제할 코드 ---
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



    # endregion UTIL
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