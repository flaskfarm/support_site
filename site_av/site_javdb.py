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
    default_headers.update({"Referer": SITE_BASE_URL + "/"})

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

        # 전역 파서를 사용하여 검색 키워드 정규화
        kw_ui_code, kw_label_part, kw_num_part = cls._parse_ui_code(temp_keyword)

        search_keyword_for_url = py_urllib_parse.quote_plus(kw_ui_code)
        search_url = f"{SITE_BASE_URL}/search?q={search_keyword_for_url}&f=all"
        logger.debug(f"JavDB Search: original='{original_keyword}', parsed_kw='{kw_ui_code}', url='{search_url}'")

        custom_cookies_for_search = {'over18': '1'}
        res_for_search = cls.get_response_cs(search_url, cookies=custom_cookies_for_search)

        # --- 접속 오류 및 Cloudflare 관련 방어 로직 복원 ---
        if res_for_search is None:
            logger.error(f"JavDB Search: Failed to get response for keyword '{kw_ui_code}'.")
            return []

        html_content_text = res_for_search.text
        if res_for_search.status_code != 200:
            logger.warning(f"JavDB Search: Status code {res_for_search.status_code} for URL: {res_for_search.url} (keyword: '{kw_ui_code}')")
            if "cf-error-details" in html_content_text or "Cloudflare to restrict access" in html_content_text:
                logger.error(f"JavDB Search: Cloudflare restriction page detected for '{kw_ui_code}' (IP block).")
            if "Due to copyright restrictions" in html_content_text or "由於版權限制" in html_content_text:
                logger.error(f"JavDB Search: Access prohibited for '{kw_ui_code}' (country block).")
            if "cf-challenge-running" in html_content_text or "Verifying you are human" in html_content_text:
                logger.error(f"JavDB Search: Cloudflare challenge page detected for '{kw_ui_code}'.")
            return []

        try:
            tree = html.fromstring(html_content_text)
        except Exception as e_parse:
            logger.error(f"JavDB Search: Failed to parse HTML for '{kw_ui_code}': {e_parse}")
            return []

        item_list_xpath_expression = '//div[(contains(@class, "item-list") or contains(@class, "movie-list"))]//div[contains(@class, "item")]/a[contains(@class, "box")]'
        item_nodes = tree.xpath(item_list_xpath_expression)

        if not item_nodes:
            if tree.xpath('//div[contains(@class, "empty-message") and (contains(text(), "No videos found") or contains(text(), "沒有找到影片"))]'):
                logger.info(f"JavDB Search: 'No videos found' message on page for keyword '{kw_ui_code}'.")
            else:
                logger.warning(f"JavDB Search: No item nodes found for keyword '{kw_ui_code}'.")
            return []

        final_search_results_list = []
        processed_codes_in_search = set()

        # --- 검색 결과 아이템 처리 루프 ---
        for node_a_tag in item_nodes[:10]:
            try:
                item = EntityAVSearch(cls.site_name)

                detail_link = node_a_tag.attrib.get('href', '').strip()
                item_code_match = re.search(r'/v/([^/?]+)', detail_link)
                if not item_code_match: continue
                item_code_raw = item_code_match.group(1).strip()
                item.code = cls.module_char + cls.site_char + item_code_raw

                if item.code in processed_codes_in_search:
                    continue
                processed_codes_in_search.add(item.code)

                visible_code_on_card = node_a_tag.xpath('string(.//div[@class="video-title"]/strong[1])').strip().upper()
                raw_ui_code = visible_code_on_card if visible_code_on_card else item_code_raw
                item_ui_code, item_label_part, item_num_part = cls._parse_ui_code(raw_ui_code)
                item.ui_code = item_ui_code

                # --- 점수 계산 ---
                kw_std_code = kw_label_part.lower() + kw_num_part.zfill(5) if kw_num_part.isdigit() else kw_label_part.lower() + kw_num_part
                item_std_code = item_label_part.lower() + item_num_part.zfill(5) if item_num_part.isdigit() else item_label_part.lower() + item_num_part

                if kw_std_code == item_std_code:
                    item.score = 100
                elif kw_ui_code.lower() == item.ui_code.lower():
                    item.score = 95
                else:
                    item.score = 60
                if not item.score:
                    item.score = 20

                item.image_url = ""
                item_img_tag_src = node_a_tag.xpath('.//div[contains(@class, "cover")]/img/@src')
                if item_img_tag_src:
                    img_url_raw = item_img_tag_src[0].strip()
                    if img_url_raw.startswith("//"): item.image_url = "https:" + img_url_raw
                    elif img_url_raw.startswith("http"): item.image_url = img_url_raw

                video_title_node = node_a_tag.xpath('.//div[@class="video-title"]')[0]
                temp_title_node = html.fromstring(html.tostring(video_title_node))
                for strong_el in temp_title_node.xpath('.//strong'):
                    strong_el.getparent().remove(strong_el)
                item.title = temp_title_node.text_content().strip()

                item.year = 0
                date_meta_text_nodes = node_a_tag.xpath('.//div[@class="meta"]/text()')
                if date_meta_text_nodes:
                    for text_node_val in reversed(date_meta_text_nodes):
                        date_match = re.search(r'(\d{4})', text_node_val.strip())
                        if date_match:
                            try: item.year = int(date_match.group(1))
                            except ValueError: pass
                            break

                if manual: 
                    if cls.config.get('use_proxy'):
                        item.image_url = cls.make_image_url(item.image_url)
                    item.title_ko = "(현재 인터페이스에서는 번역을 제공하지 않습니다) " + item.title
                else: 
                    item.title_ko = cls.trans(item.title)

                item_dict = item.as_dict()
                item_dict['is_priority_label_site'] = False 
                item_dict['site_key'] = cls.site_name

                if item_dict.get('ui_code') and cls.config.get('priority_labels_set'):
                    label_to_check = item_dict['ui_code'].split('-', 1)[0]
                    if label_to_check in cls.config['priority_labels_set']:
                        item_dict['is_priority_label_site'] = True

                final_search_results_list.append(item_dict)

            except Exception as e_item_parse:
                logger.exception(f"JavDB Search Item: Error parsing item for keyword '{keyword}': {e_item_parse}")

        sorted_result = sorted(final_search_results_list, key=lambda k: k.get("score", 0), reverse=True)

        if sorted_result:
            log_count = min(len(sorted_result), 5)
            logger.debug(f"JavDB Search: Top {log_count} results for '{kw_ui_code}':")
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
                ret["data"] = f"Failed to get JavDB info for {code}"
        except Exception as e:
            ret["ret"] = "exception"
            ret["data"] = str(e)
            logger.exception(f"JavDB info error: {e}")
        return ret
    

    @classmethod
    def __info(cls, code, keyword=None, fp_meta_mode=False):
        custom_cookies = { 'over18': '1', 'locale': 'en' }
        custom_cookies['cf_clearance'] = ''

        original_code_for_url = code[len(cls.module_char) + len(cls.site_char):]
        detail_url = f"{SITE_BASE_URL}/v/{original_code_for_url}"
        temp_poster_file_to_clean = None

        original_keyword = None
        if keyword:
            # 1. keyword 인자가 명시적으로 주어진 경우 (fp_av 등)
            original_keyword = keyword
            logger.debug(f"JavDB Info: Using provided keyword '{original_keyword}' for {code}.")
        else:
            # 2. keyword가 주어지지 않은 경우 (일반 메타 검색) - 기존 캐시 로직 사용
            try:
                keyword_cache = F.get_cache('jav_censored_keyword_cache')
                if keyword_cache:
                    original_keyword = keyword_cache.get(code)
                    if original_keyword:
                        logger.debug(f"JavDB Info: Found keyword '{original_keyword}' in cache for {code}.")
            except Exception as e_cache:
                logger.warning(f"JavDB Info: Failed to get keyword from cache for {code}: {e_cache}")

        tree = None
        entity = None

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
            tree = html.fromstring(html_info_text)
            if tree is None:
                logger.warning(f"JavDB Info: Failed to parse detail page HTML for {code}.")
                return None

            entity = EntityMovie(cls.site_name, code)
            entity.country = ['일본']; entity.mpaa = '청소년 관람불가'
            entity.thumb = []; entity.fanart = []; entity.extras = []; entity.ratings = []; entity.tag = []

            # === 2. 메타데이터 파싱 ===
            raw_ui_code = ""
            # 1. 'ID:' 패널 블록에서 품번을 먼저 시도
            id_panel_block = tree.xpath('//div[@class="panel-block" and ./strong[contains(text(),"ID:")]]/span[@class="value"]/text()')
            if id_panel_block:
                raw_ui_code = id_panel_block[0].strip()

            # 2. 'ID:'가 없으면, h2 태그의 strong 부분에서 폴백
            if not raw_ui_code:
                h2_code_node = tree.xpath('//h2[@class="title is-4"]/strong[1]/text()')
                if h2_code_node:
                    raw_ui_code = h2_code_node[0].strip()
            
            # 3. 전역 파서로 파싱
            final_ui_code, _, _ = cls._parse_ui_code(raw_ui_code)

            # 4. 최종 ui_code 할당 (파싱 성공 시 파싱된 값, 실패 시 URL 내부 ID)
            entity.ui_code = final_ui_code.upper() if final_ui_code else original_code_for_url.upper()
            entity.title = entity.originaltitle = entity.sorttitle = entity.ui_code
            current_ui_code_for_image = entity.ui_code.lower()

            if '-' in current_ui_code_for_image and current_ui_code_for_image.split('-',1)[0].upper() not in entity.tag:
                entity.tag.append(current_ui_code_for_image.split('-',1)[0].upper())

            actual_raw_title_text = ""
            h2_title_node = tree.xpath('//h2[@class="title is-4"]')
            if h2_title_node:
                full_h2_text = h2_title_node[0].text_content().strip()
                visible_code_in_h2 = tree.xpath('string(//h2[@class="title is-4"]/strong[1])').strip().upper()
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
            panel_blocks = tree.xpath('//nav[contains(@class, "movie-panel-info")]/div[contains(@class,"panel-block")]')
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

            # === 3. 이미지 처리 위임 ===
            # JavDB는 PS가 없으므로 ps_url_from_cache는 항상 None
            ps_url_from_search_cache = None

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
                logger.exception(f"JavDB: Error during image processing delegation for {code}: {e}")

            # === 4. 예고편 및 Shiroutoname 보정 처리 ===
            if not fp_meta_mode and cls.config['use_extras']:
                trailer_source_tag = tree.xpath('//video[@id="preview-video"]/source/@src')
                if trailer_source_tag:
                    trailer_url_raw = trailer_source_tag[0].strip()
                    if trailer_url_raw:
                        trailer_url_final = "https:" + trailer_url_raw if trailer_url_raw.startswith("//") else trailer_url_raw
                        trailer_url_final = cls.make_video_url(trailer_url_final)
                        entity.extras.append(EntityExtra("trailer", entity.tagline or entity.ui_code, "mp4", trailer_url_final))
            elif fp_meta_mode:
                # logger.debug(f"FP Meta Mode: Skipping extras processing for {code}.")
                pass

            if entity.originaltitle:
                try:
                    entity = cls.shiroutoname_info(entity)
                except Exception as e_shirouto:
                    logger.exception(f"JavDB Info: Shiroutoname error: {e_shirouto}")

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


    @classmethod
    def __img_urls(cls, tree):
        ret = {'ps': None, 'pl': None, 'arts': [], 'specific_poster_candidates': []}
        try:
            # PL (메인 커버)
            pl_nodes = tree.xpath('//div[@class="column column-video-cover"]//img[@class="video-cover"]/@src')
            if pl_nodes:
                pl_url = pl_nodes[0].strip()
                ret['pl'] = "https:" + pl_url if pl_url.startswith("//") else pl_url

            # Arts (샘플 이미지)
            arts_nodes = tree.xpath('//div[contains(@class, "preview-images")]/a[@class="tile-item"]/@href')
            arts_urls = ["https:" + href if href.startswith("//") else href for href in arts_nodes]
            ret['arts'] = list(dict.fromkeys(arts_urls))

            # specific_poster_candidates
            # JavDB는 VR 콘텐츠의 경우 첫 번째 샘플 이미지가 포스터일 수 있음
            if ret['arts']:
                ret['specific_poster_candidates'].append(ret['arts'][0])
        except Exception as e:
            logger.error(f"JavDB __img_urls Error: {e}")

        return ret


    # endregion INFO
    ################################################

    # --- 삭제할 코드 ---
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



    ################################################
    # region SiteAvBase 메서드 오버라이드

    @classmethod
    def set_config(cls, db):
        super().set_config(db)
        cls.config.update({
            "crop_mode": db.get_list(f"jav_censored_{cls.site_name}_crop_mode", ","),
            "priority_labels": db.get_list(f"jav_censored_{cls.site_name}_priority_search_labels", ","),
        })
        cls.config['priority_labels_set'] = {lbl.strip().upper() for lbl in cls.config.get('priority_labels', []) if lbl.strip()}


    # endregion SiteAvBase 메서드 오버라이드
    ################################################
