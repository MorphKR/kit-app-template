from omni.ui import scene as sc


class ObjInfoManipulator(sc.Manipulator):

    DOT_RADIUS = 4.0
    DOT_THICKNESS = 2.0
    LINE_THICKNESS = 2.0
    TEXT_MARGIN_PERCENT = 0.10

    LINE_COLOR = 0xFFFFFFFF
    DOT_COLOR = 0xFFFFFFFF

    def __init__(self, *args, viewport_api=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.viewport_api = viewport_api
        self._text_width = 0.0
        self._text_height = 0.0
        self._text_direction = "up"

    def set_text_metrics(self, direction="up", width=0.0, height=0.0):
        self._text_direction = direction or "up"
        self._text_width = max(float(width or 0.0), 0.0)
        self._text_height = max(float(height or 0.0), 0.0)
        self.invalidate()

    def on_build(self):
        """Called when the model is changed and rebuilds the whole manipulator."""

        if not self.model:
            return

        if self.model.get_item("name") == "":
            return

        position = self.model.get_as_floats(self.model.get_item("position"))
        if not position or len(position) != 3:
            return

        self._build_dot_and_line(position)

    def _build_dot_and_line(self, position):
        line_end = self._get_screen_line_end(position)

        with sc.Transform(transform=sc.Matrix44.get_translation_matrix(*position)):
            with sc.Transform(look_at=sc.Transform.LookAt.CAMERA):
                with sc.Transform(scale_to=sc.Space.SCREEN):
                    sc.Arc(
                        self.DOT_RADIUS,
                        begin=0,
                        end=360,
                        axis=2,
                        color=self.DOT_COLOR,
                        thickness=self.DOT_THICKNESS,
                        tesselation=32,
                    )

                    if line_end is not None:
                        sc.Line(
                            [0.0, 0.0, 0.0],
                            [line_end[0], line_end[1], 0.0],
                            color=self.LINE_COLOR,
                            thickness=self.LINE_THICKNESS,
                        )

    def _get_screen_line_end(self, anchor_world):
        """
        Returns SCREEN local delta from the anchor dot to the fixed UI text center.

        NDC and UI pixel values are not mixed directly:
        1. Convert dynamic UI label size from pixels to NDC.
        2. Build the final text-center target in NDC.
        3. Convert NDC delta to SCREEN local units once.
        """
        if not self.viewport_api:
            return None

        world_to_ndc = getattr(self.viewport_api, "world_to_ndc", None)
        if world_to_ndc is None:
            return None

        resolution = getattr(self.viewport_api, "resolution", None)
        if not resolution or len(resolution) < 2:
            return None

        try:
            width = float(resolution[0])
            height = float(resolution[1])
            if width <= 0.0 or height <= 0.0:
                return None

            anchor_ndc = world_to_ndc.Transform(anchor_world)
            if anchor_ndc is None or len(anchor_ndc) < 2:
                return None

            anchor_x = float(anchor_ndc[0])
            anchor_y = float(anchor_ndc[1])
            if anchor_x < -1.25 or anchor_x > 1.25 or anchor_y < -1.25 or anchor_y > 1.25:
                return None

            target_x, target_y = self._get_fixed_text_center_ndc(width, height)

            delta_x = (target_x - anchor_x) * width * 0.5
            delta_y = (target_y - anchor_y) * height * 0.5

            return [delta_x, delta_y]
        except Exception:
            return None

    def _get_fixed_text_center_ndc(self, viewport_width, viewport_height):
        corner_x, corner_y = self._get_fixed_text_corner_ndc()

        # Convert dynamic UI size from pixels to NDC before applying it.
        half_text_width_ndc = (self._text_width * 0.5) / max(float(viewport_width), 1.0) * 2.0
        half_text_height_ndc = (self._text_height * 0.5) / max(float(viewport_height), 1.0) * 2.0

        if self._text_direction == "down":
            return [
                corner_x + half_text_width_ndc,
                corner_y + half_text_height_ndc,
            ]

        return [
            corner_x - half_text_width_ndc,
            corner_y - half_text_height_ndc,
        ]

    def _get_fixed_text_corner_ndc(self):
        margin = self.TEXT_MARGIN_PERCENT
        inset = margin * 2.0

        direction = self._text_direction
        if hasattr(self.model, "get_line_direction"):
            direction = self.model.get_line_direction()

        if direction == "down":
            return [-1.0 + inset, -1.0 + inset]

        return [1.0 - inset, 1.0 - inset]

    def on_model_updated(self, item):
        self.invalidate()
