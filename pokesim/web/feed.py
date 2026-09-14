"""Atom feed rendering without HTTP or database dependencies."""
from __future__ import annotations

import html
from datetime import datetime, timezone
from xml.etree.ElementTree import Element, SubElement, tostring

ATOM_NAMESPACE = 'http://www.w3.org/2005/Atom'


def iso_timestamp(ts: float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def render_feed(events: list[dict], public_url: str, title: str) -> bytes:
    base = public_url.rstrip('/')
    feed = Element('feed', xmlns=ATOM_NAMESPACE)
    SubElement(feed, 'title').text = title
    SubElement(feed, 'subtitle').text = 'A Pokémon Red that plays itself'
    SubElement(feed, 'id').text = f'{base}/feed.xml'
    SubElement(feed, 'link', href=f'{base}/feed.xml', rel='self')
    SubElement(feed, 'link', href=f'{base}/')
    SubElement(feed, 'updated').text = iso_timestamp(events[0]['ts'] if events else 0)

    for event in events:
        link = f"{base}/events/{event['id']}"
        image = f"{base}/shots/{event['shot']}" if event['shot'] else None
        entry = SubElement(feed, 'entry')
        SubElement(entry, 'title').text = event['title']
        SubElement(entry, 'id').text = link
        SubElement(entry, 'link', href=link)
        if image:
            SubElement(entry, 'link', rel='enclosure', type='image/png', href=image)
        SubElement(entry, 'updated').text = iso_timestamp(event['ts'])
        SubElement(entry, 'published').text = iso_timestamp(event['ts'])
        SubElement(entry, 'category', term=event['type'])
        SubElement(entry, 'category', term=f"priority:{event['priority']}")
        content = (
            f'<p><img src="{html.escape(image, quote=True)}" alt="" width="640" height="576"></p>'
            if image else ''
        )
        content += f"<p>{html.escape(event['body'])}</p>"
        content += (
            f"<p><small>{html.escape(event['map'])} · "
            f"play time {html.escape(event['playtime'])}</small></p>"
        )
        SubElement(entry, 'content', type='html').text = content

    return tostring(feed, encoding='utf-8', xml_declaration=True)
