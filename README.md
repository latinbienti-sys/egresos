# Egresos

Panel de consulta de gastos por Razón de Pago (solo lectura). Agrupa los pagos por `x_razonpagos` para responder "¿en qué se gastó el dinero?".

Genera un archivo HTML independiente (`gastos_razon_pagos.html`). No modifica nada en Odoo.

## Garantía de solo lectura

Solo realiza lecturas vía RPC:

| Método | Uso |
|---|---|
| `fields_get` | Detecta el campo `x_razonpagos`. |
| `search_read` | Obtiene los pagos. |
| `search_count` | Cuenta registros. |
| `read` | Resuelve etiquetas de proveedores/compañías. |

Nunca llama a `create`, `write`, `unlink` ni ejecuta SQL. No instala módulos, vistas, menús o assets. Todo queda en local.

## Uso

```powershell
$env:ODOO_BASE="https://latinbien.com"
$env:ODOO_DB="erp_production"
$env:ODOO_USER="usuario"
$env:ODOO_PASSWORD="clave"

python gastos_razon_pagos.py
```

Abre `gastos_razon_pagos.html` con doble clic. Usa Python estándar; Chart.js se carga por CDN.

## Panel

- KPIs: total analizado, ticket promedio, nº de categorías, mayor gasto.
- Histórico año-mes: barras apiladas por razón de pago (un solo eje). Clic en un bloque para filtrar.
- Dona: distribución por razón. Clic para filtrar tabla e histórico.
- Desglose 3 niveles: Razón de pago → Proveedor → Documento (subtotales, %, barras). Expandible/colapsable.
- Filtros en vivo: fechas, estado (Publicado/Borrador/Todos), tipo (Salidas/Entradas/Ambos), medida (Moneda de compañía/Moneda del pago), moneda (VEF/USD), compañía, signo contable.
- Atajos: Este mes / Este año / Todo. Exportar CSV.
- Predeterminado: Publicado + Salidas, moneda de compañía (USD). Multicompañía y multimoneda.

## Pruebas

```powershell
node test_gastos_razon_pagos.js
```

61 pruebas con datos ficticios (agregación, filtros, histórico año-mes, drill-down 3 niveles, escapes). No conecta a Odoo.
