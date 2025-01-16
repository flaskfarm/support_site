import functools
import redis
from typing import Iterable

setting = {
    'filepath' : __file__,
    'use_db': True,
    'use_default_setting': True,
    'home_module': None,
    'menu': None,
    'setting_menu': {
        'uri': f"support_site",
        'name': 'SUPPORT SITE 설정',
        'list': [
            {'uri': 'setting', 'name': '설정'},
            {'uri': 'imgur_paste', 'name': 'imgur 업로드'},
            {'uri': 'manual/files/manual.md', 'name': '매뉴얼'},
            {'uri': 'manual/README.md', 'name': 'README'},
        ]
    },
    'default_route': 'normal',
}


from plugin import *

P = create_plugin_instance(setting)

try:
    from .mod_site import ModuleSite
    P.set_module_list([ModuleSite])
except Exception as e:
    P.logger.error(f'Exception:{str(e)}')
    P.logger.error(traceback.format_exc())

logger = P.logger

REDIS_EXPIRE = 21600 # in seconds (6 hours)
REDIS_KEY_PLUGIN = 'flaskfarm:support_site'
try:
    if not F.config.get('use_celery'):
        raise Exception('use_celery=False')
    redis_port = F.config.get('redis_port') or os.environ.get('REDIS_PORT') or 6379
    # decode_responses=True
    REDIS_CONN = redis.Redis(host='localhost', port=redis_port, decode_responses=True)
except:
    logger.error(traceback.format_exc())
    REDIS_CONN = None


def check_redis(func: callable) -> callable:
    @functools.wraps(func)
    def wrap(*args, **kwds) -> str | int | None:
        if REDIS_CONN:
            return func(*args, **kwds)
    return wrap


@check_redis
def hset(key: str, field: str = None, value: str = None, mapping: dict = None) -> None:
    if mapping:
        REDIS_CONN.hset(key, mapping=mapping)
    else:
        REDIS_CONN.hset(key, field, value)
    if REDIS_CONN.ttl(key) < 0:
        REDIS_CONN.expire(key, time=REDIS_EXPIRE)


@check_redis
def hget(key: str, field: str) -> str | None:
    return REDIS_CONN.hget(key, field)


@check_redis
def hgetall(key: str) -> dict:
    return REDIS_CONN.hgetall(key)


@check_redis
def scan_iter(expression: str) -> Iterable[str]:
    for key in REDIS_CONN.scan_iter(expression):
        yield key


'''
cursor = '0'
while cursor != 0:
    cursor, keys = REDIS_CONN.scan(cusor=cursor, match=f'{REDIS_KEY_PLUGIN}:*', count=5000)
    if keys:
        REDIS_CONN.delete(*keys)
'''
for key in scan_iter(f'{REDIS_KEY_PLUGIN}:*'):
    REDIS_CONN.delete(key)
