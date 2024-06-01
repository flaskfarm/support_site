import urllib.parse

from . import SiteDaum, SiteUtil
from .entity_base import (EntityActor, EntityEpisode, EntityExtra, EntityShow,
                          EntityThumb)
from .setup import *
from support.base.string import SupportString

class SiteDaumTv(SiteDaum):
    
    site_base_url = 'https://search.daum.net'
    module_char = 'K'
    site_char = 'D'

    
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
            if daum_id is None:
                url = 'https://search.daum.net/search?q=%s' % (urllib.parse.quote(str(keyword)))
            else:
                url = 'https://search.daum.net/search?q=%s&irk=%s&irt=tv-program&DA=TVP' % (urllib.parse.quote(str(keyword)), daum_id)

            root = SiteUtil.get_tree(url, proxy_url=cls._proxy_url, headers=cls.default_headers, cookies=cls._daum_cookie)
            data = cls.get_show_info_on_home(root)
            #data['link'] = 'https://search.daum.net/search?q=%s&irk=%s&irt=tv-program&DA=TVP' % (urllib.parse.quote(str(keyword)), daum_id)
            #logger.debug(data)
            # KD58568 : 비하인드 더 쇼
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
            if title  == '모델': title = '드라마 모델'
            ret = {}
            show = EntityShow(cls.site_name, code)
            # 종영와, 방송중이 표현 정보가 다르다. 종영은 studio가 없음
            url = 'https://search.daum.net/search?w=tv&q=%s&irk=%s&irt=tv-program&DA=TVP' % (urllib.parse.quote(str(title)), code[2:])
            show.home = url
            root = SiteUtil.get_tree(url, proxy_url=cls._proxy_url, headers=cls.default_headers, cookies=cls._daum_cookie)

            home_url = 'https://search.daum.net/search?q=%s&irk=%s&irt=tv-program&DA=TVP' % (urllib.parse.quote(str(title)), code[2:])
            
            #logger.debug(home_url)
            home_root = SiteUtil.get_tree(home_url, proxy_url=cls._proxy_url, headers=cls.default_headers, cookies=cls._daum_cookie)
            home_data = cls.get_show_info_on_home(home_root)

            #logger.debug('home_datahome_datahome_datahome_datahome_datahome_datahome_datahome_datahome_data')
            #logger.debug(home_data)

            tags = root.xpath('//*[@id="tv_program"]/div[1]/div[2]/strong')
            if len(tags) == 1:
                show.title = tags[0].text_content().strip()
                show.originaltitle = show.title
                show.sorttitle = show.title #unicodedata.normalize('NFKD', show.originaltitle)
                #logger.debug(show.sorttitle)
            """
            tags = root.xpath('//*[@id="tv_program"]/div[1]/div[3]/span')
            # 이 정보가 없다면 종영
            if tags:
                show.studio = tags[0].text_content().strip()
                summary = ''    
                for tag in tags:
                    entity.plot += tag.text.strip()
                    entity.plot += ' '
                match = re.compile(r'(\d{4}\.\d{1,2}\.\d{1,2})~').search(entity.plot)
                if match:
                    show.premiered = match.group(1)
            """
            show.studio = home_data['studio']
            show.plot = home_data['desc']
            match = re.compile(r'(?P<year>\d{4})\.(?P<month>\d{1,2})\.(?P<day>\d{1,2})').search(home_data['broadcast_term'])
            if match:
                show.premiered = match.group('year') + '-' + match.group('month').zfill(2) + '-'+ match.group('day').zfill(2)
                show.year = int(match.group('year'))
            try:
                if show.year == '' and home_data['year'] != 0:
                    show.year = home_data['year']
            except:
                pass
                
            
            show.status = home_data['status']
            show.genre = [home_data['genre']]
            show.episode = home_data['episode']

            tmp = root.xpath('//*[@id="tv_program"]/div[1]/div[1]/a/img')
            #logger.debug(tmp)

            try:
                # 2024-05-29 src => data-original-src
                show.thumb.append(EntityThumb(aspect='poster', value=cls.process_image_url(root.xpath('//*[@id="tv_program"]/div[1]/div[1]/a/img')[0].attrib['data-original-src']), site='daum', score=-10))
            except:
                pass


            if True: 
                tags = root.xpath('//ul[@class="col_size3 list_video"]/li')
                for idx, tag in enumerate(tags):
                    if idx > 9:
                        break
                    a_tags = tag.xpath('.//a')
                    if len(a_tags) == 2:
                        # 2024-05-29 src => data-original-src
                        thumb = cls.process_image_url(a_tags[0].xpath('.//img')[0].attrib['data-original-src'])
                        video_url = a_tags[1].attrib['href'].split('/')[-1]
                        title = a_tags[1].text_content()
                        date = cls.change_date(tag.xpath('.//span')[0].text_content().strip())
                        content_type = 'Featurette'
                        if title.find(u'예고') != -1:
                            content_type = 'Trailer'
                        # 2024-06-01 이모지 제거
                        title = SupportString.remove_emoji(title).strip()
                        #title = "title"
                        show.extras.append(EntityExtra(content_type, title, 'kakao', video_url, premiered=date, thumb=thumb))


            for i in range(1,3):
                items = root.xpath('//*[@id="tv_casting"]/div[%s]/ul//li' % i)
                #logger.debug('CASTING ITEM LEN : %s' % len(items))
                for item in items:
                    actor = EntityActor(None)
                    cast_img = item.xpath('div//img')
                    #cast_img = item.xpath('.//img')
                    if len(cast_img) == 1:
                        # 2024-05-29 src => data-original-src
                        actor.thumb = cls.process_image_url(cast_img[0].attrib['data-original-src'])
                        #logger.debug(actor.thumb)
                    
                    span_tag = item.xpath('span')
                    for span in span_tag:
                        span_text = span.text_content().strip()
                        tmp = span.xpath('a')
                        if len(tmp) == 1:
                            role_name = tmp[0].text_content().strip()
                            tail = tmp[0].tail.strip()
                            if tail == u'역':
                                actor.type ='actor'
                                actor.role = role_name.strip()
                            else:
                                actor.name = role_name.strip()
                        else:
                            if span_text.endswith(u'역'): actor.role = span_text.replace(u'역', '')
                            elif actor.name == '': actor.name = span_text.strip()
                            else: actor.role = span_text.strip()
                    if actor.type == 'actor' or actor.role.find(u'출연') != -1:
                        show.actor.append(actor)
                    elif actor.role.find(u'감독') != -1 or actor.role.find(u'연출') != -1:
                        show.director.append(actor)
                    elif actor.role.find(u'제작') != -1 or actor.role.find(u'기획') != -1 or actor.role.find(u'책임프로듀서') != -1:
                        show.director.append(actor)
                    elif actor.role.find(u'극본') != -1 or actor.role.find(u'각본') != -1:
                        show.credits.append(actor)
                    elif actor.name != u'인물관계도':
                        show.actor.append(actor)

            # 에피소드
            items = root.xpath('//*[@id="clipDateList"]/li')
            #show.extra_info['episodes'] = {}
            for item in items:
                epi = {}
                a_tag = item.xpath('a') 
                if len(a_tag) != 1:
                    continue
                epi['url'] = 'https://search.daum.net/search%s' % a_tag[0].attrib['href']
                tmp = item.attrib['data-clip']
                epi['premiered'] = tmp[0:4] + '-' + tmp[4:6] + '-' + tmp[6:8]
                match = re.compile(r'(?P<no>\d+)%s' % u'회').search(a_tag[0].text_content().strip())
                if match:
                    epi['no'] = int(match.group('no'))
                    show.extra_info['episodes'][epi['no']] = {'daum': {'code' : cls.module_char + cls.site_char + epi['url'], 'premiered':epi['premiered']}}

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
            root = SiteUtil.get_tree(episode_code, proxy_url=cls._proxy_url, headers=cls.default_headers, cookies=cls._daum_cookie)

            items = root.xpath('//div[@class="tit_episode"]')
            entity = EntityEpisode(cls.site_name, episode_code)

            if len(items) == 1:
                tmp = items[0].xpath('strong')
                if len(tmp) == 1:
                    episode_frequency = tmp[0].text_content().strip()
                    match = re.compile(r'(\d+)').search(episode_frequency)
                    if match:
                        entity.episode = int(match.group(1))

                tmp = items[0].xpath('span[@class="txt_date "]')
                date1 = ''
                if len(tmp) == 1:
                    date1 = tmp[0].text_content().strip()
                    entity.premiered = cls.change_date(date1.split('(')[0])
                    entity.title = date1
                tmp = items[0].xpath('span[@class="txt_date"]')
                if len(tmp) == 1:
                    date2 = tmp[0].text_content().strip()
                    entity.title = ('%s %s' % (date1, date2)).strip()
            items = root.xpath('//p[@class="episode_desc"]')
            has_strong_tag = False
            strong_title = ''
            if len(items) == 1:
                tmp = items[0].xpath('strong')
                if len(tmp) == 1:
                    has_strong_tag = True
                    strong_title = tmp[0].text_content().strip()
                    if strong_title != 'None': 
                        if is_ktv:
                            entity.title = '%s %s' % (entity.title, strong_title)
                        else:
                            entity.title = strong_title
                        
                else:
                    if is_ktv == False:
                        entity.title = ''
            entity.title = entity.title.strip()
            summary2 = '\r\n'.join(txt.strip() for txt in root.xpath('//p[@class="episode_desc"]/text()'))
            if summary_duplicate_remove == False:
                entity.plot = '%s\r\n%s' % (entity.title, summary2)
            else:
                entity.plot = summary2.replace(strong_title, '').strip()
            
            items = root.xpath('//*[@id="tv_episode"]/div[2]/div[1]/div/a/img')
            if len(items) == 1:
                # 2024-05-29 src => data-original-src
                entity.thumb.append(EntityThumb(aspect='landscape', value=cls.process_image_url(items[0].attrib['data-original-src']), site=cls.site_name, score=-10))

            if include_kakao:
                tags = root.xpath('//*[@id="tv_episode"]/div[3]/div/ul/li')
                for idx, tag in enumerate(tags):
                    if idx > 9:
                        break
                    a_tags = tag.xpath('.//a')
                    if len(a_tags) == 2:
                        # 2024-05-29 src => data-original-src
                        thumb = cls.process_image_url(a_tags[0].xpath('.//img')[0].attrib['data-original-src'])
                        #video_url = cls.get_kakao_play_url(a_tags[1].attrib['href'])
                        video_url = a_tags[1].attrib['href'].split('/')[-1]
                        title = a_tags[1].text_content()
                        #logger.debug(video_url)
                        date = cls.change_date(tag.xpath('.//span')[0].text_content().strip())
                        entity.extras.append(EntityExtra('Featurette', title, 'kakao', video_url, premiered=date, thumb=thumb))
            

            ret['ret'] = 'success'
            ret['data'] = entity.as_dict()
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
            root = SiteUtil.get_tree(url, proxy_url=cls._proxy_url, headers=cls.default_headers, cookies=cls._daum_cookie)

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
