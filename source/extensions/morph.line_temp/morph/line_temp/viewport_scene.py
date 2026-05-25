from omni.ui import scene as sc
import omni.ui as ui

from .object_info_manipulator import ObjInfoManipulator
from .object_info_model import ObjInfoModel


class ViewportSceneInfo():
    TEXT_MARGIN_PERCENT = 0.10

    def __init__(self, viewportWindow, ext_id) -> None:
        self.sceneView = None
        self.viewportWindow = viewportWindow
        self.model = None
        self.manipulator = None
        self.overlay_frame = None
        self.text_label = None
        self._last_direction = None
        self._update_sub = None

        with self.viewportWindow.get_frame(ext_id):
            self.sceneView = sc.SceneView()

            with self.sceneView.scene:
                self.model = ObjInfoModel()
                self.manipulator = ObjInfoManipulator(
                    model=self.model,
                    viewport_api=self.viewportWindow.viewport_api,
                )

            self.viewportWindow.viewport_api.add_scene_view(self.sceneView)

        self.overlay_frame = self.viewportWindow.get_frame(ext_id + "_fixed_text")
        self._build_fixed_text_overlay("up")

        if self.model:
            self.model.add_item_changed_fn(self._on_model_item_changed)
            self._sync_fixed_text()

        self._install_update_subscription()

    def __del__(self):
        self.destroy()

    def _install_update_subscription(self):
        try:
            import omni.kit.app
            self._update_sub = omni.kit.app.get_app().get_update_event_stream().create_subscription_to_pop(
                self._on_update,
                name="object_info_fixed_text_leader_line_update",
            )
        except Exception:
            self._update_sub = None

    def _on_update(self, event):
        if not self.model or not self.manipulator:
            return

        if not self.model.get_item("name"):
            return

        self._sync_fixed_text()
        self._sync_text_metrics_to_manipulator()
        self.manipulator.invalidate()

    def _build_fixed_text_overlay(self, direction="up"):
        if not self.overlay_frame:
            return

        self._last_direction = direction
        self.overlay_frame.clear()

        with self.overlay_frame:
            with ui.ZStack():
                if direction == "down":
                    self._build_bottom_left_text_layout()
                else:
                    self._build_top_right_text_layout()

    def _build_top_right_text_layout(self):
        with ui.VStack():
            ui.Spacer(height=ui.Percent(self.TEXT_MARGIN_PERCENT * 100.0))
            with ui.HStack():
                ui.Spacer()
                self.text_label = ui.Label(
                    "",
                    alignment=ui.Alignment.RIGHT_CENTER,
                    style={
                        "color": 0xFFFFFFFF,
                        "font_size": 16,
                    },
                )
                ui.Spacer(width=ui.Percent(self.TEXT_MARGIN_PERCENT * 100.0))
            ui.Spacer()

    def _build_bottom_left_text_layout(self):
        with ui.VStack():
            ui.Spacer()
            with ui.HStack():
                ui.Spacer(width=ui.Percent(self.TEXT_MARGIN_PERCENT * 100.0))
                self.text_label = ui.Label(
                    "",
                    alignment=ui.Alignment.LEFT_CENTER,
                    style={
                        "color": 0xFFFFFFFF,
                        "font_size": 16,
                    },
                )
                ui.Spacer()
            ui.Spacer(height=ui.Percent(self.TEXT_MARGIN_PERCENT * 100.0))

    def _on_model_item_changed(self, item):
        self._sync_fixed_text()
        self._sync_text_metrics_to_manipulator()
        if self.manipulator:
            self.manipulator.invalidate()

    def _sync_fixed_text(self):
        if not self.model:
            return

        name = self.model.get_item("name")
        if not name:
            if self.text_label:
                self.text_label.text = ""
            if self.manipulator:
                self.manipulator.set_text_metrics("up", 0.0, 0.0)
            return

        direction = "up"
        if hasattr(self.model, "get_line_direction"):
            direction = self.model.get_line_direction()

        if direction != self._last_direction:
            self._build_fixed_text_overlay(direction)

        if self.text_label:
            self.text_label.text = f"Path: {name}"

    def _sync_text_metrics_to_manipulator(self):
        if not self.manipulator or not self.text_label:
            return

        direction = "up"
        if self.model and hasattr(self.model, "get_line_direction"):
            direction = self.model.get_line_direction()

        width = self._get_computed_value(self.text_label, "computed_width")
        height = self._get_computed_value(self.text_label, "computed_height")

        self.manipulator.set_text_metrics(direction, width, height)

    def _get_computed_value(self, widget, attr_name):
        value = getattr(widget, attr_name, 0.0)
        try:
            if callable(value):
                value = value()
            return float(value or 0.0)
        except Exception:
            return 0.0

    def show_manual_outline(self, name="", position=None, bbox_min=None, bbox_max=None, prim_path=None):
        """
        Show object info outline without modifying usd_context selection.
        """
        if not self.model:
            return False

        self.model.set_manual_target(
            name=name,
            position=position,
            bbox_min=bbox_min,
            bbox_max=bbox_max,
            prim_path=prim_path,
        )
        self._sync_fixed_text()
        self._sync_text_metrics_to_manipulator()
        if self.manipulator:
            self.manipulator.invalidate()
        return True

    def clear_manual_outline(self):
        if self.model:
            self.model.clear_manual_target()
        self._sync_fixed_text()
        self._sync_text_metrics_to_manipulator()
        if self.manipulator:
            self.manipulator.invalidate()

    def destroy(self):
        if self._update_sub:
            self._update_sub.unsubscribe()
            self._update_sub = None

        if self.overlay_frame:
            self.overlay_frame.clear()
            self.overlay_frame = None
        self.text_label = None

        if self.model:
            self.model.destroy()
            self.model = None

        if self.sceneView:
            self.sceneView.scene.clear()

            if self.viewportWindow:
                self.viewportWindow.viewport_api.remove_scene_view(self.sceneView)

        self.manipulator = None
        self.viewportWindow = None
        self.sceneView = None
