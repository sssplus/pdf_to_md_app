# Contributing to Doc2MD

Thanks for your interest in improving Doc2MD! This guide covers how to get set
up and what we expect from contributions.

## Development setup

See the [README](README.md#getting-started) for full setup instructions. In
short:

```bash
# Backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python main.py

# Frontend (in a second terminal)
npm install
cp .env.example .env
npm run dev
```

## Before opening a pull request

- **Lint the frontend:** `npm run lint` should pass with no errors.
- **Build the frontend:** `npm run build` should succeed.
- Keep changes focused — one logical change per pull request.
- Update the README or other docs if your change affects usage or configuration.

## Reporting bugs

Open an issue with:

- What you expected to happen and what actually happened
- Steps to reproduce (a sample document helps, if you can share one)
- Your OS, Node version, and Python version

## Code style

- Frontend: follow the existing ESLint configuration and React conventions.
- Backend: keep it PEP 8-friendly; prefer clear, small functions.

## License

By contributing, you agree that your contributions will be licensed under the
[GNU General Public License v3.0](LICENSE).
