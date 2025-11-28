import re, time
import traceback
from lxml import html
import os 
import urllib.parse as py_urllib_parse
from PIL import Image
import socket
from urllib.parse import urlparse
import base64
import zipfile
from io import BytesIO
import requests

# Selenium imports
try:
    from selenium import webdriver
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.common.exceptions import TimeoutException, WebDriverException
    is_selenium_available = True
except ImportError:
    is_selenium_available = False

# selenium-stealth import
try:
    from selenium_stealth import stealth
    is_stealth_available = True
except ImportError:
    is_stealth_available = False

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

    _cf_cookies = {} # { 'cookie_name': 'value', ... }
    _cf_cookie_timestamp = 0
    CF_COOKIE_EXPIRY = 3600 # 1시간

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

        tree = None
        
        # 1순위: FlareSolverr 사용
        if cls.config.get('use_flaresolverr') and cls.config.get('flaresolverr_url'):
            tree, _ = cls._get_page_content_flaresolverr(search_url)
            if tree is None:
                logger.warning("JavDB Search: FlareSolverr failed. Falling back if possible.")

        # 2순위: Selenium 사용 (FlareSolverr 실패 시 또는 미설정 시)
        if tree is None and cls.config.get('use_selenium', False) and is_selenium_available:
            driver = None
            try:
                driver = cls._get_selenium_driver()
                wait_locator = (By.XPATH, '//div[(contains(@class, "item-list") or contains(@class, "movie-list"))]')
                tree, _ = cls._get_page_content_selenium(driver, search_url, wait_for_locator=wait_locator)
            except Exception as e:
                logger.error(f"JavDB Search (Selenium): Error: {e}")
            finally:
                cls._quit_selenium_driver(driver)
        
        # 3순위: 일반 Requests (FlareSolverr/Selenium 모두 없을 때)
        if tree is None:
            custom_cookies_for_search = {'over18': '1'}
            res_for_search = cls.get_response_cs(search_url, cookies=custom_cookies_for_search)

            if res_for_search:
                html_content_text = res_for_search.text
                if res_for_search.status_code != 200:
                    logger.warning(f"JavDB Search: Status code {res_for_search.status_code} for URL: {res_for_search.url}")
                    if "cf-error-details" in html_content_text or "Cloudflare to restrict access" in html_content_text:
                        logger.error(f"JavDB Search: Cloudflare restriction page detected.")
                
                try:
                    tree = html.fromstring(html_content_text)
                except Exception as e_parse:
                    logger.error(f"JavDB Search: Failed to parse HTML: {e_parse}")
            else:
                logger.error(f"JavDB Search: Failed to get response for keyword '{kw_ui_code}'.")

        if tree is None:
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
                    # FlareSolverr를 쓸 때는 make_image_url(프록시)을 쓰지 않고 원본 URL 사용
                    # (FlareSolverr가 이미지를 직접 다운로드해주진 않으므로)
                    if cls.config.get('use_proxy') and not cls.config.get('flaresolverr_url'):
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
        custom_cookies = { 'over18': '1', 'locale': 'en' }
        custom_cookies['cf_clearance'] = ''

        original_code_for_url = code[len(cls.module_char) + len(cls.site_char):]
        detail_url = f"{SITE_BASE_URL}/v/{original_code_for_url}"
        
        original_keyword = None
        if keyword:
            original_keyword = keyword
            logger.debug(f"JavDB Info: Using provided keyword '{original_keyword}' for {code}.")
        else:
            try:
                keyword_cache = F.get_cache('jav_censored_keyword_cache')
                if keyword_cache:
                    original_keyword = keyword_cache.get(code)
                    if original_keyword:
                        logger.debug(f"JavDB Info: Found keyword '{original_keyword}' in cache for {code}.")
            except Exception as e_cache:
                logger.warning(f"JavDB Info: Failed to get keyword from cache for {code}: {e_cache}")

        tree = None
        
        # 1순위: FlareSolverr 사용
        if cls.config.get('use_flaresolverr') and cls.config.get('flaresolverr_url'):
            tree, _ = cls._get_page_content_flaresolverr(detail_url)
            if tree is None:
                logger.warning("JavDB Info: FlareSolverr failed.")

        # 2순위: Selenium 사용
        if tree is None and cls.config.get('use_selenium', False) and is_selenium_available:
            driver = None
            try:
                driver = cls._get_selenium_driver()
                wait_locator = (By.XPATH, '//h2[@class="title is-4"]')
                tree, _ = cls._get_page_content_selenium(driver, detail_url, wait_for_locator=wait_locator)
            except Exception as e:
                logger.error(f"JavDB Info (Selenium): Error: {e}")
            finally:
                cls._quit_selenium_driver(driver)

        # 3순위: Requests
        if tree is None:
            try:
                logger.debug(f"JavDB Info: Accessing URL: {detail_url}")
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
            except Exception as e:
                logger.error(f"JavDB Info: Error getting page: {e}")
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
    def _get_page_content_flaresolverr(cls, url):
        flaresolverr_url = cls.config.get('flaresolverr_url', '').rstrip('/')
        if not flaresolverr_url: return None, None
        
        api_url = f"{flaresolverr_url}/v1"
        payload = {
            "cmd": "request.get",
            "url": url,
            "maxTimeout": 60000,
        }
        
        # 프록시 설정
        if cls.config.get('use_proxy') and cls.config.get('proxy_url'):
            payload["proxy"] = {"url": cls.config['proxy_url']}

        # 쿠키 재사용 로직
        if cls._cf_cookies and (time.time() - cls._cf_cookie_timestamp < cls.CF_COOKIE_EXPIRY):
            cookies_payload = []
            for k, v in cls._cf_cookies.items():
                cookie_dict = {
                    "name": k, 
                    "value": v,
                    "domain": urlparse(url).hostname, # 도메인 필수
                    "path": "/"                       # 경로 필수
                }
                cookies_payload.append(cookie_dict)
            
            payload["cookies"] = cookies_payload

        try:
            logger.debug(f"JavDB: Requesting FlareSolverr: {url}")
            res = requests.post(api_url, json=payload, headers={'Content-Type': 'application/json'}, timeout=65)
            if res.status_code == 200:
                data = res.json()
                if data.get('status') == 'ok':
                    html_source = data['solution']['response']
                    
                    if 'cookies' in data['solution']:
                        new_cookies = {}
                        for c in data['solution']['cookies']:
                            new_cookies[c['name']] = c['value']
                        
                        cls._cf_cookies.update(new_cookies)
                        cls._cf_cookie_timestamp = time.time()

                    return html.fromstring(html_source), html_source
                else:
                    logger.warning(f"JavDB: FlareSolverr returned error status: {data}")
            else:
                logger.warning(f"JavDB: FlareSolverr HTTP Error: {res.status_code}")
        except Exception as e:
            logger.error(f"JavDB: FlareSolverr Connection Error: {e}")
        
        return None, None


    # --- Selenium 메서드 ---
    @classmethod
    def _get_page_content_selenium(cls, driver, url, wait_for_locator):
        driver.get(url)
        time.sleep(5)
        
        try:
            enter_btns = driver.find_elements(By.XPATH, '//a[contains(text(), "I am over 18")] | //button[contains(text(), "I am over 18")]')
            if enter_btns:
                enter_btns[0].click()
                time.sleep(2)
        except: pass

        if "Just a moment" in driver.title or "Cloudflare" in driver.title:
            logger.debug(f"[{cls.site_name}] Cloudflare detected. Attempting bypass...")
            try:
                driver.execute_script("""
                    setInterval(() => {
                        function findAndClick(root) {
                            const checkbox = root.querySelector('input[type="checkbox"]');
                            if (checkbox && !checkbox.checked) {
                                checkbox.click();
                                return true;
                            }
                            const all = root.querySelectorAll('*');
                            for (let el of all) {
                                if (el.shadowRoot) findAndClick(el.shadowRoot);
                            }
                        }
                        findAndClick(document);
                    }, 1000);
                """)
                time.sleep(10)
            except Exception as e:
                logger.debug(f"[{cls.site_name}] Bypass script error: {e}")

        timeout = cls.config.get('selenium_timeout', 20)
        try:
            WebDriverWait(driver, timeout).until(EC.presence_of_element_located(wait_for_locator))
        except TimeoutException:
            try:
                import os
                tmp_dir = '/data/tmp'
                if not os.path.exists(tmp_dir): os.makedirs(tmp_dir, exist_ok=True)
                driver.save_screenshot(os.path.join(tmp_dir, f"javdb_fail_{int(time.time())}.png"))
                logger.error(f"[{cls.site_name}] Timeout. Screenshot saved.")
            except: pass
            
            return None, driver.page_source

        return html.fromstring(driver.page_source), driver.page_source


    @classmethod
    def _get_selenium_driver(cls):
        if not is_selenium_available:
            raise ImportError("Selenium 라이브러리가 설치되어 있지 않습니다.")
        selenium_url = cls.config.get('selenium_url')
        if not selenium_url: raise Exception("Selenium 서버 URL이 설정되지 않았습니다.")
        
        driver_type = cls.config.get('selenium_driver_type', 'chrome')
        logger.debug(f"[{cls.site_name}] Preparing Selenium driver. Type: {driver_type}")

        if driver_type == 'firefox':
            options = webdriver.FirefoxOptions()
            options.add_argument('--headless')
        else:
            options = webdriver.ChromeOptions()
            options.add_argument("--no-sandbox")
            options.add_argument("--disable-dev-shm-usage")
            options.add_argument("--disable-blink-features=AutomationControlled")
            options.add_experimental_option("excludeSwitches", ["enable-automation"])
            options.add_experimental_option('useAutomationExtension', False)
            options.add_argument("--disable-infobars")
            options.add_argument("--window-size=1920,1080")
            options.add_argument('user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')

        if cls.config.get('use_proxy') and cls.config.get('proxy_url'):
            proxy_url = cls.config["proxy_url"]
            if driver_type == 'firefox':
                if '@' in proxy_url:
                    parsed_proxy = urlparse(proxy_url)
                    proxy_url = f"{parsed_proxy.scheme}://{parsed_proxy.hostname}:{parsed_proxy.port}"
                parsed_proxy = urlparse(proxy_url)
                options.set_preference("network.proxy.type", 1)
                options.set_preference("network.proxy.http", parsed_proxy.hostname)
                options.set_preference("network.proxy.http_port", parsed_proxy.port)
                options.set_preference("network.proxy.ssl", parsed_proxy.hostname)
                options.set_preference("network.proxy.ssl_port", parsed_proxy.port)
            else:
                options.add_argument(f'--proxy-server={proxy_url}')

        original_timeout = socket.getdefaulttimeout()
        try:
            socket.setdefaulttimeout(20)
            driver = webdriver.Remote(command_executor=selenium_url, options=options)
            
            if driver_type == 'chrome' and is_stealth_available:
                try:
                    stealth(driver,
                        languages=["en-US", "en"],
                        vendor="Google Inc.",
                        platform="Win32",
                        webgl_vendor="Intel Inc.",
                        renderer="Intel Iris OpenGL Engine",
                        fix_hairline=True,
                    )
                    logger.debug(f"[{cls.site_name}] selenium-stealth applied.")
                except ValueError as e:
                    logger.warning(f"[{cls.site_name}] selenium-stealth failed (Remote Driver issue): {e}")
                    logger.debug(f"[{cls.site_name}] Applying manual CDP stealth script instead.")
                    driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
                        "source": """
                            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
                            window.navigator.chrome = { runtime: {} };
                            Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
                            Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });
                            const originalQuery = window.navigator.permissions.query;
                            window.navigator.permissions.query = (parameters) => (
                                parameters.name === 'notifications' ?
                                Promise.resolve({ state: Notification.permission }) :
                                originalQuery(parameters)
                            );
                        """
                    })
            elif driver_type == 'chrome':
                driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
                    "source": """
                        Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
                        window.navigator.chrome = { runtime: {} };
                        Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
                        Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });
                    """
                })
                logger.debug(f"[{cls.site_name}] Manual CDP stealth script applied.")

            return driver
        finally:
            socket.setdefaulttimeout(original_timeout)


    @classmethod
    def _quit_selenium_driver(cls, driver):
        if driver:
            try: driver.quit()
            except: pass


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
            "use_selenium": db.get_bool(f"jav_censored_{cls.site_name}_use_selenium"),
            "use_flaresolverr": db.get_bool(f"jav_censored_{cls.site_name}_use_flaresolverr"),
            "crop_mode": db.get_list(f"jav_censored_{cls.site_name}_crop_mode", ","),
            "priority_labels": db.get_list(f"jav_censored_{cls.site_name}_priority_search_labels", ","),
        })
        cls.config['priority_labels_set'] = {lbl.strip().upper() for lbl in cls.config.get('priority_labels', []) if lbl.strip()}



    # endregion SiteAvBase 메서드 오버라이드
    ################################################
