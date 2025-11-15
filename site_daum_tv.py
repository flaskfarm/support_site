import urllib.parse
from datetime import datetime

from lxml import etree
from lxml.html import HtmlElement
from numpy import add

from . import SiteDaum
from .site_util import caching, encode_base64, decode_base64
from .entity_base import (EntityActor, EntityEpisode, EntityExtra, EntityShow,
                          EntityThumb, EntitySearchItemTvDaum)
from .setup import *


class SiteDaumTv(SiteDaum):

    module_char = 'K'
    weekdays = {0: '월', 1: '화', 2: '수', 3: '목', 4: '금', 5: '토', 6: '일'}
    default_query = {
        'w': 'tv',
        'coll': 'tv-main',
        'spt': 'tv-info',
        'DA': 'TVP',
        'rtmaxcoll': 'TVP'
    }

    @classmethod
    def search(cls, keyword: str, daum_id: str | int = None, year: str | int = None, image_mode: str = '0') -> dict[str, str | dict]:
        keyword = cls.refine_keyword(keyword)
        logger.debug(f'Daum TV search: {keyword=} {year=} {daum_id=}')
        search_results = ()
        if year and int(year) == 1900:
            year = None
        cache_key = f"daum:tv:search:{daum_id}" if daum_id else f"daum:tv:search:{encode_base64(keyword)}:{year or '1900'}"
        try:
            if cached := caching(lambda: None, cache_key, cache_enable=cls.cache_enable, print_log=True)():
                return cached
            # request
            logger.debug(f"Try searching for '{keyword}'")
            query = cls.get_request_query(q=keyword, w='tot')
            if daum_id is not None:
                query['spId'] = daum_id
            html = cls.get_tree(cls.get_request_url(query=query))
            if not (search_results := cls.get_shows(html)):
                logger.warning(f'검색 결과가 없습니다: {keyword}')
            if search_results:
                cls.score_search_results(search_results, keyword, year)
                search_results = sorted(search_results, key=lambda x:x.get('score', 0), reverse=True)
                ret = {'ret': 'success', 'data': search_results[0]}
            else:
                ret = {'ret': 'empty'}
        except Exception as e:
            logger.exception(f"검색에 실패했습니다: {keyword=}")
            ret = {'ret': 'exception', 'data': repr(e)}
        caching(lambda: ret, cache_key, cls.cache_expiry, cls.cache_enable)()
        return ret

    @classmethod
    def info(cls, code: str, title: str = '') -> dict[str, str | dict]:
        logger.debug(f"Daum TV info: {code=} {title=}")
        cache_key = f"daum:tv:info:{code[2:]}"
        try:
            if cached :=caching(lambda: None, cache_key, cache_enable=cls.cache_enable, print_log=True)():
                return cached
            # request
            query = cls.get_request_query(q=title if title else 'TV', spId=code[2:])
            html = cls.get_tree(cls.get_request_url(query=query))
            if results := cls.get_shows(html, mode='info'):
                ret = {'ret': 'success', 'data': results[0]}
            else:
                ret = {'ret': 'empty'}
        except Exception as e:
            logger.exception(f"정보 탐색에 실패했습니다: {code=} {title=}")
            ret = {'ret': 'exception', 'data': repr(e)}
        caching(lambda: ret, cache_key, cls.cache_expiry, cls.cache_enable)()
        return ret

    @classmethod
    def get_shows(cls, html: HtmlElement, mode: str = "search") -> tuple:
        container = html.find(".//div[@id='tvpColl']")
        if container is None:
            logger.debug("TV 쇼 컨테이너를 찾지 못 했습니다.")
            return ()

        # 정보, 출연/제작, 영상, 포토, 시리즈
        card_tab = cls.parse_card_tab(container)

        # code, title, link
        card_title = cls.parse_card_title(container)
        if not (card_title.get('code') and card_title.get('title')):
            logger.debug("TV 쇼의 제목과 코드를 찾지 못 했습니다.")
            return ()
        sjva_code = cls.module_char + cls.site_char + card_title.get('code')

        # poster, description, premiered, countries, genres, runtime, mpaa, ratings, customer
        card_info = cls.parse_card_section_info(container)

        # 부제목 정보
        sub_title_info = cls.parse_sub_title(container)

        # 최신 회차
        episode = 0
        if (broadcast_info := sub_title_info.get('broadcast_info')) and "부작" in broadcast_info:
            try:
                episode = int(broadcast_info.split("부작")[0])
            except Exception:
                pass
        if episode < 1 and (shortcuts := cls.parse_shortcuts(container)):
            episode = shortcuts.get('episode') or 0

        error_info = f"code='{card_title.get('code')}' title='{card_title.get('title')}'"

        if mode == 'search':
            entity = EntitySearchItemTvDaum(cls.site_name)

            # same titles
            try:
                entity.equal_name = cls.parse_same_title(container)
            except Exception:
                logger.exception(f"동명 프로그램을 검색하는 도중 오류가 발생했습니다: {error_info}")

            # series
            if card_tab.get('시리즈'):
                try:
                    series_html = cls.get_tree(card_tab.get('시리즈'))
                    entity.series = cls.parse_series(series_html, card_title.get('code'))
                except Exception:
                    logger.exception(f"시리즈를 검색하는 도중 오류가 발생했습니다: {error_info}")

            entity.broadcast_info = sub_title_info.get('broadcast_info') + ", " + (card_info.get('편성') or "") if sub_title_info.get('broadcast_info') else card_info.get('편성') or ""
            entity.broadcast_term = sub_title_info.get('broadcast_term')
            entity.genre = sub_title_info.get('genre')
            """
            search()의 extra_info는 str 타입이어야 함
                File "/config/Library/Application Support/Plex Media Server/Plug-ins/SjvaAgent.bundle/Contents/Code/module_ktv.py", line 143, in search
                tmp = tmp + u'방송종료'
            TypeError: unsupported operand type(s) for +: 'dict' and 'str'
            """
            entity.extra_info = f'Daum {entity.studio}'
            entity.desc = card_info.get('소개') or ""
            entity.image_url = card_info.get('image') or card_info.get('thumb') or ""
        else:
            entity = EntityShow(cls.site_name, sjva_code)

            # 최신 영상
            entity.extras = cls.parse_recent_clips(container)

            # 출연진/제작진
            try:
                if card_tab.get('출연'):
                    people_html = cls.get_tree(card_tab.get('출연'))
                    entity.actor = cls.parse_show_people(people_html)
            except Exception:
                logger.exception(f"인물 정보를 검색하는 도중 오류가 발생했습니다: {error_info}")

            # 회차
            try:
                if card_tab.get('회차'):
                    epno_html = cls.get_tree(card_tab.get('회차'))
                    entity.extra_info['episodes'] = cls.parse_episodes(epno_html, card_title.get('code'), card_title.get('title'))
                else:
                    logger.debug(f'Daum 에피소드 정보가 없습니다: {error_info}')
            except Exception:
                logger.exception(f"회차 정보를 검색하는 도중 오류가 발생했습니다: {error_info}")

            # 시청률
            try:
                if card_tab.get('시청률'):
                    rating_html = cls.get_tree(card_tab.get('시청률'))
                    # 시청률 정보에서 방송일 수집
                    cls.parse_ratings(rating_html, entity.extra_info['episodes'])
            except Exception:
                logger.exception(f"시청률 정보를 검색하는 도중 오류가 발생했습니다: {error_info}")

            # 감상하기
            try:
                if card_tab.get('감상하기'):
                    ott_html = cls.get_tree(card_tab.get('감상하기'))
                    entity.extra_info.update(cls.parse_otts(ott_html))
            except Exception:
                logger.exception(f"감상하기 정보를 검색하는 도중 오류가 발생했습니다: {error_info}")

            query = cls.get_request_query(q=card_title.get('title'), spId=card_title.get('code'))
            entity.home = cls.get_request_url(query=query)
            entity.genre = [sub_title_info.get('genre')]
            entity.originaltitle = entity.sorttitle = card_title.get('title')
            entity.plot = card_info.get('소개') or ""
            entity.thumb.append(EntityThumb(aspect='poster', value=card_info.get('image') or '', thumb=card_info.get('thumb') or "", site=cls.site_name, score=100))
            '''
            metadata/mod_ktv.py:
                show['extras'] = SiteDaumTv.get_kakao_video(show['extra_info']['kakao_id'])
                show['extra_info']['tving_episode_id']
            '''
            # show.extras 에 최신 영상 넣었음
            entity.extra_info['kakao_id'] = None
            #show['extra_info']['tving_episode_id']

        # common fields
        entity.code = sjva_code
        entity.title = card_title.get('title')
        entity.studio = card_info.get('studio') or ""
        entity.status = sub_title_info.get('status')
        entity.year = sub_title_info.get('year')
        entity.premiered = sub_title_info.get('premiered')
        entity.episode = episode

        return (entity.as_dict(),)

    @classmethod
    def episode_info(cls, episode_code: str, include_kakao: bool = False, is_ktv: bool = True, summary_duplicate_remove: bool = False) -> dict[str, str | dict]:
        """
        2025.11.12 halfaider
        에피소드 code 형식 (quote로 변환되지 않고 base64에서 쓰지 않는 글자: .)

        KD1234.런닝맨.1 : 실제 에피소드 id
        KD4321..런닝맨..2 : 쇼 id, 쇼 제목, 회차
        """
        cache_key = f"daum:tv:episode:{episode_code}"
        if cached := caching(lambda: None, cache_key, cache_enable=cls.cache_enable)():
            return cached
        ret = {'ret': 'success'}
        try:
            episode_url = cls.get_episode_url(episode_code)
            root = SiteDaum.get_tree(episode_url)
            entity = EntityEpisode(cls.site_name, episode_code)
        except Exception as e:
            logger.exception(f"에피소드 탐색에 실패했습니다: {episode_code=}")
            ret['ret'] = 'exception'
            ret['data'] = repr(e)
            return ret

        no_result_elements = root.xpath('//*[@id="noResult"]')
        if no_result_elements:
            message = no_result_elements[0].xpath('string(.//p[@class="desc_info"])').strip()
            tmp = [w.strip() for w in message.split()]
            ret['ret'] = 'exception'
            ret['data'] = ' '.join(tmp)
            return ret

        container = root.find(".//div[@id='tvpColl']")
        if container is None:
            msg = f"TV 쇼 컨테이너를 찾지 못 했습니다: {episode_url}"
            logger.error(msg)
            ret['ret'] = 'exception'
            ret['data'] = msg
            return ret

        # 프로그램 제목, 코드
        card_title = cls.parse_card_title(container)
        if not (card_title.get('code') and card_title.get('title')):
            msg = f"TV 쇼의 제목과 코드를 찾지 못 했습니다: {episode_url}"
            logger.error(msg)
            ret['ret'] = 'exception'
            ret['data'] = msg
            return ret
        entity.showtitle = card_title.get('title')

        # 에피소드 코드가 없어서 프로그램 코드로 요청한 경우 체크
        if '#' in episode_code:
            code, _ = episode_code.split('#')
            if card_title.get('code') != code[2:]:
                msg = f"검색된 에피소드가 요청한 에피소드와 일치하지 않습니다: {episode_url}"
                logger.error(msg)
                ret['ret'] = 'exception'
                ret['data'] = msg
                return ret

        # 회차
        entity.episode, episode_in_title = cls.parse_episode_number(container)

        # 방영일
        entity.premiered, entity.year, date_in_title = cls.parse_episode_date(container, card_title.get('code'), entity.episode)

        # 에피소드 제목
        entity.title = f'{date_in_title} {episode_in_title}'.strip()
        strong_titles = container.xpath('.//strong[@class="tit_story"]')
        if strong_titles and strong_titles[0].text:
            entity.originaltitle = strong_titles[0].text.strip()
            entity.title = f'{entity.title} {entity.originaltitle}' if is_ktv else entity.originaltitle

        # 줄거리
        if not summary_duplicate_remove:
            entity.plot = entity.title
        plot_text = container.xpath('.//p[@class="desc_story"]/text()')
        if plot_text:
            if summary_duplicate_remove:
                entity.plot = plot_text[0].strip()
            else:
                entity.plot += f'\n\n{plot_text[0].strip()}'

        # 관련 영상
        if related_video_elements := container.xpath('.//div[@id="episode-play"]/following-sibling::div[1]'):
            clips = cls.parse_clips(related_video_elements[0])
            if include_kakao and clips:
                entity.extras.extend(clips)
            for clip in clips:
                if '예고' in clip.title:
                    continue
                if clip.thumb:
                    entity.thumb.append(EntityThumb(aspect='landscape', thumb=clip.thumb, site=cls.site_name, score=100))

        # 썸네일, 관련 영상의 썸네일을 먼저 사용하고 없을 경우 사용
        epi_thumbs = container.xpath('.//div[@class="player_sch"]//a[@class="thumb_bf"]/img')
        if epi_thumbs and not entity.thumb:
            entity.thumb.append(EntityThumb(aspect='landscape', value=cls.process_image_url(epi_thumbs[0]), site=cls.site_name, score=80))

        ret['data'] = entity.as_dict()
        return caching(lambda: ret, cache_key, cls.cache_expiry, cls.cache_enable)()

    @classmethod
    def get_actor_eng_name(cls, name: str) -> str | None:
        try:
            query = {
                'w': 'tot',
                'q': name
            }
            root = SiteDaum.get_tree(cls.get_request_url(query=query))
            name_elements = root.xpath('//*[@id="prfColl"]//c-combo[@data-type="info"]//c-frag[@data-divider]')
            name_text = name_elements[0].text.strip() if name_elements else name
            try:
                name_text.encode('ascii')
                return name_text
            except UnicodeEncodeError:
                #logger.warning(f'Is it English? {name_text}')
                return
        except Exception:
            logger.exception(f"{name=}")

    @classmethod
    def parse_episode_list(cls, episode_root: HtmlElement, bucket: dict, show_id: str, show_title: str) -> tuple[int, str]:
        # 회차정보 페이지에서 최신 회차의 방영일 저장
        current_ep_premiered = None
        date_text = episode_root.xpath('.//span[contains(text(), "방영일")]/following-sibling::text()')
        if date_text:
            date: datetime = cls.parse_date_text(' '.join(date_text).strip())
            current_ep_premiered = date.strftime('%Y-%m-%d') if date else ' '.join(date_text).strip()

        episode_elements = episode_root.xpath('.//q-select/option')
        last_ep_no = -1
        last_ep_url = ''
        selected_idx = -1
        current_episodes = []
        for element in episode_elements:
            try:
                ep_text = element.attrib['value'].strip().replace('회', '')
                ep_id = element.attrib['data-sp-id'].strip()
                ep_no_date = None
                if ep_text.isdigit():
                    ep_no = last_ep_no = int(ep_text)
                else:
                    ep_no_date = cls.parse_date_text(ep_text)
                    ep_no = last_ep_no = int(ep_no_date.strftime('%Y%m%d'))
                if ep_no in bucket:
                    continue
                if 'selected' in element.attrib:
                    selected_idx = ep_no
                if ep_no_date:
                    q_ = f'{show_title} {ep_no_date.strftime("%Y.%m.%d.")}'
                    premiered = ep_no_date.strftime("%Y-%m-%d")
                else:
                    q_ = f'{show_title} {ep_no}회'
                    if current_ep_premiered and ep_no == selected_idx:
                        premiered = current_ep_premiered
                    else:
                        cache_key = f"daum:tv:show:{show_id}:episodes:{ep_no}:premiered"
                        cached = caching(lambda: None, cache_key, cache_enable=cls.cache_enable)()
                        premiered = cached or 'unknown'
                # 첫 페이지에 노출되는 에피소드 목록
                query = cls.get_request_query(q=q_, coll='tv-episode', spt='tv-episode', spId=ep_id)
                last_ep_url = cls.get_request_url(query=query)
                """
                2025.11.12 halfaider

                KD4321.런닝맨.1 : 실제 에피소드 id
                KD4321..런닝맨..2 : 쇼 id, 쇼 제목, 회차

                dict의 키 값으로 int와 str을 섞어 쓰면 flask에서 jsonify할 때 오류 발생
                """
                bucket[ep_no] = {
                    'daum': {
                        # 실제 에피소드 id
                        'code': cls.module_char + cls.site_char + str(ep_id) + '.' + encode_base64(show_title) + '.' + str(ep_no),
                        'premiered': premiered,
                    }
                }
                current_episodes.append(ep_no)
            except Exception as e:
                logger.warning(repr(e))
        if current_episodes:
            logger.debug(f'The episode numbers of "{show_title}" : {current_episodes}')
        return last_ep_no, last_ep_url

    @classmethod
    def parse_additional_shows(cls, html: HtmlElement) -> list[dict]:
        """
        동명프로그램, 시리즈
        """
        additionals = []
        for item_thumb_tag in html.xpath(".//ul/li//div[@class='item-thumb']"):
            code = title = thumb = year = link = studio = date = None
            data = cls.parse_thumb_and_bundle(item_thumb_tag)
            if not data or not (query := data.get('query')) or not query.get("spId"):
                continue
            try:
                if query.get("spId"):
                    code = cls.module_char + cls.site_char + query.get('spId')
                if query.get("q"):
                    title = query.get("q")
                    query['w'] = 'tv'
                    link = cls.get_request_url(query=query)
                if data.get('thumb'):
                    thumb = data.get('thumb')
                if data.get('descs'):
                    studio = data.get('descs').get('studio')
                    if data.get('편성'):
                        schedule_text = data.get('편성')
                        year_text = re.sub("\D", "", schedule_text)
                        if year_text:
                            year = int(year_text)
                else:
                    for text in data.get('labels') or ():
                        date_time = cls.parse_date_text(text)
                        if date_time:
                            date = date_time.strftime("%Y-%m-%d")
                            year = date_time.year
                            break
                additionals.append({
                   "code": code,
                   "title": title,
                   "year": year or 1900,
                   "thumb": thumb or "",
                   "studio": studio or "",
                   "link": link or "",
                   "status": -1,
                   "date": date or "",
                   "spId": int(query["spId"]),
                })
            except Exception:
                logger.exception(f"Failed to search more show...")
        # sjva 에이전트에서 출시일 순(마지막을 최근 시즌으로)으로 인식
        try:
            return sorted(additionals, key=lambda x: (x['year'], x['spId']))
        except Exception:
            logger.exception(f"시리즈 정렬 실패")
            return additionals

    @classmethod
    def parse_sub_title(cls, container: HtmlElement) -> dict:
        """
        중국드라마 | 50부작 | 10.06.24. ~ 10. | 완결
        예능 | 10.07.11. ~
        영국드라마 | 10부작 | 24.11.15. ~
        뉴스 | 70.10.05. ~
        12부작 | 25.01.06. ~ 02.11. | 완결
        18.11.24. ~
        드라마 | 1부작 | 21.07.23. | 완결
        """
        status = 1
        year = 1900
        broadcast_info = broadcast_term = premiered = genre = ''
        for txt_info in container.xpath(".//div[@class='sub_header']/span/span[@class='txt_info']"):
            text = txt_info.xpath("normalize-space(string(.))")
            if not text:
                continue
            # 0: 방송예정, 1: 방송중, 2: 방송종료
            if any(word in text for word in ("종료", "완결")):
                status = 2
            elif any(word in text for word in ("예정",)):
                status = 0
            # 부작
            elif re.fullmatch(r"\d+\s*부작", text):
                # broadcast_info?
                broadcast_info = text
            else:
                parts = tuple(part.strip() for part in text.rsplit("~", 1) if part)
                # 방영일
                premiered_datetime: datetime | None = cls.parse_date_text(parts[0])
                if premiered_datetime:
                    broadcast_term = "~".join(parts)
                    year = premiered_datetime.year
                    premiered = premiered_datetime.strftime("%Y-%m-%d")
                else:
                    # 나머지 장르 취급
                    genre = text
        return {
            'status': status,
            'year': year,
            'broadcast_info': broadcast_info,
            'broadcast_term': broadcast_term,
            'premiered': premiered,
            'genre': genre,
        }

    @classmethod
    def parse_same_title(cls, container: HtmlElement) -> list[dict]:
        same_title_xpaths = (
            ".//strong[@class='screen_out' and contains(text(), '동명프로그램')]/following-sibling::div",
            ".//div[contains(@class, 'c-header') and .//*[contains(text(), '동명프로그램')]]/following-sibling::div[contains(@class, 'bundle_basic')]",
        )
        for same_xpath in same_title_xpaths:
            if not (div_tags := container.xpath(same_xpath)):
                continue
            return cls.parse_additional_shows(div_tags[0])
        else:
            return []

    @classmethod
    def parse_series(cls, container: HtmlElement, spid: str) -> list[dict]:
        if (series_container := container.xpath(".//div[@id='tvpColl']//strong[contains(text(), '시리즈')]/following-sibling::div")):
            #return [show for show in cls.parse_additional_shows(series_container[0]) if show.get('spId') != spid]
            # 검색 결과에 본편을 제외하면 플렉스에서 매칭할 때 본편이 제외됨(series 필드가 있으면 그 값만 참조하는 것 같음)
            return cls.parse_additional_shows(series_container[0])
        else:
            return []

    @classmethod
    def parse_recent_clips(cls, container: HtmlElement) -> list[EntityExtra]:
        if (recent_video_contaier := container.xpath('.//strong[contains(text(), "최신영상")]/../following-sibling::div[1]')):
            return cls.parse_clips(recent_video_contaier[0])
        return []

    @classmethod
    def parse_show_people(cls, container: HtmlElement) -> list[EntityActor]:
        actors = []
        if cast_containers := container.xpath(".//div[@id='tvpColl']//div[contains(@class, 'cont_cast')]"):
            people = cls.parse_people(cast_containers[0])
            order_actor = 0
            for person in people:
                actor_or_staff = EntityActor('', site=cls.site_name)
                actor_or_staff.name = person.get('name')
                actor_or_staff.order = order_actor
                order_actor += 1
                actor_or_staff.role = person.get('role') or ''
                actor_or_staff.thumb = person.get('thumb') or ''
                match person.get('category'):
                    case '출연':
                        actor_or_staff.type = 'actor'
                        actors.append(actor_or_staff)
                    case '제작':
                        actor_or_staff.type = 'staff'
                        actors.append(actor_or_staff)
                    case _:
                        actor_or_staff.type = 'staff'
                        actors.append(actor_or_staff)
        return actors

    @classmethod
    def parse_episodes(cls, container: HtmlElement, spid: str, title: str) -> dict:
        '''
        회차 페이지의 회차 목록은 49개씩 최대 98(이전+다음)개를 보여줌
        최신 회차가 2000일 경우 모든 회차 목록을 확인하려면 41번 요청해야함
            - 번호형 회차: 최신 회차 번호를 기준으로 나머지 회차를 유추
                - 가끔 회차 번호가 날짜로 되어 있는 경우가 있는데 이런 케이스는 포기
            - 날짜형 회차: 가능한 회차 목록을 모두 수집
                - 날짜 회차 형식은 spId 필요
        '''
        cache_key = f"daum:tv:show:{spid}:episodes"
        if cached := caching(lambda: None, cache_key, cache_enable=cls.cache_enable)():
            return cached
        episodes = {}
        # 첫번째 페이지의 회차 목록
        last_ep_no, last_ep_url = cls.parse_episode_list(container, episodes, spid, title)
        first_page_episodes = sorted(episodes.keys())
        is_number = (sum(x < 19000101 for x in first_page_episodes)) >= len(first_page_episodes) / 2
        if is_number:
            # 번호형 회차
            if last_ep_no > 19000101:
                # 마지막 회차가 날짜형이면 그 전의 번호형으로 대체
                for num in first_page_episodes[::-1]:
                    if num < 19000101:
                        last_ep_no = num
                        last_ep_url = cls.get_episode_url(episodes[num]['daum']['code'])
                        break
            for idx in range(last_ep_no - 1, 0, -1):
                """
                2025.11.12 halfaider
                첫 페이지 이후의 에피소드 목록
                에피소드 id를 모른 채로 쇼 id, 제목, 회차에 의존해서 code를 구성
                쇼 id로 검색된 에피소드의 쇼 id와 비교
                동명 프로그램이 있을 경우 키워드 검색만으로 목표 에피소드를 찾지 못할 수 있음

                KD4321.런닝맨.1 : 실제 에피소드 id
                KD4321..런닝맨..2 : 쇼 id, 쇼 제목, 회차
                """
                cached = caching(lambda: None, f"daum:tv:show:{spid}:episodes:{idx}:premiered", cache_enable=cls.cache_enable)()
                episodes[idx] = {
                    'daum': {
                        # 가상의 에피소드 id
                        'code': cls.module_char + cls.site_char + str(spid) + '..' + encode_base64(title) + '..' + str(idx),
                        'premiered': cached or 'unknown',
                    }
                }
        else:
            '''
            날짜형 회차

            무엇이든 물어보세요
            2025.01.20.
            2025.01.21.

            모든 회차, 회차 목록 페이지 접속 횟수 100회 제한
            '''
            for _ in range(100):
                try:
                    next_epno_page = SiteDaum.get_tree(last_ep_url)
                    page_last_episode_no, page_last_episode_url = cls.parse_episode_list(next_epno_page, episodes, spid, title)
                    if last_ep_no == page_last_episode_no or last_ep_url == page_last_episode_url:
                        logger.debug(f'No more episode information after: {page_last_episode_no}')
                        break
                    last_ep_no = page_last_episode_no
                    last_ep_url = page_last_episode_url
                except Exception:
                    logger.exception(f"code='{spid}' title='{title}'")
        return caching(lambda: episodes, cache_key, cls.cache_expiry, cls.cache_enable)()

    @classmethod
    def parse_ratings(cls, container: HtmlElement, episodes: dict) -> None:
        tr_elements = container.xpath('.//*[@id="tvpRatings"]//tbody/tr')
        for tr in tr_elements:
            premiered = tr.xpath('./td[1]')[0].text.strip()
            index = tr.xpath('string(./td[2])').replace('회', '').strip()
            match = re.compile('(\d{2,4}\.\d{1,2}\.\d{1,2})(.+)?').search(premiered)
            if match:
                premiered = match.group(1)
            if index and premiered:
                try:
                    index = int(index)
                    premiered = cls.parse_date_text(premiered)
                    episodes[index]['daum']['premiered'] = premiered.strftime('%Y-%m-%d')
                except Exception:
                    pass
                    #logger.exception(f"{index=} {premiered=}")

    @classmethod
    def parse_otts(cls, container: HtmlElement) -> dict:
        otts = {}
        ott_elements = container.xpath('.//*[@id="tvpColl"]//ul[@class="list_watch"]/li/a')
        for element in ott_elements:
            '''
            "https://www.wavve.com/player/vod?history=season&programid=S01_V0000330171 "
            "http://www.tving.com/vod/player/E001412821 "
            "https://www.netflix.com/kr/title/81979683 "
            "https://www.coupangplay.com/content/35999344-3bc0-40f2-809f-da76a2e5008f "
            "https://watcha.com/contents/tEZA4O9 "
            '''
            if element.get('href') is None:
                continue
            try:
                url = urllib.parse.urlparse(element.get('href'))
                content_id = element.get('href').strip().rsplit('/')[-1]
                if 'tving' in url.netloc:
                    otts['tving_id'] = content_id
                elif 'netflix' in url.netloc:
                    otts['netflix_id'] = content_id
                elif 'coupang' in url.netloc:
                    otts['coupang_id'] = content_id
                elif 'watcha' in url.netloc:
                    otts['watcha_id'] = content_id
                elif 'wavve' in url.netloc:
                    query = dict(urllib.parse.parse_qsl(url.query))
                    if wavve_id := query.get('programid'):
                        otts['wavve_id'] = wavve_id
            except Exception:
                logger.exception(etree.tostring(element, encoding='unicode'))
        return otts

    @classmethod
    def parse_episode_number(cls, container: HtmlElement) -> tuple[int, str]:
        episode = 0
        episode_text = None
        episode_in_title = ''
        for element in container.xpath('.//q-select/option'):
            if 'selected' in element.attrib:
                episode_text = element.attrib['value'].strip()
                break
        episode_info_text = container.xpath('.//span[contains(text(), "회차")]/following-sibling::text()')
        if episode_info_text:
            text = ' '.join(episode_info_text).strip()
            if '마지막' in text:
                episode_in_title = '[마지막회]'
            elif not episode_text:
                episode_text = text
        if episode_text:
            num_text = episode_text.replace('회', '').strip()
            if num_text.isdigit():
                episode = int(num_text)
            else:
                try:
                    date: datetime = cls.parse_date_text(num_text)
                    episode = int(date.strftime('%Y%m%d')) * -1
                except Exception as e:
                    logger.warning(repr(e))
        return episode, episode_in_title

    @classmethod
    def parse_episode_date(cls, container: HtmlElement, show_id: str, episode_index: int) -> tuple[str, int, str]:
        date_in_title = premiered = year = ''
        if not (date_text := container.xpath('//span[contains(text(), "방영일")]/following-sibling::text()')):
            return premiered, year, date_in_title
        date_text = ' '.join(date_text).strip()
        try:
            date: datetime = cls.parse_date_text(date_text)
            premiered = date.strftime('%Y-%m-%d') if date else date_text
            caching(lambda: premiered, f"daum:tv:show:{show_id}:episodes:{str(episode_index)}:premiered", cls.cache_expiry, cls.cache_enable)()
            year = date.year if date else 1900
            weekday = cls.weekdays[date.weekday()] if date else None
            title_date = date.strftime("%Y.%m.%d.") if date else date_text
            date_in_title = f'{title_date}({weekday})' if weekday else title_date
        except Exception:
            logger.exception(f"{show_id=} {episode_index=}")
        return premiered, year, date_in_title

    @classmethod
    def parse_shortcuts(cls, container: HtmlElement) -> dict:
        shortcuts = {}
        if not (li_tags := container.xpath(".//strong[contains(text(), 'Shortcut')]/following-sibling::ul/li")):
            return shortcuts
        for li_tag in li_tags:
            try:
                title = li_tag.get('class')
                match title:
                    case "ratings":
                        for text in cls.iter_text(li_tag):
                            if '회' in text:
                                shortcuts['episode'] = int(text.split('회')[0])
            except Exception:
                logger.exception(f"Shortcut 정보를 검색하는 도중 오류가 발생했습니다.")
        return shortcuts

    @classmethod
    def get_episode_url(cls, episode_code: str) -> str:
        code, title, index = cls.parse_episode_code(episode_code)
        query = cls.get_request_query(coll='tv-episode', spt='tv-episode')
        if '..' not in episode_code:
            # 실제 에피소드 id
            query['spId'] = code[2:]
        match isinstance(index, int), index:
            case True, index if index < 19000101:
                keyword = f"{index}회"
            case True, _:
                try:
                    keyword = datetime.strptime(str(index), "%Y%m%d").strftime("%Y.%m.%d.")
                except Exception:
                    logger.exception(f"에피소드 날짜 형식이 잘못되었습니다: {index=}")
                    keyword = index
            case _:
                keyword = ''
        match bool(query.get('spId')), bool(title), bool(keyword):
            case True, False, False:
                keyword = "회차 정보"
            case (True, _, _) | (False, True, True):
                keyword = " ".join((text for text in (title, keyword) if text))
            case _:
                # 에피소드 id가 없을 경우 제목과 회차 둘 다 필요
                raise Exception(f"에피소드 id가 없을 경우 제목과 회차 둘 다 필요 합니다: {episode_code=}")
        query['q'] = keyword
        return cls.get_request_url(query=query)

    @classmethod
    def parse_episode_code(cls, episode_code: str) -> tuple[str, str, int | str]:
        code = title = index = ''
        for idx, part in enumerate(re.split(r'\.+', episode_code)):
            match idx:
                case 0:
                    code = part
                case 1:
                    title = decode_base64(part)
                case 2:
                    try:
                        index = int(part)
                    except Exception:
                        index = part
        return code, title, index
