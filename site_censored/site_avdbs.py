import requests
from lxml import html
import os
import sqlite3
import re
from urllib.parse import urljoin

from ..setup import P, logger
from ..site_util_av import SiteUtilAv as SiteUtil
try:
    from ..tool_discord import DiscordUtil
    DISCORD_UTIL_AVAILABLE = True
except ImportError:
    P.logger.error("DiscordUtil을 임포트할 수 없습니다. Discord URL 갱신 기능 비활성화.")
    DISCORD_UTIL_AVAILABLE = False
    class DiscordUtil:
        @staticmethod
        def isurlattachment(url): return False
        @staticmethod
        def isurlexpired(url): return False
        @staticmethod
        def renew_urls(data): return data
        @staticmethod
        def proxy_image_url(urls, **kwargs): return {}

class SiteAvdbs:
    site_char = "A"
    site_name = "avdbs"
    base_url = "https://www.avdbs.com"

    @staticmethod
    def __get_actor_info_from_web(originalname, **kwargs) -> dict:
        """Avdbs.com 웹사이트에서 배우 정보를 가져오는 내부 메소드 (Fallback용)"""
        # logger.debug(f"WEB Fallback: Avdbs.com 에서 '{originalname}' 정보 직접 검색 시작.")
        proxy_url = kwargs.get('proxy_url')
        image_mode = kwargs.get('image_mode', '0')

        with requests.Session() as s:
            enhanced_headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
                "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
                "Referer": SiteAvdbs.base_url + "/",
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
            s.headers.update(enhanced_headers)
            if proxy_url: s.proxies.update({"http": proxy_url, "https": proxy_url})

            search_url = f"{SiteAvdbs.base_url}/w2017/page/search/search_actor.php"
            search_params = {'kwd': originalname}
            search_headers = enhanced_headers.copy()
            tree = None
            try:
                # logger.debug(f"WEB: Requesting search page: {search_url} with params: {search_params}")
                search_url

                response_search_page = s.get(search_url, params=search_params, headers=search_headers, timeout=20)
                response_search_page.raise_for_status()
                tree = html.fromstring(response_search_page.text)
                if tree is None: return None
            except requests.exceptions.RequestException as e_req: logger.error(f"WEB: Request failed for search page: {e_req}"); return None
            except Exception as e_parse: logger.error(f"WEB: Failed to parse search page HTML: {e_parse}"); return None

            try:
                #actor_items = tree.xpath('//div[contains(@class, "search-actor-list")]/ul/li')
                actor_items = tree.xpath('//div[contains(@class, "srch")]/ul/li')
                if not actor_items:
                    # logger.debug("WEB: No actor items found.")
                    return None

                names_to_check = SiteAvdbs._parse_name_variations(originalname)

                for idx, item_li in enumerate(actor_items):
                    try:
                        name_tags = item_li.xpath('.//p[starts-with(@class, "name")]')
                        if len(name_tags) < 3: continue
                        name_ja_raw = name_tags[0].text_content().strip()
                        name_en_raw = name_tags[1].text_content().strip()
                        name_ko_raw = name_tags[2].text_content().strip()
                        name_ja_clean = name_ja_raw.split('(')[0].strip()

                        if name_ja_clean in names_to_check:
                            logger.debug(f"WEB: Match found for '{originalname}' - JA:'{name_ja_clean}'")
                            img_tag = item_li.xpath('.//img/@src')
                            if not img_tag: continue
                            img_url_raw = img_tag[0].strip()
                            if not img_url_raw.startswith('http'): img_url_raw = urljoin(SiteAvdbs.base_url, img_url_raw)

                            processed_thumb = SiteUtil.process_image_mode(image_mode, img_url_raw, proxy_url=proxy_url)

                            return {"name": name_ko_raw, "name2": name_en_raw, "site": "avdbs_web", "thumb": processed_thumb}
                    except Exception as e_item: logger.exception(f"WEB: Error processing item at index {idx}: {e_item}")

                logger.debug("WEB: No matching actor found in search results.")
                return None
            except Exception as e_parse_results: logger.exception(f"WEB: Error parsing search results: {e_parse_results}"); return None


    @staticmethod
    def _parse_and_match_other_names(other_names_str, target_jp_name):
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

    @staticmethod
    def _parse_name_variations(originalname):
        """입력된 이름에서 검색할 이름 변형 목록을 생성합니다."""
        variations = {originalname}
        match = re.match(r'^(.*?)\s*[（\(]([^）\)]+)[）\)]\s*$', originalname)
        if match:
            before_paren = match.group(1).strip(); inside_paren = match.group(2).strip()
            if before_paren: variations.add(before_paren)
            if inside_paren: variations.add(inside_paren)
        # logger.debug(f"원본 이름 '{originalname}'에 대한 검색 변형 생성: {list(variations)}")
        return list(variations)

    @staticmethod
    def get_actor_info(entity_actor, **kwargs) -> bool:
        """
        로컬 DB(다단계 이름 검색) 조회 후 웹 스크래핑 fallback.
        이미지 URL 변환 기능 적용. 유니코드 URL 유지.
        Discord URL 갱신 포함 (가능 시).
        """
        original_input_name = entity_actor.get("originalname")
        if not original_input_name:
            logger.warning("배우 정보 조회 불가: originalname이 없습니다.")
            return False

        use_local_db = kwargs.get('use_local_db', False)
        local_db_path = kwargs.get('local_db_path') if use_local_db else None
        proxy_url = kwargs.get('proxy_url')
        image_mode = kwargs.get('image_mode', '0')
        db_image_base_url = kwargs.get('db_image_base_url', '')
        site_name_for_db = kwargs.get('site_name_for_db_query', SiteAvdbs.site_name)

        logger.debug(f"배우 정보 검색 시작: '{original_input_name}' (DB:{use_local_db}, SiteForDB:{site_name_for_db}, Prefix:'{db_image_base_url}')")

        name_variations_to_search = SiteAvdbs._parse_name_variations(original_input_name)
        final_info = None
        db_found_valid = False

        if use_local_db and local_db_path and os.path.exists(local_db_path):
            conn = None
            try:
                db_uri = f"file:{os.path.abspath(local_db_path)}?mode=ro"
                conn = sqlite3.connect(db_uri, uri=True, timeout=10)
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                # logger.debug(f"로컬 배우DB 연결 성공: {local_db_path}")

                for current_search_name in name_variations_to_search:
                    # logger.debug(f"DB 검색 시도: '{current_search_name}' (Site: {site_name_for_db})")
                    row = None
                    query1 = "SELECT inner_name_kr, inner_name_en, profile_img_path FROM actors WHERE site = ? AND inner_name_cn = ? LIMIT 1"
                    cursor.execute(query1, (site_name_for_db, current_search_name))
                    row = cursor.fetchone()
                    if not row:
                        query2 = """
                            SELECT inner_name_kr, inner_name_en, profile_img_path, actor_onm, inner_name_cn 
                            FROM actors 
                            WHERE site = ? AND (actor_onm LIKE ? OR inner_name_cn LIKE ?)
                        """
                        like_search_term = f"%{current_search_name}%"
                        cursor.execute(query2, (site_name_for_db, like_search_term, like_search_term))
                        potential_rows = cursor.fetchall()
                        if potential_rows:
                            for potential_row in potential_rows:
                                matched_by_onm = False
                                if potential_row["actor_onm"]:
                                    matched_by_onm = SiteAvdbs._parse_and_match_other_names(potential_row["actor_onm"], current_search_name)
                                
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
                        query3 = "SELECT inner_name_kr, inner_name_en, profile_img_path FROM actors WHERE site = ? AND (inner_name_kr = ? OR inner_name_en = ? OR inner_name_en LIKE ?) LIMIT 1"
                        cursor.execute(query3, (site_name_for_db, current_search_name, current_search_name, f"%({current_search_name})%"))
                        row = cursor.fetchone()

                    if row:
                        korean_name = row["inner_name_kr"]
                        name2_field = row["inner_name_en"] if row["inner_name_en"] else ""
                        db_relative_path = row["profile_img_path"]
                        thumb_url = ""

                        if db_relative_path:
                            if db_image_base_url:
                                thumb_url = db_image_base_url.rstrip('/') + '/' + db_relative_path.lstrip('/')
                                # logger.debug(f"DB: 이미지 URL 생성 (Prefix 사용): {thumb_url}")
                            else:
                                thumb_url = db_relative_path
                                logger.warning(f"DB: db_image_base_url (jav_actor_img_url_prefix) 설정 없음. 상대 경로 사용: {thumb_url}")
                            
                            # Discord URL 갱신
                            if DISCORD_UTIL_AVAILABLE and thumb_url and DiscordUtil.isurlattachment(thumb_url) and DiscordUtil.isurlexpired(thumb_url):
                                logger.warning(f"DB: 만료된 Discord URL 발견, 갱신 시도: {thumb_url}")
                                try:
                                    renewed_data = DiscordUtil.renew_urls({"thumb": thumb_url})
                                    if renewed_data and renewed_data.get("thumb") and renewed_data.get("thumb") != thumb_url:
                                        thumb_url = renewed_data.get("thumb"); # logger.debug(f"DB: Discord URL 갱신 성공 -> {thumb_url}")
                                except Exception as e_renew: logger.error(f"DB: Discord URL 갱신 중 예외: {e_renew}")
                        
                        if name2_field:
                            match_name2 = re.match(r"^(.*?)\s*\(.*\)$", name2_field)
                            if match_name2: name2_field = match_name2.group(1).strip()

                        if korean_name and thumb_url:
                            # logger.debug(f"DB에서 '{current_search_name}' 유효 정보 찾음 ({korean_name}).")
                            final_info = {"name": korean_name, "name2": name2_field, "thumb": thumb_url, "site": f"{site_name_for_db}_db"}
                            db_found_valid = True
                            break
            except sqlite3.Error as e: logger.error(f"DB 조회 중 오류: {e}")
            except Exception as e_db: logger.exception(f"DB 처리 중 예상치 못한 오류: {e_db}")
            finally:
                if conn: conn.close()
        elif use_local_db: 
            logger.warning(f"로컬 배우DB 사용 설정되었으나 경로 문제: {local_db_path}")
        # else:
        #    logger.debug("로컬 배우DB 사용 안 함.")

        if not db_found_valid and final_info is None:
            # logger.debug(f"DB에서 '{original_input_name}' 정보를 찾지 못했거나 유효하지 않아 웹 검색 시도.")
            web_info = SiteAvdbs.__get_actor_info_from_web(original_input_name, image_mode=image_mode, proxy_url=proxy_url)
            if web_info:
                # logger.debug(f"웹에서 '{original_input_name}' 정보 찾음 (출처: {web_info.get('site')}).")
                final_info = web_info
            # else:
            #    logger.debug(f"웹에서도 '{original_input_name}' 정보를 찾지 못함.")

        # 최종 결과 처리
        if final_info is not None:
            update_count = 0
            if final_info.get("name"): entity_actor["name"] = final_info["name"]; update_count += 1
            if final_info.get("name2"): entity_actor["name2"] = final_info["name2"]; update_count += 1
            if final_info.get("thumb"): entity_actor["thumb"] = final_info["thumb"]; update_count += 1
            entity_actor["site"] = final_info.get("site", "unknown_source")

            if update_count > 0: 
                logger.info(f"'{original_input_name}' 최종 정보 업데이트 완료 (출처: {entity_actor['site']}).")
                return True
            else: 
                logger.warning(f"'{original_input_name}' 정보는 찾았으나 (출처: {entity_actor['site']}), 업데이트할 유효 필드(name, name2, thumb) 부족.")
                return False
        else:
            logger.debug(f"'{original_input_name}'에 대한 정보를 DB와 웹 모두에서 찾지 못함.")

            if not entity_actor.get('name') and entity_actor.get('originalname'):
                entity_actor['name'] = entity_actor.get('originalname')
                # logger.debug("DB/웹 검색 실패 후 이름 필드를 originalname으로 설정.")
            return False
