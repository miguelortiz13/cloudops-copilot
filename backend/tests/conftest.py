"""
Aislamiento de las pruebas unitarias.

Las pruebas no deben depender del `backend/.env` de quien las ejecuta ni tocar
Azure. Este archivo se carga antes que cualquier modulo de `app`, asi que fija
aqui la configuracion que las pruebas asumen:

- `CLOUDOPS_SKIP_DOTENV` impide que `app.core.config` lea el `.env` local.
- El esquema de tags es el que usan los fixtures; las pruebas lo declaran en
  vez de heredar el valor por defecto, que puede cambiar.
- Sin credenciales de Azure ni base de datos en el entorno.
"""

import os

os.environ["CLOUDOPS_SKIP_DOTENV"] = "1"
os.environ["MANDATORY_TAGS"] = "Customer,Tenant,Platform,Product,Suite,Environment"
os.environ["SHOWBACK_TAGS"] = "Customer,Product,Suite,Environment"
os.environ.setdefault("MICROSOFT_APP_ID", "00000000-0000-0000-0000-000000000001")
for _var in ("AZURE_CLIENT_SECRET", "AZURE_READER_CLIENT_SECRET", "TFSTATE_ACCOUNT", "DATA_DIR",
             "DATABASE_URL", "DB_SERVER", "DB_NAME"):
    os.environ.pop(_var, None)
