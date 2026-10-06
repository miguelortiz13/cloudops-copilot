# 0001 · Identidad de solo lectura; remediación como código

**Estado:** aceptada

## Contexto

La plataforma ve todo el tenant y propone cambios (eliminar huérfanos, cerrar puertos, importar a Terraform). Darle permisos de escritura permitiría remediar con un clic, pero convertiría una herramienta de observación en un punto único de compromiso: quien controle el API controlaría la nube.

## Decisión

La identidad de la plataforma tiene rol `Reader`. Ningún endpoint modifica recursos de Azure. Las remediaciones se entregan como código (HCL con `import {}`) o comandos (`az`, `kubectl`) para que una persona los revise y los aplique por el camino habitual (PR, pipeline).

La única excepción es el agente SRE de Kubernetes, que ejecuta `kubectl` de lectura vía AKS Run Command, con comandos construidos por el servicio y entradas validadas.

## Consecuencias

- Comprometer el API expone información, no permite cambiar la infraestructura.
- La remediación es más lenta que un botón, pero queda trazada en el flujo de cambios del equipo.
- La remediación asistida futura (abrir un PR) mantiene la decisión: escribe en un repositorio, no en Azure.
