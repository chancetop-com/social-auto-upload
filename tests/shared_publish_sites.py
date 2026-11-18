"""Offline platform endpoints for installed publishing and recovery scenarios."""
import json
import time
from pathlib import Path

from tests.test_shared_adspower_process import Handler


class InstagramSite:
    def __init__(self):
        self.submissions = []
        self.submitted_at = []

    def configure(self, submission):
        """Override to delay or change the response after a recorded dispatch."""
        return {"media": {"id": "201_42", "code": "offline-fixture", "user": {"pk": "42"},
                          "caption": {"text": submission["caption"]}}}

    def handler(self, *, block_share=False):
        html = (Path(__file__).parent / "fixtures/instagram_composer.html").read_text(encoding="utf-8")
        html = html.replace("CONFIG", json.dumps({"blockedShare": block_share})) + """
        <script>
          document.cookie = 'ds_user_id=42;path=/';
          document.addEventListener('click', event => {
            const action = event.target.closest('[data-action=advance]');
            if (action?.textContent !== 'Share') return;
            const caption = document.querySelector('[contenteditable]').innerText;
            fetch('/api/v1/media/configure/', {method: 'POST', body: JSON.stringify({caption, files})});
          });
        </script>"""
        site = self

        class Instagram(Handler):
            def do_GET(self):
                if self.path == "/":
                    self.respond(html.encode(), "text/html; charset=utf-8")
                else:
                    self.send_error(404)

            def do_POST(self):
                if self.path != "/api/v1/media/configure/":
                    return self.send_error(404)
                submission = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                site.submissions.append(submission)
                site.submitted_at.append(time.time())
                self.respond(json.dumps(site.configure(submission)).encode(), "application/json")

        return Instagram


class TikTokSite:
    def __init__(self, *, ready=True, outcome="content"):
        self.ready = ready
        self.outcome = outcome
        self.submissions = []
        self.submitted_at = []

    def handler(self):
        site = self

        class TikTok(Handler):
            def do_GET(self):
                if self.path.startswith("/tiktokstudio/upload"):
                    document = (Path(__file__).parent / "fixtures/tiktok_composer.html").read_text()
                    document = document.replace("BUTTON_STATE", "" if site.ready else "disabled")
                    self.respond(document.encode(), "text/html; charset=utf-8")
                elif self.path.startswith("/tiktokstudio/content"):
                    self.respond(b'<a href="/video/8042"></a><script>document.querySelector("a").textContent = sessionStorage.caption</script>',
                                 "text/html")
                elif self.path.startswith("/login"):
                    self.respond(b'<form action="/login"><input name="username"></form>', "text/html")
                else:
                    self.send_error(404)

            def do_POST(self):
                if self.path != "/offline-submit":
                    return self.send_error(404)
                site.submissions.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
                site.submitted_at.append(time.time())
                self.respond(site.outcome.encode(), "text/plain")

        return TikTok
