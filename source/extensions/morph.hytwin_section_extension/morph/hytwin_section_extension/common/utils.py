from pathlib import Path


def get_data_path(filename):
    # common/utils.py -> hytwin_section -> morph -> <extension_root>
    """현재 상태에서 필요한 값을 조회해 반환한다."""
    here = Path(__file__).resolve()
    ext_root_folder = here.parents[3]
    return ext_root_folder.joinpath("data", filename).as_posix()


def Singleton(class_):
    """해당 함수의 핵심 로직을 수행한다."""
    instances = {}

    def getinstance(*args, **kwargs):
        """해당 함수의 핵심 로직을 수행한다."""
        key = (class_, args, tuple(sorted(kwargs.items())))
        if key not in instances:
            instances[key] = class_(*args, **kwargs)
        return instances[key]

    return getinstance
