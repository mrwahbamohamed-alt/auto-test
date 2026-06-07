from PIL import Image, ImageDraw, ImageFont

def make_ico():
    size = 256
    img = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    # Dark background circle
    d.ellipse([4, 4, 252, 252], fill='#121214', outline='#0A84FF', width=6)

    # Injector body (main cylinder)
    bx, by, bw, bh = 100, 28, 56, 108
    d.rounded_rectangle([bx, by, bx+bw, by+bh], radius=10,
                         fill='#2C2C2E', outline='#0A84FF', width=3)

    # Top connector rings
    for y in [38, 50, 62]:
        d.rectangle([bx-8, y, bx+bw+8, y+8], fill='#3A3A3C', outline='#48484A', width=1)

    # Nozzle tip (tapered)
    nozzle = [(128, 136), (108, 172), (120, 172), (124, 208),
              (132, 208), (136, 172), (148, 172)]
    d.polygon(nozzle, fill='#30D158', outline='#228B44', width=2)

    # Spray lines from nozzle tip
    spray_pts = [(110, 224), (116, 232), (128, 236), (140, 232), (146, 224)]
    for sx, sy in spray_pts:
        d.line([(128, 208), (sx, sy)], fill='#0A84FF', width=2)
        d.ellipse([sx-4, sy-4, sx+4, sy+4], fill='#0A84FF')

    # Electrical connector on top
    d.rounded_rectangle([112, 16, 144, 30], radius=4, fill='#FF9F0A')
    d.rectangle([121, 8, 135, 18], fill='#FF9F0A')

    # Save preview PNG too
    img.save(r"C:\Users\LAPIX\AppData\Local\Temp\campro_preview.png")

    # Save ICO
    ico_path = r"C:\Users\LAPIX\OneDrive\Desktop\Diesel Dashboard\campro.ico"
    sizes = [(16,16),(32,32),(48,48),(64,64),(128,128),(256,256)]
    imgs = [img.resize(s, Image.LANCZOS) for s in sizes]
    imgs[0].save(ico_path, format='ICO', sizes=[(s[0],s[1]) for s in sizes],
                 append_images=imgs[1:])
    print("ICO saved:", ico_path)
    return ico_path

if __name__ == "__main__":
    make_ico()
