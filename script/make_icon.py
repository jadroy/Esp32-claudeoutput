"""Generate the app icon — run once, outputs icon.png."""
from PIL import Image, ImageDraw

SIZE = 512
img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
draw = ImageDraw.Draw(img)

# Rounded terracotta square
draw.rounded_rectangle([40, 40, SIZE - 40, SIZE - 40], radius=96, fill="#D97757")

# Three white horizontal lines (e-ink text symbol)
bar_x0, bar_x1 = 140, SIZE - 140
for y in [185, 250, 315]:
    draw.rounded_rectangle([bar_x0, y, bar_x1, y + 18], radius=9, fill="#FFFFFF")

img.save("/Users/royjad/Documents/WWORK/Esp32-claudeoutput/script/icon.png")
print("icon.png created")
