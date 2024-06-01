import urllib.parse
from datetime import datetime
import requests

from .entity_base import EntityExtra, EntitySearchItemTvDaum
from .setup import *
from .site_util import SiteUtil


class SiteDaum(object):
    _daum_cookie = None
    _use_proxy = None
    _proxy_url = None

    site_name = 'daum'
    default_headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/71.0.3578.98 Safari/537.36',
        'Accept' : 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8',
        'Accept-Language' : 'ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7'
    }

    @classmethod
    def initialize(cls, daum_cookie, use_proxy=False, proxy_url=None):
        def func(daum_cookie):
            ret = {}
            tmps = daum_cookie.split(';')
            for t in tmps:
                t2 = t.split('=')
                if len(t2) == 2:
                    ret[t2[0]] = t2[1]
            return ret
        cls._daum_cookie = func(daum_cookie)
        cls._use_proxy = use_proxy
        if cls._use_proxy:
            cls._proxy_url = proxy_url
        else:
            cls._proxy_url = None


    @classmethod
    def get_show_info_on_home(cls, root):
        try:
            tags = root.xpath('//*[@id="tvpColl"]/div[2]/div/div[1]/span/a')
            # 2019-05-13
            #일밤- 미스터리 음악쇼 복면가왕 A 태그 2개
            if len(tags) < 1:
                return
            tag_index = len(tags)-1
            #entity = {}
            entity = EntitySearchItemTvDaum(cls.site_name)

            entity.title = tags[tag_index].text
            match = re.compile(r'q\=(?P<title>.*?)&').search(tags[tag_index].attrib['href'])
            if match:
                entity.title = urllib.parse.unquote(match.group('title'))
            entity.code = cls.module_char + cls.site_char + re.compile(r'irk\=(?P<id>\d+)').search(tags[tag_index].attrib['href']).group('id')

            tags = root.xpath('//*[@id="tvpColl"]/div[2]/div/div[1]/span/span')
            if len(tags) == 1:
                if tags[0].text == u'방송종료' or tags[0].text == u'완결':
                    entity.status = 2
                elif tags[0].text == u'방송예정':
                    entity.status = 0

            #entity.image_url = 'https:' + root.xpath('//*[@id="tv_program"]/div[1]/div[1]/a/img')[0].attrib['src']
            # 악동탐정스 시즌2
            try:
                # 2024-05-29 src => data-original-src
                entity.image_url = cls.process_image_url(root.xpath('//*[@id="tv_program"]/div[1]/div[1]/a/img')[0].attrib['data-original-src'])
            except:
                entity.image_url = None

            #logger.debug('get_show_info_on_home status: %s', entity.status)
            tags = root.xpath('//*[@id="tvpColl"]/div[2]/div/div[1]/div')
            entity.extra_info = SiteUtil.change_html(tags[0].text_content().strip())

            #logger.debug('get_show_info_on_home extra_info: %s', entity.extra_info)

            tags = root.xpath('//*[@id="tvpColl"]/div[2]/div/div[1]/div/a')
            if len(tags) == 1:
                entity.studio = tags[0].text
            else:
                tags = root.xpath('//*[@id="tvpColl"]/div[2]/div/div[1]/div/span[1]')
                if len(tags) == 1:
                    entity.studio = tags[0].text
            #logger.debug('get_show_info_on_home studio: %s', entity.studio)

            tags = root.xpath('//*[@id="tvpColl"]/div[2]/div/div[1]/div/span')
            extra_infos = [tag.text_content() for tag in tags]
            #logger.debug(extra_infos)
            #tmps = extra_infos[1].strip().split(' ')
            # 2021-11-03 
            # 홍루몽.  중국 방송사는 a 태그가 없기 떄문에 방송사가 장르가 되어버린다.
            entity.genre = extra_infos[0]
            if extra_infos[1] in ['미국드라마', '중국드라마', '영국드라마', '일본드라마', '대만드라마', '기타국가드라마']:
                entity.genre = extra_infos[1]
                entity.studio = extra_infos[0]
            if entity.genre in ['미국드라마', '중국드라마', '영국드라마', '일본드라마', '대만드라마', '기타국가드라마']:
                entity.status = 1
            #logger.debug(tmps)
            #if len(tmps) == 2:
            try: entity.episode = int(re.compile(r'(?P<epi>\d{1,4})%s' % u'부').search(entity.extra_info).group('epi'))
            except: entity.episode = -1
            entity.broadcast_info = extra_infos[-2].strip().replace('&nbsp;', ' ').replace('&nbsp', ' ')
            entity.broadcast_term = extra_infos[-1].split(',')[-1].strip()

            try: entity.year = re.compile(r'(?P<year>\d{4})').search(extra_infos[-1]).group('year')
            except: entity.year = 0

            entity.desc = root.xpath('//*[@id="tv_program"]/div[1]/dl[1]/dd/text()')[0]

            #logger.debug('get_show_info_on_home 1: %s', entity['status'])
            #시리즈
            entity.series = []
            
            try:
                tmp = entity.broadcast_term.split('.')
                if len(tmp) == 2:
                    entity.series.append({'title':entity.title, 'code' : entity.code, 'year' : entity.year, 'status':entity.status, 'date':'%s.%s' % (tmp[0], tmp[1])})
                else:
                    entity.series.append({'title':entity.title, 'code' : entity.code, 'year' : entity.year, 'status':entity.status, 'date':'%s' % (entity.year)})
            except Exception as exception:
                logger.debug('Not More!')
                logger.debug(traceback.format_exc())

            # 2025-05-29
            # 이전에는 하단에 시리즈가 나왔으나 탭으로 변경된 것으로 보임.
            # 지금은 후속방송 정보가 나옴

            serise_tab_tag = root.xpath('//li[@data-tab="tv_series"]')
            if serise_tab_tag:
                
                # 2019-03-05 시리즈 더보기 존재시
                try:
                    #more = root.xpath('//*[@id="tv_series"]/div/div/a')
                    #if more:
                    #url = more[0].attrib['href']
                    url = serise_tab_tag[0].xpath('a')[0].attrib['href']
                    if not url.startswith('http'):
                        url = 'https://search.daum.net/search%s' % url
                    #logger.debug('MORE URL : %s', url)
                    #if more[0].xpath('span')[0].text == u'시리즈 더보기':
                        #more_root = HTML.ElementFromURL(url)
                    more_root = SiteUtil.get_tree(url, proxy_url=cls._proxy_url, headers=cls.default_headers, cookies=cls._daum_cookie)
                    #tags = more_root.xpath('//*[@id="series"]/ul/li')
                    # 2024-05-29
                    tags = more_root.xpath('//*[@id="tv_series"]/div/ul/li')
                except Exception as exception:
                    logger.debug('Not More!')
                    logger.debug(traceback.format_exc())

                find_1900 = False
                for tag in tags:
                    dic = {}
                    dic['title'] = tag.xpath('a')[0].text
                    #logger.debug(dic['title'])
                    dic['code'] = cls.module_char + cls.site_char + re.compile(r'irk\=(?P<id>\d+)').search(tag.xpath('a')[0].attrib['href']).group('id')
                    if tag.xpath('span'):
                        # 년도 없을 수 있음
                        dic['date'] = tag.xpath('span')[0].text
                        if dic['date'] is None:
                            dic['date'] = '1900'
                            find_1900 = True
                        else:
                            dic['year'] = re.compile(r'(?P<year>\d{4})').search(dic['date']).group('year')
                    else:
                        dic['year'] = None
                    entity.series.append(dic)
                # 뒷 시즌이 code가 더 적은 경우 있음. csi 라스베가스
                # 2021-03-29 전지적 짝사랑 시점
                if find_1900 or entity.year == 0:
                    entity.series = sorted(entity.series, key=lambda k: int(k['code'][2:]))
                else:
                    # 2021-06-06 펜트하우스3. 2는 2021.2로 나오고 3은 2021로만 나와서 00이 붙어 3이 위로 가버림
                    # 같은 년도는 코드로...
                    """
                    for item in entity.series:
                        tmp = item['date'].split('.')
                        if len(tmp) == 2:
                            item['sort_value'] = int('%s%s' % (tmp[0],tmp[1].zfill(2)))
                        elif len(tmp) == 1:
                            item['sort_value'] = int('%s00' % tmp[0])
                    entity.series = sorted(entity.series, key=lambda k: k['sort_value'])
                    """
                    for item in entity.series:
                        tmp = item['date'].split('.')
                        if len(tmp) == 2:
                            item['sort_value'] = int(tmp[0])
                        elif len(tmp) == 1:
                            item['sort_value'] = int(tmp[0])
                    entity.series = sorted(entity.series, key=lambda k: (k['sort_value'], int(k['code'][2:])))

            #동명
            entity.equal_name = []
            tags = root.xpath(u'//div[@id="tv_program"]//dt[contains(text(),"동명 콘텐츠")]//following-sibling::dd')
            if tags:
                tags = tags[0].xpath('*')
                for tag in tags:
                    if tag.tag == 'a':
                        dic = {}
                        dic['title'] = tag.text
                        dic['code'] = cls.module_char + cls.site_char + re.compile(r'irk\=(?P<id>\d+)').search(tag.attrib['href']).group('id')
                    elif tag.tag == 'span':
                        match = re.compile(r'\((?P<studio>.*?),\s*(?P<year>\d{4})?\)').search(tag.text)
                        if match:
                            dic['studio'] = match.group('studio')
                            dic['year'] = match.group('year')
                        elif tag.text == u'(동명프로그램)':
                            entity.equal_name.append(dic)
                        elif tag.text == u'(동명회차)':
                            continue
            #logger.debug(entity)
            return entity.as_dict()
        except Exception as exception:
            logger.debug('Exception get_show_info_by_html : %s', exception)
            logger.debug(traceback.format_exc())

    @classmethod
    def process_image_url(cls, url):
        tmps = url.split('fname=')
        if len(tmps) == 2:
            return urllib.parse.unquote(tmps[1])
        else:
            return 'https' + url

    @classmethod 
    def get_kakao_play_url(cls, url):
        try:
            content_id = url.split('/')[-1]
            url = 'https://tv.kakao.com/katz/v2/ft/cliplink/{}/readyNplay?player=monet_html5&profile=HIGH&service=kakao_tv&section=channel&fields=seekUrl,abrVideoLocationList&startPosition=0&tid=&dteType=PC&continuousPlay=false&contentType=&{}'.format(content_id, int(time.time()))
            data = requests.get(url).json()
            return data['videoLocation']['url']
        except Exception as exception:
            logger.debug('Exception : %s', exception)
            logger.debug(traceback.format_exc())

    @classmethod 
    def change_date(cls, text):
        try:
            match = re.compile(r'(?P<year>\d{4})\.(?P<month>\d{1,2})\.(?P<day>\d{1,2})').search(text)
            if match:
                return match.group('year') + '-' + match.group('month').zfill(2) + '-'+ match.group('day').zfill(2)
        except Exception as exception:
            logger.debug('Exception : %s', exception)
            logger.debug(traceback.format_exc())
        #return text
        return datetime.now().strftime('%Y-%m-%d')

    @classmethod
    def get_kakao_video(cls, kakao_id, sort='CreateTime', size=20):
        #sort : CreateTime PlayCount
        ret = []
        try:
            url = 'https://tv.kakao.com/api/v1/ft/channels/{kakao_id}/videolinks?sort={sort}&fulllevels=clipLinkList%2CliveLinkList&fields=ccuCount%2CisShowCcuCount%2CthumbnailUrl%2C-user%2C-clipChapterThumbnailList%2C-tagList&size=20&page=1&_={timestamp}'.format(kakao_id=kakao_id, sort=sort, timestamp=int(time.time()))
            data = requests.get(url).json()
           
            for item in data['clipLinkList']:
                ret.append(EntityExtra('Featurette', item['clip']['title'], 'kakao', item['id'], premiered=item['createTime'].split(' ')[0], thumb=item['clip']['thumbnailUrl']).as_dict())
            return ret
        except Exception as exception:
            logger.debug('Exception : %s', exception)
            logger.debug(traceback.format_exc())
        return ret   

