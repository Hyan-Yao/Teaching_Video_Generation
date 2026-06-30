base_class = """
class TeachingScene(Scene):
    def setup_layout(self, title_text, lecture_lines):
        import os
        _bg = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bg.png")
        if os.path.exists(_bg):
            self.camera.background_image = _bg
            self.camera.init_background()
        else:
            self.camera.background_color = "#0a0a0f"

        # Title: bold gold with a thin cyan rule beneath it
        self.title = Text(title_text, font_size=30, weight=BOLD, color="#FFD166").to_edge(UP)
        self.add(self.title)
        _sep = Line(
            self.title.get_left(), self.title.get_right(),
            color="#00F5D4", stroke_width=2
        ).next_to(self.title, DOWN, buff=0.07)
        self.add(_sep)

        # Left-side lecture: each line is VGroup(bullet_dot, text) so set_color() still works
        _rows = []
        for line in lecture_lines:
            _dot = Dot(radius=0.07, color="#FFD166")
            _txt = Text(line, font_size=20, color=WHITE)
            _txt.next_to(_dot, RIGHT, buff=0.18)
            _rows.append(VGroup(_dot, _txt))
        self.lecture = VGroup(*_rows).arrange(DOWN, aligned_edge=LEFT, buff=0.22).scale(0.85)
        self.lecture.to_edge(LEFT, buff=0.3)
        self.add(self.lecture)

        # Thin cyan accent bar to the left of the lecture block
        _bar = Rectangle(
            width=0.05, height=self.lecture.height + 0.2,
            fill_color="#00F5D4", fill_opacity=0.75, stroke_width=0
        ).next_to(self.lecture, LEFT, buff=0.1)
        self.add(_bar)

        # 6x6 animation grid (right side of screen)
        self.grid = {}
        for i, row in enumerate(["A", "B", "C", "D", "E", "F"]):
            for j, col in enumerate(["1", "2", "3", "4", "5", "6"]):
                self.grid[f"{row}{col}"] = np.array([0.5 + j * 1, 2.2 - i * 1, 0])

    def place_at_grid(self, mobject, grid_pos, scale_factor=1.0):
        mobject.scale(scale_factor)
        mobject.move_to(self.grid[grid_pos])
        return mobject

    def place_in_area(self, mobject, top_left, bottom_right, scale_factor=1.0):
        tl = self.grid[top_left]
        br = self.grid[bottom_right]
        mobject.scale(scale_factor)
        mobject.move_to(np.array([(tl[0] + br[0]) / 2, (tl[1] + br[1]) / 2, 0]))
        return mobject
"""
