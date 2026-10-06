# Contribuir

1. Crea una rama desde `main`: `feat/...`, `fix/...` o `docs/...`.
2. `make setup` y `make dev` para trabajar en local.
3. Antes de abrir el PR: `make lint`, `make test` y, si tocaste Terraform, `make tf-validate`.
4. Si cambias reglas de tags o Shadow IT, corre también `make test-integration` contra un tenant de prueba.
5. Describe en el PR **qué** cambia y **por qué**, con la medición que lo motiva cuando aplique.
6. Actualiza la documentación de `docs/` y el `CHANGELOG.md`.

Convenciones de código y recetas en [docs/development.md](docs/development.md).

**Nunca** subas `.env`, `*.tfvars`, `backend.hcl`, estados de Terraform ni exportaciones de inventario. La CI ejecuta gitleaks en cada PR.
