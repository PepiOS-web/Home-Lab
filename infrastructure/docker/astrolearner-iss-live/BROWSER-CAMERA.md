# Cámara autorizada en el servidor: prueba antes de emitir

Preparación solicitada el 14 de octubre de 2026. El operador confirmó disponer
de permiso para retransmitir el reproductor. Esta configuración no acredita
permisos por sí misma y no se debe usar para otras fuentes sin comprobarlos.

La captura abre una página de vídeo en un navegador aislado del servidor.
La prueba con mapa añade una pestaña de ESA en esa misma instancia, no un segundo
navegador. No captura el portal, sus controles ni el escritorio del ordenador.
No monta OAuth, claves RTMP, perfiles de navegador ni el socket Docker.
Se mantiene el sandbox de Chromium y no se debilitan las protecciones del host.
La imagen base se descarga desde Microsoft y el paquete de Chrome desde Google,
ambos fijados y verificados por digest/hash; no se instalan en Windows.

El selector preparado conserva una sola salida y la música Lo-Fi: cámara válida
→ vídeos descargados → mapa. Pausas, errores del reproductor y falta de avance
invalidan la captura. La noche orbital no es un fallo. NASA puede mostrar su
propio material de respaldo, por lo que la etiqueta no asegura que cada imagen
sea una cámara en tiempo real.

## Mapa ESA en una esquina

El operador eligió expresamente el mapa exacto de
[ESA ISS Tracker](https://isstracker.spaceflight.esa.int/), no una recreación.
La prueba lo coloca arriba a la derecha, con un ancho del 28 % y el crédito
`ESA ISS Tracker · © ESA`. Se captura el widget completo a 625×365, sin eliminar
su logo ni alterar sus datos. Se revisan carga, telemetría y avance del reloj
GMT antes de mostrar una imagen; las actualizaciones son cada cinco segundos.
Un mapa que falla o queda obsoleto se oculta, sin reiniciar la cámara o el audio.
El recuadro acompaña a la cámara; durante su corte se conserva el respaldo actual
de vídeos locales y el mapa propio de emergencia.

El valor compartido `ISS_BROWSER_MAP_OVERLAY` sigue siendo `none` por defecto.
La prueba y el despliegue opt-in activan `esa`. Para retransmitir públicamente ESA
debe comprobarse que el uso previsto
está cubierto por sus condiciones o autorización; el permiso de la cámara no
acredita por sí mismo el de este mapa. Véanse las
[condiciones de ESA](https://www.esa.int/ESA_Multimedia/Terms_and_conditions_of_use_of_images_and_videos_available_on_the_esa_website).

Las capturas de vídeo ahora utilizan el método de Chrome
[`Page.captureScreenshot`](https://chromedevtools.github.io/devtools-protocol/tot/Page/#method-captureScreenshot)
con codificación optimizada para velocidad. No cambian resolución, calidad JPEG,
sandbox, límites de imagen, plazo máximo ni validación del avance del vídeo.
La prueba mantiene el mínimo de captura de 11,4 FPS para una salida de 12 FPS;
no se rebaja para convertir un resultado fallido en aprobado.

### Corrección de continuidad preparada el 15 de octubre

`MAP_SECONDS=0` elimina ahora tanto la entrada de mapa a pantalla completa como
su filtro de superposición. Una superposición invisible seguía sincronizando
el vídeo con una fuente nominal de 1 FPS que entregaba menos: se midieron
0,9769 FPS en esa fuente y retraso creciente en el emisor. El mapa ESA de la
esquina no cambia: está integrado en la captura del navegador, no en esa entrada.
Cuando el mapa grande sí está habilitado, su endpoint programa el siguiente
fotograma por plazo, descontando el tiempo de codificación del JPEG.

La comprobación `python -m app.stream_pacing_probe`, dentro del contenedor y
con el directo detenido, utiliza cámara y música reales durante 30 segundos a
un archivo temporal local, sin OAuth ni publicación. Exige cadencia de salida
de al menos 0,985 respecto al reloj después del arranque, audio AAC/vídeo H.264,
dimensiones correctas y cero descartes. Se cancela si alguien inicia una emisión.
No sustituye una comprobación de varias horas ni la recepción real de YouTube.

El instalador `infrastructure/maintenance/install-stream-stability.sh` incorpora
esta corrección y el backup sin parada del emisor. Conserva FPS, encoder, música,
token y configuración del portal; construye/recrea solo `iss-live`, sin sus
servicios dependientes. No actualiza paquetes del host, no ejecuta un backup
completo, no reinicia el servidor ni inicia una emisión. La construcción de la
imagen puede resolver su imagen base; no equivale a congelar sus paquetes. El
operador debe ejecutarlo con sudo usando el
bundle preparado; antes exige parada confirmada, reconoce el script de backup
anterior y guarda recuperación privada. Véase [la política de backup](../../../docs/backups.md).

### Mapa compacto legible (16 de octubre de 2026)

El modo `astrolearner` sustituye el pequeño visor ESA por una tarjeta propia de
432×304 píxeles, dibujada a 2× y reducida una vez. Usa Natural Earth, trayectoria
reciente y la posición orbital ya consultada por el emisor; no calcula una
órbita futura ni muestra datos inventados si todavía no hay posición válida.
La posición pasa a «ANTERIOR» a los 45 segundos sin actualización. Las fuentes
conservan la atribución de Natural Earth; no se presenta como mapa oficial ESA.

`/corner-map.png` solo devuelve la tarjeta PNG y una cabecera fija de frescura,
sin rutas locales ni credenciales. El sidecar la consulta cada cinco segundos
por un endpoint interno fijo, sin proxies ni redirecciones. No abre una segunda
página ESA, y el mapa entra en la composición del navegador: no añade una entrada
a FFmpeg ni cambia sus relojes, FPS, bitrate o encoder. El modo ESA sigue disponible
y no se recorta ni modifica su página original.

El bundle `infrastructure/maintenance/install-crisp-corner-map.sh` exige detener
la emisión y la base efectiva de 720p/30 FPS con inicio manual. Comprueba hashes,
guarda fuentes privadas, conserva la configuración/imagen de recuperación con
el deploy existente y prepara `enable-browser-camera.sh 30 astrolearner`. La
activación no publica en YouTube. Si la validación falla, no iniciar; conservar
la ruta de rollback indicada. La prueba real de recepción/calidad en YouTube
sigue pendiente después de instalar.

### Recuperación de imagen al cambiar FPS

Si Docker conserva un contenedor pero ya no puede resolver su imagen histórica,
`enable-browser-camera.sh` no omite la recuperación ni usa `docker commit`.
Reconstruye únicamente la imagen del servicio afectado desde el código y la
configuración actuales, sin recrear contenedores todavía, y guarda un tag de
recuperación antes de aplicar los nuevos FPS. Los archivos `image-id.origin` y
`browser-image-id.origin` distinguen `original` de `rebuilt-current-source`;
`original-image-id` y `original-browser-image-id` conservan los identificadores
históricos. Una imagen reconstruida no es una copia bit a bit de la anterior.
Si falla su construcción o etiquetado, el despliegue se cancela sin reemplazar
`.env`. El rollback existente utiliza el identificador recuperable guardado.

### Ensayo aislado a 30 FPS (15 de octubre de 2026)

El soporte de 30 FPS es **opt-in**: el valor predeterminado y la producción
siguen a 12. El bundle `infrastructure/maintenance/test-stream-30fps.sh` comprueba
que el arreglo de cadencia está instalado tanto en el árbol fuente como en el
emisor en ejecución, rechaza cambios de código desconocidos y guarda una copia
privada de las fuentes antes de preparar la prueba.

Con el directo detenido, el operador ejecuta el instalador del bundle con sudo.
Este lanza `./scripts/test-browser-camera.sh 30`, sin publicar y sin modificar
`.env`. Se pausa únicamente el navegador de producción para no duplicar carga;
al terminar se intenta restaurar el mismo contenedor anterior. No pulsar
«Iniciar» durante la prueba. Los locks evitan otro backup/mantenimiento al mismo
tiempo; el temporizador de backup se recupera al salir.

La prueba usa los mismos presupuestos de CPU/RAM, la cámara autorizada, ESA,
respaldo NASA y la sesión Lo-Fi de una hora **solo lectura**. No monta OAuth ni
el estado de producción. Durante 100 segundos comprueba
cámara→respaldo→cámara, captura media ≥28,5 FPS y cadencia de salida medida ≥0,985
del tiempo real después del arranque, además de H.264/AAC sin descartes. La
comprobación de silencios omite los primeros diez segundos de fundido musical.
La imagen de prueba tiene una etiqueta distinta de producción.

Pasar no activa 30 FPS ni prueba estabilidad durante horas o recepción de
YouTube: antes de un directo de prueba se revisa la salida y se despliega de
forma explícita con `enable-browser-camera.sh 30`. Conservar la ruta de
recuperación indicada para volver atrás. 30 FPS de salida no garantizan treinta
imágenes nuevas: la cámara original y el respaldo grabado pueden ir más lentos.

### Ensayo opcional a 20 FPS (15 de octubre de 2026)

El valor predeterminado permanece en 12 FPS. La captura admite ahora hasta 30;
no se cambia un contenedor en ejecución por editar estos archivos. Para probar
20, primero **Detener** en el portal y esperar a que termine la emisión:

```sh
sudo ./scripts/test-browser-camera.sh 20
```

El mismo objetivo configura navegador, selector y encoder. Se exigen al menos
19 capturas por segundo de media, objetivo declarado de 20, salida de al menos
1.940 fotogramas en 100 segundos, cero descartes, audio continuo y recuperación
tras un corte. La prueba usa los mismos límites de CPU/memoria/procesos que el
encoder de producción, sin aumentarlos en producción ni cambiar el sandbox.
Durante este ensayo se pausa únicamente el navegador de producción, si estaba
ejecutándose, y se restaura su contenedor anterior al terminar, también si la
prueba falla. No se modifica `.env` ni se inicia ninguna emisión.

Solo si devuelve `status: ok`, instalar con la emisión aún detenida:

```sh
sudo ./scripts/enable-browser-camera.sh 20
```

Tras `LISTO`, iniciar manualmente desde el portal. El despliegue crea copia
privada de configuración e imágenes para recuperar el montaje anterior. Una
repetición sin argumento conserva los FPS ya configurados; `12` selecciona de
nuevo el objetivo anterior. El objetivo y las capturas medidas no garantizan
20 fotogramas únicos de la fuente, ni estabilidad de horas: revisar movimiento
y salud de señal después de iniciar. Si la prueba falla, conservar 12 FPS.

## Ejecutar la prueba

1. Pulsar **Detener** en el portal y esperar a que termine la emisión actual.
2. En la terminal SSH del servidor:

```sh
cd /srv/data/compose/astrolearner-iss-live
sudo ./scripts/test-browser-camera.sh
```

El script comprueba que producción está parada y aborta si no puede comprobarlo.
Construye solo imágenes de prueba, con archivos y puertos separados. Espera
captura real y genera un vídeo local de 100 segundos con audio de prueba.
Interrumpe y recupera solo el navegador de staging y exige la secuencia
`camera → recorded → camera`, 720p a los FPS elegidos (12 por defecto), captura suficientemente
rápida y audio sin silencios. No llama a la API de publicación ni crea vídeos
en YouTube. Al finalizar detiene los contenedores de prueba y elimina el vídeo
temporal. Los vídeos descargados de producción se montan en solo lectura.
El montaje con cámara limita los hilos de decodificación, filtros y codificación;
no se eleva el límite de procesos/hilos del contenedor ni se cambia el montaje
actual sin cámara. Si FFmpeg termina, el resultado incluye indicadores fijos y
contadores numéricos de cgroup para distinguir límites de procesos o memoria,
sin imprimir mensajes originales, URLs ni claves.

`status: ok` es necesario antes de activar la configuración pública, no una
garantía de estabilidad durante horas. Si aparece `browser_error`, no desactivar
el sandbox, AppArmor ni otras protecciones para forzar el arranque; revisar
primero el diagnóstico del entorno. Si la fuente exige iniciar sesión o resolver
un desafío, la prueba debe fallar y conservarse el respaldo.

El archivo `.env.camera-browser` contiene solo el permiso y el identificador
público de vídeo y queda excluido de Git. El `.env` de producción permanece igual.
No ejecutar `docker compose config` sin `--quiet` con configuraciones privadas.

### Si aparece browser_error sin fotogramas

```sh
sudo ./scripts/diagnose-browser-camera.sh
```

Este diagnóstico reconstruye solo la última capa de código del navegador y
arranca un contenedor efímero en `about:blank`. No abre NASA, YouTube ni el portal,
no publica y no necesita iniciar el contenedor del selector. Devuelve etapa,
código fijo, tipo de error e indicadores de una lista cerrada (`error_signals`),
no su texto original ni URLs. La mera aparición del nombre del archivo de Chrome
`zygote_host_impl_linux.cc` no se considera evidencia de un fallo del sandbox.
Permite distinguir
un fallo del sandbox, permisos del perfil, creación de procesos o del reproductor.
Una prueba de arranque correcta no confirma todavía recepción de la cámara.

## Después de revisar el resultado

El ensayo real con mapa ESA del 14 de octubre aprobó: 100 segundos de vídeo,
1.200 fotogramas, corte y recuperación, sin silencios en el audio de prueba.
Captura media: 11,45 FPS frente a mínimo 11,4; el margen es estrecho y no
acredita estabilidad de horas ni recepción de YouTube.

`compose.camera-browser-live.yaml` conecta el sidecar al selector. Para instalar
esa configuración, después de **Detener** en el portal:

```sh
cd /srv/data/compose/astrolearner-iss-live
sudo ./scripts/enable-browser-camera.sh
```

El script aborta si hay emisión o no puede confirmar su parada. Construye antes
de aplicar; comprueba de nuevo la parada tras construir. Respalda el `.env`
privado y las imágenes anteriores, y guarda `COMPOSE_FILE` en `.env` para que
los siguientes `docker compose up` conserven el navegador y el mapa. Mantiene
`AUTO_START=false`; ni publica ni llama al inicio de la emisión. No modifica
música, títulos guardados, token, Homepage, Caddy ni protecciones del host.
Antes de indicar `LISTO` exige cámara y mapa disponibles, control preparado,
al menos diez segundos de capturas (120 a 12 FPS, 200 a 20), el 95 % del objetivo
de FPS, coincidencia del objetivo del navegador y una pista Lo-Fi estéreo válida
de una hora.
Solo después de `LISTO` se puede iniciar manualmente desde el portal.

Si los contenedores ya se instalaron pero la comprobación anterior se quedó
esperando, no repetir el despliegue ni recuperar la configuración por ese motivo.
Con la emisión detenida, repetir solo la comprobación:

```sh
sudo ./scripts/check-browser-camera.sh
```

Esta comprobación no recrea ni detiene contenedores. Cierra stdin de Compose y
desactiva su modo interactivo; el límite de cada ejecución incluye finalización
forzada si hiciera falta. Lee solo 512 bytes del vídeo local para actualizar el
selector mientras no hay encoder saliente y muestra progreso durante la espera.

El script imprime la ruta de la copia de recuperación (directorio 700, `.env`
600), nunca su contenido. Si fuera necesario, con la emisión detenida:

```sh
sudo ./scripts/rollback-browser-camera.sh /ruta/exacta/de/la/copia/indicada
```

Restaura configuración e imágenes anteriores y detiene solo el navegador del
proyecto ISS. No usa `down`, no borra volúmenes ni datos. Si la API no responde,
solo acepta una parada confirmada por Docker; si no, pide detener `iss-live`.
El puerto 8095 existe solo en staging; producción no abre puertos de captura.

Perfil seccomp derivado del de Microsoft Playwright, commit
`ccd519ec3de6bf3f1339499fb234f5e969b33844`,
`utils/docker/seccomp_profile.json`.
SHA-256 del original: `cc3e61cabda6bbc1e53e54d27ba4d55a9d3be829b6dd1a596f4a7b31b1cc7849`.
Adaptaciones locales para el contenedor sin capacidades:

- `clone3` sigue denegado, pero devuelve `ENOSYS` (38), como Docker moderno,
  para que glibc pueda recurrir a `clone`.
- Se permite la llamada `chroot`, necesaria para aislar el sistema de archivos
  del sandbox de Chrome. El kernel sigue exigiendo `CAP_SYS_CHROOT` en el espacio
  de nombres del llamador; no se concede esa capacidad al contenedor.

Estas adaptaciones solo se aplican al sidecar. Se conservan usuario no root,
`cap_drop: ALL`, `no-new-privileges`, seccomp y AppArmor; no se cambia el host.
Licencia conservada en `camera-browser-LICENSE`.
