# Mantenimiento manual del host

Revisión del 15 de octubre de 2026. El helper público
`infrastructure/maintenance/homelab-update` actualiza paquetes del host Ubuntu
24.04 en tres grupos: Ubuntu, Docker/containerd y Tailscale. No actualiza la
distribución, imágenes de aplicaciones, modelos ni dependencias Python. No
instala controladores gráficos alternativos ni modifica deliberadamente la
configuración de red, SSH, firewall o parámetros del directo. Los paquetes de
esos componentes sí pueden actualizarse. No reinicia.

## Antes de ejecutar

- Detener el directo desde el portal y no volver a iniciarlo durante el proceso.
- Esperar a que Factory de producción y staging no tengan trabajos en cola o
  procesándose. El script consulta solo el número de trabajos, no su contenido.
- Disponer de acceso local alternativo: Docker y Tailscale pueden interrumpirse.
- El backup diario debe haber terminado correctamente y tener menos de 24 horas.
  Se verifica su SHA-256; no equivale a una prueba integral de restauración.
- Se conserva una copia privada adicional de configuraciones actuales y del
  inventario de paquetes/IDs de imágenes. No es un snapshot completo del sistema
  ni garantiza que todas las versiones antiguas de paquetes sigan disponibles.

Ejecutar como tarea de systemd, no como un proceso atado a SSH. Tras copiar y
revisar el helper en el servidor:

```sh
sudo install -o root -g root -m 750 /tmp/homelab-update-prepared/homelab-update /usr/local/sbin/homelab-update
sudo systemd-run --unit=homelab-maintenance --property=Type=exec --property=RuntimeMaxSec=3h /usr/local/sbin/homelab-update apply
journalctl -u homelab-maintenance -f --no-pager
```

El directorio temporal concreto puede ser diferente; usar la ruta verificada
durante la preparación. `systemd-run` permite continuar si SSH se desconecta.
Los registros completos y archivos privados quedan en un directorio raíz 0700
bajo `/var/lib/homelab-maintenance` (padres controlados por root), nunca en Git
ni en una carpeta sincronizada.
El diario muestra únicamente progreso y resultados saneados.

Se refrescan índices, simulan cambios, rechazan eliminaciones y fijan las
versiones seleccionadas por `apt-get upgrade`, sin forzar actualizaciones
escalonadas. No se ejecuta autoremove ni se limpian imágenes/kernels. Se preservan
los archivos de configuración locales. Las aplicaciones arrancan con sus mismos
contenedores e imágenes; solo se reanudan las que estaban funcionando antes.
El temporizador de backup se pausa durante el mantenimiento para evitar una
parada concurrente y se restaura al terminar, también si falla. Si se perdió su
horario, su opción `Persistent` puede provocar un backup al reactivarlo: esperar
a su finalización antes de volver a emitir.

Si falla APT, se intenta restaurar únicamente los contenedores originales cuando
el motor siga disponible, sin cambiar imágenes ni arrancar la emisión. No se
garantiza recuperación automática de un motor/paquete roto; revisar con sudo el
registro y el inventario privado antes de nuevos comandos o reinicio.

## Después

Comprobar `Result` y `ExecMainStatus` de `homelab-maintenance.service`, el plan
restante, contenedores, DNS/HTTPS/SSH/Tailscale, cámaras y trabajos. Investigar
unidades fallidas previas sin ocultarlas con `reset-failed`. El fallo observado
de `systemd-networkd-wait-online` requiere una revisión separada; no se aplica
Netplan remotamente ni se cambia ese servicio durante el mantenimiento.

Planificar el reinicio pendiente solo después de esa revisión y verificar el
kernel cargado después. Con `AUTO_START=false`, el directo no se reanuda solo.
Las aplicaciones se actualizan posteriormente una a una, revisando versiones,
migraciones y restauración de sus datos, especialmente etiquetas mutables.

Referencias: [APT en Ubuntu](https://ubuntu.com/server/docs/how-to/software/package-management/),
[actualizar Docker](https://docs.docker.com/engine/install/ubuntu/#upgrade-docker-engine),
[actualizar Tailscale](https://tailscale.com/docs/features/client/update).
