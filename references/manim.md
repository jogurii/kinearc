# Manim Reference Guide

Manim (Mathematical Animation Engine) is a **Python-based engine** created for precise mathematical visualizations, physics animations, and scientific proofs.

---

## 1. Project Initialization

### Installation
```bash
pip install manim
```
*(Requires `ffmpeg` and optionally `latex` on the host system for LaTeX formulas).*

---

## 2. Core Architecture

Manim animations inherit from `Scene`. Elements on screen are `Mobject` instances (Math Objects).

### Example Script (`scene.py`)
```python
from manim import *

class MathProof(Scene):
    def construct(self):
        # 1. Title
        title = Title("Calculus & Geometry")
        self.play(Write(title))
        self.wait(0.5)

        # 2. LaTeX Formula
        formula = MathTex(r"\int_{0}^{\infty} e^{-x^2} dx = \frac{\sqrt{\pi}}{2}")
        formula.set_color(YELLOW)
        formula.scale(1.3)

        self.play(FadeIn(formula, shift=UP))
        self.wait(1)

        # 3. Geometric Shapes & Transforms
        circle = Circle(radius=1.5, color=BLUE)
        square = Square(side_length=3, color=RED)

        self.play(Transform(formula, circle))
        self.wait(0.5)
        self.play(ReplacementTransform(circle, square))
        self.wait(1)

        self.play(FadeOut(square), FadeOut(title))
```

---

## 3. CLI Commands & Flags

```bash
# Preview low-quality render (fast iteration)
manim -pql scene.py MathProof

# Render high-quality 1080p60 MP4
manim -pqh scene.py MathProof

# Render 4K 2160p60
manim -pqk scene.py MathProof

# Output transparent PNG sequence or GIF
manim -pqh --format=gif scene.py MathProof
```

*Flags:*
* `-p`: Preview video immediately after rendering.
* `-q` + `l/m/h/k`: Quality level (low 480p, medium 720p, high 1080p, 4K).
