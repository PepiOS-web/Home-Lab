# Portal local

## Objetivo

Homepage ofrece una unica interfaz para abrir Grafana, Uptime Kuma, NetAlertX, AdGuard Home, la consola oficial de Tailscale y la documentacion del proyecto. Homepage escucha en `127.0.0.1:8080` y Caddy lo publica como `https://portal.home.arpa`. El dashboard operativo de Grafana se integra en el portal bajo `/grafana/`.

## Seguridad

- La imagen utiliza una version fijada.
- El contenedor usa un usuario sin privilegios y `no-new-privileges`.
- No se monta `/var/run/docker.sock`.
- No se configuran widgets con tokens o credenciales.
- AdGuard Home y Tailscale se incorporan como enlaces simples, sin integrar sus APIs.
- Homepage solo recibe un JSON saneado; no puede leer el journal, el socket de Docker ni el estado privado de Tailscale.
- El control de AstroLearner usa un token aleatorio guardado en `.env`; Homepage
  no lo recibe. Se introduce una vez para crear una sesión de hasta 30 días en
  una cookie Secure/HttpOnly/SameSite=Strict limitada al control del directo.
  No se guarda el token en localStorage/sessionStorage. La sesión es revocable
  con «Cerrar sesión» y rotar el token invalida todas las sesiones existentes.
- El resumen elimina IP, puertos, huellas de claves y nombres de dispositivos.
- `HOMEPAGE_ALLOWED_HOSTS` restringe los encabezados Host a `portal.home.arpa`.
- `disableIndexing` solicita a buscadores que no indexen la pagina.
- El panel integrado mantiene la autenticacion de Grafana y no habilita acceso anonimo.
- Grafana comparte el origen de `portal.home.arpa`, evitando depender de cookies de terceros en navegadores moviles.
- `X-Frame-Options: SAMEORIGIN` continua protegiendo los paneles frente a sitios externos.

El portal no se expone directamente a Internet. El acceso remoto se realiza exclusivamente mediante Tailscale y las reglas descritas en la documentacion de acceso remoto.

## Configuracion

Los archivos persistentes residen en `/srv/data/appdata/homepage` y el proyecto Compose en `/srv/data/compose/homepage`.

Antes del primer despliegue se copian los archivos de `config/` al directorio persistente. Los enlaces utilizan nombres `*.home.arpa`; su resolucion se configura en el DNS local y no se versionan direcciones reales.

El diseno usa CSS y JavaScript locales: una cabecera editorial monocroma, cuadriculas responsivas y tarjetas compactas. No descarga fondos ni fuentes externos. La tarjeta opcional de camara NASA carga el reproductor externo de YouTube en el navegador; no se descarga ni retransmite el video desde el servidor.

### Camara oficial ISS de NASA

La tarjeta `Cámara ISS · NASA` integra el video enlazado actualmente desde
`https://eol.jsc.nasa.gov/ESRS/HDEV/`, con reproduccion manual y formato 16:9.
Es una visualizacion externa independiente: no alimenta el encoder, la musica
ni la emision de AstroLearner y no activa el selector experimental de camara.
El navegador contacta directamente con YouTube y sus proveedores de medios;
la disponibilidad, posibles avisos y material de respaldo dependen de NASA y
YouTube. Si falla, el titulo de la tarjeta abre la pagina oficial de NASA.

Solo el iframe utiliza `strict-origin-when-cross-origin` para identificar el
origen ante YouTube sin enviar rutas del portal. No se relajan las cabeceras
globales de Caddy, la autenticacion ni la exposicion de red. No utiliza OAuth,
claves, APIs de Google ni herramientas de extraccion. Si NASA sustituye el video,
verificar el nuevo enlace en su pagina y actualizar tambien la regla CSS
especifica. Comprobar reproduccion real desde el portal HTTPS: HTTP 200 no basta.

El grupo `Panel operativo` permanece plegado inicialmente. Al abrirlo, carga el dashboard autenticado con un intervalo relativo de seis horas y actualizacion automatica cada minuto.

## Monitorizacion

Uptime Kuma comprueba `https://portal.home.arpa` cada minuto y confia explicitamente en la autoridad local de Caddy. Una respuesta `200 OK` confirma que el portal responde; no garantiza por si sola que todos los servicios enlazados esten disponibles.

El temporizador `homelab-status.timer` genera un resumen con actividad SSH de las ultimas 24 horas, numero de clientes VPN activos, estado del ultimo backup y lecturas ambientales saneadas. El directorio del resumen se monta en Homepage como solo lectura y el widget `customapi` consulta `homelab-status/status.json` dentro del propio contenedor. Se monta el directorio, no el archivo individual, porque el exportador sustituye el JSON de forma atomica en cada actualizacion.

El control del directo se sirve como una página estática dentro del portal. Caddy
reenvía únicamente `/iss-live/control/*` al servicio local; el backend exige el
token de control o una sesión válida, y el origen `https://portal.home.arpa` para las operaciones
POST. La página confirma expresamente el inicio público y permite detener la
emisión. `ISS_LIVE_AUTO_START=false` protege frente a reinicios: el servicio
vuelve a simulación hasta que alguien pulse «Iniciar emisión pública». El modo
dry-run continúa bloqueando todos los controles de emisión.
