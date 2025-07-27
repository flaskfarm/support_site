import re
import traceback
import time
from datetime import datetime, timedelta
from lxml import html

from ..entity_av import EntityAVSearch
from ..entity_base import (EntityActor, EntityExtra, EntityMovie, EntityThumb)
from ..setup import P, logger
from .site_av_base import SiteAvBase

SITE_BASE_URL = 'https://fc2ppvdb.com'

class SiteFc2ppvdb(SiteAvBase):
    site_name = 'fc2'
    site_char = 'P'
    module_char = 'E'
    default_headers = SiteAvBase.base_default_headers.copy()
    default_headers['Referer'] = SITE_BASE_URL + "/"

    ppvdb_default_cookies = {}
    _block_release_time_fc2ppvdb = 0 # 차단 해제 시간 저장 (타임스탬프)
    _last_retry_after_value = 0 # 마지막으로 받은 Retry-After 값 (로그용)

    

    
    @classmethod
    def search(cls, keyword_num_part, do_trans=False, manual=False):
        # 요청 전 차단 상태 확인
        if cls._is_blocked():
            return {'ret': 'error_site_rate_limited', 'data': f"Site is currently rate-limited. Try again later. Retry-After was {cls._last_retry_after_value}s."}
        
        ret = {'ret': 'failed', 'data': []}
        tree = None
        response_html_text = None # HTML 저장용

        try:
            search_url = f'{SITE_BASE_URL}/articles/{keyword_num_part}/'
            tree, response_html_text = cls._get_fc2ppvdb_page_content(search_url, use_cloudscraper=True)

            if response_html_text and "Site is rate-limited" in response_html_text: # _get_fc2ppvdb_page_content에서 반환한 메시지
                logger.warning(f"[{cls.site_name} Search] Aborted due to rate-limiting for {search_url}.")
                return {'ret': 'Too Many Requests', 'data': response_html_text}


            if tree is None: # _get_fc2ppvdb_page_content에서 tree가 None이면 실패
                logger.warning(f"[{cls.site_name} Search] Failed to get valid HTML tree for URL: {search_url}.")
                ret['data'] = 'failed to get tree or redirection page'
                """
                if not_found_delay_seconds > 0 and ret['data'] != 'not found on site': # 'not found on site' 아닐때만 딜레이
                    logger.info(f"[{cls.site_name} Search] 'failed to get tree', delaying for {not_found_delay_seconds} seconds.")
                    time.sleep(not_found_delay_seconds)
                """
                return ret

            # 페이지를 찾을 수 없는 경우
            not_found_title_elements = tree.xpath('/html/head/title/text()')
            not_found_h1_elements = tree.xpath('/html/body/div/div/div/main/div/div/h1/text()')
            is_page_not_found = False
            if not_found_title_elements and 'お探しの商品が見つかりません' in not_found_title_elements[0]:
                is_page_not_found = True
            elif not_found_title_elements and 'not found' in not_found_title_elements[0].lower():
                logger.debug(f"[{cls.site_name} Search] Page Not Found {keyword_num_part} (429 Too many requests)")
                is_page_not_found = True
            elif not_found_h1_elements and "404 Not Found" in not_found_h1_elements[0]:
                is_page_not_found = True

            # 페이지 삭제
            # XPath: //div[contains(@class, 'absolute') and contains(@class, 'inset-0')]/h1[contains(text(), 'このページは削除されました')]
            # 더 간단하게: //h1[contains(text(), 'このページは削除されました')]
            deleted_page_elements = tree.xpath("//h1[contains(text(), 'このページは削除されました')]")
            if deleted_page_elements:
                logger.debug(f"[{cls.site_name} Search] Page deleted on site for keyword_num_part: {keyword_num_part} (문구: {deleted_page_elements[0].text.strip()})")
                is_page_not_found = True

            if is_page_not_found:
                logger.debug(f"[{cls.site_name} Search] Page not found or deleted on site for keyword_num_part: {keyword_num_part}")
                ret['data'] = 'not found on site'
                """
                if not_found_delay_seconds > 0:
                    logger.debug(f"[{cls.site_name} Search] 'not found on site', delaying for {not_found_delay_seconds} seconds.")
                    time.sleep(not_found_delay_seconds)
                """
                return ret

            item = EntityAVSearch(cls.site_name)
            item.code = cls.module_char + cls.site_char + keyword_num_part

            info_block_xpath_base = '/html/body/div[1]/div/div/main/div/section/div[1]/div[1]'

            # 제목 (번역 안 함)
            title_elements = tree.xpath(f'{info_block_xpath_base}/div[2]/h2/a/text()')
            if title_elements:
                item.title = title_elements[0].strip()
                # logger.debug(f"[{cls.site_name} Search] Parsed title: {item.title}")
            else:
                item.title = f"FC2-{keyword_num_part}" 
                logger.warning(f"[{cls.site_name} Search] Title not found. Using fallback: {item.title}")
            item.title_ko = item.title # title_ko에도 원본 제목 할당 (또는 None)

            # 출시년도
            year_text_elements = tree.xpath(f"{info_block_xpath_base}/div[2]/div[starts-with(normalize-space(.), '販売日：')]/span/text()")
            if year_text_elements:
                date_str = year_text_elements[0].strip()
                if re.match(r'\d{4}-\d{2}-\d{2}', date_str):
                    item.year = int(date_str.split('-')[0])
                    # logger.debug(f"[{cls.site_name} Search] Parsed year: {item.year}")
            # else: item.year = 0 # 또는 EntityAVSearch 기본값 사용

            # 이미지 URL
            original_image_url_from_site = None
            img_elements = tree.xpath(f'{info_block_xpath_base}/div[1]/a/img/@src')
            if img_elements:
                image_url_temp = img_elements[0]
                if image_url_temp.startswith('/'):
                    original_image_url_from_site = SITE_BASE_URL + image_url_temp
                else:
                    original_image_url_from_site = image_url_temp

            # === 이미지 URL 처리 ===
            # manual=True (에이전트 검색 결과)일 때만 이미지 URL을 process_image_mode로 처리
            if manual and original_image_url_from_site:
                # LogicJavFc2에서 전달받은 image_mode와 proxy_url 사용
                # current_image_mode_for_search는 kwargs에서 가져온 image_mode (jav_censored_image_mode)
                try:
                    if cls.config['use_proxy']:
                        item.image_url = cls.make_image_url(original_image_url_from_site)
                except Exception as e_img: 
                    logger.error(f"DMM Search: ImgProcErr (manual):{e_img}")

                # logger.debug(f"[{cls.site_name} Search Manual] Processed image URL: {original_image_url_from_site} -> {item.image_url} (mode: {current_image_mode_for_search})")
            elif original_image_url_from_site: # manual=False 이거나 이미지가 있을 경우 원본 URL 사용
                item.image_url = original_image_url_from_site
            else: # 이미지가 아예 없는 경우
                item.image_url = "" # 또는 None

            item.ui_code = f'FC2-{keyword_num_part}'
            item.score = 100 

            # logger.debug(f"[{cls.site_name} Search] Final item for keyword_num_part '{keyword_num_part}': score={item.score}, ui_code='{item.ui_code}', title='{item.title}', year={item.year if hasattr(item, 'year') else 'N/A'}, image_url='{item.image_url}'")

            ret['data'].append(item.as_dict())
            ret['ret'] = 'success'

        except Exception as exception: 
            logger.error(f'[{cls.site_name} Search] Exception for keyword_num_part {keyword_num_part}: {exception}')
            logger.error(traceback.format_exc())
            ret['ret'] = 'exception'
            ret['data'] = str(exception)

        return ret


    @classmethod
    def info(cls, code_module_site_id):

        # 요청 전 차단 상태 확인
        if cls._is_blocked():
            return {'ret': 'error_site_rate_limited', 'data': f"Site is currently rate-limited. Try again later. Retry-After was {cls._last_retry_after_value}s."}

        keyword_num_part = code_module_site_id[len(cls.module_char) + len(cls.site_char):]
        ui_code_for_images = f'FC2-{keyword_num_part}'

        ret = {'ret': 'failed', 'data': None}
        tree = None
        response_html_text = None

        try:
            info_url = f'{SITE_BASE_URL}/articles/{keyword_num_part}/'
            # logger.debug(f"[{cls.site_name} Info] Requesting URL: {info_url}")

            tree, response_html_text = cls._get_fc2ppvdb_page_content(info_url,  use_cloudscraper=True)

            if tree is None: # _get_fc2ppvdb_page_content에서 tree가 None이면 실패
                logger.warning(f"[{cls.site_name} Info] Failed to get valid HTML tree for URL: {info_url}")
                ret['data'] = 'failed to get tree or redirection page'
                return ret

            not_found_title_elements = tree.xpath('/html/head/title/text()')
            not_found_h1_elements = tree.xpath('/html/body/div/div/div/main/div/div/h1/text()')
            is_page_not_found = False
            if not_found_title_elements and ('お探しの商品が見つかりません' in not_found_title_elements[0] or 'not found' in not_found_title_elements[0].lower()):
                is_page_not_found = True
            elif not_found_h1_elements and "404 Not Found" in not_found_h1_elements[0]:
                is_page_not_found = True

            deleted_page_elements = tree.xpath("//h1[contains(text(), 'このページは削除されました')]")
            if deleted_page_elements:
                logger.debug(f"[{cls.site_name} Info] Page deleted on site for code: {code_module_site_id}")
                is_page_not_found = True

            if is_page_not_found:
                logger.info(f'[{cls.site_name} Info] Page not found or deleted on site for code: {code_module_site_id}')
                ret['data'] = 'not found on site'
                return ret

            entity = EntityMovie(cls.site_name, code_module_site_id)
            entity.country = ['일본']
            entity.mpaa = '청소년 관람불가'

            info_base_xpath = '/html/body/div[1]/div/div/main/div/section/div[1]/div[1]/div[2]'
            info_base_elements = tree.xpath(info_base_xpath)
            if not info_base_elements:
                logger.error(f"[{cls.site_name} Info] Main info block not found for {code_module_site_id}")
                ret['data'] = 'Main info block not found on page'
                return ret
            info_element = info_base_elements[0]

            entity.thumb = []
            entity.fanart = []
            entity.extras = []
            final_image_sources = {
                'poster_source': None,
                'poster_mode': None,
                'landscape_source': None,
                'arts': [],
            }
            poster_xpath = '/html/body/div[1]/div/div/main/div/section/div[1]/div[1]/div[1]/a/img/@src'
            poster_img_elements = tree.xpath(poster_xpath)
            if poster_img_elements:
                poster_url_temp = poster_img_elements[0]
                if poster_url_temp.startswith('/'):
                    poster_url_original = SITE_BASE_URL + poster_url_temp
                else:
                    poster_url_original = poster_url_temp
                #logger.debug(f"[{cls.site_name} Info] Original poster URL: {poster_url_original}")
                final_image_sources['poster_source'] = poster_url_original
                final_image_sources['landscape_source'] = poster_url_original
                
            else:
                logger.debug(f'[{cls.site_name} Info] 포스터 이미지를 찾을 수 없음: {code_module_site_id}')

            cls.finalize_images_for_entity(entity, final_image_sources)

            title_xpath = './h2/a/text()'
            title_elements = info_element.xpath(title_xpath)
            if title_elements:
                raw_title = title_elements[0].strip()
                # logger.debug(f"[{cls.site_name} Info] Raw title for tagline/plot: {raw_title}")
                entity.tagline = cls.trans(raw_title)
                entity.plot = cls.trans(entity.tagline)
                # logger.debug(f"[{cls.site_name} Info] Processed tagline/plot: {entity.tagline}")
            else:
                logger.debug(f"[{cls.site_name} Info] Tagline/Plot (Title) not found for {code_module_site_id}")

            date_xpath = "./div[starts-with(normalize-space(.), '販売日：')]/span/text()"
            date_elements = info_element.xpath(date_xpath)
            if date_elements:
                date_str = date_elements[0].strip()
                if re.match(r'\d{4}-\d{2}-\d{2}', date_str):
                    entity.premiered = date_str
                    entity.year = int(date_str.split('-')[0])
                    # logger.debug(f"[{cls.site_name} Info] Parsed premiered: {entity.premiered}, year: {entity.year}")
                else:
                    logger.debug(f"[{cls.site_name} Info] Date format mismatch: {date_str} in {code_module_site_id}")
            else:
                logger.debug(f"[{cls.site_name} Info] Premiered date not found for {code_module_site_id}")

            seller_name_raw = None
            
            seller_xpath_link = "./div[starts-with(normalize-space(.), '販売者：')]/span/a/text()"
            seller_elements_link = info_element.xpath(seller_xpath_link)

            if seller_elements_link:
                seller_name_raw = seller_elements_link[0].strip()
                logger.debug(f"[{cls.site_name} Info] Parsed Seller (for Director/Studio) from link: {seller_name_raw}")
            else: 
                seller_xpath_text = "./div[starts-with(normalize-space(.), '販売者：')]/span/text()"
                seller_elements_text = info_element.xpath(seller_xpath_text)
                if seller_elements_text and seller_elements_text[0].strip():
                    seller_name_raw = seller_elements_text[0].strip()
                    #logger.debug(f"[{cls.site_name} Info] Parsed Seller (for Director/Studio) from text: {seller_name_raw}")
                else:
                    logger.debug(f"[{cls.site_name} Info] Seller (for Director/Studio) not found for {code_module_site_id}")

            if seller_name_raw:
                entity.director = entity.studio = seller_name_raw
            else:
                entity.director = entity.studio = None

            actor_xpath = "./div[starts-with(normalize-space(.), '女優：')]/span//a/text() | ./div[starts-with(normalize-space(.), '女優：')]/span/text()[normalize-space()]"
            actor_name_elements = info_element.xpath(actor_xpath)
            if actor_name_elements:
                entity.actor = []
                processed_actors = set()
                for actor_name_part in actor_name_elements:
                    individual_names = [name.strip() for name in re.split(r'[,/\s]+', actor_name_part.strip()) if name.strip()]
                    for name_ja in individual_names:
                        if name_ja and name_ja not in processed_actors:
                            actor_obj = EntityActor(cls.trans(name_ja))
                            actor_obj.originalname = name_ja
                            entity.actor.append(actor_obj)
                            processed_actors.add(name_ja)
                            # logger.debug(f"[{cls.site_name} Info] Added actor: {name_ja} (KO: {actor_obj.name})")
            if not hasattr(entity, 'actor') or not entity.actor:
                logger.debug(f"[{cls.site_name} Info] Actors (女優) not found or empty for {code_module_site_id}")

            entity.tag = ['FC2']
            logger.debug(f"[{cls.site_name} Info] Default tag set: {entity.tag}")

            entity.genre = []
            genre_xpath = "./div[starts-with(normalize-space(.), 'タグ：')]/span//a/text() | ./div[starts-with(normalize-space(.), 'タグ：')]/span/text()[normalize-space()]"
            genre_elements = info_element.xpath(genre_xpath)
            if genre_elements:
                raw_genres_from_site = []
                for gen_text_part in genre_elements:
                    individual_tags = [tag.strip() for tag in re.split(r'[,/\s]+', gen_text_part.strip()) if tag.strip()]
                    raw_genres_from_site.extend(individual_tags)

                processed_genres = set()
                for item_genre_ja in raw_genres_from_site:
                    if item_genre_ja not in processed_genres:
                        translated_genre = cls.trans(item_genre_ja)
                        entity.genre.append(translated_genre) 
                        processed_genres.add(item_genre_ja)
                        # logger.debug(f"[{cls.site_name} Info] Added genre: {item_genre_ja} (KO: {translated_genre})")
            if not entity.genre:
                logger.debug(f"[{cls.site_name} Info] Genres (タグ) not found or empty for {code_module_site_id}")

            runtime_xpath = "./div[starts-with(normalize-space(.), '収録時間：')]/span/text()"
            runtime_elements = info_element.xpath(runtime_xpath)
            if runtime_elements:
                time_str = runtime_elements[0].strip()
                parts = time_str.split(':')
                try:
                    if len(parts) == 3:
                        h, m, s = map(int, parts)
                        entity.runtime = h * 60 + m
                    elif len(parts) == 2:
                        m, s = map(int, parts)
                        entity.runtime = m
                    else:
                        logger.debug(f"[{cls.site_name} Info] Unexpected runtime format: {time_str} for {code_module_site_id}")
                    if hasattr(entity, 'runtime') and entity.runtime is not None:
                        logger.debug(f"[{cls.site_name} Info] Parsed runtime (minutes): {entity.runtime}")
                except ValueError:
                    logger.debug(f"[{cls.site_name} Info] Failed to parse runtime string: {time_str} for {code_module_site_id}")
            else:
                logger.debug(f"[{cls.site_name} Info] Runtime (収録時間) not found for {code_module_site_id}")

            entity.title = f'FC2-{keyword_num_part}'
            entity.originaltitle = f'FC2-{keyword_num_part}'
            entity.sorttitle = f'FC2-{keyword_num_part}'
            logger.debug(f"[{cls.site_name} Info] Set fixed title/originaltitle/sorttitle: {entity.title}")

            # 리뷰 정보 파싱
            entity.review = []
            use_review = False
            if use_review:
                logger.debug(f"[{cls.site_name} Info] Parsing reviews for {code_module_site_id}")
                comments_section = tree.xpath("//div[@id='comments']")
                if comments_section:
                    comment_elements = comments_section[0].xpath("./div[starts-with(@id, 'comment-')]")
                    logger.debug(f"[{cls.site_name} Info] Found {len(comment_elements)} comment elements.")

                    for comment_el in comment_elements:
                        try:
                            review_obj = EntityReview(cls.site_name)

                            author_el = comment_el.xpath("./div[contains(@class, 'flex-auto')]/div[1]/div[1]/p/text()")
                            author = author_el[0].strip() if author_el and author_el[0].strip() else 'Anonymous'

                            up_votes_el = comment_el.xpath(".//span[starts-with(@id, 'up-counter-')]/text()")
                            up_votes = up_votes_el[0].strip() if up_votes_el else '0'

                            down_votes_el = comment_el.xpath(".//span[starts-with(@id, 'down-counter-')]/text()")
                            down_votes = down_votes_el[0].strip() if down_votes_el else '0'

                            date_id_text_el = comment_el.xpath("./div[contains(@class, 'flex-auto')]/div[1]/div[2]/p/text()")
                            review_date_str = ''
                            comment_id_str = ''
                            if date_id_text_el:
                                full_date_id_str = date_id_text_el[0].strip()
                                match_date = re.search(r'(\d{4}-\d{2}-\d{2}\s\d{2}:\d{2}:\d{2})', full_date_id_str)
                                if match_date:
                                    review_date_str = match_date.group(1)

                                match_id = re.search(r'ID:(\S+)', full_date_id_str)
                                if match_id:
                                    comment_id_str = match_id.group(1)

                            review_obj.author = author
                            if hasattr(review_obj, 'date') and review_date_str:
                                review_obj.date = review_date_str

                            comment_p_elements = comment_el.xpath("./div[contains(@class, 'flex-auto')]/p[contains(@class, 'text-gray-500')]")
                            comment_text_raw = ''
                            if comment_p_elements:
                                p_element = comment_p_elements[0]
                                parts = []
                                for node in p_element.xpath('./node()'):
                                    if isinstance(node, str):
                                        parts.append(node)
                                    elif hasattr(node, 'tag'):
                                        if node.tag == 'br':
                                            parts.append('\n')
                                        else:
                                            parts.append(html.tostring(node, encoding='unicode', method='html'))

                                inner_html_content_with_newlines = ''.join(parts)
                                temp_element = html.fromstring(f"<div>{inner_html_content_with_newlines}</div>")
                                comment_text_raw = temp_element.text_content().strip()

                            if not comment_text_raw:
                                logger.debug(f"[{cls.site_name} Info] Skipping comment (ID: {comment_id_str or 'N/A'}) due to empty content.")
                                continue

                            if hasattr(review_obj, 'source'):
                                review_obj.source = comment_text_raw

                            comment_text_for_display = SiteUtil.trans(comment_text_raw, do_trans=do_trans, source='ja', target='ko')

                            review_header_parts = [f"좋아요: {up_votes}", f"싫어요: {down_votes}"]
                            if review_date_str and not hasattr(review_obj, 'date'): # date 속성이 없을 경우 text에 포함
                                review_header_parts.append(f"작성일: {review_date_str}")

                            review_header = "[" + " / ".join(review_header_parts) + "]"
                            review_obj.text = f"{review_header} {comment_text_for_display}"

                            if comment_id_str:
                                review_obj.link = f"{info_url}#comment-{comment_id_str}"
                            else:
                                review_obj.link = info_url

                            entity.review.append(review_obj)
                            logger.debug(f"[{cls.site_name} Info] Added review by '{author}': Up={up_votes}, Down={down_votes}, Date='{review_date_str}', ID='{comment_id_str}'")

                        except Exception as e_review:
                            logger.error(f"[{cls.site_name} Info] Exception parsing a review for {code_module_site_id}: {e_review}")
                            logger.error(traceback.format_exc())
                else:
                    logger.debug(f"[{cls.site_name} Info] No comments section found for {code_module_site_id}")
            else:
                logger.debug(f"[{cls.site_name} Info] Skipping review parsing as 'use_review' is False for {code_module_site_id}")

            logger.info(f"[{cls.site_name} Info] Successfully processed info for code: {code_module_site_id}")
            ret['ret'] = 'success'
            ret['data'] = entity.as_dict()

        except Exception as exception: 
            logger.error(f'[{cls.site_name} Info] Exception for code {code_module_site_id}: {exception}')
            logger.error(traceback.format_exc())
            ret['ret'] = 'exception'
            ret['data'] = str(exception)

        return ret


    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
































    ################################################
    # region 전용 UTIL

    @classmethod
    def _get_fc2ppvdb_page_content(cls, url, use_cloudscraper=True):
        if cls._is_blocked():
            return None, "Site is rate-limited"

        res = None
        page_text_for_rate_limit_check = "" # Rate limit HTML 내용 검사용

        if use_cloudscraper:
            res_cs = cls.get_response_cs(url, cookies=cls.ppvdb_default_cookies, timeout=20)
            if res_cs is not None: # Cloudscraper가 응답 객체를 반환했다면
                res = res_cs # 일단 res에 할당
                if hasattr(res_cs, 'text'):
                    page_text_for_rate_limit_check = res_cs.text

                # Cloudscraper 응답에서 바로 Rate Limit 조건 확인
                is_rate_limited_by_content_cs = False
                if "<title>Too Many Requests</title>" in page_text_for_rate_limit_check:
                    is_rate_limited_by_content_cs = True
                
                if res.status_code == 429 or 'Retry-After' in res.headers or is_rate_limited_by_content_cs:
                    logger.warning(f"[{cls.site_name}] Rate limit detected by Cloudscraper. Status: {res.status_code}, Headers: {res.headers.get('Retry-After')}, HTML Title: {is_rate_limited_by_content_cs}")
                    if cls._handle_rate_limit(res.headers): # Retry-After 헤더가 있으면 그것을 우선 사용
                        return None, f"Rate limit hit (Cloudscraper with Header). Retry-After: {res.headers.get('Retry-After', 'N/A')}"
                    elif is_rate_limited_by_content_cs: # HTML 내용으로만 감지
                        logger.warning(f"[{cls.site_name}] Rate limit by HTML (Cloudscraper), no Retry-After. Default block.")
                        cls._block_release_time_fc2ppvdb = time.time() + 300 # 예: 5분 기본 차단
                        cls._last_retry_after_value = 300 
                        return None, "Rate limit detected by HTML content (Cloudscraper - default block applied)"
                    # else: Retry-After 헤더 없고, HTML 내용으로도 특정 못하면 그냥 일반 실패로 간주 (아래 로직 따름)

            if res is None and use_cloudscraper: # Cloudscraper가 None을 반환했거나, 위 Rate Limit 조건에 안 걸렸지만 실패한 경우
                logger.warning(f"[{cls.site_name}] Cloudscraper returned None or non-rate-limit error for {url}. Falling back to standard requests.")
                # res는 여전히 None인 상태로 아래 fallback 로직으로 넘어감

        # Cloudscraper를 사용하지 않았거나, Cloudscraper가 None을 반환했거나,
        # Cloudscraper가 응답했지만 Rate Limit이 아닌 다른 이유로 실패했을 경우 fallback
        if res is None:
            logger.debug(f"[{cls.site_name}] Attempting with standard requests for {url}...")
            res_std = cls.get_response(url, cookies=cls.ppvdb_default_cookies, timeout=20)
            if res_std is not None:
                res = res_std # res에 할당
                if hasattr(res_std, 'text'):
                    page_text_for_rate_limit_check = res_std.text
            # else: res는 여전히 None

        # 최종 res 객체로 나머지 처리
        if res:
            page_text = res.text if hasattr(res, 'text') else ""

            # 표준 requests 응답에서도 Rate Limit 조건 한 번 더 확인 (Cloudscraper가 실패하고 fallback했을 경우 대비)
            is_rate_limited_by_content_std = False
            if "<title>Too Many Requests</title>" in page_text: # status code 조건은 위에서 res_cs에 대해 이미 했을 수 있으므로 여기선 생략 가능
                is_rate_limited_by_content_std = True

            if res.status_code == 429 or 'Retry-After' in res.headers or is_rate_limited_by_content_std:
                logger.warning(f"[{cls.site_name}] Rate limit detected by standard requests (or fallback). Status: {res.status_code}, Headers: {res.headers.get('Retry-After')}, HTML Title: {is_rate_limited_by_content_std}")
                if cls._handle_rate_limit(res.headers):
                    return None, f"Rate limit hit (Standard Requests with Header). Retry-After: {res.headers.get('Retry-After', 'N/A')}"
                elif is_rate_limited_by_content_std:
                    logger.warning(f"[{cls.site_name}] Rate limit by HTML (Standard Requests), no Retry-After. Default block.")
                    cls._block_release_time_fc2ppvdb = time.time() + 300 # 예: 5분 기본 차단
                    cls._last_retry_after_value = 300
                    return None, "Rate limit detected by HTML content (Standard Requests - default block applied)"

            if res.status_code == 200:
                # 로그인 페이지 또는 "페이지 없음" 감지는 그대로 유지
                if "fc2.com" in res.url and "login.php" in res.url:
                    logger.warning(f"[{cls.site_name}] Detected redirection to FC2 main login page...")
                    return None, page_text
                if "お探しのページは見つかりません。" in page_text:
                    logger.info(f"[{cls.site_name}] Page explicitly states 'not found'...")
                    return None, page_text
                
                try:
                    return html.fromstring(page_text), page_text
                except Exception as e_parse:
                    logger.error(f"[{cls.site_name}] Failed to parse HTML: {e_parse}. URL: {url}")
                    return None, page_text
            else: # 200도 아니고 Rate Limit 조건에도 해당 안되는 다른 에러
                logger.warning(f"[{cls.site_name}] Failed to get page. Status: {res.status_code}. URL: {url}")
                return None, page_text
        else: # 최종적으로 res가 None인 경우 (모든 시도 실패)
            logger.warning(f"[{cls.site_name}] Failed to get page (all attempts failed - response is None). URL: {url}")
            return None, "Network error or no response from all attempts"


    @classmethod
    def _is_blocked(cls):
        """현재 사이트가 차단 상태인지 확인하고, 남은 차단 시간을 로깅합니다."""
        if cls._block_release_time_fc2ppvdb == 0:
            return False # 차단된 적 없거나 해제됨
        
        now_timestamp = time.time()
        if now_timestamp < cls._block_release_time_fc2ppvdb:
            remaining_seconds = int(cls._block_release_time_fc2ppvdb - now_timestamp)
            remaining_time_str = str(timedelta(seconds=remaining_seconds)) # HH:MM:SS 형식
            logger.warning(f"[{cls.site_name}] Site is currently rate-limited. Retrying after {remaining_time_str} (Retry-After was {cls._last_retry_after_value}s).")
            return True
        else: # 차단 시간 지남
            logger.info(f"[{cls.site_name}] Rate-limit period has passed. Resetting block time.")
            cls._block_release_time_fc2ppvdb = 0 # 차단 해제, 변수 초기화
            cls._last_retry_after_value = 0
            return False


    @classmethod
    def _handle_rate_limit(cls, response_headers):
        """Retry-After 헤더를 확인하고 차단 시간을 설정합니다."""
        retry_after_str = response_headers.get('Retry-After')
        if retry_after_str and retry_after_str.isdigit():
            retry_after_seconds = int(retry_after_str)
            cls._last_retry_after_value = retry_after_seconds # 로그용으로 저장
            # 현재 시간에 Retry-After 초를 더해 차단 해제 시간 계산
            # 너무 긴 시간(예: 하루 이상)이 설정되면 최대치를 두는 것도 고려
            # if retry_after_seconds > 86400: # 예: 하루 이상이면 최대 1시간으로 제한 (선택적)
            #    logger.warning(f"[{cls.site_name}] Received very long Retry-After: {retry_after_seconds}s. Limiting block to 1 hour.")
            #    retry_after_seconds = 3600
            
            cls._block_release_time_fc2ppvdb = time.time() + retry_after_seconds
            release_dt_str = datetime.fromtimestamp(cls._block_release_time_fc2ppvdb).strftime('%Y-%m-%d %H:%M:%S')
            logger.warning(f"[{cls.site_name}] Rate limit detected. Retry-After: {retry_after_seconds}s. Blocking requests until {release_dt_str}.")
            return True # 차단 설정됨
        return False # Retry-After 헤더 없거나 유효하지 않음
    
    # endregion UTIL
    ################################################