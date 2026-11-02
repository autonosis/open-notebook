"""Preserve Docling's cache choice across Transformers 4.57 model-default merging.

Observed: GenerationConfig.use_cache=True equals the global default, so
Transformers replaces it with CodeFormulaV2's model default False. Explicit
kwargs have final precedence. This changes caching, not prompts or output limits.
"""

from pathlib import Path

p = Path(
    "/app/.venv/lib/python3.12/site-packages/docling/models/inference_engines/vlm/transformers_engine.py"
)
s = p.read_text()
old = "generated_ids = self.vlm_model.generate(**gen_kwargs)"
assert s.count(old) == 1, (
    "Pinned Docling source changed; review cache fix before rebuilding"
)
p.write_text(
    s.replace(
        old,
        "generated_ids = self.vlm_model.generate(**gen_kwargs, use_cache=self.options.use_kv_cache)",
    )
)
