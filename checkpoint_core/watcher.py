"""Background autosave watcher for an active session.

Polling-based by design (reliable everywhere); native file events are used opportunistically
if `watchdog` is installed. Edits are debounced: an autosave is written only after the
working tree has been quiet for `debounce_ms`. No Git is involved, and nothing here touches
accepted history, branch heads, or the Git bridge.
"""
from __future__ import annotations

import os
import time
from typing import Any, Dict, Optional

from . import autosave
from .ignore import Ignore
from .session import Session
from .store import Repo


class Watcher:
    def __init__(self, repo: Repo, session: Session,
                 debounce_ms: Optional[int] = None,
                 poll_ms: Optional[int] = None):
        self.repo = repo
        self.session = session
        cfg = repo.config.autosave()
        self.debounce_ms = debounce_ms if debounce_ms is not None else int(cfg.get("debounce_ms", 1000))
        self.poll_ms = poll_ms if poll_ms is not None else int(cfg.get("polling_interval_ms", 2000))
        self.last_sig = self._signature()
        self.pending_since: Optional[float] = None
        self.autosaves_created = 0

    def _signature(self) -> Dict[str, Any]:
        """Cheap change-detector: path -> (mtime, size) for non-ignored files."""
        ig = Ignore.load(self.repo.root)
        sig: Dict[str, Any] = {}
        for dirpath, dirnames, filenames in os.walk(self.repo.root):
            rel_dir = os.path.relpath(dirpath, self.repo.root)
            rel_dir = "" if rel_dir == "." else rel_dir.replace(os.sep, "/")
            dirnames[:] = [d for d in dirnames
                           if not ig.ignored((rel_dir + "/" + d) if rel_dir else d)
                           and not ig.ignored(d)]
            for fn in filenames:
                rel = (rel_dir + "/" + fn) if rel_dir else fn
                if ig.ignored(rel):
                    continue
                try:
                    st = os.lstat(os.path.join(dirpath, fn))
                    sig[rel] = (int(st.st_mtime_ns), st.st_size)
                except OSError:
                    pass
        return sig

    def poll_once(self, now_ms: float) -> Optional[Dict[str, Any]]:
        """One tick. Returns an autosave record if one was created, else None.

        Pure and time-injectable so the debounce logic is unit-testable.
        """
        sig = self._signature()
        if sig != self.last_sig:
            # an edit happened: (re)start the debounce window
            self.last_sig = sig
            self.pending_since = now_ms
            return None
        if self.pending_since is not None and (now_ms - self.pending_since) >= self.debounce_ms:
            self.pending_since = None
            rec = autosave.create_autosave(self.repo, self.session, reason="edit")
            if rec:
                self.autosaves_created += 1
            return rec
        return None

    def run(self, log=lambda m: None) -> int:
        """Foreground loop until the session is no longer active or interrupted.

        Writes a final autosave on exit so the latest state is always captured.
        """
        log("watching {} (debounce {}ms, poll {}ms). Ctrl-C to stop.".format(
            self.session.id, self.debounce_ms, self.poll_ms))
        try:
            while self.repo.active_session_id() == self.session.id:
                rec = self.poll_once(time.time() * 1000.0)
                if rec:
                    log("autosave {} ({} changed)".format(
                        rec["autosave_id"], len(rec["changed_paths"])))
                time.sleep(self.poll_ms / 1000.0)
        except KeyboardInterrupt:
            log("stopping watcher...")
        finally:
            # capture whatever is on disk right now
            rec = autosave.create_autosave(self.repo, self.session, reason="watch-stop")
            if rec:
                self.autosaves_created += 1
                log("final autosave {}".format(rec["autosave_id"]))
        return self.autosaves_created
