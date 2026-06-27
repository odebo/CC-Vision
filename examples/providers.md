# Provider Configuration Examples

Each example shows the env vars to export. Pick one provider, paste into `~/.zshrc` (or `~/.bashrc`), `source` it, then run `install.sh`.

## OpenAI

```bash
export VISION_PROVIDER=openai
export VISION_API_KEY=sk-proj-...
# Default model: gpt-4o
# Cheaper: export VISION_MODEL=gpt-4o-mini
```

## Alibaba DashScope (Qwen-VL)

```bash
export VISION_PROVIDER=dashscope
export VISION_API_KEY=sk-...
# Default model: qwen-vl-max
# Alternative: export VISION_MODEL=qwen3-vl-plus
```

## Zhipu BigModel (GLM-4V)

```bash
export VISION_PROVIDER=zhipu
export VISION_API_KEY=...
# Default model: glm-4v-plus
```

## SiliconFlow

```bash
export VISION_PROVIDER=siliconflow
export VISION_API_KEY=sk-...
# Default model: Qwen/Qwen2-VL-72B-Instruct
```

## Moonshot (Kimi)

```bash
export VISION_PROVIDER=moonshot
export VISION_API_KEY=sk-...
# Default model: moonshot-v1-8k-vision-preview
```

## Custom OpenAI-compatible endpoint

```bash
export VISION_API_BASE=https://your-gateway.com/v1/chat/completions
export VISION_API_KEY=...
export VISION_MODEL=your-vision-model
```

## Internal gateway with extra routing header

If your gateway routes by a custom header (multi-tenant, provider selection, etc.):

```bash
export VISION_API_BASE=https://internal-gateway/v1/chat/completions
export VISION_API_KEY=...
export VISION_MODEL=qwen3-vl-plus
export VISION_EXTRA_HEADERS='{"X-Model-Provider-Id": "tongyi"}'
```

`VISION_EXTRA_HEADERS` is a JSON object; all key-value pairs become HTTP headers on the multimodal API call.
