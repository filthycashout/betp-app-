"""Configurable policy-aware HTML spiders for research evidence collection."""
from .spec import FieldSpec, SpiderSpec
from .engine import CrawlStats, SpiderRunner

__all__ = ["FieldSpec", "SpiderSpec", "CrawlStats", "SpiderRunner"]
