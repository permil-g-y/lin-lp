#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Claude Design の書き出し（*.dc.html）から、公開用の index.html を生成する。

やっていること
  1. Mobile / PC それぞれの本体（コンテナ div）を取り出す
  2. Claude Design のエディタ用ランタイムを除去
       - <x-dc> / <helmet> / support.js / image-slot.js
       - omelette 注入スクリプトと <style data-omelette-injected>
       - <script type="text/x-dc">
  3. 未解決テンプレートを既定値で解決
       - <sc-if value="{{ showEarnings }}">  → 既定 true なので中身を残してタグだけ除去
       - <details open="{{ faqOpen }}">      → 既定 false なので open を除去（FAQを閉じる）
  4. <image-slot> を実ファイル参照の <img> に置換
       （画像は .image-slots.state.json から img/*.webp として書き出し済み）
  5. 640px を境に Mobile / PC のデザインを出し分ける 1 枚の HTML に合成
       - PC 側の @media (max-width:640px) は不要になるので落とす
       - 素のセレクタ（section / footer / [data-only] など）は #lp-pc / #lp-sp にスコープする

使い方:  python3 build.py
"""
import re, os, sys, json, base64

HERE = os.path.dirname(os.path.abspath(__file__))
MOBILE = os.path.join(HERE, "AI Canva Instagram講座 LP Mobile.dc.html")
PC     = os.path.join(HERE, "AI Canva Instagram講座 LP.dc.html")
STATE  = os.path.join(HERE, ".image-slots.state.json")
OUT    = os.path.join(HERE, "index.html")

# 公開先のドメインが決まったらここに入れる（例 "https://example.com/lp/"）。
# 空のままでも動くが、og:image / og:url / canonical は絶対URLでないとSNS側が解決できない。
SITE_URL = ""

TITLE = "AI × Canva 無料Instagram講座｜未経験から副業・在宅ワークの第一歩を"
DESC  = ("ChatGPTとCanvaを使って、Instagram投稿をゼロから作れるように。"
         "未経験OK・完全無料・質問し放題。株式会社凛が運営する無料オンライン講座です。")

# image-slot の placeholder より読みやすい alt を当てる
ALT = {
    "post-beauty":  "美容・コスメジャンルのInstagram投稿作例",
    "post-sidejob": "ノウハウ・副業系ジャンルのInstagram投稿作例",
    "post-life":    "暮らし・ライフスタイルジャンルのInstagram投稿作例",
    "post-cafe":    "グルメ・カフェジャンルのInstagram投稿作例",
    "post-kids":    "子育てジャンルのInstagram投稿作例",
    "post-salon":   "店舗・サロンジャンルのInstagram投稿作例",
    "post-ec":      "商品紹介・ECジャンルのInstagram投稿作例",
    "closing-photo":"Instagram投稿を自分で完成させて笑顔になっている女性",
}


def export_slot_images():
    """.image-slots.state.json の data URI を img/<id>.webp として書き出す"""
    if not os.path.exists(STATE):
        return []
    state = json.load(open(STATE, encoding="utf-8"))
    written = []
    for sid, v in state.items():
        u = v.get("u", "")
        if not u.startswith("data:image/"):
            continue
        ext = u.split(";")[0].split("/")[1]
        path = os.path.join(HERE, "img", f"{sid}.{ext}")
        data = base64.b64decode(u.split(",", 1)[1])
        if not os.path.exists(path) or open(path, "rb").read() != data:
            open(path, "wb").write(data)
        written.append(f"img/{sid}.{ext}")
    return written


def slot_to_img(m):
    """<image-slot ...></image-slot> を <img> に変換"""
    tag = m.group(0)

    def attr(name):
        a = re.search(rf'{name}="([^"]*)"', tag)
        return a.group(1) if a else ""

    sid   = attr("id")
    style = attr("style")
    src   = attr("src")
    shape = attr("shape")
    radius= attr("radius")
    alt   = ALT.get(sid) or attr("placeholder") or ""

    if not src:  # state 由来の画像
        for ext in ("webp", "png", "jpg"):
            if os.path.exists(os.path.join(HERE, "img", f"{sid}.{ext}")):
                src = f"img/{sid}.{ext}"
                break
    if not src:
        sys.exit(f"[build] image-slot #{sid} の画像が見つかりません")

    extra = "display:block;object-fit:cover"
    if shape == "rounded":
        extra += f";border-radius:{radius or 4}px"
    style = (style.rstrip(";") + ";" + extra) if style else extra
    return f'<img src="{src}" alt="{alt}" loading="lazy" decoding="async" style="{style}">'


def load_body(path):
    """dc.html から helmet 内 <style> と本体コンテナを取り出す"""
    html = open(path, encoding="utf-8").read()

    m = re.search(r"<helmet[^>]*>(.*?)</helmet>", html, re.S)
    if not m:
        sys.exit(f"[build] helmet が見つかりません: {path}")
    helmet = m.group(1)
    styles = "\n".join(s.group(1) for s in re.finditer(r"<style[^>]*>(.*?)</style>", helmet, re.S))

    body = html[m.end():]
    body = body[: body.index("</x-dc>")]

    # --- Claude Design ランタイム痕跡の除去 -------------------------------
    body = re.sub(r'<script[^>]*type="text/x-dc"[^>]*>.*?</script>', "", body, flags=re.S)
    # --- 未解決テンプレートの解決 ----------------------------------------
    #  sc-if は既定 true → タグだけ剥がして中身を残す
    body = re.sub(r"</?sc-if[^>]*>", "", body)
    #  details の open は既定 false → 属性ごと除去（FAQ を閉じた状態にする）
    body = re.sub(r'\s+open="\{\{[^"]*\}\}"', "", body)
    # --- image-slot → img -------------------------------------------------
    body = re.sub(r"<image-slot\b[^>]*>\s*</image-slot>", slot_to_img, body)

    leftover = re.findall(r"\{\{[^}]*\}\}", body)
    if leftover:
        sys.exit(f"[build] 未解決テンプレートが残っています: {set(leftover)}")
    if "<image-slot" in body or "<sc-if" in body:
        sys.exit("[build] 独自要素が残っています")

    return styles.strip(), body.strip()


def scope_ids(body, prefix):
    """Mobile版とPC版を1ページに同居させるので、id と内部アンカーを衝突しないよう接頭辞付きにする"""
    ids = set(re.findall(r'\sid="([^"]+)"', body))
    for i in sorted(ids, key=len, reverse=True):
        body = body.replace(f'id="{i}"', f'id="{prefix}{i}"')
        body = body.replace(f'href="#{i}"', f'href="#{prefix}{i}"')
    return body


def lazyload(body, skip_first_section=True):
    """ファーストビューより下の画像だけ遅延読み込みにする（FVの markup は触らない）"""
    if skip_first_section:
        cut = body.index("</section>") + len("</section>")
    else:
        cut = 0
    head, tail = body[:cut], body[cut:]
    tail = re.sub(r"<img (?![^>]*loading=)", '<img loading="lazy" decoding="async" ', tail)
    return head + tail


def scope_css(css, scope):
    """素のセレクタをスコープ配下に閉じ込める。@media (max-width:640px) ブロックは落とす。"""
    css = re.sub(r"@media\s*\(max-width:\s*640px\)\s*\{.*?\n\}\n?", "", css, flags=re.S)
    out = []
    for rule in re.finditer(r"([^{}]+)\{([^{}]*)\}", css):
        sel, decl = rule.group(1).strip(), rule.group(2).strip()
        if not sel or not decl:
            continue
        parts = []
        for s in sel.split(","):
            s = s.strip()
            if s in ("html,body", "html", "body", "*"):
                parts = None      # ページ全体に効くリセットは共通側で持つ
                break
            parts.append(f"{scope} {s}")
        if parts is None:
            continue
        out.append(", ".join(parts) + "{" + decl + "}")
    return "\n".join(out)


# FV で使う写真は「変更しない」指示があるため最適化対象から外す
KEEP_AS_IS = {"img/fv-laptop.png"}
MAX_EDGE = 1400          # 表示上必要な最大辺（Retina 2x 相当まで確保）


def optimize_photos(html):
    """FV以外の写真を WebP 化して差し替える（見た目は変えず転送量だけ落とす）"""
    try:
        from PIL import Image
    except ImportError:
        return html, []
    done = []
    for rel in sorted(set(re.findall(r'"(img/[^"]+\.(?:png|jpe?g))"', html))):
        if rel in KEEP_AS_IS or rel.endswith("ogp.jpg"):
            continue
        src = os.path.join(HERE, rel)
        if not os.path.exists(src):
            continue
        dst_rel = re.sub(r"\.(png|jpe?g)$", ".webp", rel)
        dst = os.path.join(HERE, dst_rel)
        im = Image.open(src).convert("RGB")
        if max(im.size) > MAX_EDGE:
            r = MAX_EDGE / max(im.size)
            im = im.resize((round(im.size[0] * r), round(im.size[1] * r)), Image.LANCZOS)
        im.save(dst, "WEBP", quality=88, method=6)
        before, after = os.path.getsize(src), os.path.getsize(dst)
        html = html.replace(f'"{rel}"', f'"{dst_rel}"')
        done.append((rel, dst_rel, before, after))
    return html, done


def make_ogp():
    """FV写真から 1200x630 の OGP 画像を切り出す（デザインは足さない）"""
    try:
        from PIL import Image
    except ImportError:
        return None
    srcp = os.path.join(HERE, "img", "fv-laptop.png")
    if not os.path.exists(srcp):
        return None
    dst = os.path.join(HERE, "img", "ogp.jpg")
    im = Image.open(srcp).convert("RGB")
    w, h = im.size
    th = int(w * 630 / 1200)
    top = int(h * 0.16)                       # 人物の顔が入るように上寄りで切る
    top = max(0, min(top, h - th))
    im.crop((0, top, w, top + th)).resize((1200, 630), Image.LANCZOS)\
      .save(dst, quality=86, optimize=True)
    return "img/ogp.jpg"


def main():
    imgs = export_slot_images()
    sp_css, sp_body = load_body(MOBILE)
    pc_css, pc_body = load_body(PC)

    # 1ページに同居させるため id/アンカーを分離し、FV より下の画像を遅延読み込みにする
    sp_body = lazyload(scope_ids(sp_body, "sp-"))
    # PC版は先頭に「01 FV スマホ」(非表示) と「01 FV」が並ぶので 2 セクション分を除外
    pc_body = scope_ids(pc_body, "pc-")
    _cut = pc_body.index("</section>", pc_body.index("</section>") + 1) + len("</section>")
    pc_body = pc_body[:_cut] + lazyload(pc_body[_cut:], skip_first_section=False)

    ogp = make_ogp()

    base = SITE_URL.rstrip("/") + "/" if SITE_URL else ""
    head_ogp = ""
    if ogp:
        head_ogp = (f'\n<meta property="og:image" content="{base}{ogp}">'
                    f'\n<meta name="twitter:card" content="summary_large_image">')
    if base:
        head_ogp += (f'\n<meta property="og:url" content="{base}">'
                     f'\n<link rel="canonical" href="{base}">')
    else:
        head_ogp += ('\n<!-- 公開ドメイン確定後、build.py の SITE_URL を設定して再ビルドすると'
                     ' og:image / og:url / canonical が絶対URLになります -->')

    html = f"""<!doctype html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{TITLE}</title>
<meta name="description" content="{DESC}">
<meta name="format-detection" content="telephone=no">
<meta name="theme-color" content="#FFFCFA">
<meta property="og:type" content="website">
<meta property="og:site_name" content="AI × Canva 無料Instagram講座">
<meta property="og:title" content="{TITLE}">
<meta property="og:description" content="{DESC}">
<meta property="og:locale" content="ja_JP">{head_ogp}
<link rel="icon" href="favicon.svg" type="image/svg+xml">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Noto+Sans+JP:wght@400;500;700&family=Shippori+Mincho+B1:wght@400;500;600&family=Cormorant+Garamond:wght@300;400;500;600&family=Yusei+Magic&display=swap" rel="stylesheet">
<style>
/* ---- 共通リセット（Claude Design の helmet 由来） ---- */
html,body{{margin:0;padding:0}}
*{{box-sizing:border-box;text-wrap:pretty}}
body{{-webkit-font-smoothing:antialiased;background:#FFFCFA}}
img{{max-width:100%}}
a{{color:#D2708D}}
a:hover{{color:#EE7C9B}}
summary::-webkit-details-marker{{display:none}}
html{{scroll-behavior:smooth}}
@media (prefers-reduced-motion:reduce){{html{{scroll-behavior:auto}}}}

/* ---- Mobile / PC の出し分け（640px 境界） ---- */
#lp-sp,#lp-pc{{display:none}}
@media (max-width:640px){{ #lp-sp{{display:block}} body{{background:#EDE9E6}} }}
@media (min-width:641px){{ #lp-pc{{display:block}} }}

/* ---- Mobile 版（#lp-sp）由来 ---- */
{scope_css(sp_css, '#lp-sp')}

/* ---- PC 版（#lp-pc）由来 ---- */
{scope_css(pc_css, '#lp-pc')}
</style>
</head>
<body>

<!-- ============ スマートフォン版（〜640px） ============ -->
<div id="lp-sp">
{sp_body}
</div>

<!-- ============ PC版（641px〜） ============ -->
<div id="lp-pc">
{pc_body}
</div>

</body>
</html>
"""
    html, opt = optimize_photos(html)
    if opt:
        b = sum(x[2] for x in opt) / 1024 / 1024
        a = sum(x[3] for x in opt) / 1024 / 1024
        print(f"[build] 写真をWebP化: {len(opt)}点  {b:.1f}MB → {a:.1f}MB")
        for rel, dst, bb, aa in opt:
            print(f"          {rel:<26} → {dst:<26} {bb/1024:>7.0f}KB → {aa/1024:>6.0f}KB")

    open(OUT, "w", encoding="utf-8").write(html)
    print(f"[build] 生成: {OUT}  ({len(html):,} bytes)")
    if imgs:
        print(f"[build] 画像書き出し: {len(imgs)}点")
    if ogp:
        print(f"[build] OGP画像: {ogp}")

    make_dist(html)


def make_dist(html):
    """サーバへそのまま上げられる形（public/）を作る。参照されている資産だけを入れる。"""
    import shutil
    dist = os.path.join(os.path.dirname(HERE), "public")
    if os.path.exists(dist):
        shutil.rmtree(dist)
    os.makedirs(os.path.join(dist, "img"))

    shutil.copy2(OUT, os.path.join(dist, "index.html"))
    for extra in ("favicon.svg", "robots.txt"):
        p = os.path.join(HERE, extra)
        if os.path.exists(p):
            shutil.copy2(p, os.path.join(dist, extra))

    used = sorted(set(re.findall(r'(?:src|href|content)="(img/[^"]+)"', html)))
    total = 0
    for rel in used:
        src = os.path.join(HERE, rel)
        if not os.path.exists(src):
            sys.exit(f"[build] 参照されている画像がありません: {rel}")
        shutil.copy2(src, os.path.join(dist, rel))
        total += os.path.getsize(src)

    unused = [f for f in sorted(os.listdir(os.path.join(HERE, "img")))
              if f"img/{f}" not in used]
    print(f"[build] 公開用: {dist}  (HTML + 画像{len(used)}点 / 画像計 {total/1024/1024:.1f}MB)")
    if unused:
        print(f"[build] 未使用のため公開用に含めなかった画像: {', '.join(unused)}")


if __name__ == "__main__":
    main()
