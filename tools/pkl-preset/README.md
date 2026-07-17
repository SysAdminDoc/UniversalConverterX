# Pkl preset compiler

This optional sidecar compiles a local [Pkl](https://pkl-lang.org/) 0.32 or
newer module into UCX preset XML. UCX does not install or download Pkl.

```powershell
$env:PKL_PATH = 'C:\Tools\pkl.exe'
python .\tools\pkl-preset\sidecar.py compile `
  --input .\my-preset.pkl `
  --output .\my-preset.preset.xml
```

The module must evaluate to one object with exactly these fields:

| Field | Type | Rule |
|---|---|---|
| `schemaVersion` | Integer | Must be `1`. |
| `name` | String | Non-blank, at most 100 characters. |
| `folder` | String | Safe relative preset folder, at most 128 characters. |
| `description` | String | Optional, at most 500 characters. |
| `inputExtensions` | List of strings | 1–100 unique extensions without paths. |
| `outputFileNameTemplate` | String | Must begin with `{dir}/`; parent traversal and backslashes are rejected. |
| `outputExtension` | String | Safe extension, at most 32 characters. |
| `engine` | String | Lowercase UCX engine identifier. |
| `invocationMode` | String | One of UCX's five supported invocation modes. |
| `args` | List of strings | At most 128 direct sidecar arguments. |

See [`sample_ucx_preset.pkl`](../../tests/fixtures/pkl/sample_ucx_preset.pkl)
for a complete example.

The wrapper invokes `pkl eval` without a shell. File-module imports are rooted
to the source directory. Only Pkl's built-in output-format property is allowed;
file, environment, HTTP, and custom resources are denied. Projects, caches,
and user settings are disabled. Source, rendered output, diagnostics, and
runtime are bounded, duplicate JSON keys and unknown fields are rejected, and
validated XML is promoted atomically.
