"""Reload the related MGStage lookup tables as one validated snapshot."""

import ast
import logging
import os

from .constants import MGS_CODE_LEN, MGS_LABEL_MAP


logger = logging.getLogger('support_site')
_state = {
    'signature': None,
    'maps': ({key: tuple(values) for key, values in MGS_LABEL_MAP.items()}, dict(MGS_CODE_LEN)),
}


def get_mgs_maps():
    """Check for edits on each search; retain both last-good tables on any error."""
    path = os.path.join(os.path.dirname(__file__), 'constants.py')
    signature = None
    try:
        stat = os.stat(path)
        signature = (stat.st_mtime_ns, stat.st_ctime_ns, stat.st_size, stat.st_ino)
        if signature == _state['signature']:
            return _state['maps']
        with open(path, encoding='utf-8-sig') as handle:
            tree = ast.parse(handle.read(), filename=path)
        definitions = {}
        for node in tree.body:
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id in ('MGS_LABEL_MAP', 'MGS_CODE_LEN'):
                        definitions[target.id] = ast.literal_eval(node.value)
        labels, lengths = definitions['MGS_LABEL_MAP'], definitions['MGS_CODE_LEN']
        if not isinstance(labels, dict) or not all(
            isinstance(key, str) and key and isinstance(values, (list, tuple))
            and all(isinstance(value, str) and value for value in values)
            for key, values in labels.items()
        ):
            raise ValueError('MGS_LABEL_MAP must map strings to lists of strings')
        if not isinstance(lengths, dict) or not all(
            isinstance(key, str) and key and type(value) is int and value > 0
            for key, value in lengths.items()
        ):
            raise ValueError('MGS_CODE_LEN must map strings to positive integers')
        maps = ({key: tuple(values) for key, values in labels.items()}, dict(lengths))
    except (OSError, SyntaxError, ValueError, KeyError) as exc:
        # Log only once for a failed edit; a corrected file has a new signature.
        if signature != _state['signature'] or signature is None:
            logger.warning('[MGS Constants] 변경 반영 실패, 마지막 정상 맵 유지: %s', exc)
        if signature is not None:
            _state['signature'] = signature
        return _state['maps']
    _state['maps'] = maps
    _state['signature'] = signature
    logger.debug('[MGS Constants] 맵 로딩: 레이블 %s건, 코드 길이 %s건', len(labels), len(lengths))
    return maps
