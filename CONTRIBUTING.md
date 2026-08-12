# Contributing a module

You do not need this repository to publish a module. Any git repository works:

```
vahub module add --source git+https://example.com/my-modules.git@v1.0.0#subdir=modules/weather
```

Adding your module here only means people can install it by name. If that is
what you want, here is how.

## Steps

1. **Fork this repository** and create a branch.

2. **Add `modules/<name>/`.** Start from [template/](template). The directory
   name, the `name` in `module.yaml`, and the name in the registry entry must
   all be the same string, matching `^[a-z][a-z0-9_-]{0,63}$`. The directory
   holds its own `pyproject.toml`, its own dependencies, a `module.yaml`, a
   `README.md` and tests. It does not share code with any other module.

3. **Write the README.** What the module does, a table of its tools with their
   classes, a table of its config keys, and a policy block that a reader can
   paste into `vahub.yaml` and edit. Say what the module cannot do, too.

4. **Tag the version.** Tags are of the form `modules/<name>/v<version>`, and the
   version must match `version` in both `module.yaml` and `pyproject.toml`:

   ```
   git tag modules/weather/v0.1.0
   git push origin modules/weather/v0.1.0
   ```

   A tag is immutable once it is in the index. To fix a mistake, publish a new
   version. Do not move a tag: somebody's install is pinned to it.

5. **Add the registry entry** to `registry.json`, with `description`, `tags`,
   `latest`, and a `versions` map whose source points at your tag:

   ```json
   "weather": {
     "description": "Local forecast from a public weather API",
     "homepage": "https://github.com/LynnDelpy/vahub-modules/tree/main/modules/weather",
     "tags": ["weather"],
     "latest": "0.1.0",
     "versions": {
       "0.1.0": {
         "source": {
           "type": "git",
           "url": "https://github.com/LynnDelpy/vahub-modules",
           "rev": "modules/weather/v0.1.0",
           "subdir": "modules/weather"
         },
         "requires_config": ["WEATHER_API_KEY"],
         "optional_config": ["WEATHER_UNITS"],
         "requires_vahub": "0.1.0"
       }
     }
   }
   ```

   If your module lives in your own repository, use your own `url` and leave
   `subdir` matching your layout. The index is happy to point elsewhere.

6. **Open the pull request.** CI lints the module, installs it into a fresh
   virtualenv, runs its tests, starts it over stdio, and validates every
   `module.yaml` and `registry.json` against the hub's own models.

## What the review looks at

The review is not a security audit and cannot be one. It checks the things that
can be checked by reading:

* **No obfuscated code.** No `exec` of decoded blobs, no minified or generated
  source without the generator, no downloading code at runtime. If a reviewer
  cannot tell what the module does by reading it, it does not go in the index.
* **Pinned dependencies.** Every dependency needs an upper bound, no VCS or URL
  dependencies, and no dependency added for something the standard library
  already does. A module's dependency tree is code that runs on someone's home
  server.
* **Declared config.** Every key the module reads appears under `config` in the
  manifest. Every secret appears under `audit.redact`. A module that reads an
  undeclared variable will simply not receive it, which is the design, but an
  undeclared read is a bug worth catching in review.
* **Honest tool descriptions and classes.** The docstring is what the language
  model reads when choosing a tool, so it must describe what the tool does and
  not oversell it. Anything that changes state is at least `write`. Anything
  that unlocks, deletes, sends money or opens something is `destructive`. A
  module that labels a destructive action `read` will be rejected.
* **Narrow tools.** A tool that forwards an arbitrary command, service call, URL
  or query to a backend defeats the policy gate, which authorizes by tool name
  and argument values. Split it into named tools.
* **A working `__health`.** It returns `{ok, backend, latency_ms, detail}`, it
  reports failures instead of raising, and it does not have side effects. A
  health probe that sends a notification or unlocks something is a bug that only
  shows up at three in the morning.
* **No surprise network destinations.** A weather module talks to a weather API.
  Anything phoning somewhere else, including analytics, will be rejected.
* **A README and tests.** The tests do not need to cover the network. They
  should cover the parsing, the argument handling, and whatever your module does
  when the backend returns something unexpected.

## Updating a module you already published

Bump the version in `module.yaml` and `pyproject.toml`, tag
`modules/<name>/v<new>`, then add the new version to the `versions` map and move
`latest` to it. Leave the old versions in place. Somebody is pinned to one of
them, and removing it breaks their next reinstall.

## Reporting a problem in a listed module

Open an issue. If it is a security problem, say so in the title and do not
include a working exploit in the description. A module found to be malicious is
removed from the index immediately; note that this does not uninstall it from
anyone's machine, which is why the review criteria above exist.
