import requests
from lxml import html
import os
import sqlite3
import re
from urllib.parse import urljoin, urlencode
import time

from ..setup import P, logger
from .site_av_base import SiteAvBase

# DiscordUtil 제거

SITE_BASE_URL = "https://www.avdbs.com"

class SiteAvdbs(SiteAvBase):
    site_char = "A"
    site_name = "avdbs"
    default_headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
        "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
        "Referer": SITE_BASE_URL + "/",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "same-origin",
        "Sec-Fetch-User": "?1",
        "Sec-CH-UA": '"Not_A Brand";v="8", "Chromium";v="120", "Google Chrome";v="120"',
        "Sec-CH-UA-Mobile": "?0",
        "Sec-CH-UA-Platform": '"Windows"',
        "DNT": "1",
        "Cache-Control": "max-age=0",
    }


    @classmethod
    def get_actor_info(cls, entity_actor) -> bool:
        original_input_name = entity_actor.get("originalname")
        if not original_input_name:
            logger.warning("배우 정보 조회 불가: originalname이 없습니다.")
            return False

        name_variations_to_search = cls._parse_name_variations(original_input_name)
        final_info = None
        if cls.config['use_local_db']:
            final_info = cls._search_from_local_db(name_variations_to_search)
        if final_info is None and cls.config['use_web_search']:
            final_info = cls._search_from_web(original_input_name)
        if final_info is not None:
            entity_actor["name"] = final_info["name"]
            entity_actor["name2"] = final_info["name2"]
            entity_actor["thumb"] = final_info["thumb"]
            entity_actor["site"] = final_info.get("site", "unknown_source")
            return True
        return False


    @classmethod
    def _search_from_local_db(cls, name_variations_to_search):

        if (cls.config['local_db_path'] and os.path.exists(cls.config['local_db_path'])) == False:
            return None

        db_uri = f"file:{os.path.abspath(cls.config['local_db_path'])}?mode=ro"
        conn = None

        try:
            conn = sqlite3.connect(db_uri, uri=True, timeout=10)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            for current_search_name in name_variations_to_search:
                row = None
                query1 = "SELECT * FROM actors WHERE site = ? AND inner_name_cn = ? LIMIT 1"
                cursor.execute(query1, (cls.site_name, current_search_name))
                row = cursor.fetchone()
                if not row:
                    query2 = """
                        SELECT *
                        FROM actors 
                        WHERE site = ? AND (actor_onm LIKE ? OR inner_name_cn LIKE ?)
                    """
                    like_search_term = f"%{current_search_name}%"
                    cursor.execute(query2, (cls.site_name, like_search_term, like_search_term))
                    potential_rows = cursor.fetchall()
                    if potential_rows:
                        for potential_row in potential_rows:
                            matched_by_onm = False
                            if potential_row["actor_onm"]:
                                matched_by_onm = cls._parse_and_match_other_names(potential_row["actor_onm"], current_search_name)
                            
                            matched_by_cn = False
                            if potential_row["inner_name_cn"]:
                                cn_parts = set()
                                cn_text = potential_row["inner_name_cn"]
                                for part in re.split(r'[（）()/]', cn_text):
                                    cleaned_part = part.strip()
                                    if cleaned_part:
                                        cn_parts.add(cleaned_part)
                                if current_search_name in cn_parts:
                                    matched_by_cn = True

                            if matched_by_onm or matched_by_cn:
                                row = potential_row
                                logger.debug(f"DB 검색 2단계: '{current_search_name}' 매칭 성공 (ONM: {matched_by_onm}, CN: {matched_by_cn})")
                                break
                if not row:
                    query3 = "SELECT * FROM actors WHERE site = ? AND (inner_name_kr = ? OR inner_name_en = ? OR inner_name_en LIKE ?) LIMIT 1"
                    cursor.execute(query3, (cls.site_name, current_search_name, current_search_name, f"%({current_search_name})%"))
                    row = cursor.fetchone()
                
                if row:
                    korean_name = row["inner_name_kr"]
                    name2_field = row["inner_name_en"] if row["inner_name_en"] else ""
                    db_relative_path = row["profile_img_path"]
                    thumb_url = ""

                    # 2025.07.14 by soju
                    # 구글 cdn
                    if 'google_fileid' in row.keys() and row['google_fileid']:
                        thumb_url = f"https://drive.google.com/thumbnail?id={row['google_fileid']}"
                    else:
                        if cls.config['image_url_prefix']:
                            thumb_url = cls.config['image_url_prefix'] + '/' + db_relative_path.lstrip('/')
                            # logger.debug(f"DB: 이미지 URL 생성 (Prefix 사용): {thumb_url}")
                        else:
                            thumb_url = db_relative_path
                            logger.warning(f"DB: db_image_base_url (jav_actor_img_url_prefix) 설정 없음. 상대 경로 사용: {thumb_url}")
                        
                    if name2_field:
                        match_name2 = re.match(r"^(.*?)\s*\(.*\)$", name2_field)
                        if match_name2: name2_field = match_name2.group(1).strip()

                    if korean_name and thumb_url:
                        # logger.debug(f"DB에서 '{current_search_name}' 유효 정보 찾음 ({korean_name}).")
                        final_info = {
                            "name": korean_name, 
                            "name2": name2_field, 
                            "thumb": thumb_url, 
                            "site": f"{cls.site_name}_db"}
                        return final_info
        except sqlite3.Error as e: 
            logger.error(f"DB 조회 중 오류: {e}")
        finally:
            if conn: 
                conn.close()


    @classmethod
    def _search_from_web(cls, originalname) -> dict:
        """Avdbs.com 웹사이트에서 배우 정보를 가져오는 내부 메소드 (Fallback용)"""
        # logger.debug(f"WEB Fallback: Avdbs.com 에서 '{originalname}' 정보 직접 검색 시작.")
        current_timestamp = int(time.time())
        value_to_subtract = 1735310957
        seq = current_timestamp - value_to_subtract

        search_url = f"{SITE_BASE_URL}/w2017/page/search/search_actor.php"
        search_params = {'kwd': originalname,'seq': seq, 'tab':"1"}
        search_url = f"{search_url}?{urlencode(search_params)}"
        
        try:
            tree = cls.get_tree(search_url, timeout=20)
            if tree is None: 
                return None
            actor_items = tree.xpath('//div[contains(@class, "srch")]/following-sibling::ul/li')
            if not actor_items:
                return None

            names_to_check = cls._parse_name_variations(originalname)
            for idx, item_li in enumerate(actor_items):
                try:
                    name_ko_raw = item_li.xpath('.//p[@class="k_name"]//text()')[0].strip()
                    tmp = item_li.xpath('.//p[contains(@class, "e_name")]')[0].text_content().strip()
                    match = re.match(r'(?P<en>.*?)\((?P<jp>.*?)\)', tmp)
                    if match:
                        name_en_raw = match.group('en').strip()
                        name_ja_raw = match.group('jp').strip()
                    else:
                        name_en_raw = tmp.strip()
                        name_ja_raw = ""

                    if name_ja_raw in names_to_check:
                        logger.debug(f"WEB: Match found for '{originalname}' - JA:'{name_ja_raw}'")
                        img_tag = item_li.xpath('.//img/@src')
                        if not img_tag: 
                            continue
                        img_url_raw = img_tag[0].strip()
                        if not img_url_raw.startswith('http'):
                            img_url_raw = urljoin(SITE_BASE_URL, img_url_raw)
                        processed_thumb = cls.make_image_url(img_url_raw)
                        return {
                            "name": name_ko_raw, 
                            "name2": name_en_raw, 
                            "site": "avdbs_web", 
                            "thumb": processed_thumb
                        }
                except Exception as e_item: 
                    logger.exception(f"WEB: Error processing item at index {idx}: {e_item}")

            logger.debug("WEB: No matching actor found in search results.")
            return None
        except Exception as e_parse_results: 
            logger.exception(f"WEB: Error parsing search results: {e_parse_results}")
            return None


    ################################################
    # region 유틸

    @classmethod
    def _parse_and_match_other_names(cls, other_names_str, target_jp_name):
        """
        actor_onm 문자열에서 다양한 패턴의 이름을 파싱하여
        target_jp_name (검색 대상 일본어 이름)과 정확히 일치하는지 확인.
        """
        if not other_names_str or not target_jp_name:
            return False

        name_chunks = [chunk.strip() for chunk in other_names_str.split(',') if chunk.strip()]

        for chunk in name_chunks:
            match_paren = re.match(r'^(.*?)\s*[（\(]([^）\)]+)[）\)]\s*$', chunk)
            match_paren_only = re.match(r'^\s*[（\(]([^）\)]+)[）\)]\s*$', chunk)
            
            japanese_name_candidates = []

            if match_paren:
                inside_paren_content = match_paren.group(2).strip()
                japanese_name_candidates.extend(
                    [name.strip() for name in inside_paren_content.split('/') if name.strip()]
                )
            elif match_paren_only:
                inside_paren_content = match_paren_only.group(1).strip()
                japanese_name_candidates.extend(
                    [name.strip() for name in inside_paren_content.split('/') if name.strip()]
                )
            else: # 괄호 없는 경우
                japanese_name_candidates.extend(
                    [name.strip() for name in chunk.split('/') if name.strip()]
                )

            for jp_candidate in japanese_name_candidates:
                if jp_candidate == target_jp_name:
                    logger.debug(f"정확한 일본어 이름 매칭: '{target_jp_name}' 발견 in chunk '{chunk}' as '{jp_candidate}'")
                    return True
        return False


    @classmethod
    def _parse_name_variations(cls, originalname):
        """입력된 이름에서 검색할 이름 변형 목록을 생성합니다."""
        variations = {originalname}
        match = re.match(r'^(.*?)\s*[（\(]([^）\)]+)[）\)]\s*$', originalname)
        if match:
            before_paren = match.group(1).strip(); inside_paren = match.group(2).strip()
            if before_paren: variations.add(before_paren)
            if inside_paren: variations.add(inside_paren)
        # logger.debug(f"원본 이름 '{originalname}'에 대한 검색 변형 생성: {list(variations)}")
        return list(variations)

    # endregion 유틸
    ################################################

    ################################################
    # region SiteAvBase 메서드 오버라이드

    @classmethod
    def set_config(cls, db):
        super().set_config(db)
        cls.config.update({
            "use_local_db": db.get_bool("jav_censored_avdbs_use_local_db"),
            "local_db_path": db.get("jav_censored_avdbs_local_db_path"),
            "image_url_prefix": db.get("jav_actor_img_url_prefix").rstrip('/'),
            "use_web_search": db.get_bool("jav_censored_avdbs_use_web_search"),
        })

        #logger.debug(res.text)

    # endregion SiteAvBase 메서드 오버라이드
    ################################################