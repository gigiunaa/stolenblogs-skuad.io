# blog_scraper_skuad.py
# -*- coding: utf-8 -*-
import os
import re
import json
import logging
import requests
from flask import Flask, request, Response
from flask_cors import CORS
from bs4 import BeautifulSoup

logging.basicConfig(level=logging.INFO)
app = Flask(__name__)
CORS(app)

def extract_images(container):
    image_urls = set()
    if not container:
        return []

    for img in container.find_all("img"):
        src = (
            img.get("src")
            or img.get("data-src")
            or img.get("data-lazy-src")
            or img.get("data-original")
            or img.get("data-background")
        )
        if not src and img.get("srcset"):
            src = img["srcset"].split(",")[0].split()[0]
        if src:
            if src.startswith("//"):
                src = "https:" + src
            if src.startswith(("http://", "https://")):
                image_urls.add(src)

    for source in container.find_all("source"):
        srcset = source.get("srcset")
        if srcset:
            first = srcset.split(",")[0].split()[0]
            if first.startswith("//"):
                first = "https:" + first
            if first.startswith(("http://", "https://")):
                image_urls.add(first)

    for tag in container.find_all(style=True):
        style = tag["style"]
        for match in re.findall(r"url\((.*?)\)", style):
            url = match.strip("\"' ")
            if url.startswith("//"):
                url = "https:" + url
            if url.startswith(("http://", "https://")):
                image_urls.add(url)

    return list(image_urls)

def clean_article(article):
    if not article:
        return None
    for tag in article(["script", "style", "svg", "noscript"]):
        tag.decompose()
    for tag in article.find_all(True):
        if tag.name not in [
            "p", "h1", "h2", "h3", "ul", "ol", "li", "img",
            "strong", "em", "b", "i", "a"
        ]:
            tag.unwrap()
            continue
        if tag.name == "img":
            src = (
                tag.get("src")
                or tag.get("data-src")
                or tag.get("data-lazy-src")
                or tag.get("data-original")
                or tag.get("data-background")
            )
            if not src and tag.get("srcset"):
                src = tag["srcset"].split(",")[0].split()[0]
            if src and src.startswith("//"):
                src = "https:" + src
            alt = tag.get("alt", "").strip() or "Image"
            tag.attrs = {"src": src or "", "alt": alt}
        else:
            tag.attrs = {}
    return article

def extract_blog_content(soup):
    articles = soup.find_all("article", class_="blog-details-rich")
    cleaned_articles = [clean_article(a) for a in articles if a]
    combined_html = "".join([str(a) for a in cleaned_articles if a])
    return combined_html

@app.route("/scrape-blog", methods=["POST"])
def scrape_blog():
    try:
        data = request.get_json(force=True)
        url = data.get("url")
        if not url:
            return Response("Missing 'url' field", status=400)

        resp = requests.get(url, timeout=20, headers={"User-Agent": "Mozilla/5.0"})
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        h1 = soup.find("h1", class_="payo-h1")
        title = h1.get_text(strip=True) if h1 else ""

        content_html = extract_blog_content(soup)

        images = set()
        main_img_container = soup.find("div", class_="py-blog-image")
        if main_img_container:
            images.update(extract_images(main_img_container))

        article_containers = soup.find_all("article", class_="blog-details-rich")
        for c in article_containers:
            images.update(extract_images(c))

        images = list(images)
        image_names = [f"image{i+1}.png" for i in range(len(images))]

        result = {
            "title": title,
            "content_html": f"<h1>{title}</h1>{content_html}",
            "images": images,
            "image_names": image_names,
        }

        return Response(json.dumps(result, ensure_ascii=False), mimetype="application/json")

    except Exception as e:
        logging.exception("Error scraping blog")
        return Response(f"Error: {str(e)}", status=500)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
