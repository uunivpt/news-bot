from __future__ import annotations
import io, os, re
from pathlib import Path
from urllib.request import Request, urlopen
from PIL import Image, ImageDraw, ImageFont, ImageOps

W,H=1080,1350
RW,RH=1080,1920

def _font(size,bold=False):
    paths=[os.getenv("NEWS_FONT_BOLD" if bold else "NEWS_FONT","")]
    paths += ["/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf"]
    for p in paths:
        if p and Path(p).exists(): return ImageFont.truetype(p,size)
    return ImageFont.load_default()

def _download(url):
    if not url or not url.startswith(("http://","https://")): return None
    try:
        req=Request(url,headers={"User-Agent":"NewsDeskBot/1.0"})
        with urlopen(req,timeout=12) as r: return Image.open(io.BytesIO(r.read())).convert("RGB")
    except Exception: return None

def _wrap(draw,text,font,width):
    lines=[]; cur=""
    for word in re.split(r"\s+",(text or "").strip()):
        test=word if not cur else cur+" "+word
        if draw.textbbox((0,0),test,font=font)[2] <= width: cur=test
        else:
            if cur: lines.append(cur)
            cur=word
    if cur: lines.append(cur)
    return lines

def build_graphic(title,category="general",image_url=None,label="NEWS",reel=False,out_path="graphic.jpg"):
    size=(RW,RH) if reel else (W,H); margin=70
    accent={"politics":"#1f2937","world":"#0f4c81","business":"#14532d","technology":"#3730a3","sports":"#9a3412","entertainment":"#7c2d12","science":"#155e75","health":"#166534","india":"#7c2d12"}.get(category,"#111827")
    canvas=Image.new("RGB",size,"#f5f7fa"); draw=ImageDraw.Draw(canvas); draw.rectangle((0,0,size[0],18),fill=accent)
    fh=_font(66 if reel else 58,True); fl=_font(34,True); fs=_font(28)
    img_h=760 if reel else 590; img=_download(image_url)
    if img:
        canvas.paste(ImageOps.fit(img,(size[0],img_h),method=Image.Resampling.LANCZOS),(0,0))
        ov=Image.new("RGBA",size,(0,0,0,0)); od=ImageDraw.Draw(ov); od.rectangle((0,img_h-300,size[0],img_h),fill=(0,0,0,155)); canvas=Image.alpha_composite(canvas.convert("RGBA"),ov).convert("RGB"); draw=ImageDraw.Draw(canvas)
    else:
        draw.rectangle((0,0,size[0],img_h),fill="#e5e7eb"); draw.text((margin,120),"NEWS",font=_font(72,True),fill=accent); draw.text((margin,220),category.upper(),font=_font(32,True),fill="#6b7280")
    draw.rounded_rectangle((margin,img_h-130,margin+210,img_h-72),radius=16,fill=accent); draw.text((margin+22,img_h-122),label.upper(),font=fl,fill="white")
    top=img_h+65
    for i,line in enumerate(_wrap(draw,title,fh,size[0]-2*margin)[:6]): draw.text((margin,top+i*78),line,font=fh,fill="#111827")
    draw.text((margin,size[1]-80),"NewsDesk  •  Source-linked reporting",font=fs,fill="#6b7280")
    Path(out_path).parent.mkdir(parents=True,exist_ok=True); canvas.save(out_path,quality=92,optimize=True); return out_path
