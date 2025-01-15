import urllib.parse

import requests

from . import SiteDaum, SiteUtil
from .entity_base import (EntityActor, EntityExtra2, EntityMovie2,
                          EntityRatings, EntitySearchItemMovie, EntityThumb)
from .setup import *


class SiteDaumMovie(SiteDaum):
    site_base_url = 'https://search.daum.net'
    module_char = 'M'
    site_char = 'D'

    @classmethod
    def search(cls, keyword, year=1900):
        try:
            ret = {}
            result_list = cls.search_movie_api(keyword, year)
            result_list = list(reversed(sorted(result_list, key=lambda k:k['score'])))
            if len(result_list) == 0 or result_list[0]['score'] != 100:
                movie_list = []
                cls.search_movie_web(movie_list, keyword, year)
                if len(movie_list) > 0:
                    if movie_list[0]['score'] == 100:
                        home = {'site':'daum', 'score':100, 'originaltitle':''}
                        home['code'] = f"MD{movie_list[0]['id']}"
                        home['title'] = movie_list[0]['title']
                        home['year'] = movie_list[0]['year']
                        try: home['title_en'] = movie_list[0]['more']['eng_title']
                        except: home['title_en'] = ''
                        try: home['image_url'] = movie_list[0]['more']['poster']
                        except: home['image_url'] = ''
                        try: home['desc'] = movie_list[0]['more']['info'][0]
                        except: home['desc'] = ''
                        home['link'] = 'https://movie.daum.net/moviedb/main?movieId=' + movie_list[0]['id']
                        result_list.insert(0, home)

            if result_list is None:
                ret['ret'] = 'empty'
            else:
                ret['ret'] = 'success'
                ret['data'] = result_list
            return ret
        except Exception as e:
            logger.error(f"Exception:{str(e)}")
            logger.error(traceback.format_exc())
            ret['ret'] = 'exception'
            ret['data'] = str(e)
        return ret


    @classmethod
    def movie_append(cls, movie_list, data):
        try:
            exist_data = None
            for tmp in movie_list:
                if tmp['id'] == data['id']:
                    #flag_exist = True
                    exist_data = tmp
                    break
            if exist_data is not None:
                movie_list.remove(exist_data)
            movie_list.append(data)
        except Exception as e:
            logger.error(f'Exception:{str(e)}')
            logger.error(traceback.format_exc())

    @classmethod
    def get_movie_info_from_home(cls, url):
        try:
            html = SiteUtil.get_tree(url, proxy_url=cls._proxy_url, headers=cls.default_headers, cookies=cls._daum_cookie)
            movie = None
            try:
                movie = html.get_element_by_id('movieEColl')
            except Exception as exception:
                pass
            if movie is None:
                return None

            title_tag = movie.get_element_by_id('movieTitle')
            a_tag = title_tag.find('a')
            href = a_tag.attrib['href']
            title = a_tag.find('b').text_content()

            # 2019-08-09
            tmp = title_tag.text_content()
            tmp_year = ''
            match = re.compile(r'(?P<year>\d{4})\s%s' % u'제작').search(tmp)

            more = {}
            if match:
                tmp_year = match.group('year')
                more['eng_title'] = tmp.replace(title, '').replace(tmp_year, '').replace(u'제작', '').replace(u',', '').strip()

            country_tag = movie.xpath('//div[3]/div/div[1]/div[2]/dl[1]/dd[2]')
            country = ''
            if country_tag:
                country = country_tag[0].text_content().split('|')[0].strip()
            more['poster'] = movie.xpath('//*[@id="nmovie_img_0"]/a/img')[0].attrib['src']
            more['title'] = movie.xpath('//*[@id="movieTitle"]/span')[0].text_content()
            tmp = movie.xpath('//*[@id="movieEColl"]/div[3]/div/div[1]/div[2]/dl')
            more['info'] = []
            more['info'].append(country_tag[0].text_content().strip())

            tmp = more['info'][0].split('|')
            if len(tmp) == 5:
                more['country'] = tmp[0].replace(u'외', '').strip()
                more['genre'] = tmp[1].replace(u'외', '').strip()
                more['date'] = tmp[2].replace(u'개봉', '').strip()
                more['rate'] = tmp[3].strip()
                more['during'] = tmp[4].strip()
            elif len(tmp) == 4:
                more['country'] = tmp[0].replace(u'외', '').strip()
                more['genre'] = tmp[1].replace(u'외', '').strip()
                more['date'] = ''
                more['rate'] = tmp[2].strip()
                more['during'] = tmp[3].strip()
            elif len(tmp) == 3:
                more['country'] = tmp[0].replace(u'외', '').strip()
                more['genre'] = tmp[1].replace(u'외', '').strip()
                more['date'] = ''
                more['rate'] = ''
                more['during'] = tmp[2].strip()
            daum_id = href.split('=')[1]
            if isinstance(tmp_year, str):
                tmp_year = int(tmp_year)
            return {'movie':movie, 'title':title, 'daum_id':daum_id, 'year':tmp_year, 'country':country, 'more':more}

        except Exception as e:
            logger.error(f'Exception:{str(e)}')
            logger.error(traceback.format_exc())


    @classmethod
    def search_movie_web(cls, movie_list, movie_name, movie_year):
        try:
            url_list = [
                'https://search.daum.net/search?nil_suggest=btn&w=tot&DA=SBC&q=%s %s' % (urllib.parse.quote(movie_name.encode('utf8')), movie_year),
                'https://search.daum.net/search?nil_suggest=btn&w=tot&DA=SBC&q=%s' % (urllib.parse.quote(movie_name.encode('utf8'))),
                'https://search.daum.net/search?nil_suggest=btn&w=tot&DA=SBC&q=%s%s %s' % ('%EC%98%81%ED%99%94+', urllib.parse.quote(movie_name.encode('utf8')), movie_year),
                'https://search.daum.net/search?nil_suggest=btn&w=tot&DA=SBC&q=%s%s' % ('%EC%98%81%ED%99%94+', urllib.parse.quote(movie_name.encode('utf8')))
            ]
            for url in url_list:
                ret = cls.get_movie_info_from_home(url)
                if ret is not None:
                    break

            if ret is not None:
                # 부제목때문에 제목은 체크 하지 않는다.
                # 홈에 검색한게 년도도 같다면 score : 100을 주고 다른것은 검색하지 않는다.
                if ret['year'] == movie_year:
                    score = 100
                    need_another_search = False
                else:
                    score = 90
                    need_another_search = True
                cls.movie_append(movie_list, {'id':ret['daum_id'], 'title':ret['title'], 'year':ret['year'], 'score':score, 'country':ret['country'], 'more':ret['more']})

                movie = ret['movie']
                if need_another_search:
                    tmp = movie.find('div[@class="coll_etc"]')
                    if tmp is not None:
                        tag_list = tmp.findall('.//a')
                        first_url = None
                        for tag in tag_list:
                            match = re.compile(r'(.*?)\((.*?)\)').search(tag.text_content())
                            if match:
                                daum_id = tag.attrib['href'].split('||')[1]
                                score = 80
                                if match.group(1) == movie_name and match.group(2) == movie_year:
                                    first_url = 'https://search.daum.net/search?%s' % tag.attrib['href']
                                elif match.group(2) == movie_year and first_url is not None:
                                    first_url = 'https://search.daum.net/search?%s' % tag.attrib['href']
                                cls.movie_append(movie_list, {'id':daum_id, 'title':match.group(1), 'year':match.group(2), 'score':score})
                        if need_another_search and first_url is not None:
                            new_ret = cls.get_movie_info_from_home(first_url)
                            cls.movie_append(movie_list, {'id':new_ret['daum_id'], 'title':new_ret['title'], 'year':new_ret['year'], 'score':100, 'country':new_ret['country'], 'more':new_ret['more']})
                #시리즈
                    tmp = movie.find('.//ul[@class="list_thumb list_few"]')
                    if tmp is not None:
                        tag_list = tmp.findall('.//div[@class="wrap_cont"]')
                        first_url = None
                        score = 80
                        for tag in tag_list:
                            a_tag = tag.find('a')
                            daum_id = a_tag.attrib['href'].split('||')[1]
                            daum_name = a_tag.text_content()
                            span_tag = tag.find('span')
                            year = span_tag.text_content()
                            if daum_name == movie_name and year == movie_year:
                                first_url = 'https://search.daum.net/search?%s' % a_tag.attrib['href']
                            elif year == movie_year and first_url is not None:
                                first_url = 'https://search.daum.net/search?%s' % tag.attrib['href']
                            cls.movie_append(movie_list, {'id':daum_id, 'title':daum_name, 'year':year, 'score':score})
                        if need_another_search and first_url is not None:
                            new_ret = cls.get_movie_info_from_home(first_url)
                            cls.movie_append(movie_list, {'id':new_ret['daum_id'], 'title':new_ret['title'], 'year':new_ret['year'], 'score':100, 'country':new_ret['country'], 'more':new_ret['more']})
        except Exception as e:
            logger.error(f'Exception:{str(e)}')
            logger.error(traceback.format_exc())
        movie_list = list(reversed(sorted(movie_list, key=lambda k:k['score'])))
        return movie_list


    @classmethod
    def search_movie_api(cls, keyword, year):
        try:
            ret = []
            url = f"https://movie.daum.net/api/search?q={urllib.parse.quote(str(keyword))}&t=movie&page=1&size=100"
            data = requests.get(url).json()
            score_100 = 100
            count = 0
            for idx, item in enumerate(data['result']['search_result']['documents']):
                item = item['document']
                entity = EntitySearchItemMovie(cls.site_name)
                entity.title = item['titleKoreanHanl']
                entity.code = cls.module_char + cls.site_char + item['movieId']
                entity.image_url = item['mainPhoto']
                entity.year = item['productionYear']
                entity.title_en = item['titleEnglishHanl']
                entity.extra_info['title_en'] = item['titleEnglishHanl']
                entity.desc = f"{item['admission']} / {item['genres']}"
                entity.link = 'https://movie.daum.net/moviedb/main?movieId=' + item['movieId']

                if SiteUtil.compare(keyword, entity.title) or (item['titleEnglishHanl'] != '' and SiteUtil.compare(keyword, item['titleEnglishHanl'])) or (item['titleAdminHanl'] != '' and SiteUtil.compare(keyword, item['titleAdminHanl'])):
                    if year != 1900:
                        if abs(entity.year-year) == 0:
                            entity.score = score_100
                            score_100 -= 1
                        elif abs(entity.year-year) <= 1:
                            entity.score = score_100 - 1
                        else:
                            entity.score = 80
                    else:
                        entity.score = score_100 -5
                else:
                    entity.score = 80 - (idx*5)

                if entity.score < 10:
                    entity.score = 10
                if entity.score == 10:
                    count += 1
                    if count > 10:
                        continue
                ret.append(entity.as_dict())
            return ret
        except Exception as e:
            logger.error(f"Exception:{str(e)}")
            logger.error(traceback.format_exc())




    @classmethod
    def info_api(cls, code):
        try:
            ret = {'ret':'success', 'data':{}}
            url = "https://movie.daum.net/api/movie/%s/main" % code[2:]
            ret['data']['basic'] = requests.get(url).json()
            return ret
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
            entity = EntityMovie2(cls.site_name, code)
            entity.code_list.append(['daum_id', code[2:]])
            cls.info_basic(code, entity)
            #cls.info_cast(code, entity)
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


    # 2021-04-15
    @classmethod
    def info_basic(cls, code, entity):
        try:
            url = "https://movie.daum.net/api/movie/%s/main" % code[2:]
            data = requests.get(url).json()
            entity.title = data['movieCommon']['titleKorean']
            entity.originaltitle = data['movieCommon']['titleEnglish']
            entity.year = data['movieCommon']['productionYear']
            tmp = data['movieCommon']['plot']
            if tmp is None:
                entity.plot = ''
            else:
                entity.plot = tmp.replace('<b>', '').replace('</b>', '').replace('<br>', '\n')
            try: entity.ratings.append(EntityRatings(float(data['movieCommon']['avgRating']), name=cls.site_name))
            except: pass
            entity.country = data['movieCommon']['productionCountries']
            entity.genre = data['movieCommon']['genres']
            if len(data['movieCommon']['countryMovieInformation']) > 0:
                for country in data['movieCommon']['countryMovieInformation']:
                    if country['country']['id'] == 'KR':
                        entity.mpaa = country['admissionCode']
                        entity.runtime = country['duration']
                        tmp = country['releaseDate']
                        if tmp is not None:
                            entity.premiered = tmp[0:4] + '-' + tmp[4:6] + '-' + tmp[6:8]
                        break
            try:
                if entity.premiered == '':
                    ott = data['movieCommon'].get('ottInformation')
                    if ott != None and len(ott)>0:
                        date = ott[0].get('openDate')
                        if date != None:
                            entity.premiered = date[0:4] + '-' + date[4:6] + '-' + date[6:8]
            except:
                pass
            if data['movieCommon']['mainPhoto'] is not None:
                entity.art.append(EntityThumb(aspect='poster', value=data['movieCommon']['mainPhoto']['imageUrl'], site=cls.site_name, score=70))

            for cast in data['casts']:
                actor = EntityActor('', site=cls.site_name)
                actor.thumb = cast['profileImage']
                actor.name = cast['nameKorean']
                actor.originalname = cast['nameEnglish']
                actor.role = cast['description']
                if actor.role is None:
                    actor.role = cast['movieJob']['job']
                if cast['movieJob']['job'] == u'감독':
                    entity.director.append(actor.name)
                else:
                    entity.actor.append(actor)
            if 'staff' in data:
                for cast in data['staff']:
                    if cast['movieJob']['role'] == u'각본':
                        entity.credits.append(cast['nameKorean'])
        except Exception as e:
            logger.error(f"Exception:{str(e)}")
            logger.error(traceback.format_exc())



    @classmethod
    def info_photo(cls, code, entity):
        try:
            url = "https://movie.daum.net/api/movie/%s/photoList?page=1&size=100" % code[2:]
            data = requests.get(url).json()['contents']
            poster_count = art_count = 0
            max_poster_count = 5
            max_art_count = 5
            for item in data:
                art = EntityThumb()
                # 2021-07-29. 포스터가 있고, 와이드(landscape)형 포스터가 있음. 잠은행
                aspect = ''
                score = 60
                if item['movieCategory'] == '메인 포스터':
                    aspect = 'poster'
                    score = 65
                elif item['movieCategory'].find('포스터') != -1 and item['width'] < item['height']:
                    aspect = 'poster'
                elif item['movieCategory'].find('포스터') != -1 and item['width'] > item['height']:
                    aspect = 'landscape'
                elif item['movieCategory'] == '스틸':
                    aspect = 'landscape'

                if aspect == 'poster' and poster_count < max_poster_count:
                    entity.art.append(EntityThumb(aspect=aspect, value=item['imageUrl'], site=cls.site_name, score=score-poster_count))
                    poster_count += 1
                elif aspect == 'landscape' and art_count < max_art_count:
                    entity.art.append(EntityThumb(aspect=aspect, value=item['imageUrl'], site=cls.site_name, score=score-art_count))
                    art_count += 1
                if poster_count == max_poster_count and art_count == max_art_count:
                    break
        except Exception as e:
            logger.error(f"Exception:{str(e)}")
            logger.error(traceback.format_exc())


    @classmethod
    def info_video(cls, code, entity):
        try:
            for i in range(1, 5):
                url = 'https://movie.daum.net/api/video/list/movie/%s?page=%s&size=20' % (code[2:], i)
                data = requests.get(url).json()
                for item in data['contents']:
                    if item['adultOption'] == 'T':
                        continue
                    extra = EntityExtra2()
                    extra.content_type = 'Trailer' if item['subtitle'].find(u'예고편') != -1 else 'Featurette'
                    extra.mode = 'kakao'
                    extra.content_url = item['videoUrl'].split('/')[-1]
                    extra.title = item['title']
                    extra.thumb = item['thumbnailUrl']
                    entity.extras.append(extra)
                if data['page']['last']:
                    break
        except Exception as e:
            logger.error(f"Exception:{str(e)}")
            logger.error(traceback.format_exc())

