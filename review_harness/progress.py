"""A live progress comment on the PR while a reviewer or the author works.

One comment per run, created at the start and edited as steps arrive (at most every 15 s), then finished with the
outcome and the full step list folded. Configured from the environment the workflow sets: GITHUB_TOKEN (or
PROGRESS_TOKEN_FILE), GITHUB_REPOSITORY, PROGRESS_PR and RUN_URL. Without them (tests, local runs) it does nothing.
Failures to post are ignored: progress is cosmetic and must never break a review.
"""

import os
import time

import requests

SHOW_LAST = 12
MIN_INTERVAL = 15.0


def take_token(environ) -> str | None:
    """Read the token the workflow left in PROGRESS_TOKEN_FILE, then delete the file. Done before any reviewer starts,
    so the token is never in the reviewer's (or any parent process's) environment or on disk while it runs."""
    path = environ.get("PROGRESS_TOKEN_FILE")
    if not path:
        return None
    try:
        with open(path) as fh:
            token = fh.read().strip()
        os.remove(path)
        return token or None
    except OSError:
        return None


class Progress:
    def __init__(self, title: str, environ=os.environ, session=None, clock=time.monotonic):
        self.title, self.steps, self.comment_id = title, [], None
        self.token, self.repo = environ.get("GITHUB_TOKEN") or take_token(environ), environ.get("GITHUB_REPOSITORY")
        self.pr, self.run_url = environ.get("PROGRESS_PR"), environ.get("RUN_URL", "")
        self.enabled = bool(self.token and self.repo and self.pr)
        self.session, self.clock, self.last_push, self.started = session or requests.Session(), clock, 0.0, clock()

    def _call(self, method: str, url: str, body: str):
        try:
            r = self.session.request(method, url, json={"body": body}, timeout=20,
                                     headers={"Authorization": f"Bearer {self.token}",
                                              "Accept": "application/vnd.github+json"})
            return r.json() if r.status_code < 300 else None
        except Exception:  # noqa: BLE001
            return None

    def _push(self, body: str):
        if not self.enabled:
            return
        base = f"https://api.github.com/repos/{self.repo}/issues"
        if self.comment_id is None:
            out = self._call("POST", f"{base}/{self.pr}/comments", body)
            self.comment_id = (out or {}).get("id")
        else:
            self._call("PATCH", f"{base}/comments/{self.comment_id}", body)
        self.last_push = self.clock()

    def _elapsed(self) -> str:
        m, s = divmod(int(self.clock() - self.started), 60)
        return f"{m} min {s:02d} s" if m else f"{s} s"

    def render(self, status: str, done: bool = False) -> str:
        link = f" · [run]({self.run_url})" if self.run_url else ""
        head = f"{status} **{self.title}** · {len(self.steps)} steps · {self._elapsed()}{link}\n\n"
        if done:
            if not self.steps:
                return head
            return head + "<details><summary>All steps</summary>\n\n" + "\n".join(
                f"{k}. {s}" for k, s in enumerate(self.steps, 1)) + "\n</details>\n"
        shown = self.steps[-SHOW_LAST:]
        first = len(self.steps) - len(shown) + 1
        more = f"_… {first - 1} earlier steps_\n" if first > 1 else ""
        return head + more + "\n".join(f"{first + k}. {s}" for k, s in enumerate(shown)) + "\n"

    def start(self):
        self._push(self.render("⏳"))

    def step(self, text: str):
        self.steps.append(text)
        if self.clock() - self.last_push >= MIN_INTERVAL:
            self._push(self.render("⏳"))

    def finish(self, ok: bool, note: str = ""):
        status = "✅" if ok else "❌"
        body = self.render(status, done=True)
        self._push(body.replace(f"**{self.title}**", f"**{self.title}** — {note}" if note else f"**{self.title}**", 1))
