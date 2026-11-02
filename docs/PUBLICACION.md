# Publicación y operación

## Requisitos del hosting

- Python 3.11 o superior, con los módulos estándar SQLite y JSON1 habilitados.
- Ejecución de aplicaciones WSGI con acceso a disco persistente.
- Una carpeta privada para la base de datos y los archivos recibidos.
- HTTPS mediante el hosting o un proxy inverso.
- Un límite de solicitudes de al menos 35 MB para permitir tres archivos de 8 MB codificados en JSON. El servidor limita los archivos decodificados a 8 MB.

No se requieren paquetes para usar el servidor local. En producción utiliza el servidor WSGI mantenido por el proveedor; no publiques directamente el servidor de desarrollo incluido.

El punto de entrada WSGI es `server:app`. La aplicación inicializa la estructura de datos al importar el módulo. Configura una sola inicialización previa al arranque de los procesos de trabajo y evita múltiples arranques simultáneos sobre una base nueva. Por ejemplo, si el proveedor usa Gunicorn, puede iniciar la aplicación con precarga del módulo.

Configura `BAILES_DATA_DIR` con la ruta absoluta de una carpeta privada y persistente, fuera de la raíz estática. Sin esa variable, se utiliza `runtime/` dentro del proyecto. La aplicación requiere permiso de lectura y escritura sobre esa carpeta y configura sus permisos como privados.

El servidor atiende el sitio en la raíz de su origen. Si se usa un proxy con un prefijo de ruta, deben ajustarse el montaje WSGI y las rutas públicas de los medios antes de publicar. Evita publicar una carpeta completa como sitio estático: el servidor ya limita los archivos públicos a `public/` y los medios autorizados.

## Primera instalación

1. Copia el proyecto completo al hosting y conserva las rutas relativas de `data/` y `public/`.
2. Configura `BAILES_DATA_DIR` y el proceso WSGI.
3. Crea una cuenta con `python3 server.py --create-admin`. La contraseña se ingresa de forma oculta en la consola; no existe una contraseña predeterminada.
4. Configura HTTPS y asegúrate de que el servidor WSGI reconozca correctamente el esquema HTTPS detrás del proxy, para que las cookies de sesión se emitan con `Secure`.
5. Verifica inicio de sesión, guardado de una ficha, actualización del mapa, recepción de un aporte con imagen, aprobación y consulta pública desde otra sesión.
6. Define una copia de respaldo periódica de la base de datos y de los archivos multimedia.

La autenticación usa contraseñas derivadas con PBKDF2-SHA256, sesiones con expiración, cookies HttpOnly y SameSite, control de origen y un token CSRF para escrituras. Las cuentas de prueba no se incluyen en la entrega. El acceso al panel se determina en el servidor, no por una contraseña almacenada en JavaScript.

Los aportes se guardan como pendientes. Sus medios no se sirven públicamente hasta su aprobación. El contacto del autor se excluye de la API pública. Los tipos de archivo se verifican por su firma, además del límite de tamaño. Los textos se presentan como texto y no se interpretan como HTML.

## GitHub Pages y la vista independiente

El `index.html` de la raíz del paquete es una vista autónoma con las dos ilustraciones, los datos iniciales y las bibliotecas del mapa integradas. Puedes subir ese archivo a GitHub Pages sin otros archivos. Necesita internet para las capas cartográficas.

GitHub Pages no ejecuta Python, SQLite ni el panel privado. En esta vista, el formulario prepara un archivo de aporte para entregarlo al equipo; no informa falsamente que lo recibió un servidor. La instalación completa cambia automáticamente al envío real cuando encuentra su API en el mismo origen.

La vista estática conserva la carga inicial del proyecto. Las modificaciones del servidor se consultan en tiempo real desde su API y no reescriben el archivo estático inicial. Para publicar una nueva copia estática con los datos actualizados, debe generarse una exportación de esos datos y reconstruirse la vista desde la instalación.

## Datos y contenidos de partida

Se conservan 52 bailes, 133 fiestas y las referencias de 346 comunas. La carga de bailes y fiestas corresponde al material 2026 de Valparaíso proporcionado para el proyecto. No se agregaron agrupaciones de otras regiones sin información de respaldo.

Las coordenadas iniciales son referencias comunales. Los marcadores comparten ese punto cuando no se dispone de una ubicación más precisa y pueden desplegarse desde sus grupos. No se desplazaron puntos para aparentar coordenadas de sedes o santuarios.

Los números y colores de las fichas se guardan con cada registro, conservan su identidad al filtrar y son únicos en la carga inicial. Las relaciones de participación comienzan vacías cuando el material no identifica expresamente qué baile participa en una fiesta; el panel permite incorporarlas y consultarlas en ambos sentidos.

Los capítulos históricos contienen una presentación inicial con fuentes públicas. El mandante puede revisarlos y sustituirlos desde el panel, junto con los antecedentes específicos de cada agrupación. No se incluyen testimonios ficticios ni se atribuyeron las ilustraciones a una persona no identificada.

## Capas territoriales futuras

La estructura incluye una tabla `layers` y un punto de integración cartográfica para capas GeoJSON. Cada capa puede contener `id`, `name`, `color` y `geojson`. Las capas cargadas se ofrecen como controles separados del mapa.

No se inventaron capas de recursos, actividades extractivas, energía, pesca o amenazas. La preparación y carga de esas capas corresponde a una ampliación con los datos y el alcance que se definan, tal como plantea la cotización.

## Actualización y recuperación

- Respalda primero con `python3 backup.py nombre-del-respaldo.zip`.
- Actualiza los archivos de código y las bibliotecas sin sustituir `runtime/`.
- Conserva las cuentas y la base de datos del cliente.
- Para recuperar una copia completa, detén el proceso, conserva la carpeta de datos actual con otro nombre y restaura las rutas `runtime/archive.sqlite` y `runtime/media/` del respaldo en la carpeta de datos configurada. Comprueba los permisos privados y reinicia el proceso.
- Para restablecer una contraseña desde la consola autorizada, usa `python3 server.py --reset-password`.

## Pruebas

Ejecuta `python3 -m unittest discover -s tests -v`. Las pruebas crean bases temporales y cubren autenticación, autorización, CSRF, registros, conflictos de edición, relaciones, calendario, territorios, imágenes, recepción y moderación de aportes, privacidad y recuperación de versiones.

Ejecuta `python3 build.py` después de modificar el HTML, CSS, JavaScript o los datos iniciales. El proceso genera `public/index.html` sin instalar dependencias.
