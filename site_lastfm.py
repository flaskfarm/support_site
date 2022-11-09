from urllib.parse import quote

import lxml.html
import requests
from support import d, default_headers

from . import SiteUtil
from .setup import *


class SiteLastfm(object):
    
    default_headers = {
        'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/71.0.3578.98 Safari/537.36',
        'Accept' : 'application/json',
    }
    apikey = '2aca847884c23eb85e372efc857c3c90'

    @classmethod
    def info_artist(cls, entity, photo=True, youtube=True):
        url = f"https://ws.audioscrobbler.com/2.0/?method=artist.getinfo&artist={quote(entity['title'])}&api_key={cls.apikey}&format=json"
        data = requests.get(url).json()
        if data['artist']['name'] != entity['title']:
            return entity
        text = requests.get(data['artist']['url'], headers=default_headers).text
        root = lxml.html.fromstring(text)
        tag = root.xpath('//h1[@class="header-new-title"]')[0].text_content().strip()
        logger.error(tag)
        if photo:
            entity['photo_lastfm'] = []
            tags = root.xpath('//li[@class="sidebar-image-list-item"]')
            for tag in tags:
                tmp = tag.xpath('.//a/img')[0]
                src = tmp.attrib['src']
                entity['photo_lastfm'].append(src.replace('avatar170s', '770x0'))

        if youtube:
            try: import yt_dlp
            except:
                try: 
                    os.system("{} install yt-dlp".format(app.config['config']['pip']))
                    import yt_dlp
                except:
                    return entity
            entity['extras'] = []
            ydl = yt_dlp.YoutubeDL({"quiet": True})
            tags = root.xpath('//td[@class="chartlist-play"]/a')
            for tag in tags:
                try:
                    if tag.attrib['data-playlink-affiliate'] != 'youtube':
                        continue
                    item = {
                        'mode': 'youtube',
                        'type': 'musicvideo',
                        #'name' : tag.attrib['data-track-name'],
                        'param' : tag.attrib['data-youtube-id'],
                    }
                    target_url = f"https://www.youtube.com/watch?v={item['param']}"
                    result = ydl.extract_info(target_url, download=False)
                    item['thumb'] = result['thumbnail']
                    item['title'] = result['fulltitle']
                    entity['extras'].append(item)
                except:
                    logger.debug(target_url)
        return entity

    
    @classmethod
    def search_album(cls, keyword, return_format):
        tmps = keyword.split('|')
        album = tmps[0]
        artist = None
        artist_code = None
        if len(tmps) > 1:
            artist = tmps[1]
        if len(tmps) > 2:
            artist_code = tmps[2]
        logger.debug(f'artist: {artist}')
        logger.debug(f'album: {album}')
        data = cls.base_search('album', album)
        logger.debug(d(data))
        if return_format == 'api':
            return {'ret':'success', 'data':data}
        else:
            ret = {'ret':'success', 'data':[]}
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
                    elif SiteUtil.compare(album, item['ALBUMNAME']):
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
                ret['data'].append(entity)
            if len(ret['data']) == 0:
                ret['ret'] = 'empty'
            else:
                ret['data'] = list(reversed(sorted(ret['data'], key=lambda k:k['score'])))
            return ret   


    @classmethod
    def info_album(cls, code): 
        entity = {'code':code, 'album_id':code[2:], 'info_desc':''}
        url = f"https://www.melon.com/album/detail.htm?albumId={entity['album_id']}"
        text = requests.get(url, headers=default_headers).text
        root = lxml.html.fromstring(text)
        tag = root.xpath('//div[@class="thumb"]/a/img')[0]
        entity['image'] = tag.attrib['src'].split('?')[0]
        tag = root.xpath('//span[@class="gubun"]')[0]
        entity['album_type'] = re.sub('[\[\]]', '', tag.text_content()).strip()
        entity['info_desc'] = f"구분 : {entity['album_type']}\n"
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

        def song_append(data, cd_index, song_data):
            tmp = int(cd_index.replace('cd', ''))
            #logger.error(tmp)
            if len(data) < tmp:
                data.append([])
            #
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
            span_tags = tag.xpath('.//td[4]/div[1]/div[1]/div[1]/span/span')
            if len(span_tags) == 0:
                song_data['is_title'] = False
            elif len(span_tags) == 1 and span_tags[0].text_content().strip():
                song_data['is_title'] = True
            tmp_tag = tag.xpath('.//td[4]/div/div/div[1]/span/a')[0]
            song_data['title'] = tmp_tag.text_content().strip()
            match = re.search("\('(?P<menu_id>\d+)',\s?'?(?P<id>\d+)'?", tmp_tag.attrib['href'])
            song_data['song_id'] = match.group('id')
            song_data['menu_id'] = match.group('menu_id')
            tmp_tag = tag.xpath('.//td[4]/div/div/div[2]/a')[0]
            song_data['singer'] = tmp_tag.text_content().strip()
            song_data['singer_id'] = re.search("'(?P<id>\d+)'", tmp_tag.attrib['href']).group('id')
            tmp_tag = tag.xpath('.//td[9]/div/button')[0]
            if tmp_tag.attrib.get('disabled', None) == 'disabled':
                song_data['has_mv'] = False
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
                                logger.info(f"MV: {song['title']}")
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
