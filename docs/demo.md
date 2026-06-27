# Demo

> 📹 A real terminal-recorded GIF would go at `docs/demo.gif` (referenced from the README). PRs welcome — see [Recording a demo](#recording-a-demo) below.

## Before / After

**Before** — non-multimodal main model (e.g. GLM-5.2), no hook installed:

```
You: [pastes screenshot] what's wrong with this code?
AI: I see you've shared an image, but I'm not able to view images directly.
    Could you describe what's in the screenshot or paste the code as text?
```

**After** — same main model, CC-Vision hook installed:

```
You: [pastes screenshot] what's wrong with this code?
[status] 解析图片中...
AI: Looking at the screenshot, the error is on line 42 — `foo` is undefined.
    You imported `fool` but called `foo`. Fix: change `foo()` to `fool()`,
    or update the import.
```

The AI never saw pixels. It saw something like this in its context:

```
<image_vision>
以下是对本次提交中附带图片的自动解析（由 qwen3-vl-plus 生成），
主力模型可据此理解图片内容：

[图片 /Users/.../image-cache/abc/1.png]
这是一张代码编辑器截图。可见以下代码（Python）：
```python
import fool

def main():
    foo()  # line 42
```
错误：第 42 行调用 `foo()`，但只导入了 `fool`。
</image_vision>
```

## Recording a demo

If you want to contribute a real GIF:

1. Use [asciinema](https://asciinema.org/) or [vhs](https://github.com/charmbracelet/vhs) to record a terminal session
2. Show: paste a screenshot into Claude Code → "解析图片中..." status → AI answers based on the image
3. Save as `docs/demo.gif`
4. Reference it from `README.md` (both EN and zh-CN)
5. Open a PR

Keep the GIF under 5 MB. Trim the API latency pause if it's distracting.
