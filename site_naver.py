import urllib.parse
import urllib.request

import requests
from lxml import html

from . import SiteUtil
from .entity_base import (EntityActor, EntityExtra2, EntityMovie2,
                          EntityRatings, EntitySearchItemMovie, EntityThumb)
from .setup import *


class SiteNaver(object):
    site_name = 'naver'
    default_headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/71.0.3578.98 Safari/537.36',
        'Accept' : 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8',
        'Accept-Language' : 'ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7'
    }

    _naver_key = None

    @classmethod
    def initialize(cls, naver_key):
        cls._naver_key = naver_key


class SiteNaverMovie(SiteNaver):
    site_base_url = 'https://movie.naver.com'
    module_char = 'M'
    site_char = 'N'

    @classmethod 
    def search(cls, keyword, year=1900):
        try:
            ret = {}
            logger.debug('NAVER search : [%s] [%s]', keyword, year)
            data = cls.search_api(keyword)
            result_list = []
            if data is not None:
                for idx, item in enumerate(data['items']):
                    entity = EntitySearchItemMovie(cls.site_name)
                    entity.code = cls.module_char + cls.site_char + item['link'].split('=')[1]
                    entity.title = re.sub(r'\<.*?\>', '', item['title']).strip()
                    entity.originaltitle = re.sub(r'\<.*?\>', '', item['subtitle']).strip()
                    entity.image_url = item['image']
                    try: entity.year = int(item['pubDate'])
                    except: entity.year = 1900
                    if item['actor'] != '':
                        entity.desc += u'배우 : %s\r\n' % ', '.join(item['actor'].rstrip('|').split('|'))
                    if item['director'] != '':
                        entity.desc += u'감독 : %s\r\n' % ', '.join(item['director'].rstrip('|').split('|'))
                    if item['userRating'] != '0.00':
                        entity.desc += u'평점 : %s\r\n' % item['userRating']
                    # etc
                    entity.extra_info['actor'] = item['actor']
                    entity.extra_info['director'] = item['director']
                    entity.extra_info['userRating'] = item['userRating']
                
                    if SiteUtil.compare(keyword, entity.title) or SiteUtil.compare(keyword, entity.originaltitle):
                        if year != 1900:
                            if abs(entity.year-year) < 2:
                                entity.score = 100
                            else:
                                entity.score = 80
                        else:
                            entity.score = 95
                    else:
                        entity.score = 80 - (idx*5)
                        if entity.score < 0:
                            entity.socre = 10
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
    def search_api(cls, keyword):
        try:
            if cls._naver_key == None:
                return
            for tmp in cls._naver_key.split('\n'):
                tmps = tmp.strip().split(',')
                if len(tmps) != 2:
                    continue
                client_id = tmps[0]
                client_secret = tmps[1]
                try:
                    if client_id == '' or client_id is None or client_secret == '' or client_secret is None: 
                        return keyword
                    url = f"https://openapi.naver.com/v1/search/movie.json?query={urllib.parse.quote(str(keyword))}&display=100"
                    requesturl = urllib.request.Request(url)
                    requesturl.add_header("X-Naver-Client-Id", client_id)
                    requesturl.add_header("X-Naver-Client-Secret", client_secret)
                    response = urllib.request.urlopen(requesturl)
                    if sys.version_info[0] == 2:
                        data = json.load(response, encoding='utf8')
                    else:
                        data = json.load(response)
                    rescode = response.getcode()
                    if rescode == 200:
                        return data
                    else:
                        continue
                except Exception as e: 
                    logger.error(f"Exception:{str(e)}")
                    logger.error(traceback.format_exc())             
        except Exception as e: 
            logger.error(f"Exception:{str(e)}")
            logger.error(traceback.format_exc())       

    @classmethod 
    def info(cls, code):
        try:
            ret = {}
            entity = EntityMovie2(cls.site_name, code)
            cls.info_basic(code, entity)
            cls.info_detail(code, entity)
            cls.info_photo(code, entity)
            cls.info_video(code, entity)
            ret['ret'] = 'success'
            ret['data'] = entity.as_dict()
            return ret
        except Exception as e: 
            logger.error(f"Exception:{str(e)}")
            logger.error(traceback.format_exc()) 
            ret['ret'] = 'exception'
            ret['data'] = str(e)
        return ret


    @classmethod 
    def info_video(cls, code, entity):
        try:
            url = 'https://movie.naver.com/movie/bi/mi/media.nhn?code=%s' % code[2:]
            root = html.fromstring(requests.get(url).text)
            tags = root.xpath('//div[@class="video"]')
            if not tags:
                return
            video_map = [['ifr_trailer','Trailer'], ['ifr_making','BehindTheScenes'], ['ifr_interview','Interview'], ['ifr_movie_talk','Featurette']]
            for video in video_map:
                li_tags = tags[0].xpath('.//div[@class="%s"]//ul[@class="video_thumb"]/li' % video[0])
                for tag in li_tags:
                    extra = EntityExtra2()
                    extra.content_type = video[1]
                    extra.mode = cls.site_name
                    video_page_url = tag.xpath('.//a')[0].attrib['href']
                    extra.content_url = '%s,%s' % (code, video_page_url.split('#')[0].split('mid=')[1])
                    try:
                        tmp_root = SiteUtil.get_tree('https://movie.naver.com' + video_page_url)
                        tmp = tmp_root.xpath('//iframe[@class="_videoPlayer"]')
                        if tmp:
                            tmp2 = tmp[0].attrib['src']
                            extra.thumb = 'https://ssl.pstatic.net/imgmovie' + tmp2.split('coverImage=')[1].split('&')[0]
                    except Exception as e: 
                        logger.error(f"Exception:{str(e)}")
                        logger.error(traceback.format_exc()) 
                    extra.title = tag.xpath('.//a/img')[0].attrib['alt']
                    extra.premiered = tag.xpath('.//p[@class="video_date"]')[0].text_content().replace('.', '-')
                    entity.extras.append(extra)
        except Exception as e: 
            logger.error(f"Exception:{str(e)}")
            logger.error(traceback.format_exc()) 


    @classmethod 
    def info_photo(cls, code, entity):
        try:
            page = 1
            while True:
                url = 'https://movie.naver.com/movie/bi/mi/photoListJson.nhn?movieCode=%s&size=100&offset=%s' % (code[2:], (page-1)*100)
                data = requests.get(url).json()['lists']
                poster_count = 0
                art_count = 0
                max_art_count = 10
                base_score  = 60
                for item in data:
                    art = EntityThumb()
                    if item['imageType'] == 'STILLCUT':
                        if art_count >= max_art_count:
                            continue
                        art.aspect = 'landscape'
                        art.score = base_score - 10 - art_count
                        art_count += 1
                    elif item['imageType'] == 'POSTER':
                        if poster_count >= max_art_count:
                            continue
                        if item['width'] > item['height']:
                            art.aspect = 'landscape'
                            art.score = base_score + max_art_count - art_count
                            art_count += 1
                        else:
                            art.aspect = 'poster'
                            art.score = base_score - poster_count
                            poster_count += 1
                    else:
                        continue
                    art.value = item['fullImageUrl']
                    art.thumb = item['fullImageUrl221px']
                    entity.art.append(art)
                page += 1
                if len(data) != 100 or page > 3:
                    break
        except Exception as e: 
            logger.error(f"Exception:{str(e)}")
            logger.error(traceback.format_exc()) 

    @classmethod 
    def info_detail(cls, code, entity):
        try:
            url = 'https://movie.naver.com/movie/bi/mi/detail.nhn?code=%s' % code[2:]
            root = html.fromstring(requests.get(url).text)
            tags = root.xpath('//ul[@class="lst_people"]/li')
            if tags:
                for tag in tags:
                    actor = EntityActor('', site=cls.site_name)
                    tmp = tag.xpath('.//img')[0].attrib['src']
                    match = re.search(r'src\=(?P<url>.*?)\&', tmp) 
                    if match:
                        actor.thumb = urllib.parse.unquote(match.group('url'))
                    actor.name = tag.xpath('.//div[@class="p_info"]/a')[0].attrib['title']
                    tmp = tag.xpath('.//div[@class="p_info"]/em')
                    if tmp:
                        actor.originalname = tmp[0].text_content()
                    tmp = tag.xpath('.//div[@class="p_info"]//p[@class="pe_cmt"]/span')
                    if tmp:
                        actor.role = tmp[0].text_content().replace(u'역', '').strip()
                    entity.actor.append(actor)
            tags = root.xpath('//div[@class="director"]//div[@class="dir_obj"]')
            if tags:
                for tag in tags:
                    tmp = tag.xpath('.//div[@class="dir_product"]/a')
                    if tmp:
                        entity.director.append(tmp[0].attrib['title'])
            tags = root.xpath('//div[@class="staff"]//tr[1]//span')
            if tags:
                for tag in tags:
                    tmp = tag.xpath('.//a')
                    if tmp:
                        entity.credits.append(tmp[0].text_content().strip()) 
                    else:
                        entity.credits.append(tag.text.strip()) 
            tags = root.xpath('//div[@class="agency"]/dl')
            if tags:
                tmp1 = tags[0].xpath('.//dt')
                tmp2 = tags[0].xpath('.//dd')
                for idx, tag in enumerate(tmp1):
                    if tag.text_content().strip() == u'제작':
                        tmp = tmp2[idx].xpath('.//a')
                        entity.studio = tmp[0].text_content().strip() if tmp else tmp2[idx].text_content().strip()
        except Exception as e: 
            logger.error(f"Exception:{str(e)}")
            logger.error(traceback.format_exc()) 


    @classmethod 
    def info_basic(cls, code, entity):
        try:
            url = 'https://movie.naver.com/movie/bi/mi/basic.nhn?code=%s' % code[2:]
            logger.debug(url)
            entity.code_list.append(['naver_id', code[2:]])
            text = requests.get(url, headers=cls.default_headers).text
            root = html.fromstring(text)
            tags = root.xpath('//div[@class="mv_info"]')
            if tags:
                entity.title = tags[0].xpath('.//h3/a')[0].text_content()
                entity.extra_info['title_ko'] = entity.title
                tmp = tags[0].xpath('.//strong')[0].text_content()
                tmps = [x.strip() for x in tmp.split(',')]
                if len(tmps) == 2:# 영문제목, 년도
                    entity.extra_info['title_en'] = tmps[0]
                    entity.year = int(tmps[1])
                elif len(tmps) == 3: # 일문,한문 / 영문 / 년도
                    entity.extra_info['title_3'] = tmps[0]
                    entity.extra_info['title_en'] = tmps[1]
                    entity.year = int(tmps[2])
                elif len(tmps) == 1:
                    entity.year = int(tmps[0])
                else:
                    logger.debug('TTTTTOOOOOODDDDOOO')
            else:
                # 19금
                return False
            tags = root.xpath('//div[@class="main_score"]')
            if tags:
                tmp_tag = tags[0].xpath('.//*[@id="pointNetizenPersentWide"]//em')
                if tmp_tag:
                    tmp = ''.join([x.text for x in tmp_tag])
                    try: entity.ratings.append(EntityRatings(float(tmp), name=cls.site_name))
                    except: pass
            tags = root.xpath('//p[@class="info_spec"]')
            if tags:
                tags = tags[0].xpath('.//span')
                for tag in tags:
                    a_tag = tag.xpath('.//a')
                    if a_tag:
                        href = a_tag[0].attrib['href']
                        if href.find('genre=') != -1:
                            for tmp in a_tag:
                                entity.genre.append(tmp.text_content().strip())
                        elif href.find('nation=') != -1:
                            tmp = a_tag[0].text_content().strip()
                            entity.country.append(tmp)
                            if tmp == u'한국':
                                entity.originaltitle = entity.extra_info['title_ko']
                            else:
                                entity.originaltitle = entity.extra_info['title_3'] if 'title_3' in entity.extra_info else entity.extra_info['title_en'] 
                        elif href.find('open=') != -1:
                            for a_tag_tmp in a_tag:
                                tmp = a_tag_tmp.attrib['href'].split("open=")[1]
                                logger.debug(tmp)
                                if len(tmp) == 8:
                                    entity.premiered = '%s-%s-%s' % (tmp[0:4], tmp[4:6], tmp[6:8])
                        elif href.find('grade=') != -1:
                            entity.mpaa = a_tag[0].text_content().strip()
                    else:
                        if tag.text_content().find(u'분') != -1:
                            entity.runtime = int(tag.text_content().replace(u'분', '').strip())
            tags = root.xpath('//div[@class="story_area"]//h5[@class="h_tx_story"]')
            if tags:
                entity.tagline = tags[0].text_content().strip()
            tags = root.xpath('//div[@class="story_area"]//p[@class="con_tx"]/text()')
            if tags:
                entity.plot = '\r\n'.join([tag.strip().replace('&nbsp;', '') for tag in tags])
        except Exception as e: 
            logger.error(f"Exception:{str(e)}")
            logger.error(traceback.format_exc()) 
        return True


    @classmethod 
    def get_video_url(cls, param):
        try:
            tmps = param.split(',')
            if tmps[0].startswith('MN'):
                tmps[0] = tmps[0][2:]
            url = 'https://movie.naver.com/movie/bi/mi/mediaView.nhn?code=%s&mid=%s' % (tmps[0], tmps[1])
            root = html.fromstring(requests.get(url).text)
            tmp = root.xpath('//iframe[@class="_videoPlayer"]')[0].attrib['src']
            match = re.search(r'&videoId=(.*?)&videoInKey=(.*?)&', tmp)
            if match:
                url = 'https://apis.naver.com/rmcnmv/rmcnmv/vod/play/v2.0/%s?key=%s' % (match.group(1), match.group(2))
                data = requests.get(url).json()
                ret = data['videos']['list'][0]['source']
                return ret
        except Exception as e: 
            logger.error(f"Exception:{str(e)}")
            logger.error(traceback.format_exc())

