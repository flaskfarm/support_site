import base64
import urllib.parse
from datetime import datetime

import lxml.html

from support.base.string import SupportString

from . import SiteDaum
from .entity_base import (EntityActor, EntityEpisode, EntityExtra, EntityShow,
                          EntityThumb)
from .setup import *


class SiteDaumTv(SiteDaum):

    site_base_url = 'https://search.daum.net'
    module_char = 'K'
    site_char = 'D'

    weekdays = {0: '월', 1: '화', 2: '수', 3: '목', 4: '금', 5: '토', 6: '일'}

    @classmethod
    def get_search_name_from_original(cls, search_name: str) -> str:
        search_name = search_name.replace('일일연속극', '').strip()
        search_name = search_name.replace('특별기획드라마', '').strip()
        search_name = re.sub(r'\[.*?\]', '', search_name).strip()
        search_name = search_name.replace(".", ' ')
        # 2020-10-10
        channel_list = ['채널 A', '채널A']
        for tmp in channel_list:
            if search_name.startswith(tmp):
                search_name = search_name.replace(tmp, '').strip()
        search_name = re.sub(r'^.{2,3}드라마', '', search_name).strip()
        #2019-08-01
        search_name = re.sub(r'^.{1,3}특집', '', search_name).strip()
        return search_name

    @classmethod
    def search(cls, keyword: str, daum_id: str | int = None, year: str | int = None, image_mode: str = '0') -> dict[str, str | dict]:
        try:
            keyword = keyword.replace(' | 시리즈', '').strip()
            logger.debug(f'Daum TV search: {keyword=} {year=}')
            ret = {}

            query = cls.get_default_tv_query(q=keyword, spId=daum_id)
            url = cls.get_request_url(query=query)

            root = SiteDaum.get_tree(url)
            data = cls.get_show_info_on_home(root)

            if not data:
                # 애플 오리지널 타이틀
                quotes = re.compile(r"'(.+?)'").findall(keyword)
                if quotes:
                    search_title = quotes[0]
                    retry_data = cls.search(search_title, daum_id, year, image_mode)
                    if retry_data['ret'] == 'success':
                        data = retry_data['data']
            if data is not None and data['code'] in ['KD58568']:
                data = None
            if data is None:
                ret['ret'] = 'empty'
            else:
                ret['ret'] = 'success'
                ret['data'] = data
        except Exception as e:
            logger.exception(f"{keyword=}")
            ret['ret'] = 'exception'
            ret['data'] = str(e)
        return ret

    @classmethod
    def info(cls, code: str, title: str) -> dict[str, str | dict]:
        ret = {'ret': 'success'}
        logger.debug(f"{code} - {title}")
        if title == '모델': title = '드라마 모델'
        show = EntityShow(cls.site_name, code)
        query = cls.get_default_tv_query(q=title, spId=code[2:])
        url = cls.get_request_url(query=query)
        show.home = url

        try:
            root = SiteDaum.get_tree(url)
        except Exception:
            logger.exception(f"{code=} {title=}")
            return {'ret':'fail'}

        home_data = cls.get_show_info_on_home(root)
        if not home_data:
            return {'ret':'fail'}

        show.title = home_data['title']
        show.originaltitle = show.sorttitle = show.title
        show.studio = home_data.get('studio', '')
        show.plot = home_data['desc']
        show.status = home_data['status']
        show.genre = [home_data['genre']]
        show.episode = home_data['episode']

        show.year = home_data.get('year') or ''
        show.premiered = home_data.get('premiered') or ''

        # 포스터
        show.thumb.append(EntityThumb(aspect='poster', value=home_data['image_url'], site='daum', score=-10))

        # 최신영상
        recent_video_elements = root.xpath('//strong[contains(text(), "최신영상")]/../following-sibling::div[1]//ul/li')
        if recent_video_elements:
            show.extras.extend(cls.get_kakao_video_list(recent_video_elements))

        # 출연진/제작진
        actor_root = cls.get_info_tab('출연', root)
        if actor_root is not None:
            last_actor_order = 0
            actor_elements = actor_root.xpath('//div[@data-tab="출연"]//ul/li/div')
            for element in actor_elements:
                try:
                    actor = EntityActor(None)
                    actor.type = 'actor'
                    actor.order = last_actor_order
                    last_actor_order += 1

                    title_elements = element.xpath('.//div[@class="item-title"]')
                    title_text = title_elements[0].text_content().strip()
                    '''
                    인물관계도      .item-title
                    (blank)        .item-contents
                    '''
                    if title_text == '인물관계도':
                        continue
                    '''
                    이지안 역       .item-title
                    이지은          .item-contents
                    '''
                    content_elements = element.xpath('.//div[@class="item-contents"]/p')
                    if content_elements:
                        actor.name = content_elements[0].text_content().strip()
                        actor.role = title_text.replace('역', '').strip()
                    '''
                    유재석          .item-title
                    출연            .item-contents
                    '''
                    content_elements = element.xpath('.//div[@class="item-contents"]/span')
                    if content_elements:
                        actor.name = title_text
                        actor.role = content_elements[0].text_content().strip()

                    cast_img_elements = element.xpath('.//img')
                    if cast_img_elements:
                        thumb_url = cls.process_image_url(cast_img_elements[0])
                        if urllib.parse.urlparse(thumb_url).scheme:
                            actor.thumb = thumb_url

                    #logger.debug(f'{actor.role=} {actor.name=} {actor.thumb=}')
                    show.actor.append(actor)
                except Exception:
                    logger.exception(f"{code=} {title=}")

            staff_elements = actor_root.xpath('//div[@data-tab="제작"]//ul/li/div')
            for element in staff_elements:
                try:
                    staff = EntityActor(None)
                    staff.type = 'staff'
                    staff.order = last_actor_order
                    last_actor_order += 1
                    '''
                    황동혁          .item-title
                    연출            .item-contents
                    '''
                    title_elements = element.xpath('.//div[@class="item-title"]')
                    title_text = title_elements[0].text_content().strip()

                    content_elements = element.xpath('.//div[@class="item-contents"]/span')
                    if content_elements:
                        staff.name = title_text
                        staff.role = content_elements[0].text_content().strip()
                    img_elements = element.xpath('.//img')
                    if img_elements:
                        thumb_url = cls.process_image_url(img_elements[0])
                        if urllib.parse.urlparse(thumb_url).scheme:
                            staff.thumb = thumb_url
                    #logger.debug(f'{staff.role=} {staff.name=} {staff.thumb=}')
                    show.actor.append(staff)
                except Exception:
                    logger.exception(f"{code=} {title=}")

        '''
        회차
        회차 페이지의 회차 목록은 49개씩 최대 98(이전+다음)개를 보여줌
        최신 회차가 2000일 경우 모든 회차 목록을 확인하려면 41번 요청해야함
            - 번호형 회차: 최신 회차 번호를 기준으로 나머지 회차를 유추
                - 가끔 회차 번호가 날짜로 되어 있는 경우가 있는데 이런 케이스는 포기
            - 날짜형 회차: 가능한 회차 목록을 모두 수집
                - 날짜 회차 형식은 spId 필요
        '''
        epno_root = cls.get_info_tab('회차', root)
        if epno_root is not None:
            # 첫번째 페이지의 회차 목록
            last_ep_no, last_ep_url = cls.parse_episode_list(epno_root, show.extra_info['episodes'], code[2:], show.title)
            first_page_episodes = sorted(show.extra_info['episodes'].keys())
            is_number = (sum(x < 19000101 for x in first_page_episodes)) >= len(first_page_episodes) / 2
            if is_number:
                # 번호형 회차
                if last_ep_no > 19000101:
                    for num in first_page_episodes[::-1]:
                        if num < 19000101:
                            last_ep_no = num
                            last_ep_url = show.extra_info['episodes'][num]['daum']['code'][2:]
                for idx in range(last_ep_no - 1, 0, -1):
                    query = cls.get_default_tv_query(coll='tv-episode', spt='tv-episode', q=f'{show.title} {idx}회')
                    url = cls.get_request_url(query=query)
                    episode_code = cls.module_char + cls.site_char + url
                    premiered = hget(f'{cls.REDIS_KEY_DAUM}:tv:show:{code[2:]}:episodes:{idx}', 'premiered') or 'unknown'
                    show.extra_info['episodes'][idx] = {
                        'daum': {
                            'code': episode_code,
                            'premiered': premiered,
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
                        page_last_episode_no, page_last_episode_url = cls.parse_episode_list(next_epno_page, show.extra_info['episodes'], code[2:], show.title)
                        if last_ep_no == page_last_episode_no or last_ep_url == page_last_episode_url:
                            logger.debug(f'No more episode information after: {page_last_episode_no}')
                            break
                        last_ep_no = page_last_episode_no
                        last_ep_url = page_last_episode_url
                    except Exception:
                        logger.exception(f"{code=} {title=}")
        else:
            logger.warning(f'No episodes infomation: {show.title}')

        # 시청률
        rating_root = cls.get_info_tab('시청률', root)
        if rating_root is not None:
            # 시청률 정보에서 방송일 수집
            tr_elements = rating_root.xpath('//*[@id="tvpRatings"]//tbody/tr')
            for tr in tr_elements:
                try:
                    premiered = tr.xpath('./td[1]')[0].text.strip()
                    index = tr.xpath('string(./td[2])').replace('회', '').strip()
                    match = re.compile('(\d{2,4}\.\d{1,2}\.\d{1,2})(.+)?').search(premiered)
                    if match:
                        premiered = match.group(1)
                    if index and premiered:
                        try:
                            index = int(index)
                            premiered = cls.parse_date_text(premiered)
                            show.extra_info['episodes'][index]['daum']['premiered'] = premiered.strftime('%Y-%m-%d')
                        except Exception:
                            pass
                except Exception:
                    logger.exception(f"{code=} {title=}")

        # 감상하기
        ott_root = cls.get_info_tab('감상하기', root)
        if ott_root is not None:
            ott_elements = ott_root.xpath('.//*[@id="tvpColl"]//ul[@class="list_watch"]/li/a')
            for e in ott_elements:
                '''
                "https://www.wavve.com/player/vod?history=season&programid=S01_V0000330171 "
                "http://www.tving.com/vod/player/E001412821 "
                "https://www.netflix.com/kr/title/81979683 "
                "https://www.coupangplay.com/content/35999344-3bc0-40f2-809f-da76a2e5008f "
                "https://watcha.com/contents/tEZA4O9 "
                '''
                try:
                    url = urllib.parse.urlparse(e.attrib['href'])
                    content_id = e.attrib['href'].strip().split('/')[-1]
                    if 'tving' in url.netloc:
                        show.extra_info['tving_id'] = content_id
                    elif 'netflix' in url.netloc:
                        show.extra_info['netflix_id'] = content_id
                    elif 'coupang' in url.netloc:
                        show.extra_info['coupang_id'] = content_id
                    elif 'watcha' in url.netloc:
                        show.extra_info['watcha_id'] = content_id
                    elif 'wavve' in url.netloc:
                        query = dict(urllib.parse.parse_qsl(url.query))
                        wavve_id = query.get('programid')
                        if wavve_id:
                            show.extra_info['wavve_id'] = wavve_id
                except Exception:
                    logger.exception(f"{code=} {title=}")

        '''
        metadata/mod_ktv.py:
            show['extras'] = SiteDaumTv.get_kakao_video(show['extra_info']['kakao_id'])
            show['extra_info']['tving_episode_id']
        '''
        # show.extras 에 최신 영상 넣었음
        show.extra_info['kakao_id'] = None
        #show['extra_info']['tving_episode_id']

        ret['data'] = show.as_dict()
        return ret

    @classmethod
    def episode_info(cls, episode_code: str, include_kakao: bool = False, is_ktv: bool = True, summary_duplicate_remove: bool = False) -> dict[str, str | dict]:
        ret = {'ret': 'success'}
        try:
            episode_url = episode_code[2:]
            root = SiteDaum.get_tree(episode_url)
            entity = EntityEpisode(cls.site_name, episode_url)
            query = dict(urllib.parse.parse_qsl(episode_url))
        except Exception as e:
            logger.exception(f"{episode_code=}")
            ret['ret'] = 'exception'
            ret['data'] = repr(e)
            return ret

        no_result_elements = root.xpath('//*[@id="noResult"]')
        if no_result_elements:
            message = no_result_elements[0].xpath('string(.//p[@class="desc_info"])').strip()
            tmp = [w.strip() for w in message.split()]
            raise Exception(' '.join(tmp))

        # 프로그램 제목
        show_id = -1
        show_title_elements = root.xpath('//*[@id="tvpColl"]//div[@class="inner_header"]//a')
        if show_title_elements:
            try:
                entity.showtitle = show_title_elements[0].text.strip()
                query = dict(urllib.parse.parse_qsl(show_title_elements[0].attrib['href']))
                show_id = query.get('spId')
            except Exception:
                logger.exception(f"{episode_code=}")

        # 회차
        entity.episode = -1
        episode_text = None
        episode_in_title = ''
        episode_elements = root.xpath('//q-select/option')
        for e in episode_elements:
            if 'selected' in e.attrib:
                episode_text = e.attrib['value'].strip()
                break
        episode_info_text = root.xpath('//span[contains(text(), "회차")]/following-sibling::text()')
        if episode_info_text:
            text = ' '.join(episode_info_text).strip()
            if '마지막' in text:
                episode_in_title = '[마지막회]'
            elif not episode_text:
                episode_text = text
        if episode_text:
            num_text = episode_text.replace('회', '').strip()
            if num_text.isdigit():
                entity.episode = int(num_text)
            else:
                try:
                    date: datetime = cls.parse_date_text(num_text)
                    entity.episode = int(date.strftime('%Y%m%d')) * -1
                except Exception as e:
                    logger.warning(repr(e))

        # 방영일
        date_in_title = ''
        date_text = root.xpath('//span[contains(text(), "방영일")]/following-sibling::text()')
        if date_text:
            try:
                date: datetime = cls.parse_date_text(' '.join(date_text).strip())
                entity.premiered = date.strftime('%Y-%m-%d') if date else ' '.join(date_text).strip()
                hset(f'{cls.REDIS_KEY_DAUM}:tv:show:{show_id}:episodes:{entity.episode}', 'premiered', entity.premiered)
                entity.year = date.year if date else 1900
                weekday = cls.weekdays[date.weekday()] if date else None
                title_date = date.strftime("%Y.%m.%d.") if date else ' '.join(date_text).strip()
                date_in_title = f'{title_date}({weekday})' if weekday else title_date
            except Exception:
                logger.exception(f"{episode_code=}")


        # 제목
        entity.title = f'{date_in_title} {episode_in_title}'.strip()
        strong_titles = root.xpath('//div[@id="tvpColl"]//strong[@class="tit_story"]')
        if strong_titles and strong_titles[0].text:
            entity.originaltitle = strong_titles[0].text.strip()
            entity.title = f'{entity.title} {entity.originaltitle}' if is_ktv else entity.originaltitle

        # 줄거리
        if not summary_duplicate_remove:
            entity.plot = entity.title
        plot_text = root.xpath('//p[@class="desc_story"]/text()')
        if plot_text:
            if summary_duplicate_remove:
                entity.plot = plot_text[0].strip()
            else:
                entity.plot += f'\n\n{plot_text[0].strip()}'

        # 썸네일
        epi_thumbs = root.xpath('//div[@id="tvpColl"]//div[@class="player_sch"]//a[@class="thumb_bf"]/img')
        if epi_thumbs:
            thumb_url = cls.process_image_url(epi_thumbs[0])
            entity.thumb.append(EntityThumb(aspect='landscape', value=thumb_url, site=cls.site_name, score=-10))
            '''
            if 'alt' in epi_thumbs[0].attrib and epi_thumbs[0].attrib['alt']:
                sub = re.compile('\[.+\]')
                tmp = epi_thumbs[0].attrib['alt'].split('|')
                tmp = sub.sub('', tmp[0]).strip()
                if tmp:
                    entity.title = tmp
            '''

        # 관련 영상
        related_video_elements = root.xpath('//div[@id="episode-play"]/following-sibling::div[1]//ul/li')
        if include_kakao and related_video_elements:
            entity.extras.extend(cls.get_kakao_video_list(related_video_elements))

        ret['data'] = entity.as_dict()
        #logger.debug(ret['data'])
        return ret

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
    def get_default_tv_query(cls, **kwds: dict) -> dict[str, str | None]:
        q_ = {
            'w': 'tv',
            'q': None,
            'coll': 'tv-main',
            'spt': 'tv-info',
            'DA': 'TVP',
            'rtmaxcoll': 'TVP'
        }
        for k in kwds:
            if kwds[k]:
                q_[k] = kwds[k]
        return q_

    @classmethod
    def get_kakao_video_list(cls, video_element_list: list[lxml.html.HtmlElement]) -> list[EntityExtra]:
        bucket = []
        for e in video_element_list:
            try:
                data_id = e.xpath('.//div[@data-id]')[0].attrib['data-id'].strip()
                '''
                metadata 플러그인에서 data_id만 입력받아 video_url을 따로 처리중

                video_url = cls.get_kakao_play_url2(data_id)
                if not video_url:
                    continue
                '''
                thumb_element = e.xpath('.//img')[0]
                thumb = cls.process_image_url(thumb_element)
                title_alt = thumb_element.attrib['alt'].strip() if 'alt' in thumb_element else ''
                title_text = e.xpath('.//div[@class="item-title"]//a/text()')[0].strip()
                title = title_text or title_alt
                title = SupportString.remove_emoji(title).strip()
                date_text = e.xpath('.//div[@class="item-contents"]//span/text()')[0].strip()
                date = cls.change_date(date_text)
                content_type = 'Featurette'
                if title.find(u'예고') != -1:
                    content_type = 'Trailer'
                # metadata 플러그인에서 video_url을 id만 받음
                extra = EntityExtra(content_type, title, 'kakao', data_id, premiered=date, thumb=thumb)
                bucket.append(extra)
                #logger.warning(extra.as_dict())
            except Exception as e:
                #logger.warning(repr(e))
                continue
        return bucket

    @classmethod
    def parse_episode_list(cls, episode_root: lxml.html.HtmlElement, bucket: dict, show_id: str, show_title: str) -> tuple[int, str]:
        # 회차정보 페이지에서 최신 회차의 방영일 저장
        current_ep_premiered = None
        date_text = episode_root.xpath('//span[contains(text(), "방영일")]/following-sibling::text()')
        if date_text:
            date: datetime = cls.parse_date_text(' '.join(date_text).strip())
            current_ep_premiered = date.strftime('%Y-%m-%d') if date else ' '.join(date_text).strip()

        episode_elements = episode_root.xpath('//q-select/option')
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
                        premiered = hget(f'{cls.REDIS_KEY_DAUM}:tv:show:{show_id}:episodes:{ep_id}', 'premiered') or 'unknown'
                query = cls.get_default_tv_query(q=q_, coll='tv-episode', spt='tv-episode', spId=ep_id)
                url = last_ep_url = cls.get_request_url(query=query)
                code = cls.module_char + cls.site_char + url
                bucket[ep_no] = {
                    'daum': {
                        'code': code,
                        'premiered': premiered,
                    }
                }
                #logger.debug(f'{ep_no}: {bucket[ep_no]}')
                current_episodes.append(ep_no)
            except Exception as e:
                logger.warning(repr(e))
        if current_episodes:
            logger.debug(f'The episode numbers of "{show_title}" : {current_episodes}')
        return last_ep_no, last_ep_url
