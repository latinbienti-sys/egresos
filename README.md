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

## Bases y favoritos de Odoo

El panel no inventa criterios: cada base reproduce el dominio de un favorito real de `account.payment`.

| Base | Favorito | Dominio |
|---|---|---|
| Clientes | `inglb` | `partner_type = customer`, `is_internal_transfer = False`, `state = posted` |
| Proveedores | `Gastoslb` (`ir.filters` 467) | `partner_type = supplier`, `is_internal_transfer = False`, `state = posted` |
| Flujo de pagos | — | `payment_type` (sí distingue entrada de salida) |

El selector **Tipo** fija la base: Salidas → Proveedores (Gastoslb), Entradas → Clientes (inglb), Ambos → Flujo de pagos. Por eso Salidas **no** se miden con `payment_type`: el dominio de Gastoslb se apoya en `partner_type = supplier`.

Los dos favoritos excluyen transferencias internas y los pagos que no están en estado `posted`, por eso el panel arranca en Publicado.

## Panel

- KPIs: total analizado, ticket promedio, nº de categorías, mayor gasto.
- Ingresos de clientes: ventas + anticipos − descuentos = ingreso neto.
- Cierre por año y mes: tabla agrupada por año / mes con subtotal por año y total general, igual que el agrupamiento `x_fecha_de_publicacion:year` / `:month` de los favoritos en Odoo. Los pagos sin fecha se listan aparte al final.
- Histórico año-mes: barras apiladas por razón de pago (un solo eje). Clic en un bloque para filtrar.
- Dona: distribución por razón. Clic para filtrar tabla e histórico.
- Desglose 3 niveles: Razón de pago → Proveedor → Documento (subtotales, %, barras). Expandible/colapsable.
- Filtros en vivo: fechas, estado (Publicado/Borrador/Todos), tipo (Salidas/Entradas/Ambos), base (Clientes/Proveedores/Flujo de pagos), casilla de pagos sin fecha, fecha usada (Publicación/Pago), medida (Moneda de compañía/Moneda del pago), moneda (VEF/USD), compañía, signo contable.
- Atajos: Este mes / Este año / Todo. Exportar CSV.
- Predeterminado: Publicado + Clientes, moneda de compañía (USD). Multicompañía y multimoneda.

## Ingresos de clientes (favorito "inglb")

Replica el criterio del favorito **inglb** de *Pagos* en Odoo:

- **Base**: `partner_type = 'customer'` y `is_internal_transfer = False`, no `payment_type`.
- **Fecha**: `x_fecha_de_publicacion`, no `date` ni `create_date`.
- **Medida**: `amount_company_currency_signed`.

El ingreso se descompone así:

```
Ingreso neto = Ingresos por ventas + Anticipos de clientes - Descuentos y devoluciones
```

Los descuentos (`DESCUENTOSDFC`, `PROMODESCUENTOS`, `DEVOLUCIONES`) llegan **positivos** en
`amount_company_currency_signed`, así que el panel fuerza el negativo; una devolución ya
negativa en origen no se resta dos veces.

Referencia: octubre 2026 → ventas 10,644.56 + anticipos 3,162.08 − descuentos 66.26 = **13,740.38** (355 pagos).

En la base de clientes no existe `DEVOLUCIONES`; esa razón solo aparece con `payment_type = 'inbound'`.
Los pagos sin fecha de publicación quedan fuera de cualquier corte con rango de fechas.

El selector **Base** permite volver al criterio anterior por `payment_type` y **Usar fecha** a `date`.

## Pruebas

```powershell
node test_gastos_razon_pagos.js
node test_ingresos_clientes.js
```

99 pruebas (61 de agregación, filtros, histórico año-mes, drill-down de 3 niveles y escapes;
38 de la base de ingresos de clientes contra los datos reales). No conectan a Odoo.
