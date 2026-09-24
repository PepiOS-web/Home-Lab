# Copias de seguridad

## Objetivo

El servidor genera una copia consistente cada madrugada. Antes de archivar los datos detiene temporalmente los contenedores que escriben en disco y los inicia nuevamente al terminar. Una funcion registrada con `trap` intenta reiniciarlos incluso cuando el proceso falla.

## Contenido

- Datos persistentes de Grafana, Prometheus, Uptime Kuma, NetAlertX, Homepage, AdGuard Home y Caddy.
- Proyectos Docker Compose.
- Recolector de temperaturas.
- Script, servicio y temporizador de backup.
- Servicio y temporizador de temperaturas.
- Colector saneado del portal y su servicio y temporizador.
- Exportador de metricas operativas para Prometheus y Grafana.
- Configuracion de OpenSSH y sus fragmentos de endurecimiento.
- Reglas persistentes de UFW.
- Configuracion de reenvio IP necesaria para la ruta restringida de Tailscale.
- Repositorio firmado y llavero publico usados para instalar Tailscale.
- Configuracion conservadora de actualizaciones automaticas de seguridad.

Los archivos contienen datos privados y nunca deben publicarse ni compartirse sin cifrado.

La copia contiene la autoridad privada y las claves TLS de Caddy. Se crea con `umask 077`, directorio `0700` y archivos `0600`. Perderla impide recuperar la misma cadena de confianza; divulgarla permitiria suplantar servicios internos.

El estado `/var/lib/tailscale` se excluye deliberadamente porque contiene la identidad privada del nodo. Despues de una restauracion, Tailscale debe instalarse, autenticarse y aprobarse como un dispositivo nuevo.

## Ejecucion

El temporizador de systemd ejecuta `homelab-backup.service` diariamente. El script:

1. Crea el directorio con permisos restrictivos.
2. Detiene los servicios con datos persistentes.
3. Genera un archivo temporal comprimido.
4. Renombra el archivo solo cuando la compresion finaliza.
5. Reinicia los contenedores.
6. Genera y verifica una suma SHA-256.
7. Elimina copias diarias con mas de siete dias.

## Comprobaciones

```bash
systemctl status homelab-backup.timer --no-pager
systemctl list-timers --all | grep homelab-backup
sudo systemctl start homelab-backup.service
systemctl status homelab-backup.service --no-pager
sudo journalctl -u homelab-backup.service -n 40 --no-pager
sudo ls -lh /srv/data/backups/daily
```

Un servicio `oneshot` aparece como `inactive (dead)` despues de finalizar correctamente. La propiedad importante es `status=0/SUCCESS`.

## Prueba de restauracion

La integridad criptografica y el listado del archivo no sustituyen una prueba de restauracion. Periodicamente se realiza una extraccion parcial en un directorio temporal dentro del area de backups, sin detener ni sobrescribir el servidor activo.

La prueba comprueba:

- extraccion de proyectos Compose, SSH, UFW, unidades y scripts;
- sintaxis del script principal de backup;
- compilacion del colector Python del portal;
- validacion de las unidades de systemd;
- validacion de todos los archivos `compose.yaml` mediante `docker compose config --quiet`;
- presencia de la politica SSH endurecida.

El directorio temporal solo se elimina despues de resolver su ruta absoluta y confirmar que coincide con `/srv/data/backups/restore-test.*`. El archivo original y su suma SHA-256 permanecen intactos.

La primera prueba parcial finalizo correctamente. Esto demuestra que las configuraciones esenciales pueden extraerse y analizarse, aunque no sustituye una restauracion integral en hardware independiente.

## Limitacion actual

Estas copias protegen frente a borrados accidentales, errores de configuracion y corrupcion logica, pero residen en el mismo HDD que los datos originales. No protegen frente a averia, robo o dano fisico. La siguiente mejora sera replicarlas cifradas en otro dispositivo o ubicacion.
