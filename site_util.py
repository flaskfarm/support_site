import urllib.parse
import html

import requests
from tool import ToolUtil
import lxml.html

from .setup import *


class SiteUtil(object):

    session = requests.Session()

    default_headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/93.0.4577.82 Safari/537.36',
        'Accept' : 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8',
        'Accept-Language' : 'ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7',
    }

    @classmethod
    def initialize(cls):
        logger.debug('Request session has been initialized.')
        cls.session = requests.Session()

    @classmethod
    def get_tree(cls, url, proxy_url=None, headers=None, post_data=None, cookies=None, verify=None):
        text = cls.get_text(url, proxy_url=proxy_url, headers=headers, post_data=post_data, cookies=cookies, verify=verify)
        if text is None:
            return
        return lxml.html.fromstring(text)

    @classmethod
    def get_text(cls, url, proxy_url=None, headers=None, post_data=None, cookies=None, verify=None):
        res = cls.get_response(url, proxy_url=proxy_url, headers=headers, post_data=post_data, cookies=cookies, verify=verify)
        return res.text

    @classmethod
    def get_response(cls, url, proxy_url=None, headers=None, post_data=None, cookies=None, verify=None):
        proxies = None
        if proxy_url is not None and proxy_url != '':
            proxies = {"http"  : proxy_url, "https" : proxy_url}
        if headers is None:
            headers = cls.default_headers
        if post_data is None:
            if verify == None:
                res = cls.session.get(url, headers=headers, proxies=proxies, cookies=cookies)
            else:
                res = cls.session.get(url, headers=headers, proxies=proxies, cookies=cookies, verify=verify)
        else:
            if verify == None:
                res = cls.session.post(url, headers=headers, proxies=proxies, data=post_data, cookies=cookies)
            else:
                res = cls.session.post(url, headers=headers, proxies=proxies, data=post_data, cookies=cookies, verify=verify)
        if not 300 > res.status_code > 199:
            logger.warning(f'http_code={res.status_code} url="{res.url}" "body="{html.escape(res.text)}"')
        return res


    @classmethod
    def process_image_mode(cls, image_mode, image_url, proxy_url=None):
        if image_url is None:
            return
        ret = image_url
        if image_mode == '1':
            tmp = '{ddns}/metadata/api/image_proxy?url=' + urllib.parse.quote_plus(image_url)
            if proxy_url is not None:
                tmp += '&proxy_url=' + urllib.parse.quote_plus(proxy_url)
            ret = ToolUtil.make_apikey_url(tmp)
        elif image_mode == '2':
            tmp = '{ddns}/metadata/api/discord_proxy?url=' + urllib.parse.quote_plus(image_url)
            ret = ToolUtil.make_apikey_url(tmp)
        elif image_mode == '3': # 고정 디스코드 URL.
            ret = cls.discord_proxy_image(image_url)
        elif image_mode == '4': #landscape to poster
            ret = '{ddns}/metadata/normal/image_process.jpg?mode=landscape_to_poster&url=' + urllib.parse.quote_plus(image_url)
            ret = ret.format(ddns=F.SystemModelSetting.get('ddns'))
        elif image_mode == '5':  #로컬에 포스터를 만들고
            from PIL import Image
            im = Image.open(requests.get(image_url, stream=True).raw)
            width, height = im.size
            filename = 'proxy_%s.jpg' % str(time.time())
            filepath = os.path.join(F.config['path_data'], 'tmp', filename)
            if width > height:
                left = width/1.895734597
                top = 0
                right = width
                bottom = height
                poster = im.crop((left, top, right, bottom))
                poster.save(filepath)
            else:
                im.save(filepath)
            ret = cls.discord_proxy_image_localfile(filepath)
        return ret


    @classmethod
    def trans(cls, text, do_trans=True, source='ja', target='ko'):
        if do_trans:
            from trans import SupportTrans
            return SupportTrans.translate(text, source=source, target=target)
        return text


    @classmethod
    def discord_proxy_get_target_poster(cls, image_url):
        from tool_expand import ToolExpandDiscord
        return ToolExpandDiscord.discord_proxy_get_target(image_url + 'av_poster')


    @classmethod
    def discord_proxy_set_target(cls, source, target):
        from tool_expand import ToolExpandDiscord
        return ToolExpandDiscord.discord_proxy_set_target(source, target)


    @classmethod
    def discord_proxy_set_target_poster(cls, source, target):
        from tool_expand import ToolExpandDiscord
        return ToolExpandDiscord.discord_proxy_set_target(source + 'av_poster', target)


    @classmethod
    def discord_proxy_image(cls, image_url):
        from tool_expand import ToolExpandDiscord
        return ToolExpandDiscord.discord_proxy_image(image_url)


    @classmethod
    def discord_proxy_image_localfile(cls, filepath):
        from tool_expand import ToolExpandDiscord
        return ToolExpandDiscord.discord_proxy_image_localfile(filepath)


    @classmethod
    def get_image_url(cls, image_url, image_mode, proxy_url=None, with_poster=False):
        try:
            ret = {}
            ret['image_url'] = cls.process_image_mode(image_mode, image_url, proxy_url=proxy_url)
            if with_poster:
                logger.debug(ret['image_url'])
                ret['poster_image_url'] = cls.process_image_mode('5', ret['image_url']) #포스터이미지 url 본인 sjva
        except Exception as e:
            logger.error(f"Exception:{str(e)}")
            logger.error(traceback.format_exc())
        return ret


    @classmethod
    def change_html(cls, text):
        if text is not None:
            return text.replace('&nbsp;', ' ').replace('&nbsp', ' ').replace('&lt;', '<').replace('&gt;', '>').replace('&amp;', '&').replace('&quot;', '"').replace('&#35;', '#').replace('&#39;', "‘")


    @classmethod
    def remove_special_char(cls, text):
        return re.sub('[-=+,#/\?:^$.@*\"※~&%ㆍ!』\\‘|\(\)\[\]\<\>`\'…》：]', '', text)


    @classmethod
    def compare(cls, a, b):
        return (cls.remove_special_char(a).replace(' ', '').lower() == cls.remove_special_char(b).replace(' ', '').lower())


    @classmethod
    def get_show_compare_text(cls, title):
        title = title.replace(u'일일연속극', '').strip()
        title = title.replace(u'특별기획드라마', '').strip()
        title = re.sub(r'\[.*?\]', '', title).strip()
        title = re.sub(r'\(.*?\)', '', title).strip()
        title = re.sub(r'^.{2,3}%s' % u'드라마', '', title).strip()
        title = re.sub(r'^.{1,3}%s' % u'특집', '', title).strip()
        return title


    @classmethod
    def compare_show_title(cls, title1, title2):
        title1 = cls.get_show_compare_text(title1)
        title2 = cls.get_show_compare_text(title2)
        return cls.compare(title1, title2)


    @classmethod
    def info_to_kodi(cls, data):
        data['info'] = {}
        data['info']['title'] = data['title']
        data['info']['studio'] = data['studio']
        data['info']['premiered'] = data['premiered']
        data['info']['year'] = data['year']
        data['info']['genre'] = data['genre']
        data['info']['plot'] = data['plot']
        data['info']['tagline'] = data['tagline']
        data['info']['mpaa'] = data['mpaa']
        if 'director' in data and len(data['director']) > 0:
            if type(data['director'][0]) == type({}):
                tmp_list = []
                for tmp in data['director']:
                    tmp_list.append(tmp['name'])
                data['info']['director'] = ', '.join(tmp_list).strip()
            else:
                data['info']['director'] = data['director']
        if 'credits' in data and len(data['credits']) > 0:
            data['info']['writer'] = []
            if type(data['credits'][0]) == type({}):
                for tmp in data['credits']:
                    data['info']['writer'].append(tmp['name'])
            else:
                data['info']['writer'] = data['credits']
        if 'extras' in data and data['extras'] is not None and len(data['extras']) > 0:
            if data['extras'][0]['mode'] in ['naver', 'youtube']:
                url = '{ddns}/metadata/api/video?site={site}&param={param}&apikey={apikey}'.format(
                    ddns=F.SystemModelSetting.get('ddns'),
                    site=data['extras'][0]['mode'],
                    param=data['extras'][0]['content_url'],
                    apikey=F.SystemModelSetting.get('apikey')
                )
                data['info']['trailer'] = url
            elif data['extras'][0]['mode'] == 'mp4':
                data['info']['trailer'] = data['extras'][0]['content_url']
        data['cast'] = []
        if 'actor' in data and data['actor'] is not None:
            for item in data['actor']:
                entity = {}
                entity['type'] = 'actor'
                entity['role'] = item['role']
                entity['name'] = item['name']
                entity['thumbnail'] = item['thumb']
                data['cast'].append(entity)
        if 'art' in data and data['art'] is not None:
            for item in data['art']:
                if item['aspect'] == 'landscape':
                    item['aspect'] = 'fanart'
        elif 'thumb' in data and data['thumb'] is not None:
            for item in data['thumb']:
                if item['aspect'] == 'landscape':
                    item['aspect'] = 'fanart'
            data['art'] = data['thumb']
        if 'art' in data:
            data['art'] = sorted(data['art'], key=lambda k: k['score'], reverse=True)
        return data


    @classmethod
    def is_hangul(cls, text):
        pyVer3 =  sys.version_info >= (3, 0)
        if pyVer3 : # for Ver 3 or later
            encText = text
        else: # for Ver 2.x
            if type(text) is not unicode:
                encText = text.decode('utf-8')
            else:
                encText = text
        hanCount = len(re.findall(u'[\u3130-\u318F\uAC00-\uD7A3]+', encText))
        return hanCount > 0


    @classmethod
    def is_include_hangul(cls, text):
        hanCount = len(re.findall(u'[\u3130-\u318F\uAC00-\uD7A3]+', text))
        return hanCount > 0


    # 의미상으로 여기 있으면 안되나 예전 코드에서 많이 사용하기 때문에 잠깐만 나둔다.
    """
    @classmethod
    def get_tree_daum(cls, url, post_data=None):
        from system.logic_site import SystemLogicSite
        cookies = SystemLogicSite.get_daum_cookies()
        from framework import SystemModelSetting
        proxy_url = SystemModelSetting.get('site_daum_proxy')
        from .site_daum import SiteDaum
        headers = SiteDaum.default_headers
        text = cls.get_text(url, proxy_url=proxy_url, headers=headers, post_data=post_data, cookies=cookies)
        if text is None:
            return
        return html.fromstring(text)

    @classmethod
    def get_text_daum(cls, url, post_data=None):
        from system.logic_site import SystemLogicSite
        cookies = SystemLogicSite.get_daum_cookies()
        from framework import SystemModelSetting
        proxy_url = SystemModelSetting.get('site_daum_proxy')
        from .site_daum import SiteDaum
        headers = SiteDaum.default_headers
        res = cls.get_response(url, proxy_url=proxy_url, headers=headers, post_data=post_data, cookies=cookies)
        return res.text


    @classmethod
    def get_response_daum(cls, url, post_data=None):
        from system.logic_site import SystemLogicSite
        cookies = SystemLogicSite.get_daum_cookies()
        from framework import SystemModelSetting
        proxy_url = SystemModelSetting.get('site_daum_proxy')
        from .site_daum import SiteDaum
        headers = SiteDaum.default_headers

        res = cls.get_response(url, proxy_url=proxy_url, headers=headers, post_data=post_data, cookies=cookies)
        return res
    """

    @classmethod
    def process_image_book(cls, url):
        from PIL import Image
        im = Image.open(requests.get(url, stream=True).raw)
        width, height = im.size
        filename = 'proxy_%s.jpg' % str(time.time())
        filepath = os.path.join(F.config['path_data'], 'tmp', filename)
        left = 0
        top = 0
        right = width
        bottom = width
        poster = im.crop((left, top, right, bottom))
        try:
            poster.save(filepath)
        except:
            poster = poster.convert("RGB")
            poster.save(filepath)
        ret = cls.discord_proxy_image_localfile(filepath)
        return ret


    @classmethod
    def get_treefromcontent(cls, url, proxy_url=None, headers=None, post_data=None, cookies=None):
        text = SiteUtil.get_response(url, proxy_url=proxy_url, headers=headers, post_data=post_data, cookies=cookies).content
        if text is None:
            return
        return lxml.html.fromstring(text)


    @classmethod
    def get_translated_tag(cls, type, tag):
        tags_json = os.path.join(os.path.dirname(__file__), 'tags.json')
        with open(tags_json, 'r', encoding='utf8') as f:
            tags = json.load(f)

        if type in tags:
            if tag in tags[type]:
                res = tags[type][tag]
            else:
                trans_text = SiteUtil.trans(tag, source='ja', target='ko').strip()
                if cls.is_include_hangul(trans_text) or trans_text.replace(' ', '').isalnum():
                    tags[type][tag] = trans_text
                    with open(tags_json, 'w', encoding='utf8') as f:
                        json.dump(tags, f, indent=4, ensure_ascii=False)
                    res = tags[type][tag]
                else:
                    res = tag
            return res
        else:
            return tag

    av_genre = {u'巨尻':u'큰엉덩이', u'ギャル':u'갸루', u'着エロ':u'착에로', u'競泳・スクール水着':u'학교수영복', u'日焼け':u'태닝', u'指マン':u'핑거링', u'潮吹き':u'시오후키', u'ごっくん':u'곳쿤', u'パイズリ':u'파이즈리', u'手コキ':u'수음', u'淫語':u'음란한말', u'姉・妹':u'남매', u'お姉さん':u'누님', u'インストラクター':u'트레이너', u'ぶっかけ':u'붓카케', u'シックスナイン':u'69', u'ボディコン':u'타이트원피스', u'電マ':u'전동마사지', u'イタズラ':u'짖궂음', u'足コキ':u'풋잡', u'原作コラボ':u'원작각색', u'看護婦・ナース':u'간호사', u'コンパニオン':u'접객업', u'家庭教師':u'과외', u'キス・接吻':u'딥키스', u'局部アップ':u'음부확대', u'ポルチオ':u'자궁성감자극', u'セーラー服':u'교복', u'イラマチオ':u'격한페라·딥스로트', u'投稿':u'투고', u'キャンギャル':u'도우미걸', u'女優ベスト・総集編':u'베스트총집편', u'クンニ':u'커닐링구스', u'アナル':u'항문노출', u'超乳':u'폭유', u'復刻':u'리마스터', u'投稿':u'투고', u'義母':u'새어머니', u'おもちゃ':u'노리개', u'くノ一':u'여자닌자', u'羞恥' : u'수치심', u'ドラッグ':u'최음제', u'パンチラ':u'판치라', u'巨乳フェチ':u'큰가슴', u'巨乳':u'큰가슴', u'レズキス':u'레즈비언', u'レズ':u'레즈비언', u'スパンキング':u'엉덩이때리기', u'放尿・お漏らし':u'방뇨·오모라시', u'アクメ・オーガズム':u'절정·오르가즘', u'ニューハーフ':u'쉬메일', u'鬼畜':u'색마·양아치', u'辱め':u'능욕', u'フェラ':u'펠라치오'}
    av_genre_ignore_ja = [u'DMM獨家']
    av_genre_ignore_ko = [u'고화질', u'독점전달', u'세트상품', u'단체작품', u'기간한정세일', u'기리모자', u'데지모', u'슬림', u'미소녀', u'미유', u'망상족', u'거유', u'에로스', u'작은', u'섹시']
    av_studio  = {u'乱丸':u'란마루', u'大洋図書':u'대양도서', u'ミル':u'미루', u'無垢':u'무쿠', u'サムシング':u'Something', u'本中':u'혼나카', u'ナンパJAPAN':u'난파 재팬', u'溜池ゴロー':u'다메이케고로', u'プラム':u'프라무', u'アップス':u'Apps', u'えむっ娘ラボ':u'엠코 라보', u'クンカ':u'킁카', u'映天':u'에이텐', u'ジャムズ':u'JAMS', u'牛感':u'규칸'}

    country_code_translate ={
        "GH" : u"가나",
        "GA" : u"가봉",
        "GY" : u"가이아나",
        "GM" : u"감비아",
        "GP" : u"프랑스",
        "GT" : u"과테말라",
        "GU" : u"미국",
        "GD" : u"그레나다",
        "GE" : u"그루지야",
        "GR" : u"그리스",
        "GL" : u"덴마크",
        "GW" : u"기니비소",
        "GN" : u"기니",
        "NA" : u"나미비아",
        "NG" : u"나이지리아",
        "ZA" : u"남아프리카공화국",
        "NL" : u"네덜란드",
        "AN" : u"네덜란드",
        "NP" : u"네팔",
        "NO" : u"노르웨이",
        "NF" : u"오스트레일리아",
        "NZ" : u"뉴질랜드",
        "NC" : u"프랑스",
        "NE" : u"니제르",
        "NI" : u"니카라과",
        "TW" : u"타이완",
        "DK" : u"덴마크",
        "DM" : u"도미니카연방",
        "DO" : u"도미니카공화국",
        "DE" : u"독일",
        "LA" : u"라오스",
        "LV" : u"라트비아",
        "RU" : u"러시아",
        "LB" : u"레바논",
        "LS" : u"레소토",
        "RO" : u"루마니아",
        "RW" : u"르완다",
        "LU" : u"룩셈부르크",
        "LR" : u"라이베리아",
        "LY" : u"리비아",
        "RE" : u"프랑스",
        "LT" : u"리투아니아",
        "LI" : u"리첸쉬테인",
        "MG" : u"마다가스카르",
        "MH" : u"미국",
        "FM" : u"미크로네시아",
        "MK" : u"마케도니아",
        "MW" : u"말라위",
        "MY" : u"말레이지아",
        "ML" : u"말리",
        "MT" : u"몰타",
        "MQ" : u"프랑스",
        "MX" : u"멕시코",
        "MC" : u"모나코",
        "MA" : u"모로코",
        "MU" : u"모리셔스",
        "MR" : u"모리타니",
        "MZ" : u"모잠비크",
        "MS" : u"영국",
        "MD" : u"몰도바",
        "MV" : u"몰디브",
        "MN" : u"몽고",
        "US" : u"미국",
        "VI" : u"미국",
        "AS" : u"미국",
        "MM" : u"미얀마",
        "VU" : u"바누아투",
        "BH" : u"바레인",
        "BB" : u"바베이도스",
        "BS" : u"바하마",
        "BD" : u"방글라데시",
        "BY" : u"벨라루스",
        "BM" : u"영국",
        "VE" : u"베네수엘라",
        "BJ" : u"베넹",
        "VN" : u"베트남",
        "BE" : u"벨기에",
        "BZ" : u"벨리세",
        "BA" : u"보스니아헤르체코비나",
        "BW" : u"보츠와나",
        "BO" : u"볼리비아",
        "BF" : u"부르키나파소",
        "BT" : u"부탄",
        "MP" : u"미국",
        "BG" : u"불가리아",
        "BR" : u"브라질",
        "BN" : u"브루네이",
        "BI" : u"브룬디",
        "WS" : u"미국(사모아,",
        "SA" : u"사우디아라비아",
        "CY" : u"사이프러스",
        "SM" : u"산마리노",
        "SN" : u"세네갈",
        "SC" : u"세이셸",
        "LC" : u"세인트루시아",
        "VC" : u"세인트빈센트그레나딘",
        "KN" : u"세인트키츠네비스",
        "SB" : u"솔로몬아일란드",
        "SR" : u"수리남",
        "LK" : u"스리랑카",
        "SZ" : u"스와질랜드",
        "SE" : u"스웨덴",
        "CH" : u"스위스",
        "ES" : u"스페인",
        "SK" : u"슬로바키아",
        "SI" : u"슬로베니아",
        "SL" : u"시에라리온",
        "SG" : u"싱가포르",
        "AE" : u"아랍에미레이트연합국",
        "AW" : u"네덜란드",
        "AM" : u"아르메니아",
        "AR" : u"아르헨티나",
        "IS" : u"아이슬란드",
        "HT" : u"아이티",
        "IE" : u"아일란드",
        "AZ" : u"아제르바이잔",
        "AF" : u"아프가니스탄",
        "AI" : u"영국",
        "AD" : u"안도라",
        "AG" : u"앤티과바부다",
        "AL" : u"알바니아",
        "DZ" : u"알제리",
        "AO" : u"앙골라",
        "ER" : u"에리트리아",
        "EE" : u"에스토니아",
        "EC" : u"에콰도르",
        "SV" : u"엘살바도르",
        "GB" : u"영국",
        "VG" : u"영국",
        "YE" : u"예멘",
        "OM" : u"오만",
        "AU" : u"오스트레일리아",
        "AT" : u"오스트리아",
        "HN" : u"온두라스",
        "JO" : u"요르단",
        "UG" : u"우간다",
        "UY" : u"우루과이",
        "UZ" : u"우즈베크",
        "UA" : u"우크라이나",
        "ET" : u"이디오피아",
        "IQ" : u"이라크",
        "IR" : u"이란",
        "IL" : u"이스라엘",
        "EG" : u"이집트",
        "IT" : u"이탈리아",
        "IN" : u"인도",
        "ID" : u"인도네시아",
        "JP" : u"일본",
        "JM" : u"자메이카",
        "ZM" : u"잠비아",
        "CN" : u"중국",
        "MO" : u"중국",
        "HK" : u"중국",
        "CF" : u"중앙아프리카",
        "DJ" : u"지부티",
        "GI" : u"영국",
        "ZW" : u"짐바브웨",
        "TD" : u"차드",
        "CZ" : u"체코",
        "CS" : u"체코슬로바키아",
        "CL" : u"칠레",
        "CA" : u"캐나다",
        "CM" : u"카메룬",
        "CV" : u"카보베르데",
        "KY" : u"영국",
        "KZ" : u"카자흐",
        "QA" : u"카타르",
        "KH" : u"캄보디아",
        "KE" : u"케냐",
        "CR" : u"코스타리카",
        "CI" : u"코트디봐르",
        "CO" : u"콜롬비아",
        "CG" : u"콩고",
        "CU" : u"쿠바",
        "KW" : u"쿠웨이트",
        "HR" : u"크로아티아",
        "KG" : u"키르키즈스탄",
        "KI" : u"키리바티",
        "TJ" : u"타지키스탄",
        "TZ" : u"탄자니아",
        "TH" : u"타이",
        "TC" : u"영국",
        "TR" : u"터키",
        "TG" : u"토고",
        "TO" : u"통가",
        "TV" : u"투발루",
        "TN" : u"튀니지",
        "TT" : u"트리니다드토바고",
        "PA" : u"파나마",
        "PY" : u"파라과이",
        "PK" : u"파키스탄",
        "PG" : u"파푸아뉴기니",
        "PW" : u"미국",
        "FO" : u"덴마크",
        "PE" : u"페루",
        "PT" : u"포르투갈",
        "PL" : u"폴란드",
        "PR" : u"미국",
        "FR" : u"프랑스",
        "GF" : u"프랑스",
        "PF" : u"프랑스",
        "FJ" : u"피지",
        "FI" : u"필란드",
        "PH" : u"필리핀",
        "HU" : u"헝가리",
        "KR" : u"한국",
        "EU" : u"유럽",
        "SY" : u"시리아",
        "A1" : u"Anonymous Proxy",
        "A2" : u"인공위성IP",
        "PS" : u"팔레스타인",
        "RS" : u"세르비아",
        "JE" : u"저지",
        "YU" : u"유고슬라비아",
        "SU" : u"소련",
    }


    genre_map = {
        'Action' : u'액션',
        'Adventure' : u'어드벤처',
        'Drama' : u'드라마',
        'Mystery' : u'미스터리',
        'Mini-Series' : u'미니시리즈',
        'Science-Fiction' : u'SF',
        'Thriller' : u'스릴러',
        'Crime' : u'범죄',
        'Documentary' : u'다큐멘터리',
        'Sci-Fi & Fantasy' : u'SF & 판타지',
        'Animation' : u'애니메이션',
        'Comedy' : u'코미디',
        'Romance' : u'로맨스',
        'Fantasy' : u'판타지',
        'Sport' : u'스포츠',
        'Soap' : u'연속극',
        'Suspense' : u'서스펜스',
        'Action & Adventure' : u'액션 & 어드벤처',
        'History' : u'역사',
        'Science Fiction' : u'SF',
        'War & Politics' : u'전쟁 & 정치',
        'Reality' : '리얼리티',
    }

    @classmethod
    def normalize_url(cls, url: str, scheme: str ='https') -> str:
        url = url.lstrip('/')
        parsed = urllib.parse.urlparse(url, scheme=scheme)
        if not parsed.netloc:
            parsed = urllib.parse.urlparse(f'{parsed.scheme}://{url}', scheme=scheme)
        return urllib.parse.urlunparse(parsed)
