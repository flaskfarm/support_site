import urllib.parse
from datetime import datetime

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
    def get_search_name_from_original(cls, search_name):
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
    def search(cls, keyword, daum_id=None, year=None, image_mode='0'):
        try:
            keyword = keyword.replace(' | 시리즈', '').strip()
            keyword = cls.get_search_name_from_original(keyword)
            ret = {}

            query = cls.get_default_tv_query()
            query['q'] = keyword
            if daum_id:
                query['spId'] = daum_id
            url = cls.get_request_url(query=query)

            root = SiteDaum.get_tree(url)
            data = cls.get_show_info_on_home(root)

            if data is not None and data['code'] in ['KD58568']:
                data = None
            if data is None:
                ret['ret'] = 'empty'
            else:
                ret['ret'] = 'success'
                ret['data'] = data
        except Exception as e:
            logger.error(f"Exception:{str(e)}")
            logger.error(traceback.format_exc())
            ret['ret'] = 'exception'
            ret['data'] = str(e)
        return ret

    @classmethod
    def info(cls, code, title):
        try:
            logger.debug(f"{code} - {title}")
            if title == '모델': title = '드라마 모델'
            ret = {}
            show = EntityShow(cls.site_name, code)
            query = cls.get_default_tv_query()
            query['q'] = title
            query['spId'] = code[2:]
            url = cls.get_request_url(query=query)
            show.home = url
            root = SiteDaum.get_tree(url)

            home_data = cls.get_show_info_on_home(root)
            if not home_data:
                return {'ret':'fail'}

            show.title = home_data['title']
            show.originaltitle = show.sorttitle = show.title

            show.studio = home_data.get('studio', '')
            show.plot = home_data['desc']

            term: datetime = cls.parse_date_text(home_data['broadcast_term'])
            if term:
                show.premiered = term.strftime('%Y-%m-%d') if term else home_data['broadcast_term']
                show.year = term.year if term else 1900

            show.status = home_data['status']
            show.genre = [home_data['genre']]
            show.episode = home_data['episode']

            # 포스터
            show.thumb.append(EntityThumb(aspect='poster', value=home_data['image_url'], site='daum', score=-10))

            # 최신영상
            recent_video_elements = root.xpath('//strong[contains(text(), "최신영상")]/../following-sibling::div[1]//ul/li')
            if recent_video_elements:
                show.extras.extend(cls.get_kakao_video_list(recent_video_elements))

            # 출연진/제작진
            actor_tab_element = None
            for element in root.xpath('//ul[@class="grid_xscroll"]/li/a'):
                if element.text and element.text.strip() == '출연':
                    actor_tab_element = element
                    break
            if actor_tab_element is not None:
                actor_tab_url = urllib.parse.urljoin(cls.get_request_url(), actor_tab_element.attrib['href'])
                actor_root = SiteDaum.get_tree(actor_tab_url)

                last_actor_order = 0
                actor_elements = actor_root.xpath('//div[@data-tab="출연"]//ul/li/div')
                for element in actor_elements:
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

                staff_elements = actor_root.xpath('//div[@data-tab="제작"]//ul/li/div')
                for element in staff_elements:
                    staff = EntityActor(None)
                    staff.type = 'staff'
                    actor.order = last_actor_order
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

            # 에피소드
            last_ep_no = -2
            last_ep_url = None
            for _ in range(100):
                if last_ep_url:
                    more_episode_root = SiteDaum.get_tree(last_ep_url)
                    tv_info_tab_elements = more_episode_root.xpath('//ul[@class="grid_xscroll"]/li/a')
                else:
                    tv_info_tab_elements = root.xpath('//ul[@class="grid_xscroll"]/li/a')

                epno_tab_element = None
                for element in tv_info_tab_elements:
                    if element.text and element.text.strip() == '회차':
                        epno_tab_element = element
                        break

                if epno_tab_element is None:
                    break

                epno_tab_url = urllib.parse.urljoin(cls.get_request_url(), epno_tab_element.attrib['href'])
                epno_root = SiteDaum.get_tree(epno_tab_url)
                episode_elements = epno_root.xpath('//q-select/option')
                current_ep_no, current_ep_url = cls.parse_episode_list(episode_elements, show.extra_info['episodes'], show.title)
                if last_ep_no == current_ep_no or last_ep_url == current_ep_url:
                    logger.debug(f'No more episode information after: {current_ep_no}')
                    break
                last_ep_no = current_ep_no
                last_ep_url = current_ep_url

            tags = root.xpath('//*[@id="tv_program"]//div[@class="clipList"]//div[@class="mg_expander"]/a')
            show.extra_info['kakao_id'] = None
            if tags:
                tmp = tags[0].attrib['href']
                show.extra_info['kakao_id'] = re.compile('/(?P<id>\d+)/').search(tmp).group('id')

            tags = root.xpath("//a[starts-with(@href, 'http://www.tving.com/vod/player')]")
            #tags = root.xpath('//a[@contains(@href, "tving.com")')
            if tags:
                show.extra_info['tving_episode_id'] = tags[0].attrib['href'].split('/')[-1]

            ret['ret'] = 'success'
            ret['data'] = show.as_dict()

        except Exception as e:
            logger.error(f"Exception:{str(e)}")
            logger.error(traceback.format_exc())
            ret['ret'] = 'exception'
            ret['data'] = str(e)
        return ret

    @classmethod
    def episode_info(cls, episode_code, include_kakao=False, is_ktv=True, summary_duplicate_remove=False):
        try:
            ret = {}
            episode_code = episode_code[2:]
            root = SiteDaum.get_tree(episode_code)

            entity = EntityEpisode(cls.site_name, episode_code)

            date_text = root.xpath('//span[contains(text(), "방영일")]/following-sibling::text()')
            if date_text:
                date: datetime = cls.parse_date_text(' '.join(date_text).strip())
                entity.premiered = date.strftime('%Y-%m-%d') if date else ' '.join(date_text).strip()
                entity.year = date.year if date else 1900
                weekday = cls.weekdays[date.weekday()]
                title_date = date.strftime("%Y.%m.%d")
                entity.title = f'{title_date}({weekday})' if weekday else title_date

            epno_text = root.xpath('//span[contains(text(), "회차")]/following-sibling::text()')
            if epno_text:
                text = ' '.join(epno_text).strip()
                epno = text.replace('회', '').strip()
                if epno.isdigit():
                    entity.episode = int(epno)
                else:
                    # 마지막회
                    entity.title += f' {text}'
            else:
                epno_elements = root.xpath('//q-select/option')
                for element in epno_elements:
                    if 'selected' in element.attrib:
                        try:
                            entity.episode = int(element.attrib['value'].strip().replace('회', ''))
                        except:
                            logger.error(traceback.format_exc())

            strong_titles = root.xpath('//div[@id="tvpColl"]//strong[@class="tit_story"]')
            if strong_titles and strong_titles[0].text:
                entity.originaltitle = strong_titles[0].text.strip()
                entity.title = f'{entity.title} {entity.originaltitle}' if is_ktv else entity.originaltitle

            show_title = root.xpath('//*[@id="tvpColl"]//div[@class="inner_header"]//a/text()')
            if show_title:
                entity.showtitle = show_title[0].strip()

            if not summary_duplicate_remove:
                entity.plot = entity.title
            plot_text = root.xpath('//p[@class="desc_story"]/text()')
            if plot_text:
                if summary_duplicate_remove:
                    entity.plot = plot_text[0].strip()
                else:
                    entity.plot += f'\n\n{plot_text[0].strip()}'

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

            related_video_elements = root.xpath('//div[@id="episode-play"]/following-sibling::div[1]//ul/li')
            if include_kakao and related_video_elements:
                entity.extras.extend(cls.get_kakao_video_list(related_video_elements))

            ret['ret'] = 'success'
            ret['data'] = entity.as_dict()
            #logger.debug(ret['data'])
        except Exception as e:
            logger.error(f"Exception:{str(e)}")
            logger.error(traceback.format_exc())
            ret['ret'] = 'exception'
            ret['data'] = str(e)
        return ret

    @classmethod
    def get_actor_eng_name(cls, name):
        try:
            ret = {}
            url = 'https://search.daum.net/search?w=tot&q=%s' % (name)
            root = SiteDaum.get_tree(url)

            for xpath in ['//*[@id="prfColl"]/div/div/div/div[2]/div[2]/div[1]/span[2]', '//*[@id="prfColl"]/div/div/div/div[2]/div/div/span[2]']:
                tags = root.xpath(xpath)
                if tags:
                    tmp = tags[0].text_content()
                    #logger.debug(tmp)
                    tmps = tmp.split(',')
                    if len(tmps) == 1:
                        ret = [tmps[0].strip()]
                    else:
                        ret = [x.strip() for x in tmps]
                    #일본배우땜에
                    ret2 = []
                    for x in ret:
                        ret2.append(x)
                        tmp = x.split(' ')
                        if len(tmp) == 2:
                            ret2.append('%s %s' % (tmp[1], tmp[0]))

                    return ret2
        except Exception as e:
            logger.error(f"Exception:{str(e)}")
            logger.error(traceback.format_exc())

    @classmethod
    def parse_episode_list(cls, episode_elements: list, episodes: dict, show_title: str) -> tuple[int, str]:
        last_ep_no = -1
        last_ep_url = ''
        episode_nums = []
        for element in episode_elements:

            ep_text = element.attrib['value'].strip().replace('회', '')

            if ep_text.isdigit():
                ep_no = last_ep_no = int(ep_text)
            else:
                delimiter = '-' if '-' in ep_text else '.'
                date_nums = [t.strip() for t in ep_text.split(delimiter) if t.strip().isdigit()]
                ep_no = last_ep_no = int(''.join(date_nums)) * -1

            if ep_no in episodes:
                continue

            try:
                ep_id = element.attrib['data-sp-id'].strip()
            except Exception as e:
                logger.warning(repr(e))
                continue

            query = cls.get_default_tv_query()
            query['q'] = f'{show_title} {ep_no}회'
            query['spId'] = ep_id
            query['coll'] = 'tv-episode'
            query['spt'] = 'tv-episode'
            url = last_ep_url = cls.get_request_url(query=query)
            episodes[ep_no] = {
                'daum': {
                    'code': cls.module_char + cls.site_char + url,
                    'premiered': 'unknown',
                }
            }
            #logger.debug(f'{ep_no}: {episodes[ep_no]}')
            episode_nums.append(ep_no)
        logger.debug(f'The episode numbers of "{show_title}" : {episode_nums}')
        return last_ep_no, last_ep_url

    @classmethod
    def get_default_tv_query(cls):
        return {
        'w': 'tv',
        'q': None,
        'coll': 'tv-main',
        'spt': 'tv-info',
        'DA': 'TVP',
        'rtmaxcoll': 'TVP'
    }

    @classmethod
    def get_request_url(cls, scheme: str = 'https', netloc: str = 'search.daum.net', path: str = 'search', params: dict = None, query: dict = None, fragment: str = None) -> str:
        return urllib.parse.urlunparse([scheme, netloc, path, urllib.parse.urlencode(params) if params else None, urllib.parse.urlencode(query) if query else None, fragment])

    @classmethod
    def get_kakao_video_list(cls, video_element_list: list) -> list:
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