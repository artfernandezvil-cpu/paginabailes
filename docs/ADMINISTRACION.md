# Administración del archivo de Bailes Chinos

Abre **Administración**, al final del sitio, e ingresa con tu correo y contraseña. La cuenta inicial se crea en la primera apertura local o por quien instala el sitio.

## Bailes y fiestas

Busca una ficha y pulsa **Editar**. Puedes cambiar nombre, localidad, comuna, historia, fuente, imagen, video, ubicación y color. Para cargar una fotografía usa **Cargar imagen**; no necesitas conocer su dirección web.

Para una nueva agrupación pulsa **+ Baile**. Para una celebración pulsa **+ Fiesta**. Cada ficha recibe un número y un color propios; si eliges un color ya utilizado, el sistema pide otro para conservar la identificación.

En una fiesta puedes indicar el mes y, cuando esté confirmada, la fecha exacta. También puedes marcar sus agrupaciones participantes. En la ficha de un baile puedes asociar las fiestas en que participa. Las relaciones se muestran en ambas direcciones y los cambios se reflejan en el mapa y el calendario.

Selecciona **Referencia comunal** cuando solo conozcas la comuna: el sistema usa su punto de referencia. Elige **Referencia de localidad** o **Coordenadas del lugar** solo cuando cuentes con esos datos. Latitud y longitud se ingresan en grados decimales.

**Retirar** elimina una ficha del recorrido público. Puedes recuperarla en **Recuperar versiones**.

## Textos y secciones

Puedes cambiar el nombre y la bajada de la marca, título y presentación de la portada, título del navegador, descripción para buscadores, títulos y descripciones de las secciones, texto del pie de página y enlaces de contacto.

En **Menú y orden de las secciones**, cambia los nombres del menú, sube o baja cada sección y marca cuáles se muestran. Los botones del inicio se ajustan si ocultas su sección de destino.

En **Historia y contenidos patrimoniales**, abre cada capítulo para editar su título, contenido y fuente. Puedes agregar, ordenar y retirar capítulos.

En **Secciones adicionales**, puedes agregar contenido con texto e imagen y su enlace en el menú. Esto permite ampliar las páginas sin modificar código.

Pulsa **Guardar cambios**. Si otra persona guardó contenidos mientras trabajabas, el sistema evita sobrescribirlos y te pide actualizar antes de continuar.

## Logo, imágenes y colores

Elige una de las dos ilustraciones originales o carga otra imagen para el logo y para cada lado de la portada. El sistema conserva las imágenes cargadas para reutilizarlas. **Restaurar original** permite volver a la ilustración inicial.

Puedes cambiar fondo, color del texto, acento y color de botones. Guarda los cambios para aplicarlos al sitio.

## Territorios

Busca una comuna y cambia sus antecedentes o su punto de referencia. Las fichas que usan referencia comunal se actualizan con ella. Las fichas con coordenadas específicas conservan su ubicación.

## Aportes de la comunidad

Los testimonios y archivos recibidos aparecen en **Aportes**. Antes de aprobarlos, revisa el relato, los créditos y su autorización. El contacto del autor queda reservado al equipo y no se incluye en la consulta pública.

- **Publicar** incorpora el aporte y sus archivos al archivo público.
- **Reservar sin publicar** mantiene el material para el equipo.
- **Volver a revisión** retira su publicación y permite revisarlo otra vez.

El formulario recibe hasta tres archivos por aporte, con un máximo de 8 MB cada uno. Admite fotografías PNG, JPG y WebP, documentos PDF y audios MP3, OGG o WAV. Los videos se pueden asociar mediante un enlace HTTPS.

Si alguien preparó un aporte desde la vista descargable, usa **Importar un aporte descargado** y selecciona su archivo JSON. El material se incorpora a la bandeja de revisión.

## Usuarios

Las cuentas administradoras pueden crear otras cuentas. Una persona con rol **Editor** puede gestionar contenidos, registros y aportes. El rol **Administrador** también habilita o desactiva usuarios. Al desactivar una cuenta se cierran sus sesiones. El sistema protege la cuenta con la que estás trabajando y evita dejar el sitio sin administración.

## Recuperar versiones y respaldar

El sistema conserva versiones anteriores al guardar textos, imágenes, fichas y territorios. Abre **Recuperar versiones**, identifica el contenido por su fecha y pulsa **Recuperar**. El estado actual también se guarda antes de recuperar otra versión.

**Exportar datos del sitio** descarga los datos en JSON, incluidos los antecedentes privados de los aportes: guárdalo solo donde tenga acceso el equipo. Este archivo no contiene los archivos multimedia binarios ni las contraseñas.

Para un respaldo completo, quien administra el servidor puede ejecutar `python3 backup.py`. El ZIP incluye la base de datos y los archivos cargados. La carpeta `runtime/` contiene los datos persistentes y nunca debe sustituirse al actualizar el código.

## Cambios que requieren desarrollo

Los contenidos y las relaciones anteriores se gestionan desde el panel. Una nueva función que cambie el funcionamiento del sistema, una integración externa o una nueva capa territorial especializada requiere desarrollo. Esto permite ampliar el proyecto manteniendo la administración cotidiana en manos del cliente.
