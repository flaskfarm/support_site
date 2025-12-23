import urllib.parse

from lxml.html import HtmlElement

from . import SiteDaum
from .site_util import caching, encode_base64, score_to_stars
from .entity_base import (EntityActor, EntityMovie2, EntityReview,
                          EntityRatings, EntitySearchItemMovie, EntityThumb)
from .setup import *


class SiteDaumMovie(SiteDaum):

    module_char = 'M'
    default_query = {
        "w": "cin",
        "coll": "movie-main",
        "spt": "movie-info",
        "DA": "EM1",
        "rtmaxcoll": "EM1"
    }

    @classmethod
    def search(cls, keyword: str, year: int = None) -> dict[str, str | list]:
        search_results = []
        keyword = cls.refine_keyword(keyword)
        logger.debug(f'Daum movie search: {keyword=} {year=}')
        # 실제 1900년 영화라면?
        if year and int(year) == 1900:
            year = None
        cache_key = f"daum:movie:search:{encode_base64(keyword)}:{year or '1900'}"
        try:
            # 캐시 활용
            if cached := caching(lambda: None, cache_key, cache_enable=cls.cache_enable, print_log=True)():
                return cached
            # request
            search_keywords = [f"영화 {keyword}", keyword]
            if year:
                search_keywords.append(f"{keyword} {str(year)}")
                search_keywords.append(f"영화 {keyword} {str(year)}")

            for search_keyword in search_keywords:
                logger.debug(f"Try searching for '{search_keyword}'")
                query = cls.get_request_query(w='tot', q=search_keyword)
                html = cls.get_tree(cls.get_request_url(query=query))
                if results := cls.get_movies(html):
                    search_results.extend(results)
                    break
            else:
                logger.warning(f"검색 결과가 없습니다: '{keyword}'")
            if search_results:
                cls.score_search_results(search_results, keyword, year)
                search_results = sorted(search_results, key=lambda x:x.get('score', 0), reverse=True)
                ret = {'ret': 'success', 'data': search_results}
            else:
                ret = {'ret': 'empty'}
        except Exception as e:
            logger.exception(f"검색에 실패했습니다: {keyword=} {year=}")
            ret = {'ret': 'exception', 'data': repr(e)}
        caching(lambda: ret, cache_key, cls.cache_expiry, cls.cache_enable)()
        return ret

    @classmethod
    def info(cls, code: str) -> dict:
        code = code.split('#')[0]
        logger.debug(f'Daum movie info: {code=}')
        cache_key = f"daum:movie:info:{code[2:]}"
        try:
            if cached := caching(lambda: None, cache_key, cache_enable=cls.cache_enable, print_log=True)():
                return cached
            # request
            query = cls.get_request_query(q='영화', spId=code[2:])
            html = cls.get_tree(cls.get_request_url(query=query))
            if results := cls.get_movies(html, mode="info"):
                ret = {'ret': 'success', 'data': results[0]}
            else:
                ret = {'ret': 'empty'}
        except Exception as e:
            logger.exception(f"정보 탐색에 실패했습니다: {code=}")
            ret = {'ret': 'exception', 'data': repr(e)}
        caching(lambda: ret, cache_key, cls.cache_expiry, cls.cache_enable)()
        return ret

    @classmethod
    def get_movies(cls, html: HtmlElement, mode: str = "search") -> tuple:
        container = html.find(".//div[@id='em1Coll']")
        movies = []
        if container is None:
            logger.warning("No movie container found...")
            return tuple(movies)

        # 정보, 출연/제작, 영상, 포토, 시리즈
        card_tab = cls.parse_card_tab(container)

        # code, title, link
        card_title = cls.parse_card_title(container)
        if not (card_title.get('code') and card_title.get('title')):
            logger.warning("No title and code found...")
            return tuple(movies)

        # poster, description, premiered, countries, genres, runtime, mpaa, ratings, customer
        card_info = cls.parse_card_section_info(container)

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
        if year is None:
            dates = (card_info.get('개봉') or '').split("-")
            primary_movie.year = int(dates[0]) if dates and dates[0].isdigit() else 1900
        else:
            primary_movie.year = year
        if mode == "search":
            primary_movie.link = card_title.get('link') or ""
            primary_movie.image_url = card_info.get('image') or card_info.get('thumb') or ""
            primary_movie.title_en = title_in_english or ""
            primary_movie.desc = "\n".join((", ".join( (card_info.get('감독') or "") + (card_info.get('개요') or "") ), card_info.get('줄거리') or ""))
            primary_movie.score = 100
            primary_movie.originaltitle = primary_movie.title if "한국" in card_info.get('개요') or () else title_in_english or ""
        else:
            primary_movie.art.append(EntityThumb(aspect='poster', value=card_info.get('image') or '', thumb=card_info.get('thumb') or '', site=cls.site_name, score=101))
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
                    movies.extend(cls.parse_additional_movies(div_tags[0]))

                # series
                if '시리즈' in card_tab:
                    query = cls.get_request_query(q=f"{primary_movie.title} 시리즈", spId=primary_movie.code[2:], spt='movie-series')
                    series_html = cls.get_tree(cls.get_request_url(query=query))
                    if (series_container := series_html.find(".//div[@disp-attr='EM1']//div[@class='cont_series']/div")) is not None:
                        movies.extend(movie for movie in cls.parse_additional_movies(series_container) if movie.code != primary_movie.code)
            except Exception:
                logger.exception(f"Failed to search more movies...")
        else:
            # people
            try:
                if (credit_url := card_tab.get('출연') or card_tab.get('출연/제작')):
                    people_html = cls.get_tree(credit_url)
                    data = cls.parse_movie_people(people_html)
                    primary_movie.director.extend(data.get('director'))
                    primary_movie.producers.extend(data.get('producer'))
                    primary_movie.credits.extend(data.get('writer'))
                    primary_movie.actor.extend(data.get('actor'))
            except Exception:
                logger.exception(f"Failed to parse cast and crew...")

            # clip
            try:
                if card_tab.get('영상'):
                    clip_html = cls.get_tree(card_tab.get('영상'))
                    if (clip_container := clip_html.xpath(".//div[@id='em1Coll']//div[@class='cont_vod']")):
                        primary_movie.extras.extend(cls.parse_clips(clip_container[0]))
            except Exception:
                logger.exception(f"Failed to parse clips...")

            # art
            try:
                if any('포토' in tab for tab in card_tab):
                    query = cls.get_request_query(q=f"{primary_movie.title} 포토", spId=primary_movie.code[2:], spt='movie-photo')
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
                                thumb = img_tag.get('data-original-src') or img_tag.get('src') or ""
                                if not thumb:
                                    continue
                                img_query = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(thumb).query))
                                image = img_query.get('fname')
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
                                bucket.append(EntityThumb(aspect=aspect, value=image if image else '', thumb=thumb if thumb else '', site=cls.site_name, score=image_score))
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
                    query = cls.get_request_query(q=f"{primary_movie.title} 전문가평점", spId=primary_movie.code[2:], spt='movie-review')
                    review_html = cls.get_tree(cls.get_request_url(query=query))
                    for li_tag in review_html.xpath(".//div[@id='em1Coll']//div[@class='cont_score']//li"):
                        try:
                            texts = cls.iter_text(li_tag, excludes=(",", "|", "/", "점"))
                            if len(texts) == 3:
                                stars = score_to_stars(float(texts[1]))
                                primary_movie.review.append(EntityReview(cls.site_name, author=texts[0], source="Cine21", text=f"{stars}/{texts[1]} {texts[-1]}", rating=float(texts[1])))
                        except Exception:
                            logger.exception(f"Failed to parse a review...")
            except Exception:
                logger.exception(f"Failed to parse reviews...")
        return tuple(movie.as_dict() for movie in movies)

    @classmethod
    def parse_additional_movies(cls, html: HtmlElement) -> list:
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
                if data.get('title'):
                    title = data.get('title')
                if data.get('labels') and not title:
                    title = data.get('labels')[0]
                if query.get("spId"):
                    code = cls.module_char + cls.site_char + query.get('spId')
                if query.get("q"):
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
        try:
            return sorted(additionals, key=lambda x: (x.year, int(x.code[2:])))
        except Exception:
            logger.exception(f"시리즈/동명 정렬 실패")
        return additionals

    @classmethod
    def parse_movie_people(cls, container: HtmlElement) -> dict:
        data = {
            'director': [],
            'producer': [],
            'writer': [],
            'actor': [],
        }
        if (cast_container := container.find(".//div[@id='em1Coll']//div[@class='cont_cast']")) is not None:
            people = cls.parse_people(cast_container)
            order_actor = 0
            for person in people:
                try:
                    match person.get('category'):
                        case 'director':
                            data['director'].append(person.get('name'))
                        case 'producer':
                            data['producer'].append(person.get('name'))
                        case 'writer':
                            # SjvaAgent에서 credits을 플렉스 writers로 저장 중
                            data['writer'].append(person.get('name'))
                        case 'actor':
                            entity = EntityActor('', site=cls.site_name)
                            entity.name = person.get('name')
                            entity.order = order_actor
                            if person.get('role'):
                                if '출연' not in person.get('role'):
                                    entity.role = person.get('role')
                            if person.get('thumb'):
                                entity.thumb = person.get('thumb')
                            data['actor'].append(entity)
                            order_actor += 1
                except Exception:
                    logger.exception(f"Failed to parse a person...")
        return data
