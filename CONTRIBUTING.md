# Contributing

Thanks for considering a contribution. Chinese speakers: feel free to open issues in Chinese — I read both.

## Quick rules

- **Discuss before big changes.** Open an issue first for anything architectural. Saves you from building something I'd reject.
- **Keep the dependency count.** We're at 3 pip packages (`Flask`, `ruamel.yaml`, `requests`) and zero npm packages. New dependencies need a strong argument.
- **No frontend build step.** Plain JS + hand-drawn Canvas is a deliberate choice. Don't introduce React/Vite/webpack.
- **Standard library for alerts.** All 12 notification channels use stdlib only. New channels should too.
- **Never break read-only mode.** `DASH_READ_ONLY=1` must stay airtight.

## Dev setup

```bash
git clone https://github.com/136772/hermes-console.git
cd hermes-console
pip install -r requirements.txt

export HERMES_DIR=/tmp/hermes-fake
export DASH_AUTH=0          # skip login while developing
python app.py               # → http://localhost:8080
```

## Before you open a PR

```bash
bash -n install.sh start-dash.sh fnos-setup.sh          # shell syntax
python -m py_compile app.py auth.py hermes_ctl.py cost.py notify.py
node --check static/app.js                              # if you touched JS
python test_smoke.py                                    # 29 smoke tests
```

CI runs the same checks on every push. All must pass.

Also update `CHANGELOG.md` under `## [Unreleased]`.

## Adding a notification channel

This is the most common contribution, and it's designed to be easy:

1. In `notify.py`, add a `send_<name>(cfg, title, text)` function — stdlib only.
2. Add an entry to `SCHEMA` with its fields (`type`, `label`, `placeholder`, `secret`).
3. Done. The frontend renders the form from the schema — **no JS changes needed**.

Mask anything secret with `secret: true`. The backend preserves secrets by index on save, so masked values never overwrite real ones.

## Commit style

Short imperative subject, optional body. Examples:

```
feat: add Discord alert channel
fix: guard /proxy/* behind auth
docs: clarify docker.sock trade-off
```

## Reporting security issues

**Don't open a public issue.** Email or use GitHub's private vulnerability reporting. This project can restart containers and edit config files — a real vulnerability here matters.

## License

By contributing you agree your work is released under the MIT License.
