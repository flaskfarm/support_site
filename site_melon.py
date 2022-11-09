import re
from collections import OrderedDict
from urllib.parse import quote

import lxml.html
import requests
from support import default_headers

try:
    from .setup import *
except:
    from support import get_logger
    logger = None
    def set_logger(_):
        global logger
        logger = _

class SiteMelon(object):
    site_name = 'melon'
    
    default_headers = {
        'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/71.0.3578.98 Safari/537.36',
        'Accept' : 'application/json',
    }

    module_char = 'S'
    site_char = 'M'
    artist_site_char = 'A'


    @classmethod
    def base_search(cls, mode, keyword):
        url = f'https://www.melon.com/search/keyword/index.json?query={quote(keyword)}'
        data = requests.get(url, headers=default_headers).json()
        if mode == 'artist' and 'ARTISTCONTENTS' in data:
            return data['ARTISTCONTENTS']
        elif mode == 'album' and 'ALBUMCONTENTS' in data:
            return data['ALBUMCONTENTS']
        elif mode == 'song' and 'SONGCONTENTS' in data:
            return data['SONGCONTENTS']
        return []


    @classmethod       
    def search_artist(cls, keyword, return_format):
        data = cls.base_search('artist', keyword)
        if return_format == 'api':
            return {'ret':'success', 'data':data}
        else:
            ret = {'ret':'success', 'data':[]}
            count = 0
            for idx, item in enumerate(data):
                entity = {'image':''}
                entity['artist'] = item['ARTISTNAME']
                entity['code'] = cls.module_char + cls.artist_site_char + item['ARTISTID']
                if len(item['ARITSTIMG']) > 0:
                    entity['image'] = item['ARITSTIMG'].split('.jpg')[0] + '.jpg'
                entity['desc'] = f"{item['NATIONALITYNAME']} / {item['ACTTYPENAMES']} / {item['SEX']} / {entity['code']}"

                if keyword == entity['artist']:
                    entity['score'] = 99 - idx*5
                else:
                    entity['score'] = 80 - idx*5
                if entity['score'] < 10:
                    entity['score'] = 10
                if entity['score'] == 10:
                    count += 1
                    if count > 10:
                        continue
                ret['data'].append(entity)
            if len(ret['data']) == 0:
                ret['ret'] = 'empty'
            else:
                ret['data'] = list(reversed(sorted(ret['data'], key=lambda k:k['score'])))
            return ret        


    @classmethod
    def info_artist(cls, code): 
        entity = {'code':code, 'artist_id':code[2:], 'genres':[], 'desc':'', 'info_desc':''}
        url = f"https://www.melon.com/artist/detail.htm?artistId={code[2:]}"
        text = requests.get(url, headers=default_headers).text
        root = lxml.html.fromstring(text)
        tag = root.xpath('//p[@class="title_atist"]/strong/following-sibling::text()')[0]
        entity['title'] = tag
        try:
            tag = root.xpath('//span[@id="artistImgArea"]/img')[0]
            entity['image'] = tag.attrib['src'].split('?')[0]
        except Exception as e: 
            logger.error(f'Exception:{e}')
            logger.error(traceback.format_exc())   
        tags = root.xpath('//div[@id="d_artist_intro"]/text()')
        for tag in tags:
            tmp = tag.strip()
            entity['desc'] += '\n' if tmp == '' else tmp + '\n'
        entity['desc'] = entity['desc'].strip()
        entity['info'] = OrderedDict()
        for class_name in ['section_atistinfo03', 'section_atistinfo04', 'section_atistinfo05']:
            dl_tags = root.xpath(f'//div[@class="{class_name}"]/dl/dt')
            dd_tags = root.xpath(f'//div[@class="{class_name}"]/dl/dd')
            for idx in range(len(dl_tags)):
                key = dl_tags[idx].text_content().strip()
                value = re.sub('[\r\n\t]', '', dd_tags[idx].text_content().strip().replace('|', ', '))
                entity['info'][key] = value
                if key == '장르':
                    entity['genres'] = [x.strip() for x in value.split(',')]
                if key == '국적': 
                    entity['countries'] = [value]
                entity['info_desc'] += f"{key} : {value}\n"
        entity['info_desc'] = entity['info_desc'].strip()
        url = f"https://www.melon.com/artist/photoPaging.htm?startIndex=1&pageSize=24&orderBy=LIKE&listType=0&artistId={entity['artist_id']}"
        logger.debug(url)
        text = requests.get(url, headers=default_headers).text
        root = lxml.html.fromstring(text)
        entity['photo'] = []
        tags = root.xpath('//li')
        for tag in tags:
            img_tag = tag.xpath('.//img')[0]
            tmp = img_tag.attrib['src'].split('.jpg')[0].rsplit('_', 1)[0] + '_org.jpg'
            entity['photo'].append(tmp)
        del entity['info']
        return entity


    @classmethod
    def info_artist_albums(cls, code): 
        url = f"https://www.melon.com/artist/albumPaging.htm?startIndex=1&pageSize=1000&listType=0&orderBy=ISSUE_DATE&artistId={code[2:]}"
        return cls.get_album_list(url)


    @classmethod 
    def get_album_list(cls, url):
        ret = []
        try:
            text = requests.get(url, headers=default_headers).text
            root = lxml.html.fromstring(text)
            tags = root.xpath('//li[@class="album11_li"]')
            logger.debug(f"HTML 앨범 수 : {len(tags)}")
            for tag in tags:
                entity = {'artist':'Various Artists'}
                tmp = tag.xpath('.//div/a')[0]
                tmp = tmp.attrib['href']
                match = re.search('\(\'?(?P<code>\d+)\'?\)', tmp)
                if match:
                    entity['code'] = cls.module_char + cls.site_char + match.group('code')
                tmp = tag.xpath('.//img')
                if len(tmp) > 0:
                    entity['image'] = tmp[0].attrib['src']
                entity['album_type'] = tag.xpath('.//div/div/dl/dt/span')[0].text_content().strip().replace('[','').replace(']','').strip()
                entity['title'] = tag.xpath('.//div/div/dl/dt/a')[0].text_content().strip()
                tmp = tag.xpath('.//div/div/dl/dd[1]/div/a')
                if len(tmp) > 0:
                    entity['artist'] = tmp[0].text_content().strip()
                entity['date'] = tag.xpath('.//div/div/dl/dd[3]/span')[0].text_content().strip()
                ret.append(entity)
        except Exception as e:
            logger.debug(f'Exception:{e}')
            logger.debug(traceback.format_exc())
        return ret


    @classmethod
    def search_album_from_html(cls, data, album, artist, artist_code, pub_date):
        if artist_code != None and artist_code.startswith('SA'):
            data = cls.info_artist_albums(artist_code)
            ret = []
            for item in data:
                if album == item['title']:
                    item['score'] = 100
                elif cls.compare(album, item['title']):
                    item['score'] = 95
                elif album in item['title']:
                    item['score'] = 85
                else:
                    from difflib import SequenceMatcher 
                    ratio = SequenceMatcher(None, album, item['title']).ratio()
                    if ratio > 0.80:
                        item['score'] = int(ratio*100)
                if 'score' in item:
                    item['desc'] = f"아티스트 : {artist} / 발매일 : {item['date']}"
                    ret.append(item)
            logger.debug(f"html score count : {len(ret)}")    
            return ret
        else: #if len(pub_date) == 8:
            ret = []
            page_size = 21
            keyword = quote(album)
            for i in range(5):
                url = f"https://www.melon.com/search/album/index.htm?startIndex={1+page_size*i}&pageSize=21&q={keyword}&sortorder=&section=all&sectionId=&genreDir=&sort=weight&mwkLogType=T"
                data = cls.get_album_list(url)
                if len(data) == 0:
                    break
                for item in data:
                    if album == item['title']:
                        item['score'] = 95
                    elif cls.compare(album, item['title']):
                        item['score'] = 90
                    elif album in item['title']:
                        item['score'] = 80
                    else:
                        from difflib import SequenceMatcher 
                        ratio = SequenceMatcher(None, album, item['title']).ratio()
                        if ratio > 0.80:
                            item['score'] = int(ratio*100)
                    if len(pub_date) == 8 and 'score' in item:
                        tmp = item['date'].replace('.', '')
                        if len(tmp) != 8:
                            continue
                        diff = abs(int(pub_date) - int(tmp))
                        if diff == 0:
                            item['score'] += 10
                        if diff < 3:
                            item['score'] += 5
                        if item['score'] >= 100:
                            item['score'] = 100
                    if 'score' in item:
                        item['desc'] = f"아티스트 : {artist} / 발매일 : {item['date']}"
                        ret.append(item)
            logger.debug(f"html2 score count : {len(ret)}")
            return ret

    
    @classmethod
    def search_album(cls, keyword, return_format):
        tmps = keyword.split('|')
        album = tmps[0]
        artist = None
        artist_code = None
        pub_date = None
        if len(tmps) > 1:
            artist = tmps[1]
        if len(tmps) > 2:
            artist_code = tmps[2]
        if len(tmps) > 3:
            pub_date = tmps[3]
        logger.debug(f'artist: {artist}')
        logger.debug(f'album: {album}')
        data = cls.base_search('album', album)
        if return_format == 'api':
            return {'ret':'success', 'data':data}
        else:
            ret = {'ret':'success', 'data':[]}
            ret['data'] = cls.search_album_from_api(data, album, artist, artist_code)
            ret['data'] += cls.search_album_from_html(data, album, artist, artist_code, pub_date)
            if len(ret['data']) == 0:
                ret['ret'] = 'empty'
            else:
                ret['data'] = list(reversed(sorted(ret['data'], key=lambda k:k['score'])))
            return ret   
         
    @classmethod
    def search_album_from_api(cls, data, album, artist, artist_code):
        ret = []
        if data == None:
            return ret
        count = 0
        for idx, item in enumerate(data):
            entity = {'image':''}
            entity['title'] = item['ALBUMNAME']
            entity['artist'] = item['ARTISTNAME']
            entity['code'] = cls.module_char + cls.site_char + item['ALBUMID']
            if len(item['ALBUMIMG']) > 0:
                entity['image'] = item['ALBUMIMG'].split('.jpg')[0] + '.jpg'
            entity['desc'] = f"아티스트 : {item['ARTISTNAME']} / 발매일 : {item['ISSUEDATE'][0:4]}.{item['ISSUEDATE'][4:6]}.{item['ISSUEDATE'][6:8]}"
            if artist == item['ARTISTNAME']:
                if album == item['ALBUMNAME']:
                    entity['score'] = 100
                elif cls.compare(album, item['ALBUMNAME']):
                    entity['score'] = 95 - idx*5
                else:
                    entity['score'] = 90 - idx*5
            else:
                entity['score'] = 80 - idx*5
            if entity['score'] < 10:
                entity['score'] = 10
            if entity['score'] == 10:
                count += 1
                if count > 10:
                    continue
            ret.append(entity)
        return ret


    @classmethod
    def info_album(cls, code): 
        entity = {'code':code, 'album_id':code[2:], 'info_desc':''}
        url = f"https://www.melon.com/album/detail.htm?albumId={entity['album_id']}"
        text = requests.get(url, headers=default_headers).text
        root = lxml.html.fromstring(text)
        tag = root.xpath('//div[@class="thumb"]/a/img')[0]
        entity['image'] = tag.attrib['src'].split('?')[0]
        if entity['image'] == 'https://cdnimg.melon.co.kr':
            entity['image'] = 'https://cdnimg.melon.co.kr/resource/image/web/default/noAlbum_500_160727.jpg'
        tag = root.xpath('//span[@class="gubun"]')[0]
        entity['album_type'] = re.sub('[\[\]]', '', tag.text_content()).strip()
        entity['info_desc'] = f"구분 : {entity['album_type']}\n"
        tag = root.xpath('//div[@class="song_name"]/strong/following-sibling::text()')[0]
        entity['title'] = tag.strip()
        tag = root.xpath('//div[@class="artist"]/a')
        tags = root.xpath('//div[@class="ellipsis artist"]/a')
        if len(tag) == 0 and len(tags) > 0:
            tag = tags
        if len(tag) > 0:
            tag = tag[0]
            tmp = tag.attrib['href']
            entity['artist_id'] = re.search("'(?P<id>\d+)'", tmp).group('id')
            tag = tag.xpath('.//span')[0]
            entity['artist_name'] = tag.text_content().strip()
        else:
            tag = root.xpath('//div[@class="artist"]')[0]
            entity['artist_name'] = tag.text_content().strip()
            entity['artist_id'] = ''
        entity['info'] = {}
        dt_tags = root.xpath(f'//div[@class="meta"]/dl[@class="list"]/dt')
        dd_tags = root.xpath(f'//div[@class="meta"]/dl[@class="list"]/dd')
        for idx in range(len(dt_tags)):
            key = dt_tags[idx].text_content().strip()
            value = re.sub('[\r\n\t]', '', dd_tags[idx].text_content().strip().replace('|', ', '))
            entity['info'][key] = value
            if key == '장르':
                entity['genres'] = [x.strip() for x in value.split(',')]
            if key == '발매일':
                entity['originally_available_at'] = value
            if key == '기획사':
                entity['studio'] = value
            entity['info_desc'] += f"{key} : {value}\n"
        tag = root.xpath(f'//span[@id="gradPointLayer"]')
        if len(tag) > 0:
            entity['rating'] = tag[0].text_content()
        tags = root.xpath('//div[@class="dtl_albuminfo"]/div//text()')
        entity['desc'] = ''
        for tag in tags:
            tmp = tag.strip()
            entity['desc'] += '\n' if tmp == '' else tmp + '\n'
        entity['desc'] = entity['desc'].strip()

        # https://www.melon.com/album/detail.htm?albumId=6690 
        # 9번 트랙 없음
        def song_append(data, cd_index, song_data):
            tmp = int(cd_index.replace('cd', ''))
            if len(data) < tmp:
                data.append([])
            data[tmp-1].append(song_data)
            if len(data[tmp-1]) != song_data['number']:
                logger.error(f"{tmp} {song_data['number']}")
                logger.error("number wrong!!")
        entity['track'] = []
        tags = root.xpath('//*[@id="frm"]/div/table/tbody/tr')
        for tag in tags:
            if 'data-group-items' not in tag.attrib:
                continue
            cd_index = tag.attrib['data-group-items']
            song_data = {'has_mv':True}
            song_data['number'] = int(tag.xpath('.//td[2]/div[1]/span[1]/text()')[0])
            tmp_tag = tag.xpath('.//td[4]/div/div/div[1]/span/a')
            if len(tmp_tag) > 0:
                tmp_tag = tmp_tag[0]
                song_data['title'] = tmp_tag.text_content().strip()
                match = re.search("\('(?P<menu_id>\d+)',\s?'?(?P<id>\d+)'?", tmp_tag.attrib['href'])
                song_data['song_id'] = match.group('id')
                song_data['menu_id'] = match.group('menu_id')
                span_tags = tag.xpath('.//td[4]/div[1]/div[1]/div[1]/span/span')
                if len(span_tags) == 0:
                    song_data['is_title'] = False
                elif len(span_tags) == 1 and span_tags[0].text_content().strip():
                    song_data['is_title'] = True
            else:
                # 링크 없는 것들 있음
                tmp_tag = tag.xpath('.//td[4]/div/div/div[1]/span/span')[-1]
                song_data['title'] = tmp_tag.text_content().strip()
                song_data['song_id'] = ''
                song_data['menu_id'] = ''
                tmp_tag = tag.xpath('.//td[4]/div/div/div[1]/span/span')[0]
                song_data['is_title'] = False
                if tmp_tag.text_content().strip() == 'Title':
                    song_data['is_title'] = True
            tmp_tag = tag.xpath('.//td[4]/div/div/div[2]/a')
            if len(tmp_tag) > 0:
                tmp_tag = tmp_tag[0]
                song_data['singer'] = tmp_tag.text_content().strip()
                song_data['singer_id'] = re.search("'(?P<id>\d+)'", tmp_tag.attrib['href']).group('id')
            else:
                song_data['singer'] = song_data['singer_id'] = ''
            tmp_tag = tag.xpath('.//td[9]/div/button')[0]
            if tmp_tag.attrib.get('disabled', None) == 'disabled':
                song_data['has_mv'] = False
            tmp_tag = tag.xpath('.//td[5]/div/button/span[2]/text()')
            try:
                song_data['rating_count'] = int(tmp_tag[1].replace(',', '').strip())
            except:
                logger.error("rating_count error")
                song_data['rating_count'] = 0
            song_append(entity['track'], cd_index, song_data)
        tag = root.xpath('//div[@class="section_movie"]')
        if len(tags) > 0:
            tags = tag[0].xpath('.//div[2]/ul/li')
            for tag in tags:
                tmp = tag.xpath('.//div/a')
                if len(tmp) > 0:
                    match = re.search("\('(?P<menu_id>\d+)',\s?'?(?P<id>\d+)'?", tmp[0].attrib['href'])
                    if match == None:
                        logger.error(tmp[0].attrib['href'])
                        continue
                    title = tmp[1].text_content().strip()
                    mv_id = match.group('id')
                    find = False
                    for cd in entity['track']:
                        for song in cd:
                            if song['title'] == title:
                                img_tag = tmp[0].xpath('.//img')[0]
                                song['mv_image'] = img_tag.attrib['src'].split('.jpg')[0] + '.jpg'
                                song['mv_id'] = mv_id
                                find = True
                                break
                        if find:
                            break
        return entity


    @classmethod
    def info_song(cls, song_id):
        try:
            entity = {'ret':'fail', 'song_id':song_id, 'lyric':'', 'producer':{}}
            url = f"https://www.melon.com/song/detail.htm?songId={song_id}"
            text = requests.get(url, headers=default_headers).text
            root = lxml.html.fromstring(text)
            tag = root.xpath('//div[@class="thumb"]/a/img')[0]
            entity['image'] = tag.attrib['src'].split('?')[0]
            tag = root.xpath('//div[@class="song_name"]/strong/following-sibling::text()')[0]
            entity['title'] = tag.strip()
            tag = root.xpath('//div[@class="artist"]/a')
            if len(tag) == 1:
                tag = tag[0]
                tmp = tag.attrib['href']
                entity['artist_id'] = re.search("'(?P<id>\d+)'", tmp).group('id')
                tag = tag.xpath('.//span')[0]
                entity['artist_name'] = tag.text_content().strip()
            else:
                tag = root.xpath('//div[@class="artist"]')[0]
                entity['artist_name'] = tag.text_content().strip()
                entity['artist_id'] = ''
            entity['info'] = {}
            dt_tags = root.xpath(f'//div[@class="meta"]/dl[@class="list"]/dt')
            dd_tags = root.xpath(f'//div[@class="meta"]/dl[@class="list"]/dd')
            for idx in range(len(dt_tags)):
                key = dt_tags[idx].text_content().strip()
                value = dd_tags[idx].text_content().strip().replace('|', ', ')
                entity['info'][key] = re.sub('[\r\n\t]', '', value)
                if key == '앨범':
                    tmp = dd_tags[idx].xpath('.//a')
                    if len(tmp) > 0:
                        entity['album_id'] = re.search("'(?P<id>\d+)'", tmp[0].attrib['href']).group('id')
                        entity['album_name'] = value
            tags = root.xpath('//div[@id="d_video_summary"]/text()')
            entity['lyric'] = '\n'.join([x.strip() for x in tags])
            tags = root.xpath(f'//div[@class="section_prdcr"]//li')
            for tag in tags:
                meta = tag.xpath('.//div[@class="meta"]')[0].text_content().strip()
                name = tag.xpath('.//div[@class="ellipsis artist"]')[0].text_content().strip()
                if meta not in entity['producer']:
                    entity['producer'][meta] = []
                entity['producer'][meta].append(name)
            entity['ret'] = 'success'
            return entity
        except Exception as e:
            logger.debug(f'Exception:{e}')
            logger.debug(traceback.format_exc())


    @classmethod
    def compare(cls, a, b):
        return (cls.remove_special_char(a).replace(' ', '').lower() == cls.remove_special_char(b).replace(' ', '').lower())

    
    @classmethod
    def remove_special_char(cls, text):
        return re.sub('[-=+,#/\?:^$.@*\"※~&%ㆍ!』\\‘|\(\)\[\]\<\>`\'…》]', '', text)
