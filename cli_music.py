
import copy
import os
import platform
import re
import shutil
import sys
import traceback
from difflib import SequenceMatcher

import flaskfarm
from support import SupportFile, SupportString, d, get_logger

logger = get_logger()

from site_melon import SiteMelon, set_logger

set_logger(logger)


class MusicProcess:

    def __init__(self, config):
        self.config = config

    def album_rename(self):
        # 아티스트 탐색
        for artist in os.listdir(self.config['source']):
            artist_path =  os.path.join(self.config['source'], artist)
            album_listdir = os.listdir(artist_path)
            
            # 비어있는 폴더면 지움
            if len(album_listdir) == 0:
                shutil.rmtree(artist_path)
                continue

            # 아티스트 서치
            # 동명이인... 폴더에 있는 [MA1234] 처리
            match = re.search("(?P<artist>.*?)\s?\[MA(?P<code>\d+)\]", artist)
            if match:
                select_artist = {
                    'code' : f"SA{match.group('code')}",
                    'artist' : artist,
                }
            else:
                data = SiteMelon.search_artist(artist, 'normal')['data']
                if len(data) == 0:
                    logger.critical(f"[!] [{artist}] 검색 결과 없음!")
                    continue
                elif data[0]['score'] < 99:
                    logger.critical(f"[!] [{artist}] 검색 결과 100점 없음!")
                    for idx, item in enumerate(data):
                        print(f"[{idx}] [{item['score']}] [{item['artist']}] [{item['desc']}]")
                    try:
                        artist_index = int(input("아티스트 선택 (번호:선택 그외:패스): "))
                        select_artist = data[artist_index]
                    except:
                        continue
                else:
                    select_artist = data[0]
            #logger.debug(d(data))
          
            # 아티스트 앨범
            album_data = SiteMelon.info_artist_albums(select_artist['code'])


            for item in album_data:
                tmp = f"{item['date']} {item['album_type']}".strip()
                item['foldername'] = f"[{tmp}] {item['title']}"


            for album in album_listdir:
                album_path = os.path.join(artist_path, album)
                if os.path.isfile(album_path):
                    continue
                
                if len(os.listdir(album_path)) == 0:
                    shutil.rmtree(album_path)
                    continue

                has_dirs = False
                for base, dirs, files in os.walk(album_path): 
                    logger.info(f"앨범 - dirs:{len(dirs)} files:{len(files)}")
                    if len(dirs)>0:
                        for tmp in dirs:
                            if tmp.startswith('CD') == False:
                                has_dirs = True
                                break
                
                if has_dirs:
                    logger.critical(f"[!] {album} 하위 폴더 있어서 패스")
                    continue

                for item in album_data:
                    move_flag = False

                    if item['foldername'] == album or item['title'] == album:
                        logger.warning("[!] 제목 일치해 이동 진행")
                        move_flag = True

                    if move_flag == False:
                        album_tmp = re.sub("\[.*?\]", '', album).strip() 
                        if item['title'] == album_tmp:
                            move_flag = True
                            logger.warning(f"[!] [] 제외 일치 : [{album}] [{album_tmp}] [{item['title']}]")
                    
                    if move_flag:
                        self.move(select_artist['artist'], album, album_path, item['foldername'])
                        break
                else:
                    #for idx, item in enumerate(album_data):
                    #    logger.debug(f"{idx} - {item['foldername']}")

                    ratio_album_data = copy.deepcopy(album_data)
                    for item in ratio_album_data:
                        item['ratio'] = SequenceMatcher(None, album.lower(), item['title'].lower()).ratio()
                    ratio_album_data = list((sorted(ratio_album_data, key=lambda k:k['ratio'])))

                    def print_album(mode):
                        if mode.lower() == 'r':
                            print('=====================================================')
                            for idx, item in enumerate(ratio_album_data):
                                print(f"[{idx}] {item['foldername']} [{int(item['ratio']*100)}%]")
                            print('=====================================================')
                            print(f"현재 아티스트: {select_artist['artist']}")
                            print(f"현재 폴더: {album}")
                            print(f"dirs:{len(dirs)} files:{len(files)}")
                            print('=====================================================')
                            return ratio_album_data
                        elif mode == 'd':
                            print('=====================================================')
                            for idx, item in enumerate(album_data):
                                print(f"[{idx}] {item['foldername']}")
                            print('=====================================================')
                            print(f"현재 아티스트: {select_artist['artist']}")
                            print(f"현재 폴더: {album}")
                            print(f"dirs:{len(dirs)} files:{len(files)}")
                            print('=====================================================')
                            return album_data

                            
                    current_album_data = print_album('r')
                    while True:
                        ans = input("앨범 선택 (번호:선택 D:시간순출력 R:유사도출력 L:파일목록, 번호L:트랙목록): ")
                        list_flag = False
                        ans = ans.strip().lower()
                        if ans in ['d', 'r']:
                            current_album_data = print_album(ans)
                            continue
                        elif ans == 'l':
                            logger.debug(d(os.listdir(album_path)))
                            continue
                        elif ans.endswith('l'):
                            list_flag = True
                            ans = ans.rstrip('l')

                        try:
                            ans = int(ans)
                            if list_flag:
                                tmp = SiteMelon.info_album(current_album_data[ans]['code'])
                                for _ in tmp['track']:
                                    for __ in _:
                                        print(__['title'])
                            else:
                                ret = self.move(select_artist['artist'], album, album_path, current_album_data[ans]['foldername'])
                                break
                        except Exception as e: 
                            #logger.error('Exception:%s', e)
                            #logger.error(traceback.format_exc())
                            #logger.error("변환하지 않음")
                            break
                            pass


            album_listdir = os.listdir(artist_path)
            if len(album_listdir) == 0:
                shutil.rmtree(artist_path)
                continue

    def move(self, artist, album, album_path, new_album):
        try:
            logger.info(f"이동!!! : [{artist}] [{album}] => {new_album}")
            artist = SupportFile.text_for_filename(artist)
            new_album = SupportFile.text_for_filename(new_album)
            #new_album = new_album.replace('-', ' ') # 아티스트로 처리됨
            #new_album = re.sub("\s{2,}", ' ', new_album)

            new_artist_path = os.path.join(self.config['target'], SupportString.get_cate_char_by_first(artist),  artist)
            os.makedirs(new_artist_path, exist_ok=True)
            new_album_path = os.path.join(new_artist_path, new_album)
            if os.path.exists(new_album_path):
                logger.error(f"{new_album_path} EXISTS!!")
            else:
                shutil.move(album_path, new_album_path)
                return True
            return False
        except Exception as e: 
            logger.error('Exception:%s', e)
            logger.error(traceback.format_exc())


    def remove_trash_file(self):
        for base, dirs, files in os.walk(self.config['remove_target']): 
            def print_current():
                logger.info(f"[{base}] dirs:{len(dirs)} files:{len(files)}")
            if len(dirs) == 0 and len(files) == 0:
                print_current()
                logger.error("파일 없음")
                
            for f in files:
                if f in self.config['remove_except_filename']:
                    continue
                filename, ext = os.path.splitext(f)
                ext = ext.strip('.')
                if filename in self.config['remove_except_filename_except_ext']:
                    continue
                if filename.lower() in self.config['remove_except_filename_except_ext']:
                    print_current()
                    logger.warning(f"소문자로 변경 : {f}")
                    shutil.move(os.path.join(base, f), os.path.join(base, f.lower()))
                    continue
                if ext in self.config['remove_except_ext']:
                    if '.com' in filename:
                        print_current()
                        logger.debug(f"변경 필요 : {f}")
                        tmp = re.sub('\s-\s\w+\.com', '', f)
                        if f != tmp:
                            shutil.move(os.path.join(base, f), os.path.join(base, tmp))
                            continue

                    continue
                if ext.lower() in self.config['remove_except_ext']:
                    print_current()
                    logger.warning(f"확장자 소문자로 변경 : {f}")
                    shutil.move(os.path.join(base, f), os.path.join(base, f"{filename}.{ext.lower()}"))
                    continue
                
                print_current()
                logger.debug(f"삭제 : {f}")
                os.remove(os.path.join(base, f))


    def test(self):
        data = SiteMelon.info_artist_albums('SA3295')
        logger.debug(d(data))


    @classmethod
    def process_cli(cls):
        import argparse

        import yaml
        parser = argparse.ArgumentParser()
        parser.add_argument('--config', default='config.yaml', help='config filepath')
        parser.add_argument('--mode', default='rename', help='rename / clear')

        args = parser.parse_args()
        with open(args.config, encoding='utf8') as file:
            config = yaml.load(file, Loader=yaml.FullLoader)
        ins = MusicProcess(config)
        if args.mode == 'rename':
            ins.album_rename()
        elif args.mode == 'remove_trash_file':
            ins.remove_trash_file()
        elif args.mode == 'test':
            ins.test()



if __name__ == '__main__':
    MusicProcess.process_cli()


