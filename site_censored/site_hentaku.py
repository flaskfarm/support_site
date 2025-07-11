import time

from ..setup import P, logger
from ..site_util_av import SiteUtilAv as SiteUtil


class SiteHentaku:
    site_char = "H"
    site_name = "hentaku"

    @staticmethod
    def __get_actor_info(originalname, proxy_url=None, image_mode="0"):
        url = "https://hentaku.co/starsearch.php"
        tree = SiteUtil.get_tree(url, post_data={"name": originalname}, proxy_url=proxy_url)

        hrefs = tree.xpath('//div[@class="avstar_photo"]/a/@href')
        if not hrefs:
            # logger.debug("검색 결과 없음: originalname=%s", originalname)
            return None

        names = tree.xpath('//div[@class="avstar_info_b"]/text()')[0].split("/")
        if len(names) != 3:
            # logger.debug("검색 결과에서 이름을 찾을 수 없음: len(%s) != 2", names)
            return None

        name_ko, name_en, name_ja = [x.strip() for x in names]
        if name_ja == originalname:
            doc = SiteUtil.get_tree(hrefs[0], proxy_url=proxy_url)
            thumb_url = doc.xpath('//div[@class="avstar_photo"]//img/@src')[0]
            return {
                "name": name_ko,
                "name2": name_en,
                "site": "hentaku",
                "thumb": SiteUtil.process_image_mode(image_mode, thumb_url, proxy_url=proxy_url),
            }
        # logger.debug("검색 결과 중 일치 항목 없음: %s != %s", name_ja, originalname)
        return None

    @staticmethod
    def get_actor_info(entity_actor, **kwargs) -> bool:
        retry = kwargs.pop("retry", True)
        proxy_url = kwargs.get("proxy_url") 
        image_mode = kwargs.get("image_mode", "0")
        info = None
        try:
            info = SiteHentaku.__get_actor_info(
                entity_actor["originalname"], 
                proxy_url=proxy_url, 
                image_mode=image_mode
            )
        except Exception as e_hentaku:
            logger.warning(f"Hentaku 정보 조회 중 예외 발생: {e_hentaku}")
            if retry:
                logger.debug("Hentaku: 단시간 많은 요청으로 2초 후 재시도")
                time.sleep(2)
                return SiteHentaku.get_actor_info(entity_actor, retry=False, **kwargs)
            logger.exception("Hentaku: 배우 정보 업데이트 중 최종 예외: originalname=%s", entity_actor["originalname"])
            return False

        if info is not None:
            logger.info(f"Hentaku: '{entity_actor['originalname']}' 정보 찾음. 업데이트 수행.")
            entity_actor.update(info)
            return True
        else:
            logger.debug(f"Hentaku: '{entity_actor['originalname']}' 정보 찾지 못함.")
            return False
