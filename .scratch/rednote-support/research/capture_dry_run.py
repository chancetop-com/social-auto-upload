"""Diagnostic runner for the real Rednote CLI; refuses runs without --no-publish.

Snapshots are local-only under .local/rednote-acceptance/advanced. The runner
calls the production uploader and records DOM evidence without changing actions.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

import sau_cli  # noqa: E402
from uploader.rednote_uploader import main as rednote  # noqa: E402

OUT = ROOT / ".local/rednote-acceptance/advanced"
OUT.mkdir(parents=True, exist_ok=True)

CAPTURE = r"""() => {
  const visible = n => {
    const r = n.getBoundingClientRect();
    const s = getComputedStyle(n);
    return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none';
  };
  const nodes = s => Array.from(document.querySelectorAll(s));
  const pick = n => ({tag:n.tagName, cls:n.className, text:(n.innerText || '').slice(0,1200), visible:visible(n)});
  return {
    url:location.href, language:navigator.language, languages:navigator.languages,
    timezone:Intl.DateTimeFormat().resolvedOptions().timeZone,
    modals:nodes('.d-modal,[role="dialog"],.d-dialog').filter(visible).map(n=>({...pick(n),html:n.outerHTML.slice(0,22000)})),
    title:nodes('div.d-input input').map(n=>({value:n.value,placeholder:n.placeholder})),
    body:nodes('div.tiptap[role="textbox"]').map(n=>({text:n.innerText,html:n.innerHTML})),
    topics:nodes('#creator-editor-topic-container').map(n=>({...pick(n),html:n.innerHTML.slice(0,10000)})),
    declarations:nodes('.publish-container,.declaration-drop-down').map(n=>({...pick(n),html:n.outerHTML.slice(0,10000)})),
    declarationTriggers:nodes('span,div,button').filter(n=>n.childElementCount === 0 && /添加内容类型声明|笔记含AI合成内容/.test(n.textContent)).map(n=>({text:n.textContent,html:n.parentElement.outerHTML.slice(0,7000)})),
    selects:nodes('.d-select').filter(visible).map(n=>({html:n.parentElement.outerHTML.slice(0,9000)})),
    sourceDetails:nodes('.notation').map(n=>({...pick(n),html:n.outerHTML})),
    sourceInputs:nodes('.self-shooting-contain input').map(n=>({cls:n.className,value:n.value,placeholder:n.placeholder})),
    locationSuggestions:nodes('.el-autocomplete-suggestion li').map(n=>({...pick(n),html:n.outerHTML.slice(0,4000)})),
    switches:nodes('.original-wrapper,.post-time-wrapper,.post-time-switch-container').map(n=>({...pick(n),html:n.outerHTML.slice(0,8000)})),
    schedule:nodes('.date-picker-container input,.d-datepicker-input-filter input').map(n=>({value:n.value,cls:n.className})),
    covers:nodes('.cover-plugin-preview').map(n=>({...pick(n),html:n.outerHTML.slice(0,10000)})),
    publish:nodes('xhs-publish-btn').map(n=>({text:n.innerText,isPublish:n.getAttribute('is-publish'),disabled:n.getAttribute('submit-disabled')}))
  };
}"""


async def capture(page, label):
    try:
        data = await page.evaluate(CAPTURE)
        (OUT / f"{label}.json").write_text(
            json.dumps(data, ensure_ascii=False, indent=2)
        )
        await page.screenshot(path=str(OUT / f"{label}.png"), full_page=True)
        print(
            f"[evidence] {label}: language={data['language']}, modals={len(data['modals'])}"
        )
    except Exception as exc:
        print(f"[evidence failed] {label}: {exc}")


def capture_after(cls, method, label):
    original = getattr(cls, method)

    async def wrapped(self, page, *args, **kwargs):
        try:
            return await original(self, page, *args, **kwargs)
        finally:
            await capture(page, label)

    setattr(cls, method, wrapped)


if __name__ == "__main__":
    if (
        len(sys.argv) < 3
        or sys.argv[1] != "rednote"
        or sys.argv[2] not in {"upload-video", "upload-note"}
        or "--no-publish" not in sys.argv
    ):
        raise SystemExit(
            "Only rednote upload-video/upload-note --no-publish is allowed"
        )
    resolve_anchor = rednote._resolve_anchor

    async def capture_cover_modal(page, what, *args, **kwargs):
        resolved = await resolve_anchor(page, what, *args, **kwargs)
        if what == "封面弹窗":
            await capture(page, "cover-modal")
        elif what == "原创声明弹窗":
            await capture(page, "original-modal")
        return resolved

    rednote._resolve_anchor = capture_cover_modal
    capture_after(rednote.RednoteBaseUploader, "fill_meta", "metadata")
    capture_after(
        rednote.RednoteBaseUploader,
        "_open_content_declaration_menu",
        "declaration-menu",
    )
    capture_after(rednote.RednoteBaseUploader, "apply_declarations", "declarations")
    capture_after(rednote.RednoteVideo, "set_thumbnail", "cover")
    capture_after(rednote.RednoteVideo, "upload_video_content", "video-final")
    capture_after(rednote.RednoteNote, "upload_note_content", "note-final")
    raise SystemExit(sau_cli.main(sys.argv[1:]))
