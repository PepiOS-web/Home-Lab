# Portal local

## Objetivo

Homepage ofrece una unica interfaz para abrir Grafana, Uptime Kuma, NetAlertX y la documentacion del proyecto. Homepage escucha en `127.0.0.1:8080` y Caddy lo publica como `https://portal.home.arpa`.

## Seguridad

- La imagen utiliza una version fijada.
- El contenedor usa un usuario sin privilegios y `no-new-privileges`.
- No se monta `/var/run/docker.sock`.
- No se configuran widgets con tokens o credenciales.
- `HOMEPAGE_ALLOWED_HOSTS` restringe los encabezados Host a `portal.home.arpa`.
- `disableIndexing` solicita a buscadores que no indexen la pagina.

El portal no debe exponerse directamente a Internet. Un despliegue remoto futuro requerira VPN o proxy inverso con autenticacion y TLS.

## Configuracion

Los archivos persistentes residen en `/srv/data/appdata/homepage` y el proyecto Compose en `/srv/data/compose/homepage`.

Antes del primer despliegue se copian los archivos de `config/` al directorio persistente. Los enlaces utilizan nombres `*.home.arpa`; su resolucion se configura en el DNS local y no se versionan direcciones reales.

## Monitorizacion

Uptime Kuma comprueba `https://portal.home.arpa` cada minuto y confia explicitamente en la autoridad local de Caddy. Una respuesta `200 OK` confirma que el portal responde; no garantiza por si sola que todos los servicios enlazados esten disponibles.
