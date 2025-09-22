# blog_scraper_clean.py
# -*- coding: utf-8 -*-
import os
import re
import json
import logging
import requests
from urllib.parse import urlparse
from flask import Flask, request, Response
from flask_cors import CORS
from bs4 import BeautifulSoup

logging.basicConfig(level=logging.INFO)
app = Flask(__name__)
CORS(app)


def clean_html(container):
    for tag in container(["script", "style", "svg", "noscript"]):
        tag.decompose()

    for tag in container.find_all(True):
        if tag.name not in [
            "p", "h1", "h2", "h3", "ul", "ol", "li", "img",
            "strong", "em", "b", "i", "a"
        ]:
            tag.unwrap()
            continue

        if tag.name == "img":
            src = tag.get("src")
            if not src and tag.get("srcset"):
                src = tag["srcset"].split(",")[0].split()[0]
            if src and src.startswith("//"):
                src = "https:" + src
            if src:
                alt = tag.get("alt", "").strip() or "Image"
                tag.attrs = {"src": src, "alt": alt}
            else:
                tag.decompose()

        elif tag.name == "a":
            href = tag.get("href", "").strip()
            tag.attrs = {"href": href} if href else {}
        else:
            tag.attrs = {}

    return container


@app.post("/scrape-blog")
def scrape_blog():
    try:
        data = request.get_json(force=True)
        url = data.get("url")
        if not url:
            return Response("Missing 'url' field", status=400)

        parsed = urlparse(url)
        if "safeguardglobal.com" not in parsed.netloc and "skuad.io" not in parsed.netloc:
            return Response("This scraper only works for safeguardglobal.com or skuad.io", status=403)

        resp = requests.get(url, timeout=20, headers={"User-Agent": "Mozilla/5.0"})
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        # ✅ სათაური
        h1_tag = soup.find("h1")
        title = h1_tag.get_text(strip=True) if h1_tag else ""

        # ✅ ბანერის სურათი
        banner_img = soup.select_one(".py-blog-image img, .container-new img")
        banner_url = banner_img["src"] if banner_img and banner_img.get("src") else None

        # ✅ სტატია (skuad.io → multiple articles, safeguardglobal → flex/gap-10 div)
        articles = soup.find_all("article", class_="blog-details-rich")
        if articles:
            article_html = "".join([str(clean_html(a)) for a in articles])
        else:
            article = soup.find("div", class_=lambda c: c and "lg:w-2/3" in c and "flex" in c)
            if not article:
                return Response("Could not extract blog content", status=422)
            article_html = str(clean_html(article))

        # ✅ content_html
        content_html = f"<article>{article_html}</article>"

        # ✅ მთავარი სურათი (იგივე banner)
        main_image_url = banner_url
        image_name = "image1.png" if main_image_url else None

        result = {
            "title": title,
            "banner_image": banner_url,
            "content_html": content_html,
            "image": main_image_url,
            "image_name": image_name
        }

        return Response(json.dumps(result, ensure_ascii=False), mimetype="application/json")
    except Exception as e:
        logging.exception("Error scraping blog")
        return Response(json.dumps({"error": str(e)}), status=500, mimetype="application/json")


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
