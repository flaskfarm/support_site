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
                item_ui_code, item_label_part, item_num_part = cls._parse_ui_code(raw_ui_code_from_page)
                item.ui_code = item_ui_code

                # --- 비교용 표준 코드 생성 (5자리 패딩으로 통일) ---
                kw_std_code = kw_label_part + kw_num_part.zfill(5) if kw_num_part.isdigit() else kw_label_part + kw_num_part
                item_std_code = item_label_part + item_num_part.zfill(5) if item_num_part.isdigit() else item_label_part + item_num_part

                if kw_std_code.lower() == item_std_code.lower():
                    item.score = 100
                elif kw_ui_code.lower() == item.ui_code.lower():
                    item.score = 95 # 하이픈 유무 차이
                else:
                    # 부분 일치 점수
                    kw_parts = set(kw_ui_code.lower().replace('-', ' ').split())
                    item_parts = set(item.ui_code.lower().replace('-', ' ').split())
                    if kw_parts.issubset(item_parts):
                        item.score = 80
                    else:
                        item.score = 60
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

            if not keyword:
                try:
                    cache = F.get_cache(f"{P.package_name}_jav_censored_keyword_cache")
                    keyword = cache.get(code)
                    if keyword:
                        logger.debug(f"[{cls.site_name} Info] Restored keyword '{keyword}' from cache for code '{code}'.")
                except Exception as e:
                    logger.warning(f"[{cls.site_name} Info] Failed to get keyword from cache: {e}")

            # 페이지에서 "識別碼"를 가져와 검증/폴백용으로 준비
            ui_code_val_nodes = info_node.xpath("./p[./span[@class='header' and contains(text(),'識別碼')]]/span[not(@class='header')]//text()")
            if not ui_code_val_nodes:
                ui_code_val_nodes = info_node.xpath("./p[./span[@class='header' and contains(text(),'識別碼')]]/text()[normalize-space()]")
            raw_ui_code_from_page = "".join(ui_code_val_nodes).strip()

            if keyword:
                trusted_ui_code, _, _ = cls._parse_ui_code(keyword)
                logger.debug(f"JavBus Info: Using trusted UI code '{trusted_ui_code}' from keyword '{keyword}'.")

                # 페이지 품번과 교차 검증
                if raw_ui_code_from_page:
                    parsed_pid_from_page, _, _ = cls._parse_ui_code(raw_ui_code_from_page)
                    core_trusted = re.sub(r'[^A-Z0-9]', '', trusted_ui_code.upper())
                    core_page = re.sub(r'[^A-Z0-9]', '', parsed_pid_from_page.upper())
                    if not (core_trusted in core_page or core_page in core_trusted):
                        logger.warning(f"JavBus Info: Significant UI code mismatch detected!")
                        logger.warning(f"  - Trusted UI Code: {trusted_ui_code}")
                        logger.warning(f"  - Page UI Code (for verification): {parsed_pid_from_page}")
            else:
                # keyword가 없으면 페이지 정보(폴백)를 신뢰.
                trusted_ui_code, _, _ = cls._parse_ui_code(raw_ui_code_from_page)
                logger.debug(f"JavBus Info: No keyword. Using UI code '{trusted_ui_code}' from page.")

            entity.ui_code = trusted_ui_code
            entity.title = entity.originaltitle = entity.sorttitle = entity.ui_code

            h3_text = tree.xpath("normalize-space(//div[@class='container']/h3/text())")
            cleaned_h3_text = cls.A_P(h3_text)

            if cleaned_h3_text.upper().startswith(entity.ui_code):
                tagline_text = cleaned_h3_text[len(entity.ui_code):].strip()
            else:
                tagline_text = cleaned_h3_text

            entity.original['tagline'] = original_tagline
            entity.tagline = cls.trans(original_tagline)

            if not entity.plot and entity.tagline and entity.tagline != entity.ui_code:
                entity.plot = entity.tagline

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


    @classmethod
    def get_response(cls, url, **kwargs):
        """
        Javbus는 모든 요청에 Cloudflare 보호가 적용되므로,
        get_response를 오버라이드하여 항상 cloudscraper를 사용하도록 강제하고,
        SSL 검증을 비활성화하며, 필요한 헤더와 쿠키를 설정합니다.
        """
        if 'cookies' not in kwargs:
            kwargs['cookies'] = {}
        kwargs['cookies'].update({'age': 'verified', 'age_check_done': '1', 'ckcy': '1', 'dv': '1', 'existmag': 'mag'})

        # SSL 인증서 검증 비활성화 (ValueError 해결)
        # 이 값이 get_response_cs로 전달되어 no_verify 인스턴스를 선택하게 함
        kwargs['verify'] = False

        # logger.debug(f"Javbus: Using overridden get_response -> get_response_cs for URL: {url}")
        return super().get_response_cs(url, **kwargs)


    @classmethod
    def jav_image(cls, url, mode=None, **kwargs):
        """
        [이미지 요청용] jav_image 요청도 Cloudflare를 통과해야 하므로,
        get_response를 오버라이드한 이 클래스의 로직을 타도록 default_jav_image를 호출.
        kwargs를 통해 사용하지 않는 인자(예: site)를 받아 에러를 방지.
        """
        # logger.debug(f"Javbus: Using overridden jav_image (default_jav_image) for URL: {url}")
        return cls.default_jav_image(url, mode)


    # endregion SiteAvBase 메서드 오버라이드
    ################################################
