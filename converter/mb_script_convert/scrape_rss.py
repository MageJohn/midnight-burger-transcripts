import logging
from dataclasses import fields
from datetime import datetime
from time import struct_time
from urllib.parse import urlparse

import feedparser
from rapidfuzz import fuzz

from .feeds_cache import cache
from .transcript import Transcript

logger = logging.getLogger(__name__)


def scrape_episode_metadata(transcript: Transcript, url_file_stream_or_string):
    ep_title = transcript.metadata.episode_title
    assert (
        ep_title is not None
    ), "Cannot scrape episode metadata when episode title is not set"

    feed = _get_feed(url_file_stream_or_string)
    if feed is None:
        return

    episode = _match_episode(ep_title, feed)
    if episode is None:
        return

    m = transcript.metadata
    m.date_published = _date_to_iso(episode.get("published_parsed"))
    m.season = episode.get("itunes_season")
    m.season_episode_number = episode.get("itunes_episode")
    m.cover_url = getattr(episode.get("image"), "href", None)

    for field in fields(m):
        name, value = field.name, getattr(m, field.name)
        if value is None:
            logger.warning(f"Could not find a value for {name}")


def _get_feed(url_file_stream_or_string):
    looks_like_url = isinstance(url_file_stream_or_string, str) and urlparse(
        url_file_stream_or_string
    )[0] in ("http", "https")
    if not looks_like_url:
        return feedparser.parse(url_file_stream_or_string)
    url: str = url_file_stream_or_string

    if url not in cache:
        cache[url] = feedparser.parse(url)
        match cache[url].status:
            case 200 | 302:
                # all good
                pass
            case 301:
                logger.warning(
                    f"HTTP response 301: {url} has permanently moved to {cache[url].href}"
                )
            case _:
                logger.warning(
                    f"Something went wrong fetching {url} (status {cache[url].status}). Cannot scrape metadata"
                )
                return
    else:
        cached_feed = cache[url]
        new_feed = feedparser.parse(
            url, etag=cached_feed.get("etag"), modified=cached_feed.get("modified")
        )
        match new_feed.status:
            case 200 | 302:
                cache[url] = new_feed
            case 304:
                # the feed has not been modified
                pass
            case 301:
                logger.warning(
                    f"HTTP response 301: {url} has permanently moved to {new_feed.href}"
                )
                cache[url] = new_feed
            case _:
                logger.warning(
                    f"Something went wrong fetching {url} (status {new_feed.status}). Using cached feed."
                )

    return cache[url]


def _match_episode(ep_title: str, feed):
    most_similar = (0, "")
    for entry in feed.entries:
        ratio = fuzz.partial_ratio(ep_title, entry.title)
        if ratio > most_similar[0]:
            most_similar = (ratio, entry.title)
        if ratio >= 85:
            logger.info(f"Matched episode '{entry.title}' in RSS feed")
            return entry
    logger.warning(f"Could not find entry matching '{ep_title}'")
    logger.warning(
        f"The most similar title is {most_similar[1]} (similarity {most_similar[0]})"
    )
    logger.warning("Set the correct title with the --episode-title flag")


def _date_to_iso(date: struct_time):
    return datetime(
        date.tm_year,
        date.tm_mon,
        date.tm_mday,
        date.tm_hour,
        date.tm_min,
        date.tm_sec,
    ).isoformat()
