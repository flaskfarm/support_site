import re
import os
import sqlite3
from urllib.parse import urljoin, urlencode, quote
from lxml import html

from ..setup import P, logger, path_data
from .site_av_base import SiteAvBase

SITE_BASE_URL = "https://www.avdbs.com"

class SiteAvdbs(SiteAvBase):
    site_char = "A"
    site_name = "avdbs"
    default_headers = SiteAvBase.base_default_headers.copy()

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
            # actor_idx는 save_actor_image 등에서 사용하기 위해 저장
            if final_info.get("actor_idx"):
                # EntityActor 클래스 구조에 따라 저장 방식이 다를 수 있음 (속성 추가)
                try: entity_actor.actor_idx = final_info.get("actor_idx")
                except: entity_actor["actor_idx"] = final_info.get("actor_idx")
            return True
        return False


    @classmethod
    def _search_from_local_db(cls, name_variations_to_search):
        if not (cls.config['local_db_path'] and os.path.exists(cls.config['local_db_path'])):
            return None

        db_path = os.path.abspath(cls.config['local_db_path'])

        try:
            with sqlite3.connect(db_path, timeout=10) as conn:
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
                        
                        # actor_idx 추출 (A11340 -> 11340)
                        actor_idx = ""
                        if row["actor_id"]:
                            match = re.search(r'(\d+)', row["actor_id"])
                            if match: actor_idx = match.group(1)

                        if korean_name and thumb_url:
                            logger.debug(f"AVDBS DB: Match found for '{current_search_name}': {korean_name} ({name2_field})")
                            final_info = {
                                "name": korean_name, 
                                "name2": name2_field, 
                                "thumb": thumb_url, 
                                "actor_idx": actor_idx,
                                "site": f"{cls.site_name}_db"}
                            return final_info

        except sqlite3.Error as e: 
            logger.error(f"DB 조회 중 오류: {e}")
        
        return None


    @classmethod
    def _search_from_web(cls, originalname) -> dict:
        # logger.debug(f"AVDBS WEB: Avdbs.com 에서 '{originalname}' 정보 직접 검색 시작.")
        
        try:
            from curl_cffi import requests as cffi_requests
            # [중요] 세션을 하나 생성하여 API 호출과 검색 페이지 접속을 연속으로 수행 (쿠키 유지)
            session = cffi_requests.Session(impersonate="chrome110")
        except ImportError:
            logger.error("curl_cffi not installed.")
            return None

        try:
            headers = cls.default_headers.copy()
            headers['Referer'] = SITE_BASE_URL + "/"
            
            # --- 1. 메타/API 호출하여 seq 및 쿠키 획득 ---
            api_path = f"/w2017/api/iux_kwd_srch_log2.php?op=srch&kwd={quote(originalname)}"
            api_url = f"{SITE_BASE_URL}{api_path}"
            
            # 메인 접속 (기본 쿠키 획득)
            session.get(SITE_BASE_URL, headers=headers)
            
            # API 접속
            res = session.get(api_url, headers=headers)
            
            # WAF(자바스크립트 챌린지) 우회
            if res and "<script>" in res.text and "localStorage" in res.text:
                match = re.search(r'location\.href\s*=\s*["\']([^"\']+)["\']', res.text)
                if match:
                    bypass_url = urljoin(SITE_BASE_URL, match.group(1))
                    # 리디렉션 따라가며 쿠키 갱신
                    res = session.get(bypass_url, headers=headers, allow_redirects=True)
            
            seq = None
            if res and res.status_code == 200:
                try:
                    data = res.json()
                    seq = data.get('seq')
                except: pass
            
            if not seq:
                logger.warning("AVDBS WEB: Failed to obtain seq.")
                return None

            # logger.debug(f"AVDBS WEB: Got seq: {seq}")

            # --- 2. 검색 페이지 접속 (쿠키 유지된 세션 사용) ---
            search_url = f"{SITE_BASE_URL}/w2017/page/search/search_actor.php"
            params = {'kwd': originalname, 'seq': seq, 'tab': '1'}
            
            res_search = session.get(search_url, params=params, headers=headers)
            if res_search.status_code != 200:
                logger.warning(f"AVDBS WEB: Search failed. Status: {res_search.status_code}")
                return None

            tree = html.fromstring(res_search.text)
            if tree is None: return None

            # 검색 결과 파싱 (XPath 보강)
            actor_items = tree.xpath('//ul[contains(@class, "lst")]/li')
            if not actor_items:
                # Fallback XPath
                actor_items = tree.xpath('//div[contains(@class, "srch")]/following-sibling::ul/li')

            if not actor_items:
                # logger.debug("AVDBS WEB: No actor items found in HTML.")
                return None

            names_to_check = cls._parse_name_variations(originalname)
            
            for idx, item_li in enumerate(actor_items):
                try:
                    # actor_idx 추출
                    actor_idx = item_li.get('data-idx')
                    
                    # 이름 파싱 (k_name, e_name)
                    k_name_node = item_li.xpath('.//span[contains(@class, "k_name")]') or item_li.xpath('.//p[contains(@class, "k_name")]')
                    if not k_name_node: continue
                    name_ko_raw = k_name_node[0].text_content().strip()

                    e_name_node = item_li.xpath('.//span[contains(@class, "e_name")]') or item_li.xpath('.//p[contains(@class, "e_name")]')
                    if not e_name_node: continue
                    tmp = e_name_node[0].text_content().strip()
                    
                    match = re.match(r'(?P<en>.*?)\((?P<jp>.*?)\)', tmp)
                    if match:
                        name_en_raw = match.group('en').strip()
                        name_ja_raw = match.group('jp').strip()
                    else:
                        name_en_raw = tmp.strip()
                        name_ja_raw = ""

                    # 매칭 확인
                    if (name_ja_raw and name_ja_raw in names_to_check) or \
                       (name_en_raw and name_en_raw in names_to_check) or \
                       (name_ko_raw == originalname):
                        
                        logger.debug(f"AVDBS WEB: Match found for '{originalname}': {name_ko_raw} ({name_en_raw})")

                        # 이미지 URL 추출
                        img_tag = item_li.xpath('.//div[@class="photo"]//img/@src')
                        if not img_tag: continue
                        img_url_raw = img_tag[0].strip()
                        
                        if not img_url_raw.startswith('http'):
                            img_url_raw = urljoin(SITE_BASE_URL, img_url_raw)
                        
                        # 고화질 변환
                        if img_url_raw.endswith('_ns.jpg'):
                            img_url_raw = img_url_raw.replace('_ns.jpg', '_n.jpg')
                        
                        processed_thumb = cls.make_image_url(img_url_raw)
                        
                        return {
                            "name": name_ko_raw, 
                            "name2": name_en_raw,
                            "actor_idx": actor_idx,
                            "site": "avdbs_web", 
                            "thumb": processed_thumb 
                        }
                except Exception as e_item: 
                    logger.exception(f"AVDBS WEB: Error processing item at index {idx}: {e_item}")

            logger.debug("AVDBS WEB: No matching actor found in search results.")
            return None

        except Exception as e:
            logger.error(f"AVDBS WEB: Exception: {e}")
            logger.error(traceback.format_exc())
        finally:
            session.close()
        
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
