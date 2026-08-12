# Module template

Copy this directory, rename three things, write your tool. That is the whole
process. A module is a separate program that speaks MCP over stdin and stdout,
so it can be written in any language; this template is the Python version, built
on the official MCP SDK.

## The three steps

1. **Copy and rename.** Pick a name matching `^[a-z][a-z0-9_-]{0,63}$`.

   ```
   cp -r template modules/weather
   cd modules/weather
   git mv src/vahub_mod_example src/vahub_mod_weather
   ```

   Then edit the name in three files: `pyproject.toml` (`project.name` and
   `tool.hatch.build.targets.wheel.packages`), `module.yaml` (`name` and the
   module named in `runtime.command`), and `src/vahub_mod_weather/server.py`
   (the string passed to `FastMCP`).

2. **Write the tool.** Replace `reverse` with what your module actually does.
   Keep the logic in a plain function and let the decorated tool be a thin
   wrapper, so your tests do not depend on the MCP SDK. Keep `__health`: the hub
   calls it on a timer, and it is how a broken backend shows up as degraded on
   the status page instead of as a mysteriously silent assistant.

3. **Declare yourself in `module.yaml`.** Every config key you read must be
   listed under `config`, or it will not be in your environment. Every tool goes
   under `tools` with a class: `read` for anything that only looks, `write` for
   anything that changes something, `destructive` for anything a person would
   want to be asked about first. Anything secret goes in `audit.redact`.

## Try it

```
python -m venv .venv
.venv/bin/pip install -e ".[dev]"
.venv/bin/python -m pytest
```

Install it into a hub straight from the working copy, no tagging or publishing
involved:

```
vahub module add --source ./modules/weather
vahub module list
```

Then add a rule to `vahub.yaml`, because with `policy.default: deny` a tool
nobody mentioned cannot be called:

```yaml
policy:
  default: deny
  rules:
    "example.reverse":
      class: read
      constraints:
        text:
          max_len: 200
```

Note that every argument needs a constraint entry. The gate rejects arguments it
was not told about, so a rule with no `constraints` block permits only calls with
no arguments.

## Things worth knowing before you write the real thing

* **Your environment is not the hub's environment.** Only the keys you declared
  are passed in, which is why a token belonging to one module is not readable by
  another. Read them with `os.environ.get` and give them sane defaults.
* **Never raise where you can report.** A probe returns `{"ok": false, ...}`; a
  tool returns an error field. Exceptions become errors the user hears.
* **Do not trust the backend's shape.** Guard `isinstance` before indexing a
  parsed response. The homeassistant and transit modules in this repository both
  do this, and their tests cover it.
* **Bound your output.** The hub truncates a tool result to a byte budget, and
  truncated JSON is worse than a short list. Cap it yourself.
* **Write tool docstrings for the model.** The first line is how it chooses, and
  the argument lines are how it fills them in. An honest, boring description
  performs better than a generous one.
* **One in-flight call per module.** The hub serializes calls to a module and
  applies a timeout. A tool that blocks for a minute blocks everything else that
  module offers, so keep your own timeouts short.

## Publishing

Nothing forces you to publish here. A module can live in any git repository and
be installed with a pinned source:

```
vahub module add --source git+https://example.com/my-modules.git@v1.0.0#subdir=modules/weather
```

If you would like it listed in the catalogue so `vahub module add weather` works
for everyone, see [CONTRIBUTING.md](../CONTRIBUTING.md).
