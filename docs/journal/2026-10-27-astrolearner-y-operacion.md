# 2026-10-27 - AstroLearner y continuidad operativa

## Objetivo y alcance

Reunir las implementaciones acumuladas desde la entrada anterior y dejar
documentadas sus condiciones de activación. Esta entrada describe el código y
los procedimientos versionados; no acredita por sí misma el estado actual del
servidor ni la instalación de todos los cambios preparados.

## Factory: pruebas separadas y clips por escena

- Se añadió un Compose de staging con contenedor, puerto y trabajos propios,
  enlazado solo a loopback. Reutiliza el Ollama existente y su voz en solo
  lectura; una generación de prueba puede consumir CPU y afectar a su cola.
- Cada segmento puede incluir un prompt visual para producir un clip fuera del
  servidor. El panel admite una subida opcional MP4 H.264 de 1–20 segundos,
  comprueba sus características y limita el tamaño por clip y por trabajo.
  Sin clip se mantiene el render procedural existente. No se instaló un motor
  local de generación de vídeo ni se añadió una API de pago.
- Se conserva el vídeo largo y los tres Shorts con ángulos propios. Para
  trabajos de al menos dos minutos se intenta extraer además un Short literal y
  continuo del guion, cuando existe un fragmento válido.
- La auditoría del guion reduce el contexto y contempla respuestas compactas
  para mitigar JSON truncado. Una narración fuera del rango de duración admite
  una revisión acotada antes de repetir su validación. Se mantienen las
  referencias a fuentes y la revisión humana; el modelo no puede inventar
  hechos para rellenar tiempo.

La guía de [Factory](../../infrastructure/docker/astrolearner-factory/README.md)
explica las pruebas y la conservación de datos. Generar prompts no significa
que se hayan generado los clips; subir o publicar resultados sigue siendo una
acción humana.

## ISS Live: continuidad, control y visibilidad

- El controlador diferencia un fallo de transporte de errores de encoder,
  configuración o memoria. Los cortes recuperables intentan retomar la misma
  emisión y su entrada, sin crear un vídeo nuevo en cada reintento. La fecha
  límite original del bloque se conserva; al alcanzarla se cierra y rota.
- El multistream opcional codifica una vez y envía a YouTube y Starvios con
  colas por destino. Su configuración permanece privada y guardar no inicia
  una emisión. La preparación local no acredita recepción en la plataforma ni
  ofrece dos emisores independientes ante un fallo común del servidor.
- El portal permite guardar títulos y descripciones, consultar por separado
  progreso de FFmpeg, salud de YouTube y antigüedad de la posición ISS, y
  mostrar el tema musical según el progreso de medios confirmado.
- Una autorización inicial del operador crea una sesión revocable mediante
  cookie Secure/HttpOnly/SameSite=Strict. El token no se guarda en el
  almacenamiento web ni se convierte el control en acceso anónimo. El inicio
  del directo sigue siendo manual tras un reinicio.
- La captura opcional abre el reproductor en un navegador aislado del servidor,
  con sandbox, plazos máximos y comprobación de avance. No captura el portal ni
  el escritorio del ordenador. La noche orbital no se trata como un fallo y
  recibir una señal externa no demuestra qué material muestra el proveedor.
- Se prepararon mapas de esquina, pruebas de cadencia y recuperación de imagen.
  El mapa ESA tiene comprobaciones de frescura y atribución; el mapa propio
  permite una alternativa local. La autorización de una fuente no acredita
  automáticamente el uso de otra.

El [último panel preparado](../../infrastructure/docker/astrolearner-iss-live/STREAM-UPGRADE.md)
añade respaldo cámara → mapa, un panel orbital persistente, tarjetas de fuentes
oficiales con fechas y una sesión melódica original de una hora precalculada.
Su perfil produce una salida de 30 FPS; la frecuencia de rasterizado y de los
datos se controla por separado. No copia el panel de otro canal y no presenta
imágenes fechadas o pronósticos como observaciones en directo.

La activación exige una ventana con el directo detenido, comparación de
versiones, copia de recuperación y pruebas previas sin publicación. Si los
archivos del servidor no coinciden con la base prevista, el instalador rechaza
sobrescribirlos. Las guías de [ISS Live](../../infrastructure/docker/astrolearner-iss-live/README.md)
y [captura](../../infrastructure/docker/astrolearner-iss-live/BROWSER-CAMERA.md)
detallan los límites y la reversión.

## Backup y mantenimiento

- El backup preparado reconoce los servicios ISS por etiquetas y volúmenes
  esperados para conservarlos encendidos. Sus archivos persistentes se copian
  a un snapshot privado y se comprueban inventarios, formatos y metadatos; un
  cambio concurrente que impida una copia coherente hace fallar la operación.
- AdGuard solo se detiene durante su propia copia. Las demás aplicaciones
  mantienen la copia en parada, con recuperación de los contenedores detenidos
  y comprobación de errores. Se conserva la verificación SHA-256 y el límite
  de 90 minutos del servicio.
- El helper de mantenimiento separa actualizaciones de Ubuntu, Docker y
  Tailscale, requiere un backup reciente verificado y evita reinicios o
  actualizaciones automáticas de imágenes de aplicaciones. El procedimiento
  conserva inventarios y recuperación privada; no garantiza revertir cualquier
  fallo de paquetes.

Véanse [copias](../backups.md) y [mantenimiento](../manual-maintenance.md).
Un snapshot coherente y un checksum correcto no sustituyen una restauración
completa ni garantizan ausencia de carga sobre el directo.

## Validación y pendientes

El repositorio incorpora pruebas para guiones y medios, autenticación,
metadatos, frescura de señales, mapas, recuperación, multistream, playlists,
instaladores y snapshot ISS. También incluye preflights sintéticos sin claves
ni publicación para probar cambios de fuente y receptores de loopback.

Validación local del 27 de octubre, sin conectar con las plataformas ni iniciar
emisiones:

| Suite | Resultado |
|---|---|
| ISS Live | 963 pruebas superadas; 10 omitidas |
| Factory | 26 pruebas superadas |
| Snapshot de backup | 51 pruebas superadas; 1 omitida |

Las omisiones dependen de FFmpeg/ffprobe, shell POSIX y permisos de enlaces o
metadatos que este entorno Windows no ofrece. No equivalen a pruebas aprobadas
en Linux. Se corrigió una aserción de Factory que dependía de los saltos de
línea del prompt, conservando las comprobaciones de duración y de contenido.

Antes de dar por activa una revisión en el servidor quedan por confirmar:

1. Qué versiones e imágenes están realmente instaladas y qué diagnóstico
   devuelve cada servicio, sin publicar su configuración privada.
2. El backup completo con el directo activo, comprobando que conserva el
   emisor y el identificador de emisión, y una restauración de sus datos.
3. La reproducción de la fuente autorizada, la cadencia sostenida y el consumo
   real de recursos durante varias horas; una salida nominal de 30 FPS no
   demuestra 30 capturas distintas por segundo.
4. La recepción de cada destino externo y la activación del último panel y
   sesión musical. Las pruebas unitarias o con loopback no lo acreditan.

## Privacidad de la publicación

Solo se versionan fuentes, pruebas, ejemplos y documentación revisados. Quedan
fuera los archivos de entorno reales, OAuth, claves de emisión, sesiones,
copias privadas, registros completos, analíticas del canal, capturas y paquetes
creativos o de despliegue temporales. Los ejemplos usan marcadores y no
publican identificadores de la red doméstica.
