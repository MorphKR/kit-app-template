from pathlib import Path


def get_data_path(filename):
    # 현재 파일 기준으로 확장 루트를 계산해 data 폴더 절대 경로를 만든다.
    ext_root_folder = Path(__file__).parent.parent.parent.parent.parent.parent
    return ext_root_folder.joinpath(f"data/{filename}").as_posix()


def Singleton(class_):
    """
    싱글턴 데코레이터.

    TODO: 유사 유틸이 다른 확장에도 있으므로 공용 유틸 확장으로 이동 검토.
    """
    instances = {}

    def getinstance(*args, **kwargs):
        if class_ not in instances:
            instances[class_] = class_(*args, **kwargs)
        return instances[class_]

    return getinstance
