from pathlib import Path


def get_data_path(filename):
    current = Path(__file__).resolve()
    for parent in current.parents:
        candidate = parent / "data" / filename
        if candidate.exists():
            return candidate.as_posix()
    # Fallback: expected extension root is .../<ext_name>/morph/hytwin_section_extension2/common/utils.py
    ext_root_folder = current.parents[3]
    return (ext_root_folder / "data" / filename).as_posix()


def Singleton(class_):
    """
    A singleton decorator.

    TODO: It's also available in other extensions. Do we have a utility extension where we can put the utilities
    like this?
    """
    instances = {}

    def getinstance(*args, **kwargs):
        if class_ not in instances:
            instances[class_] = class_(*args, **kwargs)
        return instances[class_]

    return getinstance
