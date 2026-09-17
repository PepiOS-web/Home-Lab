# Portal local

## Objetivo

Homepage ofrece una unica interfaz para abrir Grafana, Uptime Kuma, NetAlertX y la documentacion del proyecto. El portal se publica solamente en la direccion privada del servidor y UFW limita el acceso a la red local.

## Seguridad

- La imagen utiliza una version fijada.
- El contenedor usa un usuario sin privilegios y `no-new-privileges`.
- No se monta `/var/run/docker.sock`.
- No se configuran widgets con tokens o credenciales.
- `HOMEPAGE_ALLOWED_HOSTS` restringe los encabezados Host aceptados.
- `disableIndexing` solicita a buscadores que no indexen la pagina.

El portal no debe exponerse directamente a Internet. Un despliegue remoto futuro requerira VPN o proxy inverso con autenticacion y TLS.

## Configuracion

Los archivos persistentes residen en `/srv/data/appdata/homepage` y el proyecto Compose en `/srv/data/compose/homepage`. Las plantillas del repositorio sustituyen la direccion real por variables de entorno.

Antes del primer despliegue se copian los archivos de `config/` al directorio persistente y se crea un `.env` local a partir de `.env.example`. La direccion `192.0.2.10` de la plantilla pertenece a TEST-NET-1 y debe reemplazarse por la direccion privada del servidor. El archivo `.env` real no se versiona.

## Monitorizacion

Uptime Kuma comprueba el portal mediante HTTP cada minuto. Una respuesta `200 OK` confirma que el servicio web responde; no garantiza por si sola que todos los servicios enlazados esten disponibles.
