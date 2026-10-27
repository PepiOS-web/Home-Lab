# Copias de seguridad

## Objetivo

El servidor genera una copia cada madrugada. La revisión preparada el 15 de
octubre de 2026 conserva encendidos el emisor ISS y su navegador, identificados
por sus etiquetas Compose exactas y sus volúmenes esperados. Nunca los detiene
para hacer el backup. El resto de las aplicaciones mantiene una copia en parada.

Los archivos persistentes ISS se copian primero a un snapshot privado estable:
se comprueban inventarios antes/después, JSON de OAuth, WAV, manifiestos y hashes
NASA, propietarios, permisos y atributos extendidos. Si hay una generación o un
cambio concurrente, se reintenta; si no se obtiene una copia coherente, el backup
falla antes de detener otros servicios. No se archiva directamente el árbol ISS
activo ni se ignoran errores de `tar` para aparentar éxito.

AdGuard se detiene solo durante la copia de sus propios datos y se reinicia
antes de comprimir el archivo general. Así no permanece sin DNS durante toda la
copia. Una función `trap` intenta recuperar los demás contenedores que el backup
haya detenido incluso si falla; los errores de reinicio ya no se silencian.

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
2. Identifica los servicios activos y sus volúmenes sin imprimir credenciales.
   Conserva el emisor ISS y su navegador en marcha y prepara su snapshot estable.
3. Copia AdGuard con una parada breve y lo reinicia. Detiene las otras
   aplicaciones y genera un archivo temporal comprimido con los datos en parada
   y los snapshots, conservando las rutas originales de restauración.
4. Renombra el archivo solo cuando la compresion finaliza.
5. Reinicia los contenedores.
6. Genera y verifica una suma SHA-256.
7. Elimina copias diarias con mas de siete dias.

Se necesita instalar también el helper
`infrastructure/backup/homelab-backup-iss.py` como
`/usr/local/libexec/homelab-backup-iss.py`, propietario root y modo 0750. El script
principal comprueba ese permiso antes de empezar. Se usa un lock privado bajo
`/run/homelab-backup` para evitar ejecuciones simultáneas.

El snapshot temporal queda dentro del directorio privado de copias en el HDD,
no en el SSD: la biblioteca ISS actual ocupa unos 25 GiB. Se comprueba espacio
libre antes de parar servicios y se limpia únicamente el directorio exacto de
trabajo creado por `mktemp`. Esto añade lectura/escritura al backup; no equivale
a una garantía de rendimiento del directo durante toda la operación.

Se conservan música, títulos guardados, credenciales OAuth y vídeos/manifiestos
locales. Se excluyen únicamente los contenidos regenerables de `status/` y la
caché `nasa/epic/`, preservando directorios vacíos con sus propietarios/permisos
para que el servicio pueda reconstruirlos. Restaurar un backup no reanuda un
directo de YouTube ya terminado ni desactiva la política de inicio manual.

También se excluye el contenido regenerable de
`/srv/data/appdata/homelab-status`, actualizado por el recolector cada cinco
segundos: se conserva su directorio vacío con propietario, permisos y ACL en la
misma ruta de restauración. El script, servicio y temporizador del recolector
siguen incluidos; no se detiene su temporizador.

La instalación debe comparar el script real del servidor con la versión
anterior conocida antes de reemplazarlo, guardar una recuperación privada y
revisar las identidades reales. La prueba integral del próximo backup debe
confirmar que no cambian el PID/inicio del emisor ni el identificador público de
la emisión. Las pruebas unitarias no sustituyen esa verificación.

El servicio permite hasta 90 minutos para completar el archivo y verificar su
SHA-256. Una ejecución anterior alcanzó el límite de 30 minutos durante la
verificación y systemd la terminó; el resultado del servicio debe comprobarse
después de cada ejecución:

```bash
systemctl show homelab-backup.service -p TimeoutStartUSec -p Result -p ExecMainStatus
```

En el servidor existe un drop-in de systemd con el mismo límite de 90 minutos.
El archivo versionado y el drop-in se mantienen alineados para que futuras
instalaciones no vuelvan al límite anterior.

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

## Copia externa cifrada

Una segunda copia se almacena en el ordenador personal dentro de una carpeta sincronizada por OneDrive. Antes de entrar en esa carpeta, el archivo se verifica mediante SHA-256 y se incorpora a un repositorio cifrado con `restic`. El archivo temporal sin cifrar se elimina siempre al finalizar.

La transferencia usa una clave SSH cargada en `ssh-agent`. Un helper del servidor expone exclusivamente tres operaciones de solo lectura sobre el backup mas reciente: nombre, archivo y checksum. La regla `sudoers` no permite modificar ni eliminar copias.

El servidor mantiene su ejecucion diaria. El ordenador ejecuta la copia externa semanalmente y conserva siete snapshots semanales. La tarea utiliza `StartWhenAvailable`, por lo que una ejecucion perdida se inicia cuando el usuario vuelve a tener una sesion disponible.

La credencial automatica se protege localmente con DPAPI y no se guarda dentro del repositorio. La contrasena original de `restic` debe conservarse aparte en un gestor de contrasenas para permitir una restauracion desde otro equipo.

La primera restauracion externa recupero el archivo completo, permitio leer el `tar.gz` y confirmo la presencia de Caddy, Compose de monitorizacion, Homepage y OpenSSH.

## Limitaciones restantes

La copia externa protege frente a la averia del HDD del servidor. No protege si se pierde simultaneamente el servidor, el ordenador y la cuenta sincronizada, ni sustituye una restauracion integral periodica en hardware independiente. OneDrive solo debe recibir el repositorio cifrado, nunca los archivos `.tar.gz` originales.
