import re
import json
import base64

from lxml.html import HtmlElement

from . import SiteDaum, SiteUtil
from .entity_base import (EntityActor, EntityExtra2, EntityMovie2, EntityReview,
                          EntityRatings, EntitySearchItemMovie, EntityThumb)
from .setup import *


class SiteDaumMovie(SiteDaum):
    site_base_url = 'https://search.daum.net'
    module_char = 'M'
    site_char = 'D'

    DEFAULT_QUERY = {
        "w": "cin",
        "coll": "movie-main",
        "spt": "movie-info",
        "DA": "EM1",
        "rtmaxcoll": "EM1"
    }

    @classmethod
    def search(cls, keyword: str, year: int = None) -> dict[str, str | list]:
        search_results = []
        logger.debug(f'Daum movie search: {keyword=} {year=}')
        # 실제 1900년 영화라면?
        if year and int(year) == 1900:
            year = None
        encoded_keyword = base64.urlsafe_b64encode(keyword.encode('utf-8')).decode('utf-8')
        cache_key = f"site_daum_movie:search:{encoded_keyword}:{year or '1900'}"
        try:
            # 캐시 활용
            cached = P.cache.get(cache_key)
            if cached:
                logger.debug(f"Cache hit: {cache_key}")
                ret = json.loads(cached)
                ret['cached'] = True
                return ret

            # request
            search_keywords = []
            if year:
                search_keywords.append(f"{keyword} {str(year)}")
                search_keywords.append(f"영화 {keyword} {str(year)}")
            search_keywords.extend([f"영화 {keyword}", keyword])

            for search_keyword in search_keywords:
                query = cls.DEFAULT_QUERY.copy()
                query['w'] = 'tot'
                query['q'] = search_keyword
                html = cls.get_tree(cls.get_request_url(query=query))
                if results := cls.get_movies(html):
                    search_results.extend(results)
                    break
            else:
                logger.warning(f"No movie found: '{keyword}'")
        except Exception:
            logger.exception(f"Failed to search: {keyword=} {year=}")
        if search_results:
            # 스코어
            for idx, sr in enumerate(search_results):
                if SiteUtil.compare(keyword, sr['title']):
                    if year and year != 1900:
                        discrepancy = abs(sr['year'] - year)
                        if discrepancy == 0:
                            score = 100
                        elif discrepancy < 2:
                            score = 90
                        else:
                            score = 80
                    else:
                        score = 75
                else:
                    score = max(75 - (idx * 5), 0)
                sr['score'] = score
            search_results = sorted(search_results, key=lambda x:x.get('score', 0), reverse=True)
            ret = {'ret': 'success', 'data': search_results, 'cached': False}
            P.cache.set(cache_key, json.dumps(ret, separators=(',', ':')), ex=30)
            return ret
        return {'ret': 'empty'}

    @classmethod
    def info(cls, code: str) -> dict:
        code = code.split('#')[0]
        logger.debug(f'Daum movie info: {code=}')
        cache_key = f"site_daum_movie:info:{code}"
        try:
            cached = P.cache.get(cache_key)
            if cached:
                logger.debug(f"Cache hit: {cache_key}")
                ret = json.loads(cached)
                ret['cached'] = True
                return ret

            # request
            query = cls.DEFAULT_QUERY.copy()
            query['q'] = '영화'
            query['spId'] = code[2:]
            html = cls.get_tree(cls.get_request_url(query=query))
            if results := cls.get_movies(html, mode="info"):
                ret = {
                    'ret': 'success',
                    'data': results[0],
                    'cached': False
                }
                P.cache.set(cache_key, json.dumps(ret, separators=(',', ':')), ex=30)
                return ret
        except Exception:
            logger.exception(f"Failed to get info: {code=}")
        return {'ret': 'empty'}

    @classmethod
    def get_movies(cls, html: HtmlElement, mode: str = "search") -> tuple:
        container = html.find(".//div[@id='em1Coll']")
        movies = []
        if container is None:
            logger.warning("No movie container found...")
            return movies

        # 정보, 출연/제작, 영상, 포토, 시리즈
        card_tab = cls.parse_card_tab(c_section_tab) if (c_section_tab := container.find(".//div[@class='c-section-tab']")) is not None else {}

        # code, title, link
        card_title = cls.parse_card_title(c_tit_exact) if (c_tit_exact := container.find(".//div[@class='c-tit-exact']")) is not None else {}
        if not (card_title.get('code') and card_title.get('title')):
            logger.warning("No title and code found...")
            return movies

        # poster, description, premiered, countries, genres, runtime, mpaa, ratings, customer
        card_info = cls.parse_card_section_info(cont_info) if (cont_info := container.find(".//div[@class='cont_info']")) is not None else {}

        # title in english, year
        title_in_english = year = None
        if sub_title := card_title.get('sub_title'):
            splits = sub_title.rsplit(',', 1)
            if splits:
                title_in_english = splits[0].strip()
                try:
                    year = int(splits[-1].strip())
                except Exception:
                    pass

        code = cls.module_char + cls.site_char + card_title.get('code')
        if mode == "search":
            primary_movie = EntitySearchItemMovie(cls.site_name)
        else:
            primary_movie = EntityMovie2(cls.site_name, code)
        primary_movie.code = code
        primary_movie.title = card_title.get('title')
        primary_movie.year = year or 1900

        if mode == "search":
            primary_movie.link = card_title.get('link') or ""
            primary_movie.image_url = card_info.get('thumb') or ""
            primary_movie.title_en = title_in_english or ""
            primary_movie.desc = "\n".join((", ".join( card_info.get('감독') + card_info.get('개요')), card_info.get('줄거리') or ""))
            primary_movie.score = 100
            primary_movie.originaltitle = primary_movie.title if "한국" in card_info.get('개요') or () else title_in_english or ""
        else:
            primary_movie.plot = card_info.get('줄거리') or ""
            primary_movie.code_list.append(["daum_id", code[2:]])
            primary_movie.premiered = card_info.get('개봉') or ""
            primary_movie.country = card_info.get('국가') or ()
            primary_movie.genre = card_info.get('장르') or ()
            primary_movie.mpaa = card_info.get('등급') or ""
            for rating in card_info.get('평점') or ():
                primary_movie.ratings.append(EntityRatings(rating.get('value') or 0, name=rating.get('name') or ""))
            primary_movie.runtime = card_info.get('시간') or 0
            primary_movie.originaltitle = primary_movie.title if "한국" in primary_movie.country else title_in_english or ""
        movies.append(primary_movie)

        if mode == "search":
            try:
                # same titles
                same_title_xpaths = (
                    ".//strong[@class='screen_out' and contains(text(), '동명영화')]/following-sibling::div",
                    ".//div[contains(@class, 'c-header') and .//*[contains(text(), '동명영화')]]/following-sibling::div[contains(@class, 'bundle_basic')]",
                )
                for same_xpath in same_title_xpaths:
                    if not (div_tags := container.xpath(same_xpath)):
                        continue
                    movies.extend(cls.get_additional_movies(div_tags[0]))

                # series
                if '시리즈' in card_tab:
                    query = cls.DEFAULT_QUERY.copy()
                    query['q'] = f"{primary_movie.title} 시리즈"
                    query['spId'] = primary_movie.code[2:]
                    query['spt'] = 'movie-series'
                    series_html = cls.get_tree(cls.get_request_url(query=query))
                    if (series_container := series_html.find(".//div[@disp-attr='EM1']//div[@class='cont_series']/div")) is not None:
                        movies.extend(movie for movie in cls.get_additional_movies(series_container) if movie.code != primary_movie.code)
            except Exception:
                logger.exception(f"Failed to search more movies...")
        else:
            # people
            try:
                if any('출연' in tab for tab in card_tab):
                    query = cls.DEFAULT_QUERY.copy()
                    query['q'] = f"{primary_movie.title} 출연진"
                    query['spId'] = primary_movie.code[2:]
                    query['spt'] = 'movie-casting'
                    people_html = cls.get_tree(cls.get_request_url(query=query))
                    if (cast_container := people_html.find(".//div[@id='em1Coll']//div[@class='cont_cast']")) is not None:
                        people = cls.parse_people(cast_container)
                        order_actor = 0
                        for person in people:
                            try:
                                match person.get('category'):
                                    case 'director':
                                        primary_movie.director.append(person.get('name'))
                                    case 'producer':
                                        primary_movie.producers.append(person.get('name'))
                                    case 'writer':
                                        # SjvaAgent에서 credits을 플렉스 writers로 저장 중
                                        primary_movie.credits.append(person.get('name'))
                                    case 'actor':
                                        entity = EntityActor('', site=cls.site_name)
                                        entity.name = person.get('name')
                                        entity.order = order_actor
                                        if person.get('role'):
                                            role = re.sub(r'\s역$', '', person.get('role'))
                                            if not role == '출연':
                                                entity.role = role
                                        if person.get('thumb'):
                                            entity.thumb = person.get('thumb')
                                        primary_movie.actor.append(entity)
                                        order_actor += 1
                            except Exception:
                                logger.exception(f"Failed to parse a person...")
            except Exception:
                logger.exception(f"Failed to parse cast and crew...")

            # clip
            try:
                if any('영상' in tab for tab in card_tab):
                    query = cls.DEFAULT_QUERY.copy()
                    query['q'] = f"{primary_movie.title} 영상"
                    query['spId'] = primary_movie.code[2:]
                    query['spt'] = 'movie-clip'
                    clip_html = cls.get_tree(cls.get_request_url(query=query))
                    if (clip_container := clip_html.find(".//div[@id='em1Coll']//div[@class='cont_vod']")) is not None:
                        for item_thumb in clip_container.xpath(".//li//div[@class='item-thumb']"):
                            try:
                                clip_data = cls.parse_thumb_and_bundle(item_thumb)
                                if not clip_data:
                                    continue
                                extra = EntityExtra2()
                                extra.thumb = clip_data.get('thumb') or ""
                                extra.content_url = clip_data.get('link') or ""
                                labels = clip_data.get('labels') or ("", "")
                                if labels[0]:
                                    extra.title = labels[0]
                                if '예고' not in extra.title:
                                    extra.content_type = 'Featurette'
                                if labels[1]:
                                    date = cls.parse_date_text(labels[1])
                                    extra.premiered = date.strftime('%Y-%m-%d')
                                primary_movie.extras.append(extra)
                            except Exception:
                                logger.exception(f"Failed to parse a clip...")
            except Exception:
                logger.exception(f"Failed to parse clips...")

            # art
            try:
                if any('포토' in tab for tab in card_tab):
                    query = cls.DEFAULT_QUERY.copy()
                    query['q'] = f"{primary_movie.title} 포토"
                    query['spId'] = primary_movie.code[2:]
                    query['spt'] = 'movie-photo'
                    photo_html = cls.get_tree(cls.get_request_url(query=query))
                    stills = []
                    posters = []
                    etcs = []
                    for container_photo in photo_html.xpath(".//div[@id='em1Coll']//div[@class='cont_photo']"):
                        if (container_title := container_photo.find("./div[@class='c-tit-section']")) is None:
                            continue
                        title_section = container_title.text_content()
                        for img_tag in container_photo.xpath(".//img"):
                            try:
                                image_url = cls.process_image_url(img_tag)
                                if not image_url:
                                    continue
                                aspect = 'poster' if float(img_tag.get('height') or 0) > float(img_tag.get('width') or 0) else 'landscape'
                                image_score = 100
                                match title_section:
                                    case '스틸':
                                        bucket = stills
                                    case '포스터':
                                        bucket = posters
                                    case _:
                                        bucket = etcs
                                        image_score = 80
                                bucket.append(EntityThumb(aspect=aspect, value=image_url, site=cls.site_name, score=image_score))
                            except Exception:
                                logger.exception(f"Failed to parse a photo...")
                    primary_movie.art.extend(posters)
                    primary_movie.art.extend(stills)
                    primary_movie.art.extend(etcs)
            except Exception:
                logger.exception(f"Failed to parse photos...")

            # review
            try:
                if any('평점' in tab for tab in card_tab):
                    query = cls.DEFAULT_QUERY.copy()
                    query['q'] = f"{primary_movie.title} 전문가평점"
                    query['spId'] = primary_movie.code[2:]
                    query['spt'] = 'movie-review'
                    review_html = cls.get_tree(cls.get_request_url(query=query))
                    for li_tag in review_html.xpath(".//div[@id='em1Coll']//div[@class='cont_score']//li"):
                        try:
                            texts = cls.iter_text(li_tag, excludes=(",", "|", "/", "점"))
                            if len(texts) == 3:
                                primary_movie.review.append(EntityReview(cls.site_name, author=texts[0], source="cine21-expert", text=texts[-1], rating=float(texts[1])))
                        except Exception:
                            logger.exception(f"Failed to parse a review...")
            except Exception:
                logger.exception(f"Failed to parse reviews...")
        return tuple(movie.as_dict() for movie in movies)

    @classmethod
    def get_additional_movies(cls, html: HtmlElement) -> list[dict]:
        """
        동명영화, 시리즈 등의 포스터 형식 영화 목록
        """
        additionals = []
        for item_thumb_tag in html.xpath(".//ul/li//div[@class='item-thumb']"):
            code = title = thumb = year = link = None
            data = cls.parse_thumb_and_bundle(item_thumb_tag)
            if not data or not (query := data.get('query')):
                continue
            try:
                if query.get("spId"):
                    code = cls.module_char + cls.site_char + query.get('spId')
                if query.get("q"):
                    title = query.get("q")
                    query['w'] = 'cin'
                    link = cls.get_request_url(query=query)
                if data.get('thumb'):
                    thumb = data.get('thumb')
                for text in data.get('labels') or ():
                    if text.isdigit():
                        year = int(text)
                        break
                additional = EntitySearchItemMovie(cls.site_name)
                additional.code = code
                additional.title = title
                additional.image_url = thumb or ""
                additional.year = year or 1900
                additional.link = link or ""
                additional.desc = "Daum 영화 검색"
                additionals.append(additional)
            except Exception:
                logger.exception(f"Failed to search more movie...")
        return additionals
