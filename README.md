# Manamarket — Backend (Django + DRF)

API REST para tienda especializada en cartas Magic: The Gathering. Gestiona productos, carrito, órdenes, pagos con Webpay y envíos con Chilexpress.

## Stack

- Python 3.11+ · Django 5 · Django REST Framework
- JWT (SimpleJWT) · MySQL (prod) / SQLite (dev)
- Webpay (Transbank) · Chilexpress · Scryfall API

## Apps instaladas

- `accounts` — registro, login JWT, roles (admin / worker / customer)
- `products` — catálogo MTG, singles, sellados, bundles, Kardex, órdenes de compra, Scryfall
- `cart` — carrito por usuario
- `orders` — checkout, órdenes, compras asistidas, cotización de envío
- `payments` — Webpay, reserva de stock, comprobantes
- `shipping` — integración Chilexpress (cobertura y cotización)

## Instalación local

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cd store_backend
cp .env.example .env             # editar con tus valores
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

## Variables de entorno requeridas (.env)

```env
SECRET_KEY=<clave-secreta>
DEBUG=True
ALLOWED_HOSTS=localhost,127.0.0.1

# Base de datos (dejar vacío para SQLite local)
MYSQL_NAME=
MYSQL_USER=
MYSQL_PASSWORD=
MYSQL_HOST=localhost
MYSQL_PORT=3306

# Webpay
WEBPAY_ENVIRONMENT=integration
WEBPAY_COMMERCE_CODE=597055555532
WEBPAY_API_KEY_SECRET=579B532A7440BB0C9079DED94D31EA1615BACEB56610332264630D42D0A36B1C
WEBPAY_RETURN_URL=http://localhost:5173/pago/retorno
WEBPAY_FINAL_URL=http://localhost:5173/pago/final

# Chilexpress
CHILEXPRESS_ENV=test
CHILEXPRESS_COVERAGE_KEY=<tu-key>
CHILEXPRESS_COTIZADOR_KEY=<tu-key>
CHILEXPRESS_ENVIOS_KEY=<tu-key>
CHILEXPRESS_ORIGEN_COVERAGE=STGO
CHILEXPRESS_TCC=<tu-tcc>

# Negocio
TAX_RATE=0.19
STOCK_RESERVATION_MINUTES=15
```

## Autenticación JWT

```
POST /api/accounts/register/     Registrar usuario
POST /api/accounts/login/        Obtener tokens (access + refresh)
POST /api/accounts/logout/       Invalidar refresh token
POST /api/accounts/token/refresh/ Renovar access token
GET  /api/accounts/me/           Perfil del usuario autenticado
PATCH /api/accounts/me/password/ Cambiar contraseña
```

Header requerido en requests autenticados:
```
Authorization: Bearer <access_token>
```

## Endpoints principales

### Productos
```
GET    /api/products/products/                    Catálogo (público)
GET    /api/products/products/{id}/               Detalle de producto
POST   /api/products/products/                    Crear producto (admin/worker)
PATCH  /api/products/products/{id}/               Editar producto
POST   /api/products/products/import-catalog-xlsx/ Importar catálogo Excel
GET    /api/products/categories/                  Listar categorías
GET    /api/products/kardex/                      Movimientos de inventario
GET    /api/products/inventory/dashboard/         Dashboard de inventario
GET    /api/products/pricing-settings/            Configuración de precios
GET    /api/products/suppliers/                   Proveedores
GET    /api/products/purchase-orders/             Órdenes de compra
POST   /api/products/scryfall/search/             Buscar carta en Scryfall
POST   /api/products/scryfall/import/             Importar carta desde Scryfall
```

### Carrito
```
GET    /api/cart/                  Ver carrito
POST   /api/cart/items/            Agregar producto
PATCH  /api/cart/items/{id}/       Actualizar cantidad
DELETE /api/cart/items/{id}/remove/ Eliminar ítem
DELETE /api/cart/clear/            Vaciar carrito
```

### Órdenes
```
GET    /api/orders/                     Listar órdenes del usuario
GET    /api/orders/{id}/               Detalle de orden
POST   /api/orders/from-cart/          Crear orden desde carrito
POST   /api/orders/manual/             Crear orden manual (admin/worker)
POST   /api/orders/{id}/cancel/        Cancelar orden
PATCH  /api/orders/{id}/update-status/ Cambiar estado (admin/worker)
POST   /api/orders/shipping-quote/     Cotizar envío Chilexpress
GET    /api/orders/assisted/           Compras asistidas
```

### Pagos
```
POST   /api/payments/webpay/create/    Iniciar transacción Webpay
POST   /api/payments/webpay/commit/    Confirmar transacción Webpay
GET    /api/payments/receipts/{order_id}/ Comprobante de pago
```

## Tareas programadas (cron)

Liberar reservas de stock expiradas — ejecutar cada 5 minutos:

```cron
*/5 * * * * cd /ruta/store_backend && python manage.py release_expired_stock_reservations >> /var/log/stock_release.log 2>&1
```

Sincronizar precios desde Scryfall — ejecutar diariamente:

```cron
0 3 * * * cd /ruta/store_backend && python manage.py sync_external_prices >> /var/log/scryfall_sync.log 2>&1
```

## Deploy en PythonAnywhere

### 1. Crear base de datos MySQL
Panel → Databases → Create new database (nombre: `manamarket`)

### 2. Instalar dependencias
```bash
pip install -r requirements.txt
```

### 3. Configurar `.env`
```env
MYSQL_NAME=tu_usuario$manamarket
MYSQL_USER=tu_usuario
MYSQL_PASSWORD=<contraseña-del-panel>
MYSQL_HOST=tu_usuario.mysql.pythonanywhere-services.com
MYSQL_PORT=3306
DEBUG=False
SECRET_KEY=<generar con get_random_secret_key()>
ALLOWED_HOSTS=tu_usuario.pythonanywhere.com
CORS_ALLOWED_ORIGINS=https://tu-frontend.vercel.app
```

### 4. Migraciones y superusuario
```bash
cd store_backend
python manage.py migrate
python manage.py createsuperuser
```

### 5. Configurar WSGI
En panel Web → WSGI configuration file:
```python
import os, sys
sys.path.insert(0, '/home/tu_usuario/e-commerce/store_backend')
os.environ['DJANGO_SETTINGS_MODULE'] = 'store_backend.settings'
from django.core.wsgi import get_wsgi_application
application = get_wsgi_application()
```

### 6. Tareas programadas
Panel → Tasks → agregar tareas diarias para `sync_external_prices` y cada 5 minutos para `release_expired_stock_reservations`.
