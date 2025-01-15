
import urllib.parse
from xml import etree

import xmltodict
from framework import SystemModelSetting

from . import SiteNaver, SiteUtil
from .setup import *


class SiteNaverBook(SiteNaver):
    @classmethod
    def search_api(cls, title, auth, cont, isbn, publ):
        logger.debug(f"책 검색 : [{title}] [{auth}] ")
        trans_papago_key = cls._naver_key
        for tmp in trans_papago_key.split('\n'):
            client_id, client_secret = tmp.strip().split(',')
            try:
                if client_id == '' or client_id is None or client_secret == '' or client_secret is None:
                    return title
                url = f"https://openapi.naver.com/v1/search/book_adv.xml?display=100"
                if title != '':
                    url += f"&d_titl={urllib.parse.quote(str(title))}"
                if auth != '':
                    url += f"&d_auth={urllib.parse.quote(str(auth))}"
                if cont != '':
                    url += f"&d_cont={urllib.parse.quote(str(cont))}"
                if isbn != '':
                    url += f"&d_isbn={urllib.parse.quote(str(isbn))}"
                if publ != '':
                    url += f"&d_publ={urllib.parse.quote(str(publ))}"
                requesturl = urllib.request.Request(url)
                requesturl.add_header("X-Naver-Client-Id", client_id)
                requesturl.add_header("X-Naver-Client-Secret", client_secret)
                response = urllib.request.urlopen(requesturl)
                data = response.read()
                data = json.loads(json.dumps(xmltodict.parse(data)))
                rescode = response.getcode()
                if rescode == 200:
                    return data
                else:
                    continue
            except Exception as e:
                logger.error(f"Exception:{str(e)}")
                logger.error(traceback.format_exc())


    @classmethod
    def search(cls, titl, auth, cont, isbn, publ):
        data = cls.search_api(titl, auth, cont, isbn, publ)
        result_list = []
        ret = {}
        if data['rss']['channel']['total'] != '0':
            tmp = data['rss']['channel']['item']
            if type(tmp) == type({}):
                tmp = [tmp]
            for idx, item in enumerate(tmp):
                entity = {}
                #entity['code'] = 'BN' + item['link'].split('bid=')[1]
                entity['code'] = 'BN' + item['link'].rsplit('/', 1)[1]
                entity['title'] = item['title'].replace('<b>', '').replace('</b>', '')
                entity['image'] = item['image']
                try:
                    entity['author'] = item['author'].replace('<b>', '').replace('</b>', '')
                except:
                    entity['author'] = ''
                entity['publisher'] = item['publisher']
                entity['description'] = ''
                try:
                    if item['description'] is not None:
                        entity['description'] = item['description'].replace('<b>', '').replace('</b>', '')
                except:
                    pass
                if titl in entity['title'] and auth in entity['author']:
                    if entity['image'] != None:
                        entity['score'] = 100 - idx
                    else:
                        entity['score'] = 90 - idx
                elif titl in entity['title']:
                    entity['score'] = 95 - idx*5
                else:
                    entity['score'] = 90 - idx*5
                if entity['description'] == '':
                    entity['score'] += -10
                result_list.append(entity)
        else:
            logger.warning("검색 실패")
        if result_list:
            ret['ret'] = 'success'
            ret['data'] = result_list
        else:
            ret['ret'] = 'empty'
        return ret


    @classmethod
    def change_for_plex(cls, text):
        return text.replace('<p>', '').replace('</p>', '').replace('<br/>', '\n').replace('&lt;', '<').replace('&gt;', '>').replace('&amp;', '&').replace('&apos;', '‘').replace('&quot;', '"').replace('&#13;', '').replace('<b>', '').replace('</b>', '')


    @classmethod
    def info(cls, code):
        #url = 'http://book.naver.com/bookdb/book_detail.php?bid=' + code[2:].rstrip('A')
        url = "https://search.shopping.naver.com/book/catalog/" + code[2:].rstrip('A')
        logger.warning(url)
        entity = {}
        root = SiteUtil.get_tree(url, headers=cls.default_headers)
        entity['code'] = code
        title_tag = root.xpath('//h2[starts-with(@class, "bookTitle_book_name__")]')[0]
        entity['title'] = title_tag.text
        try: entity['sub_title'] = title_tag.xpath('following-sibling::span')[0].text
        except: entity['sub_title'] = ''
        entity['poster'] = root.xpath('//div[starts-with(@class, "bookImage_img_wrap__")]/img')[0].attrib['src']
        entity['ratings'] = root.xpath('//span[starts-with(@class, "bookReview_grade__")]/descendant::text()')[1]
        entity['desc'] = root.xpath('//div[starts-with(@class, "infoItem_data_text")]')[0].text
        tags = root.xpath('//li[starts-with(@class, "bookTitle_item_info__")]')
        for tag in tags:
            try:
                name = tag.xpath('div[1]/text()')[0]
                #P.logger.error(name)
                value = tag.xpath('div[2]/span/text()')[0]
                if name == '저자':
                    entity['author'] = value
                elif name == '출판':
                    entity['publisher'] = value
                elif name == '출간':
                    entity['premiered'] = value
            except:
                pass
        entity['author_intro'] = root.xpath('//p[starts-with(@class, "asideAuthorIntro_introduce__")]/text()')[0]
        return entity
