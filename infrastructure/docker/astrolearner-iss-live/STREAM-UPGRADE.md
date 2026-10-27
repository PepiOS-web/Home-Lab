# Panel orbital y música melódica — 23/10/2026

Esta actualización se prepara sin detener la emisión existente. La activación
requiere una ventana de mantenimiento y sudo en el servidor. No arranca ni
detiene emisiones públicas automáticamente.

## Cambios

- Capturador: plazos máximos para las operaciones del navegador; un bloqueo
  invalida la fuente. Si Chrome no puede cerrarse, el sidecar sale para que su
  política `unless-stopped` lo recicle. No desactiva el sandbox.
- Respaldo: cámara automática → mapa orbital, sin borrar los vídeos. La opción
  de volver a utilizar grabaciones queda en el portal y no detiene el encoder.
- Panel persistente después del selector: mapa propio, datos orbitales, UTC,
  antigüedad, estado de fuente, música y tarjetas Sol/Tierra/Luna/auroras.
  Los JPEG se repiten a 30 FPS, aunque datos y raster se actualizan aparte.
- Imágenes: fuentes HTTPS fijas NASA SDO/EPIC/SVS y NOAA SWPC, sin claves,
  redirecciones o URLs elegidas por el usuario. Caché local limitada; conservar
  una imagen antigua no renueva su fecha. Luna 2026 se deshabilita fuera del año.
- Música: doce temas originales de cinco minutos con melodía, secciones A/B,
  variaciones y transiciones. WAV de una hora precalculado, sin GPU ni IA
  funcionando continuamente. Se mantiene el audio anterior para revertir.
- Audio del perfil con panel: limitador de picos antes de AAC. No equivale a
  una certificación de LUFS/true-peak ni sustituye la escucha.
- Controles autenticados `/presentation`: respaldo aplicado ahora; panel y
  selección musical al próximo bloque. No hay cambio en caliente del archivo WAV.

## Etiquetas y fuentes

«Señal externa» confirma recepción, no que el proveedor esté mostrando una
cámara real en ese instante. El mapa sigue la ISS actual y no necesariamente
el terreno de un vídeo grabado. EPIC es imagen fechada, Luna es visualización
calculada, SDO304 es falso color y auroras es pronóstico.

Fuentes: [SDO](https://sdo.gsfc.nasa.gov/data/dataaccess.php),
[EPIC](https://epic.gsfc.nasa.gov/about/api),
[Luna2026](https://svs.gsfc.nasa.gov/5587/),
[NOAA](https://www.spaceweather.gov/products/aurora-30-minute-forecast).
Conservar créditos de NASA/SDO y equipos AIA, EVE y HMI, NASA EPIC, NASA SVS y
NOAA SWPC. El programa no copia el panel ni la retransmisión de AfarTV.

## Activación

1. Ejecutar primero `sudo python3 /ruta/al/paquete/install.py diagnose` para
   consultar la captura. No modifica ni publica.
2. En una ventana elegida, pulsar **Detener** en el portal y esperar confirmación.
3. Ejecutar `sudo python3 /ruta/al/paquete/install.py install`.
4. El instalador verifica los predecesores y hashes, guarda una copia privada
   `.before-stream-upgrade-*`, conserva las imágenes Docker antiguas y compila.
5. Ejecuta obligatoriamente un probe de 30s sin red externa ni credenciales,
   con cámara/mapa sintéticos, panel real y música nueva. Comprueba 720p30,
   H264/AAC, timestamps, cambio visual, niveles y velocidad.
6. Solo si todo pasa recrea servicios con autoarranque forzado a `false`.
   La emisión continúa detenida. Comprobar diagnóstico, datos y panel e iniciar
   manualmente desde el portal cuando corresponda.

La única clave de `.env` que cambia es `ISS_BROWSER_MAP_OVERLAY=none`, para
evitar duplicar el mapa dentro de la captura y del nuevo panel. Se conservan
OAuth, tokens, destinos, calidad y permisos. No publicar las copias privadas.

Ante un fallo, usar `rollback --recovery /srv/data/compose/astrolearner-iss-live/.before-stream-upgrade-FECHA`.
La reversión exige emisión detenida y rechaza modificaciones posteriores
desconocidas. No borra la música o los módulos nuevos: los deja para inspección.

## Fuera de la activación automática

La emisión vertical depende de YouTube Studio y de la compatibilidad de la
creación de directos por API; no se activa mediante este paquete. Los Shorts,
la selección de su vídeo relacionado y la promoción tampoco se publican solos.
Faltan las analíticas filtradas a directos recientes para medir resultados.
No se han añadido predicciones de amanecer, países/océanos, rayos o nubes:
necesitan integración adicional validada. No se inventan estos datos.

La reproducción real de la cámara y el rendimiento sostenido del servidor
solo se confirman después de las pruebas en ese servidor; los tests unitarios
no lo demuestran.
