import requests
from .setup import *

CDN_ALBUM_TITLE = 'cdn'

class ToolImgur(object):
    __client = None
    __cdn_id = None

    @classmethod
    def __get_client(cls):
        try:
            from imgurpython import ImgurClient
        except:
            try:
                os.system("pip install imgurpython")
                from imgurpython import ImgurClient
            except Exception as e:
                logger.error(f"Exception:{str(e)}")
                logger.error(traceback.format_exc())
        try:
            if cls.__client == None:
                cls.__client = ImgurClient(
                    P.ModelSetting.get('site_imgur_client_id'),
                    P.ModelSetting.get('site_imgur_client_secret'),
                    P.ModelSetting.get('site_imgur_access_token'),
                    P.ModelSetting.get('site_imgur_refresh_token')
                )
                find = False
                for album in cls.__client .get_account_albums('me'):
                    album_title = album.title if album.title else 'Untitled'
                    if album_title == CDN_ALBUM_TITLE:
                        cls.__cdn_id = album.id
                        find = True
                        logger.debug(f"imgur cdn album id: {cls.__cdn_id}")
                        break
                if find == False:
                    ret = cls.__client.create_album({'title':CDN_ALBUM_TITLE})
                    cls.__cdn_id = ret['id']
                    #logger.error(ret)
        except Exception as e:
            logger.error(f"Exception:{str(e)}")
            logger.error(traceback.format_exc())
        return cls.__client


    @classmethod
    def upload_from_path(cls, localpath):
        client = cls.__get_client()
        if client:
            image = client.upload_from_path(localpath, config={'album':cls.__cdn_id}, anon=False)
            return image['link']

    @classmethod
    def upload_from_url(cls, url):
        client = cls.__get_client()
        if client:
            image = client.upload_from_url(url, config={'album':cls.__cdn_id}, anon=False)
            return image['link']

    @classmethod
    def upload_from_paste(cls, img):
        client = cls.__get_client()
        if client:
            data = {
                'image': img.split('base64,')[1],
                'type': 'base64',
                'album': cls.__cdn_id
            }
            tmp = client.make_request('POST', 'upload', data, False)
            return tmp['link']

    """
    @classmethod
    def request_auth(cls, id, secret):
        url = f"https://api.imgur.com/oauth2/authorize?client_id={id}&response_type=token&state=APPLICATION_STATE"
        headers = {
            'Authorization': f'Client-ID {id}'
        }
        res = requests.get(url, headers=headers)
        if res.status_code == 200:
            return True, res.text
        return False, res.status_code
    """