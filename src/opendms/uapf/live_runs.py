"""In-memory live-run buffer for streaming UAPF process audit events to the UI.

The uapf-engine posts audit CloudEvents to /uapf/host/audit while a session
runs. Those events are tagged with `uapfsessionid` but NOT the host-supplied
correlationId, so we buffer events per sessionId and maintain a
correlationId -> sessionId map.

The host calls register_pending(correlationId, packageId) just before it
invokes the engine's start-session; the engine's first event for that run
(dev.uapf.session.created) lets bind_session() attach the freshly-created
sessionId to the oldest matching pending correlationId.

The frontend polls GET /api/uapf/live-run/{correlation_id}; get() resolves
the correlationId to its sessionId transparently (and also accepts a raw
sessionId, for backward compatibility).
"""
from collections import OrderedDict
import time
from typing import Any, Dict, List, Optional

_MAX_RUNS = 100      # distinct sessions retained (oldest evicted)
_MAX_EVENTS = 400    # events retained per run
_PENDING_TTL = 180   # seconds a pending correlationId waits for its session

_runs: "OrderedDict[str, List[Dict[str, Any]]]" = OrderedDict()   # session_id -> events
_corr_to_session: "OrderedDict[str, str]" = OrderedDict()          # correlation_id -> session_id
_pending: List[tuple] = []                                         # (correlation_id, package_id, ts)


def register_pending(correlation_id: str, package_id: str = "") -> None:
    """Remember a correlationId that is about to produce an engine session."""
    if not correlation_id:
        return
    now = time.time()
    _pending.append((str(correlation_id), package_id or "", now))
    cutoff = now - _PENDING_TTL
    _pending[:] = [p for p in _pending if p[2] > cutoff][-50:]


def bind_session(session_id: str, package_id: str = "") -> Optional[str]:
    """On a session.created event, bind the oldest pending correlationId for
    this package to the new sessionId. Returns the correlationId bound."""
    if not session_id:
        return None
    for i, (cid, pkg, _ts) in enumerate(_pending):
        if not package_id or not pkg or pkg == package_id:
            _corr_to_session[str(cid)] = str(session_id)
            while len(_corr_to_session) > _MAX_RUNS:
                _corr_to_session.popitem(last=False)
            _pending.pop(i)
            return cid
    return None


def push(key: str, event: Dict[str, Any]) -> None:
    """Append one audit event to the run identified by key (a sessionId)."""
    if not key:
        return
    k = str(key)
    lst = _runs.get(k)
    if lst is None:
        lst = []
        _runs[k] = lst
        while len(_runs) > _MAX_RUNS:
            _runs.popitem(last=False)
    lst.append(event)
    if len(lst) > _MAX_EVENTS:
        del lst[: len(lst) - _MAX_EVENTS]
    _runs.move_to_end(k)


def get(correlation_id: str, since: int = 0) -> Dict[str, Any]:
    """Return events for a run after index `since`. Resolves a correlationId
    to its sessionId; also accepts a sessionId directly."""
    cid = str(correlation_id or "")
    sid = _corr_to_session.get(cid, cid)
    lst = _runs.get(sid) or _runs.get(cid) or []
    since = max(0, int(since or 0))
    new = lst[since:]
    return {
        "correlationId": cid,
        "since": since,
        "next": since + len(new),
        "total": len(lst),
        "events": new,
    }
