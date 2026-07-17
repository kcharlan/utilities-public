# plugin-advanced

Small runnable plugin benchmark that demonstrates the Python escape hatch.

Run it with:

```bash
./bench run examples/plugin-advanced -m demo-model
```

Use this shape when linear shell hooks stop being enough and you need custom orchestration or richer post-processing.

Plugin runs also get runtime timing capture for the `prepare`, `execute`, `judge`, and `summarize` phases, even if the plugin does not emit any usage metrics of its own.
