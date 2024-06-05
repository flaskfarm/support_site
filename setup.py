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
