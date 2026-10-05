from app import app

# Deployment entrypoint for the legacy runtime plus the unified evidence layer.
# A project-specific module name avoids collisions with generic `main` modules in
# test runners and deployment environments.
# Evidence is registered once in app.py so both deployment paths behave alike.
