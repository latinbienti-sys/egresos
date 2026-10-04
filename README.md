# Gastos por Razón de Pago — panel de consulta (solo lectura)

Responde **"¿en qué se gastó el dinero?"** agrupando los pagos por el campo
`x_razonpagos` (la razón / clasificación del gasto), en vez de por la jerarquía
Año → Mes → Día.

Genera un **HTML independiente** en tu escritorio. **No modifica nada en Odoo.**

## Garantía de solo lectura

El script solo hace tres llamadas RPC de lectura:

| Método          | Para qué                              |
| --------------- | ------------------------------------- |
| `fields_get`    | descubrir el campo `x_razonpagos`     |
| `search_read`   | traer los pagos                       |
| `search_count`  | contar registros                      |
| `read`          | resolver etiquetas de proveedores    |

Nunca llama a `create`, `write`, `unlink`, ni ejecuta SQL. No instala módulos,
vistas, menús ni assets. El HTML se genera en tu carpeta local.

## Uso

```powershell
$env:ODOO_BASE="https://tu-odoo.com"
$env:ODOO_DB="basededatos"
$env:ODOO_USER="usuario"
$env:ODOO_PASSWORD="clave"

python gastos_razon_pagos.py
```

Abre `gastos_razon_pagos.html` con doble clic. Se genera **sin dependencias**:
solo la biblioteca estándar de Python (Chart.js se carga por CDN).

### Variables de entorno opcionales

| Variable             | Default            | Para qué                             |
| -------------------- | ------------------ | ------------------------------------ |
| `GASTOS_MODEL`       | `account.payment`  | modelo a consultar                   |
| `GASTOS_REASON_FIELD`| `x_razonpagos`     | campo por el que se agrupa          |
| `GASTOS_LIMIT`       | `20000`            | tope de registros que se descargan  |

El script **detecta solo** los campos reales (`amount`, `payment_date`, `state`,
`payment_type`, `partner_id`) y si `x_razonpagos` es selección o relación, así
que no hay que hardcodear la estructura. Si el campo no existe, lo dice y lista
los `x_` disponibles.

## Qué trae el panel

- **4 KPIs**: total analizado, ticket promedio, nº de categorías, mayor gasto.
- **Dona** con % por categoría; clic en una porción filtra la tabla.
- **Desglose en 3 niveles**: Razón de pago → Proveedor → Documento, con
  subtotales, % y barras. Se expande y colapsa.
- **Filtros en vivo**: rango de fechas, estado (Publicado / Borrador / Todos) y
  tipo de pago (Salidas / Entradas / Ambos). Todo se recalcula en el navegador,
  sin volver a consultar Odoo.
- **Atajos**: Este mes / Este año / Todo.
- **Exportar CSV** de lo que se está viendo.

Por defecto arranca en **Publicado + Salidas**, que es el corte de egreso real.

## Pruebas

```powershell
node test_gastos_razon_pagos.js
```

20 aserciones sobre datos ficticios: agregación, filtros, drill-down de tres
niveles y limpieza de estado al cambiar filtros. **No se conecta a Odoo.**