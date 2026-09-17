# Copias de seguridad

## Objetivo

El servidor genera una copia consistente cada madrugada. Antes de archivar los datos detiene temporalmente los contenedores que escriben en disco y los inicia nuevamente al terminar. Una funcion registrada con `trap` intenta reiniciarlos incluso cuando el proceso falla.

## Contenido

- Datos persistentes de Grafana, Prometheus, Uptime Kuma, NetAlertX, Homepage y Caddy.
- Proyectos Docker Compose.
- Recolector de temperaturas.
- Script, servicio y temporizador de backup.
- Servicio y temporizador de temperaturas.

Los archivos contienen datos privados y nunca deben publicarse ni compartirse sin cifrado.

La copia contiene la autoridad privada y las claves TLS de Caddy. Se crea con `umask 077`, directorio `0700` y archivos `0600`. Perderla impide recuperar la misma cadena de confianza; divulgarla permitiria suplantar servicios internos.

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

## Limitacion actual

Estas copias protegen frente a borrados accidentales, errores de configuracion y corrupcion logica, pero residen en el mismo HDD que los datos originales. No protegen frente a averia, robo o dano fisico. La siguiente mejora sera replicarlas cifradas en otro dispositivo o ubicacion.
