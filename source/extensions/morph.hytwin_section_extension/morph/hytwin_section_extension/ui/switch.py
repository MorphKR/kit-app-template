import omni.ui as ui


class Switch:
    """토글 스위치 UI 모델과 버튼 상태를 관리한다."""
    def __init__(self, model: ui.SimpleBoolModel, **kwargs):
        """인스턴스의 초기 상태를 구성한다."""
        self._model = model

        self._image = ui.ImageWithProvider(
            checked=model.as_bool,
            width=24,
            height=24,
            # image_width=24,
            # image_height=24,
            style_type_name_override="Switch",
            mouse_pressed_fn=lambda x, y, key, a: self._on_clicked(key),
            identifier="switch",
            **kwargs,
        )

        self.__sub = model.subscribe_value_changed_fn(self.__on_changed)

    def destroy(self) -> None:
        """사용한 구독과 리소스를 정리한다."""
        self.__sub = None

    @property
    def model(self) -> ui.SimpleBoolModel:
        """현재 상태에서 필요한 값을 조회해 반환한다."""
        return self._model

    @property
    def checked(self) -> bool:
        """현재 상태에서 필요한 값을 조회해 반환한다."""
        return self._image.checked

    @checked.setter
    def checked(self, value: bool):
        """현재 상태에서 필요한 값을 조회해 반환한다."""
        self._image.checked = value

    def _on_clicked(self, button, *_):
        """이벤트가 발생했을 때 후속 처리를 수행한다."""
        if button != 0:  # pragma: no cover
            return

        self.checked = not self.checked
        self._model.set_value(self.checked)

    def __on_changed(self, model: ui.SimpleBoolModel) -> None:
        """해당 함수의 핵심 로직을 수행한다."""
        self._image.checked = model.as_bool
