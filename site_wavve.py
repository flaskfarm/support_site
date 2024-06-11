from . import SiteUtil, SupportWavve
from .entity_base import (EntityActor, EntityMovie2, EntityRatings,
                          EntitySearchItemMovie, EntitySearchItemTv,
                          EntityShow, EntityThumb)
from .setup import *

channelname_map = {
    u'카카오M' : 'kakaoTV',
    u'KBS 2TV' : 'KBS2',
    u'KBS 1TV' : 'KBS1',
}
mpaa_map = {'0' : u'모든 연령 시청가', '7' : u'7세 이상 시청가', '12' : u'12세 이상 시청가', '15' : u'15세 이상 시청가', '19' : u'19세 이상 시청가'}

movie_mpaa_map = {'0' : u'전체 관람가', '12': u'12세 관람가', '15': u'15세 관람가', '18' : u'청소년 관람불가', '21' : u'청소년 관람불가'}

class SiteWavve(object):
    site_name = 'wavve'

    @classmethod
    def change_daum_channelname(cls, channelname):
        if channelname in channelname_map:
            return channelname_map[channelname]
        return channelname

    @classmethod
    def trim_program_id(cls, code):
        code, delimiter, trailing = code.partition('&')
        return code


# 2024-06-08
#https://image.wavve.com/v1/thumbnails/480_720_20_80/BMS/program_poster/201904/C3701_C37000000068_2.jpg
#https://img.pooq.co.kr/BMS/program_poster/201904/C3701_C37000000068_2.jpg
                    


class SiteWavveTv(SiteWavve):
    module_char = 'K'
    site_char = 'W'


    @classmethod
    def search(cls, keyword, **kwargs):
        try:
            ret = {}
            search_list = SupportWavve.search_tv(keyword)
            if search_list:
                show_list = []
                count_100 = 0
                for idx, item in enumerate(search_list):
                    entity = EntitySearchItemTv(cls.site_name)
                    entity.title = item['title_list'][0]['text']
                    if entity.title.find('[스페셜]') != -1:
                        continue
                    #entity.code = (kwargs['module_char'] if 'module_char' in kwargs else cls.module_char) + cls.site_char + item['event_list'][1]['url'].split('=')[1]
                    match = re.search('id=(?P<code>[^&\n]+)', item['event_list'][1]['url'])
                    if match:
                        entity.code = (kwargs['module_char'] if 'module_char' in kwargs else cls.module_char) + cls.site_char + match.group('code')
                    item['thumbnail'] = item['thumbnail'].replace('img.pooq.co.kr/BMS/program_poster', 'image.wavve.com/v1/thumbnails/480_720_20_80/BMS/program_poster')
                    entity.image_url = 'https://' + item['thumbnail']
                    if SiteUtil.compare_show_title(entity.title, keyword):
                        entity.score = 100 - count_100
                        count_100 += 1
                    else:
                        entity.score = 60 - idx * 5
                    show_list.append(entity.as_dict())
                ret['ret'] = 'success'
                ret['data'] = show_list
            else:
                ret['ret'] = 'empty'
        except Exception as e:
            logger.error(f"Exception:{str(e)}")
            logger.error(traceback.format_exc())
            ret['ret'] = 'exception'
            ret['data'] = str(e)
        return ret


    @classmethod
    def apply_tv_by_search(cls, show, force_search_title=None):
        try:
            keyword = force_search_title if force_search_title is not None else show['title']
            data = cls.search(keyword)
            if data['ret'] == 'success':
                data = data['data']
                for item in data:
                    if SiteUtil.compare_show_title(item['title'], keyword) and SiteUtil.compare(cls.change_daum_channelname(item['title']), keyword):
                        info = SupportWavve.vod_programs_programid(item['code'][2:])
                        # 2021-10-03  JTBC2 부자의 탄생
                        # Daum 검색 -> 회차정보 없음 -> 동명 드라마 에피 정보가 들어가버림
                        # 스튜디오로나 첫날짜가 같다면 동일로 판단. 이것들 정보가 항상 있는지 파악 못함
                        if info is not None and (show['studio'] == info['cpname'] or show['premiered'] == info['firstreleasedate']):
                            cls._apply_tv_by_program(show, info)
                            break
        except Exception as e:
            logger.error(f"Exception:{str(e)}")
            logger.error(traceback.format_exc())


    @classmethod
    def _apply_tv_by_program(cls, show, program_info):
        try:
            show['extra_info']['wavve_id'] = program_info['programid']
            show['plot'] = program_info['programsynopsis'].replace('<br>', '\r\n')
            score = 70
            show['thumb'].append(EntityThumb(aspect='landscape', value='https://' + program_info['image'], site=cls.site_name, score=0).as_dict())
            program_info['posterimage']= program_info['posterimage'].replace('img.pooq.co.kr/BMS/program_poster', 'image.wavve.com/v1/thumbnails/480_720_20_80/BMS/program_poster')
            show['thumb'].append(EntityThumb(aspect='poster', value='https://' + program_info['posterimage'], site=cls.site_name, score=score).as_dict())

            page = 1
            epi = None
            while True:
                episode_data = SupportWavve.vod_program_contents_programid(program_info['programid'], page=page)
                for epi in episode_data['list']:
                    try:
                        tmp = epi['episodenumber'].split('-')
                        if len(tmp) == 1:
                            epi_no = int(tmp[0])
                        else:
                            epi_no = int(tmp[1]) / 2
                    except: continue
                    if epi_no not in show['extra_info']['episodes']:
                        show['extra_info']['episodes'][epi_no] = {}

                    show['extra_info']['episodes'][epi_no][cls.site_name] = {
                        'code' : cls.module_char + cls.site_char + epi['contentid'],
                        'thumb' : 'https://' + epi['image'],
                        'plot' : epi['synopsis'].replace('<br>', '\r\n'),
                        'premiered' : epi['releasedate'],
                        'title' : epi['episodetitle'],
                    }
                page += 1
                if episode_data['pagecount'] == episode_data['count'] or page == 10:
                    break
            # 방송정보에 없는 데이터 에피소드에서 빼서 입력
            if epi:
                show['mpaa'] = mpaa_map.get(epi.get('targetage')) or mpaa_map['0']

                if len(show['actor']) == 0:
                    for item in epi['episodeactors'].split(','):
                        actor = EntityActor(item.strip())
                        actor.name = item.strip()
                        show['actor'].append(actor.as_dict())

        except Exception as e:
            logger.error(f"Exception:{str(e)}")
            logger.error(traceback.format_exc())


    @classmethod
    def info(cls, code):
        try:
            ret = {}
            code = cls.trim_program_id(code)
            program_info = SupportWavve.vod_programs_programid(code[2:])
            show = EntityShow(cls.site_name, code)
            show.title = program_info['programtitle']
            show.originaltitle = show.title
            show.sorttitle = show.title
            show.studio = cls.change_daum_channelname(program_info['channelname'])
            show.premiered = program_info['firstreleasedate']
            if show.premiered != '':
                show.year = int(show.premiered.split('-')[0])
            logger.warning(program_info['closedate'])
            show.status = 1
            if program_info['tags']['list']:
                show.genre = [program_info['tags']['list'][0]['text']]
            for item in program_info['programactors']['list']:
                actor = EntityActor(None)
                actor.name = item['text']
                show.actor.append(actor)
            show = show.as_dict()
            cls._apply_tv_by_program(show, program_info)
            ret['ret'] = 'success'
            ret['data'] = show
        except Exception as e:
            logger.error(f"Exception:{str(e)}")
            logger.error(traceback.format_exc())
            ret['ret'] = 'exception'
            ret['data'] = str(e)
        return ret





class SiteWavveMovie(SiteWavve):
    module_char = 'M'
    site_char = 'W'


    @classmethod
    def search_api(cls, keyword):
        return SupportWavve.search_movie(keyword)

    @classmethod
    def info_api(cls, code):
        code = cls.trim_program_id(code)
        if code.startswith(cls.module_char + cls.site_char):
            code = code[2:]
        return SupportWavve.movie_contents_movieid(code)

    @classmethod
    def search(cls, keyword, year=1900):
        try:
            ret = {}
            search_list = cls.search_api(keyword)
            result_list = []
            if search_list:
                for idx, item in enumerate(search_list):
                    entity = EntitySearchItemMovie(cls.site_name)
                    #entity.code = cls.module_char + cls.site_char + item['event_list'][1]['url'].split('=')[1]
                    match = re.search('id=(?P<code>[^&\n]+)', item['event_list'][1]['url'])
                    if match:
                        entity.code = cls.module_char + cls.site_char + match.group('code')

                    entity.title = item['title_list'][0]['text']
                    entity.image_url = 'https://' + item['thumbnail']
                    entity.desc = u'Age: %s' % (item['age'])

                    if SiteUtil.compare(keyword, entity.title):
                        entity.score = 94
                    else:
                        entity.score = 80 - (idx*5)
                    result_list.append(entity.as_dict())
                result_list = sorted(result_list, key=lambda k: k['score'], reverse=True)
            if result_list:
                ret['ret'] = 'success'
                ret['data'] = result_list
            else:
                ret['ret'] = 'empty'
        except Exception as e:
            logger.error(f"Exception:{str(e)}")
            logger.error(traceback.format_exc())
            ret['ret'] = 'exception'
            ret['data'] = str(e)
        return ret


    @classmethod
    def info(cls, code):
        try:
            ret = {}
            code = cls.trim_program_id(code)
            entity = EntityMovie2(cls.site_name, code)
            entity.code_list.append(['wavve_id', code[2:]])
            wavve_data = cls.info_api(code)
            if wavve_data == None:
                return

            entity.title = wavve_data['title']
            try:
                tmp = wavve_data['origintitle'].split(',')
                entity.extra_info['title_en'] = tmp[0].strip()

            except: pass

            entity.country.append(wavve_data['country'])
            if wavve_data['country'] == u'한국':
                entity.originaltitle = entity.title
            else:
                entity.originaltitle = entity.extra_info['title_en']

            for item in wavve_data['genre']['list']:
                entity.genre.append(item['text'])

            try: entity.runtime = int(int(wavve_data['playtime']) / 60)
            except: pass
            for item in wavve_data['actors']['list']:
                actor = EntityActor('', site=cls.site_name)
                actor.name = item['text']
                entity.actor.append(actor)

            for item in wavve_data['directors']['list']:
                entity.director.append(item['text'])

            entity.art.append(EntityThumb(aspect='poster', value='https://' + wavve_data['image'], site=cls.site_name, score=50))

            try: entity.ratings.append(EntityRatings(float(wavve_data['rating']), name=cls.site_name))
            except: pass
            entity.premiered = wavve_data['releasedate']
            try: entity.year = int(entity.premiered.split('-')[0])
            except: pass
            entity.plot = wavve_data['synopsis']
            try: entity.mpaa = movie_mpaa_map[wavve_data['targetage']]
            except: entity.mpaa = wavve_data['targetage']

            permission = SupportWavve.getpermissionforcontent(code[2:])
            if permission['action'] == 'stream':
                entity.extra_info['wavve_stream'] = {}
                entity.extra_info['wavve_stream']['drm'] = (wavve_data['drms'] != '')
                if entity.extra_info['wavve_stream']['drm'] == False:
                    entity.extra_info['wavve_stream']['plex'] = code
                entity.extra_info['wavve_stream']['kodi'] = 'plugin://metadata.sjva.movie/?action=play&code=%s' % code
            ret['ret'] = 'success'
            ret['data'] = entity.as_dict()
            return ret
        except Exception as e:
            logger.error(f"Exception:{str(e)}")
            logger.error(traceback.format_exc())
            ret['ret'] = 'exception'
            ret['data'] = str(e)
        return ret
