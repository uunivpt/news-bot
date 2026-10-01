import sqlite3
from pathlib import Path

from app.advanced_system import (
    ensure_schema, score_story, select_layout, similarity, attach_event,
    publish_lock, is_published, mark_published, source_reliability
)

class DB:
    _postgres=False
    def __init__(self):
        self.conn=sqlite3.connect(":memory:")
        self.conn.row_factory=sqlite3.Row

def test_layout_selector_is_64_and_deterministic():
    a=select_layout("politics","Government announces new policy",101,False,True)
    b=select_layout("politics","Government announces new policy",101,False,True)
    assert a==b
    assert 0 <= a["variant"] < 64
    assert a["family"] in {"editorial","split","quote","minimal","dark"}

def test_similarity_and_scoring():
    assert similarity("India announces new policy","India announces new policy") == 1.0
    db=DB(); ensure_schema(db)
    row={"id":1,"title":"Breaking government policy update","summary":"Major update","category":"politics","created_at":"2026-10-01T00:00:00+00:00"}
    result=score_story(db,row,source_count=3,verification="CONFIRMED",duplicate_risk=0)
    assert 0 <= result["score"] <= 100
    assert result["coverage"] == 84

def test_event_and_zero_duplicate_lock():
    db=DB(); ensure_schema(db)
    eid=attach_event(db,1,"Government announces new policy","politics","Source A")
    assert eid
    assert publish_lock(db,1,"story-key-1") is True
    assert publish_lock(db,2,"story-key-1") is False
    assert is_published(db,1,"instagram") is False
    mark_published(db,1,"instagram","https://example.test/reel.mp4")
    assert is_published(db,1,"instagram") is True

def test_source_reliability_metrics():
    db=DB(); ensure_schema(db)
    from app.advanced_system import record_source
    record_source(db,"Source A",success=True,coverage=True)
    record_source(db,"Source A",success=False,broken=True,coverage=False)
    r=source_reliability(db,"Source A")
    assert r["success_rate"] == 50.0
    assert r["broken_links"] == 1


def test_historical_analytics_has_real_buckets():
    from app.advanced_system import historical_analytics, record_preview, alert
    db=DB(); ensure_schema(db)
    alert(db,"WARNING","test","step",1,"example")
    result=historical_analytics(db,30)
    assert result["counts"]["alerts"] == 1
    assert isinstance(result["day"], dict)
    assert sum(result["day"].values()) >= 1
