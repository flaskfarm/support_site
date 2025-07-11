import random
import time
from base64 import b64decode
from datetime import datetime, timedelta
from io import BytesIO
from itertools import islice, zip_longest
from pathlib import Path
from typing import Dict, List
from urllib.parse import parse_qs, urlparse

from discord_webhook import DiscordEmbed, DiscordWebhook
from framework import path_data  # pylint: disable=import-error
from PIL import Image

from .setup import logger

try:
    webhook_file = Path(path_data).joinpath("db/lib_metadata.webhook")
    with open(webhook_file, encoding="utf-8") as fp:
        webhook_list = list(filter(str, fp.read().splitlines()))
    assert webhook_list, f"웹훅을 찾을 수 없음: {webhook_file}"
    logger.debug("나의 웹훅 사용: %d", len(webhook_list))
except Exception as e:
    logger.debug("내장 웹훅 사용: %s", e)
    webhook_list = [
        "aHR0cHM6Ly9kaXNjb3JkLmNvbS9hcGkvd2ViaG9va3MvMTE2MjIyODM4MzE4MzI4MjIyNy9ORXpNWFBmT05vbUU3bl8xck1iT0ZWQUI4ZmlXN21vRFlGYnJHRk03UlJSWF90ZGMyS0lxY2hWcXV6VF8wVm5ZUEJRVQ==",  # 1
        "aHR0cHM6Ly9kaXNjb3JkLmNvbS9hcGkvd2ViaG9va3MvMTE2MjIyODc5MzExMzU4MzY3Ni94dEZlWnRWbkhEUGc4aFBYZkZDMkFidUtDSmlwNjQ0d1RQMDFJalVncTR5ODB6XzZCRi1kTFctemlEdGNlWF84RXVtRw==",  # 2
        "aHR0cHM6Ly9kaXNjb3JkLmNvbS9hcGkvd2ViaG9va3MvMTE2MjIyODkyMTA4MTgxMDk1NS9xOUVYZndHYll6bHdwM1MtMnpxUmxZcnJYWS1nTUttTTRlTUd0YW8zNTF1d1c2N0U2ckNFUW0zWDJhbDJURnFXMHR4cw==",  # 3
        "aHR0cHM6Ly9kaXNjb3JkLmNvbS9hcGkvd2ViaG9va3MvMTE2MjIyOTA4MzA0NDg1MTc3My9jVU1YRkVERHQ2emtWOW90Mmd5dlpYeVlOZV9VcGtmcmZhTzg5aHZoLVdod0c0Z24zOGJhT19DVkg2Z0N4clFraVZRcA==",  # 4
        "aHR0cHM6Ly9kaXNjb3JkLmNvbS9hcGkvd2ViaG9va3MvMTE2MjIyOTE4MzAwMzQ5MjM5Mi9CVXl1U3lKTHc1cktHdFRKOWhqRDk3SklKWW9HSTZ6SnJ4MzdLX0s4TkVKU3ZTYlZ4aC0tMVFRMEFZbTJFa0tzaEJRcQ==",  # 5
        "aHR0cHM6Ly9kaXNjb3JkLmNvbS9hcGkvd2ViaG9va3MvMTE2MjIyOTI4OTQ4ODQ5NDY0My9XLWhZck95QTBza2M1dUdVTkpyenU4ZHFSMVF0QmMtOVAzMW45RHhQWkhVLXptdEZ3MWVLWTE0dlZubkRUV25EU2ZRTw==",  # 6
        "aHR0cHM6Ly9kaXNjb3JkLmNvbS9hcGkvd2ViaG9va3MvMTE2MjIyOTQwOTExODQzNzQ2OS95NDRjVTkwM1hLS2NyaWFidERHMzRuMzZfRkZsMF9TV2p4b0lWMlBZY0dxNWxyU1dxVWt5ZklkZlcwM0FFVDJObThMaQ==",  # 7
        "aHR0cHM6Ly9kaXNjb3JkLmNvbS9hcGkvd2ViaG9va3MvMTE2MjIyOTQ5NTQyNDYxODQ5Ni9PSnFlVHRhZ1FtVGFrU2VNQkRucVhZRTJieWRuX2cweHV2VTA0WmdKS3NjWEQydkVHbHBWYzdhQWZMQ0ZYSXNTbTN5OQ==",  # 8
        "aHR0cHM6Ly9kaXNjb3JkLmNvbS9hcGkvd2ViaG9va3MvMTE2MjIyOTU4NzE2NjY0MjM2OC9PeG9NRllUT1dOWmcwS3pfQ3k2ZXowX2laQnpqbm02QVkyTjJfMWhaVHhYdWxPRm5oZ0lsOGxxcUVYNVVWRWhyMHJNcw==",  # 9
        "aHR0cHM6Ly9kaXNjb3JkLmNvbS9hcGkvd2ViaG9va3MvMTE2MjIyOTY4OTM3NzYzNjQ3Mi9iblgyYTNsWjI1R2NZZ1g4Sy1JeXZVcS1TMV9zYmhkbEtoSTI4eWp6SWdHOHRyekFWMXBKUkgxYkdrdmhzMVNUNS1uMg==",  # 10
        "aHR0cHM6Ly9kaXNjb3JkLmNvbS9hcGkvd2ViaG9va3MvMTE2MjIyOTgwMTg0MzY5MTY4Mi96OUFocjZjNmxaS1VyWV9TRmhfODVQeEVlSjJuQW8wMXlHS3RCUWpNNnJmR3JGVXdvQ1oyQ3NJYmlTMHQ1NDZwU3NUUg==",  # 11
        "aHR0cHM6Ly9kaXNjb3JkLmNvbS9hcGkvd2ViaG9va3MvMTE2MjIyOTk0NjQyMTM2Njg0NC9BYnFVRlJCN0dzb3ktUkdfMzBLNXZkNm9XUWRnbkpDZ1ctTlpBbkFRN0N2TzdsNjRfeXRkY0ZHUkhLV2RldE1jQzhTSw==",  # 12
        "aHR0cHM6Ly9kaXNjb3JkLmNvbS9hcGkvd2ViaG9va3MvMTE2MjIzMDExNjAyNjQyMTM0OC82dG1NOTA2eV9QTHJ3WGFxcGNZS25OMEJIQjlDTkxJT1dJeTdpc3Exbm9VMHJxU2V0NzI2R1Y4Zk9Ua2pCbDZacXMxVA==",  # 13
        "aHR0cHM6Ly9kaXNjb3JkLmNvbS9hcGkvd2ViaG9va3MvMTE2MjIzMDIwMTExMjA3MjM2My9DYkdkcVdvd3hCcTV3ck1hck0taGZqajVIbFJ2VFFWa0tuZUVaVl9yMlc1UkxHZFZpWW15VzZZcl9PbEJCZG5KWk1wNw==",  # 14
        "aHR0cHM6Ly9kaXNjb3JkLmNvbS9hcGkvd2ViaG9va3MvMTE2MjIzMDI5MTUwNzcyNDQwOC9UanJFc08zSTJyT3l0d0ZvVFhUSlNTOXphaDJpbG9CcVk3TzhHMHZWbDROTmI0aGpaaDNjVGo0cGNla2lxa3RqaGRPTg==",  # 15
        "aHR0cHM6Ly9kaXNjb3JkLmNvbS9hcGkvd2ViaG9va3MvMTE2MjIzMDM3NDQ4NzgzNDc3NC85ZFpodjZfajRuT0hpbGtMaFVVc1B6OVFKa2dqQ3BJZ19PWE55YnZtV1BiQlNVdmRZWC1IVW5UM3RneDlKdnZlYjVMZw==",  # 16
        "aHR0cHM6Ly9kaXNjb3JkLmNvbS9hcGkvd2ViaG9va3MvMTE2MjIzMDU2ODkzMTU2OTc3NC82MTFBVTg0ZUZBcXllWlktQ2lPbnozbm4zSHg3ZldwQUNCbjlMTFNENUFJdHRkYjVHSm9pV3B1dHpxdEVHZ3l0RHlXYg==",  # 17
        "aHR0cHM6Ly9kaXNjb3JkLmNvbS9hcGkvd2ViaG9va3MvMTE2MjIzMDY3MzkxMDgwMDM4Ni9jbEZvZHEwREhGNUlvYUtVRXVRcXNGbnB3OXZoZUx1RU1qbVJFNjQyRUZGa21wYXBwMzhYWDNPMmZKWUVSdjMzY0tORg==",  # 18
        "aHR0cHM6Ly9kaXNjb3JkLmNvbS9hcGkvd2ViaG9va3MvMTE2MjIzMDc0OTMyMDE5NjE5OC8weE1vZ2o5UXRCM1NGZE5KYk04STk1LU9XQzI2Zm1WTWpjelpSX2REY2hnblZoUk1QelVzRHFlYTc0QUdISFRFVWFVZQ==",  # 19
        "aHR0cHM6Ly9kaXNjb3JkLmNvbS9hcGkvd2ViaG9va3MvMTE2MjIzMDg0NTMxNTIyMzU2Mi9HWVItZUo2WFltdy1VMHRkWWY5QXdnU2JVZFpSb1k4aWx2MlVxaVJBSnlBdDBsYWV5ck1tSzJmRGp5T1YyenBJUUR2bA==",  # 20
    ]
    webhook_list = [b64decode(x).decode() for x in webhook_list]


class DiscordUtil:
    _webhook_list = []
    MARGIN = timedelta(seconds=60)

    @classmethod
    def get_webhook_url(cls):
        if not cls._webhook_list:
            cls._webhook_list = random.sample(webhook_list, k=len(webhook_list))
        return cls._webhook_list.pop()

    @classmethod
    def __execute(cls, webhook: DiscordWebhook, num_retries: int = 2, sleep_sec: int = 1) -> dict:
        """warps DiscordWebhook.execute() with a retry scheme"""
        for retry_num in range(num_retries + 1):
            if retry_num > 0:
                logger.warning("[%d/%d] Sleeping %.2f secs before executing webhook", retry_num, num_retries, sleep_sec)
                webhook.url = cls.get_webhook_url()
                time.sleep(sleep_sec)

            res = webhook.execute()
            if isinstance(res, list):
                res = res[0]
            if res.status_code != 429:
                break

        try:
            return res.json()
        except AttributeError:
            return res[0].json()

    @classmethod
    def proxy_image(cls, im: Image.Image, filename: str, title: str = None, fields: List[dict] = None) -> str:
        """proxy image by attachments"""
        webhook = DiscordWebhook(url=cls.get_webhook_url())
        with BytesIO() as buf:
            im.save(buf, format=im.format, quality=95)
            webhook.add_file(buf.getvalue(), filename)
        embed = DiscordEmbed(title=title, color=16164096)
        embed.set_footer(text="lib_metadata")
        embed.set_timestamp()
        for field in fields or []:
            embed.add_embed_field(**field)
        embed.set_image(url=f"attachment://{filename}")
        webhook.add_embed(embed)

        return cls.__execute(webhook)["embeds"][0]["image"]["url"]

    @classmethod
    def isurlattachment(cls, url: str) -> bool:
        if not any(x in url for x in ["cdn.discordapp.com", "media.discordapp.net"]):
            return False
        if "/attachments/" not in url:
            return False
        return True

    @classmethod
    def isurlexpired(cls, url: str) -> bool:
        u = urlparse(url)
        q = parse_qs(u.query, keep_blank_values=True)
        try:
            ex = datetime.utcfromtimestamp(int(q["ex"][0], base=16))
            return ex - cls.MARGIN < datetime.utcnow()
        except KeyError:
            return True

    @classmethod
    def iter_attachment_url(cls, data: dict):
        if isinstance(data, dict):
            for v in data.values():
                yield from cls.iter_attachment_url(v)
        if isinstance(data, list):
            for v in data:
                yield from cls.iter_attachment_url(v)
        if isinstance(data, str) and cls.isurlattachment(data):
            yield data

    @classmethod
    def __proxy_image_url(
        cls,
        urls: List[str],
        titles: List[str] = None,
        lfields: List[List[dict]] = None,  # list of fields
    ) -> Dict[str, str]:
        # https://discord.com/safety/using-webhooks-and-embeds
        assert len(urls) <= 10, "A webhook can have 10 embeds per message"

        webhook = DiscordWebhook(url=cls.get_webhook_url())
        for url, title, fields in zip_longest(urls, titles, lfields):
            embed = DiscordEmbed(title=title, color=5814783)
            embed.set_footer(text="lib_metadata")
            embed.set_timestamp()
            for field in fields or []:
                embed.add_embed_field(**field)
            embed.set_image(url=url)
            webhook.add_embed(embed)

        res = cls.__execute(webhook)
        return {ourl: res["embeds"][n]["image"]["url"] for n, ourl in enumerate(urls)}

    @classmethod
    def proxy_image_url(
        cls,
        urls: List[str],
        titles: List[str] = None,
        lfields: List[List[dict]] = None,  # list of fields
    ) -> Dict[str, str]:
        urls = list(set(urls))

        def chunker(it, chunk_size=10):
            it = iter(it)
            while chunk := list(islice(it, chunk_size)):
                yield chunk

        titles = titles or []
        lfields = lfields or []
        urlmaps = {}
        for u, t, lf in zip_longest(*[chunker(x) for x in [urls, titles, lfields]]):
            urlmaps.update(cls.__proxy_image_url(u, t, lf))
        return urlmaps

    @classmethod
    def renew_urls(cls, data):
        """renew and in-place replacement of discord attachments urls in data"""

        def _repl(d, m):
            if isinstance(d, (dict, list)):
                for k, v in d.items() if isinstance(d, dict) else enumerate(d):
                    if isinstance(v, str) and v in m:
                        d[k] = m[v]
                    _repl(v, m)

        if isinstance(data, dict):
            urls = list(filter(cls.isurlexpired, cls.iter_attachment_url(data)))
            titles = [x.split("?")[0] for x in urls]
            lfields = [[{"name": "mode", "value": "renew"}]] * len(urls)
            urlmaps = cls.proxy_image_url(urls, titles=titles, lfields=lfields)
            _repl(data, urlmaps)
            return data
        if isinstance(data, list):
            urls = list(filter(cls.isurlexpired, data))
            titles = [x.split("?")[0] for x in urls]
            lfields = [[{"name": "mode", "value": "renew"}]] * len(urls)
            urlmaps = cls.proxy_image_url(urls, titles=titles, lfields=lfields)
            return [urlmaps.get(x, x) for x in data]
        raise NotImplementedError(f"알 수 없는 데이터 유형: {type(data)}")
