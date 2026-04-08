from pathlib import Path


def get_data_path(filename):
    # common/utils.py -> hytwin_section -> morph -> <extension_root>
    here = Path(__file__).resolve()
    ext_root_folder = here.parents[3]
    return ext_root_folder.joinpath("data", filename).as_posix()


def Singleton(class_):
    """Singleton decorator with optional argument-aware instances."""
    instances = {}

    def getinstance(*args, **kwargs):
        key = (class_, args, tuple(sorted(kwargs.items())))
        if key not in instances:
            instances[key] = class_(*args, **kwargs)
        return instances[key]

    return getinstance
