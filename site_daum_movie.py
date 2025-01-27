import urllib.parse

import requests

from . import SiteDaum, SiteUtil
from .entity_base import (EntityActor, EntityExtra2, EntityMovie2,
                          EntityRatings, EntitySearchItemMovie, EntityThumb)
from .setup import *

endofservice = {'ret': 'exception', 'data': '다음 영화 검색 API 종료 : https://magazine.daum.net/daummovie_notice/6572a022c4ce232353605038'}

class SiteDaumMovie(SiteDaum):
    site_base_url = 'https://search.daum.net'
    module_char = 'M'
    site_char = 'D'

    @classmethod
    def search(cls, keyword: str, year: int = None) -> dict[str, str | list]:
        search_results = []
        logger.debug(f'Daum search: [{keyword}] [{year}]')
        try:
            query = {
                'w': 'tot',
                'rtmaxcoll': 'EM1',
                'q': keyword,
                'irt': 'movie-single',
            }
            request_url = cls.get_request_url(query=query)
            root = cls.get_tree(request_url)

            movie_sections = root.xpath('//h2[@class="screen_out" and contains(text(), "영화")]/following-sibling::div')
            if not movie_sections:
                return {'ret': 'empty'}
            movie_section = movie_sections[0]

            entity = EntitySearchItemMovie(cls.site_name)

            # 제목, daum_id
            c_titles = movie_section.xpath('.//c-header-content/c-title')
            if c_titles:
                entity.title = c_titles[0].text.strip()
                href = c_titles[0].attrib['data-href']
                query = dict(urllib.parse.parse_qsl(href))
                if query.get('irk'):
                    entity.code = f'MD{query.get("irk")}'
                entity.link = href if 'http' in href else urllib.parse.urljoin(cls.get_request_url(), href)

            # 영어 제목, 연도
            eng_title_texts = movie_section.xpath('.//c-header-content/c-combo[@data-type="info"]/c-frag/text()')
            if eng_title_texts:
                eng_title, _, release_year = eng_title_texts[0].partition(',')
                entity.originaltitle = eng_title.strip()
                try:
                    entity.year = int(release_year.strip())
                except:
                    entity.year = 1900
                entity.code += f'#{urllib.parse.quote(entity.title)}'

            # 포스터
            c_thumbs = movie_section.xpath('.//c-doc-content//c-thumb')
            if c_thumbs:
                entity.image_url = c_thumbs[0].attrib['data-original-src']

            # 줄거리
            c_summaries = movie_section.xpath('.//c-summary')
            if c_summaries:
                entity.desc = c_summaries[0].text.strip()

            entity.score = 100
            search_results.append(entity.as_dict())

            '''
            # { "info": { "type": "feed", "collection_name": "영화" }, "param": { "w": "tot", "rtmaxcoll": "EM1" }, "data": { "TH_IMAGE_URL_0": "https://search1.kakaocdn.net/thumb/R448x0.fpng/?fname=http%3A%2F%2Ft1.daumcdn.net%2Ftvpot%2Fthumb%2Fv26b9dxHspHAitTt6AtnxB6%2Fthumb.png", "TH_W_0": 448, "TH_H_0": 251, "TH_MOBILE_WEB_URL_0": "https://tv.kakao.com/channel/20341/cliplink/73580055", "TH_WEB_URL_0": "https://tv.kakao.com/channel/20341/cliplink/73580055", "TH_PLAY_TIME_0": 140, "TITLE": "인터스텔라", "TITLE_MOBILE_WEB_URL": "https://m.search.daum.net/search?w=tot&rtmaxcoll=EM1&q=%EC%9D%B8%ED%84%B0%EC%8A%A4%ED%85%94%EB%9D%BC&irt=movie-single&irk=62730", "TITLE_WEB_URL": "https://search.daum.net/search?w=tot&rtmaxcoll=EM1&q=%EC%9D%B8%ED%84%B0%EC%8A%A4%ED%85%94%EB%9D%BC&irt=movie-single&irk=62730", "DESCRIPTION": "SF | 2016.01.14 재개봉\\n평점: 8.3\\n감독: 크리스토퍼 놀란\\n출연: 매튜 맥커너히, 앤 해서웨이, 마이클 케인 외" }, "custom": {"max": {"title": 50, "description": 150}} }

            json_texts = movie_section.xpath('.//script/text()')
            if json_texts:
                json_info = json.loads(json_texts[0].strip())
                if not entity.title:
                    entity.title = json_info.get('data', {}).get('title')
                clip_url = json_info.get('data', {}).get('TH_WEB_URL_0')
                home_url = json_info.get('data', {}).get('TITLE_WEB_URL')
            '''

            # 동명영화
            c_docs = movie_section.xpath('.//c-scr-similar/c-doc')
            if c_docs:
                for idx, c_doc in enumerate(c_docs):
                    s_info = EntitySearchItemMovie(cls.site_name)
                    s_info.desc = 'Daum'
                    c_contents = c_doc.xpath('./c-contents-desc-sub')
                    if c_contents:
                        try:
                            s_info.year = int(c_contents[0].text.strip())
                        except:
                            continue
                    c_titles = c_doc.xpath('./c-title')
                    if c_titles:
                        s_info.title = c_titles[0].text.strip()
                        href = c_titles[0].attrib['data-href']
                        query = dict(urllib.parse.parse_qsl(href))
                        q_ = {
                            'w': 'cin',
                            'q': s_info.title,
                            'DA': 'EM1',
                            'rtmaxcoll': 'EM1',
                            'irt': 'movie-single-tab',
                            'irk': query.get('irk', ''),
                            'refq': s_info.title,
                            'tabInfo': 'total',
                        }
                        s_info.link = cls.get_request_url(query=q_)
                        s_info.code = f'MD{query.get("irk", "")}#{urllib.parse.quote(s_info.title)}'
                    if not s_info.title or not s_info.year:
                        continue
                    c_thumbs = c_doc.xpath('./c-thumb')
                    if c_thumbs:
                        img_src = c_thumbs[0].attrib['data-original-src']
                        s_info.image_url = img_src if 'http' in img_src else ''
                    search_results.append(s_info.as_dict())

            # 스코어
            for idx, sr in enumerate(search_results):
                if SiteUtil.compare(keyword, sr['title']):
                    if year != 1900:
                        discrepancy = abs(sr['year'] - year)
                        if discrepancy == 0:
                            sr['score'] = 100
                        elif discrepancy < 2:
                            sr['score'] = 90
                        else:
                            sr['score'] = 80
                    else:
                        sr['score'] = 75
                else:
                    sr['score'] = 75 - (idx * 5)
        except:
            logger.error(traceback.format_exc())
        if search_results:
            search_results = sorted(search_results, key= lambda x:x.get('score', 0), reverse=True)
            return {'ret': 'success', 'data': search_results}
        return {'ret': 'empty'}

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
    def get_movie_info(cls, code: str) -> dict[str, str | list]:
        movie_info = {}
        try:
            code_ = code.split('#')
            title = urllib.parse.unquote(code_[1])
            logger.info(f'Daum info: {title=}')
            '''
            https://search.daum.net/search?w=cin&q=%ED%82%A4%EB%93%9C&DA=EM1&rtmaxcoll=EM1&irt=movie-single-tab&irk=13552&refq=%ED%82%A4%EB%93%9C&tabInfo=total
            '''
            query = {
                'w': 'cin',
                'q': title,
                'DA': 'EM1',
                'rtmaxcoll': 'EM1',
                'irt': 'movie-single-tab',
                'irk': code_[0][2:],
                'refq': title,
                'tabInfo': 'total',
            }
            url = cls.get_request_url(query=query)
            root = cls.get_tree(url)
            movie_divs = root.xpath('//h2[@class="screen_out" and contains(text(), "영화")]/following-sibling::div')
            if movie_divs:
                movie_section = movie_divs[0]
            else:
                return

            entity = EntityMovie2(cls.site_name, None)
            entity.code = code
            entity.code_list.append(['daum_id', code_[0][2:]])

            # 제목, daum_id
            c_titles = movie_section.xpath('.//c-header-content/c-title')
            if c_titles:
                entity.title = entity.sorttitle = entity.originaltitle = c_titles[0].text.strip()

            # 영어 제목, 연도
            eng_title_texts = movie_section.xpath('.//c-header-content/c-combo[@data-type="info"]/c-frag/text()')
            if eng_title_texts:
                eng_title, _, release_year = eng_title_texts[0].partition(',')
                entity.originaltitle = eng_title.strip()
                try:
                    entity.year = int(release_year.strip())
                except:
                    entity.year = 1900
                entity.code += f'#{entity.year}#{urllib.parse.quote(entity.title)}'

            # 포스터
            c_thumbs = movie_section.xpath('.//c-doc-content//c-thumb')
            if c_thumbs:
                try:
                    w, h = int(c_thumbs[0].attrib['width']), int(c_thumbs[0].attrib['height'])
                    aspect = 'poster' if h > w else 'landscape'
                    entity.art.append(EntityThumb(aspect=aspect, value=c_thumbs[0].attrib['data-original-src'], site=cls.site_name, score=65))
                except:
                    logger.error(traceback.format_exc())

            # 기본 정보
            desc_titles = movie_section.xpath('.//c-list-grid-desc[@slot="contents"]/dt')
            desc_details = movie_section.xpath('.//c-list-grid-desc[@slot="contents"]/dd')
            for idx, dt in enumerate(desc_titles):
                try:
                    match dt.text:
                        case '개봉' | '재개봉':
                            release_date = cls.parse_date_text(desc_details[idx].xpath('string()').strip())
                            entity.premiered = release_date.strftime('%Y-%m-%d')
                            if not entity.year:
                                entity.year = release_date.year
                        case '국가':
                            entity.country.extend([c.strip() for c in desc_details[idx].text.split(',') if c])
                        case '장르':
                            entity.genre.extend([g.strip() for g in desc_details[idx].text.split('/') if g])
                        case '등급':
                            entity.mpaa = desc_details[idx].text.strip()
                        case '시간':
                            running_time = desc_details[idx].text.strip()
                            digits = [c for c in running_time if c.isdigit()]
                            entity.runtime = int(''.join(digits))
                        case '평점':
                            ratings = desc_details[idx].xpath('.//c-star/text()')
                            if ratings:
                                rating = ratings[0].strip()
                                if rating.isdigit():
                                    entity.ratings.append(EntityRatings(float(rating), name=cls.site_name))
                        case '관객수':
                            entity.customers = desc_details[idx].text.strip()
                except:
                    logger.error(traceback.format_exc())

            # 줄거리
            c_summaries = movie_section.xpath('.//c-summary')
            if c_summaries:
                entity.plot = c_summaries[0].text.strip()

            # 감독/출연
            for c_doc in movie_section.xpath('.//c-list-doc[@data-title="감독/출연"]/c-doc'):
                try:
                    actor = EntityActor(None, site=cls.site_name)
                    c_titles = c_doc.xpath('./c-title')
                    if c_titles:
                        actor.name = c_titles[0].text.strip()
                    c_thumbs = c_doc.xpath('./c-thumb')
                    if c_thumbs:
                        thumb_url = c_thumbs[0].attrib['data-original-src']
                        actor.thumb = thumb_url if 'http' in thumb_url else urllib.parse.urljoin(cls.get_request_url(), thumb_url)
                    c_contents_descs = c_doc.xpath('./c-contents-desc')
                    if c_contents_descs:
                        actor.role = c_contents_descs[0].text.replace('역', '').strip()
                    c_contents_desc_subs = c_doc.xpath('./c-contents-desc-sub')
                    if c_contents_desc_subs:
                        sub_role = c_contents_desc_subs[0].text.strip()
                        if sub_role == '감독':
                            entity.director = actor.name
                            continue
                    entity.actor.append(actor)
                except:
                    logger.error(traceback.format_exc())

            # 영상
            for c_doc in movie_section.xpath('.//c-list-doc[@data-title="영상"]/c-doc'):
                try:
                    extra = EntityExtra2()
                    c_thumbs = c_doc.xpath('./c-thumb')
                    if c_thumbs:
                        thumb_url = c_thumbs[0].attrib['data-original-src']
                        content_url = c_thumbs[0].attrib['data-href']
                        extra.thumb = thumb_url if 'http' in thumb_url else urllib.parse.urljoin(cls.get_request_url(), thumb_url)
                        extra.content_url = content_url if 'http' in thumb_url else urllib.parse.urljoin(cls.get_request_url(), content_url)
                    c_titles = c_doc.xpath('./c-title')
                    if c_titles:
                        extra.title = c_titles[0].text.strip() if c_titles[0].text else ''
                    c_contents_desc_subs = c_doc.xpath('./c-contents-desc-sub')
                    if c_contents_desc_subs:
                        date = cls.parse_date_text(c_contents_desc_subs[0].text.strip())
                        extra.premiered = date.strftime('%Y-%m-%d')
                    entity.extras.append(extra)
                except:
                    logger.error(traceback.format_exc())

            # 포토
            for c_thumb in movie_section.xpath('.//c-card[@id="em1Coll_photos"]//c-thumb'):
                try:
                    thumb_url = c_thumb.attrib['data-original-src']
                    thumb_url = thumb_url if 'http' in thumb_url else urllib.parse.urljoin(cls.get_request_url(), thumb_url)
                    w, h = int(c_thumb.attrib['width']), int(c_thumb.attrib['height'])
                    aspect = 'poster' if h > w else 'landscape'
                    entity.art.append(EntityThumb(aspect=aspect, value=thumb_url, site=cls.site_name, score=50))
                except:
                    logger.error(traceback.format_exc())

            # 시리즈
            '''
            for c_doc in root.xpath('//*[@id="em1Coll_series"]//c-list-doc[@data-title="시리즈"]//c-doc'):
                c_thumb = c_doc.find('c-thumb')
                if c_thumb:
                    c_thumb.attrib['data-original-src']
            '''

            # 추가정보 (crew, clip, photo)
            '''
            extras = {}
            for item in movie_section.xpath('.//c-header-tab-item'):
                href = item.attrib['data-href']
                query = dict(urllib.parse.parse_qsl(href))
                key = query.get('tabInfo', 'total')
                extras[key] = href
            extras = {item.text.strip():item.attrib['data-href'] for item in movie_section.xpath('.//c-header-tab-item')}
            '''
            movie_info = entity.as_dict()
        except:
            logger.error(traceback.format_exc())
        return movie_info

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
        return endofservice
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
        data = cls.get_movie_info(code)
        if data:
            return {
                'ret': 'success',
                'data': data,
            }
        else:
            return {
                'ret': 'exception',
                'data': 'No information',
            }


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
                    entity.director = actor.name
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

