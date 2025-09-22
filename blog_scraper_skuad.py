# -*- coding: utf-8 -*-
import os
import re
import json
import logging
import requests
from flask import Flask, request, Response, jsonify
from flask_cors import CORS
from bs4 import BeautifulSoup

logging.basicConfig(level=logging.INFO)
app = Flask(__name__)
CORS(app)

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123 Safari/537.36"

# ------------------------------
# Helpers
# ------------------------------
def _first_src_from_srcset(srcset: str) -> str:
    if not srcset:
        return ""
    # e.g. "url1 1x, url2 2x"
    first = srcset.split(",")[0].strip().split()[0]
    return first

def _absolutize(url: str) -> str:
    if not url:
        return ""
    if url.startswith("//"):
        return "https:" + url
    return url

def extract_images(container) -> list:
    """Collect image URLs from <img>, <source srcset>, style background-image."""
    if container is None:
        return []
    urls = set()

    # <img>
    for img in container.find_all("img"):
        src = (
            img.get("src")
            or img.get("data-src")
            or img.get("data-lazy-src")
            or img.get("data-original")
            or img.get("data-background")
        )
        if not src and img.get("srcset"):
            src = _first_src_from_srcset(img.get("srcset"))
        src = _absolutize(src)
        if src.startswith(("http://", "https://")):
            urls.add(src)

    # <source srcset="...">
    for source in container.find_all("source"):
        srcset = source.get("srcset")
        if srcset:
            first = _absolutize(_first_src_from_srcset(srcset))
            if first.startswith(("http://", "https://")):
                urls.add(first)

    # style="background-image:url(...)"
    for tag in container.find_all(style=True):
        style = tag["style"]
        for match in re.findall(r"url\((.*?)\)", style):
            u = _absolutize(match.strip("\"' "))
            if u.startswith(("http://", "https://")):
                urls.add(u)

    return list(urls)

def clean_article(node):
    """Sanitize article HTML and strip noisy attributes/components."""
    if node is None:
        return None

    # remove noisy blocks unique to Skuad blog layout (CTAs, tables of contents etc.)
    for sel in [
        "div.py-blog-cta",
        "div.toc-wrapper-new",
        "div.t-toc-stick",
        "div.blog-form",
        "div.normal-lead-magnet",
        "div.accordion-trigger",
        "div.toc-accordion-item",
        "script",
        "style",
        "svg",
        "noscript",
    ]:
        for t in node.select(sel):
            t.decompose()

    # allowlist of tags
    allowed = {"p","h1","h2","h3","ul","ol","li","img","strong","em","b","i","a","blockquote","code","pre"}

    for tag in list(node.find_all(True)):
        if tag.name not in allowed:
            # keep textual content, drop wrapper
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
                src = _first_src_from_srcset(tag.get("srcset"))
            src = _absolutize(src)
            alt = (tag.get("alt") or "Image").strip()
            if src:
                tag.attrs = {"src": src, "alt": alt}
            else:
                tag.decompose()
        elif tag.name == "a":
            href = tag.get("href", "").strip()
            tag.attrs = {"href": href} if href else {}
        else:
            tag.attrs = {}

    return node

def build_combined_article_html(soup: BeautifulSoup) -> str:
    """
    Skuad.io ბლოგის სტრუქტურა:
      - მთავარი სურათი: div.py-blog-image
      - კონტენტი: div.blog-content-new შიგნით მრავალი <article class="blog-details-rich w-richtext">
    ვიზამთ: შევკრიბოთ ყველა სტატიის <article> გაწმენდილი_html ერთად ერთ <article> wrapper-ში.
    """
    container = soup.find("div", class_="blog-content-new")
    if not container:
        # fallback: შეაგროვე ყველა richtext article დოკუმენტიდან
        articles = soup.find_all("article", class_="blog-details-rich")
    else:
        articles = container.find_all("article", class_="blog-details-rich")

    cleaned_parts = []
    for a in articles:
        cleaned = clean_article(a)
        if cleaned:
            cleaned_parts.append(str(cleaned))

    combined = "".join(cleaned_parts).strip()
    return f"<article>{combined}</article>" if combined else ""

def extract_title(soup: BeautifulSoup) -> str:
    """
    H1 სათაური: ძირითადად h1.payo-h1.mt-2 (ან უბრალოდ h1.payo-h1).
    ეკრანზე მოცემული ბლოკის მიხედვით fallback-ებიც დავამატოთ.
    """
    candidates = [
        "div.container-new h1.payo-h1",
        "h1.payo-h1",
        "h1.mt-2.payo-h1",
        "h1",  # very last fallback
    ]
    for sel in candidates:
        tag = soup.select_one(sel)
        if tag and tag.get_text(strip=True):
            return tag.get_text(strip=True)
    return ""

def extract_all_images(soup: BeautifulSoup) -> list:
    urls = set()
    # main hero image container
    hero = soup.find("div", class_="py-blog-image")
    if hero:
        urls.update(extract_images(hero))
    # content container images
    cont = soup.find("div", class_="blog-content-new")
    if cont:
        urls.update(extract_images(cont))
    # fallback: scan all articles
    for art in soup.find_all("article", class_="blog-details-rich"):
        urls.update(extract_images(art))
    return list(urls)

# ------------------------------
# API
# ------------------------------
@app.route("/scrape-blog", methods=["POST"])
def scrape_blog():
    try:
        data = request.get_json(force=True, silent=False)
        url = (data or {}).get("url")
        if not url:
            return jsonify({"error": "Missing 'url' field"}), 400

        # fetch
        resp = requests.get(url, timeout=25, headers={"User-Agent": UA})
        resp.raise_for_status()

        soup = BeautifulSoup(resp.text, "html.parser")

        # title
        title = extract_title(soup)

        # article html (single <article> wrapper containing all rich sections)
        article_html = build_combined_article_html(soup)
        if not article_html:
            return jsonify({"error": "Could not extract article content"}), 422

        # images
        images = extract_all_images(soup)
        image_names = [f"image{i+1}.png" for i in range(len(images))]

        # final content_html
        content_html = f"<h1>{title}</h1>{article_html}"

        result = {
            "title": title,
            "content_html": content_html,
            "images": images,
            "image_names": image_names
        }
        return Response(json.dumps(result, ensure_ascii=False), mimetype="application/json")

    except Exception as e:
        logging.exception("Error scraping blog")
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
