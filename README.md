<!-- Timestamp GIT Verification Badges -->
[![Timestamp GIT](https://timestampgit.dev/api/statusSummary/py2native/py2native)](https://timestampgit.dev/status/py2native/py2native)
[![Timestamp GIT](https://timestampgit.dev/api/statusCount/py2native/py2native)](https://timestampgit.dev/status/py2native/py2native)
[![Timestamp GIT](https://timestampgit.dev/api/statusLast/py2native/py2native)](https://timestampgit.dev/status/py2native/py2native)
[![Timestamp GIT](https://timestampgit.dev/api/statusBadge/py2native/py2native)](https://timestampgit.dev/status/py2native/py2native)

# Py2Native

A Python-to-native compiler that compiles your proprietary Python files to C via Cython,
then links them into a single native executable (or shared library). Open-source libraries
are kept as plain Python inside a managed `uv` environment — only your code is compiled.

## Product tiers

| Tier       | Package         | License    | Key differences                               |
|------------|-----------------|------------|-----------------------------------------------|
| Community  | `py2native`     | MIT        | Full compilation, `uv` embedding, cross-platform |
| Pro        | `py2nativepro`  | Proprietary| JWT license verification, string compression  |


## Usage

### Installation

````
uv add --dev py2native 
````

### Use

````
uv run py2native build --embed embed --wheel dist --base src --exe entry main *.py
````
