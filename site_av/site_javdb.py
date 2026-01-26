# -*- coding: utf-8 -*-
import re
import urllib.parse as py_urllib_parse
from lxml import html

from ..entity_av import EntityAVSearch
from ..entity_base import EntityMovie, EntityActor, EntityThumb, EntityExtra, EntityRatings
from ..setup import P, logger
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

        kw_ui_code, kw_label_part, kw_num_part = cls._parse_ui_code(temp_keyword)

        search_keyword_for_url = py_urllib_parse.quote_plus(kw_ui_code)
        search_url = f"{SITE_BASE_URL}/search?q={search_keyword_for_url}&f=all"
        logger.debug(f"JavDB Search: original='{original_keyword}', parsed_kw='{kw_ui_code}', url='{search_url}'")

        tree = cls.get_tree(search_url)

        if tree is None:
            logger.warning(f"JavDB Search: Failed to get content for '{original_keyword}' (curl_cffi failed).")
            return []

        item_list_xpath_expression = '//div[(contains(@class, "item-list") or contains(@class, "movie-list"))]//div[contains(@class, "item")]/a[contains(@class, "box")]'
        item_nodes = tree.xpath(item_list_xpath_expression)

        if not item_nodes:
            if tree.xpath('//div[contains(@class, "empty-message") and (contains(text(), "No videos found") or contains(text(), "沒有找到影片"))]'):
                logger.info(f"JavDB Search: 'No videos found' message on page for keyword '{kw_ui_code}'.")
            else:
                logger.warning(f"JavDB Search: No item nodes found for keyword '{kw_ui_code}'. (Possible parsing error or empty result)")
            return []

        final_search_results_list = []
        processed_codes_in_search = set()

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
                item_ui_code, _, _ = cls._parse_ui_code(raw_ui_code)
                item.ui_code = item_ui_code

                item.score = cls._calculate_score(original_keyword, item.ui_code)
                
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
                logger.exception(f"JavDB Search Item: Error parsing item: {e_item_parse}")

        sorted_result = sorted(final_search_results_list, key=lambda k: k.get("score", 0), reverse=True)
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
        original_code_for_url = code[len(cls.module_char) + len(cls.site_char):]
        detail_url = f"{SITE_BASE_URL}/v/{original_code_for_url}"
        
        original_keyword = keyword

        logger.debug(f"JavDB Info: Accessing URL: {detail_url}")
        tree = cls.get_tree(detail_url)

        if tree is None:
            logger.warning(f"JavDB Info: Failed to get detail page for {code} (curl_cffi failed).")
            return None

        entity = EntityMovie(cls.site_name, code)
        entity.country = ['일본']; entity.mpaa = '청소년 관람불가'
        entity.thumb = []; entity.fanart = []; entity.extras = []; entity.ratings = []; entity.tag = []
        entity.original = {}

        raw_ui_code_from_page = ""
        if id_panel_block := tree.xpath('//div[@class="panel-block" and ./strong[contains(text(),"ID:")]]/span[@class="value"]/text()'):
            raw_ui_code_from_page = id_panel_block[0].strip()
        elif h2_code_node := tree.xpath('//h2[@class="title is-4"]/strong[1]/text()'):
            raw_ui_code_from_page = h2_code_node[0].strip()

        if raw_ui_code_from_page:
            entity.ui_code, _, _ = cls._parse_ui_code(raw_ui_code_from_page)
            logger.debug(f"JavDB Info: UI Code set from page -> '{entity.ui_code}'")

            if original_keyword:
                trusted_ui_code, _, _ = cls._parse_ui_code(original_keyword)
                core_page = re.sub(r'[^A-Z0-9]', '', entity.ui_code.upper())
                core_trusted = re.sub(r'[^A-Z0-9]', '', trusted_ui_code.upper())
                if not (core_trusted in core_page or core_page in core_trusted):
                    logger.warning(f"JavDB Info: Keyword mismatch!")
                    logger.warning(f"  - Keyword (parsed): {trusted_ui_code}")
                    logger.warning(f"  - Final UI Code (from page): {entity.ui_code}")
        else:
            logger.warning(f"JavDB Info: ID not found on page. Falling back to keyword.")
            if original_keyword:
                entity.ui_code, _, _ = cls._parse_ui_code(original_keyword)
                logger.debug(f"JavDB Info: UI Code set from keyword (fallback) -> '{entity.ui_code}'")
            else:
                entity.ui_code, _, _ = cls._parse_ui_code(original_code_for_url)
                logger.error(f"JavDB Info: No keyword available. Using URL part as last resort.")

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
            entity.original['tagline'] = cls.A_P(actual_raw_title_text)
            entity.tagline = cls.trans(cls.A_P(actual_raw_title_text))
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
                if director_text.lower() not in ['n/a', '暂无', '暫無']:
                    entity.original['director'] = director_text
                    entity.director = cls.trans(director_text)
            elif key in ('maker', 'publisher'):
                studio_text = value_node.xpath('normalize-space(./a/text())') or value_node.xpath('normalize-space()')
                if not entity.studio and studio_text.lower() not in ['n/a', '暂无', '暫無']:
                    studio_name = studio_text.split(',')[0].strip()
                    entity.original['studio'] = studio_name
                    entity.studio = cls.trans(studio_name)
            elif key == 'series':
                series_text = value_node.xpath('normalize-space(./a/text())') or value_node.xpath('normalize-space()')
                if series_text.lower() not in ['n/a', '暂无', '暫無']:
                    entity.original['series'] = series_text
                    series_name = cls.trans(series_text)
                    if series_name not in (entity.tag or []):
                        if entity.tag is None: entity.tag = []
                        entity.tag.append(series_name)
            elif key == 'tags':
                if entity.genre is None: entity.genre = []
                if 'genre' not in entity.original: entity.original['genre'] = []
                for genre_name_raw in value_node.xpath('./a/text()'):
                    genre_name = genre_name_raw.strip()
                    if genre_name:
                        entity.original['genre'].append(genre_name)
                        trans_genre = cls.trans(genre_name)
                        if trans_genre not in entity.genre: 
                            entity.genre.append(trans_genre)
            elif key == 'actor(s)':
                if entity.actor is None: entity.actor = []
                for actor_node in value_node.xpath('./a'):
                    if 'female' in (actor_node.xpath('./following-sibling::strong[1]/@class') or [''])[0]:
                        actor_name = actor_node.xpath('string()').strip()
                        if actor_name and actor_name.lower() not in ['n/a', '暂无', '暫無'] and not any(act.originalname == actor_name for act in entity.actor):
                            actor_entity = EntityActor(actor_name)
                            entity.actor.append(actor_entity)

        if not entity.plot and entity.tagline and entity.tagline != entity.ui_code:
            entity.plot = entity.tagline

        ps_url_from_search_cache = None
        try:
            raw_image_urls = cls.__img_urls(tree)
            entity = cls.process_image_data(entity, raw_image_urls, ps_url_from_search_cache)
        except Exception as e:
            logger.exception(f"JavDB: Error during image processing delegation for {code}: {e}")

        if cls.config['use_extras']:
            trailer_source_tag = tree.xpath('//video[@id="preview-video"]/source/@src')
            if trailer_source_tag:
                trailer_url_raw = trailer_source_tag[0].strip()
                if trailer_url_raw:
                    trailer_url_final = "https:" + trailer_url_raw if trailer_url_raw.startswith("//") else trailer_url_raw
                    trailer_url_final = cls.make_video_url(trailer_url_final)
                    entity.extras.append(EntityExtra("trailer", entity.tagline or entity.ui_code, "mp4", trailer_url_final))

        if entity.originaltitle:
            try:
                entity = cls.shiroutoname_info(entity)
            except Exception as e_shirouto:
                logger.exception(f"JavDB Info: Shiroutoname error: {e_shirouto}")

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

        logger.info(f"JavDB: __info finished for {code}. UI Code: {entity.ui_code}")
        return entity


    @classmethod
    def __img_urls(cls, tree):
        ret = {'ps': None, 'pl': None, 'arts': [], 'specific_poster_candidates': []}
        try:
            pl_nodes = tree.xpath('//div[@class="column column-video-cover"]//img[@class="video-cover"]/@src')
            if pl_nodes:
                pl_url = pl_nodes[0].strip()
                ret['pl'] = "https:" + pl_url if pl_url.startswith("//") else pl_url

            arts_nodes = tree.xpath('//div[contains(@class, "preview-images")]/a[@class="tile-item"]/@href')
            arts_urls = ["https:" + href if href.startswith("//") else href for href in arts_nodes]
            ret['arts'] = list(dict.fromkeys(arts_urls))

            if ret['arts']:
                ret['specific_poster_candidates'].append(ret['arts'][0])
        except Exception as e:
            logger.error(f"JavDB __img_urls Error: {e}")

        return ret


    # endregion INFO
    ################################################

    ################################################
    # region SiteAvBase 메서드 오버라이드

    @classmethod
    def set_config(cls, db):
        super().set_config(db)
        cls.config.update({
            "use_selenium": db.get_bool(f"jav_censored_{cls.site_name}_use_selenium"), 
            "use_flaresolverr": db.get_bool(f"jav_censored_{cls.site_name}_use_flaresolverr"),
            "crop_mode": db.get_list(f"jav_censored_{cls.site_name}_crop_mode", ","),
            "priority_labels": db.get_list(f"jav_censored_{cls.site_name}_priority_search_labels", ","),
        })
        cls.config['priority_labels_set'] = {lbl.strip().upper() for lbl in cls.config.get('priority_labels', []) if lbl.strip()}


    # endregion SiteAvBase 메서드 오버라이드
    ################################################
